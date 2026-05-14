# =============================================================================
# HAFTALIK MIP — ACTUAL V7 (WEEKLY, HAFTAİÇİ)
# =============================================================================
#
# V7 amacı: Bir agent'ın Pzt-Cum aynı vardiyada olmasını GARANTİLEMEK.
#
# V6 günlük MIP'i her günü bağımsız çözüyordu → günler arası vardiya
# atamaları kayıyordu. V7 ise **tek bir MIP'i 5 gün için** çözer:
#
#   - x[shift]            → stabil vardiyalar (Pzt-Cum boyunca aynı kişi sayısı)
#   - x_day[shift, day]   → güne-özel vardiyalar (örn. Cuma-özel 14-23 inhouse)
#   - Coverage kısıtları her gün × her slot için ayrı uygulanır
#   - min_per_shift, RR penalty, slot_cap her gün için ayrı hesaplanır
#
# Gün-özel vardiya tanımı:
#   df_shifts'e opsiyonel 'available_days' kolonu eklenir.
#   Değer: ['Mon','Tue','Wed','Thu','Fri'] (default), veya alt küme.
#   Örnek: {'shift': '14:00-23:00_inhouse_fri', ..., 'available_days': ['Fri']}
#
# v6'dan yeniden kullanılan tüm yardımcılar (load_aht, prepare_calls_30,
# calculate_erlang_all, is_slot_in_shift, create_shift_coverage, vs.) buraya
# import edilerek geri-uyumluluk korunur.
#
# Config: config_v6_weekday.py kullanılabilir; queue_configs altında ek
# 'weekly_mip' bloğu yoksa default davranış geçerli.
# =============================================================================

import pandas as pd
import math
from pulp import (
    LpProblem, LpMinimize, LpVariable, lpSum, value,
    PULP_CBC_CMD, LpStatus,
)

from actual_pipeline_v6_weekday import (
    SLOTS_30,
    is_slot_in_shift,
    add_30min,
    prepare_calls_30,
    calculate_erlang_all,
    create_shift_coverage,
    load_aht_from_df,
    _classify_shift,
    get_time_cost_multiplier,
)

DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']


# =============================================================================
# Yardımcılar
# =============================================================================

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


# =============================================================================
# Haftalık MIP
# =============================================================================

