# =============================================================================
# HAFTALIK MIP PİPELİNE - ACTUAL V9 (WEEKLY, HAFTAİÇİ)
# =============================================================================
#
# V9 = V8 + STAGE 4 (Coverage Shortfall — eksik kapsama izni)
#
# V8 fallback ladder'ı korunur, sonuna 4. aşama eklenir:
#
#   AŞAMA 1) Orijinal config
#   AŞAMA 2) PER-DAY shrinkage azaltma (çağrı sırasıyla, en yoğun gün önce)
#   AŞAMA 3) PER-DAY min_per_shift azaltma (çağrı sırasıyla, en yoğun gün önce)
#   AŞAMA 4) COVERAGE SHORTFALL — YENİ (V9)
#            - Stage 1-3 tükenmiş ve hâlâ infeasible
#            - Coverage kısıtı YUMUŞATILIR: covered + shortfall ≥ erlang_need
#            - shortfall'a yüksek penalty (örn. 1000) → MIP son çare olarak kullanır
#            - MIP en az hasarlı slot'larda eksik bırakır (cost minimization)
#            - ASLA infeasible değil — her zaman çözüm bulur
#            - info_per_day[d]['shortfall_by_slot'] = {slot: eksik_kişi}
#            - info_per_day[d]['total_shortfall'] = toplam eksik kişi-slot
#
# YENİ CONFIG ANAHTARI (queue_configs[Q]['mip']):
#   'coverage_shortfall': {       # V9'de YENİ
#       'enabled': True, 'penalty': 1000,
#   },
#
# Davranış:
#   - Stage 1-3 zaten çözerse Stage 4 hiç çalışmaz, hiçbir fark yok
#   - Stage 1-3 hepsi infeasible olursa Stage 4 devreye girer
#   - Stage 4 ÇOĞU ZAMAN çözer (shortfall ile esnek)
#   - Çıktıda eksik kapsama detayı + "kabaca X ek kadro lazım" tahmini
#
# Geriye uyumlu: coverage_shortfall.enabled=False ise V8 ile aynı davranış.
# Pipeline'ın diğer fonksiyonları V8 ile birebir aynı.
# =============================================================================

import pandas as pd
import numpy as np
import math
import calendar
import copy
from pulp import *

# CONFIG dışarıdan gelir (Jupyter hücresinde tanımlı), bu modül tek başına
# çalıştırılırken default olarak None — her fonksiyon çağrısında explicit verilmeli.
CONFIG = None


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


