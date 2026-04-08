# =============================================================================
# KUYRUK BAZLI VARDIYA PİPELİNE - ACTUAL v10.8
# =============================================================================
#
# v10.9:
#   - Pattern / geçmiş veri analizi KALDIRILDI
#   - Occupancy KALDIRILDI (Erlang'a dahil)
#   - Raporlar aynen korundu
#
# v10.7:
#   - Slot Cap: saat aralığı bazlı üst sınır (bands yapısı)
#   - AHT Override: saat bazlı manuel AHT girişi
#   - 3 seviyeli RR Penalty: peak / gündüz / gece farklı ceza
#   - Part-time inhouse çarpanı kullanır
#   - Saatlik shrinkage (dict)
#   - default_aht fallback
#   - Ek kapasite analizi (dış arama / atıl kapasite)
#
# =============================================================================

import pandas as pd
import numpy as np
import math
import calendar
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
    target_date = pd.to_datetime(target_date)
    day = target_date.day
    weekday = target_date.weekday()
    year = target_date.year
    month = target_date.month

    pt_config = config.get('part_time', {})
    if not pt_config.get('enabled', False):
        return {q: 0 for q in config['queues']}

    pt_counts = pt_config.get('count', {})

    if weekday < 5:
        return {q: 0 for q in config['queues']}

    last_day_of_month = calendar.monthrange(year, month)[1]
    result = {}

    for queue in config['queues']:
        total_pt = pt_counts.get(queue, 0)
        if total_pt == 0:
            result[queue] = 0
            continue
        if day in [1, 2, 3]:
            result[queue] = 0
            continue
        if day == last_day_of_month and weekday == 5:
            result[queue] = total_pt
            continue
        half = total_pt // 2
        if weekday == 5:
            result[queue] = half
        else:
            result[queue] = total_pt - half

    return result


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
# 2. ERLANG-C (occupancy kaldırıldı — Erlang'a dahil)
# =============================================================================

# =============================================================================
# 6. ERLANG-C
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


def find_optimal_agents(calls, aht, slot, config=CONFIG):
    ecfg = config['erlang']
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

    # Saatlik shrinkage
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
            need, asa, _ = find_optimal_agents(calls, weighted_aht, slot, config)

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
                   outsource_min_by_slot=None, config=None):

    if config is None:
        config = CONFIG

    qcfg = config['queues'][queue]
    mcfg = config['mip']
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

    ssp_cfg = config.get('small_shift_penalty', {})
    ssp_enabled = ssp_cfg.get('enabled', False)
    ssp_penalty = ssp_cfg.get('penalty', 3.0)

    rr_cfg = config.get('rr_penalty', {})
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

    sc_cfg = config.get('slot_cap', {})
    slot_cap_detail = []
    sc_excess = {}

    if sc_cfg.get('enabled', False):
        sc_queues = sc_cfg.get('queues', list(config['queues'].keys()))
        if queue in sc_queues:
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

    for slot in active_slots:
        covering = [s for s in shifts if slot in shift_cov[s]['slots']]
        if covering:
            prob += lpSum([x[s] for s in covering]) >= erlang_by_slot[slot]

    M = 500
    for s in shifts:
        prob += x[s] <= M * y[s]
        prob += x[s] >= mcfg['min_per_shift'] * y[s]

    if pt_available > 0 and pt_shift_keys:
        prob += lpSum([x[s] for s in pt_shift_keys]) == pt_available

    out_cfg = config['outsource_ratio'].get(queue)
    if not only_inhouse and out_cfg:
        t_in = lpSum([x[s] for s in in_shifts]) + lpSum([x[s] for s in pt_shift_keys])
        t_out = lpSum([x[s] for s in out_shifts])
        prob += (1 - out_cfg['min']) * t_out >= out_cfg['min'] * t_in
        prob += (1 - out_cfg['max']) * t_out <= out_cfg['max'] * t_in

    if inhouse_min_by_slot:
        for slot, min_in in inhouse_min_by_slot.items():
            if min_in > 0:
                covering_in = [s for s in in_shifts if slot in shift_cov[s]['slots']]
                covering_pt = [s for s in pt_shift_keys if slot in shift_cov[s]['slots']]
                covering_all_in = covering_in + covering_pt
                if covering_all_in:
                    prob += lpSum([x[s] for s in covering_all_in]) >= min_in

    if outsource_min_by_slot:
        for slot, min_out in outsource_min_by_slot.items():
            if min_out > 0:
                covering_out = [s for s in out_shifts if slot in shift_cov[s]['slots']]
                if covering_out:
                    prob += lpSum([x[s] for s in covering_out]) >= min_out


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
# 9. GÜNLÜK KAPASİTE HESABI
# =============================================================================

def calculate_daily_capacity(mip_info, weighted_aht_by_slot, config=CONFIG):
    eff = config.get('capacity', {}).get('efficiency', {
        'inhouse': 0.70, 'outsource': 0.70, 'part_time': 0.80
    })

    active_ahts = [v for v in weighted_aht_by_slot.values() if v > 0]
    avg_aht = sum(active_ahts) / len(active_ahts) if active_ahts else 150

    sc = mip_info['shift_coverage']
    assignments = mip_info['assignments']

    total_cap = 0
    in_cap = 0
    out_cap = 0
    pt_cap = 0

    for shift, count in assignments.items():
        info = sc[shift]
        company = info['company']

        start_h, start_m = int(info['start'][:2]), int(info['start'][3:5])
        end_h, end_m = int(info['end'][:2]), int(info['end'][3:5])

        start_min = start_h * 60 + start_m
        end_min = end_h * 60 + end_m
        if end_min <= start_min:
            end_min += 24 * 60

        duration_sn = (end_min - start_min) * 60
        efficiency = eff.get(company, 0.70)
        cap_per_person = (duration_sn / avg_aht) * efficiency
        cap_total = cap_per_person * count

        total_cap += cap_total
        if company == 'inhouse':
            in_cap += cap_total
        elif company == 'outsource':
            out_cap += cap_total
        elif company == 'part_time':
            pt_cap += cap_total

    return {
        'total_capacity': round(total_cap, 0),
        'inhouse_capacity': round(in_cap, 0),
        'outsource_capacity': round(out_cap, 0),
        'pt_capacity': round(pt_cap, 0),
        'avg_aht': round(avg_aht, 1),
    }


# =============================================================================
# 6. RAPOR (MIP vs Gerçek + kapasite raporu)
# =============================================================================