def optimize_week(erlang_by_slot_per_day, df_shifts, queue, target_dates, config,
                  inhouse_min_per_day=None, outsource_min_per_day=None,
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

    only_inhouse = (allowed == ['inhouse'])
    inhouse_value = ccfg['inhouse']['shift_value']
    outsource_value = ccfg['outsource']['shift_value']

    shift_cov = create_shift_coverage(df_sf, config)
    # available_days bilgisini shift_cov'a ekle
    shift_days = _classify_shifts_by_days(df_sf)
    for k, sc in shift_cov.items():
        sc['available_days'] = shift_days.get(k, set(DAY_LABELS))

    shifts = list(shift_cov.keys())

    # Stable vs day-specific ayrımı:
    # Bir shift TÜM target günlerde aktifse stabil, değilse gün-özel.
    target_day_labels = [_date_to_day_label(d) for d in target_dates]
    stable_shifts = [s for s in shifts
                     if all(d in shift_cov[s]['available_days'] for d in target_day_labels)]
    day_specific_shifts = [s for s in shifts if s not in stable_shifts]

    in_shifts_stable = [s for s in stable_shifts if shift_cov[s]['company'] == inhouse_value]
    out_shifts_stable = [s for s in stable_shifts if shift_cov[s]['company'] == outsource_value]

    if verbose:
        print(f"  [optimize_week] queue={queue}, stable={len(stable_shifts)}, "
              f"day_specific={len(day_specific_shifts)}")

    # =========================================================================
    # Değişkenler
    # =========================================================================
    prob = LpProblem(f"Q_{queue}_weekly", LpMinimize)

    # Stabil: bir değişken, Pzt-Cum aynı
    x = LpVariable.dicts("x", stable_shifts, lowBound=0, cat='Integer')
    y = LpVariable.dicts("y", stable_shifts, cat='Binary')

    # Gün-özel: (shift, day) çiftleri için ayrı değişken
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

    # =========================================================================
    # Cost (shift bazlı)
    #   - Stabil: x[s] × base_cost (5 gün boyu kullanılacak ama
    #     tek-faturalandı, çünkü aynı agent paylaşılıyor)
    #   - Gün-özel: x_day[s,d] × base_cost
    # =========================================================================
    cost_details = []
    pt_shift_keys = []  # part-time bu sürümde yok, placeholder

    for s in stable_shifts:
        company_type, base_cost, multiplier, start_hour = _classify_shift(
            s, shift_cov, queue, pt_shift_keys, inhouse_value, mcfg, config)
        final_cost = base_cost * multiplier
        cost.append(x[s] * final_cost)
        if multiplier != 1.0:
            cost_details.append({
                'shift': s, 'company': company_type, 'start': start_hour,
                'base_cost': base_cost, 'multiplier': multiplier,
                'final_cost': final_cost, 'kind': 'stable',
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

    # =========================================================================
    # Coverage kısıtı (her gün × her slot)
    # + RR penalty + Slot cap (günlük)
    # =========================================================================
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

    excess_per_day = {}      # {(day, slot): excess_var}
    sc_excess_per_day = {}   # {(day, slot): (excess_var, penalty)}
    peak_slots_per_day = {}  # {day: set(slot)}
    sc_detail_per_day = {}   # {day: [{slot, cap, ...}]}

    for day_label in target_day_labels:
        erlang_by_slot = erlang_by_slot_per_day.get(day_label, {})
        active_slots = [s for s in SLOTS_30 if erlang_by_slot.get(s, 0) > 0]

        # Peak slotları
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

            # Bu slotu kapsayan stabil vardiyalar
            covering_stable = [s for s in stable_shifts
                               if slot in shift_cov[s]['slots']]
            # Bu slotu kapsayan gün-özel vardiyalar (bu güne ait)
            covering_day = [(s, day_label) for (s, d) in day_shift_pairs
                            if d == day_label and slot in shift_cov[s]['slots']]

            if not (covering_stable or covering_day):
                continue   # bu slotta hiç kaynak yok

            total_cov_expr = (
                lpSum([x[s] for s in covering_stable]) +
                lpSum([x_day[pair] for pair in covering_day])
            )
            # Coverage zorunluluğu
            prob += total_cov_expr >= erlang_need

            # RR penalty (gün × slot)
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

            # Slot cap (gün × slot)
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

        # Inhouse / Outsource min_by_slot (opsiyonel) — günlük
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

    # =========================================================================
    # min_per_shift kısıtı
    # Açılan her vardiyada (stable veya day-specific) en az N kişi.
    # override yoksa default mcfg['min_per_shift'].
    # =========================================================================
    M = 500
    min_default = mcfg['min_per_shift']
    min_overrides = mcfg.get('min_per_shift_overrides', {})

    for s in stable_shifts:
        prob += x[s] <= M * y[s]
        start_hour = shift_cov[s]['start']
        min_v = min_overrides.get(start_hour, min_default)
        prob += x[s] >= min_v * y[s]

    for (s, d) in day_shift_pairs:
        prob += x_day[(s, d)] <= M * y_day[(s, d)]
        start_hour = shift_cov[s]['start']
        min_v = min_overrides.get(start_hour, min_default)
        prob += x_day[(s, d)] >= min_v * y_day[(s, d)]

    # =========================================================================
    # Kadro tavanı (haftalık staffing için)
    # =========================================================================
    kadro_cfg = config.get('surplus_distribution', {}).get('total_kadro', {}).get(queue, {})
    kadro_in = kadro_cfg.get('inhouse', 0)
    kadro_out = kadro_cfg.get('outsource', 0)
    if kadro_in > 0 and in_shifts_stable:
        # Stabil inhouse + günde maks gün-özel inhouse
        prob += lpSum([x[s] for s in in_shifts_stable]) <= kadro_in
    if kadro_out > 0 and out_shifts_stable:
        prob += lpSum([x[s] for s in out_shifts_stable]) <= kadro_out

    # =========================================================================
    # Amaç fonksiyonu
    # =========================================================================
    prob += lpSum(cost)

    # =========================================================================
    # Çöz
    # =========================================================================
    solver = PULP_CBC_CMD(msg=0)
    prob.solve(solver)
    status = LpStatus[prob.status]
    if verbose:
        print(f"  [optimize_week] solver status: {status}")

    if status != 'Optimal':
        return None, None, None

    # =========================================================================
    # Sonuçları topla
    # =========================================================================
    stable_assignments = {s: int(round(value(x[s]) or 0)) for s in stable_shifts}

    day_specific_assignments = {d: {} for d in target_day_labels}
    for (s, d), var in x_day.items():
        v = int(round(value(var) or 0))
        if v > 0:
            day_specific_assignments[d][s] = v

    # Her gün için v6-uyumlu mip_info dict'i hazırla
    info_per_day = {}
    for day_label, target_date in zip(target_day_labels, target_dates):
        erlang_by_slot = erlang_by_slot_per_day.get(day_label, {})
        # day-level assignments = stable + day_specific
        assigns_this_day = dict(stable_assignments)
        for s, v in day_specific_assignments[day_label].items():
            assigns_this_day[s] = assigns_this_day.get(s, 0) + v

        # mip_by_slot, mip_in_by_slot, mip_out_by_slot
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

        # rr_excess_by_slot, sc_excess_by_slot
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

        info = {
            'assignments': assigns_this_day,
            'shift_coverage': shift_cov,
            'mip_by_slot': mip_by_slot,
            'mip_in_by_slot': mip_in_by_slot,
            'mip_out_by_slot': mip_out_by_slot,
            'total_kisi': sum(assigns_this_day.values()),
            'total_inhouse_kisi': sum(v for s, v in assigns_this_day.items()
                                       if shift_cov[s]['company'] == inhouse_value),
            'total_outsource_kisi': sum(v for s, v in assigns_this_day.items()
                                        if shift_cov[s]['company'] == outsource_value),
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
            'target_date': target_date,
            'day_label': day_label,
            # haftalık-özel bilgi:
            'weekly_stable_assignments': stable_assignments,
            'weekly_day_specific': day_specific_assignments[day_label],
        }
        info_per_day[day_label] = info

    return stable_assignments, day_specific_assignments, info_per_day


# =============================================================================
# Haftalık özet
# =============================================================================

def print_weekly_summary(stable_assignments, day_specific_assignments,
                         shift_cov, queue, target_dates):
    """Haftanın stable vardiya listesi + günlere göre eklenen day-specific."""
    print(f"\n{'='*90}")
    print(f"HAFTALIK STABLE VARDIYA — {queue.upper()}")
    print(f"  Tarih aralığı: {target_dates[0]} → {target_dates[-1]}")
    print(f"{'='*90}")
    if not stable_assignments:
        print("  (Stable vardiya yok)")
    else:
        print(f"  {'Vardiya':<32} {'Saat':<14} {'Şirket':<10} {'Kişi':>6}")
        print(f"  {'-'*70}")
        active = [(s, v) for s, v in stable_assignments.items() if v > 0]
        for s, v in sorted(active, key=lambda x: shift_cov[x[0]]['start']):
            sc = shift_cov[s]
            saat = f"{sc['start']}-{sc['end']}"
            print(f"  {s:<32} {saat:<14} {sc['company']:<10} {v:>6}")
        print(f"  {'-'*70}")
        print(f"  {'TOPLAM (Pzt-Cum aynı kişi)':<58} {sum(v for _, v in active):>6}")

    has_extra = any(d for d in day_specific_assignments.values())
    if has_extra:
        print(f"\n  GÜN-ÖZEL EKLER (haftaya stabil değil):")
        for d_label, day_assigns in day_specific_assignments.items():
            if not day_assigns:
                continue
            print(f"  --- {d_label} ---")
            for s, v in sorted(day_assigns.items(), key=lambda x: shift_cov[x[0]]['start']):
                sc = shift_cov[s]
                saat = f"{sc['start']}-{sc['end']}"
                print(f"    {s:<30} {saat:<14} {sc['company']:<10} {v:>6}")


# =============================================================================
# Orchestrator
# =============================================================================

def run_week_all_queues(df_calls, df_shifts_by_queue, target_dates, config,
                        queues=('kitle', 'kurumsal', 'gold'), verbose=True):
    """5 günlük df_calls'tan erlang hesapla, her queue için optimize_week çağır.

    Args:
        df_calls: tüm hafta çağrı verisi
        df_shifts_by_queue: {queue: df_shifts} (available_days kolonlu)
        target_dates: 5 günün tarih listesi (Pzt..Cum), str format
        config: v6 config
        queues: hangi kuyrukları çöz

    Returns:
        {queue: {'stable': dict, 'day_specific': dict, 'info_per_day': dict}}
    """
    df_calls_30 = prepare_calls_30(df_calls, config=config)
    df_erlang = calculate_erlang_all(df_calls_30, config=config)

    results = {}
    for queue in queues:
        if verbose:
            print(f"\n{'#'*80}\n# {queue.upper()} HAFTALIK MIP\n{'#'*80}")
        # Her gün için erlang_by_slot
        erlang_by_slot_per_day = {}
        for date_str in target_dates:
            d = pd.to_datetime(date_str)
            day_label = _date_to_day_label(date_str)
            df_q = df_erlang[(df_erlang['date'] == d) & (df_erlang['queue'] == queue)]
            erlang_by_slot_per_day[day_label] = dict(zip(df_q['slot'], df_q['erlang_need']))

        df_shifts = df_shifts_by_queue.get(queue)
        if df_shifts is None or df_shifts.empty:
            if verbose:
                print(f"  {queue}: vardiya yok, atlandı.")
            continue

        stable, day_specific, info_per_day = optimize_week(
            erlang_by_slot_per_day, df_shifts, queue, target_dates,
            config, verbose=verbose,
        )
        if stable is None:
            if verbose:
                print(f"  ✗ {queue}: MIP infeasible")
            continue

        results[queue] = {
            'stable': stable, 'day_specific': day_specific,
            'info_per_day': info_per_day,
        }
        if verbose:
            # haftalık özet
            sample_info = next(iter(info_per_day.values()))
            print_weekly_summary(stable, day_specific,
                                 sample_info['shift_coverage'],
                                 queue, target_dates)

    return results