def _classify_shift(s, shift_cov, queue, pt_shift_keys, inhouse_value, mcfg, config):
    """Bir vardiya için (company_type, base_cost, multiplier, start_hour) döner."""
    start_h = shift_cov[s]['start']
    if s in pt_shift_keys:
        return ('part_time', mcfg['cost_inhouse'],
                get_time_cost_multiplier(queue, 'inhouse', start_h, config), start_h)
    if shift_cov[s]['company'] == inhouse_value:
        return ('inhouse', mcfg['cost_inhouse'],
                get_time_cost_multiplier(queue, 'inhouse', start_h, config), start_h)
    return ('outsource', mcfg['cost_outsource'],
            get_time_cost_multiplier(queue, 'outsource', start_h, config), start_h)


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
# 3. MIP OPTİMİZASYON (V4 — Balans Penalty, cross-queue kaldırıldı)
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
                   min_per_shift_override=None):
    """
    V6 MIP — V5 + pencere bazlı start_smoothing (her pencere kendi penalty'si).
    min_per_shift_override: None ise config'teki default kullanılır, aksi halde
    mcfg['min_per_shift'] yerine bu değer geçerli olur. Overrides dict (saat-özel)
    yine kendi değerlerini korur.
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

    # --- Small shift penalty ---
    ssp_cfg = qconfigs.get('small_shift_penalty', {})
    ssp_enabled = ssp_cfg.get('enabled', False)
    ssp_penalty = ssp_cfg.get('penalty', 3.0)

    # --- RR Penalty ---
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

    # --- Shift maliyetleri (V3: eşit maliyet) ---
    for s in shifts:
        company_type, base_cost, multiplier, start_hour = _classify_shift(
            s, shift_cov, queue, pt_shift_keys, inhouse_value, mcfg, config)

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

    # --- RR Penalty ---
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

    # --- Slot Cap ---
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

    # =========================================================================
    # V3 — PENCERE BAZLI BALANS PENALTY
    # =========================================================================
    bp_cfg = qconfigs.get('balance_penalty', config.get('balance_penalty', {}))
    bp_enabled = bp_cfg.get('enabled', False) and not only_inhouse
    bp_windows = bp_cfg.get('windows', [])
    bp_penalty = bp_cfg.get('penalty_per_diff', 2.0)
    balance_vars = {}

    if bp_enabled and in_shifts and out_shifts:
        for win in bp_windows:
            win_name = win['name']
            win_start = win['start']
            win_end = win['end']

            win_in = [s for s in in_shifts
                      if win_start <= shift_cov[s]['start'] <= win_end]
            win_out = [s for s in out_shifts
                       if win_start <= shift_cov[s]['start'] <= win_end]

            if not win_in or not win_out:
                continue

            diff_pos = LpVariable(f"bp_{win_name}_pos", lowBound=0, cat='Continuous')
            diff_neg = LpVariable(f"bp_{win_name}_neg", lowBound=0, cat='Continuous')

            in_total_expr = lpSum([x[s] for s in win_in])
            out_total_expr = lpSum([x[s] for s in win_out])
            prob += diff_pos - diff_neg == in_total_expr - out_total_expr

            win_penalty = win.get('penalty', bp_penalty)
            cost.append((diff_pos + diff_neg) * win_penalty)

            balance_vars[win_name] = {
                'diff_pos': diff_pos, 'diff_neg': diff_neg,
                'in_shifts': win_in, 'out_shifts': win_out,
                'penalty': win_penalty
            }

    # --- Kısıtlar ---
    for slot in active_slots:
        covering = [s for s in shifts if slot in shift_cov[s]['slots']]
        if covering:
            prob += lpSum([x[s] for s in covering]) >= erlang_by_slot[slot]

    M = 500
    min_per_shift_default = min_per_shift_override if min_per_shift_override is not None else mcfg['min_per_shift']
    min_per_shift_overrides = mcfg.get('min_per_shift_overrides', {})
    for s in shifts:
        prob += x[s] <= M * y[s]
        start_hour = shift_cov[s]['start']
        min_for_shift = min_per_shift_overrides.get(start_hour, min_per_shift_default)
        prob += x[s] >= min_for_shift * y[s]

    if pt_available > 0 and pt_shift_keys:
        prob += lpSum([x[s] for s in pt_shift_keys]) == pt_available

    # Outsource oran kısıtı (V3'te genelde kapalı)
    out_cfg = config.get('outsource_ratio', {}).get(queue) if isinstance(config.get('outsource_ratio'), dict) else None
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
                if covering_in + covering_pt:
                    prob += lpSum([x[s] for s in covering_in + covering_pt]) >= min_in

    if outsource_min_by_slot:
        for slot, min_out in outsource_min_by_slot.items():
            if min_out > 0:
                covering_out = [s for s in out_shifts if slot in shift_cov[s]['slots']]
                if covering_out:
                    prob += lpSum([x[s] for s in covering_out]) >= min_out

    # Kadro tavanı (V3: hem inhouse hem outsource)
    kadro_cfg = config.get('surplus_distribution', {}).get('total_kadro', {}).get(queue, {})
    kadro_in = kadro_cfg.get('inhouse', 0)
    kadro_out = kadro_cfg.get('outsource', 0)
    if kadro_in > 0 and in_shifts:
        prob += lpSum([x[s] for s in in_shifts]) <= kadro_in
    if kadro_out > 0 and out_shifts:
        prob += lpSum([x[s] for s in out_shifts]) <= kadro_out

    # Start smoothing — sadece AKTİF komşu saatler arasında ceza uygular.
    # yh[h] = "h saatinde en az bir shift aktif mi" binary göstergesi.
    # link[i,j] = 1 ⇔ h_i ve h_j ikisi de aktif VE aralarındaki tüm saatler kapalı
    # (yani "ardışık aktif komşular"). Ceza sadece link=1 olan çiftlerde devrede.
    #
    # V6: pencere bazlı. Her pencere kendi penalty değeri ile config edilir.
    # Smoothing yalnızca aynı pencere içindeki ardışık aktif saatler arasında
    # uygulanır — pencereler arası fark cezasız (örn. sabah ile öğlen-sonrası
    # birbirine eşitlenmeye zorlanmaz). 'windows' yoksa eski format kullanılır.
    sm_cfg = qconfigs.get('start_smoothing', {})
    if sm_cfg.get('enabled', False):
        sm_companies = sm_cfg.get('companies', ['inhouse', 'outsource'])
        M_sm = sm_cfg.get('big_m', 1000)

        # Pencereleri oluştur (yeni format) ya da eski formatı tek pencereye çevir.
        sm_windows = sm_cfg.get('windows')
        if not sm_windows:
            sm_windows = [{
                'name': 'all',
                'start': sm_cfg.get('hours', {}).get('start', '07:00'),
                'end': sm_cfg.get('hours', {}).get('end', '20:00'),
                'penalty': sm_cfg.get('penalty_per_diff', 0.5),
            }]

        for comp in sm_companies:
            comp_shifts = in_shifts if comp == 'inhouse' else (out_shifts if comp == 'outsource' else [])
            if not comp_shifts:
                continue

            for win in sm_windows:
                win_name = win.get('name', f"{win['start']}_{win['end']}")
                win_start = win['start']
                win_end = win['end']
                win_penalty = win.get('penalty', sm_cfg.get('penalty_per_diff', 0.5))

                starts_by_hour = {}
                for s in comp_shifts:
                    st = shift_cov[s]['start']
                    if win_start <= st < win_end:
                        starts_by_hour.setdefault(st, []).append(s)
                sorted_hours = sorted(starts_by_hour.keys())
                if len(sorted_hours) < 2:
                    continue

                # yh göstergeleri pencere bazlı isim alır (aynı saatte birden fazla
                # pencere varsa çakışmasın diye)
                yh = {}
                for h in sorted_hours:
                    var_name = f"yh_{comp}_{win_name}_{h.replace(':', '')}"
                    yh[h] = LpVariable(var_name, cat='Binary')
                    for s in starts_by_hour[h]:
                        prob += yh[h] >= y[s]

                n_hours = len(sorted_hours)
                for i in range(n_hours):
                    for j in range(i + 1, n_hours):
                        h_i = sorted_hours[i]
                        h_j = sorted_hours[j]
                        between = sorted_hours[i + 1:j]
                        tag = f"{comp}_{win_name}_{h_i.replace(':', '')}_{h_j.replace(':', '')}"
                        link = LpVariable(f"sm_link_{tag}", cat='Binary')
                        prob += link <= yh[h_i]
                        prob += link <= yh[h_j]
                        for h_k in between:
                            prob += link <= 1 - yh[h_k]
                        prob += link >= yh[h_i] + yh[h_j] - lpSum([yh[h_k] for h_k in between]) - 1

                        d_pos = LpVariable(f"sm_{tag}_pos", lowBound=0, cat='Continuous')
                        d_neg = LpVariable(f"sm_{tag}_neg", lowBound=0, cat='Continuous')
                        sum_i = lpSum([x[s] for s in starts_by_hour[h_i]])
                        sum_j = lpSum([x[s] for s in starts_by_hour[h_j]])
                        prob += d_pos >= sum_j - sum_i - M_sm * (1 - link)
                        prob += d_neg >= sum_i - sum_j - M_sm * (1 - link)
                        cost.append((d_pos + d_neg) * win_penalty)

    # --- Amaç fonksiyonu (tüm cost eklemeleri bittikten sonra) ---
    prob += lpSum(cost)

    # --- SOLVE ---
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
        ct, _base, mult, start_h = _classify_shift(
            s, shift_cov, queue, pt_shift_keys, inhouse_value, mcfg, config)
        if mult > 1.0:
            early_starts[s] = {'count': cnt, 'start': start_h, 'company': ct,
                               'multiplier': mult, 'penalty': cnt * (mult - 1.0)}
            early_total += cnt
            early_penalty += cnt * (mult - 1.0)

    # Small shift detail
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
    rr_total_excess = rr_total_penalty_cost = rr_penalized_slots = 0
    if rr_enabled and excess:
        peak_penalty_per_val = rr_cfg.get('peak_penalty', rr_penalty_per)
        for slot, exc_var in excess.items():
            exc_val = value(exc_var) or 0
            if exc_val > 0.5:
                exc_int = int(round(exc_val))
                rr_excess_by_slot[slot] = exc_int
                rr_total_excess += exc_int
                if slot in peak_slots_rr:
                    rr_total_penalty_cost += exc_int * peak_penalty_per_val
                elif night_mult_enabled and _is_night_slot(slot):
                    rr_total_penalty_cost += exc_int * rr_penalty_per * night_mult_value
                else:
                    rr_total_penalty_cost += exc_int * rr_penalty_per
                rr_penalized_slots += 1

    # Slot cap excess
    sc_excess_by_slot = {}
    sc_total_excess = sc_total_penalty_cost = sc_penalized_slots = 0
    if sc_cfg.get('enabled', False) and sc_excess:
        for slot, exc_var in sc_excess.items():
            exc_val = value(exc_var) or 0
            if exc_val > 0.5:
                exc_int = int(round(exc_val))
                slot_pen = next((d['penalty'] for d in slot_cap_detail if d['slot'] == slot), 50.0)
                sc_excess_by_slot[slot] = (exc_int, slot_pen)
                sc_total_excess += exc_int
                sc_total_penalty_cost += exc_int * slot_pen
                sc_penalized_slots += 1

    # Balans sonuçları
    balance_result = {}
    if bp_enabled and balance_vars:
        for win_name, bv in balance_vars.items():
            dp = value(bv['diff_pos']) or 0
            dn = value(bv['diff_neg']) or 0
            win_in_total = sum(assignments.get(s, 0) for s in bv['in_shifts'])
            win_out_total = sum(assignments.get(s, 0) for s in bv['out_shifts'])
            balance_result[win_name] = {
                'inhouse': win_in_total, 'outsource': win_out_total,
                'diff': win_in_total - win_out_total,
                'abs_diff': abs(win_in_total - win_out_total),
                'penalty_cost': (dp + dn) * bv['penalty'],
            }

    info = {
        'assignments': assignments, 'shift_coverage': shift_cov,
        'mip_by_slot': mip_by_slot, 'mip_in_by_slot': mip_in_by_slot,
        'mip_out_by_slot': mip_out_by_slot, 'mip_pt_by_slot': mip_pt_by_slot,
        'total_kisi': total, 'total_inhouse_kisi': total_in,
        'total_outsource_kisi': total_out, 'total_part_time_kisi': total_pt,
        'pt_available': pt_available, 'outsource_ratio': out_ratio,
        'cost_details': cost_details,
        'early_starts': early_starts, 'early_total': early_total, 'early_penalty': early_penalty,
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
        'sc_excess_by_slot': sc_excess_by_slot,
        'sc_total_excess': sc_total_excess,
        'sc_total_penalty_cost': sc_total_penalty_cost,
        'sc_penalized_slots': sc_penalized_slots,
        'balance_penalty_enabled': bp_enabled,
        'balance_result': balance_result,
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

    slot_total = {}; slot_in = {}; slot_out = {}
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
# 5. RAPOR (V2 ile aynı + V3 balans penalty bloğu)
# =============================================================================

def print_queue_report(date, queue, erlang_by_slot, mip_info, actual,
                       weighted_aht_by_slot=None, total_calls_day=0,
                       calls_by_slot=None, mip_info_stage1=None,
                       e_sup1_by_slot=None, e_sup2_by_slot=None,
                       config=CONFIG):

    label = config['queues'][queue]['label']
    date_str = pd.to_datetime(date).strftime('%Y-%m-%d')

    print(f"\n{'='*95}")
    print(f"KUYRUK RAPORU: {label} ({queue.upper()}) - {date_str}")
    print(f"{'='*95}")

    e_peak = max(erlang_by_slot.values()) if erlang_by_slot else 0
    m_peak = max(mip_info['mip_by_slot'].values()) if mip_info['mip_by_slot'] else 0
    a_peak = max(actual['slot_total'].values()) if actual['slot_total'] else 0

    has_s1 = mip_info_stage1 is not None

    print(f"\n📊 ÖZET (KİŞİ BAZLI):")
    if has_s1:
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
            print(f"   {'Part-time Kişi':<22} {s1['total_part_time_kisi']:>10} {mip_info['total_part_time_kisi']:>10} "
                  f"{'-':>7} {'-':>10} {'-':>8}")
        print(f"   {'Outsource %':<22} {s1['outsource_ratio']:>9.1%} {mip_info['outsource_ratio']:>10.1%} "
              f"{'':>7} {actual['outsource_ratio']:>9.1%} {'':>8}")
        print(f"   {'Aktif Shift':<22} {len([s for s,c in s1['assignments'].items() if c>0]):>10} "
              f"{len([s for s,c in mip_info['assignments'].items() if c>0]):>10}")
    else:
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

    # EŞZAMANLI PEAK
    if has_s1:
        m1_peak = max(mip_info_stage1['mip_by_slot'].values()) if mip_info_stage1['mip_by_slot'] else 0
        print(f"\n📊 EŞZAMANLI PEAK:")
        print(f"   Erlang: {e_peak}  |  MIP1: {m1_peak}  |  MIP2: {m_peak}  |  Gerçek: {a_peak}")
    else:
        print(f"\n📊 EŞZAMANLI PEAK:")
        print(f"   Erlang: {e_peak}  |  MIP: {m_peak}  |  Gerçek: {a_peak}")

    # V5: Çözüm aşaması bilgisi
    sol_stage = mip_info.get('solution_stage')
    if sol_stage:
        used_min = mip_info.get('min_per_shift_used', '?')
        default_min = mip_info.get('min_per_shift_default', '?')
        src = mip_info.get('shrinkage_source', 'default')
        src_label = {
            'default': 'default (config.erlang.shrinkage)',
            'kapasite_kaybi': 'kapasite_kaybi (hourly_report.kapasite_kaybi)',
            'zero': 'zero (shrinkage=0)',
        }.get(src, src)
        print(f"\n🧭 ÇÖZÜM AŞAMASI:")
        print(f"   Aşama: {sol_stage}")
        print(f"   min_per_shift: kullanılan={used_min}  (default={default_min})")
        print(f"   Erlang shrinkage kaynağı: {src_label}")

    # --- V3: Balans Penalty Raporu ---
    balance_result = mip_info.get('balance_result', {})
    if balance_result:
        print(f"\n⚖️  BALANS PENALTY (pencere bazlı denge):")
        print(f"   {'Pencere':<15} {'Inhouse':>8} {'Outsource':>10} {'Fark':>8} {'|Fark|':>8} {'Penalty':>10}")
        print(f"   {'-'*65}")
        for win_name, br in balance_result.items():
            print(f"   {win_name:<15} {br['inhouse']:>8} {br['outsource']:>10} "
                  f"{br['diff']:>+8} {br['abs_diff']:>8} {br['penalty_cost']:>10.1f}")

    # Erken saat raporu
    early_starts = mip_info.get('early_starts', {})
    early_total = mip_info.get('early_total', 0)
    early_penalty_val = mip_info.get('early_penalty', 0)

    if early_starts:
        print(f"\n⏰ ERKEN SAAT BAŞLANGIÇLARI - {label.upper()}:")
        print(f"   {'Shift':<25} {'Saat':<8} {'Kişi':>6} {'Çarpan':>8} {'Penalty':>10}")
        print(f"   {'-'*60}")
        for s, info in sorted(early_starts.items(), key=lambda x: x[1]['start']):
            print(f"   {s:<25} {info['start']:<8} {info['count']:>6} {info['multiplier']:>7.1f}x {info['penalty']:>10.2f}")
        print(f"   {'-'*60}")
        print(f"   {'TOPLAM':<25} {'':>8} {early_total:>6} {'':>8} {early_penalty_val:>10.2f}")

    # Küçük atama raporu
    if mip_info.get('small_shift_penalty_enabled', False):
        small_detail = mip_info.get('small_shifts_detail', [])
        total_shifts = len(mip_info['assignments'])
        ssp_penalty = config['queue_configs'][queue].get('small_shift_penalty', {}).get('penalty', 3.0)

        if small_detail:
            print(f"\n🔧 KÜÇÜK ATAMALI SHIFT'LER (≤5 kişi):")
            print(f"   {'Shift':<25} {'Saat':<8} {'Tip':<10} {'Kişi':>6}")
            print(f"   {'-'*55}")
            for sd in sorted(small_detail, key=lambda x: x['start']):
                print(f"   {sd['shift']:<25} {sd['start']:<8} {sd['company']:<10} {sd['count']:>6}")

    # Birleşik slot bazlı penalty raporu (RR + Slot Cap)
    rr_excess = mip_info.get('rr_excess_by_slot', {}) if mip_info.get('rr_penalty_enabled', False) else {}
    sc_excess_map = mip_info.get('sc_excess_by_slot', {})

    if rr_excess or sc_excess_map:
        rr_peak = mip_info.get('rr_peak_slots', set())
        rr_cfg_q = config['queue_configs'][queue].get('rr_penalty', {})
        rr_pp = rr_cfg_q.get('penalty_per_person', 5.0)
        rr_peak_p = rr_cfg_q.get('peak_penalty', rr_pp)
        nm_cfg = rr_cfg_q.get('night_multiplier', {})
        nm_enabled = nm_cfg.get('enabled', False)
        nm_mult = nm_cfg.get('multiplier', 3.0)
        nm_start = nm_cfg.get('hours', {}).get('start', '22:00')
        nm_end = nm_cfg.get('hours', {}).get('end', '08:00')

        all_slots = sorted(set(rr_excess.keys()) | set(sc_excess_map.keys()))

        print(f"\n📊 SLOT BAZLI PENALTY DETAYI (RR + Slot Cap):")
        print(f"   {'Slot':<8} {'Tip':<6} {'Erlang':>7} {'MIP':>7} "
              f"{'RR_Fz':>6} {'RR_Çrp':>7} {'RR_Pen':>9} | "
              f"{'SC_Fz':>6} {'SC_Çrp':>7} {'SC_Pen':>9} | {'Toplam':>9}")
        print(f"   {'-'*100}")

        rr_sum = sc_sum = total_sum = 0
        for slot in all_slots:
            e = erlang_by_slot.get(slot, 0)
            m = mip_info['mip_by_slot'].get(slot, 0)

            rr_fz = rr_excess.get(slot, 0)
            if rr_fz:
                if slot in rr_peak:
                    rr_coef = rr_peak_p; tip = 'peak'
                elif nm_enabled and is_slot_in_shift(slot, nm_start, nm_end):
                    rr_coef = rr_pp * nm_mult; tip = 'gece'
                else:
                    rr_coef = rr_pp; tip = 'gun'
                rr_pen = rr_fz * rr_coef
            else:
                rr_coef = rr_pen = 0
                tip = '-'

            sc_data = sc_excess_map.get(slot)
            if sc_data:
                sc_fz, sc_coef = sc_data
                sc_pen = sc_fz * sc_coef
            else:
                sc_fz = sc_coef = sc_pen = 0

            toplam = rr_pen + sc_pen
            rr_sum += rr_pen; sc_sum += sc_pen; total_sum += toplam

            rr_str = f"{rr_pen:>9.1f}" if rr_pen else f"{'-':>9}"
            sc_str = f"{sc_pen:>9.1f}" if sc_pen else f"{'-':>9}"
            print(f"   {slot:<8} {tip:<6} {e:>7} {m:>7} "
                  f"{rr_fz:>6} {rr_coef:>7.1f} {rr_str} | "
                  f"{sc_fz:>6} {sc_coef:>7.1f} {sc_str} | {toplam:>9.1f}")

        print(f"   {'-'*100}")
        print(f"   {'TOPLAM':<8} {'':>6} {'':>7} {'':>7} "
              f"{'':>6} {'':>7} {rr_sum:>9.1f} | "
              f"{'':>6} {'':>7} {sc_sum:>9.1f} | {total_sum:>9.1f}")
        print(f"   Tip: peak=peak slot çarpanı | gece=night_multiplier | gun=normal")

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
    ccfg = config['company']
    inhouse_value = ccfg['inhouse']['shift_value']
    sc = mip_info['shift_coverage']
    mcfg = config['queue_configs'][queue]['mip']

    print(f"\n📋 SHIFT ATAMALARI ({len(mip_info['assignments'])} shift):")
    if has_s1:
        print(f"   {'Shift':<22} {'Saat':<12} {'Tip':<10} {'MIP(1)':>7} {'MIP(2)':>7} {'Fark':>6} {'Maliyet':>10}")
        print(f"   {'-'*78}")
        s1_assigns = mip_info_stage1['assignments']
    else:
        print(f"   {'Shift':<22} {'Saat':<12} {'Tip':<10} {'Kişi':>6} {'Maliyet':>10}")
        print(f"   {'-'*65}")
        s1_assigns = None

    pt_shift_keys = [s for s in sc if sc[s]['company'] == 'part_time']
    for s, cnt in sorted(mip_info['assignments'].items(), key=lambda x: sc[x[0]]['start']):
        info_s = sc[s]
        _ct, base_cost, mult, _start = _classify_shift(
            s, sc, queue, pt_shift_keys, inhouse_value, mcfg, config)
        final_cost = base_cost * mult * cnt
        mult_str = f" ({mult}x)" if mult != 1.0 else ""

        if s1_assigns is not None:
            cnt1 = s1_assigns.get(s, 0)
            diff = cnt - cnt1
            diff_str = f"{diff:+d}" if diff != 0 else "-"
            mark = " ←" if diff > 0 else "  "
            print(f"   {s:<22} {info_s['start']}-{info_s['end']:<5} {info_s['company']:<10} "
                  f"{cnt1:>7} {cnt:>7} {diff_str:>6}{mark} {final_cost:>8.2f}{mult_str}")
        else:
            print(f"   {s:<22} {info_s['start']}-{info_s['end']:<5} {info_s['company']:<10} {cnt:>6} {final_cost:>9.2f}{mult_str}")

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
    s1_slot = mip_info_stage1['mip_by_slot'] if has_s1 else {}
    s1_slot_in = mip_info_stage1['mip_in_by_slot'] if has_s1 else {}
    s1_slot_out = mip_info_stage1.get('mip_out_by_slot', {}) if has_s1 else {}

    print(f"\n📋 SLOT BAZLI (eşzamanlı çalışan)  * = peak slot")

    # E_sup1 / E_sup2 kolonları (sadece kitle, verildiğinde gösterilir)
    # E_sup1 = donor MIP2 - donor Erlang (pozitif)
    # E_sup2 = donor MIP2 - donor MIP1 (sadece surplus dağıtımı)
    has_esup = e_sup1_by_slot is not None or e_sup2_by_slot is not None
    esup_header = f" {'E_sup1':>6} {'E_sup2':>6}" if has_esup else ""
    esup_pad = f" {'':>6} {'':>6}" if has_esup else ""
    esup_extra = 14 if has_esup else 0

    if has_s1:
        if has_subq:
            print(f"   {'Slot':<8} {'W_AHT':>6} {'Erlang':>7}{esup_header} {'InMin':>6} {'OutMin':>7}  "
                  f"{'---- MIP(1) ----':^23}  {'---- MIP(2) ----':^23}  "
                  f"{'---- GERÇEK ----':^23}  {'Fark':>6} {'RR1':>6} {'RR2':>6}  {'E.Fark':>7}")
            print(f"   {'':>8} {'':>6} {'':>7}{esup_pad} {'':>6} {'':>7}  "
                  f"{'Toplam':>7} {'Inhouse':>7} {'Outsrc':>7}  "
                  f"{'Toplam':>7} {'Inhouse':>7} {'Outsrc':>7}  "
                  f"{'Toplam':>7} {'Inhouse':>7} {'Outsrc':>7}  "
                  f"{'':>6} {'':>6} {'':>6}  {'':>7}")
            sep_len = 148 + esup_extra
        else:
            print(f"   {'Slot':<8} {'W_AHT':>6} {'Erlang':>7}{esup_header}  "
                  f"{'---- MIP(1) ----':^23}  {'---- MIP(2) ----':^23}  "
                  f"{'---- GERÇEK ----':^23}  {'Fark':>6} {'RR1':>6} {'RR2':>6}  {'E.Fark':>7}")
            print(f"   {'':>8} {'':>6} {'':>7}{esup_pad}  "
                  f"{'Toplam':>7} {'Inhouse':>7} {'Outsrc':>7}  "
                  f"{'Toplam':>7} {'Inhouse':>7} {'Outsrc':>7}  "
                  f"{'Toplam':>7} {'Inhouse':>7} {'Outsrc':>7}  "
                  f"{'':>6} {'':>6} {'':>6}  {'':>7}")
            sep_len = 134 + esup_extra
        print(f"   {'-'*sep_len}")
    else:
        if has_subq:
            print(f"   {'Slot':<8} {'W_AHT':>6} {'Erlang':>7}{esup_header} {'InMin':>6} {'OutMin':>7}  "
                  f"{'---- MIP ----':^23}  {'---- GERÇEK ----':^23}  {'Fark':>6} {'RR':>7} {'E.Fark':>7}")
            print(f"   {'':>8} {'':>6} {'':>7}{esup_pad} {'':>6} {'':>7}  "
                  f"{'Toplam':>7} {'Inhouse':>7} {'Outsrc':>7}  "
                  f"{'Toplam':>7} {'Inhouse':>7} {'Outsrc':>7}  {'':>6} {'':>7} {'':>7}")
            sep_len = 115 + esup_extra
        else:
            print(f"   {'Slot':<8} {'W_AHT':>6} {'Erlang':>7}{esup_header}  "
                  f"{'---- MIP ----':^23}  {'---- GERÇEK ----':^23}  {'Fark':>6} {'RR':>7} {'E.Fark':>7}")
            print(f"   {'':>8} {'':>6} {'':>7}{esup_pad}  "
                  f"{'Toplam':>7} {'Inhouse':>7} {'Outsrc':>7}  "
                  f"{'Toplam':>7} {'Inhouse':>7} {'Outsrc':>7}  {'':>6} {'':>7} {'':>7}")
            sep_len = 106 + esup_extra
        print(f"   {'-'*sep_len}")

    e_slot_sum = m_slot_sum = a_slot_sum = m1_slot_sum = 0

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

        if has_s1:
            m1 = s1_slot.get(slot, 0)
            m1i = s1_slot_in.get(slot, 0)
            m1o = s1_slot_out.get(slot, 0)
            m1_slot_sum += m1
        else:
            m1 = m1i = m1o = 0

        if e > 0 or m > 0 or at > 0:
            w_aht = weighted_aht_by_slot.get(slot, 0) if weighted_aht_by_slot else 0
            fark = m - at
            peak_mark = "*" if slot in peak_slots else " "
            e_fark = m - e

            if has_esup:
                e_sup1_v = e_sup1_by_slot.get(slot, 0) if e_sup1_by_slot else 0
                e_sup2_v = e_sup2_by_slot.get(slot, 0) if e_sup2_by_slot else 0
                esup_cell = f" {e_sup1_v:>6} {e_sup2_v:>6}"
            else:
                esup_cell = ""

            if has_s1:
                rr1_v = (m1 / e) if e > 0 else 0
                rr2_v = (m / e) if e > 0 else 0
                rr1_str = f"{rr1_v:.0%}" if e > 0 else "-"
                rr2_arrow = "↑" if e > 0 and rr2_v > rr1_v else " "
                rr2_str = f"{rr2_v:.0%}{rr2_arrow}" if e > 0 else "- "
                if has_subq:
                    in_min = in_only_by_slot.get(slot, 0)
                    out_min = out_only_by_slot.get(slot, 0)
                    in_min_str = str(in_min) if in_min > 0 else "-"
                    out_min_str = str(out_min) if out_min > 0 else "-"
                    print(f"   {slot}{peak_mark:<2} {w_aht:>6.0f} {e:>7}{esup_cell} {in_min_str:>6} {out_min_str:>7}  "
                          f"{m1:>7} {m1i:>7} {m1o:>7}  {m:>7} {mi:>7} {mo:>7}  "
                          f"{at:>7} {ai:>7} {ao:>7}  {fark:>+6} {rr1_str:>6} {rr2_str:>6}  {e_fark:>+7}")
                else:
                    print(f"   {slot}{peak_mark:<2} {w_aht:>6.0f} {e:>7}{esup_cell}  "
                          f"{m1:>7} {m1i:>7} {m1o:>7}  {m:>7} {mi:>7} {mo:>7}  "
                          f"{at:>7} {ai:>7} {ao:>7}  {fark:>+6} {rr1_str:>6} {rr2_str:>6}  {e_fark:>+7}")
            else:
                rr_str = f"{m/e:.0%}" if e > 0 else "-"
                if has_subq:
                    in_min = in_only_by_slot.get(slot, 0)
                    out_min = out_only_by_slot.get(slot, 0)
                    in_min_str = str(in_min) if in_min > 0 else "-"
                    out_min_str = str(out_min) if out_min > 0 else "-"
                    print(f"   {slot}{peak_mark:<2} {w_aht:>6.0f} {e:>7}{esup_cell} {in_min_str:>6} {out_min_str:>7}  "
                          f"{m:>7} {mi:>7} {mo:>7}  {at:>7} {ai:>7} {ao:>7}  {fark:>+6} {rr_str:>7} {e_fark:>+7}")
                else:
                    print(f"   {slot}{peak_mark:<2} {w_aht:>6.0f} {e:>7}{esup_cell}  "
                          f"{m:>7} {mi:>7} {mo:>7}  {at:>7} {ai:>7} {ao:>7}  {fark:>+6} {rr_str:>7} {e_fark:>+7}")

    sep = '-' * sep_len
    print(f"   {sep}")
    e_m_fark = m_slot_sum - e_slot_sum
    if has_esup:
        esup1_tot = sum(e_sup1_by_slot.get(s, 0) for s in SLOTS_30) if e_sup1_by_slot else 0
        esup2_tot = sum(e_sup2_by_slot.get(s, 0) for s in SLOTS_30) if e_sup2_by_slot else 0
        esup_tot_cell = f" {esup1_tot:>6} {esup2_tot:>6}"
    else:
        esup_tot_cell = ""
    if has_s1:
        trr1_v = (m1_slot_sum / e_slot_sum) if e_slot_sum > 0 else 0
        trr2_v = (m_slot_sum / e_slot_sum) if e_slot_sum > 0 else 0
        trr1 = f"{trr1_v:.0%}" if e_slot_sum > 0 else "-"
        trr2 = f"{trr2_v:.0%}" if e_slot_sum > 0 else "-"
        print(f"   {'SLOT TOP':<15} {e_slot_sum:>7}{esup_tot_cell}  "
              f"{m1_slot_sum:>7} {'':>7} {'':>7}  {m_slot_sum:>7} {'':>7} {'':>7}  "
              f"{a_slot_sum:>7} {'':>7} {'':>7}  {m_slot_sum - a_slot_sum:>+6} {trr1:>6} {trr2:>6}  {e_m_fark:>+7}")
    else:
        print(f"   {'SLOT TOP':<15} {e_slot_sum:>7}{esup_tot_cell}  "
              f"{m_slot_sum:>7} {'':>7} {'':>7}  "
              f"{a_slot_sum:>7} {'':>7} {'':>7}  {m_slot_sum - a_slot_sum:>+6} {'':>7} {e_m_fark:>+7}")

    legend = "Fark = MIP-Gerçek  |  RR = MIP/Erlang  |  E.Fark = MIP-Erlang  |  * = Peak"
    if has_s1:
        legend = "MIP(1)=min  |  MIP(2)=MIP(1)+surplus  |  RR1=MIP1/Erlang  |  RR2=MIP2/Erlang  |  ↑ = RR2>RR1  |  " + legend
    if has_esup:
        legend += "\n   E_sup1 = diğer kuyrukların MIP2 - Erlang pozitif farkı  |  E_sup2 = diğer kuyruklarda surplus ile eklenenler (MIP2 - MIP1)  |  bilgi notu, MIP'e dahil değil"
    print(f"\n   {legend}")

    # Slot bazlı kapasite raporu (30dk)
    hr_cfg = config['queue_configs'][queue].get('hourly_report', {})
    if hr_cfg and weighted_aht_by_slot and calls_by_slot:
        rapor_etkisi_cfg = hr_cfg.get('rapor_etkisi', {})
        kap_kaybi_cfg = hr_cfg.get('kapasite_kaybi', {})
        cagri_adedi_cfg = hr_cfg.get('cagri_adedi', {})

        print(f"\n📋 SLOT BAZLI KAPASİTE RAPORU (30dk)")
        if has_s1:
            print(f"   {'Slot':<6} {'Çağrı':>6} {'Erlng':>6}  "
                  f"{'MIP1':>5} {'MIP2':>5} {'Fark':>5}  "
                  f"{'R.Et1':>5} {'R.Et2':>5}  "
                  f"{'K.Ka1':>5} {'K.Ka2':>5}  "
                  f"{'NMT1':>5} {'NMT2':>5} {'FNMT':>5}  "
                  f"{'Ç.Kp1':>6} {'Ç.Kp2':>6}  "
                  f"{'KpRR1':>6} {'KpRR2':>6}")
            print(f"   {'-'*115}")
        else:
            print(f"   {'Slot':<7} {'Çağrı':>7} {'Erlang':>7} {'Kap.':>6} "
                  f"{'R.Etk':>6} {'K.Kay':>6} {'NetMT':>6} {'Ç.Kap':>7} {'Kap_RR':>7}")
            print(f"   {'-'*70}")

        t_cagri = t_erl = 0
        t_m1 = t_m2 = 0
        t_re1 = t_re2 = 0
        t_kk1 = t_kk2 = 0
        t_nmt1 = t_nmt2 = 0
        t_ck1 = t_ck2 = 0

        for slot in SLOTS_30:
            h = int(slot[:2])
            cagri = int(calls_by_slot.get(slot, 0))
            kap2 = mip_info['mip_by_slot'].get(slot, 0)
            kap1 = mip_info_stage1['mip_by_slot'].get(slot, 0) if has_s1 else kap2
            erl = erlang_by_slot.get(slot, 0)

            if cagri == 0 and kap2 == 0:
                continue

            re_oran = rapor_etkisi_cfg.get(h, rapor_etkisi_cfg.get('default', 0))
            kk_oran = kap_kaybi_cfg.get(h, kap_kaybi_cfg.get('default', 0))
            ca = cagri_adedi_cfg.get(h, cagri_adedi_cfg.get('default', 15))

            re1 = round(kap1 * re_oran)
            kk1 = round(kap1 * kk_oran)
            nmt1 = kap1 - re1 - kk1
            ck1 = nmt1 * (ca / 2)
            rr1 = ck1 / cagri if cagri > 0 else 0

            re2 = round(kap2 * re_oran)
            kk2 = round(kap2 * kk_oran)
            nmt2 = kap2 - re2 - kk2
            ck2 = nmt2 * (ca / 2)
            rr2 = ck2 / cagri if cagri > 0 else 0

            t_cagri += cagri; t_erl += erl
            t_m1 += kap1; t_m2 += kap2
            t_re1 += re1; t_re2 += re2
            t_kk1 += kk1; t_kk2 += kk2
            t_nmt1 += nmt1; t_nmt2 += nmt2
            t_ck1 += ck1; t_ck2 += ck2

            if has_s1:
                arrow = "↑" if rr2 > rr1 else " "
                warn = " ⚠" if rr2 < 1.0 and cagri > 0 else ""
                print(f"   {slot:<6} {cagri:>6} {erl:>6}  "
                      f"{kap1:>5} {kap2:>5} {kap2-kap1:>+5}  "
                      f"{re1:>5} {re2:>5}  "
                      f"{kk1:>5} {kk2:>5}  "
                      f"{nmt1:>5} {nmt2:>5} {nmt2-nmt1:>+5}  "
                      f"{ck1:>6.0f} {ck2:>6.0f}  "
                      f"{rr1:>5.0%} {rr2:>5.0%}{arrow}{warn}")
            else:
                warn = " ⚠" if rr2 < 1.0 and cagri > 0 else ""
                print(f"   {slot:<7} {cagri:>7} {erl:>7} {kap2:>6} "
                      f"{re2:>6} {kk2:>6} {nmt2:>6} {ck2:>7.0f} {rr2:>6.0%}{warn}")

        if has_s1:
            print(f"   {'-'*115}")
            trr1 = t_ck1 / t_cagri if t_cagri > 0 else 0
            trr2 = t_ck2 / t_cagri if t_cagri > 0 else 0
            arrow = "↑" if trr2 > trr1 else " "
            print(f"   {'TOPLAM':<6} {t_cagri:>6} {t_erl:>6}  "
                  f"{t_m1:>5} {t_m2:>5} {t_m2-t_m1:>+5}  "
                  f"{t_re1:>5} {t_re2:>5}  "
                  f"{t_kk1:>5} {t_kk2:>5}  "
                  f"{t_nmt1:>5} {t_nmt2:>5} {t_nmt2-t_nmt1:>+5}  "
                  f"{t_ck1:>6.0f} {t_ck2:>6.0f}  "
                  f"{trr1:>5.0%} {trr2:>5.0%}{arrow}")
            print(f"\n   Kap_RR = Çağrı_Kapasitesi / Gelen_Çağrı (MIP1 ve MIP2 ayrı hesap)  |  ↑ = KpRR2>KpRR1")
        else:
            print(f"   {'-'*70}")
            trr2 = t_ck2 / t_cagri if t_cagri > 0 else 0
            print(f"   {'TOPLAM':<7} {t_cagri:>7} {t_erl:>7} {t_m2:>6} "
                  f"{t_re2:>6} {t_kk2:>6} {t_nmt2:>6} {t_ck2:>7.0f} {trr2:>6.0%}")


# =============================================================================
# 6. SURPLUS DAĞITIMI (V3 — hem inhouse hem outsource)
# =============================================================================

def distribute_surplus(mip_info, queue, erlang_by_slot, config=CONFIG, verbose=True):
    """
    V3 surplus: hem inhouse hem outsource kadrosundan kalan kişileri dağıtır.
    Pencere oranları (2/3 sabah, 1/3 akşam) uygulanır.
    """
    sd_cfg = config.get('surplus_distribution', {})
    if not sd_cfg.get('enabled', False):
        return mip_info

    kadro_cfg = sd_cfg.get('total_kadro', {}).get(queue, {})
    total_inhouse_kadro = kadro_cfg.get('inhouse', 0)
    total_outsource_kadro = kadro_cfg.get('outsource', 0)

    current_inhouse = mip_info['total_inhouse_kisi']
    current_outsource = mip_info['total_outsource_kisi']

    surplus_in = max(0, total_inhouse_kadro - current_inhouse)
    surplus_out = max(0, total_outsource_kadro - current_outsource) if sd_cfg.get('outsource_enabled', True) else 0
    total_surplus = surplus_in + surplus_out

    if total_surplus <= 0:
        if verbose:
            print(f"   ℹ Surplus: fazla yok (in: {total_inhouse_kadro}-{current_inhouse}={surplus_in}, "
                  f"out: {total_outsource_kadro}-{current_outsource}={surplus_out})")
        return mip_info

    ccfg = config['company']
    inhouse_value = ccfg['inhouse']['shift_value']
    outsource_value = ccfg['outsource']['shift_value']
    shift_cov = mip_info['shift_coverage']
    assignments = mip_info['assignments']

    only_assigned = sd_cfg.get('only_assigned_shifts', True)
    fallback = sd_cfg.get('fallback_all_inhouse', True)
    method = sd_cfg.get('method', 'rr_first')
    windows = sd_cfg.get('windows', [])

    if not windows:
        if verbose:
            print(f"   ⚠ Surplus: pencere tanımı yok.")
        return mip_info

    inhouse_shifts = [s for s in shift_cov if shift_cov[s]['company'] == inhouse_value]
    outsource_shifts = [s for s in shift_cov if shift_cov[s]['company'] == outsource_value]

    if only_assigned:
        eligible_in = [s for s in inhouse_shifts if assignments.get(s, 0) > 0]
        eligible_out = [s for s in outsource_shifts if assignments.get(s, 0) > 0]
    else:
        eligible_in = inhouse_shifts
        eligible_out = outsource_shifts

    def _window_candidates(win, eligible):
        return [s for s in eligible if win['start'] <= shift_cov[s]['start'] <= win['end']]

    if verbose:
        print(f"   ➕ Surplus V3: in={surplus_in}, out={surplus_out}, method={method}")

    added_total = {}
    local_mip_by_slot = dict(mip_info['mip_by_slot'])
    by_window_log = {}

    for company_label, surplus, eligible in [
        ('inhouse', surplus_in, eligible_in),
        ('outsource', surplus_out, eligible_out),
    ]:
        if surplus <= 0 or not eligible:
            continue

        win_cands = {win['name']: _window_candidates(win, eligible) for win in windows}

        if all(len(c) == 0 for c in win_cands.values()):
            if fallback and eligible:
                windows_eff = [{'name': 'fallback', 'start': '00:00', 'end': '23:59', 'ratio': 1.0}]
                win_cands = {'fallback': eligible}
            else:
                continue
        else:
            windows_eff = windows

        active_windows = [w for w in windows_eff if win_cands.get(w['name'])]
        active_ratio_sum = sum(w['ratio'] for w in active_windows)
        if active_ratio_sum == 0:
            continue

        raw_shares = {w['name']: surplus * (w['ratio'] / active_ratio_sum) for w in active_windows}
        floor_shares = {n: int(v) for n, v in raw_shares.items()}
        leftover = surplus - sum(floor_shares.values())
        fracs = sorted(((n, raw_shares[n] - floor_shares[n]) for n in floor_shares),
                       key=lambda x: x[1], reverse=True)
        for i in range(leftover):
            floor_shares[fracs[i % len(fracs)][0]] += 1
        window_shares = floor_shares

        if verbose:
            share_str = ", ".join(f"{w['name']}={window_shares[w['name']]}" for w in active_windows)
            print(f"      [{company_label}] surplus={surplus}, pencereler: {share_str}")

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
            log_key = f"{company_label}_{name}"
            by_window_log[log_key] = {
                'company': company_label, 'share': share,
                'rr_fix': used_rr, 'proportional': used_prop, 'added': added_w,
            }

    # mip_info güncelle
    total_added = sum(added_total.values())
    if total_added == 0:
        return mip_info

    for s, n in added_total.items():
        if n > 0:
            assignments[s] = assignments.get(s, 0) + n

    in_all = [s for s in shift_cov if shift_cov[s]['company'] == inhouse_value]
    out_all = [s for s in shift_cov if shift_cov[s]['company'] == outsource_value]

    for slot in mip_info['mip_by_slot']:
        mip_info['mip_by_slot'][slot] = sum(assignments.get(s, 0) for s in shift_cov if slot in shift_cov[s]['slots'])
        mip_info['mip_in_by_slot'][slot] = sum(assignments.get(s, 0) for s in in_all if slot in shift_cov[s]['slots'])
        mip_info['mip_out_by_slot'][slot] = sum(assignments.get(s, 0) for s in out_all if slot in shift_cov[s]['slots'])

    added_in = sum(added_total.get(s, 0) for s in in_all)
    added_out = sum(added_total.get(s, 0) for s in out_all)

    mip_info['total_inhouse_kisi'] = current_inhouse + added_in
    mip_info['total_outsource_kisi'] = current_outsource + added_out
    mip_info['total_kisi'] = mip_info['total_inhouse_kisi'] + mip_info['total_outsource_kisi'] + mip_info.get('total_part_time_kisi', 0)
    total_for_ratio = mip_info['total_inhouse_kisi'] + mip_info['total_outsource_kisi']
    mip_info['outsource_ratio'] = mip_info['total_outsource_kisi'] / total_for_ratio if total_for_ratio > 0 else 0

    mip_info['surplus_added'] = added_total
    mip_info['surplus_total_added'] = total_added
    mip_info['surplus_by_window'] = by_window_log

    if verbose:
        print(f"      ✓ Eklenen: {total_added} (in:{added_in}, out:{added_out}) → "
              f"toplam in={mip_info['total_inhouse_kisi']}, out={mip_info['total_outsource_kisi']}, "
              f"oran={mip_info['outsource_ratio']:.1%}")

    return mip_info


def _allocate_within_pool(share, candidates, shift_cov, erlang_by_slot,
                          assignments, mip_by_slot_state, method):
    added = {s: 0 for s in candidates}
    remaining = share
    used_rr = 0
    used_prop = 0

    if not candidates or share <= 0:
        return added, used_rr, used_prop

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

    return added, used_rr, used_prop


# =============================================================================
# 6. SHIFT SAAT SINIFLANDIRMASI
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
    _fmt = lambda lst: ", ".join(lst) if lst else "(yok)"
    print(f"   Inhouse-only  ({len(io):>2}): {_fmt(io)}")
    print(f"   Outsource-only({len(oo):>2}): {_fmt(oo)}")
    print(f"   Kesişim       ({len(ks):>2}): {_fmt(ks)}")


# =============================================================================
# 7. SUBQUEUE MİNİMUM HESAPLAMA
# =============================================================================

def _build_subqueue_min_slots(df_calls_30, queue, target_date, erlang_by_slot, config):
    target_date = pd.to_datetime(target_date)
    df_day = df_calls_30[df_calls_30['data_date'] == target_date]
    if len(df_day) == 0:
        return {}, {}

    inhouse_min_by_slot = {}
    outsource_min_by_slot = {}

    for item in config.get('inhouse_only_subqueues', {}).get(queue, []):
        sq_name = item if isinstance(item, str) else item['sub_queue']
        min_ratio = 1.0 if isinstance(item, str) else item.get('min_ratio', 1.0)
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

    for item in config.get('outsource_only_subqueues', {}).get(queue, []):
        sq_name = item if isinstance(item, str) else item['sub_queue']
        min_ratio = 1.0 if isinstance(item, str) else item.get('min_ratio', 1.0)
        hours = None if isinstance(item, str) else item.get('hours')
        sq_col = f"{sq_name}_calls"
        total_col = f"{queue}_total"
        for _, row in df_day.iterrows():
            slot = row['slot_30']
            erlang = erlang_by_slot.get(slot, 0)
            if erlang <= 0:
                continue
            if hours and not is_slot_in_shift(slot, hours['start'], hours['end']):
                continue
            sq_calls = row.get(sq_col, 0) if sq_col in row.index else 0
            total_calls = row.get(total_col, 0) if total_col in row.index else 0
            if total_calls > 0 and sq_calls > 0:
                call_ratio = sq_calls / total_calls
                min_need = math.ceil(erlang * call_ratio * min_ratio)
                outsource_min_by_slot[slot] = outsource_min_by_slot.get(slot, 0) + min_need

    return inhouse_min_by_slot, outsource_min_by_slot


# =============================================================================
# 8. ANA AKIŞ
# =============================================================================

def run_queue_pipeline(df_calls, df_actual, df_shifts, target_date, queue,
                       e_sup1_by_slot=None, e_sup2_by_slot=None,
                       config=CONFIG, verbose=True):
    """V4 akışı — SADECE HAFTAİÇİ. Cross-queue kaldırıldı."""
    target_date = pd.to_datetime(target_date)
    date_str = target_date.strftime('%Y-%m-%d')

    if target_date.weekday() >= 5:
        raise ValueError(f"V4 sadece haftaiçi. {date_str} için v10.9 kullanın.")

    if queue not in config.get('queue_configs', {}):
        raise ValueError(f"'{queue}' için queue_configs bulunamadı.")

    label = config['queues'][queue]['label']
    df_shifts_queue = df_shifts.get(queue) if isinstance(df_shifts, dict) else df_shifts
    if df_shifts_queue is None:
        raise ValueError(f"'{queue}' için shift verisi bulunamadı.")

    if verbose:
        print(f"\n{'='*95}")
        print(f"PİPELİNE V3 WEEKDAY: {label} ({queue.upper()}) - {date_str} [Haftaiçi]")
        print(f"{'='*95}")

    classification = classify_shifts(df_shifts_queue, config)
    if verbose:
        print_shift_classification(classification, label)

    if verbose: print(f"\n[1/4] Veri hazırlama...")
    df_calls_30 = prepare_calls_30(df_calls, config)

    if verbose: print(f"[2/4] Erlang hesaplama...")
    df_erlang = calculate_erlang_all(df_calls_30, config)
    df_erlang_day = df_erlang[(df_erlang['date'] == target_date) & (df_erlang['queue'] == queue)].copy()

    erlang_by_slot = dict(zip(df_erlang_day['slot'], df_erlang_day['erlang_need']))
    weighted_aht_by_slot = dict(zip(df_erlang_day['slot'], df_erlang_day['weighted_aht']))

    if verbose:
        e_total = sum(erlang_by_slot.values())
        e_peak = max(erlang_by_slot.values()) if erlang_by_slot else 0
        print(f"   Erlang: toplam={e_total}, peak={e_peak}")

    inhouse_min_by_slot, outsource_min_by_slot = _build_subqueue_min_slots(
        df_calls_30, queue, target_date, erlang_by_slot, config)

    if verbose: print(f"[3/4] MIP optimizasyon (V5: fallback + capacity-loss adjustment)...")

    mcfg = config['queue_configs'][queue]['mip']
    default_min = mcfg['min_per_shift']
    fb_cfg = mcfg.get('min_per_shift_fallback', {})
    fb_enabled = fb_cfg.get('enabled', False)
    fb_floor = fb_cfg.get('floor', 1)
    fb_step = max(1, fb_cfg.get('step', 1))

    cl_cfg = mcfg.get('capacity_loss_fallback', {})
    cl_enabled = cl_cfg.get('enabled', False)

    try_values = [default_min]
    if fb_enabled and default_min > fb_floor:
        v = default_min - fb_step
        while v >= fb_floor:
            try_values.append(v)
            v -= fb_step
        if try_values[-1] != fb_floor:
            try_values.append(fb_floor)

    assignments = None
    mip_info = None
    used_min = default_min
    solution_stage = None
    last_status = None

    if verbose:
        in_min_total = sum(inhouse_min_by_slot.values()) if inhouse_min_by_slot else 0
        out_min_total = sum(outsource_min_by_slot.values()) if outsource_min_by_slot else 0
        print(f"      [original] Erlang toplam={sum(erlang_by_slot.values())} peak={max(erlang_by_slot.values()) if erlang_by_slot else 0} | "
              f"InMin toplam={in_min_total}, OutMin toplam={out_min_total}")

    for try_min in try_values:
        assignments, mip_info = optimize_queue(
            erlang_by_slot, df_shifts_queue, queue,
            target_date=target_date,
            inhouse_min_by_slot=inhouse_min_by_slot,
            outsource_min_by_slot=outsource_min_by_slot,
            config=config,
            min_per_shift_override=try_min)
        if verbose:
            status = 'OPTIMAL' if assignments is not None else (str(mip_info) if mip_info else 'UNKNOWN')
            print(f"      [original] min={try_min:>3} → {status}")
        if assignments is not None:
            used_min = try_min
            solution_stage = 'default' if try_min == default_min else f'min_fallback={try_min}'
            if try_min != default_min and verbose:
                print(f"   ⚠ min_per_shift {default_min} ile çözülemedi → {try_min} ile çözüldü")
            break
        last_status = mip_info

    def _recompute_erlang_with_shrinkage(shrinkage_value):
        """Verilen shrinkage (dict veya skaler) ile Erlang'ı yeniden hesaplar."""
        cfg_alt = copy.deepcopy(config)
        cfg_alt['queue_configs'][queue]['erlang']['shrinkage'] = shrinkage_value
        df_alt = calculate_erlang_all(df_calls_30, cfg_alt)
        df_alt_day = df_alt[(df_alt['date'] == target_date) & (df_alt['queue'] == queue)].copy()
        return dict(zip(df_alt_day['slot'], df_alt_day['erlang_need']))

    def _scan_min_with_erlang(erl_dict, stage_label):
        """try_values üzerinden tarama yapar. Subqueue min'leri de erl_dict'e göre yeniden hesaplanır."""
        in_min, out_min = _build_subqueue_min_slots(df_calls_30, queue, target_date, erl_dict, config)
        if verbose:
            erl_total = sum(erl_dict.values())
            erl_peak = max(erl_dict.values()) if erl_dict else 0
            in_min_total = sum(in_min.values()) if in_min else 0
            out_min_total = sum(out_min.values()) if out_min else 0
            print(f"      [{stage_label}] Erlang toplam={erl_total} peak={erl_peak} | "
                  f"InMin toplam={in_min_total}, OutMin toplam={out_min_total}")
        a = None
        m = None
        um = default_min
        ss = None
        ls = None
        for tm in try_values:
            a, m = optimize_queue(
                erl_dict, df_shifts_queue, queue,
                target_date=target_date,
                inhouse_min_by_slot=in_min,
                outsource_min_by_slot=out_min,
                config=config,
                min_per_shift_override=tm)
            if verbose:
                status = 'OPTIMAL' if a is not None else (str(m) if m else 'UNKNOWN')
                print(f"      [{stage_label}] min={tm:>3} → {status}")
            if a is not None:
                um = tm
                if stage_label == 'capacity_loss':
                    ss = 'capacity_loss_adjusted' if tm == default_min else f'capacity_loss_min_fallback={tm}'
                elif stage_label == 'zero_shrinkage':
                    ss = 'zero_shrinkage' if tm == default_min else f'zero_shrinkage_min_fallback={tm}'
                else:
                    ss = 'default' if tm == default_min else f'min_fallback={tm}'
                return a, m, um, ss, None, in_min, out_min
            ls = m
        return None, None, um, ss, ls, in_min, out_min

    # Kademe 3-4: shrinkage'i alternatif kaynaklarla değiştir, Erlang yenile, min tara
    if cl_enabled and assignments is None:
        hr_cfg = config['queue_configs'][queue].get('hourly_report', {})
        kk_dict = hr_cfg.get('kapasite_kaybi', {})
        fallback_shrinkages = [
            ('capacity_loss', kk_dict, "shrinkage = kapasite_kaybi"),
            ('zero_shrinkage', 0, "shrinkage = 0"),
        ]
        for stage_label, shrinkage_value, msg in fallback_shrinkages:
            if assignments is not None:
                break
            erl_alt = _recompute_erlang_with_shrinkage(shrinkage_value)
            if verbose:
                delta = sum(erl_alt.values()) - sum(erlang_by_slot.values())
                print(f"   ⚠ {msg} (Erlang Δ={delta:+}), min taraması başlıyor")
            a, m, um, ss, ls, im, om = _scan_min_with_erlang(erl_alt, stage_label)
            if a is not None:
                assignments, mip_info, used_min, solution_stage = a, m, um, ss
                erlang_by_slot = erl_alt
                inhouse_min_by_slot, outsource_min_by_slot = im, om
            else:
                last_status = ls

    if assignments is None:
        print(f"   ⚠ Çözüm bulunamadı (tüm kademeler tükendi): {last_status}")
        return None

    mip_info['min_per_shift_used'] = used_min
    mip_info['min_per_shift_default'] = default_min
    mip_info['solution_stage'] = solution_stage
    if solution_stage and solution_stage.startswith('capacity_loss'):
        mip_info['shrinkage_source'] = 'kapasite_kaybi'
    elif solution_stage and solution_stage.startswith('zero_shrinkage'):
        mip_info['shrinkage_source'] = 'zero'
    else:
        mip_info['shrinkage_source'] = 'default'

    if verbose:
        print(f"   ✓ Çözüm aşaması: {solution_stage} (min_per_shift={used_min})")

    if verbose:
        print(f"   MIP(1): {mip_info['total_kisi']} kişi "
              f"(In:{mip_info['total_inhouse_kisi']}, Out:{mip_info['total_outsource_kisi']}, "
              f"Oran:{mip_info['outsource_ratio']:.1%})")

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
                       e_sup1_by_slot=e_sup1_by_slot,
                       e_sup2_by_slot=e_sup2_by_slot,
                       config=config)

    return {
        'date': target_date, 'queue': queue, 'label': label,
        'day_type': 'haftalici',
        'erlang_by_slot': erlang_by_slot,
        'weighted_aht_by_slot': weighted_aht_by_slot,
        'mip_info': mip_info, 'mip_info_stage1': mip_info_stage1,
        'actual': actual,
        'total_calls_day': total_calls_day, 'calls_by_slot': calls_by_slot,
        'inhouse_min_by_slot': inhouse_min_by_slot,
        'outsource_min_by_slot': outsource_min_by_slot,
        'shift_classification': classification,
    }