def print_queue_report(date, queue, erlang_by_slot, mip_info, actual,
                       weighted_aht_by_slot=None, total_calls_day=0,
                       calls_by_slot=None, config=CONFIG):

    label = config['queues'][queue]['label']
    date_str = pd.to_datetime(date).strftime('%Y-%m-%d')

    print(f"\n{'='*95}")
    print(f"KUYRUK RAPORU: {label} ({queue.upper()}) - {date_str}")
    print(f"{'='*95}")

    e_peak = max(erlang_by_slot.values()) if erlang_by_slot else 0
    m_peak = max(mip_info['mip_by_slot'].values()) if mip_info['mip_by_slot'] else 0
    a_peak = max(actual['slot_total'].values()) if actual['slot_total'] else 0

    print(f"\n📊 ÖZET (KİŞİ BAZLI):")
    print(f"   {'Metrik':<25} {'MIP':>10} {'Gerçek':>10} {'Fark':>10}")
    print(f"   {'-'*55}")
    print(f"   {'Toplam Kişi':<25} {mip_info['total_kisi']:>10} {actual['kisi_total']:>10} "
          f"{mip_info['total_kisi'] - actual['kisi_total']:>+10}")
    print(f"   {'Inhouse Kişi':<25} {mip_info['total_inhouse_kisi']:>10} {actual['kisi_in']:>10} "
          f"{mip_info['total_inhouse_kisi'] - actual['kisi_in']:>+10}")
    print(f"   {'Outsource Kişi':<25} {mip_info['total_outsource_kisi']:>10} {actual['kisi_out']:>10} "
          f"{mip_info['total_outsource_kisi'] - actual['kisi_out']:>+10}")
    if mip_info.get('total_part_time_kisi', 0) > 0:
        print(f"   {'Part-time Kişi':<25} {mip_info['total_part_time_kisi']:>10} {'-':>10} {'-':>10}")
    print(f"   {'Outsource %':<25} {mip_info['outsource_ratio']:>9.1%} {actual['outsource_ratio']:>9.1%}")
    print(f"   {'Aktif Shift Sayısı':<25} {len(mip_info['assignments']):>10}")

    print(f"\n📊 EŞZAMANLI PEAK:")
    print(f"   Erlang: {e_peak}  |  MIP: {m_peak}  |  Gerçek: {a_peak}")

    if weighted_aht_by_slot:
        cap = calculate_daily_capacity(mip_info, weighted_aht_by_slot, config)
        rr = cap['total_capacity'] / total_calls_day if total_calls_day > 0 else 0

        print(f"\n📊 GÜNLÜK KAPASİTE:")
        print(f"   {'Metrik':<30} {'Değer':>12}")
        print(f"   {'-'*45}")
        print(f"   {'Günlük Avg AHT':<30} {cap['avg_aht']:>11.0f}s")
        print(f"   {'Toplam Kapasite (çağrı)':<30} {cap['total_capacity']:>12,.0f}")
        print(f"   {'  - Inhouse':<30} {cap['inhouse_capacity']:>12,.0f}")
        print(f"   {'  - Outsource':<30} {cap['outsource_capacity']:>12,.0f}")
        if cap['pt_capacity'] > 0:
            print(f"   {'  - Part-time':<30} {cap['pt_capacity']:>12,.0f}")
        if total_calls_day > 0:
            print(f"   {'Toplam Çağrı':<30} {total_calls_day:>12,.0f}")
            print(f"   {'Response Rate':<30} {rr:>11.1%}")
            status = "✅ Yeterli" if rr >= 1.0 else "⚠ Yetersiz"
            print(f"   {'Durum':<30} {status:>12}")

    # Erken saat raporu
    early_starts = mip_info.get('early_starts', {})
    early_total = mip_info.get('early_total', 0)
    early_penalty = mip_info.get('early_penalty', 0)

    if early_starts:
        print(f"\n⏰ ERKEN SAAT BAŞLANGIÇLARI - {label.upper()}:")
        print(f"   {'Shift':<25} {'Saat':<8} {'Kişi':>6} {'Çarpan':>8} {'Penalty':>10}")
        print(f"   {'-'*60}")
        for s, info in sorted(early_starts.items(), key=lambda x: x[1]['start']):
            print(f"   {s:<25} {info['start']:<8} {info['count']:>6} {info['multiplier']:>7.1f}x {info['penalty']:>10.2f}")
        print(f"   {'-'*60}")
        print(f"   {'TOPLAM':<25} {'':>8} {early_total:>6} {'':>8} {early_penalty:>10.2f}")

    # Küçük atama raporu
    if mip_info.get('small_shift_penalty_enabled', False):
        small_detail = mip_info.get('small_shifts_detail', [])
        total_shifts = len(mip_info['assignments'])
        ssp_penalty = config.get('small_shift_penalty', {}).get('penalty', 3.0)

        if small_detail:
            print(f"\n🔧 KÜÇÜK ATAMALI SHIFT'LER (≤5 kişi):")
            print(f"   {'Shift':<25} {'Saat':<8} {'Tip':<10} {'Kişi':>6}")
            print(f"   {'-'*55}")
            for sd in sorted(small_detail, key=lambda x: x['start']):
                print(f"   {sd['shift']:<25} {sd['start']:<8} {sd['company']:<10} {sd['count']:>6}")

    # RR penalty raporu
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
                pen = exc * config.get('rr_penalty', {}).get('penalty_per_person', 5.0)
                print(f"   {slot:<8} {e:>7} {m:>7} {exc:>+7} {pen:>10.1f}")

    # Slot cap raporu
    if mip_info.get('sc_penalized_slots', 0) > 0:
        print(f"\n📊 SLOT CAP:")
        print(f"   İhlal: {mip_info['sc_penalized_slots']} slot | "
              f"Fazla: {mip_info['sc_total_excess']} | Penalty: {mip_info['sc_total_penalty_cost']:.1f}")

    # Ek kapasite analizi
    if weighted_aht_by_slot:
        dis_arama_kisi = 0
        dis_arama_cagri = 0
        atil_kisi = 0
        atil_cagri = 0

        for slot in SLOTS_30:
            e = erlang_by_slot.get(slot, 0)
            m = mip_info['mip_by_slot'].get(slot, 0)
            w_aht = weighted_aht_by_slot.get(slot, 0)
            fazla = m - e
            if fazla <= 0:
                continue
            fazla_cagri = fazla * (1800 / w_aht) if w_aht > 0 else 0
            h = int(slot[:2])
            if 9 <= h < 20:
                dis_arama_kisi += fazla
                dis_arama_cagri += fazla_cagri
            else:
                atil_kisi += fazla
                atil_cagri += fazla_cagri

        print(f"\n📊 EK KAPASİTE ANALİZİ:")
        print(f"   {'Metrik':<35} {'Kişi-Slot':>12} {'Çağrı Kap.':>12}")
        print(f"   {'-'*60}")
        print(f"   {'Dış Arama (09:00-20:00)':<35} {dis_arama_kisi:>12} {dis_arama_cagri:>11,.0f}")
        print(f"   {'Atıl (20:00-09:00)':<35} {atil_kisi:>12} {atil_cagri:>11,.0f}")

    # Shift atamaları
    sc = mip_info['shift_coverage']
    mcfg = config['mip']

    print(f"\n📋 SHIFT ATAMALARI ({len(mip_info['assignments'])} shift):")
    print(f"   {'Shift':<22} {'Saat':<12} {'Tip':<10} {'Kişi':>6} {'Maliyet':>10}")
    print(f"   {'-'*65}")

    for s, cnt in sorted(mip_info['assignments'].items(), key=lambda x: sc[x[0]]['start']):
        info = sc[s]
        if info['company'] == 'part_time':
            base_cost = mcfg['cost_inhouse']
            mult = 1.0
        elif info['company'] == 'inhouse':
            base_cost = mcfg['cost_inhouse']
            mult = get_time_cost_multiplier(queue, 'inhouse', info['start'], config)
        else:
            base_cost = mcfg['cost_outsource']
            mult = get_time_cost_multiplier(queue, 'outsource', info['start'], config)

        final_cost = base_cost * mult * cnt
        mult_str = f" ({mult}x)" if mult != 1.0 else ""
        print(f"   {s:<22} {info['start']}-{info['end']:<5} {info['company']:<10} {cnt:>6} {final_cost:>9.2f}{mult_str}")

    in_kisi = mip_info['total_inhouse_kisi']
    out_kisi = mip_info['total_outsource_kisi']
    pt_kisi = mip_info.get('total_part_time_kisi', 0)
    print(f"   {'-'*65}")
    print(f"   {'TOPLAM':<22} {'':>12} {'inhouse':>10} {in_kisi:>6}")
    print(f"   {'':>22} {'':>12} {'outsource':>10} {out_kisi:>6}")
    if pt_kisi > 0:
        print(f"   {'':>22} {'':>12} {'part_time':>10} {pt_kisi:>6}")
    print(f"   {'':>22} {'':>12} {'TOPLAM':>10} {in_kisi + out_kisi + pt_kisi:>6}")

    # Slot bazlı detay
    peak_thr = config.get('report', {}).get('peak_threshold', 0.70)
    if calls_by_slot:
        max_calls = max(calls_by_slot.values()) if calls_by_slot else 0
        peak_slots = {s for s, c in calls_by_slot.items() if c >= max_calls * peak_thr}
    else:
        max_erlang = max(erlang_by_slot.values()) if erlang_by_slot else 0
        peak_slots = {s for s, e in erlang_by_slot.items() if e >= max_erlang * peak_thr}

    in_only_by_slot = mip_info.get('inhouse_min_by_slot', {})
    out_only_by_slot = mip_info.get('outsource_min_by_slot', {})
    has_subq = bool(in_only_by_slot or out_only_by_slot)

    print(f"\n📋 SLOT BAZLI (eşzamanlı çalışan)  * = peak slot")
    if has_subq:
        print(f"   {'Slot':<8} {'W_AHT':>6} {'Erlang':>7} {'InMin':>6} {'OutMin':>7}  "
              f"{'---- MIP ----':^23}  {'---- GERÇEK ----':^23}  {'Fark':>6} {'RR':>7} {'E.Fark':>7}")
        print(f"   {'':>8} {'':>6} {'':>7} {'':>6} {'':>7}  "
              f"{'Toplam':>7} {'Inhouse':>7} {'Outsrc':>7}  "
              f"{'Toplam':>7} {'Inhouse':>7} {'Outsrc':>7}  {'':>6} {'':>7} {'':>7}")
        print(f"   {'-'*115}")
    else:
        print(f"   {'Slot':<8} {'W_AHT':>6} {'Erlang':>7}  "
              f"{'---- MIP ----':^23}  {'---- GERÇEK ----':^23}  {'Fark':>6} {'RR':>7} {'E.Fark':>7}")
        print(f"   {'':>8} {'':>6} {'':>7}  "
              f"{'Toplam':>7} {'Inhouse':>7} {'Outsrc':>7}  "
              f"{'Toplam':>7} {'Inhouse':>7} {'Outsrc':>7}  {'':>6} {'':>7} {'':>7}")
        print(f"   {'-'*106}")

    e_slot_sum = 0
    m_slot_sum = 0
    a_slot_sum = 0

    for slot in SLOTS_30:
        e = erlang_by_slot.get(slot, 0)
        m = mip_info['mip_by_slot'].get(slot, 0)
        mi = mip_info['mip_in_by_slot'].get(slot, 0)
        mo = mip_info['mip_out_by_slot'].get(slot, 0)
        at = actual['slot_total'].get(slot, 0)
        ai = actual['slot_in'].get(slot, 0)
        ao = actual['slot_out'].get(slot, 0)

        e_slot_sum += e
        m_slot_sum += m
        a_slot_sum += at

        if e > 0 or m > 0 or at > 0:
            w_aht = weighted_aht_by_slot.get(slot, 0) if weighted_aht_by_slot else 0
            fark = m - at
            rr_slot = f"{m/e:.0%}" if e > 0 else "-"
            peak_mark = "*" if slot in peak_slots else " "
            e_fark = m - e

            if has_subq:
                in_min = in_only_by_slot.get(slot, 0)
                out_min = out_only_by_slot.get(slot, 0)
                in_min_str = str(in_min) if in_min > 0 else "-"
                out_min_str = str(out_min) if out_min > 0 else "-"
                print(f"   {slot}{peak_mark:<2} {w_aht:>6.0f} {e:>7} {in_min_str:>6} {out_min_str:>7}  "
                      f"{m:>7} {mi:>7} {mo:>7}  {at:>7} {ai:>7} {ao:>7}  {fark:>+6} {rr_slot:>7} {e_fark:>+7}")
            else:
                print(f"   {slot}{peak_mark:<2} {w_aht:>6.0f} {e:>7}  "
                      f"{m:>7} {mi:>7} {mo:>7}  {at:>7} {ai:>7} {ao:>7}  {fark:>+6} {rr_slot:>7} {e_fark:>+7}")

    sep = '-'*115 if has_subq else '-'*106
    print(f"   {sep}")
    e_m_fark = m_slot_sum - e_slot_sum
    print(f"   {'SLOT TOP':<15} {e_slot_sum:>7}  {m_slot_sum:>7} {'':>7} {'':>7}  "
          f"{a_slot_sum:>7} {'':>7} {'':>7}  {m_slot_sum - a_slot_sum:>+6} {'':>7} {e_m_fark:>+7}")
    print(f"\n   Fark = MIP-Gerçek  |  RR = MIP/Erlang  |  E.Fark = MIP-Erlang  |  * = Peak slot")

    # =================================================================
    # SLOT BAZLI KAPASİTE RAPORU (30dk)
    # =================================================================
    hr_cfg = config.get('hourly_report', {})
    if hr_cfg and weighted_aht_by_slot and calls_by_slot:
        rapor_etkisi_cfg = hr_cfg.get('rapor_etkisi', {})
        kap_kaybi_cfg = hr_cfg.get('kapasite_kaybi', {})
        cagri_adedi_cfg = hr_cfg.get('cagri_adedi', {})

        print(f"\n📋 SLOT BAZLI KAPASİTE RAPORU (30dk)")
        print(f"   {'Slot':<7} {'Çağrı':>7} {'Kap.':>6} {'R.Etk':>6} {'K.Kay':>6} {'NetMT':>6} {'Ç.Kap':>7} {'RR':>7}")
        print(f"   {'-'*55}")

        total_cagri = 0
        total_cap = 0
        total_retki = 0
        total_kkaybi = 0
        total_netmt = 0
        total_ckap = 0

        for slot in SLOTS_30:
            h = int(slot[:2])
            cagri = int(calls_by_slot.get(slot, 0))
            kapasite = mip_info['mip_by_slot'].get(slot, 0)

            if cagri == 0 and kapasite == 0:
                continue

            re_oran = rapor_etkisi_cfg.get(h, rapor_etkisi_cfg.get('default', 0))
            rapor_etki = round(kapasite * re_oran)

            kk_oran = kap_kaybi_cfg.get(h, kap_kaybi_cfg.get('default', 0))
            kap_kaybi = round(kapasite * kk_oran)

            net_mt = kapasite - rapor_etki - kap_kaybi

            ca = cagri_adedi_cfg.get(h, cagri_adedi_cfg.get('default', 15))
            cagri_kap = net_mt * (ca / 2)

            rr = cagri_kap / cagri if cagri > 0 else 0

            total_cagri += cagri
            total_cap += kapasite
            total_retki += rapor_etki
            total_kkaybi += kap_kaybi
            total_netmt += net_mt
            total_ckap += cagri_kap

            warn = " ⚠" if rr < 1.0 and cagri > 0 else ""
            print(f"   {slot:<7} {cagri:>7} {kapasite:>6} {rapor_etki:>6} {kap_kaybi:>6} {net_mt:>6} {cagri_kap:>7.0f} {rr:>6.0%}{warn}")

        print(f"   {'-'*55}")
        total_rr = total_ckap / total_cagri if total_cagri > 0 else 0
        print(f"   {'TOPLAM':<7} {total_cagri:>7} {total_cap:>6} {total_retki:>6} {total_kkaybi:>6} {total_netmt:>6} {total_ckap:>7.0f} {total_rr:>6.0%}")


