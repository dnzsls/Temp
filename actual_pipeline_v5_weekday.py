# =============================================================================
# WEEKLY WEEKDAY PIPELINE — FORECAST (V9, Stage 4 dahil)
# =============================================================================
# Bu dosya forecast verisi üzerinden çalışan SADE haftaiçi MIP pipeline'ı.
# actual_pipeline_v9_weekly.py'den V9 weekday için gereken fonksiyonlar
# ayıklanıp tek dosyada toplandı; v6 daily, weekend, df_actual karşılaştırma,
# print_queue_report (Gerçek kolonlu rapor) gibi forecast'ta gerek olmayan
# parçalar dahil EDİLMEDİ.
#
# Veri akışı:
#   df_forecast (15dk geniş format — KITLE_NOF_CALL vb.)
#     ↓ prepare_forecast_calls_30()
#   df_calls_30 (30dk internal format — data_date, slot_30, {queue}_total)
#     ↓ calculate_erlang_all() + _build_erlang_per_day*
#   erlang_by_slot_per_day  (gün × slot → ihtiyaç)
#     ↓ optimize_week() — V9 MIP
#   stable_assignments + day_specific_assignments + info_per_day
#     ↓ run_week_all_queues() — 4 aşamalı cascading fallback
#   results  (kuyruk başına)
#
# V9 FALLBACK:
#   Stage 1: Orijinal
#   Stage 2: Per-day shrinkage azaltma
#   Stage 3: Per-day min_per_shift (varsayılan KAPALI — sert kısıt)
#   Stage 4: Coverage shortfall (yumuşak coverage + yüksek penalty)
#
# CONFIG'de olması gerekenler:
#   'forecast_cols': {'datetime', 'date', 'kitle_total', 'kurumsal_total',
#                      'gold_total', vs.}
#   'queues': {...}, 'company': {...}, 'shift_columns': {...}
#   'queue_configs'[queue]['mip']: {min_per_shift, weekly_shrinkage_fallback,
#                                    coverage_shortfall, ...}
#   'surplus_distribution': {'enabled', 'total_kadro' (int veya per-day dict)}
#
# Kullanım:
#   from weekly_weekday_pipeline_forecast import (
#       load_aht_from_df,
#       prepare_forecast_calls_30,
#       run_week_all_queues,
#   )
#   results = run_week_all_queues(
#       df_forecast=df_forecast,
#       df_shifts_by_queue=df_shifts_dict,
#       target_dates=['2026-02-09', ..., '2026-02-13'],
#       config=CONFIG_WEEKDAY,
#   )
# =============================================================================

import math
import copy
import pandas as pd
from pulp import LpProblem, LpMinimize, LpVariable, LpStatus, lpSum, value, PULP_CBC_CMD

CONFIG = None  # Dışarıdan verilir (config dict)


# =============================================================================
# SABİTLER
# =============================================================================

SLOTS_30 = [f"{h:02d}:{m}" for h in range(24) for m in ['00', '30']]
DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']


# =============================================================================
# 0. AHT YÜKLEME
# =============================================================================

def load_aht_from_df(df_aht, config=CONFIG):
    """AHT verisini config['sub_queues']'a uygun yapıya çevirir.

    df_aht kolonları: 'saat', 'sub_queue', 'line_based_main_group', 'weighted_avg_aht'
    Returns: {queue_key: {'queues': [...], 'aht': {sq: {hour: aht}}}}
    """
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
            aht_dict = dict(zip(df_sq['saat'].astype(int),
                                 df_sq['weighted_avg_aht'].astype(int)))
            aht_dict['default'] = int(df_sq['weighted_avg_aht'].mean())
            sub_queues_cfg[queue_key]['aht'][sq] = aht_dict
        print(f"   ✓ {queue_key}: {len(sub_queues_cfg[queue_key]['queues'])} alt kuyruk yüklendi "
              f"({', '.join(sub_queues_cfg[queue_key]['queues'])})")

    return sub_queues_cfg


# =============================================================================
# YARDIMCI — SLOT / SHIFT
# =============================================================================

def is_slot_in_shift(slot, start, end):
    """slot vardiyanın (start, end) aralığına düşüyor mu? Wrap-around destekli."""
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