def run_all_queues(df_calls, df_actual, df_shifts, target_date, config=CONFIG):
    """V4 — tüm kuyruklar, cross-queue aktarımı kaldırıldı."""
    target_date_chk = pd.to_datetime(target_date)
    if target_date_chk.weekday() >= 5:
        raise ValueError(f"V4 sadece haftaiçi. v10.9 kullanın.")

    results = {}
    # Önce donor kuyruklar (kitle dışındakiler), sonra kitle — e_sup bilgi notu için
    queue_order = [q for q in config['queues'] if q != 'kitle'] + (['kitle'] if 'kitle' in config['queues'] else [])
    for queue in queue_order:
        e_sup1_by_slot = None
        e_sup2_by_slot = None
        if queue == 'kitle':
            e_sup1_by_slot = {}
            e_sup2_by_slot = {}
            for _, donor_r in results.items():
                donor_mip2 = donor_r['mip_info']['mip_by_slot']
                donor_erl = donor_r['erlang_by_slot']
                donor_s1 = donor_r.get('mip_info_stage1')
                donor_mip1 = donor_s1['mip_by_slot'] if donor_s1 else donor_mip2
                for s in set(donor_mip2) | set(donor_erl) | set(donor_mip1):
                    e_sup1_by_slot[s] = e_sup1_by_slot.get(s, 0) + max(0, donor_mip2.get(s, 0) - donor_erl.get(s, 0))
                    e_sup2_by_slot[s] = e_sup2_by_slot.get(s, 0) + max(0, donor_mip2.get(s, 0) - donor_mip1.get(s, 0))
        result = run_queue_pipeline(df_calls, df_actual, df_shifts, target_date, queue,
                                     e_sup1_by_slot=e_sup1_by_slot,
                                     e_sup2_by_slot=e_sup2_by_slot, config=config)
        if result:
            results[queue] = result

    # Toplam rapor
    target_date = pd.to_datetime(target_date)
    print(f"\n{'='*95}")
    print(f"TÜM KUYRUKLAR - {target_date.strftime('%Y-%m-%d')} [Haftaiçi V4]")
    print(f"{'='*95}")
    print(f"{'Kuyruk':<12} {'MIP':>8} {'Grç':>8} {'Fark':>6} "
          f"{'In':>6} {'Out':>6} {'PT':>5} {'MIP%':>7} {'Grç%':>7} {'Shift':>6}")
    print(f"{'-'*77}")

    for q, r in results.items():
        mi = r['mip_info']; a = r['actual']
        fark = mi['total_kisi'] - a['kisi_total']
        pt = mi.get('total_part_time_kisi', 0)
        print(f"{r['label']:<12} {mi['total_kisi']:>8} {a['kisi_total']:>8} {fark:>+6} "
              f"{mi['total_inhouse_kisi']:>6} {mi['total_outsource_kisi']:>6} {pt:>5} "
              f"{mi['outsource_ratio']:>6.1%} {a['outsource_ratio']:>6.1%} {len(mi['assignments']):>6}")

    t_mip = sum(r['mip_info']['total_kisi'] for r in results.values())
    t_grc = sum(r['actual']['kisi_total'] for r in results.values())
    t_in = sum(r['mip_info']['total_inhouse_kisi'] for r in results.values())
    t_out = sum(r['mip_info']['total_outsource_kisi'] for r in results.values())
    t_out_pct = t_out / t_mip if t_mip > 0 else 0

    print(f"{'-'*77}")
    print(f"{'TOPLAM':<12} {t_mip:>8} {t_grc:>8} {t_mip-t_grc:>+6} "
          f"{t_in:>6} {t_out:>6} {'':>5} {t_out_pct:>6.1%}")

    return results


