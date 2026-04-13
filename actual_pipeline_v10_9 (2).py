# V3: Overflow ayarları
'overflow': {
    'donors': ['gold', 'kurumsal'],   # fazlalığını kitleye veren kuyruklar
    'receiver': 'kitle',               # overflow alan kuyruk
},


from actual_pipeline_v3_weekday import *

results = run_all_queues(df_calls, df_actual, df_shifts_dict, '2025-02-17', config=CONFIG)


# =============================================================================
# KUYRUK BAZLI VARDIYA PİPELİNE - ACTUAL V3 (WEEKDAY)
# =============================================================================
#
# V3 (sadece HAFTAİÇİ):
#   - V2 üzerine kurulu, gold/kurumsal overflow yaklaşımı eklendi
#   - Akış:
#       1) Gold & Kurumsal Erlang hesapla
#       2) Gold & Kurumsal MIP → minimum ihtiyaç (sadece inhouse)
#       3) Gold & Kurumsal fazlalık hesapla (atanan - erlang) → overflow
#       4) Kitle Erlang hesapla
#       5) Kitle net ihtiyaç = kitle_erlang - overflow (slot bazlı)
#       6) Kitle MIP → net ihtiyaçla çalış (daha az kişi atar)
#       7) Surplus dağıtımı (her kuyruk kendi kadrosundan)
#       8) Rapor
#   - Gold/kurumsal agentlar boşta kalınca kitle çağrılarını karşılar
#     (haftaiçine özel operasyonel gerçek)
#
# =============================================================================

import pandas as pd
import numpy as np
import math
import calendar
import copy
from pulp import *

# CONFIG dışarıdan gelir (Jupyter'da ayrı hücre veya import)


# =============================================================================
# 0. AHT YÜKLEME
# =============================================================================

def load_aht_from_df(df_aht, config=CONFIG):
    required_cols = ['saat', 'sub_queue', 'line_based_main_group', 'weighted_avg_aht']
    missing = [c for c in required_cols if c not in df_aht.columns]
    if missing:
        raise ValueError(f"df_aht'de eksik kolonlar: {missing}")

    main_queue_map = {
        qcfg['actual_name']: qkey
        for qkey, qcfg in config['queues'].items()
    }

    sub_queues_cfg = {}

    for main_group, queue_key in main_queue_map.items():
        df_q = df_aht[df_aht['line_based_main_group'] == main_group]
        if len(df_q) == 0:
            print(f"   ⚠ {main_group} için AHT verisi bulunamadı")
            continue

        sub_queues_cfg[queue_key] = {'queues': [], 'aht': {}}

        for sq in sorted(df_q['sub_queue'].unique()):
            sub_queues_cfg[queue_key]['queues'].append(sq)
            df_sq = df_q[df_q['sub_queue'] == sq].copy()
            aht_dict = dict(zip(df_sq['saat'].astype(int), df_sq['weighted_avg_aht'].astype(int)))
            aht_dict['default'] = int(df_sq['weighted_avg_aht'].mean())
            sub_queues_cfg[queue_key]['aht'][sq] = aht_dict

        print(f"   ✓ {queue_key}: {len(sub_queues_cfg[queue_key]['queues'])} alt kuyruk yüklendi "
              f"({', '.join(sub_queues_cfg[queue_key]['queues'])})")

    return sub_queues_cfg


# =============================================================================
# YARDIMCI
# =============================================================================

SLOTS_30 = [f"{h:02d}:{m}" for h in range(24) for m in ['00', '30']]


def get_weekends(year, month):
    month_names = {
        'ocak': 1, 'şubat': 2, 'mart': 3, 'nisan': 4,
        'mayıs': 5, 'haziran': 6, 'temmuz': 7, 'ağustos': 8,
        'eylül': 9, 'ekim': 10, 'kasım': 11, 'aralık': 12,
        'january': 1, 'february': 2, 'march': 3, 'april': 4,
        'may': 5, 'june': 6, 'july': 7, 'august': 8,
        'september': 9, 'october': 10, 'november': 11, 'december': 12
    }
    if isinstance(month, str):
        month_lower = month.lower().strip()
        if month_lower not in month_names:
            raise ValueError(f"Geçersiz ay adı: {month}")
        month = month_names[month_lower]

    weekends = []
    cal = calendar.Calendar()
    for day in cal.itermonthdates(year, month):
        if day.month == month and day.weekday() >= 5:
            weekends.append(day.strftime('%Y-%m-%d'))
    return weekends


def is_slot_in_shift(slot, start, end):
    if start <= end:
        return start <= slot < end
    else:
        return slot >= start or slot < end


def get_part_time_availability(target_date, config=CONFIG):
    pt_config = config.get('part_time', {})
    if not pt_config.get('enabled', False):
        return {q: 0 for q in config['queues']}
    pt_counts = pt_config.get('count', {})
    return {q: pt_counts.get(q, 0) for q in config['queues']}


def get_part_time_shifts(config=CONFIG):
    pt_config = config.get('part_time', {})
    if not pt_config.get('enabled', False):
        return []
    shifts = []
    for shift_str in pt_config.get('shifts', []):
        start, end = shift_str.split('-')
        slots = [slot for slot in SLOTS_30 if is_slot_in_shift(slot, start, end)]
        shifts.append({
            'start': start, 'end': end, 'slots': slots,
            'key': f"pt_{start.replace(':', '')}_{end.replace(':', '')}"
        })
    return shifts


def get_time_cost_multiplier(queue, company_type, start_hour, config=CONFIG):
    time_mults_all = config.get('time_cost_multipliers', {})
    time_mults = time_mults_all.get(queue, time_mults_all.get('default', {}))
    return time_mults.get(company_type, {}).get(start_hour, 1.0)


# =============================================================================
# 1. VERİ HAZIRLAMA
# =============================================================================

def get_sub_queue_aht(queue, sub_queue, slot, config=CONFIG):
    sub_cfg = config['sub_queues'].get(queue, {})
    aht_cfg = sub_cfg.get('aht', {}).get(sub_queue, {})
    hour = int(slot.split(':')[0])
    if hour in aht_cfg:
        return aht_cfg[hour]
    if 'default' in aht_cfg:
        return aht_cfg['default']
    return config.get('default_aht', 150)


def calculate_weighted_aht(row, queue, slot, config=CONFIG):
    overrides = config.get('aht_overrides', {}).get(queue, {})
    if overrides:
        hour = int(slot[:2])
        if hour in overrides:
            return overrides[hour]

    sub_cfg = config['sub_queues'].get(queue, {})
    sub_queues = sub_cfg.get('queues', [])

    total_calls = 0
    weighted_sum = 0

    for sq in sub_queues:
        col = f"{sq}_calls"
        if col in row.index:
            calls = row[col]
            if pd.notna(calls) and calls > 0:
                aht = get_sub_queue_aht(queue, sq, slot, config)
                weighted_sum += calls * aht
                total_calls += calls

    if total_calls > 0:
        return round(weighted_sum / total_calls, 1)
    else:
        if sub_queues:
            ahts = [get_sub_queue_aht(queue, sq, slot, config) for sq in sub_queues]
            return round(sum(ahts) / len(ahts), 1)
        return config.get('default_aht', 150)