# =============================================================================
# 10.4 SURPLUS DAĞITIM (Aşama 2 — sadece haftaiçi inhouse)
# =============================================================================

def distribute_surplus(mip_info, queue, erlang_by_slot, config=CONFIG, verbose=True):
    """
    MIP'in (Aşama 1) çıkardığı min ihtiyaç planının üzerine, configdeki
    inhouse kadrosundan kalan fazla kişileri çoklu zaman penceresine yayar.

    Kurallar:
      - Sadece inhouse. Outsource'a dokunulmaz.
      - Surplus, configdeki pencere oranlarına göre paylara bölünür.
        Örn: sabah 2/3, akşam 1/3.
      - Her pencerenin aday seti: MIP'in atadığı (count > 0) ve başlangıç saati
        o pencere içinde olan inhouse shift'ler.
      - Bir pencerede aday yoksa o pay diğer pencerelere devredilir.
      - Hiçbir pencerede aday yoksa ve fallback_all_inhouse=True ise →
        tüm atanmış inhouse shift'lere yayılır.
      - Her pencere içinde method='rr_first' ise: önce RR<%100 olan slotları
        kapatan shift'lere greedy, kalanı MIP ağırlığına oransal.
      - Shift bazlı tavan yok.

    mip_info'yu yerinde günceller:
      - assignments[s] arttırılır
      - mip_by_slot, mip_in_by_slot yeniden hesaplanır
      - total_kisi, total_inhouse_kisi, outsource_ratio güncellenir
      - 'surplus_added' (shift bazlı toplam) ve 'surplus_by_window' eklenir
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

    # Hiçbir pencerede aday yoksa → fallback
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

    # --- Surplus'ı pencere paylarına böl (largest-remainder) ---
    # Aday olmayan pencerelerin payı, aday olanlara orantılı dağıtılır
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

    # --- Her pencere için RR-fix + oransal dağıtım ---
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
                  f"pay={share}, RR-fix={used_rr}, oransal={used_prop}")

    # --- mip_info'yu güncelle ---
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
    """
    Tek bir aday havuzu için RR-fix + oransal dağıtım.
    mip_by_slot_state'i yerinde günceller (sonraki pencere bunu görür).
    Döner: (added_dict, used_rr, used_proportional)
    """
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

    # 2) Oransal (MIP ağırlığına göre)
    if remaining > 0:
        weights = {s: assignments.get(s, 0) for s in candidates}
        weight_sum = sum(weights.values())

        if weight_sum == 0:
            n = len(candidates)
            base = remaining // n
            extra = remaining - base * n
            for i, s in enumerate(candidates):
                inc = base + (1 if i < extra else 0)
                added[s] += inc
                for slot in shift_cov[s]['slots']:
                    mip_by_slot_state[slot] = mip_by_slot_state.get(slot, 0) + inc
            used_prop += remaining
            remaining = 0
        else:
            raw = {s: remaining * (weights[s] / weight_sum) for s in candidates}
            floors = {s: int(raw[s]) for s in candidates}
            leftover = remaining - sum(floors.values())
            fracs = sorted(
                ((s, raw[s] - floors[s]) for s in candidates),
                key=lambda x: x[1], reverse=True
            )
            for i in range(leftover):
                floors[fracs[i][0]] += 1
            for s in candidates:
                inc = floors[s]
                added[s] += inc
                for slot in shift_cov[s]['slots']:
                    mip_by_slot_state[slot] = mip_by_slot_state.get(slot, 0) + inc
            used_prop += remaining
            remaining = 0

    return added, used_rr, used_prop

# =============================================================================
# 10.5 INHOUSE/OUTSOURCE MİNİMUM HESAPLAMA
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
# 11. ANA AKIŞ
# =============================================================================

def run_queue_pipeline(df_calls, df_actual, df_shifts, target_date, queue,
                       config=CONFIG, verbose=True):

    import copy
    target_date = pd.to_datetime(target_date)
    date_str = target_date.strftime('%Y-%m-%d')
    weekday = target_date.weekday()

    # Gün tipi belirle
    if weekday < 5:
        override_key = 'haftalici'
    elif weekday == 5:
        override_key = 'cumartesi'
    else:
        override_key = 'pazar'

    is_weekend = weekday >= 5
    day_label = {'haftalici': 'Haftaiçi', 'cumartesi': 'Cumartesi', 'pazar': 'Pazar'}[override_key]

    # Queue override uygula (deep merge — sadece değişen anahtarları yaz yeterli)
    overrides = config.get('queue_overrides', {}).get(queue, {}).get(override_key, {})
    if overrides:
        config = copy.deepcopy(config)
        def _deep_merge(base, override):
            """Override'daki anahtarları base'e recursive merge eder."""
            for key, val in override.items():
                if key in base and isinstance(base[key], dict) and isinstance(val, dict):
                    _deep_merge(base[key], val)
                else:
                    base[key] = val
        _deep_merge(config, overrides)
        if verbose:
            print(f"   📌 Override aktif: {queue}/{override_key} → {list(overrides.keys())}")

    label = config['queues'][queue]['label']

    if isinstance(df_shifts, dict):
        df_shifts_queue = df_shifts.get(queue)
        if df_shifts_queue is None:
            raise ValueError(f"'{queue}' için shift verisi bulunamadı.")
    else:
        df_shifts_queue = df_shifts

    if verbose:
        print(f"\n{'='*95}")
        print(f"PİPELİNE v10.9 ACTUAL: {label} ({queue.upper()}) - {date_str} [{day_label}]")
        print(f"{'='*95}")

    if verbose: print(f"\n[1/4] Veri hazırlama (weighted AHT)...")
    df_calls_30 = prepare_calls_30(df_calls, config)

    if verbose: print(f"\n[2/4] Erlang hesaplama (weighted AHT + shrinkage)...")
    df_erlang = calculate_erlang_all(df_calls_30, config)

    df_erlang_day = df_erlang[
        (df_erlang['date'] == target_date) & (df_erlang['queue'] == queue)
    ].copy()

    erlang_by_slot = dict(zip(df_erlang_day['slot'], df_erlang_day['erlang_need']))
    weighted_aht_by_slot = dict(zip(df_erlang_day['slot'], df_erlang_day['weighted_aht']))

    if verbose:
        e_total = sum(erlang_by_slot.values())
        e_peak = max(erlang_by_slot.values()) if erlang_by_slot else 0
        avg_aht = df_erlang_day['weighted_aht'].mean() if len(df_erlang_day) > 0 else 0
        print(f"   Erlang: toplam={e_total}, peak={e_peak}, avg_weighted_aht={avg_aht:.0f}")

    inhouse_min_by_slot, outsource_min_by_slot = _build_subqueue_min_slots(
        df_calls_30, queue, target_date, erlang_by_slot, config
    )

    if verbose:
        if inhouse_min_by_slot:
            active_in = {k: v for k, v in inhouse_min_by_slot.items() if v > 0}
            total_in_min = sum(active_in.values())
            print(f"   Inhouse-only kısıt: {len(active_in)} slotta aktif, toplam min={total_in_min}")
        if outsource_min_by_slot:
            active_out = {k: v for k, v in outsource_min_by_slot.items() if v > 0}
            total_out_min = sum(active_out.values())
            print(f"   Outsource-only kısıt: {len(active_out)} slotta aktif, toplam min={total_out_min}")

    if verbose: print(f"[3/4] MIP optimizasyon...")
    assignments, mip_info = optimize_queue(
        erlang_by_slot, df_shifts_queue, queue,
        target_date=target_date,
        inhouse_min_by_slot=inhouse_min_by_slot,
        outsource_min_by_slot=outsource_min_by_slot,
        config=config
    )

    if assignments is None:
        print(f"   ⚠ Çözüm bulunamadı: {mip_info}")
        return None

    if verbose:
        pt_info = ""
        if mip_info.get('total_part_time_kisi', 0) > 0:
            pt_info = f", PT: {mip_info['total_part_time_kisi']}/{mip_info['pt_available']}"
        print(f"   MIP: {mip_info['total_kisi']} kişi "
              f"(In: {mip_info['total_inhouse_kisi']}, Out: {mip_info['total_outsource_kisi']}{pt_info}, "
              f"Oran: {mip_info['outsource_ratio']:.1%})")

    # --- Aşama 2: Surplus dağıtımı (sadece haftaiçi) ---
    if not is_weekend and config.get('surplus_distribution', {}).get('enabled', False):
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
                       config=config)

    return {
        'date': target_date,
        'queue': queue,
        'label': label,
        'day_type': override_key,
        'erlang_by_slot': erlang_by_slot,
        'weighted_aht_by_slot': weighted_aht_by_slot,
        'mip_info': mip_info,
        'actual': actual,
        'total_calls_day': total_calls_day,
        'calls_by_slot': calls_by_slot,
        'inhouse_min_by_slot': inhouse_min_by_slot,
        'outsource_min_by_slot': outsource_min_by_slot,
        '_config': config,  # override uygulanmış config
    }


def run_all_queues(df_calls, df_actual, df_shifts, target_date, config=CONFIG):
    results = {}
    for queue in config['queues']:
        result = run_queue_pipeline(
            df_calls, df_actual, df_shifts, target_date, queue, config=config
        )
        if result:
            results[queue] = result

    target_date = pd.to_datetime(target_date)
    day_label = 'Haftasonu' if target_date.weekday() >= 5 else 'Haftaiçi'

    print(f"\n{'='*95}")
    print(f"TÜM KUYRUKLAR - {target_date.strftime('%Y-%m-%d')} [{day_label}]")
    print(f"{'='*95}")
    print(f"{'Kuyruk':<12} {'MIP':>8} {'Grç':>8} {'Fark':>6} "
          f"{'In':>6} {'Out':>6} {'PT':>5} {'MIP%':>7} {'Grç%':>7} {'Shift':>6} {'RR':>8}")
    print(f"{'-'*85}")

    for q, r in results.items():
        mi = r['mip_info']
        a = r['actual']
        fark = mi['total_kisi'] - a['kisi_total']
        pt = mi.get('total_part_time_kisi', 0)
        n_shifts = len(mi['assignments'])

        w_aht = r.get('weighted_aht_by_slot', {})
        calls = r.get('total_calls_day', 0)
        if w_aht and calls > 0:
            cap = calculate_daily_capacity(mi, w_aht, config)
            rr = f"{cap['total_capacity'] / calls:.1%}"
        else:
            rr = "-"

        print(f"{r['label']:<12} {mi['total_kisi']:>8} {a['kisi_total']:>8} {fark:>+6} "
              f"{mi['total_inhouse_kisi']:>6} {mi['total_outsource_kisi']:>6} {pt:>5} "
              f"{mi['outsource_ratio']:>6.1%} {a['outsource_ratio']:>6.1%} {n_shifts:>6} {rr:>8}")

    # Toplam (tüm kuyruklar) kapasite RR — her kuyruk kendi override config'i ile
    t_mip = t_grc = t_in = t_out = t_pt = 0
    t_cagri_kap = t_cagri_gelen = t_calls = 0

    for q, r in results.items():
        mi = r['mip_info']; a = r['actual']
        t_mip += mi['total_kisi']; t_grc += a['kisi_total']
        t_in += mi['total_inhouse_kisi']; t_out += mi['total_outsource_kisi']
        t_pt += mi.get('total_part_time_kisi', 0)
        t_calls += r.get('total_calls_day', 0)

        # Bu kuyruğun override edilmiş config'ini kullan
        q_cfg = r.get('_config', config)
        q_hr = q_cfg.get('hourly_report', {})
        q_re = q_hr.get('rapor_etkisi', {})
        q_kk = q_hr.get('kapasite_kaybi', {})
        q_ca = q_hr.get('cagri_adedi', {})

        calls_by_slot = r.get('calls_by_slot', {})
        for slot in SLOTS_30:
            h = int(slot[:2])
            cagri = int(calls_by_slot.get(slot, 0))
            kap = mi['mip_by_slot'].get(slot, 0)
            if cagri == 0 and kap == 0: continue
            re = round(kap * q_re.get(h, q_re.get('default', 0)))
            kk = round(kap * q_kk.get(h, q_kk.get('default', 0)))
            net = kap - re - kk
            ca = q_ca.get(h, q_ca.get('default', 15))
            t_cagri_kap += net * (ca / 2)
            t_cagri_gelen += cagri

    t_kap_rr = t_cagri_kap / t_cagri_gelen if t_cagri_gelen > 0 else 0
    t_out_pct = t_out / t_mip if t_mip > 0 else 0

    print(f"{'-'*85}")
    print(f"{'TOPLAM':<12} {t_mip:>8} {t_grc:>8} {t_mip-t_grc:>+6} "
          f"{t_in:>6} {t_out:>6} {t_pt:>5} {t_out_pct:>6.1%} {'':>7} {'':>6} {t_kap_rr:>7.1%}")
    print(f"\n   Toplam Çağrı: {t_calls:,} | Kapasite RR: {t_kap_rr:.1%}")

    return results


# =============================================================================
# 12. EXCEL EXPORT
# =============================================================================

def export_to_excel(df_calls, df_actual, df_shifts, dates, queues=None,
                    output_file=None, config=CONFIG):

    if queues is None:
        queues = list(config['queues'].keys())

    # Otomatik dosya adı: tarih aralığı ile
    if output_file is None:
        dates_pd = [pd.to_datetime(d) for d in dates]
        first = min(dates_pd).strftime('%Y%m%d')
        last = max(dates_pd).strftime('%Y%m%d')
        if first == last:
            output_file = f'vardiya_actual_{first}.xlsx'
        else:
            output_file = f'vardiya_actual_{first}_{last}.xlsx'

    all_assignments = []
    all_slots = []
    all_summary = []

    print(f"\n{'='*70}")
    print(f"EXCEL EXPORT - {len(dates)} tarih, {len(queues)} kuyruk")
    print(f"{'='*70}")

    for i, date in enumerate(dates):
        date = pd.to_datetime(date)
        date_str = date.strftime('%Y-%m-%d')
        day_name = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz'][date.weekday()]
        is_weekend = date.weekday() >= 5
        day_type_label = 'Haftasonu' if is_weekend else 'Haftaiçi'

        print(f"\n[{i+1}/{len(dates)}] {date_str} ({day_name}) - {day_type_label}")

        for queue in queues:
            label = config['queues'][queue]['label']

            result = run_queue_pipeline(
                df_calls, df_actual, df_shifts, date, queue,
                config=config, verbose=False
            )

            if result is None:
                print(f"   ⚠ {label}: Çözüm bulunamadı")
                continue

            mip_info = result['mip_info']
            actual = result['actual']
            erlang_by_slot = result['erlang_by_slot']
            weighted_aht_by_slot = result.get('weighted_aht_by_slot', {})
            total_calls_day = result.get('total_calls_day', 0)
            sc = mip_info['shift_coverage']

            for shift, count in mip_info['assignments'].items():
                info = sc[shift]
                all_assignments.append({
                    'Tarih': date_str, 'Gün': day_name, 'Tip': day_type_label,
                    'Kuyruk': label, 'Shift': shift,
                    'Başlangıç': info['start'], 'Bitiş': info['end'],
                    'Company': info['company'], 'Kişi_Sayısı': count
                })

            in_only_by_slot = mip_info.get('inhouse_min_by_slot', {})
            out_only_by_slot = mip_info.get('outsource_min_by_slot', {})
            calls_by_slot = result.get('calls_by_slot', {})
            q_config = result.get('_config', config)
            hr_cfg = q_config.get('hourly_report', {})
            re_cfg = hr_cfg.get('rapor_etkisi', {})
            kk_cfg = hr_cfg.get('kapasite_kaybi', {})
            ca_cfg = hr_cfg.get('cagri_adedi', {})

            for slot in SLOTS_30:
                e = erlang_by_slot.get(slot, 0)
                m = mip_info['mip_by_slot'].get(slot, 0)
                m_in = mip_info['mip_in_by_slot'].get(slot, 0)
                m_out = mip_info['mip_out_by_slot'].get(slot, 0)
                m_pt = mip_info.get('mip_pt_by_slot', {}).get(slot, 0)
                a = actual['slot_total'].get(slot, 0)
                a_in = actual['slot_in'].get(slot, 0)
                a_out = actual['slot_out'].get(slot, 0)
                w_aht = weighted_aht_by_slot.get(slot, 0)
                rr_slot = round(m / e, 3) if e > 0 else None

                # Kapasite raporu
                h = int(slot[:2])
                cagri = int(calls_by_slot.get(slot, 0))
                re_oran = re_cfg.get(h, re_cfg.get('default', 0))
                kk_oran = kk_cfg.get(h, kk_cfg.get('default', 0))
                ca = ca_cfg.get(h, ca_cfg.get('default', 15))
                rapor_etki = round(m * re_oran)
                kap_kaybi = round(m * kk_oran)
                net_mt = m - rapor_etki - kap_kaybi
                cagri_kap = net_mt * (ca / 2)
                kap_rr = round(cagri_kap / cagri, 3) if cagri > 0 else None

                if e > 0 or m > 0 or a > 0:
                    all_slots.append({
                        'Tarih': date_str, 'Gün': day_name, 'Tip': day_type_label,
                        'Kuyruk': label, 'Slot': slot,
                        'Weighted_AHT': w_aht, 'Erlang': e,
                        'Inhouse_Min': in_only_by_slot.get(slot, 0),
                        'Outsource_Min': out_only_by_slot.get(slot, 0),
                        'MIP_Toplam': m, 'MIP_Inhouse': m_in,
                        'MIP_Outsource': m_out, 'MIP_PartTime': m_pt,
                        'Gerçek_Toplam': a, 'Gerçek_Inhouse': a_in,
                        'Gerçek_Outsource': a_out, 'Fark_MIP_Gerçek': m - a,
                        'Response_Rate_Slot': rr_slot,
                        'Çağrı': cagri, 'Rapor_Etkisi': rapor_etki,
                        'Kapasite_Kaybı': kap_kaybi, 'Net_MT': net_mt,
                        'Çağrı_Kapasitesi': round(cagri_kap),
                        'Kapasite_RR': kap_rr,
                    })

            avg_aht = sum(weighted_aht_by_slot.values()) / len(weighted_aht_by_slot) \
                      if weighted_aht_by_slot else 0

            cap = calculate_daily_capacity(mip_info, weighted_aht_by_slot, config) \
                  if weighted_aht_by_slot else {}
            total_cap = cap.get('total_capacity', 0)
            daily_rr = round(total_cap / total_calls_day, 3) if total_calls_day > 0 else None

            # Kapasite raporu bazlı toplam RR (weighted — doğru hesap)
            toplam_cagri_kap = 0
            toplam_cagri_gelen = 0
            for slot in SLOTS_30:
                h = int(slot[:2])
                cagri = int(calls_by_slot.get(slot, 0))
                kap = mip_info['mip_by_slot'].get(slot, 0)
                if cagri == 0 and kap == 0: continue
                re = round(kap * re_cfg.get(h, re_cfg.get('default', 0)))
                kk = round(kap * kk_cfg.get(h, kk_cfg.get('default', 0)))
                net = kap - re - kk
                ca = ca_cfg.get(h, ca_cfg.get('default', 15))
                toplam_cagri_kap += net * (ca / 2)
                toplam_cagri_gelen += cagri
            kapasite_rr_gunluk = round(toplam_cagri_kap / toplam_cagri_gelen, 3) if toplam_cagri_gelen > 0 else None

            all_summary.append({
                'Tarih': date_str, 'Gün': day_name, 'Tip': day_type_label,
                'Kuyruk': label,
                'MIP_Toplam': mip_info['total_kisi'],
                'MIP_Inhouse': mip_info['total_inhouse_kisi'],
                'MIP_Outsource': mip_info['total_outsource_kisi'],
                'MIP_PartTime': mip_info.get('total_part_time_kisi', 0),
                'MIP_Out%': round(mip_info['outsource_ratio'] * 100, 1),
                'Aktif_Shift': len(mip_info['assignments']),
                'Avg_Weighted_AHT': round(avg_aht, 1),
                'Toplam_Cagri': total_calls_day,
                'Gunluk_Kapasite': total_cap,
                'Response_Rate_Gunluk': daily_rr,
                'Gerçek_Toplam': actual['kisi_total'],
                'Gerçek_Inhouse': actual['kisi_in'],
                'Gerçek_Outsource': actual['kisi_out'],
                'Gerçek_Out%': round(actual['outsource_ratio'] * 100, 1),
                'Fark_Toplam': mip_info['total_kisi'] - actual['kisi_total'],
                'Kapasite_RR_Gunluk': kapasite_rr_gunluk,
            })

            rr_str = f"{daily_rr:.1%}" if daily_rr else "-"
            print(f"   ✓ {label}: {mip_info['total_kisi']} kişi (MIP) vs {actual['kisi_total']} (Gerçek) | RR: {rr_str}")

        # Tarih bazlı TOPLAM satırı — bu tarihteki tüm kuyrukları topla
        date_summaries = [s for s in all_summary if s['Tarih'] == date_str and s['Kuyruk'] != 'TOPLAM']
        if date_summaries:
            t_mip = sum(s['MIP_Toplam'] for s in date_summaries)
            t_in = sum(s['MIP_Inhouse'] for s in date_summaries)
            t_out = sum(s['MIP_Outsource'] for s in date_summaries)
            t_pt = sum(s['MIP_PartTime'] for s in date_summaries)
            t_grc = sum(s['Gerçek_Toplam'] for s in date_summaries)
            t_grc_in = sum(s['Gerçek_Inhouse'] for s in date_summaries)
            t_grc_out = sum(s['Gerçek_Outsource'] for s in date_summaries)
            t_calls = sum(s['Toplam_Cagri'] for s in date_summaries)
            t_cap = sum(s['Gunluk_Kapasite'] for s in date_summaries)

            # Kapasite RR: slot bazlı weighted hesap (all_slots'tan)
            date_slots = [s for s in all_slots if s['Tarih'] == date_str]
            t_ckap = sum(s.get('Çağrı_Kapasitesi', 0) or 0 for s in date_slots)
            t_cgelen = sum(s.get('Çağrı', 0) or 0 for s in date_slots)
            t_kap_rr = round(t_ckap / t_cgelen, 3) if t_cgelen > 0 else None

            all_summary.append({
                'Tarih': date_str, 'Gün': day_name, 'Tip': day_type_label,
                'Kuyruk': 'TOPLAM',
                'MIP_Toplam': t_mip, 'MIP_Inhouse': t_in,
                'MIP_Outsource': t_out, 'MIP_PartTime': t_pt,
                'MIP_Out%': round(t_out / t_mip * 100, 1) if t_mip > 0 else 0,
                'Aktif_Shift': None, 'Avg_Weighted_AHT': None,
                'Toplam_Cagri': t_calls,
                'Gunluk_Kapasite': t_cap,
                'Response_Rate_Gunluk': round(t_cap / t_calls, 3) if t_calls > 0 else None,
                'Gerçek_Toplam': t_grc, 'Gerçek_Inhouse': t_grc_in,
                'Gerçek_Outsource': t_grc_out,
                'Gerçek_Out%': round(t_grc_out / t_grc * 100, 1) if t_grc > 0 else 0,
                'Fark_Toplam': t_mip - t_grc,
                'Kapasite_RR_Gunluk': t_kap_rr,
            })

        # Slot bazlı TOPLAM satırları (tüm kuyruklar toplanmış)
        date_slots = [s for s in all_slots if s['Tarih'] == date_str and s['Kuyruk'] != 'TOPLAM']
        if date_slots:
            slot_agg = {}
            for s in date_slots:
                slot = s['Slot']
                if slot not in slot_agg:
                    slot_agg[slot] = {
                        'MIP_Toplam': 0, 'MIP_Inhouse': 0, 'MIP_Outsource': 0, 'MIP_PartTime': 0,
                        'Erlang': 0, 'Gerçek_Toplam': 0, 'Gerçek_Inhouse': 0, 'Gerçek_Outsource': 0,
                        'Çağrı': 0, 'Rapor_Etkisi': 0, 'Kapasite_Kaybı': 0, 'Net_MT': 0,
                        'Çağrı_Kapasitesi': 0,
                    }
                sa = slot_agg[slot]
                sa['MIP_Toplam'] += s.get('MIP_Toplam', 0) or 0
                sa['MIP_Inhouse'] += s.get('MIP_Inhouse', 0) or 0
                sa['MIP_Outsource'] += s.get('MIP_Outsource', 0) or 0
                sa['MIP_PartTime'] += s.get('MIP_PartTime', 0) or 0
                sa['Erlang'] += s.get('Erlang', 0) or 0
                sa['Gerçek_Toplam'] += s.get('Gerçek_Toplam', 0) or 0
                sa['Gerçek_Inhouse'] += s.get('Gerçek_Inhouse', 0) or 0
                sa['Gerçek_Outsource'] += s.get('Gerçek_Outsource', 0) or 0
                sa['Çağrı'] += s.get('Çağrı', 0) or 0
                sa['Rapor_Etkisi'] += s.get('Rapor_Etkisi', 0) or 0
                sa['Kapasite_Kaybı'] += s.get('Kapasite_Kaybı', 0) or 0
                sa['Net_MT'] += s.get('Net_MT', 0) or 0
                sa['Çağrı_Kapasitesi'] += s.get('Çağrı_Kapasitesi', 0) or 0

            for slot in SLOTS_30:
                if slot not in slot_agg: continue
                sa = slot_agg[slot]
                rr_slot = round(sa['MIP_Toplam'] / sa['Erlang'], 3) if sa['Erlang'] > 0 else None
                kap_rr = round(sa['Çağrı_Kapasitesi'] / sa['Çağrı'], 3) if sa['Çağrı'] > 0 else None
                all_slots.append({
                    'Tarih': date_str, 'Gün': day_name, 'Tip': day_type_label,
                    'Kuyruk': 'TOPLAM', 'Slot': slot,
                    'Weighted_AHT': None, 'Erlang': sa['Erlang'],
                    'Inhouse_Min': None, 'Outsource_Min': None,
                    'MIP_Toplam': sa['MIP_Toplam'], 'MIP_Inhouse': sa['MIP_Inhouse'],
                    'MIP_Outsource': sa['MIP_Outsource'], 'MIP_PartTime': sa['MIP_PartTime'],
                    'Gerçek_Toplam': sa['Gerçek_Toplam'], 'Gerçek_Inhouse': sa['Gerçek_Inhouse'],
                    'Gerçek_Outsource': sa['Gerçek_Outsource'],
                    'Fark_MIP_Gerçek': sa['MIP_Toplam'] - sa['Gerçek_Toplam'],
                    'Response_Rate_Slot': rr_slot,
                    'Çağrı': sa['Çağrı'], 'Rapor_Etkisi': sa['Rapor_Etkisi'],
                    'Kapasite_Kaybı': sa['Kapasite_Kaybı'], 'Net_MT': sa['Net_MT'],
                    'Çağrı_Kapasitesi': sa['Çağrı_Kapasitesi'],
                    'Kapasite_RR': kap_rr,
                })

    df_assignments = pd.DataFrame(all_assignments)
    df_slots = pd.DataFrame(all_slots)
    df_summary = pd.DataFrame(all_summary)

    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        df_assignments.to_excel(writer, sheet_name='Vardiya_Atamaları', index=False)
        df_slots.to_excel(writer, sheet_name='Slot_Karşılaştırma', index=False)
        df_summary.to_excel(writer, sheet_name='Özet', index=False)

    print(f"\n✅ Excel: {output_file}")
    print(f"   Vardiya: {len(df_assignments)} | Slot: {len(df_slots)} | Özet: {len(df_summary)}")

    return {'assignments': df_assignments, 'slots': df_slots, 'summary': df_summary}