# =============================================================================
# =============================================================================
#  V7 — HAFTALIK MIP (Pzt-Cum stabil staffing)
# =============================================================================
# =============================================================================
#
# v6'daki günlük optimize_queue'nun haftalık karşılığı: 5 günü tek MIP'te
# çözer, stabil vardiyaları (Pzt-Cum) aynı kişi sayısında tutar, gün-özel
# vardiyalar için ayrı değişken açar.
#
# Kullanım:
#   results = run_week_all_queues(df_calls, df_shifts_dict, WEEK_DATES, CONFIG)
#
# =============================================================================

DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']


def _shift_available_on_day(shift_row_or_dict, day_label):
    """df_shifts satırı veya dict — 'available_days' alanı varsa kontrol et,
    yoksa her gün geçerli kabul et."""
    if hasattr(shift_row_or_dict, 'get'):
        avail = shift_row_or_dict.get('available_days')
    else:
        avail = getattr(shift_row_or_dict, 'available_days', None)
    if avail is None or (isinstance(avail, float) and pd.isna(avail)):
        return True
    if isinstance(avail, (list, tuple, set)):
        return day_label in avail
    if isinstance(avail, str):
        return day_label in [x.strip() for x in avail.split(',')]
    return True


def _classify_shifts_by_days(df_shifts, day_labels=DAY_LABELS):
    """Her shift için hangi günlerde aktif olduğunu döndür.
    Returns: {shift_key: set(day_labels_active)}"""
    out = {}
    for _, row in df_shifts.iterrows():
        key = f"{row['shift']}_{row['company']}"
        active_days = {d for d in day_labels if _shift_available_on_day(row, d)}
        out[key] = active_days
    return out


def _date_to_day_label(date_str):
    """'2026-02-09' → 'Mon'"""
    d = pd.to_datetime(date_str)
    return ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][d.weekday()]