def prepare_calls_30(df_calls, config=CONFIG):
    col = config['calls_columns']
    sub_queues_cfg = config['sub_queues']

    main_queue_map = {
        qcfg['actual_name']: qkey
        for qkey, qcfg in config['queues'].items()
    }

    df = df_calls.copy()
    df[col['date']] = pd.to_datetime(df[col['date']])

    time_str = df[col['time']].astype(str)
    hour = time_str.str.split(':').str[0].astype(int)
    minute = time_str.str.split(':').str[1].astype(int)
    df['slot_30'] = hour.astype(str).str.zfill(2) + ':' + \
                    ((minute // 30) * 30).astype(str).str.zfill(2)

    df['queue_key'] = df[col['main_queue']].map(main_queue_map)
    df = df[df['queue_key'].notna()].copy()

    base = df.groupby([col['date'], 'slot_30']).size().reset_index()[[col['date'], 'slot_30']]
    base = base.rename(columns={col['date']: 'data_date'})

    for queue_key, sq_cfg in sub_queues_cfg.items():
        actual_name = config['queues'][queue_key]['actual_name']
        sub_queues = sq_cfg['queues']
        df_q = df[df[col['main_queue']] == actual_name]

        for sq in sub_queues:
            df_sq = df_q[df_q[col['sub_queue']] == sq].copy()
            sq_30 = df_sq.groupby([col['date'], 'slot_30'])[col['calls']].sum().reset_index()
            sq_30 = sq_30.rename(columns={col['date']: 'data_date', col['calls']: f"{sq}_calls"})
            base = base.merge(sq_30, on=['data_date', 'slot_30'], how='left')
            base[f"{sq}_calls"] = base[f"{sq}_calls"].fillna(0)

        total_30 = df_q.groupby([col['date'], 'slot_30'])[col['calls']].sum().reset_index()
        total_30 = total_30.rename(columns={col['date']: 'data_date', col['calls']: f"{queue_key}_total"})
        base = base.merge(total_30, on=['data_date', 'slot_30'], how='left')
        base[f"{queue_key}_total"] = base[f"{queue_key}_total"].fillna(0)

    for queue_key, qcfg in config['queues'].items():
        total_col = f"{queue_key}_total"
        if total_col not in base.columns:
            actual_name = qcfg['actual_name']
            df_q = df[df[col['main_queue']] == actual_name]
            if len(df_q) > 0:
                total_30 = df_q.groupby([col['date'], 'slot_30'])[col['calls']].sum().reset_index()
                total_30 = total_30.rename(columns={col['date']: 'data_date', col['calls']: total_col})
                base = base.merge(total_30, on=['data_date', 'slot_30'], how='left')
                base[total_col] = base[total_col].fillna(0)
            else:
                base[total_col] = 0

    return base.sort_values(['data_date', 'slot_30']).reset_index(drop=True)


def add_30min(time_str):
    h, m = int(time_str[:2]), int(time_str[3:5])
    m += 30
    if m >= 60:
        m -= 60
        h = (h + 1) % 24
    return f"{h:02d}:{m:02d}"


def prepare_actual(df_actual, config=CONFIG):
    col = config['actual_columns']
    df = df_actual.copy()
    df[col['date']] = pd.to_datetime(df[col['date']], dayfirst=True)
    df[col['shift_start']] = df[col['shift_start']].astype(str).str.strip().str[:5]
    df[col['shift_end']] = df[col['shift_end']].astype(str).str.strip().str[:5]
    mask_out = df[col['outsource']] == 1
    df.loc[mask_out, col['shift_end']] = df.loc[mask_out, col['shift_end']].apply(add_30min)
    return df


# =============================================================================
# 2. ERLANG-C
# =============================================================================

def erlang_c(agents, traffic):
    if agents <= traffic or agents == 0:
        return 1.0
    eb = traffic / agents
    for i in range(2, int(agents) + 1):
        eb = (traffic * eb) / (i + traffic * eb)
    return min(eb / (1 - (traffic / agents) * (1 - eb)), 1.0)


def calc_asa(agents, traffic, aht):
    if agents <= traffic or agents == 0:
        return 999
    ec = erlang_c(agents, traffic)
    return (ec * (aht / 60)) / (agents - traffic) * 60


def find_optimal_agents(calls, aht, slot, queue, config=CONFIG):
    ecfg = config['queue_configs'][queue]['erlang']
    if calls == 0:
        return 0, 0, 0

    traffic = (calls * (aht / 60)) / ecfg['interval_minutes']
    if traffic == 0:
        return 0, 0, 0

    min_a = math.ceil(traffic)
    max_a = math.ceil(traffic * 3) + 10

    raw = max_a
    for a in range(min_a, max_a + 1):
        if calc_asa(a, traffic, aht) <= ecfg['target_asa']:
            raw = a
            break

    hour = int(slot[:2])
    shrinkage_cfg = ecfg['shrinkage']
    if isinstance(shrinkage_cfg, dict):
        shrinkage = shrinkage_cfg.get(hour, shrinkage_cfg.get('default', 0.10))
    else:
        shrinkage = shrinkage_cfg

    final = math.ceil(raw / (1 - shrinkage))
    asa = calc_asa(raw, traffic, aht)
    return final, round(asa, 1), round(raw, 0)


def calculate_erlang_all(df_calls_30, config=CONFIG):
    results = []
    for _, row in df_calls_30.iterrows():
        date = row['data_date']
        slot = row['slot_30']
        for queue, qcfg in config['queues'].items():
            total_col = f"{queue}_total"
            calls = row.get(total_col, 0)
            if pd.isna(calls):
                calls = 0
            weighted_aht = calculate_weighted_aht(row, queue, slot, config)
            need, asa, _ = find_optimal_agents(calls, weighted_aht, slot, queue, config)
            results.append({
                'date': date, 'slot': slot, 'queue': queue,
                'label': qcfg['label'], 'calls': int(calls),
                'weighted_aht': weighted_aht, 'erlang_need': need, 'asa': asa
            })
    return pd.DataFrame(results)


# =============================================================================
# 3. MIP OPTİMİZASYON
# =============================================================================

def create_shift_coverage(df_shifts, config=CONFIG):
    scol = config['shift_columns']
    cov = {}
    for _, row in df_shifts.iterrows():
        shift = row[scol['shift']]
        start = str(row[scol['start']])[:5]
        end = str(row[scol['end']])[:5]
        company = row[scol['company']]
        key = f"{shift}_{company}"
        slots = [s for s in SLOTS_30 if is_slot_in_shift(s, start, end)]
        cov[key] = {'shift': shift, 'company': company,
                    'start': start, 'end': end, 'slots': slots}
    return cov


def optimize_queue(erlang_by_slot, df_shifts, queue,
                   target_date=None, inhouse_min_by_slot=None,
                   outsource_min_by_slot=None, config=None,
                   overflow_by_slot=None):
    """
    V3: overflow_by_slot parametresi eklendi.
    Eğer verilirse, her slottaki coverage kısıtından overflow düşülür:
       atanan + overflow >= erlang
    yani: atanan >= erlang - overflow
    """

    if config is None:
        config = CONFIG

    qcfg = config['queues'][queue]
    qconfigs = config['queue_configs'][queue]
    mcfg = qconfigs['mip']
    scol = config['shift_columns']
    ccfg = config['company']

    allowed = qcfg['companies']
    allowed_values = [ccfg[c]['shift_value'] for c in allowed]

    df_sf = df_shifts[df_shifts[scol['company']].isin(allowed_values)]
    shift_cov = create_shift_coverage(df_sf, config)

    only_inhouse = (allowed == ['inhouse'])

    shifts = list(shift_cov.keys())
    active_slots = [s for s in SLOTS_30 if erlang_by_slot.get(s, 0) > 0]

    inhouse_value = ccfg['inhouse']['shift_value']
    outsource_value = ccfg['outsource']['shift_value']
    in_shifts = [s for s in shifts if shift_cov[s]['company'] == inhouse_value]
    out_shifts = [s for s in shifts if shift_cov[s]['company'] == outsource_value]

    if not active_slots:
        return None, "İhtiyaç yok"

    # Part-time
    pt_available = 0
    pt_shift_keys = []

    if target_date is not None and config.get('part_time', {}).get('enabled', False):
        pt_availability = get_part_time_availability(target_date, config)
        pt_available = pt_availability.get(queue, 0)

        if pt_available > 0:
            pt_shifts_list = get_part_time_shifts(config)
            for pt in pt_shifts_list:
                pt_shift_keys.append(pt['key'])
                shift_cov[pt['key']] = {
                    'shift': pt['key'], 'company': 'part_time',
                    'start': pt['start'], 'end': pt['end'], 'slots': pt['slots']
                }
            shifts = list(shift_cov.keys())

    prob = LpProblem(f"Q_{queue}", LpMinimize)

    x = LpVariable.dicts("x", shifts, lowBound=0, cat='Integer')
    y = LpVariable.dicts("y", shifts, cat='Binary')

    cost = []
    cost_details = []

    ssp_cfg = qconfigs.get('small_shift_penalty', {})
    ssp_enabled = ssp_cfg.get('enabled', False)
    ssp_penalty = ssp_cfg.get('penalty', 3.0)

    rr_cfg = qconfigs.get('rr_penalty', {})
    rr_enabled = rr_cfg.get('enabled', False)
    rr_penalty_per = rr_cfg.get('penalty_per_person', 5.0)
    rr_peak_exempt = rr_cfg.get('peak_exempt', True)
    rr_peak_thr = rr_cfg.get('peak_threshold', 0.70)

    night_mult_cfg = rr_cfg.get('night_multiplier', {})
    night_mult_enabled = night_mult_cfg.get('enabled', False)
    night_mult_value = night_mult_cfg.get('multiplier', 3.0)
    night_mult_start = night_mult_cfg.get('hours', {}).get('start', '22:00')
    night_mult_end = night_mult_cfg.get('hours', {}).get('end', '08:00')

    def _is_night_slot(slot):
        return is_slot_in_shift(slot, night_mult_start, night_mult_end)

    # Maliyet
    for s in shifts:
        start_hour = shift_cov[s]['start']

        if s in pt_shift_keys:
            base_cost = mcfg['cost_inhouse']
            company_type = 'part_time'
            multiplier = get_time_cost_multiplier(queue, 'inhouse', start_hour, config)
        elif shift_cov[s]['company'] == inhouse_value:
            base_cost = mcfg['cost_inhouse']
            company_type = 'inhouse'
            multiplier = get_time_cost_multiplier(queue, company_type, start_hour, config)
        else:
            base_cost = mcfg['cost_outsource']
            company_type = 'outsource'
            multiplier = get_time_cost_multiplier(queue, company_type, start_hour, config)

        final_cost = base_cost * multiplier
        cost.append(x[s] * final_cost)

        if ssp_enabled and s not in pt_shift_keys:
            cost.append(y[s] * ssp_penalty)

        if multiplier != 1.0:
            cost_details.append({
                'shift': s, 'company': company_type,
                'start': start_hour, 'base_cost': base_cost,
                'multiplier': multiplier, 'final_cost': final_cost
            })

    # RR penalty
    excess = {}
    peak_slots_rr = set()

    if rr_enabled and active_slots:
        max_erlang = max(erlang_by_slot.get(s, 0) for s in active_slots)
        if rr_peak_exempt and max_erlang > 0:
            peak_slots_rr = {s for s in active_slots
                             if erlang_by_slot.get(s, 0) >= max_erlang * rr_peak_thr}

        peak_penalty_per = rr_cfg.get('peak_penalty', rr_penalty_per)

        for slot in active_slots:
            erlang_need = erlang_by_slot.get(slot, 0)
            if erlang_need <= 0:
                continue

            excess[slot] = LpVariable(f"excess_{slot}", lowBound=0, cat='Continuous')

            covering = [s for s in shifts if slot in shift_cov[s]['slots']]
            if covering:
                prob += excess[slot] >= lpSum([x[s] for s in covering]) - erlang_need

            if slot in peak_slots_rr:
                effective_penalty = peak_penalty_per
            elif night_mult_enabled and _is_night_slot(slot):
                effective_penalty = rr_penalty_per * night_mult_value
            else:
                effective_penalty = rr_penalty_per

            cost.append(excess[slot] * effective_penalty)

    # Slot cap
    sc_cfg = qconfigs.get('slot_cap', {})
    slot_cap_detail = []
    sc_excess = {}

    if sc_cfg.get('enabled', False):
        bands = sc_cfg.get('bands', [])
        for slot in active_slots:
            erlang_need = erlang_by_slot.get(slot, 0)
            if erlang_need <= 0:
                continue
            matched_band = None
            for band in bands:
                if is_slot_in_shift(slot, band['start'], band['end']):
                    matched_band = band
                    break
            if matched_band is None:
                continue
            band_ratio = matched_band.get('max_ratio', 1.20)
            band_penalty = matched_band.get('penalty', 50.0)
            cap = max(math.ceil(erlang_need * band_ratio), 3)
            sc_excess[slot] = LpVariable(f"sc_excess_{slot}", lowBound=0, cat='Continuous')
            covering = [s for s in shifts if slot in shift_cov[s]['slots']]
            if covering:
                prob += sc_excess[slot] >= lpSum([x[s] for s in covering]) - cap
            cost.append(sc_excess[slot] * band_penalty)
            slot_cap_detail.append({
                'slot': slot, 'erlang': erlang_need, 'cap': cap,
                'ratio': band_ratio, 'penalty': band_penalty,
                'band': f"{matched_band['start']}-{matched_band['end']}"
            })

    prob += lpSum(cost)

    # ---- COVERAGE KISITI (V3: overflow düşülür) ----
    overflow_used_by_slot = {}
    for slot in active_slots:
        covering = [s for s in shifts if slot in shift_cov[s]['slots']]
        if covering:
            erlang_need = erlang_by_slot[slot]
            overflow = 0
            if overflow_by_slot:
                overflow = overflow_by_slot.get(slot, 0)
            net_need = max(0, erlang_need - overflow)
            overflow_used_by_slot[slot] = min(overflow, erlang_need)
            prob += lpSum([x[s] for s in covering]) >= net_need

    # Shift min/max
    M = 500
    for s in shifts:
        prob += x[s] <= M * y[s]
        prob += x[s] >= mcfg['min_per_shift'] * y[s]

    # Part-time
    if pt_available > 0 and pt_shift_keys:
        prob += lpSum([x[s] for s in pt_shift_keys]) == pt_available

    # Outsource oran kısıtı
    out_cfg = config['outsource_ratio'].get(queue)
    if not only_inhouse and out_cfg:
        t_in = lpSum([x[s] for s in in_shifts]) + lpSum([x[s] for s in pt_shift_keys])
        t_out = lpSum([x[s] for s in out_shifts])
        prob += (1 - out_cfg['min']) * t_out >= out_cfg['min'] * t_in
        prob += (1 - out_cfg['max']) * t_out <= out_cfg['max'] * t_in

    # Inhouse min kısıtları
    if inhouse_min_by_slot:
        for slot, min_in in inhouse_min_by_slot.items():
            if min_in > 0:
                covering_in = [s for s in in_shifts if slot in shift_cov[s]['slots']]
                covering_pt = [s for s in pt_shift_keys if slot in shift_cov[s]['slots']]
                covering_all_in = covering_in + covering_pt
                if covering_all_in:
                    prob += lpSum([x[s] for s in covering_all_in]) >= min_in

    # Outsource min kısıtları
    if outsource_min_by_slot:
        for slot, min_out in outsource_min_by_slot.items():
            if min_out > 0:
                covering_out = [s for s in out_shifts if slot in shift_cov[s]['slots']]
                if covering_out:
                    prob += lpSum([x[s] for s in covering_out]) >= min_out

    # ---- KADRO TAVANI ----
    kadro_cfg = config.get('surplus_distribution', {}).get('total_kadro', {}).get(queue, {})
    kadro_in = kadro_cfg.get('inhouse', 0)
    if kadro_in > 0 and in_shifts:
        prob += lpSum([x[s] for s in in_shifts]) <= kadro_in

    # ---- START SMOOTHING ----
    sm_cfg = qconfigs.get('start_smoothing', {})
    if sm_cfg.get('enabled', False):
        sm_hours = sm_cfg.get('hours', {'start': '07:00', 'end': '20:00'})
        sm_companies = sm_cfg.get('companies', ['inhouse', 'outsource'])
        sm_penalty = sm_cfg.get('penalty_per_diff', 0.5)
        sm_start = sm_hours.get('start', '07:00')
        sm_end = sm_hours.get('end', '20:00')

        for comp in sm_companies:
            if comp == 'inhouse':
                comp_shifts = in_shifts
            elif comp == 'outsource':
                comp_shifts = out_shifts
            else:
                continue
            if not comp_shifts:
                continue
            starts_by_hour = {}
            for s in comp_shifts:
                start_str = shift_cov[s]['start']
                if sm_start <= start_str < sm_end:
                    starts_by_hour.setdefault(start_str, []).append(s)
            sorted_hours = sorted(starts_by_hour.keys())
            if len(sorted_hours) < 2:
                continue
            for i in range(1, len(sorted_hours)):
                h_prev = sorted_hours[i - 1]
                h_curr = sorted_hours[i]
                starts_prev = lpSum([x[s] for s in starts_by_hour[h_prev]])
                starts_curr = lpSum([x[s] for s in starts_by_hour[h_curr]])
                diff_pos = LpVariable(f"sm_{comp}_{h_curr}_pos", lowBound=0, cat='Continuous')
                diff_neg = LpVariable(f"sm_{comp}_{h_curr}_neg", lowBound=0, cat='Continuous')
                prob += diff_pos - diff_neg == starts_curr - starts_prev
                cost.append((diff_pos + diff_neg) * sm_penalty)
        prob.objective = lpSum(cost)

    prob.solve(PULP_CBC_CMD(msg=0))

    if LpStatus[prob.status] != 'Optimal':
        return None, LpStatus[prob.status]

    assignments = {s: int(value(x[s])) for s in shifts if value(x[s]) and value(x[s]) > 0}

    mip_by_slot = {}
    mip_in_by_slot = {}
    mip_out_by_slot = {}
    mip_pt_by_slot = {}

    for slot in SLOTS_30:
        mip_by_slot[slot] = sum(assignments.get(s, 0) for s in shifts if slot in shift_cov[s]['slots'])
        mip_in_by_slot[slot] = sum(assignments.get(s, 0) for s in in_shifts if slot in shift_cov[s]['slots'])
        mip_out_by_slot[slot] = sum(assignments.get(s, 0) for s in out_shifts if slot in shift_cov[s]['slots'])
        mip_pt_by_slot[slot] = sum(assignments.get(s, 0) for s in pt_shift_keys if slot in shift_cov[s]['slots'])

    total_in = sum(assignments.get(s, 0) for s in in_shifts)
    total_out = sum(assignments.get(s, 0) for s in out_shifts)
    total_pt = sum(assignments.get(s, 0) for s in pt_shift_keys) if pt_shift_keys else 0
    total = total_in + total_out + total_pt
    out_ratio = total_out / total if total > 0 else 0

    # Early starts
    early_starts = {}
    early_total = 0
    early_penalty = 0
    for s, cnt in assignments.items():
        start_h = shift_cov[s]['start']
        if s in pt_shift_keys:
            company_type = 'part_time'
            mult = get_time_cost_multiplier(queue, 'inhouse', start_h, config)
        elif shift_cov[s]['company'] == inhouse_value:
            company_type = 'inhouse'
            mult = get_time_cost_multiplier(queue, company_type, start_h, config)
        else:
            company_type = 'outsource'
            mult = get_time_cost_multiplier(queue, company_type, start_h, config)
        if mult > 1.0:
            early_starts[s] = {
                'count': cnt, 'start': start_h,
                'company': company_type, 'multiplier': mult,
                'penalty': cnt * (mult - 1.0)
            }
            early_total += cnt
            early_penalty += cnt * (mult - 1.0)

    # Small shift
    small_shift_count = 0
    small_shift_total_penalty = 0
    small_shifts_detail = []
    if ssp_enabled:
        for s, cnt in assignments.items():
            if s in pt_shift_keys:
                continue
            small_shift_count += 1
            small_shift_total_penalty += ssp_penalty
            if cnt <= 5:
                small_shifts_detail.append({
                    'shift': s, 'count': cnt,
                    'start': shift_cov[s]['start'],
                    'company': shift_cov[s]['company']
                })

    # RR excess
    rr_excess_by_slot = {}
    rr_total_excess = 0
    rr_total_penalty_cost = 0
    rr_penalized_slots = 0

    if rr_enabled and excess:
        peak_penalty_per = rr_cfg.get('peak_penalty', rr_penalty_per)
        for slot, exc_var in excess.items():
            exc_val = value(exc_var) or 0
            if exc_val > 0.5:
                exc_int = int(round(exc_val))
                rr_excess_by_slot[slot] = exc_int
                rr_total_excess += exc_int
                if slot in peak_slots_rr:
                    rr_total_penalty_cost += exc_int * peak_penalty_per
                elif night_mult_enabled and _is_night_slot(slot):
                    rr_total_penalty_cost += exc_int * rr_penalty_per * night_mult_value
                else:
                    rr_total_penalty_cost += exc_int * rr_penalty_per
                rr_penalized_slots += 1

    # Slot cap excess
    sc_total_excess = 0
    sc_total_penalty_cost = 0
    sc_penalized_slots = 0

    if sc_cfg.get('enabled', False) and sc_excess:
        for slot, exc_var in sc_excess.items():
            exc_val = value(exc_var) or 0
            if exc_val > 0.5:
                exc_int = int(round(exc_val))
                slot_pen = 50.0
                for d in slot_cap_detail:
                    if d['slot'] == slot:
                        slot_pen = d['penalty']
                        break
                sc_total_excess += exc_int
                sc_total_penalty_cost += exc_int * slot_pen
                sc_penalized_slots += 1

    info = {
        'assignments': assignments,
        'shift_coverage': shift_cov,
        'mip_by_slot': mip_by_slot,
        'mip_in_by_slot': mip_in_by_slot,
        'mip_out_by_slot': mip_out_by_slot,
        'mip_pt_by_slot': mip_pt_by_slot,
        'total_kisi': total,
        'total_inhouse_kisi': total_in,
        'total_outsource_kisi': total_out,
        'total_part_time_kisi': total_pt,
        'pt_available': pt_available,
        'outsource_ratio': out_ratio,
        'cost_details': cost_details,
        'early_starts': early_starts,
        'early_total': early_total,
        'early_penalty': early_penalty,
        'inhouse_min_by_slot': inhouse_min_by_slot or {},
        'outsource_min_by_slot': outsource_min_by_slot or {},
        'overflow_by_slot': overflow_by_slot or {},
        'overflow_used_by_slot': overflow_used_by_slot,
        'small_shift_penalty_enabled': ssp_enabled,
        'small_shift_count': small_shift_count,
        'small_shift_total_penalty': small_shift_total_penalty,
        'small_shifts_detail': small_shifts_detail,
        'rr_penalty_enabled': rr_enabled,
        'rr_excess_by_slot': rr_excess_by_slot,
        'rr_total_excess': rr_total_excess,
        'rr_total_penalty_cost': rr_total_penalty_cost,
        'rr_penalized_slots': rr_penalized_slots,
        'rr_peak_slots': peak_slots_rr,
        'slot_cap_detail': slot_cap_detail,
        'sc_total_excess': sc_total_excess,
        'sc_total_penalty_cost': sc_total_penalty_cost,
        'sc_penalized_slots': sc_penalized_slots,
    }

    return assignments, info


# =============================================================================
# 4. GERÇEK VERİ
# =============================================================================

def get_actual_summary(df_actual, date, queue, config=CONFIG):
    col = config['actual_columns']
    actual_name = config['queues'][queue]['actual_name']

    df = prepare_actual(df_actual, config)
    df_day = df[(df[col['date']] == pd.to_datetime(date)) & (df[col['queue']] == actual_name)]

    slot_total = {}
    slot_in = {}
    slot_out = {}

    for slot in SLOTS_30:
        mask = df_day.apply(
            lambda r: is_slot_in_shift(slot, r[col['shift_start']], r[col['shift_end']]), axis=1)
        working = df_day[mask]
        slot_total[slot] = working[col['count']].sum()
        slot_in[slot] = working[working[col['outsource']] == 0][col['count']].sum()
        slot_out[slot] = working[working[col['outsource']] == 1][col['count']].sum()

    kisi_in = df_day[df_day[col['outsource']] == 0][col['count']].sum()
    kisi_out = df_day[df_day[col['outsource']] == 1][col['count']].sum()
    kisi_total = kisi_in + kisi_out

    return {
        'slot_total': slot_total, 'slot_in': slot_in, 'slot_out': slot_out,
        'kisi_total': kisi_total, 'kisi_in': kisi_in, 'kisi_out': kisi_out,
        'outsource_ratio': kisi_out / kisi_total if kisi_total > 0 else 0
    }


# =============================================================================
# 5. OVERFLOW HESABI (V3'e özel)
# =============================================================================

def calculate_overflow(mip_info, erlang_by_slot):
    """
    Bir kuyruğun MIP sonucu ile Erlang ihtiyacı arasındaki fazlalığı
    slot bazında hesaplar. Bu fazlalık başka kuyruklara overflow olarak verilebilir.

    Returns:
        overflow_by_slot: {slot: fazla_kişi} — sadece pozitif değerler
    """
    overflow = {}
    for slot in SLOTS_30:
        atanan = mip_info['mip_by_slot'].get(slot, 0)
        erlang = erlang_by_slot.get(slot, 0)
        fazla = atanan - erlang
        if fazla > 0:
            overflow[slot] = fazla
    return overflow


def merge_overflows(*overflow_dicts):
    """
    Birden fazla kuyruğun overflow'unu birleştirir (slot bazında toplar).
    """
    merged = {}
    for ov in overflow_dicts:
        for slot, val in ov.items():
            merged[slot] = merged.get(slot, 0) + val
    return merged


# =============================================================================
# 6. SURPLUS DAĞITIMI
# =============================================================================

def distribute_surplus(mip_info, queue, erlang_by_slot, config=CONFIG, verbose=True):
    """
    MIP'in çıkardığı min ihtiyaç planının üzerine, configdeki
    inhouse kadrosundan kalan fazla kişileri pencerere yayar.
    """
    sd_cfg = config.get('surplus_distribution', {})
    if not sd_cfg.get('enabled', False):
        return mip_info

    kadro_cfg = sd_cfg.get('total_kadro', {}).get(queue, {})
    total_inhouse_kadro = kadro_cfg.get('inhouse', 0)
    if total_inhouse_kadro <= 0:
        if verbose:
            print(f"   ℹ Surplus: {queue} için inhouse kadro tanımlı değil, atlandı.")
        return mip_info

    current_inhouse = mip_info['total_inhouse_kisi']
    surplus = total_inhouse_kadro - current_inhouse

    if surplus <= 0:
        if verbose:
            print(f"   ℹ Surplus: kadro={total_inhouse_kadro}, MIP inhouse={current_inhouse} → "
                  f"fazla yok ({surplus})")
        return mip_info

    ccfg = config['company']
    inhouse_value = ccfg['inhouse']['shift_value']
    shift_cov = mip_info['shift_coverage']
    assignments = mip_info['assignments']

    only_assigned = sd_cfg.get('only_assigned_shifts', True)
    fallback = sd_cfg.get('fallback_all_inhouse', True)
    method = sd_cfg.get('method', 'rr_first')
    windows = sd_cfg.get('windows', [])

    if not windows:
        if verbose:
            print(f"   ⚠ Surplus: pencere tanımı yok, dağıtım yapılmadı.")
        return mip_info

    def _is_inhouse(s):
        return shift_cov[s]['company'] == inhouse_value

    inhouse_shifts = [s for s in shift_cov if _is_inhouse(s)]
    if only_assigned:
        eligible_inhouse = [s for s in inhouse_shifts if assignments.get(s, 0) > 0]
    else:
        eligible_inhouse = inhouse_shifts

    def _window_candidates(win):
        return [
            s for s in eligible_inhouse
            if win['start'] <= shift_cov[s]['start'] <= win['end']
        ]

    win_cands = {win['name']: _window_candidates(win) for win in windows}

    if all(len(c) == 0 for c in win_cands.values()):
        if fallback and eligible_inhouse:
            if verbose:
                print(f"   ⚠ Surplus: hiçbir pencerede aday yok, "
                      f"tüm atanmış inhouse shift'lere yayılıyor.")
            windows = [{'name': 'fallback', 'start': '00:00', 'end': '23:59', 'ratio': 1.0}]
            win_cands = {'fallback': eligible_inhouse}
        else:
            if verbose:
                print(f"   ⚠ Surplus: aday shift bulunamadı, {surplus} kişi atıl kaldı.")
            return mip_info

    # Surplus'ı pencere paylarına böl
    active_windows = [w for w in windows if win_cands[w['name']]]
    active_ratio_sum = sum(w['ratio'] for w in active_windows)
    if active_ratio_sum == 0:
        return mip_info

    raw_shares = {
        w['name']: surplus * (w['ratio'] / active_ratio_sum)
        for w in active_windows
    }
    floor_shares = {n: int(v) for n, v in raw_shares.items()}
    leftover = surplus - sum(floor_shares.values())
    fracs = sorted(
        ((n, raw_shares[n] - floor_shares[n]) for n in floor_shares),
        key=lambda x: x[1], reverse=True
    )
    for i in range(leftover):
        floor_shares[fracs[i % len(fracs)][0]] += 1
    window_shares = floor_shares

    if verbose:
        share_str = ", ".join(
            f"{w['name']}({w['start']}-{w['end']})={window_shares[w['name']]}"
            for w in active_windows
        )
        print(f"   ➕ Surplus: kadro={total_inhouse_kadro}, MIP inhouse={current_inhouse}, "
              f"fazla={surplus}, method={method}")
        print(f"      Pencere payları: {share_str}")

    # Her pencere için dağıtım
    added_total = {}
    by_window_log = {}
    local_mip_by_slot = dict(mip_info['mip_by_slot'])

    for win in active_windows:
        name = win['name']
        share = window_shares[name]
        if share <= 0:
            continue
        candidates = win_cands[name]

        added_w, used_rr, used_prop = _allocate_within_pool(
            share, candidates, shift_cov, erlang_by_slot,
            assignments, local_mip_by_slot, method
        )

        for s, n in added_w.items():
            added_total[s] = added_total.get(s, 0) + n

        by_window_log[name] = {
            'share': share, 'rr_fix': used_rr, 'proportional': used_prop,
            'added': added_w, 'window': f"{win['start']}-{win['end']}"
        }
        if verbose and share > 0:
            print(f"      [{name} {win['start']}-{win['end']}] "
                  f"pay={share}, RR-fix={used_rr}, eşit={used_prop}")

    # mip_info güncelle
    total_added = sum(added_total.values())
    if total_added == 0:
        return mip_info

    for s, n in added_total.items():
        if n > 0:
            assignments[s] = assignments.get(s, 0) + n

    in_shifts_all = [s for s in shift_cov if shift_cov[s]['company'] == inhouse_value]
    new_mip_by_slot = {}
    new_mip_in_by_slot = {}
    for slot in mip_info['mip_by_slot'].keys():
        new_mip_by_slot[slot] = sum(
            assignments.get(s, 0) for s in shift_cov if slot in shift_cov[s]['slots']
        )
        new_mip_in_by_slot[slot] = sum(
            assignments.get(s, 0) for s in in_shifts_all if slot in shift_cov[s]['slots']
        )
    mip_info['mip_by_slot'] = new_mip_by_slot
    mip_info['mip_in_by_slot'] = new_mip_in_by_slot

    if 'mip_out_by_slot' in mip_info:
        mip_info['mip_out_by_slot'] = {
            slot: new_mip_by_slot[slot] - new_mip_in_by_slot[slot]
            for slot in new_mip_by_slot
        }

    mip_info['total_inhouse_kisi'] = current_inhouse + total_added
    mip_info['total_kisi'] = mip_info.get('total_kisi', 0) + total_added
    total_out = mip_info.get('total_outsource_kisi', 0)
    total_all_for_ratio = mip_info['total_inhouse_kisi'] + total_out
    if total_all_for_ratio > 0:
        mip_info['outsource_ratio'] = total_out / total_all_for_ratio

    mip_info['surplus_added'] = added_total
    mip_info['surplus_total_added'] = total_added
    mip_info['surplus_by_window'] = by_window_log

    if verbose:
        print(f"      ✓ Eklenen toplam: {total_added} kişi → "
              f"yeni inhouse: {mip_info['total_inhouse_kisi']}, "
              f"yeni oran: {mip_info['outsource_ratio']:.1%}")

    return mip_info


def _allocate_within_pool(share, candidates, shift_cov, erlang_by_slot,
                          assignments, mip_by_slot_state, method):
    added = {s: 0 for s in candidates}
    remaining = share
    used_rr = 0
    used_prop = 0

    if not candidates or share <= 0:
        return added, used_rr, used_prop

    # 1) RR-fix
    if method == 'rr_first' and remaining > 0:
        candidate_slots = set()
        for s in candidates:
            candidate_slots.update(shift_cov[s]['slots'])

        def _open_deficits():
            return {
                slot: erlang_by_slot[slot] - mip_by_slot_state.get(slot, 0)
                for slot in candidate_slots
                if slot in erlang_by_slot
                and erlang_by_slot[slot] - mip_by_slot_state.get(slot, 0) > 0
            }

        deficits = _open_deficits()
        guard = 0
        while remaining > 0 and deficits and guard < 10000:
            guard += 1
            best_shift = None
            best_score = 0
            for s in candidates:
                score = sum(1 for slot in shift_cov[s]['slots'] if slot in deficits)
                if score > best_score:
                    best_score = score
                    best_shift = s
            if best_shift is None or best_score == 0:
                break
            added[best_shift] += 1
            remaining -= 1
            used_rr += 1
            for slot in shift_cov[best_shift]['slots']:
                mip_by_slot_state[slot] = mip_by_slot_state.get(slot, 0) + 1
            deficits = _open_deficits()

    # 2) Eşit dağıtım
    if remaining > 0:
        n = len(candidates)
        base = remaining // n
        extra = remaining - base * n
        sorted_cands = sorted(candidates, key=lambda s: assignments.get(s, 0))
        for i, s in enumerate(sorted_cands):
            inc = base + (1 if i < extra else 0)
            if inc > 0:
                added[s] += inc
                for slot in shift_cov[s]['slots']:
                    mip_by_slot_state[slot] = mip_by_slot_state.get(slot, 0) + inc
        used_prop += remaining
        remaining = 0

    return added, used_rr, used_prop


# =============================================================================
# 7. SUBQUEUE MIN HESAPLAMA
# =============================================================================

def _build_subqueue_min_slots(df_calls_30, queue, target_date, erlang_by_slot, config):
    target_date = pd.to_datetime(target_date)
    df_day = df_calls_30[df_calls_30['data_date'] == target_date]

    if len(df_day) == 0:
        return {}, {}

    inhouse_min_by_slot = {}
    outsource_min_by_slot = {}

    in_only_cfg = config.get('inhouse_only_subqueues', {}).get(queue, [])

    for item in in_only_cfg:
        if isinstance(item, str):
            sq_name = item
            min_ratio = 1.0
        else:
            sq_name = item['sub_queue']
            min_ratio = item.get('min_ratio', 1.0)

        sq_col = f"{sq_name}_calls"
        total_col = f"{queue}_total"

        for _, row in df_day.iterrows():
            slot = row['slot_30']
            erlang = erlang_by_slot.get(slot, 0)
            if erlang <= 0:
                continue
            sq_calls = row.get(sq_col, 0) if sq_col in row.index else 0
            total_calls = row.get(total_col, 0) if total_col in row.index else 0
            if total_calls > 0 and sq_calls > 0:
                call_ratio = sq_calls / total_calls
                min_need = math.ceil(erlang * call_ratio * min_ratio)
                inhouse_min_by_slot[slot] = inhouse_min_by_slot.get(slot, 0) + min_need

    out_only_cfg = config.get('outsource_only_subqueues', {}).get(queue, [])

    for item in out_only_cfg:
        if isinstance(item, str):
            sq_name = item
            min_ratio = 1.0
            hours = None
        else:
            sq_name = item['sub_queue']
            min_ratio = item.get('min_ratio', 1.0)
            hours = item.get('hours')

        sq_col = f"{sq_name}_calls"
        total_col = f"{queue}_total"

        for _, row in df_day.iterrows():
            slot = row['slot_30']
            erlang = erlang_by_slot.get(slot, 0)
            if erlang <= 0:
                continue
            if hours:
                if not is_slot_in_shift(slot, hours['start'], hours['end']):
                    continue
            sq_calls = row.get(sq_col, 0) if sq_col in row.index else 0
            total_calls = row.get(total_col, 0) if total_col in row.index else 0
            if total_calls > 0 and sq_calls > 0:
                call_ratio = sq_calls / total_calls
                min_need = math.ceil(erlang * call_ratio * min_ratio)
                outsource_min_by_slot[slot] = outsource_min_by_slot.get(slot, 0) + min_need

    return inhouse_min_by_slot, outsource_min_by_slot


# =============================================================================
# 8. SHIFT SINIFLANDIRMA (V2'den)
# =============================================================================

def classify_shifts(df_shifts_queue, config=CONFIG):
    ccfg = config['company']
    scol = config['shift_columns']
    inhouse_value = ccfg['inhouse']['shift_value']
    outsource_value = ccfg['outsource']['shift_value']

    in_starts = set()
    out_starts = set()

    for _, row in df_shifts_queue.iterrows():
        start = str(row[scol['start']])[:5]
        company = row[scol['company']]
        if company == inhouse_value:
            in_starts.add(start)
        elif company == outsource_value:
            out_starts.add(start)

    return {
        'inhouse_only': sorted(in_starts - out_starts),
        'outsource_only': sorted(out_starts - in_starts),
        'kesisim': sorted(in_starts & out_starts),
    }


def print_shift_classification(classification, label):
    print(f"\n📋 SHIFT SAAT SINIFLANDIRMASI ({label}):")
    io = classification.get('inhouse_only', [])
    oo = classification.get('outsource_only', [])
    ks = classification.get('kesisim', [])
    def _fmt(lst):
        return ", ".join(lst) if lst else "(yok)"
    print(f"   Inhouse-only başlangıç saatleri  ({len(io):>2}): {_fmt(io)}")
    print(f"   Outsource-only başlangıç saatleri({len(oo):>2}): {_fmt(oo)}")
    print(f"   Kesişim başlangıç saatleri       ({len(ks):>2}): {_fmt(ks)}")


# =============================================================================
# 9. RAPOR
# =============================================================================

def print_queue_report(date, queue, erlang_by_slot, mip_info, actual,
                       weighted_aht_by_slot=None, total_calls_day=0,
                       calls_by_slot=None, mip_info_stage1=None, config=CONFIG,
                       overflow_by_slot=None):

    label = config['queues'][queue]['label']
    date_str = pd.to_datetime(date).strftime('%Y-%m-%d')

    print(f"\n{'='*95}")
    print(f"KUYRUK RAPORU: {label} ({queue.upper()}) - {date_str}")
    print(f"{'='*95}")

    e_peak = max(erlang_by_slot.values()) if erlang_by_slot else 0
    m_peak = max(mip_info['mip_by_slot'].values()) if mip_info['mip_by_slot'] else 0
    a_peak = max(actual['slot_total'].values()) if actual['slot_total'] else 0

    # V3: Overflow bilgisi
    if overflow_by_slot:
        total_overflow = sum(overflow_by_slot.values())
        overflow_slots = sum(1 for v in overflow_by_slot.values() if v > 0)
        print(f"\n🔄 OVERFLOW (Gold/Kurumsal → Kitle):")
        print(f"   Toplam overflow: {total_overflow} kişi-slot, {overflow_slots} slotta aktif")
        overflow_used = mip_info.get('overflow_used_by_slot', {})
        if overflow_used:
            total_used = sum(overflow_used.values())
            print(f"   Kullanılan overflow: {total_used} kişi-slot")

    print(f"\n📊 ÖZET (KİŞİ BAZLI):")
    if mip_info_stage1 is not None:
        s1 = mip_info_stage1
        print(f"   {'Metrik':<22} {'MIP(1)':>10} {'MIP(2)':>10} {'Fark':>7} {'Gerçek':>10} {'MIP2-G':>8}")
        print(f"   {'-'*72}")
        print(f"   {'Toplam Kişi':<22} {s1['total_kisi']:>10} {mip_info['total_kisi']:>10} "
              f"{mip_info['total_kisi']-s1['total_kisi']:>+7} {actual['kisi_total']:>10} "
              f"{mip_info['total_kisi']-actual['kisi_total']:>+8}")
        print(f"   {'Inhouse Kişi':<22} {s1['total_inhouse_kisi']:>10} {mip_info['total_inhouse_kisi']:>10} "
              f"{mip_info['total_inhouse_kisi']-s1['total_inhouse_kisi']:>+7} {actual['kisi_in']:>10} "
              f"{mip_info['total_inhouse_kisi']-actual['kisi_in']:>+8}")
        print(f"   {'Outsource Kişi':<22} {s1['total_outsource_kisi']:>10} {mip_info['total_outsource_kisi']:>10} "
              f"{mip_info['total_outsource_kisi']-s1['total_outsource_kisi']:>+7} {actual['kisi_out']:>10} "
              f"{mip_info['total_outsource_kisi']-actual['kisi_out']:>+8}")
        if mip_info.get('total_part_time_kisi', 0) > 0:
            print(f"   {'Part-time Kişi':<22} {s1['total_part_time_kisi']:>10} {mip_info['total_part_time_kisi']:>10}")
        print(f"   {'Outsource %':<22} {s1['outsource_ratio']:>9.1%} {mip_info['outsource_ratio']:>10.1%} "
              f"{'':>7} {actual['outsource_ratio']:>9.1%}")
        print(f"   {'Aktif Shift':<22} {len([s for s,c in s1['assignments'].items() if c>0]):>10} "
              f"{len([s for s,c in mip_info['assignments'].items() if c>0]):>10}")
    else:
        print(f"   {'Metrik':<22} {'MIP':>10} {'Gerçek':>10} {'Fark':>8}")
        print(f"   {'-'*55}")
        print(f"   {'Toplam Kişi':<22} {mip_info['total_kisi']:>10} {actual['kisi_total']:>10} "
              f"{mip_info['total_kisi']-actual['kisi_total']:>+8}")
        print(f"   {'Inhouse Kişi':<22} {mip_info['total_inhouse_kisi']:>10} {actual['kisi_in']:>10} "
              f"{mip_info['total_inhouse_kisi']-actual['kisi_in']:>+8}")
        print(f"   {'Outsource Kişi':<22} {mip_info['total_outsource_kisi']:>10} {actual['kisi_out']:>10} "
              f"{mip_info['total_outsource_kisi']-actual['kisi_out']:>+8}")
        if mip_info.get('total_part_time_kisi', 0) > 0:
            print(f"   {'Part-time Kişi':<22} {mip_info['total_part_time_kisi']:>10}")
        print(f"   {'Outsource %':<22} {mip_info['outsource_ratio']:>9.1%} {actual['outsource_ratio']:>9.1%}")
        print(f"   {'Aktif Shift':<22} {len(mip_info['assignments']):>10}")

    # Eşzamanlı peak
    m1_peak = max(mip_info_stage1['mip_by_slot'].values()) if mip_info_stage1 else m_peak
    print(f"\n📊 EŞZAMANLI PEAK:")
    print(f"   Erlang: {e_peak} | MIP1: {m1_peak} | MIP2: {m_peak} | Gerçek: {a_peak}")

    # RR penalty
    if mip_info.get('rr_penalty_enabled', False):
        rr_excess = mip_info.get('rr_excess_by_slot', {})
        rr_peak = mip_info.get('rr_peak_slots', set())
        rr_total_exc = mip_info.get('rr_total_excess', 0)
        rr_total_cost = mip_info.get('rr_total_penalty_cost', 0)
        rr_n_penalized = mip_info.get('rr_penalized_slots', 0)

        print(f"\n📈 RR PENALTY:")
        print(f"   Peak slotlar (muaf): {len(rr_peak)} | Cezalı: {rr_n_penalized} | "
              f"Fazla: {rr_total_exc} | Penalty: {rr_total_cost:.1f}")

        if rr_excess:
            sorted_excess = sorted(rr_excess.items(), key=lambda x: x[1], reverse=True)[:10]
            print(f"   {'Slot':<8} {'Erlang':>7} {'MIP':>7} {'Fazla':>7} {'Penalty':>10}")
            print(f"   {'-'*45}")
            for slot, exc in sorted_excess:
                e = erlang_by_slot.get(slot, 0)
                m = mip_info['mip_by_slot'].get(slot, 0)
                pen = exc * config['queue_configs'][queue].get('rr_penalty', {}).get('penalty_per_person', 5.0)
                print(f"   {slot:<8} {e:>7} {m:>7} {exc:>+7} {pen:>10.1f}")

    # Slot cap
    if mip_info.get('sc_penalized_slots', 0) > 0:
        print(f"\n📊 SLOT CAP:")
        print(f"   İhlal: {mip_info['sc_penalized_slots']} slot | "
              f"Fazla: {mip_info['sc_total_excess']} | Penalty: {mip_info['sc_total_penalty_cost']:.1f}")

    # Shift atamaları
    sc = mip_info['shift_coverage']
    mcfg = config['queue_configs'][queue]['mip']

    print(f"\n📋 SHIFT ATAMALARI ({len(mip_info['assignments'])} shift):")
    if mip_info_stage1 is not None:
        print(f"   {'Shift':<22} {'Saat':<12} {'Tip':<10} {'MIP(1)':>7} {'MIP(2)':>7} {'Fark':>6}")
        print(f"   {'-'*68}")
        s1_assigns = mip_info_stage1['assignments']
    else:
        print(f"   {'Shift':<22} {'Saat':<12} {'Tip':<10} {'Kişi':>6}")
        print(f"   {'-'*55}")
        s1_assigns = None

    for s, cnt in sorted(mip_info['assignments'].items(), key=lambda x: sc[x[0]]['start']):
        info = sc[s]
        if s1_assigns is not None:
            cnt1 = s1_assigns.get(s, 0)
            diff = cnt - cnt1
            diff_str = f"{diff:+d}" if diff != 0 else "-"
            print(f"   {s:<22} {info['start']}-{info['end']:<5} {info['company']:<10} "
                  f"{cnt1:>7} {cnt:>7} {diff_str:>6}")
        else:
            print(f"   {s:<22} {info['start']}-{info['end']:<5} {info['company']:<10} {cnt:>6}")


# =============================================================================
# 10. ANA AKIŞ — V3 WEEKDAY
# =============================================================================

def run_queue_pipeline(df_calls, df_actual, df_shifts, target_date, queue,
                       config=CONFIG, verbose=True, overflow_by_slot=None):
    """
    V3 akışı — SADECE HAFTAİÇİ.

    V2'den fark: overflow_by_slot parametresi.
    Kitle kuyruğu çağrılırken gold/kurumsal fazlalıkları buraya verilir.
    MIP coverage kısıtında erlang - overflow kullanılır.
    """

    target_date = pd.to_datetime(target_date)
    date_str = target_date.strftime('%Y-%m-%d')
    weekday = target_date.weekday()

    if weekday >= 5:
        raise ValueError(
            f"V3 pipeline sadece haftaiçi içindir. "
            f"{date_str} ({'Cumartesi' if weekday == 5 else 'Pazar'}) için "
            f"v10.9 kullanın."
        )

    label = config['queues'][queue]['label']

    if isinstance(df_shifts, dict):
        df_shifts_queue = df_shifts.get(queue)
        if df_shifts_queue is None:
            raise ValueError(f"'{queue}' için shift verisi bulunamadı.")
    else:
        df_shifts_queue = df_shifts

    if verbose:
        print(f"\n{'='*95}")
        print(f"PİPELİNE V3 WEEKDAY: {label} ({queue.upper()}) - {date_str}")
        print(f"{'='*95}")

    # Shift sınıflandırma
    classification = classify_shifts(df_shifts_queue, config)
    if verbose:
        print_shift_classification(classification, label)

    if verbose: print(f"\n[1/4] Veri hazırlama...")
    df_calls_30 = prepare_calls_30(df_calls, config)

    if verbose: print(f"[2/4] Erlang hesaplama...")
    df_erlang = calculate_erlang_all(df_calls_30, config)

    df_erlang_day = df_erlang[
        (df_erlang['date'] == target_date) & (df_erlang['queue'] == queue)
    ].copy()

    erlang_by_slot = dict(zip(df_erlang_day['slot'], df_erlang_day['erlang_need']))
    weighted_aht_by_slot = dict(zip(df_erlang_day['slot'], df_erlang_day['weighted_aht']))

    if verbose:
        e_total = sum(erlang_by_slot.values())
        e_peak = max(erlang_by_slot.values()) if erlang_by_slot else 0
        print(f"   Erlang: toplam={e_total}, peak={e_peak}")

        if overflow_by_slot:
            total_ov = sum(overflow_by_slot.values())
            ov_slots = sum(1 for v in overflow_by_slot.values() if v > 0)
            net_total = sum(max(0, erlang_by_slot.get(s, 0) - overflow_by_slot.get(s, 0))
                          for s in erlang_by_slot)
            print(f"   Overflow: {total_ov} kişi-slot ({ov_slots} slot)")
            print(f"   Net ihtiyaç (Erlang - overflow): {net_total}")

    inhouse_min_by_slot, outsource_min_by_slot = _build_subqueue_min_slots(
        df_calls_30, queue, target_date, erlang_by_slot, config
    )

    if verbose:
        if inhouse_min_by_slot:
            active_in = {k: v for k, v in inhouse_min_by_slot.items() if v > 0}
            print(f"   Inhouse-only kısıt: {len(active_in)} slotta aktif, toplam min={sum(active_in.values())}")
        if outsource_min_by_slot:
            active_out = {k: v for k, v in outsource_min_by_slot.items() if v > 0}
            print(f"   Outsource-only kısıt: {len(active_out)} slotta aktif, toplam min={sum(active_out.values())}")

    if verbose: print(f"[3/4] MIP optimizasyon...")
    assignments, mip_info = optimize_queue(
        erlang_by_slot, df_shifts_queue, queue,
        target_date=target_date,
        inhouse_min_by_slot=inhouse_min_by_slot,
        outsource_min_by_slot=outsource_min_by_slot,
        config=config,
        overflow_by_slot=overflow_by_slot
    )

    if assignments is None:
        print(f"   ⚠ Çözüm bulunamadı: {mip_info}")
        return None

    if verbose:
        pt_info = ""
        if mip_info.get('total_part_time_kisi', 0) > 0:
            pt_info = f", PT: {mip_info['total_part_time_kisi']}/{mip_info['pt_available']}"
        print(f"   MIP(1): {mip_info['total_kisi']} kişi "
              f"(In: {mip_info['total_inhouse_kisi']}, Out: {mip_info['total_outsource_kisi']}{pt_info}, "
              f"Oran: {mip_info['outsource_ratio']:.1%})")

    # Surplus dağıtımı
    mip_info_stage1 = None
    if config.get('surplus_distribution', {}).get('enabled', False):
        mip_info_stage1 = copy.deepcopy(mip_info)
        distribute_surplus(mip_info, queue, erlang_by_slot, config=config, verbose=verbose)

    if verbose: print(f"[4/4] Rapor...")
    actual = get_actual_summary(df_actual, target_date, queue, config)

    df_calls_30_day = df_calls_30[df_calls_30['data_date'] == target_date]
    calls_by_slot = {}
    if f"{queue}_total" in df_calls_30_day.columns:
        calls_by_slot = dict(zip(df_calls_30_day['slot_30'], df_calls_30_day[f"{queue}_total"]))

    total_calls_day = int(sum(calls_by_slot.values())) if calls_by_slot else 0

    print_queue_report(target_date, queue, erlang_by_slot, mip_info, actual,
                       weighted_aht_by_slot=weighted_aht_by_slot,
                       total_calls_day=total_calls_day,
                       calls_by_slot=calls_by_slot,
                       mip_info_stage1=mip_info_stage1,
                       config=config,
                       overflow_by_slot=overflow_by_slot)

    return {
        'date': target_date,
        'queue': queue,
        'label': label,
        'day_type': 'haftalici',
        'erlang_by_slot': erlang_by_slot,
        'weighted_aht_by_slot': weighted_aht_by_slot,
        'mip_info': mip_info,
        'mip_info_stage1': mip_info_stage1,
        'actual': actual,
        'total_calls_day': total_calls_day,
        'calls_by_slot': calls_by_slot,
        'inhouse_min_by_slot': inhouse_min_by_slot,
        'outsource_min_by_slot': outsource_min_by_slot,
        'shift_classification': classification,
        'overflow_by_slot': overflow_by_slot or {},
    }


# =============================================================================
# 11. V3 ORCHESTRATOR — TÜM KUYRUKLAR
# =============================================================================

def run_all_queues(df_calls, df_actual, df_shifts, target_date, config=CONFIG):
    """
    V3 akışı:
      1) Gold → MIP → overflow hesapla
      2) Kurumsal → MIP → overflow hesapla
      3) Gold + Kurumsal overflow'u birleştir
      4) Kitle → MIP (overflow düşülmüş Erlang ile)
      5) Her kuyruk surplus dağıtımı (run_queue_pipeline içinde)
    """
    target_date_chk = pd.to_datetime(target_date)
    if target_date_chk.weekday() >= 5:
        day_name = 'Cumartesi' if target_date_chk.weekday() == 5 else 'Pazar'
        raise ValueError(
            f"V3 pipeline sadece haftaiçi içindir. "
            f"{target_date_chk.strftime('%Y-%m-%d')} ({day_name}) için "
            f"v10.9 kullanın."
        )

    results = {}
    overflow_sources = {}

    # --- V3 Config: hangi kuyrukların overflow'u kitleye akacak ---
    overflow_cfg = config.get('overflow', {})
    overflow_donors = overflow_cfg.get('donors', ['gold', 'kurumsal'])
    overflow_receiver = overflow_cfg.get('receiver', 'kitle')

    # Queue sıralaması: önce donor'lar, sonra receiver
    queue_order = []
    for q in config['queues']:
        if q in overflow_donors:
            queue_order.insert(0, q)  # başa ekle
        else:
            queue_order.append(q)  # sona ekle

    # Donor'ları en başa al (gold, kurumsal → kitle sırasıyla)
    donor_queues = [q for q in queue_order if q in overflow_donors]
    other_queues = [q for q in queue_order if q not in overflow_donors]
    queue_order = donor_queues + other_queues

    print(f"\n{'='*95}")
    print(f"V3 WEEKDAY ORCHESTRATOR - {target_date_chk.strftime('%Y-%m-%d')}")
    print(f"{'='*95}")
    print(f"   Sıralama: {' → '.join(queue_order)}")
    print(f"   Overflow: {', '.join(overflow_donors)} → {overflow_receiver}")

    for queue in queue_order:
        overflow_input = None

        if queue == overflow_receiver:
            # Donor'lardan gelen overflow'u birleştir
            if overflow_sources:
                overflow_input = merge_overflows(*overflow_sources.values())
                total_ov = sum(overflow_input.values())
                print(f"\n🔄 {overflow_receiver.upper()}'ye overflow aktarılıyor: "
                      f"{total_ov} kişi-slot")
                for donor, ov in overflow_sources.items():
                    print(f"   ← {donor}: {sum(ov.values())} kişi-slot")

        result = run_queue_pipeline(
            df_calls, df_actual, df_shifts, target_date, queue,
            config=config, overflow_by_slot=overflow_input
        )

        if result:
            results[queue] = result

            # Donor ise overflow hesapla
            if queue in overflow_donors:
                overflow = calculate_overflow(
                    result['mip_info'],
                    result['erlang_by_slot']
                )
                overflow_sources[queue] = overflow
                if overflow:
                    print(f"   → {queue} overflow: {sum(overflow.values())} kişi-slot")

    # Özet
    print(f"\n{'='*95}")
    print(f"TÜM KUYRUKLAR ÖZET - {target_date_chk.strftime('%Y-%m-%d')} [V3 Weekday]")
    print(f"{'='*95}")
    print(f"{'Kuyruk':<12} {'MIP':>8} {'Grç':>8} {'Fark':>6} "
          f"{'In':>6} {'Out':>6} {'PT':>5} {'MIP%':>7} {'Grç%':>7} {'Shift':>6}")
    print(f"{'-'*77}")

    t_mip = t_grc = t_in = t_out = t_pt = 0
    for q, r in results.items():
        mi = r['mip_info']
        a = r['actual']
        fark = mi['total_kisi'] - a['kisi_total']
        pt = mi.get('total_part_time_kisi', 0)
        n_shifts = len(mi['assignments'])

        print(f"{r['label']:<12} {mi['total_kisi']:>8} {a['kisi_total']:>8} {fark:>+6} "
              f"{mi['total_inhouse_kisi']:>6} {mi['total_outsource_kisi']:>6} {pt:>5} "
              f"{mi['outsource_ratio']:>6.1%} {a['outsource_ratio']:>6.1%} {n_shifts:>6}")

        t_mip += mi['total_kisi']
        t_grc += a['kisi_total']
        t_in += mi['total_inhouse_kisi']
        t_out += mi['total_outsource_kisi']
        t_pt += pt

    t_out_pct = t_out / t_mip if t_mip > 0 else 0
    print(f"{'-'*77}")
    print(f"{'TOPLAM':<12} {t_mip:>8} {t_grc:>8} {t_mip-t_grc:>+6} "
          f"{t_in:>6} {t_out:>6} {t_pt:>5} {t_out_pct:>6.1%}")

    # Overflow özet
    if overflow_sources:
        print(f"\n🔄 OVERFLOW ÖZETİ:")
        for donor, ov in overflow_sources.items():
            total_ov = sum(ov.values())
            ov_slots = sum(1 for v in ov.values() if v > 0)
            print(f"   {donor} → {overflow_receiver}: {total_ov} kişi-slot ({ov_slots} slot)")

    return results