def _shift_available_on_day(shift_row_or_dict, day_label):
    """'available_days' alanı varsa kontrol et, yoksa her gün aktif kabul et."""
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
    """Her shift için hangi günlerde aktif. {shift_key: set(day_labels_active)}"""
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


def _week_of_month(date_str):
    """V9 — Tarihin ayın kaçıncı haftasında olduğunu döner (1-tabanlı).

    Hafta tanımı: AY SINIRINA SAYGILI, Pzt başlangıçlı.
    Ayın 1'i hangi gün-of-week'e denk gelirse hafta_1 oradan başlar.
    Bir sonraki Pzt → hafta_2, sonraki → hafta_3, vs.

    Önemli: Ay sınırını GEÇMEZ. Aynı Pzt-Pzr blok'unda iki farklı ay varsa,
    her gün kendi ayının hafta numarasında değerlendirilir:

      Örnekler:
        2026-04-01 (Çar): Nisan hafta_1   (Nisan'ın 1'i Çar)
        2026-04-30 (Per): Nisan hafta_5   (1'i Çar → 30. gün 5. haftada)
        2026-05-01 (Cum): Mayıs hafta_1   (Mayıs'ın 1'i Cum)
        2026-05-04 (Pzt): Mayıs hafta_2
        2026-05-11 (Pzt): Mayıs hafta_3

    Formül:
        first_weekday = ayın 1'inin weekday()'i (0=Pzt, ..., 6=Pzr)
        week_num = ((day_of_month + first_weekday - 1) // 7) + 1
    """
    d = pd.to_datetime(date_str)
    first_day = d.replace(day=1)
    first_weekday = first_day.weekday()
    return ((d.day + first_weekday - 1) // 7) + 1


def create_shift_coverage(df_shifts, config=CONFIG):
    """Vardiya → kapsadığı 30dk slot listesi map'i."""
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


# =============================================================================
# AHT — alt-kuyruk bazlı
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
    """Bir slot için weighted AHT: alt-kuyruk çağrı dağılımına göre."""
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
    if sub_queues:
        ahts = [get_sub_queue_aht(queue, sq, slot, config) for sq in sub_queues]
        return round(sum(ahts) / len(ahts), 1)
    return config.get('default_aht', 150)


# =============================================================================
# FORECAST FORMAT → INTERNAL 30DK FORMAT
# =============================================================================

def prepare_forecast_calls_30(df_forecast, config=CONFIG):
    """Forecast geniş formatını (15dk, KITLE_NOF_CALL vs.) 30dk internal format'a
    çevirir: data_date, slot_30, {queue}_total, {sub_queue}_calls.

    config['forecast_cols'] kolonu beklenir:
        'datetime': tam timestamp kolon adı (örn. 'forecast_datetime')
        'date': tarih kolon adı (örn. 'forecast_date')
        'kitle_total':    'KITLE_NOF_CALL'  (default)
        'kurumsal_total': 'KURUMSAL_NOF_CALL'
        'gold_total':     'GOLD_NOF_CALL'

    Alt-kuyruk kolonları config['sub_queues']'tan otomatik tespit edilir:
    {sq}_NOF_CALL, {sq}_nof_call veya {sq}.
    """
    fcols = config['forecast_cols']
    df = df_forecast.copy()
    df[fcols['datetime']] = df[fcols['datetime']].astype(str).str.strip()

    def extract_time(val):
        val = str(val).strip()
        return val.split(' ', 1)[1].strip()[:5] if ' ' in val else '00:00'

    df['_time_str'] = df[fcols['datetime']].apply(extract_time)
    hour = df['_time_str'].str.split(':').str[0].astype(int)
    minute = df['_time_str'].str.split(':').str[1].astype(int)
    df['slot_30'] = (hour.astype(str).str.zfill(2) + ':' +
                     ((minute // 30) * 30).astype(str).str.zfill(2))
    df['data_date'] = pd.to_datetime(df[fcols['date']], dayfirst=True)

    queue_total_map = {
        'kitle':    fcols.get('kitle_total', 'KITLE_NOF_CALL'),
        'kurumsal': fcols.get('kurumsal_total', 'KURUMSAL_NOF_CALL'),
        'gold':     fcols.get('gold_total', 'GOLD_NOF_CALL'),
    }
    agg_cols = {}
    for qk, cn in queue_total_map.items():
        if cn in df.columns:
            agg_cols[cn] = 'sum'

    sub_queues_cfg = config.get('sub_queues', {})
    for qk, sq_cfg in sub_queues_cfg.items():
        for sq in sq_cfg.get('queues', []):
            for cand in [f"{sq}_NOF_CALL", f"{sq}_nof_call", sq]:
                if cand in df.columns:
                    agg_cols[cand] = 'sum'
                    break

    df_30 = df.groupby(['data_date', 'slot_30']).agg(agg_cols).reset_index()

    for qk, cn in queue_total_map.items():
        if cn in df_30.columns:
            df_30 = df_30.rename(columns={cn: f"{qk}_total"})

    for qk, sq_cfg in sub_queues_cfg.items():
        for sq in sq_cfg.get('queues', []):
            for cand in [f"{sq}_NOF_CALL", f"{sq}_nof_call", sq]:
                if cand in df_30.columns:
                    df_30 = df_30.rename(columns={cand: f"{sq}_calls"})
                    break

    return df_30.sort_values(['data_date', 'slot_30']).reset_index(drop=True)


# =============================================================================
# ERLANG-C
# =============================================================================

def erlang_c(agents, traffic):
    """Erlang-C formülü — kuyruğa düşme olasılığı."""
    if agents <= traffic or agents == 0:
        return 1.0
    eb = traffic / agents
    for i in range(2, int(agents) + 1):
        eb = (traffic * eb) / (i + traffic * eb)
    return min(eb / (1 - (traffic / agents) * (1 - eb)), 1.0)


def calc_asa(agents, traffic, aht):
    """ASA (Average Speed of Answer) saniye cinsinden."""
    if agents <= traffic or agents == 0:
        return 999
    ec = erlang_c(agents, traffic)
    return (ec * (aht / 60)) / (agents - traffic) * 60


def find_optimal_agents(calls, aht, slot, queue, config=CONFIG):
    """Bir slot için minimum agent sayısı (shrinkage uygulanmış)."""
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
    """Her (tarih × slot × kuyruk) için Erlang ihtiyacı hesapla."""
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
# KADRO RESOLVER (V9 — per-day destekli)
# =============================================================================

def _resolve_kadro(kadro_value, date_str=None, day_label=None):
    """V9 — Kadro tavanını 4 katmanlı çözer:
        tarih > hafta_N > gün-of-week > default

    kadro_value: int (tüm günlerde aynı) VEYA dict.
        Dict ise key'ler:
          - 'YYYY-MM-DD'   → o gün için (en spesifik)
          - 'hafta_1', 'hafta_2', ...  → o ayın N. haftası (ay-içi sıralı,
              ay sınırı geçmez, Pzt başlangıçlı, _week_of_month formülü ile)
          - 'Mon'..'Sun'   → her hafta o gün
          - 'default'      → diğer hepsi

    Örnekler:
        _resolve_kadro(380, ...)  → 380

        # Hafta bazlı:
        d = {'hafta_1': 400, 'hafta_2': 410, 'default': 380}
        _resolve_kadro(d, date_str='2026-02-02')  → 400  (Şubat'ın 1. haftası)
        _resolve_kadro(d, date_str='2026-02-09')  → 410  (Şubat'ın 2. haftası)
        _resolve_kadro(d, date_str='2026-02-23')  → 380  (4. hafta, dict'te yok)

        # Karışık (tarih en üstte):
        d = {'2026-02-09': 500, 'hafta_2': 410, 'Mon': 400, 'default': 380}
        _resolve_kadro(d, date_str='2026-02-09', day_label='Mon')  → 500  (tarih)
        _resolve_kadro(d, date_str='2026-02-10', day_label='Tue')  → 410  (hafta_2)
        _resolve_kadro(d, date_str='2026-02-16', day_label='Mon')  → 400  (Mon)
        _resolve_kadro(d, date_str='2026-02-17', day_label='Tue')  → 380  (default)
    """
    if isinstance(kadro_value, (int, float)):
        return int(kadro_value)
    if isinstance(kadro_value, dict):
        # 1) Belirli tarih (en spesifik)
        if date_str and date_str in kadro_value:
            return int(kadro_value[date_str])
        # 2) Hafta-N (ay içi sıralı, _week_of_month ile)
        if date_str:
            week_key = f"hafta_{_week_of_month(date_str)}"
            if week_key in kadro_value:
                return int(kadro_value[week_key])
        # 3) Gün-of-week (Mon..Sun)
        if day_label and day_label in kadro_value:
            return int(kadro_value[day_label])
        # 4) Default
        return int(kadro_value.get('default', 0))
    return 0


# =============================================================================
# SURPLUS DAĞITIM YARDIMCISI
# =============================================================================

def _allocate_within_pool(share, candidates, shift_cov, erlang_by_slot,
                          assignments, mip_by_slot_state, method):
    """rr_first: önce açık deficit'leri kapat; sonra proporsiyonel dağıt."""
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
# ERLANG PER-DAY BUILDERS (cascading fallback için)
# =============================================================================

def _decrement_shrinkage_cfg(shrinkage_cfg, decrement):
    """Saatlik dict shrinkage'da her değerden `decrement` çıkar, 0'da kıs."""
    if isinstance(shrinkage_cfg, dict):
        return {k: max(0.0, float(v) - decrement) for k, v in shrinkage_cfg.items()}
    return max(0.0, float(shrinkage_cfg) - decrement)


def _build_erlang_per_day(df_calls_30, queue, target_dates, config):
    """Verilen config ile Erlang hesapla, gün bazlı {day_label: {slot: need}}."""
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
    """Her gün için AYRI decrement uygulayarak Erlang hesapla (Stage 2 için)."""
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


# =============================================================================
# COVERAGE SHORTFALL ÖNERİSİ (Stage 4 için)
# =============================================================================

def _compute_shortfall_recommendations(info):
    """V9 — Shortfall'u kapatmak için MIP'in zaten kullandığı vardiyalara
    greedy +N kişi önerisi.

    Mantık: shortfall_by_slot'taki her slot'ta erlang_need - covered kadar
    kişi eksik. Bu eksikleri kapatabilen vardiyalar arasında (sadece o gün
    zaten atanmış olanlar = MIP'in seçtiği vardiyalar), en çok shortfall
    slot'unu birden kapatan vardiyaya +1 kişi ekle, kalan eksikleri düşür.

    Returns: {shift_key: int}  (öneri > 0 olanlar)
    """
    sf_by_slot = dict(info.get('shortfall_by_slot', {}))
    if not any(v > 0 for v in sf_by_slot.values()):
        return {}

    assigns = info.get('assignments', {})
    shift_cov = info.get('shift_coverage', {})

    candidates = [
        s for s, v in assigns.items()
        if v > 0 and any(slot in shift_cov[s]['slots'] for slot in sf_by_slot)
    ]
    if not candidates:
        return {}

    suggestions = {s: 0 for s in candidates}
    remaining = dict(sf_by_slot)

    guard = 0
    while any(v > 0 for v in remaining.values()) and guard < 10000:
        guard += 1
        best_shift = None
        best_score = 0
        for s in candidates:
            score = sum(1 for slot in shift_cov[s]['slots']
                        if remaining.get(slot, 0) > 0)
            if score > best_score:
                best_score = score
                best_shift = s
        if best_shift is None or best_score == 0:
            break
        suggestions[best_shift] += 1
        for slot in shift_cov[best_shift]['slots']:
            if remaining.get(slot, 0) > 0:
                remaining[slot] -= 1

    return {s: v for s, v in suggestions.items() if v > 0}


# =============================================================================
# PRINT HELPERS
# =============================================================================

def _print_trial_log_v8(trial_log, queue, solution_stage_label=None):
    """Fallback ladder denemelerini tablo halinde bas."""
    print(f"\n  ┌─ Fallback Ladder ({queue}) ─┐")
    print(f"  │ {'#':>3} {'Stage':<58} {'min':>14} {'Erlang':>8} {'Sonuç':<11} │")
    for t in trial_log:
        marker = ' ←' if t.get('stage') == solution_stage_label else '  '
        stage_short = t['stage'][:58] if len(t['stage']) <= 58 else t['stage'][:55] + '..'
        m = t['min_per_shift']
        if isinstance(m, dict):
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


def print_weekly_summary(stable_assignments, day_specific_assignments,
                         shift_cov, queue, target_dates):
    """Haftanın stable inhouse + günlük outsource + day-specific özeti."""
    print(f"\n{'='*90}")
    print(f"HAFTALIK ATAMA — {queue.upper()}")
    print(f"  Tarih aralığı: {target_dates[0]} → {target_dates[-1]}")
    print(f"{'='*90}")

    # Stable INHOUSE
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

    # Günlük outsource + day-specific
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


# =============================================================================
# SURPLUS DAĞITIM (per-day)
# =============================================================================

def _distribute_surplus_per_day(stable_assignments, day_specific_assignments,
                                 info_per_day, erlang_by_slot_per_day, queue,
                                 config, verbose=True):
    """Her gün için ayrı surplus dağıtımı.
    Stable atamalara DOKUNULMAZ — eklenenler day_specific'e yazılır.
    Her gün için info_per_day[d]'ye 'mip_info_stage1' (snapshot) eklenir.
    """
    sd_cfg = config.get('surplus_distribution', {})
    if not sd_cfg.get('enabled', False):
        return stable_assignments, day_specific_assignments, info_per_day

    kadro_cfg = sd_cfg.get('total_kadro', {}).get(queue, {})
    total_in_kadro_raw = kadro_cfg.get('inhouse', 0)
    total_out_kadro_raw = kadro_cfg.get('outsource', 0)

    def _any_positive(raw):
        if isinstance(raw, (int, float)):
            return raw > 0
        if isinstance(raw, dict):
            return any(v > 0 for v in raw.values())
        return False

    if not _any_positive(total_in_kadro_raw) and not _any_positive(total_out_kadro_raw):
        return stable_assignments, day_specific_assignments, info_per_day

    method = sd_cfg.get('method', 'rr_first')
    only_assigned = sd_cfg.get('only_assigned_shifts', True)
    fallback = sd_cfg.get('fallback_all_inhouse', True)
    windows = sd_cfg.get('windows', [])
    out_enabled = sd_cfg.get('outsource_enabled', True)

    ccfg = config['company']
    inhouse_value = ccfg['inhouse']['shift_value']
    outsource_value = ccfg['outsource']['shift_value']

    sample_info = next(iter(info_per_day.values()))
    shift_cov = sample_info['shift_coverage']

    for d_label, info in info_per_day.items():
        info['mip_info_stage1'] = copy.deepcopy(info)

        date_s = info.get('target_date')
        total_in_kadro_d = _resolve_kadro(total_in_kadro_raw, date_s, d_label)
        total_out_kadro_d = _resolve_kadro(total_out_kadro_raw, date_s, d_label)

        current_in = info['total_inhouse_kisi']
        current_out = info['total_outsource_kisi']
        surplus_in = max(0, total_in_kadro_d - current_in)
        surplus_out = max(0, total_out_kadro_d - current_out) if out_enabled else 0

        if verbose:
            print(f"   ➕ Surplus [{d_label}]: in={surplus_in} (kadro {total_in_kadro_d}-{current_in}), "
                  f"out={surplus_out} (kadro {total_out_kadro_d}-{current_out})")

        if surplus_in <= 0 and surplus_out <= 0:
            continue
        if not windows:
            if verbose:
                print(f"      ⚠ pencere tanımı yok, atlanıyor")
            continue

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

        for s, n in added_today.items():
            day_specific_today[s] = day_specific_today.get(s, 0) + n
            info['assignments'][s] = info['assignments'].get(s, 0) + n
        day_specific_assignments[d_label] = day_specific_today

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


# =============================================================================
# MIP CORE — optimize_week (V9, Stage 4 dahil)
# =============================================================================

def optimize_week(erlang_by_slot_per_day, df_shifts, queue, target_dates, config,
                  inhouse_min_per_day=None, outsource_min_per_day=None,
                  min_per_shift_override=None,
                  enable_coverage_shortfall=False,
                  coverage_shortfall_penalty=1000.0,
                  verbose=True):
    """5 günlük (Pzt-Cum) haftaiçi için tek MIP — V9 Stage 4 dahil.

    Returns:
        (stable_assignments, day_specific_assignments, info_per_day)
        - stable_assignments: {shift_key: count} → Pzt-Cum boyunca aynı
        - day_specific_assignments: {day_label: {shift_key: count}}
        - info_per_day: {day_label: mip_info dict}
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

    # V7 stabilite: inhouse + her gün aktif → stable; aksi → day-specific
    stable_shifts = [s for s in shifts
                     if shift_cov[s]['company'] == inhouse_value
                     and all(d in shift_cov[s]['available_days'] for d in target_day_labels)]
    day_specific_shifts = [s for s in shifts if s not in stable_shifts]

    in_shifts_stable = stable_shifts
    out_shifts_stable = []

    if verbose:
        n_out_ds = sum(1 for s in day_specific_shifts
                       if shift_cov[s]['company'] == outsource_value)
        n_in_ds = len(day_specific_shifts) - n_out_ds
        print(f"  [optimize_week] queue={queue}: stable_inhouse={len(stable_shifts)}, "
              f"daily_outsource={n_out_ds}, day_specific_inhouse={n_in_ds}")

    prob = LpProblem(f"Q_{queue}_weekly", LpMinimize)

    # ---- Karar değişkenleri ----
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
    n_days = len(target_day_labels)

    # ---- Vardiya maliyeti (stable cost n_days ile çarpılır — asimetri fix) ----
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

    # ---- RR penalty config ----
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

    # ---- Slot cap config ----
    sc_cfg = qconfigs.get('slot_cap', {})
    sc_enabled = sc_cfg.get('enabled', False)
    sc_bands = sc_cfg.get('bands', [])

    excess_per_day = {}
    sc_excess_per_day = {}
    peak_slots_per_day = {}
    sc_detail_per_day = {}
    # V9: Coverage shortfall — kadro yetmediğinde Erlang ihtiyacının altına izin
    shortfall_vars_per_day = {}

    # ---- Coverage + RR + Slot cap kısıtları (her gün × slot) ----
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

            # V9 Stage 4: coverage soft yap
            if enable_coverage_shortfall:
                sf_var = LpVariable(f"sf_{day_label}_{slot}",
                                     lowBound=0, cat='Continuous')
                shortfall_vars_per_day[(day_label, slot)] = sf_var
                prob += total_cov_expr + sf_var >= erlang_need
                cost.append(sf_var * coverage_shortfall_penalty)
            else:
                prob += total_cov_expr >= erlang_need

            # RR penalty
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

            # Slot cap
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

        # Alt-kuyruk min (inhouse / outsource — slot bazlı)
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

    # ---- min_per_shift (big-M) ----
    M = 500
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
        min_v = min_overrides.get(start_hour, min_default_global)
        prob += x[s] >= min_v * y[s]

    for (s, d) in day_shift_pairs:
        prob += x_day[(s, d)] <= M * y_day[(s, d)]
        start_hour = shift_cov[s]['start']
        if min_per_day_override is not None and d in min_per_day_override:
            min_v = min_per_day_override[d]
        else:
            min_v = min_overrides.get(start_hour, min_default_global)
        prob += x_day[(s, d)] >= min_v * y_day[(s, d)]

    # ---- Kadro tavanları (V9 per-day) ----
    kadro_cfg = config.get('surplus_distribution', {}).get('total_kadro', {}).get(queue, {})
    kadro_in_raw = kadro_cfg.get('inhouse', 0)
    kadro_out_raw = kadro_cfg.get('outsource', 0)

    kadro_in_per_day = {}
    kadro_out_per_day = {}
    for d_l, date_s in zip(target_day_labels, target_dates):
        kadro_in_per_day[d_l] = _resolve_kadro(kadro_in_raw, date_s, d_l)
        kadro_out_per_day[d_l] = _resolve_kadro(kadro_out_raw, date_s, d_l)

    if verbose and (any(v > 0 for v in kadro_in_per_day.values()) or
                     any(v > 0 for v in kadro_out_per_day.values())):
        in_uniform = len(set(kadro_in_per_day.values())) <= 1
        out_uniform = len(set(kadro_out_per_day.values())) <= 1
        if not (in_uniform and out_uniform):
            in_str = ','.join(f"{d}={kadro_in_per_day[d]}"
                              for d in target_day_labels)
            out_str = ','.join(f"{d}={kadro_out_per_day[d]}"
                               for d in target_day_labels)
            print(f"  [optimize_week] per-day kadro: in={in_str} | out={out_str}")

    for d in target_day_labels:
        kadro_in_d = kadro_in_per_day[d]
        kadro_out_d = kadro_out_per_day[d]

        if kadro_in_d > 0:
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
                prob += lpSum(terms) <= kadro_in_d

        if kadro_out_d > 0:
            out_day_pairs = [
                (s, d) for (s, d_p) in day_shift_pairs
                if d_p == d and shift_cov[s]['company'] == outsource_value
            ]
            if out_day_pairs:
                prob += lpSum([x_day[p] for p in out_day_pairs]) <= kadro_out_d

    # ---- Balance penalty ----
    only_inhouse = (allowed == ['inhouse'])
    bp_cfg = qconfigs.get('balance_penalty', config.get('balance_penalty', {}))
    bp_enabled = bp_cfg.get('enabled', False) and not only_inhouse
    bp_windows = bp_cfg.get('windows', [])
    bp_penalty_default = bp_cfg.get('penalty_per_diff', 2.0)
    balance_vars_per_day = {}

    if bp_enabled and bp_windows:
        for day_label in target_day_labels:
            for win in bp_windows:
                win_name = win['name']
                win_start = win['start']
                win_end = win['end']

                stable_in_in_win = [s for s in stable_shifts
                                     if shift_cov[s]['company'] == inhouse_value
                                     and win_start <= shift_cov[s]['start'] <= win_end]
                ds_in_in_win = [(s, day_label) for (s, d_p) in day_shift_pairs
                                if d_p == day_label
                                and shift_cov[s]['company'] == inhouse_value
                                and win_start <= shift_cov[s]['start'] <= win_end]
                ds_out_in_win = [(s, day_label) for (s, d_p) in day_shift_pairs
                                 if d_p == day_label
                                 and shift_cov[s]['company'] == outsource_value
                                 and win_start <= shift_cov[s]['start'] <= win_end]

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

    # ---- Solve ----
    prob += lpSum(cost)
    solver = PULP_CBC_CMD(msg=0)
    prob.solve(solver)
    status = LpStatus[prob.status]
    if verbose:
        print(f"  [optimize_week] solver status: {status}")

    if status != 'Optimal':
        return None, None, None

    # ---- Sonuçları topla ----
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

        # RR excess
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

        # Slot cap excess
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

        # Balance sonuçları
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
                    'inhouse': in_tot, 'outsource': out_tot,
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


# =============================================================================
# ORCHESTRATOR — run_week_all_queues
# =============================================================================

def run_week_all_queues(df_forecast, df_shifts_by_queue, target_dates, config,
                        queues=('kitle', 'kurumsal', 'gold'),
                        df_calls_30_pre=None, verbose=True):
    """V9 — 4-aşamalı cascading fallback ile haftalık MIP (forecast).

    Args:
        df_forecast: Forecast geniş formatı (15dk, KITLE_NOF_CALL vb.).
                     prepare_forecast_calls_30 ile içeride 30dk'ya çevrilir.
        df_shifts_by_queue: {queue: df_shifts}
        target_dates: ['2026-02-09', ..., '2026-02-13'] (5 günlük blok)
        config: CONFIG dict (forecast_cols, queues, queue_configs, vs.)
        queues: Çözülecek kuyruklar
        df_calls_30_pre: Önceden hesaplanmış df_calls_30 (opsiyonel — aylık
                         runner her hafta için tekrar convert etmesin diye).

    AŞAMA 1: Orijinal config
    AŞAMA 2: Per-day shrinkage azaltma (worst-day-first)
    AŞAMA 3: Per-day min_per_shift azaltma (varsayılan KAPALI)
    AŞAMA 4: Coverage shortfall (V9 — Erlang altına izin, yüksek penalty)

    Returns: {queue: {'stable', 'day_specific', 'info_per_day',
                       'solution_stage', 'shortfall_per_day',
                       'total_shortfall_week', ...}}
    """
    # Forecast → 30dk internal (kullanıcı df_calls_30_pre vermediyse)
    if df_calls_30_pre is None:
        df_calls_30 = prepare_forecast_calls_30(df_forecast, config=config)
    else:
        df_calls_30 = df_calls_30_pre

    day_labels = [_date_to_day_label(d) for d in target_dates]

    results = {}
    for queue in queues:
        if verbose:
            print(f"\n{'#'*80}\n# {queue.upper()} HAFTALIK MIP (V9 FORECAST)\n{'#'*80}")

        df_shifts = df_shifts_by_queue.get(queue)
        if df_shifts is None or df_shifts.empty:
            if verbose:
                print(f"  {queue}: vardiya yok, atlandı.")
            continue

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

        cs_cfg = mcfg.get('coverage_shortfall', {})
        cs_enabled = cs_cfg.get('enabled', False)
        cs_penalty = float(cs_cfg.get('penalty', 1000.0))

        original_shrinkage = config['queue_configs'][queue]['erlang']['shrinkage']
        if isinstance(original_shrinkage, dict):
            max_shr = max((float(v) for v in original_shrinkage.values()), default=0.0)
        else:
            max_shr = float(original_shrinkage)

        # Günleri çağrı sayısına göre sırala (en yoğun gün önce)
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

        # State
        decrements_per_day = {d: 0.0 for d in day_labels}
        mins_per_day = {d: default_min for d in day_labels}
        trial_log = []
        stable = day_specific = info_per_day = None
        solution_stage = None
        last_erl_pd = None

        def _trial(stage_label, min_param, enable_shortfall=False):
            """Bir MIP denemesi."""
            nonlocal last_erl_pd
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

            if isinstance(min_param, dict):
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
                'idx': idx, 'stage': stage_label,
                'decrements_per_day': dict(decrements_per_day),
                'decrement': max(decrements_per_day.values()) if decrements_per_day else 0.0,
                'min_per_shift': (dict(min_param) if isinstance(min_param, dict)
                                   else min_param),
                'erlang_total': erl_total, 'status': status,
            })
            if stable_try is not None:
                last_erl_pd = erl_pd
            return stable_try, day_try, info_try

        # ============== STAGE 1: Orijinal ==============
        stable, day_specific, info_per_day = _trial('STAGE 1: original', default_min)
        if stable is not None:
            solution_stage = 'STAGE 1: original'
            if verbose:
                print(f"\n  ✓ Orijinal config ile çözüldü")

        # ============== STAGE 2: Shrinkage fallback ==============
        if stable is None and wsf_enabled and max_shr > wsf_floor:
            if wsf_per_day:
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

        # ============== STAGE 3: min_per_shift per-day azaltma ==============
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

        # ============== STAGE 4: Coverage shortfall (V9) ==============
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

        # Sonuç değerlendirme
        if stable is None:
            if verbose:
                print(f"\n  ✗ {queue}: TÜM AŞAMALAR TÜKENDİ — INFEASIBLE")
                _print_trial_log_v8(trial_log, queue, None)
            continue

        # Meta bilgi — her günün info'sune ekle
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
            info_per_day[d_label]['shortfall_recommendations'] = \
                _compute_shortfall_recommendations(info_per_day[d_label])

        # Per-day surplus dağıtımı
        if config.get('surplus_distribution', {}).get('enabled', False):
            if verbose:
                print(f"\n  ➤ Per-day surplus dağıtımı başlıyor ({queue})…")
            stable, day_specific, info_per_day = _distribute_surplus_per_day(
                stable, day_specific, info_per_day,
                last_erl_pd, queue, config, verbose=verbose,
            )

        if verbose:
            _print_trial_log_v8(trial_log, queue, solution_stage)

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
            'shrinkage_decrement_used': max(decrements_per_day.values())
                                         if decrements_per_day else 0.0,
            'shrinkage_trial_log': trial_log,
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