def optimize_week(erlang_by_slot_per_day, df_shifts, queue, target_dates, config,
                  inhouse_min_per_day=None, outsource_min_per_day=None,
                  min_per_shift_override=None,
                  enable_coverage_shortfall=False,
                  coverage_shortfall_penalty=1000.0,
                  verbose=True):
    """5 günlük (Pzt-Cum) haftaiçi için tek MIP.

    Args:
        erlang_by_slot_per_day: {day_label: {slot: erlang_need}}
            day_label: 'Mon'..'Fri'
        df_shifts: pandas DataFrame, kolonlar: shift, start, end, company,
            opsiyonel 'available_days' (liste, hangi günlerde aktif).
        queue: 'kitle' | 'kurumsal' | 'gold'
        target_dates: [date_str, ...] 5 günün tarihleri (raporlama için)
        config: v6 config yapısı
        inhouse_min_per_day: {day_label: {slot: min_in}} (opsiyonel)
        outsource_min_per_day: {day_label: {slot: min_out}} (opsiyonel)
        min_per_shift_override: None ise config'teki default kullanılır,
            aksi halde mcfg['min_per_shift'] yerine bu değer geçerli olur.

    Returns:
        (stable_assignments, day_specific_assignments, info_per_day)
        - stable_assignments: {shift_key: count} → Pzt-Cum boyunca aynı
        - day_specific_assignments: {day_label: {shift_key: count}}
        - info_per_day: {day_label: mip_info dict (v6 ile uyumlu)}
    """
    qcfg = config['queues'][queue]
    qconfigs = config['queue_configs'][queue]
    mcfg = qconfigs['mip']
    scol = config['shift_columns']
    ccfg = config['company']

    allowed = qcfg['companies']
    allowed_values = [ccfg[c]['shift_value'] for c in allowed]
    df_sf = df_shifts[df_shifts[scol['company']].isin(allowed_values)].copy()

    inhouse_value = ccfg['inhouse']['shift_value']
    outsource_value = ccfg['outsource']['shift_value']

    shift_cov = create_shift_coverage(df_sf, config)
    shift_days = _classify_shifts_by_days(df_sf)
    for k, sc in shift_cov.items():
        sc['available_days'] = shift_days.get(k, set(DAY_LABELS))

    shifts = list(shift_cov.keys())

    target_day_labels = [_date_to_day_label(d) for d in target_dates]
    # V7 stabilite kuralı:
    #   - INHOUSE + her gün aktif → stable (tek x[s], Pzt-Cum aynı)
    #   - OUTSOURCE veya gün-kısıtlı → day-specific (her gün ayrı x_day[(s,d)])
    # Bu sayede outsource ekibinin günlük değişebilmesi sağlanır.
    stable_shifts = [s for s in shifts
                     if shift_cov[s]['company'] == inhouse_value
                     and all(d in shift_cov[s]['available_days'] for d in target_day_labels)]
    day_specific_shifts = [s for s in shifts if s not in stable_shifts]

    in_shifts_stable = stable_shifts   # tümü inhouse
    out_shifts_stable = []             # outsource artık stable değil

    if verbose:
        n_out_ds = sum(1 for s in day_specific_shifts
                       if shift_cov[s]['company'] == outsource_value)
        n_in_ds = len(day_specific_shifts) - n_out_ds
        print(f"  [optimize_week] queue={queue}: stable_inhouse={len(stable_shifts)}, "
              f"daily_outsource={n_out_ds}, day_specific_inhouse={n_in_ds}")

    prob = LpProblem(f"Q_{queue}_weekly", LpMinimize)

    x = LpVariable.dicts("x", stable_shifts, lowBound=0, cat='Integer')
    y = LpVariable.dicts("y", stable_shifts, cat='Binary')

    day_shift_pairs = []
    for s in day_specific_shifts:
        for d in target_day_labels:
            if d in shift_cov[s]['available_days']:
                day_shift_pairs.append((s, d))
    x_day = {(s, d): LpVariable(f"x_day_{s}_{d}", lowBound=0, cat='Integer')
             for (s, d) in day_shift_pairs}
    y_day = {(s, d): LpVariable(f"y_day_{s}_{d}", cat='Binary')
             for (s, d) in day_shift_pairs}

    cost = []
    cost_details = []
    pt_shift_keys = []

    # Cost asimetrisini düzelt: stable inhouse her gün çalışır, ama tek cost
    # term'i alır. Day-specific shift'ler ise her (s, d) için ayrı term alır.
    # Stable cost'u n_days ile çarpmazsak inhouse, outsource'a göre n_days kat
    # ucuz görünür ve MIP yanlışlıkla inhouse seçer.
    n_days = len(target_day_labels)

    for s in stable_shifts:
        company_type, base_cost, multiplier, start_hour = _classify_shift(
            s, shift_cov, queue, pt_shift_keys, inhouse_value, mcfg, config)
        final_cost = base_cost * multiplier
        cost.append(x[s] * final_cost * n_days)
        if multiplier != 1.0:
            cost_details.append({
                'shift': s, 'company': company_type, 'start': start_hour,
                'base_cost': base_cost, 'multiplier': multiplier,
                'final_cost': final_cost, 'kind': 'stable',
                'weekly_cost': final_cost * n_days,
            })

    for (s, d) in day_shift_pairs:
        company_type, base_cost, multiplier, start_hour = _classify_shift(
            s, shift_cov, queue, pt_shift_keys, inhouse_value, mcfg, config)
        final_cost = base_cost * multiplier
        cost.append(x_day[(s, d)] * final_cost)
        if multiplier != 1.0:
            cost_details.append({
                'shift': s, 'day': d, 'company': company_type,
                'start': start_hour, 'base_cost': base_cost,
                'multiplier': multiplier, 'final_cost': final_cost,
                'kind': 'day_specific',
            })

    rr_cfg = qconfigs.get('rr_penalty', {})
    rr_enabled = rr_cfg.get('enabled', False)
    rr_penalty_per = rr_cfg.get('penalty_per_person', 5.0)
    rr_peak_exempt = rr_cfg.get('peak_exempt', True)
    rr_peak_thr = rr_cfg.get('peak_threshold', 0.70)
    peak_penalty_per = rr_cfg.get('peak_penalty', rr_penalty_per)
    night_mult_cfg = rr_cfg.get('night_multiplier', {})
    night_mult_enabled = night_mult_cfg.get('enabled', False)
    night_mult_value = night_mult_cfg.get('multiplier', 3.0)
    night_mult_start = night_mult_cfg.get('hours', {}).get('start', '22:00')
    night_mult_end = night_mult_cfg.get('hours', {}).get('end', '08:00')

    def _is_night_slot(slot):
        return is_slot_in_shift(slot, night_mult_start, night_mult_end)

    sc_cfg = qconfigs.get('slot_cap', {})
    sc_enabled = sc_cfg.get('enabled', False)
    sc_bands = sc_cfg.get('bands', [])

    excess_per_day = {}
    sc_excess_per_day = {}
    peak_slots_per_day = {}
    sc_detail_per_day = {}
    # V9: Coverage shortfall — kadro yetmediğinde Erlang ihtiyacının altına
    # düşmeye izin verir (yüksek penalty ile, son çare). MIP her zaman çözer.
    shortfall_vars_per_day = {}   # (day_label, slot) → shortfall LpVar

    for day_label in target_day_labels:
        erlang_by_slot = erlang_by_slot_per_day.get(day_label, {})
        active_slots = [s for s in SLOTS_30 if erlang_by_slot.get(s, 0) > 0]

        peak_slots = set()
        if rr_enabled and active_slots:
            max_erlang = max(erlang_by_slot.get(s, 0) for s in active_slots)
            if rr_peak_exempt and max_erlang > 0:
                peak_slots = {s for s in active_slots
                              if erlang_by_slot.get(s, 0) >= max_erlang * rr_peak_thr}
        peak_slots_per_day[day_label] = peak_slots

        sc_detail_per_day[day_label] = []

        for slot in active_slots:
            erlang_need = erlang_by_slot.get(slot, 0)
            if erlang_need <= 0:
                continue

            covering_stable = [s for s in stable_shifts
                               if slot in shift_cov[s]['slots']]
            covering_day = [(s, day_label) for (s, d) in day_shift_pairs
                            if d == day_label and slot in shift_cov[s]['slots']]

            if not (covering_stable or covering_day):
                continue

            total_cov_expr = (
                lpSum([x[s] for s in covering_stable]) +
                lpSum([x_day[pair] for pair in covering_day])
            )
            # V9: Coverage shortfall — soft constraint
            if enable_coverage_shortfall:
                sf_var = LpVariable(f"sf_{day_label}_{slot}",
                                     lowBound=0, cat='Continuous')
                shortfall_vars_per_day[(day_label, slot)] = sf_var
                # covered + shortfall ≥ erlang_need (yumuşatılmış)
                prob += total_cov_expr + sf_var >= erlang_need
                cost.append(sf_var * coverage_shortfall_penalty)
            else:
                # Sert (default) kısıt
                prob += total_cov_expr >= erlang_need

            if rr_enabled:
                exc = LpVariable(f"exc_{day_label}_{slot}",
                                 lowBound=0, cat='Continuous')
                prob += exc >= total_cov_expr - erlang_need
                excess_per_day[(day_label, slot)] = exc
                if slot in peak_slots:
                    eff_pen = peak_penalty_per
                elif night_mult_enabled and _is_night_slot(slot):
                    eff_pen = rr_penalty_per * night_mult_value
                else:
                    eff_pen = rr_penalty_per
                cost.append(exc * eff_pen)

            if sc_enabled and sc_bands:
                matched_band = None
                for band in sc_bands:
                    if is_slot_in_shift(slot, band['start'], band['end']):
                        matched_band = band
                        break
                if matched_band is not None:
                    band_ratio = matched_band.get('max_ratio', 1.20)
                    band_pen = matched_band.get('penalty', 50.0)
                    cap = max(math.ceil(erlang_need * band_ratio), 3)
                    sc_exc = LpVariable(f"sc_exc_{day_label}_{slot}",
                                        lowBound=0, cat='Continuous')
                    prob += sc_exc >= total_cov_expr - cap
                    sc_excess_per_day[(day_label, slot)] = (sc_exc, band_pen)
                    cost.append(sc_exc * band_pen)
                    sc_detail_per_day[day_label].append({
                        'slot': slot, 'erlang': erlang_need, 'cap': cap,
                        'ratio': band_ratio, 'penalty': band_pen,
                        'band': f"{matched_band['start']}-{matched_band['end']}"
                    })

        if inhouse_min_per_day:
            day_min = inhouse_min_per_day.get(day_label, {})
            for slot, min_in in day_min.items():
                if min_in <= 0:
                    continue
                cov_in_stable = [s for s in stable_shifts
                                 if shift_cov[s]['company'] == inhouse_value
                                 and slot in shift_cov[s]['slots']]
                cov_in_day = [(s, day_label) for (s, d) in day_shift_pairs
                              if d == day_label
                              and shift_cov[s]['company'] == inhouse_value
                              and slot in shift_cov[s]['slots']]
                if cov_in_stable or cov_in_day:
                    prob += (lpSum([x[s] for s in cov_in_stable]) +
                             lpSum([x_day[p] for p in cov_in_day])) >= min_in

        if outsource_min_per_day:
            day_min = outsource_min_per_day.get(day_label, {})
            for slot, min_out in day_min.items():
                if min_out <= 0:
                    continue
                cov_out_stable = [s for s in stable_shifts
                                  if shift_cov[s]['company'] == outsource_value
                                  and slot in shift_cov[s]['slots']]
                cov_out_day = [(s, day_label) for (s, d) in day_shift_pairs
                               if d == day_label
                               and shift_cov[s]['company'] == outsource_value
                               and slot in shift_cov[s]['slots']]
                if cov_out_stable or cov_out_day:
                    prob += (lpSum([x[s] for s in cov_out_stable]) +
                             lpSum([x_day[p] for p in cov_out_day])) >= min_out

    M = 500
    # V8: min_per_shift_override scalar VEYA dict olabilir.
    #   - scalar (int)  → tüm shift'ler için tek değer
    #   - dict {day_label: int} → day-specific shift'ler için per-day override;
    #     stable inhouse shift'ler her zaman default (single var, per-day yapılamaz)
    if isinstance(min_per_shift_override, dict):
        min_per_day_override = min_per_shift_override
        min_default_global = mcfg['min_per_shift']
    elif min_per_shift_override is not None:
        min_per_day_override = None
        min_default_global = min_per_shift_override
    else:
        min_per_day_override = None
        min_default_global = mcfg['min_per_shift']
    min_overrides = mcfg.get('min_per_shift_overrides', {})

    for s in stable_shifts:
        prob += x[s] <= M * y[s]
        start_hour = shift_cov[s]['start']
        # Stable shift'ler her zaman global default kullanır (per-day yapılamaz)
        min_v = min_overrides.get(start_hour, min_default_global)
        prob += x[s] >= min_v * y[s]

    for (s, d) in day_shift_pairs:
        prob += x_day[(s, d)] <= M * y_day[(s, d)]
        start_hour = shift_cov[s]['start']
        if min_per_day_override is not None and d in min_per_day_override:
            # Day-specific shift için bu güne özgü min
            min_v = min_per_day_override[d]
        else:
            min_v = min_overrides.get(start_hour, min_default_global)
        prob += x_day[(s, d)] >= min_v * y_day[(s, d)]

    # Kadro tavanları:
    #   - INHOUSE: stable + her günün day-specific inhouse'u toplamı her gün
    #     için kadro_in'i aşmasın. Stable kısım zaten her gün aynı.
    #   - OUTSOURCE: her gün ayrı kapasitede çalışabildiği için her gün
    #     ayrı cap uygulanır.
    kadro_cfg = config.get('surplus_distribution', {}).get('total_kadro', {}).get(queue, {})
    kadro_in = kadro_cfg.get('inhouse', 0)
    kadro_out = kadro_cfg.get('outsource', 0)

    if kadro_in > 0:
        for d in target_day_labels:
            in_day_specific_pairs = [
                (s, d) for (s, d_p) in day_shift_pairs
                if d_p == d and shift_cov[s]['company'] == inhouse_value
            ]
            terms = []
            if in_shifts_stable:
                terms.append(lpSum([x[s] for s in in_shifts_stable]))
            if in_day_specific_pairs:
                terms.append(lpSum([x_day[p] for p in in_day_specific_pairs]))
            if terms:
                prob += lpSum(terms) <= kadro_in

    if kadro_out > 0:
        for d in target_day_labels:
            out_day_pairs = [
                (s, d) for (s, d_p) in day_shift_pairs
                if d_p == d and shift_cov[s]['company'] == outsource_value
            ]
            if out_day_pairs:
                prob += lpSum([x_day[p] for p in out_day_pairs]) <= kadro_out

    # =========================================================================
    # BALANCE PENALTY — pencere bazlı inhouse/outsource dengesi
    # Outsource gün-spesifik olduğu için her gün için ayrı diff variable.
    # Stable inhouse + day-specific inhouse vs day-specific outsource karşılaştırılır.
    # =========================================================================
    only_inhouse = (allowed == ['inhouse'])
    bp_cfg = qconfigs.get('balance_penalty', config.get('balance_penalty', {}))
    bp_enabled = bp_cfg.get('enabled', False) and not only_inhouse
    bp_windows = bp_cfg.get('windows', [])
    bp_penalty_default = bp_cfg.get('penalty_per_diff', 2.0)
    balance_vars_per_day = {}  # (day_label, win_name) → vars + shift refs

    if bp_enabled and bp_windows:
        for day_label in target_day_labels:
            for win in bp_windows:
                win_name = win['name']
                win_start = win['start']
                win_end = win['end']

                # Stable inhouse — her gün aynı, bu yüzden tüm günlerde geçerli
                stable_in_in_win = [s for s in stable_shifts
                                     if shift_cov[s]['company'] == inhouse_value
                                     and win_start <= shift_cov[s]['start'] <= win_end]
                # Bu gün için day-specific inhouse pencere içinde
                ds_in_in_win = [(s, day_label) for (s, d_p) in day_shift_pairs
                                if d_p == day_label
                                and shift_cov[s]['company'] == inhouse_value
                                and win_start <= shift_cov[s]['start'] <= win_end]
                # Bu gün için day-specific outsource pencere içinde
                ds_out_in_win = [(s, day_label) for (s, d_p) in day_shift_pairs
                                 if d_p == day_label
                                 and shift_cov[s]['company'] == outsource_value
                                 and win_start <= shift_cov[s]['start'] <= win_end]

                # İki taraf da boşsa balance anlamsız
                if not (stable_in_in_win or ds_in_in_win) or not ds_out_in_win:
                    continue

                tag = f"{day_label}_{win_name}"
                diff_pos = LpVariable(f"bp_{tag}_pos", lowBound=0, cat='Continuous')
                diff_neg = LpVariable(f"bp_{tag}_neg", lowBound=0, cat='Continuous')

                in_total_expr = (lpSum([x[s] for s in stable_in_in_win]) +
                                 lpSum([x_day[p] for p in ds_in_in_win]))
                out_total_expr = lpSum([x_day[p] for p in ds_out_in_win])
                prob += diff_pos - diff_neg == in_total_expr - out_total_expr

                win_penalty = win.get('penalty', bp_penalty_default)
                cost.append((diff_pos + diff_neg) * win_penalty)

                balance_vars_per_day[(day_label, win_name)] = {
                    'diff_pos': diff_pos, 'diff_neg': diff_neg,
                    'stable_in': stable_in_in_win,
                    'ds_in_pairs': ds_in_in_win,
                    'ds_out_pairs': ds_out_in_win,
                    'penalty': win_penalty,
                }

    prob += lpSum(cost)

    solver = PULP_CBC_CMD(msg=0)
    prob.solve(solver)
    status = LpStatus[prob.status]
    if verbose:
        print(f"  [optimize_week] solver status: {status}")

    if status != 'Optimal':
        return None, None, None

    # Sadece >0 olan atamaları sakla — v6 ile uyumlu, raporda 0-li satır çıkmasın
    stable_assignments = {s: int(round(value(x[s]) or 0)) for s in stable_shifts}
    stable_assignments = {s: v for s, v in stable_assignments.items() if v > 0}

    day_specific_assignments = {d: {} for d in target_day_labels}
    for (s, d), var in x_day.items():
        v = int(round(value(var) or 0))
        if v > 0:
            day_specific_assignments[d][s] = v

    info_per_day = {}
    for day_label, target_date in zip(target_day_labels, target_dates):
        erlang_by_slot = erlang_by_slot_per_day.get(day_label, {})
        assigns_this_day = dict(stable_assignments)
        for s, v in day_specific_assignments[day_label].items():
            assigns_this_day[s] = assigns_this_day.get(s, 0) + v

        mip_by_slot = {}
        mip_in_by_slot = {}
        mip_out_by_slot = {}
        for slot in SLOTS_30:
            tot = in_v = out_v = 0
            for s, v in assigns_this_day.items():
                if v <= 0 or slot not in shift_cov[s]['slots']:
                    continue
                tot += v
                if shift_cov[s]['company'] == inhouse_value:
                    in_v += v
                elif shift_cov[s]['company'] == outsource_value:
                    out_v += v
            mip_by_slot[slot] = tot
            mip_in_by_slot[slot] = in_v
            mip_out_by_slot[slot] = out_v

        rr_excess_by_slot = {}
        rr_total_excess = rr_total_penalty_cost = rr_penalized_slots = 0
        if rr_enabled:
            peak_slots = peak_slots_per_day.get(day_label, set())
            for (d_l, slot), exc_var in excess_per_day.items():
                if d_l != day_label:
                    continue
                val = value(exc_var) or 0
                if val > 0.5:
                    exc_int = int(round(val))
                    rr_excess_by_slot[slot] = exc_int
                    rr_total_excess += exc_int
                    if slot in peak_slots:
                        rr_total_penalty_cost += exc_int * peak_penalty_per
                    elif night_mult_enabled and _is_night_slot(slot):
                        rr_total_penalty_cost += exc_int * rr_penalty_per * night_mult_value
                    else:
                        rr_total_penalty_cost += exc_int * rr_penalty_per
                    rr_penalized_slots += 1

        sc_excess_by_slot = {}
        sc_total_excess = sc_total_penalty_cost = sc_penalized_slots = 0
        for (d_l, slot), (exc_var, pen) in sc_excess_per_day.items():
            if d_l != day_label:
                continue
            val = value(exc_var) or 0
            if val > 0.5:
                exc_int = int(round(val))
                sc_excess_by_slot[slot] = (exc_int, pen)
                sc_total_excess += exc_int
                sc_total_penalty_cost += exc_int * pen
                sc_penalized_slots += 1

        # Balance penalty sonuçları — bu gün için pencere bazlı
        balance_result = {}
        if bp_enabled and balance_vars_per_day:
            for (d_l, win_name), bv in balance_vars_per_day.items():
                if d_l != day_label:
                    continue
                dp = value(bv['diff_pos']) or 0
                dn = value(bv['diff_neg']) or 0
                in_tot = (sum(assigns_this_day.get(s, 0) for s in bv['stable_in']) +
                          sum(assigns_this_day.get(s, 0) for (s, _) in bv['ds_in_pairs']))
                out_tot = sum(assigns_this_day.get(s, 0) for (s, _) in bv['ds_out_pairs'])
                balance_result[win_name] = {
                    'inhouse': in_tot,
                    'outsource': out_tot,
                    'diff': in_tot - out_tot,
                    'abs_diff': abs(in_tot - out_tot),
                    'penalty_cost': (dp + dn) * bv['penalty'],
                }

        _total_in = sum(v for s, v in assigns_this_day.items()
                        if shift_cov[s]['company'] == inhouse_value)
        _total_out = sum(v for s, v in assigns_this_day.items()
                         if shift_cov[s]['company'] == outsource_value)
        _total_all = sum(assigns_this_day.values())
        info = {
            'assignments': assigns_this_day,
            'shift_coverage': shift_cov,
            # MIP'in fiilen çözüldüğü Erlang ihtiyacı (shrinkage fallback
            # devreye girdiyse azaltılmış değer). Raporlar bunu kullansın,
            # yoksa orijinal Erlang gösterilince "MIP, Erlang'ı karşılamıyor"
            # gibi yanıltıcı görünüyor.
            'erlang_by_slot': dict(erlang_by_slot),
            'mip_by_slot': mip_by_slot,
            'mip_in_by_slot': mip_in_by_slot,
            'mip_out_by_slot': mip_out_by_slot,
            'mip_pt_by_slot': {s: 0 for s in SLOTS_30},
            'total_kisi': _total_all,
            'total_inhouse_kisi': _total_in,
            'total_outsource_kisi': _total_out,
            'total_part_time_kisi': 0,
            'outsource_ratio': (_total_out / _total_all) if _total_all > 0 else 0,
            'pt_available': 0,
            'cost_details': cost_details,
            'rr_penalty_enabled': rr_enabled,
            'rr_excess_by_slot': rr_excess_by_slot,
            'rr_total_excess': rr_total_excess,
            'rr_total_penalty_cost': rr_total_penalty_cost,
            'rr_penalized_slots': rr_penalized_slots,
            'rr_peak_slots': peak_slots_per_day.get(day_label, set()),
            'slot_cap_detail': sc_detail_per_day.get(day_label, []),
            'sc_excess_by_slot': sc_excess_by_slot,
            'sc_total_excess': sc_total_excess,
            'sc_total_penalty_cost': sc_total_penalty_cost,
            'sc_penalized_slots': sc_penalized_slots,
            'balance_penalty_enabled': bp_enabled,
            'balance_result': balance_result,
            'target_date': target_date,
            'day_label': day_label,
            'weekly_stable_assignments': stable_assignments,
            'weekly_day_specific': day_specific_assignments[day_label],
        }

        # V9: Coverage shortfall sonuçları
        sf_by_slot = {}
        total_sf = 0
        if enable_coverage_shortfall:
            for (d_l, slot), sf_var in shortfall_vars_per_day.items():
                if d_l != day_label:
                    continue
                val = value(sf_var) or 0
                if val > 0.5:
                    sf_int = int(round(val))
                    sf_by_slot[slot] = sf_int
                    total_sf += sf_int
        info['coverage_shortfall_enabled'] = enable_coverage_shortfall
        info['shortfall_by_slot'] = sf_by_slot
        info['total_shortfall'] = total_sf

        info_per_day[day_label] = info

    return stable_assignments, day_specific_assignments, info_per_day


def _distribute_surplus_per_day(stable_assignments, day_specific_assignments,
                                 info_per_day, erlang_by_slot_per_day, queue,
                                 config, verbose=True):
    """Her gün için ayrı surplus dağıtımı (v7 weekly).

    v6 daily distribute_surplus mantığı, haftaiçi her güne ayrı uygulanır:
      - O günün toplam inhouse / outsource'una göre fazlayı hesapla
      - v6 pencere oranları + rr_first yöntemi
      - Stable atamalara DOKUNULMAZ — eklenen kişiler day_specific olarak
        günün assignment'una yazılır (Pzt-Cum'a yayılmaması için).

    Her gün için info_per_day[d]'ye 'mip_info_stage1' eklenir (surplus öncesi
    snapshot) ve info güncellenir.

    Returns: güncellenmiş (stable_assignments, day_specific_assignments, info_per_day)
    """
    sd_cfg = config.get('surplus_distribution', {})
    if not sd_cfg.get('enabled', False):
        return stable_assignments, day_specific_assignments, info_per_day

    kadro_cfg = sd_cfg.get('total_kadro', {}).get(queue, {})
    total_in_kadro = kadro_cfg.get('inhouse', 0)
    total_out_kadro = kadro_cfg.get('outsource', 0)

    if total_in_kadro <= 0 and total_out_kadro <= 0:
        return stable_assignments, day_specific_assignments, info_per_day

    method = sd_cfg.get('method', 'rr_first')
    only_assigned = sd_cfg.get('only_assigned_shifts', True)
    fallback = sd_cfg.get('fallback_all_inhouse', True)
    windows = sd_cfg.get('windows', [])
    out_enabled = sd_cfg.get('outsource_enabled', True)

    ccfg = config['company']
    inhouse_value = ccfg['inhouse']['shift_value']
    outsource_value = ccfg['outsource']['shift_value']

    # shift_cov tüm günlerde aynı
    sample_info = next(iter(info_per_day.values()))
    shift_cov = sample_info['shift_coverage']

    for d_label, info in info_per_day.items():
        # 1) surplus öncesi snapshot — v6 ile uyumlu rapor için
        info['mip_info_stage1'] = copy.deepcopy(info)

        current_in = info['total_inhouse_kisi']
        current_out = info['total_outsource_kisi']
        surplus_in = max(0, total_in_kadro - current_in)
        surplus_out = max(0, total_out_kadro - current_out) if out_enabled else 0

        if verbose:
            print(f"   ➕ Surplus [{d_label}]: in={surplus_in} (kadro {total_in_kadro}-{current_in}), "
                  f"out={surplus_out} (kadro {total_out_kadro}-{current_out})")

        if surplus_in <= 0 and surplus_out <= 0:
            continue
        if not windows:
            if verbose:
                print(f"      ⚠ pencere tanımı yok, atlanıyor")
            continue

        # 2) Eligible shift'ler: o gün aktif olan TÜM shift'ler (stable +
        #    day-specific). Stable'a eklersek bile day-specific olarak yazacağız.
        day_specific_today = day_specific_assignments.get(d_label, {})
        current_assigns_today = dict(stable_assignments)
        for s, v in day_specific_today.items():
            current_assigns_today[s] = current_assigns_today.get(s, 0) + v

        in_shifts = [s for s, sc in shift_cov.items()
                     if sc['company'] == inhouse_value]
        out_shifts = [s for s, sc in shift_cov.items()
                      if sc['company'] == outsource_value]

        if only_assigned:
            eligible_in = [s for s in in_shifts if current_assigns_today.get(s, 0) > 0]
            eligible_out = [s for s in out_shifts if current_assigns_today.get(s, 0) > 0]
        else:
            eligible_in = in_shifts
            eligible_out = out_shifts

        erlang_by_slot = erlang_by_slot_per_day.get(d_label, {})
        local_mip_by_slot = dict(info['mip_by_slot'])
        added_today = {}

        for company_label, surplus, eligible in [
            ('inhouse', surplus_in, eligible_in),
            ('outsource', surplus_out, eligible_out),
        ]:
            if surplus <= 0 or not eligible:
                continue

            win_cands = {win['name']: [s for s in eligible
                                       if win['start'] <= shift_cov[s]['start'] <= win['end']]
                         for win in windows}
            if all(len(c) == 0 for c in win_cands.values()):
                if fallback and eligible:
                    windows_eff = [{'name': 'fallback', 'start': '00:00', 'end': '23:59', 'ratio': 1.0}]
                    win_cands = {'fallback': eligible}
                else:
                    continue
            else:
                windows_eff = windows

            active_windows = [w for w in windows_eff if win_cands.get(w['name'])]
            ratio_sum = sum(w['ratio'] for w in active_windows)
            if ratio_sum == 0:
                continue

            raw_shares = {w['name']: surplus * (w['ratio'] / ratio_sum)
                          for w in active_windows}
            floor_shares = {n: int(v) for n, v in raw_shares.items()}
            leftover = surplus - sum(floor_shares.values())
            fracs = sorted(((n, raw_shares[n] - floor_shares[n]) for n in floor_shares),
                           key=lambda x: x[1], reverse=True)
            for i in range(leftover):
                floor_shares[fracs[i % len(fracs)][0]] += 1

            if verbose:
                share_str = ", ".join(f"{w['name']}={floor_shares[w['name']]}"
                                       for w in active_windows)
                print(f"      [{company_label}] surplus={surplus}, pencereler: {share_str}")

            for win in active_windows:
                share = floor_shares[win['name']]
                if share <= 0:
                    continue
                cands = win_cands[win['name']]
                added_w, _used_rr, _used_prop = _allocate_within_pool(
                    share, cands, shift_cov, erlang_by_slot,
                    current_assigns_today, local_mip_by_slot, method
                )
                for s, n in added_w.items():
                    if n > 0:
                        added_today[s] = added_today.get(s, 0) + n

        if not added_today:
            continue

        # 3) Eklenen kişileri day_specific'e yaz (stable bozulmasın)
        for s, n in added_today.items():
            day_specific_today[s] = day_specific_today.get(s, 0) + n
            info['assignments'][s] = info['assignments'].get(s, 0) + n
        day_specific_assignments[d_label] = day_specific_today

        # 4) info'nun aggregate'lerini yeniden hesapla
        in_all = [s for s, sc in shift_cov.items() if sc['company'] == inhouse_value]
        out_all = [s for s, sc in shift_cov.items() if sc['company'] == outsource_value]
        for slot in info['mip_by_slot']:
            info['mip_by_slot'][slot] = sum(info['assignments'].get(s, 0)
                                            for s in shift_cov if slot in shift_cov[s]['slots'])
            info['mip_in_by_slot'][slot] = sum(info['assignments'].get(s, 0)
                                               for s in in_all if slot in shift_cov[s]['slots'])
            info['mip_out_by_slot'][slot] = sum(info['assignments'].get(s, 0)
                                                for s in out_all if slot in shift_cov[s]['slots'])

        added_in = sum(n for s, n in added_today.items()
                       if shift_cov[s]['company'] == inhouse_value)
        added_out = sum(n for s, n in added_today.items()
                        if shift_cov[s]['company'] == outsource_value)
        info['total_inhouse_kisi'] = current_in + added_in
        info['total_outsource_kisi'] = current_out + added_out
        info['total_kisi'] = info['total_inhouse_kisi'] + info['total_outsource_kisi']
        info['outsource_ratio'] = (info['total_outsource_kisi'] / info['total_kisi']
                                    if info['total_kisi'] > 0 else 0)
        info['surplus_added'] = added_today
        info['surplus_total_added'] = sum(added_today.values())

        if verbose:
            print(f"      ✓ [{d_label}] eklenen: in={added_in}, out={added_out} "
                  f"→ yeni toplam in={info['total_inhouse_kisi']}, "
                  f"out={info['total_outsource_kisi']}")

    return stable_assignments, day_specific_assignments, info_per_day


def print_weekly_summary(stable_assignments, day_specific_assignments,
                         shift_cov, queue, target_dates):
    """Haftanın stable inhouse vardiya listesi + günlük outsource + day-specific."""
    print(f"\n{'='*90}")
    print(f"HAFTALIK ATAMA — {queue.upper()}")
    print(f"  Tarih aralığı: {target_dates[0]} → {target_dates[-1]}")
    print(f"{'='*90}")

    # 1) Stable INHOUSE
    print(f"\n  STABLE INHOUSE (Pzt-Cum aynı kişi):")
    if not stable_assignments or all(v == 0 for v in stable_assignments.values()):
        print("    (yok)")
    else:
        print(f"    {'Vardiya':<32} {'Saat':<14} {'Kişi':>6}")
        print(f"    {'-'*60}")
        active = [(s, v) for s, v in stable_assignments.items() if v > 0]
        for s, v in sorted(active, key=lambda x: shift_cov[x[0]]['start']):
            sc = shift_cov[s]
            saat = f"{sc['start']}-{sc['end']}"
            print(f"    {s:<32} {saat:<14} {v:>6}")
        print(f"    {'-'*60}")
        print(f"    {'TOPLAM':<48} {sum(v for _, v in active):>6}")

    # 2) Günlük OUTSOURCE + day-specific inhouse — gün gün
    has_extra = any(d for d in day_specific_assignments.values())
    if has_extra:
        print(f"\n  GÜNLÜK DEĞİŞKEN (outsource her gün + gün-özel inhouse):")
        for d_label, day_assigns in day_specific_assignments.items():
            if not day_assigns:
                continue
            print(f"    --- {d_label} ---")
            print(f"    {'Vardiya':<32} {'Saat':<14} {'Şirket':<10} {'Kişi':>6}")
            for s, v in sorted(day_assigns.items(), key=lambda x: shift_cov[x[0]]['start']):
                sc = shift_cov[s]
                saat = f"{sc['start']}-{sc['end']}"
                print(f"    {s:<32} {saat:<14} {sc['company']:<10} {v:>6}")


def _decrement_shrinkage_cfg(shrinkage_cfg, decrement):
    """Option A — saatlik dict shrinkage'da her değerden `decrement` çıkar, 0'da kıs.

    Skaler ise tek değerden çıkar. Profili kabaca korur; düşük olanlar erken sıfırlanır.
    """
    if isinstance(shrinkage_cfg, dict):
        return {k: max(0.0, float(v) - decrement) for k, v in shrinkage_cfg.items()}
    return max(0.0, float(shrinkage_cfg) - decrement)


def _build_erlang_per_day(df_calls_30, queue, target_dates, config):
    """Verilen config ile Erlang hesapla, gün bazlı {day_label: {slot: need}} döndür."""
    df_erl = calculate_erlang_all(df_calls_30, config=config)
    out = {}
    for date_str in target_dates:
        d = pd.to_datetime(date_str)
        day_label = _date_to_day_label(date_str)
        df_q = df_erl[(df_erl['date'] == d) & (df_erl['queue'] == queue)]
        out[day_label] = dict(zip(df_q['slot'], df_q['erlang_need']))
    return out


def _build_erlang_per_day_individual(df_calls_30, queue, target_dates,
                                       base_config, decrements_per_day,
                                       floor=0.0):
    """V8 — her gün için AYRI decrement uygulayarak Erlang hesapla.

    decrements_per_day: {day_label: decrement} (örn. {'Mon': 0.20, 'Tue': 0.0, ...})

    Her gün için orijinal shrinkage'a o günün decrement'ini uygular, sonra
    o güne ait Erlang'ı yeniden hesaplayıp döner.
    Bir gün decrement=0 ise orijinal Erlang (tek bir defa hesap dahili cache'lenebilir
    ama küçük overhead için tekrar hesaplıyoruz; semantik temiz).
    """
    base_shr = base_config['queue_configs'][queue]['erlang']['shrinkage']
    out = {}
    for date_str in target_dates:
        d = pd.to_datetime(date_str)
        day_label = _date_to_day_label(date_str)
        dec = decrements_per_day.get(day_label, 0.0)

        if dec == 0.0:
            new_shr = base_shr
        else:
            new_shr = _decrement_shrinkage_cfg(base_shr, dec)
            if isinstance(new_shr, dict):
                new_shr = {k: max(floor, v) for k, v in new_shr.items()}
            else:
                new_shr = max(floor, new_shr)

        cfg_t = copy.deepcopy(base_config)
        cfg_t['queue_configs'][queue]['erlang']['shrinkage'] = new_shr
        df_erl = calculate_erlang_all(df_calls_30, config=cfg_t)
        df_q = df_erl[(df_erl['date'] == d) & (df_erl['queue'] == queue)]
        out[day_label] = dict(zip(df_q['slot'], df_q['erlang_need']))
    return out


def _print_trial_log_v8(trial_log, queue, solution_stage_label=None):
    """V8 — fallback ladder denemelerini tablo halinde bas."""
    print(f"\n  ┌─ Fallback Ladder ({queue}) ─┐")
    print(f"  │ {'#':>3} {'Stage':<58} {'min':>14} {'Erlang':>8} {'Sonuç':<11} │")
    for t in trial_log:
        marker = ' ←' if t.get('stage') == solution_stage_label else '  '
        stage_short = t['stage'][:58] if len(t['stage']) <= 58 else t['stage'][:55] + '..'
        # min_per_shift: int veya dict olabilir → string'e çevir
        m = t['min_per_shift']
        if isinstance(m, dict):
            # Sadece default'tan farklı olanları compact göster
            uniq = set(m.values())
            if len(uniq) == 1:
                min_str = str(next(iter(uniq)))
            else:
                min_str = ','.join(f"{d}:{v}" for d, v in m.items())
        else:
            min_str = str(m)
        if len(min_str) > 14:
            min_str = min_str[:12] + '..'
        print(f"  │ {t['idx']:>3} {stage_short:<58} {min_str:>14} "
              f"{t['erlang_total']:>8} {t['status']:<11}{marker}│")
    print(f"  └{'─' * 102}┘")


def run_week_all_queues(df_calls, df_shifts_by_queue, target_dates, config,
                        queues=('kitle', 'kurumsal', 'gold'), verbose=True):
    """V8 — 3-aşamalı cascading fallback ile haftalık MIP çağrısı.

    AŞAMA 1: Orijinal config (default shrinkage, default min_per_shift)
    AŞAMA 2: Shrinkage azaltma
       - per_day=True (V8 önerilen): worst-day-first sırayla SADECE bottleneck günü azalt
       - per_day=False (V7 backward compat): TÜM günleri uniform azalt
    AŞAMA 3: min_per_shift azaltma (uniform, tüm shift'lere)
       - Shrinkage tüm günlerde floor'da, hâlâ infeasible
       - min_per_shift = default → default-step → ... → floor

    Returns: {queue: {'stable', 'day_specific', 'info_per_day',
                       'solution_stage', 'decrements_per_day_used',
                       'min_per_shift_used', 'shrinkage_trial_log'}}
    """
    df_calls_30 = prepare_calls_30(df_calls, config=config)
    day_labels = [_date_to_day_label(d) for d in target_dates]

    results = {}
    for queue in queues:
        if verbose:
            print(f"\n{'#'*80}\n# {queue.upper()} HAFTALIK MIP (V8)\n{'#'*80}")

        df_shifts = df_shifts_by_queue.get(queue)
        if df_shifts is None or df_shifts.empty:
            if verbose:
                print(f"  {queue}: vardiya yok, atlandı.")
            continue

        # ---- Config'leri oku ----
        mcfg = config['queue_configs'][queue]['mip']
        default_min = mcfg['min_per_shift']

        wsf_cfg = mcfg.get('weekly_shrinkage_fallback', {})
        wsf_enabled = wsf_cfg.get('enabled', False)
        wsf_per_day = wsf_cfg.get('per_day', False)
        wsf_step = float(wsf_cfg.get('step', 0.10))
        wsf_floor = float(wsf_cfg.get('floor', 0.0))

        wmpsf_cfg = mcfg.get('weekly_min_per_shift_fallback', {})
        wmpsf_enabled = wmpsf_cfg.get('enabled', False)
        wmpsf_step = max(1, int(wmpsf_cfg.get('step', 1)))
        wmpsf_floor = max(1, int(wmpsf_cfg.get('floor', 1)))

        # V9: Coverage shortfall config (Stage 4)
        cs_cfg = mcfg.get('coverage_shortfall', {})
        cs_enabled = cs_cfg.get('enabled', False)
        cs_penalty = float(cs_cfg.get('penalty', 1000.0))

        original_shrinkage = config['queue_configs'][queue]['erlang']['shrinkage']
        if isinstance(original_shrinkage, dict):
            max_shr = max((float(v) for v in original_shrinkage.values()), default=0.0)
        else:
            max_shr = float(original_shrinkage)

        # ---- Günleri çağrı sayısına göre sırala (büyükten küçüğe) ----
        # Bottleneck heuristic: en çok çağrı = en kritik gün
        calls_per_day = {}
        calls_col = f"{queue}_total"
        for date_str in target_dates:
            d = pd.to_datetime(date_str)
            day_label = _date_to_day_label(date_str)
            df_day = df_calls_30[df_calls_30['data_date'] == d]
            calls_per_day[day_label] = (int(df_day[calls_col].sum())
                                         if calls_col in df_day.columns else 0)
        days_by_calls = sorted(day_labels,
                               key=lambda d: calls_per_day[d], reverse=True)
        if verbose:
            calls_str = ', '.join(f"{d}={calls_per_day[d]:,}" for d in days_by_calls)
            print(f"  Çağrı sıralaması (büyükten küçüğe): {calls_str}")

        # ---- State ----
        decrements_per_day = {d: 0.0 for d in day_labels}
        mins_per_day = {d: default_min for d in day_labels}
        trial_log = []
        stable = day_specific = info_per_day = None
        solution_stage = None
        last_erl_pd = None

        def _trial(stage_label, min_param, enable_shortfall=False):
            """min_param: int (scalar/uniform) veya dict {day_label: int}
            enable_shortfall: V9 Stage 4 için True — coverage shortfall aktif.
            """
            nonlocal last_erl_pd
            # Erlang'ı oluştur
            if any(v > 0 for v in decrements_per_day.values()):
                erl_pd = _build_erlang_per_day_individual(
                    df_calls_30, queue, target_dates, config,
                    decrements_per_day, floor=wsf_floor,
                )
            else:
                erl_pd = _build_erlang_per_day(
                    df_calls_30, queue, target_dates, config)

            erl_total = sum(sum(v.values()) for v in erl_pd.values())
            idx = len(trial_log)

            # min_param'ı optimize_week'e nasıl geçireceğiz?
            if isinstance(min_param, dict):
                # Her gün default ise None (yani default kullan), aksi halde dict
                if all(v == default_min for v in min_param.values()):
                    min_arg = None
                    min_summary = f"min={default_min}"
                else:
                    min_arg = min_param
                    non_default = {d: v for d, v in min_param.items()
                                    if v != default_min}
                    min_summary = "min=" + ','.join(
                        f"{d}:{v}" for d, v in non_default.items())
            else:
                min_arg = min_param if min_param != default_min else None
                min_summary = f"min={min_param}"

            sf_summary = " +shortfall" if enable_shortfall else ""
            if verbose:
                print(f"\n  [trial #{idx}] {stage_label}  "
                      f"→ Erlang toplam={erl_total}  {min_summary}{sf_summary}")

            stable_try, day_try, info_try = optimize_week(
                erl_pd, df_shifts, queue, target_dates, config,
                min_per_shift_override=min_arg,
                enable_coverage_shortfall=enable_shortfall,
                coverage_shortfall_penalty=cs_penalty,
                verbose=verbose,
            )
            status = 'OPTIMAL' if stable_try is not None else 'INFEASIBLE'
            trial_log.append({
                'idx': idx,
                'stage': stage_label,
                'decrements_per_day': dict(decrements_per_day),
                # Geriye dönük uyumluluk için 'decrement' alanı = max
                'decrement': max(decrements_per_day.values()) if decrements_per_day else 0.0,
                'min_per_shift': (dict(min_param) if isinstance(min_param, dict)
                                   else min_param),
                'erlang_total': erl_total,
                'status': status,
            })
            if stable_try is not None:
                last_erl_pd = erl_pd
            return stable_try, day_try, info_try

        # ============== AŞAMA 1: Orijinal ==============
        stable, day_specific, info_per_day = _trial('STAGE 1: original', default_min)
        if stable is not None:
            solution_stage = 'STAGE 1: original'
            if verbose:
                print(f"\n  ✓ Orijinal config ile çözüldü")

        # ============== AŞAMA 2: Shrinkage fallback ==============
        if stable is None and wsf_enabled and max_shr > wsf_floor:
            if wsf_per_day:
                # Per-day: en çok çağrı alan günden başlayarak SADECE o günü azalt
                if verbose:
                    print(f"\n  ▶ STAGE 2 (per-day shrinkage) — çağrı sırası: "
                          f"{days_by_calls}")
                for target_day in days_by_calls:
                    while stable is None and decrements_per_day[target_day] < max_shr:
                        decrements_per_day[target_day] = round(
                            min(decrements_per_day[target_day] + wsf_step, max_shr), 4)
                        active = ', '.join(
                            f"{d}=-{v:.2f}" for d, v in decrements_per_day.items() if v > 0)
                        stage_label = f"STAGE 2 (per-day): {active}"
                        stable, day_specific, info_per_day = _trial(stage_label, default_min)
                        if stable is not None:
                            solution_stage = stage_label
                            if verbose:
                                print(f"\n  ✓ Per-day shrinkage ile çözüldü ({active})")
                            break
                    if stable is not None:
                        break
            else:
                # Uniform: V7 ile aynı davranış
                if verbose:
                    print(f"\n  ▶ STAGE 2 (uniform shrinkage)")
                trial_decs = []
                d_val = wsf_step
                while d_val < max_shr:
                    trial_decs.append(round(d_val, 4))
                    d_val += wsf_step
                trial_decs.append(round(max(d_val, max_shr), 4))

                for dec in trial_decs:
                    for d in day_labels:
                        decrements_per_day[d] = dec
                    stage_label = f"STAGE 2 (uniform): all -{dec:.2f}"
                    stable, day_specific, info_per_day = _trial(stage_label, default_min)
                    if stable is not None:
                        solution_stage = stage_label
                        if verbose:
                            print(f"\n  ✓ Uniform shrinkage -{dec:.2f} ile çözüldü")
                        break

        # ============== AŞAMA 3: min_per_shift PER-DAY azaltma ==============
        # Çağrı sırasıyla — en yoğun gün önce min'ini azalt, floor'a inene kadar.
        # Sonra 2. yoğun gün de eklen, vs. (kümülatif).
        if stable is None and wmpsf_enabled and default_min > wmpsf_floor:
            if verbose:
                print(f"\n  ▶ STAGE 3 (per-day min_per_shift azalt) — çağrı sırası: "
                      f"{days_by_calls}  default={default_min} → floor={wmpsf_floor}")
            for target_day in days_by_calls:
                while stable is None and mins_per_day[target_day] > wmpsf_floor:
                    mins_per_day[target_day] = max(
                        mins_per_day[target_day] - wmpsf_step, wmpsf_floor)
                    non_def = {d: v for d, v in mins_per_day.items()
                                if v != default_min}
                    active = ', '.join(f"{d}={v}" for d, v in non_def.items())
                    stage_label = f"STAGE 3 (per-day): {active}"
                    stable, day_specific, info_per_day = _trial(stage_label, mins_per_day)
                    if stable is not None:
                        solution_stage = stage_label
                        if verbose:
                            print(f"\n  ✓ Per-day min_per_shift ile çözüldü ({active})")
                        break
                if stable is not None:
                    break

        # ============== AŞAMA 4: COVERAGE SHORTFALL (V9) ==============
        # Stage 1-3 hâlâ infeasible bıraktıysa, coverage'ı soft yap:
        # covered + shortfall ≥ erlang_need (shortfall'a yüksek penalty).
        # En agresif state (shrinkage=floor, min_per_shift=floor) ile dener.
        if stable is None and cs_enabled:
            if verbose:
                print(f"\n  ▶ STAGE 4 (coverage shortfall) — "
                      f"kadro yetersiz, eksik kapsamaya izin "
                      f"(penalty={cs_penalty:g})")
            stage_label = "STAGE 4: coverage_shortfall"
            stable, day_specific, info_per_day = _trial(
                stage_label, mins_per_day, enable_shortfall=True)
            if stable is not None:
                solution_stage = stage_label
                total_sf = sum(info.get('total_shortfall', 0)
                                for info in info_per_day.values())
                if verbose:
                    print(f"\n  ✓ Coverage shortfall ile çözüldü — "
                          f"toplam eksik kapsama: {total_sf} kişi-slot")
                    # Gün bazlı eksik raporu
                    print(f"     Gün bazlı eksik:")
                    for d_l, info in info_per_day.items():
                        sf = info.get('total_shortfall', 0)
                        sf_slots = info.get('shortfall_by_slot', {})
                        if sf > 0:
                            slots_str = ', '.join(f"{s}:{v}" for s, v in
                                                   sorted(sf_slots.items()))
                            print(f"       {d_l}: {sf} kişi-slot  ({slots_str})")
                        else:
                            print(f"       {d_l}: tam kapsandı")
                    print(f"     ÖNERİ: kadro arttırılırsa Stage 1-3 ile "
                          f"tam kapsama mümkün olabilir.")

        # ---- Sonuç değerlendirme ----
        if stable is None:
            if verbose:
                print(f"\n  ✗ {queue}: TÜM AŞAMALAR TÜKENDİ — INFEASIBLE")
                _print_trial_log_v8(trial_log, queue, None)
            continue

        # ---- Meta bilgi: her günün info'sune ekle ----
        # min_per_shift_used: tüm günler aynı ise scalar, farklı ise dict
        all_same_min = len(set(mins_per_day.values())) == 1
        used_min_global = (next(iter(mins_per_day.values()))
                            if all_same_min else dict(mins_per_day))

        for d_label in info_per_day:
            info_per_day[d_label]['solution_stage'] = solution_stage
            info_per_day[d_label]['shrinkage_decrement_used'] = decrements_per_day.get(d_label, 0.0)
            info_per_day[d_label]['decrements_per_day_used'] = dict(decrements_per_day)
            info_per_day[d_label]['min_per_shift_used'] = mins_per_day.get(d_label, default_min)
            info_per_day[d_label]['mins_per_day_used'] = dict(mins_per_day)
            info_per_day[d_label]['min_per_shift_default'] = default_min
            info_per_day[d_label]['shrinkage_source'] = (
                'default' if not any(v > 0 for v in decrements_per_day.values())
                else 'fallback')
            info_per_day[d_label]['shrinkage_trial_log'] = trial_log

        # ---- Per-day surplus dağıtımı ----
        if config.get('surplus_distribution', {}).get('enabled', False):
            if verbose:
                print(f"\n  ➤ Per-day surplus dağıtımı başlıyor ({queue})…")
            stable, day_specific, info_per_day = _distribute_surplus_per_day(
                stable, day_specific, info_per_day,
                last_erl_pd, queue, config, verbose=verbose,
            )

        # ---- Final trial log ----
        if verbose:
            _print_trial_log_v8(trial_log, queue, solution_stage)

        # V9: shortfall özet bilgileri
        shortfall_per_day = {d: info_per_day[d].get('total_shortfall', 0)
                              for d in info_per_day}
        total_shortfall_week = sum(shortfall_per_day.values())

        results[queue] = {
            'stable': stable, 'day_specific': day_specific,
            'info_per_day': info_per_day,
            'solution_stage': solution_stage,
            'decrements_per_day_used': dict(decrements_per_day),
            'mins_per_day_used': dict(mins_per_day),
            'min_per_shift_used': used_min_global,
            # Geriye dönük uyumluluk için max decrement:
            'shrinkage_decrement_used': max(decrements_per_day.values())
                                         if decrements_per_day else 0.0,
            'shrinkage_trial_log': trial_log,
            # V9: coverage shortfall özeti
            'shortfall_per_day': shortfall_per_day,
            'total_shortfall_week': total_shortfall_week,
            'coverage_shortfall_used': total_shortfall_week > 0,
        }
        if verbose:
            sample_info = next(iter(info_per_day.values()))
            print_weekly_summary(stable, day_specific,
                                 sample_info['shift_coverage'],
                                 queue, target_dates)

    return results


# =============================================================================
# Haftalık FULL rapor — günlük slot detayı + RR + per-company
# =============================================================================

def _capacity_calc_v7(kap, hour, cagri, re_cfg, kk_cfg, ca_cfg):
    """Tek satırlık kapasite hesabı — gercek_karsilastirma'daki ile aynı."""
    re_oran = re_cfg.get(hour, re_cfg.get('default', 0))
    kk_oran = kk_cfg.get(hour, kk_cfg.get('default', 0))
    ca = ca_cfg.get(hour, ca_cfg.get('default', 15))
    re = round(kap * re_oran)
    kk = round(kap * kk_oran)
    nmt = kap - re - kk
    ck = nmt * (ca / 2)
    rr = ck / cagri if cagri > 0 else 0
    return re, kk, nmt, ck, rr


def print_weekly_full_report(results, df_calls, config,
                             queues=('kitle', 'kurumsal', 'gold')):
    """Haftalık FULL rapor: stable vardiya + günlük breakdown + slot bazlı RR."""
    df_calls_30 = prepare_calls_30(df_calls, config=config)
    df_erlang = calculate_erlang_all(df_calls_30, config=config)

    for queue in queues:
        if queue not in results:
            continue
        r = results[queue]
        info_per_day = r['info_per_day']
        day_labels = list(info_per_day.keys())
        if not day_labels:
            continue

        target_dates = [info_per_day[d]['target_date'] for d in day_labels]
        sample_info = info_per_day[day_labels[0]]
        shift_cov = sample_info['shift_coverage']
        hr_cfg = config['queue_configs'][queue].get('hourly_report', {})
        re_cfg = hr_cfg.get('rapor_etkisi', {})
        kk_cfg = hr_cfg.get('kapasite_kaybi', {})
        ca_cfg = hr_cfg.get('cagri_adedi', {})

        ccfg = config['company']
        inhouse_value = ccfg['inhouse']['shift_value']
        outsource_value = ccfg['outsource']['shift_value']

        line = '=' * 110
        print(f"\n{line}")
        print(f"HAFTALIK FULL RAPOR — {queue.upper()} — "
              f"{target_dates[0]} → {target_dates[-1]}")
        print(line)

        # Çözüm aşaması özeti — shrinkage fallback devreye girmiş mi?
        sol_stage = r.get('solution_stage')
        dec_used = r.get('shrinkage_decrement_used', 0.0)
        trial_log = r.get('shrinkage_trial_log', [])
        if sol_stage:
            print(f"\n🧭 ÇÖZÜM AŞAMASI:")
            if dec_used == 0.0:
                print(f"   Orijinal shrinkage ile çözüldü (decrement=0).")
            else:
                print(f"   Shrinkage -{dec_used:.2f} ile çözüldü "
                      f"(orijinal infeasible, fallback devreye girdi).")
            if trial_log and len(trial_log) > 1:
                print(f"   Adım adım denemeler:")
                print(f"     {'#':>2}  {'Kademe':<32} {'Erlang':>8}  {'Sonuç':<11}")
                for t in trial_log:
                    mark = ' ←' if t['decrement'] == dec_used else '  '
                    print(f"     {t['idx']:>2}  {t['stage']:<32} "
                          f"{t['erlang_total']:>8}  {t['status']:<11}{mark}")

        # -----------------------------------------------------------
        # 1) Stable INHOUSE vardiya tablosu
        # -----------------------------------------------------------
        print(f"\n📋 STABLE INHOUSE VARDIYALAR (Pzt-Cum aynı kişi):")
        if not r['stable'] or all(v == 0 for v in r['stable'].values()):
            print("  (stable inhouse yok)")
        else:
            print(f"  {'Vardiya':<32} {'Saat':<14} {'Kişi':>6}")
            print(f"  {'-'*60}")
            active = [(s, v) for s, v in r['stable'].items() if v > 0]
            t_in_stable = 0
            for s, v in sorted(active, key=lambda x: shift_cov[x[0]]['start']):
                sc = shift_cov[s]
                saat = f"{sc['start']}-{sc['end']}"
                print(f"  {s:<32} {saat:<14} {v:>6}")
                t_in_stable += v
            print(f"  {'-'*60}")
            print(f"  {'TOPLAM':<48} {t_in_stable:>6}")

        # 2) Günlük outsource + gün-özel inhouse
        has_ext = any(d for d in r['day_specific'].values())
        if has_ext:
            print(f"\n📋 GÜNLÜK DEĞİŞKEN (outsource her gün + gün-özel inhouse):")
            for dl, asg in r['day_specific'].items():
                if not asg:
                    continue
                # company bazlı toplam
                in_v = sum(v for s, v in asg.items()
                           if shift_cov[s]['company'] == inhouse_value)
                out_v = sum(v for s, v in asg.items()
                            if shift_cov[s]['company'] == outsource_value)
                print(f"  --- {dl} (in={in_v}, out={out_v}, total={in_v+out_v}) ---")
                for s, v in sorted(asg.items(), key=lambda x: shift_cov[x[0]]['start']):
                    sc = shift_cov[s]
                    saat = f"{sc['start']}-{sc['end']}"
                    print(f"    {s:<32} {saat:<14} {sc['company']:<10} {v:>6}")

        # -----------------------------------------------------------
        # 2) Günlük özet (toplam çağrı, kapasite, RR%)
        # -----------------------------------------------------------
        print(f"\n📊 GÜNLÜK ÖZET METRİKLER:")
        print(f"  {'Gün':<5} {'Tarih':<12} {'Çağrı':>7} {'Erlang':>7} "
              f"{'MIP':>5} {'In':>4} {'Out':>4} "
              f"{'NMT':>5} {'Ç.Kap':>7} {'RR%':>6}")
        print(f"  {'-'*80}")
        tot_cagri = tot_erl = tot_kap = tot_in = tot_out = tot_nmt = tot_ck = 0
        for d_label, info in info_per_day.items():
            target_date = info['target_date']
            d = pd.to_datetime(target_date)
            # Fallback ile değişen Erlang varsa onu kullan; yoksa orijinali hesapla
            erlang_by_slot = info.get('erlang_by_slot')
            if not erlang_by_slot:
                df_q = df_erlang[(df_erlang['date'] == d) & (df_erlang['queue'] == queue)]
                erlang_by_slot = dict(zip(df_q['slot'], df_q['erlang_need']))
            df_calls_day = df_calls_30[df_calls_30['data_date'] == d]
            calls_col = f"{queue}_total"
            calls_by_slot = (dict(zip(df_calls_day['slot_30'], df_calls_day[calls_col]))
                             if calls_col in df_calls_day.columns else {})

            day_cagri = day_erl = day_kap = day_in = day_out = day_nmt = day_ck = 0
            for slot in SLOTS_30:
                cagri = int(calls_by_slot.get(slot, 0))
                erl = erlang_by_slot.get(slot, 0)
                kap = info['mip_by_slot'].get(slot, 0)
                if cagri == 0 and kap == 0:
                    continue
                h = int(slot[:2])
                _, _, nmt, ck, _ = _capacity_calc_v7(kap, h, cagri, re_cfg, kk_cfg, ca_cfg)
                day_cagri += cagri; day_erl += erl
                day_kap += kap
                day_in += info['mip_in_by_slot'].get(slot, 0)
                day_out += info['mip_out_by_slot'].get(slot, 0)
                day_nmt += nmt; day_ck += ck

            day_rr = day_ck / day_cagri if day_cagri > 0 else 0
            print(f"  {d_label:<5} {target_date:<12} {day_cagri:>7} {day_erl:>7} "
                  f"{day_kap:>5} {day_in:>4} {day_out:>4} "
                  f"{day_nmt:>5} {day_ck:>7.0f} {day_rr:>5.0%}")
            tot_cagri += day_cagri; tot_erl += day_erl
            tot_kap += day_kap; tot_in += day_in; tot_out += day_out
            tot_nmt += day_nmt; tot_ck += day_ck

        tot_rr = tot_ck / tot_cagri if tot_cagri > 0 else 0
        print(f"  {'-'*80}")
        print(f"  {'TOPLAM':<18} {tot_cagri:>7} {tot_erl:>7} "
              f"{tot_kap:>5} {tot_in:>4} {tot_out:>4} "
              f"{tot_nmt:>5} {tot_ck:>7.0f} {tot_rr:>5.0%}")

        # -----------------------------------------------------------
        # 3) Slot bazlı detay — her gün için ayrı tablo
        # -----------------------------------------------------------
        for d_label, info in info_per_day.items():
            target_date = info['target_date']
            d = pd.to_datetime(target_date)
            # Fallback ile değişen Erlang varsa onu kullan; yoksa orijinali hesapla
            erlang_by_slot = info.get('erlang_by_slot')
            if not erlang_by_slot:
                df_q = df_erlang[(df_erlang['date'] == d) & (df_erlang['queue'] == queue)]
                erlang_by_slot = dict(zip(df_q['slot'], df_q['erlang_need']))
            df_calls_day = df_calls_30[df_calls_30['data_date'] == d]
            calls_col = f"{queue}_total"
            calls_by_slot = (dict(zip(df_calls_day['slot_30'], df_calls_day[calls_col]))
                             if calls_col in df_calls_day.columns else {})

            print(f"\n📋 SLOT DETAY — {d_label} ({target_date}):")
            print(f"  {'Slot':<6} {'Çağrı':>6} {'Erl':>5} | "
                  f"{'Kap':>4} {'In':>4} {'Out':>4} | "
                  f"{'R.Et':>5} {'K.Ka':>5} {'NMT':>5} {'Ç.Kap':>7} {'RR%':>6}")
            print(f"  {'-'*92}")
            t_cag = t_e = t_kp = t_in = t_out = t_re = t_kk = t_nmt = t_ck = 0
            for slot in SLOTS_30:
                cagri = int(calls_by_slot.get(slot, 0))
                erl = erlang_by_slot.get(slot, 0)
                kap = info['mip_by_slot'].get(slot, 0)
                if cagri == 0 and kap == 0:
                    continue
                in_v = info['mip_in_by_slot'].get(slot, 0)
                out_v = info['mip_out_by_slot'].get(slot, 0)
                h = int(slot[:2])
                re_v, kk_v, nmt, ck, rr = _capacity_calc_v7(
                    kap, h, cagri, re_cfg, kk_cfg, ca_cfg)
                warn = " ⚠" if rr < 1.0 and cagri > 0 else ""
                print(f"  {slot:<6} {cagri:>6} {erl:>5} | "
                      f"{kap:>4} {in_v:>4} {out_v:>4} | "
                      f"{re_v:>5} {kk_v:>5} {nmt:>5} {ck:>7.0f} {rr:>5.0%}{warn}")
                t_cag += cagri; t_e += erl; t_kp += kap
                t_in += in_v; t_out += out_v
                t_re += re_v; t_kk += kk_v; t_nmt += nmt; t_ck += ck

            t_rr = t_ck / t_cag if t_cag > 0 else 0
            print(f"  {'-'*92}")
            print(f"  {'TOP':<6} {t_cag:>6} {t_e:>5} | "
                  f"{t_kp:>4} {t_in:>4} {t_out:>4} | "
                  f"{t_re:>5} {t_kk:>5} {t_nmt:>5} {t_ck:>7.0f} {t_rr:>5.0%}")

            # RR penalty / Slot cap penalty özeti (varsa)
            rr_ex = info.get('rr_excess_by_slot', {})
            sc_ex = info.get('sc_excess_by_slot', {})
            if rr_ex or sc_ex:
                print(f"\n  Penalty özeti:  "
                      f"RR_excess slotları={len(rr_ex)}, "
                      f"toplam fazla kişi-slot={info.get('rr_total_excess', 0)}, "
                      f"toplam RR cezası={info.get('rr_total_penalty_cost', 0):.0f}  |  "
                      f"SC_excess slotları={len(sc_ex)}, "
                      f"toplam SC cezası={info.get('sc_total_penalty_cost', 0):.0f}")


# =============================================================================
# v6 mantığında günlük detay raporu — her gün için MIP(1)/MIP(2) yan yana
# =============================================================================

def print_weekly_daily_detail(queue, results, df_calls, df_actual=None,
                              config=CONFIG):
    """Verilen queue(lar) için haftanın HER GÜNÜNE ayrı v6-tarzı detay raporu basar.

    `queue` tek bir string veya liste/tuple olabilir. Liste verilirse her queue
    için sırasıyla rapor üretilir.

    Her gün için v6 print_queue_report çağrılır:
      - mip_info_stage1 = surplus öncesi snapshot (MIP1)
      - mip_info        = surplus sonrası (MIP2)
      - Erlang: info['erlang_by_slot'] (fallback ile değişen değer)
      - df_actual varsa gerçek karşılaştırma sütunu da gelir
    """
    queues = [queue] if isinstance(queue, str) else list(queue)

    df_calls_30 = prepare_calls_30(df_calls, config=config)
    df_erlang = calculate_erlang_all(df_calls_30, config=config)

    for q in queues:
        if q not in results:
            print(f"⚠ {q} için sonuç yok.")
            continue
        r = results[q]
        info_per_day = r.get('info_per_day', {})
        if not info_per_day:
            print(f"⚠ {q} için info_per_day boş.")
            continue

        for d_label, info in info_per_day.items():
            target_date = info['target_date']
            d = pd.to_datetime(target_date)

            # Erlang: MIP'in fiilen çözüldüğü değer (shrinkage fallback sonrası).
            erlang_by_slot = info.get('erlang_by_slot')
            if not erlang_by_slot:
                df_qd = df_erlang[(df_erlang['date'] == d) & (df_erlang['queue'] == q)]
                erlang_by_slot = dict(zip(df_qd['slot'], df_qd['erlang_need']))

            # weighted_aht shrinkage'tan bağımsız — orijinal config yeterli
            df_qd = df_erlang[(df_erlang['date'] == d) & (df_erlang['queue'] == q)]
            weighted_aht_by_slot = dict(zip(df_qd['slot'], df_qd['weighted_aht']))

            df_calls_day = df_calls_30[df_calls_30['data_date'] == d]
            calls_col = f"{q}_total"
            calls_by_slot = (dict(zip(df_calls_day['slot_30'], df_calls_day[calls_col]))
                             if calls_col in df_calls_day.columns else {})
            total_calls_day = int(sum(calls_by_slot.values())) if calls_by_slot else 0

            actual = None
            if df_actual is not None:
                try:
                    actual = get_actual_summary(df_actual, target_date, q, config)
                except Exception as ex:
                    print(f"  ℹ {d_label}: actual hesaplanamadı ({ex})")
            if actual is None:
                actual = {
                    'slot_total': {s: 0 for s in SLOTS_30},
                    'slot_in': {s: 0 for s in SLOTS_30},
                    'slot_out': {s: 0 for s in SLOTS_30},
                    'kisi_total': 0, 'kisi_in': 0, 'kisi_out': 0,
                    'outsource_ratio': 0,
                }

            print(f"\n{'#'*95}")
            print(f"# GÜNLÜK DETAY — {q.upper()} — {d_label} ({target_date})")
            print(f"{'#'*95}")

            print_queue_report(
                target_date, q, erlang_by_slot, info, actual,
                weighted_aht_by_slot=weighted_aht_by_slot,
                total_calls_day=total_calls_day,
                calls_by_slot=calls_by_slot,
                mip_info_stage1=info.get('mip_info_stage1'),
                config=config,
            )
