# =============================================================================
# AYLIK ÇALIŞTIRMA V9 + UYUM KONTROLÜ
# =============================================================================
# Bir ayın TÜM günlerini koşar:
#   - Haftaiçi → actual_pipeline_v9_weekly.run_week_all_queues
#     (Pzt-Cum bloklarına ayırıp HER HAFTAYI tek MIP'te çözer)
#     V9 = V8 fallback ladder + Stage 4 (coverage shortfall)
#   - Haftasonu → weekend_model_gelistirim_final.run_all_queues (günlük MIP)
#
# V9 farkları:
#   - Stage 4 (coverage shortfall) sayesinde kadro yetmediğinde de çözüm üretir
#   - Her gün/queue için solution_stage notu çıkarılır (orijinal / shrinkage -X /
#     shortfall N kişi-slot)
#   - HÜCRE 7 sade çıktı: gün başına kuyruk bazlı OK [not] / INFEASIBLE
#   - HÜCRE 9/10/11 — KİTLE / GOLD / KURUMSAL plan özetleri ayrı hücrelerde
#
# Sonuç: results = {date_str: {queue: pipeline_output} | None}
# Cache: monthly_v9_YYYY_MM.pkl
#
# DOSYALAR:
#   - actual_pipeline_v9_weekly.py     → haftaiçi MIP motoru (V9, Stage 4 dahil)
#   - weekend_model_gelistirim_final.py → haftasonu MIP motoru (günlük)
#
# Hücre hücre çalıştır (# %% [HÜCRE N] ile işaretli).
# =============================================================================


# %% [HÜCRE 1] — Importlar
import io
import os
import pickle
import calendar
import contextlib
import pandas as pd

# V9 weekly — haftaiçi 5 günlük blok için (Stage 4 coverage shortfall ile)
from actual_pipeline_v9_weekly import (
    load_aht_from_df,
    run_week_all_queues,
    prepare_calls_30,
)
# weekend pipeline — haftasonu günlük
from weekend_model_gelistirim_final import (
    run_all_queues as run_weekend_all,
)


# %% [HÜCRE 2] — Veri çekme
# Mevcut notebook'taki veri çekme kodunu BURAYA YAPIŞTIR.
# Gereken:
#   - df_calls (en az tüm ayı içermeli)
#   - df_aht
#   - df_actual (gerçek vardiya verisi)
#   - df_shifts_dict = {'kitle': df, 'kurumsal': df, 'gold': df}


# %% [HÜCRE 3] — CONFIG_WEEKDAY
# run_weekly_v9.py'deki CONFIG_WEEKDAY'i buraya kopyala.
# V9 config eklemeleri (mip altında her queue için):
#   'coverage_shortfall': {'enabled': True, 'penalty': 1000.0}
#   'weekly_min_per_shift_fallback': {'enabled': False, ...}  (min sert kısıt)


# %% [HÜCRE 4] — CONFIG_WEEKEND


# %% [HÜCRE 5] — AHT yükle (her iki config için)
CONFIG_WEEKDAY['sub_queues'] = load_aht_from_df(df_aht, config=CONFIG_WEEKDAY)
CONFIG_WEEKEND['sub_queues'] = load_aht_from_df(df_aht, config=CONFIG_WEEKEND)


# %% [HÜCRE 6] — Aylık çalıştırma fonksiyonu
# Self-contained: notebook'ta HÜCRE 1 tekrar koşturulmasa bile çalışsın diye
# kritik import'ları burada da güvene alıyoruz.
import io
import contextlib

DAY_LABELS_EN = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
DAY_LABELS_TR = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Pzr']


def _wrap_weekly_info_as_daily(info, df_calls_30, queue, date_str):
    """v9 weekly info_per_day[d] çıktısını v6 daily benzeri dict'e çevirir."""
    d = pd.to_datetime(date_str)
    calls_col = f"{queue}_total"
    df_day = df_calls_30[df_calls_30['data_date'] == d]
    calls_by_slot = (dict(zip(df_day['slot_30'], df_day[calls_col]))
                     if calls_col in df_day.columns else {})
    return {
        'mip_info': info,
        'erlang_by_slot': info.get('erlang_by_slot', {}),
        'calls_by_slot': calls_by_slot,
        'actual': None,
        'date': d,
        'queue': queue,
    }


def _short_stage_note(solution_stage, total_shortfall_week=0):
    """V9 — solution_stage string'ini kısa, okunaklı bir nota çevirir.

    Örnekler:
      'STAGE 1: original'                       → 'orijinal'
      'STAGE 2 (per-day): Mon=-0.10'            → 'shrinkage Mon=-0.10'
      'STAGE 2 (uniform): all -0.20'            → 'shrinkage all -0.20'
      'STAGE 3 (per-day): Mon=12'               → 'min_per_shift Mon=12'
      'STAGE 4: coverage_shortfall'             → 'shortfall N kişi-slot'
    """
    if not solution_stage:
        return '?'
    s = solution_stage
    if s.startswith('STAGE 1'):
        return 'orijinal'
    if s.startswith('STAGE 2'):
        # 'STAGE 2 (per-day): Mon=-0.10, Tue=-0.05' veya 'STAGE 2 (uniform): all -0.20'
        try:
            payload = s.split(': ', 1)[1]
        except IndexError:
            payload = s
        return f"shrinkage {payload}"
    if s.startswith('STAGE 3'):
        try:
            payload = s.split(': ', 1)[1]
        except IndexError:
            payload = s
        return f"min_per_shift {payload}"
    if s.startswith('STAGE 4'):
        return f"shortfall {total_shortfall_week} kişi-slot"
    return s


def _run_weekend_silent(df_calls, df_actual, df_shifts_dict, date_str, config):
    """Haftasonu pipeline'ı stdout'u yutarak çağır — sadece sonuç dict'i alıyoruz."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = run_weekend_all(df_calls, df_actual, df_shifts_dict,
                            date_str, config=config)
    return r


def run_month(year, month, df_calls, df_actual, df_shifts_dict,
              cfg_weekday, cfg_weekend, queues=('kitle', 'kurumsal', 'gold'),
              verbose=False):
    """Bir ayın tüm günlerini koşar, results dict döner.

    verbose=False (default): per-day kuyruk bazlı tek satır OK[not] / INFEASIBLE
    verbose=True: V9 pipeline'ın tüm verbose çıktısı (debug için)

    Returns: {date_str: {queue: {mip_info, ...}} | None}
    """
    results = {}
    cal = calendar.Calendar()

    all_days = [d for d in cal.itermonthdates(year, month) if d.month == month]

    # Haftaiçi blokları (ardışık Pzt-Cum)
    weekday_blocks = []
    current = []
    for d in all_days:
        if d.weekday() < 5:
            current.append(d)
        else:
            if current:
                weekday_blocks.append(current)
                current = []
    if current:
        weekday_blocks.append(current)

    df_calls_30 = prepare_calls_30(df_calls, config=cfg_weekday)

    # ---- HAFTAİÇİ BLOKLARI ----
    for block in weekday_blocks:
        block_dates = [d.strftime('%Y-%m-%d') for d in block]
        block_label = f"{block_dates[0]} → {block_dates[-1]} ({len(block)} gün)"
        print(f"\n▶ Haftaiçi blok: {block_label}")

        try:
            if verbose:
                week_results = run_week_all_queues(
                    df_calls=df_calls,
                    df_shifts_by_queue=df_shifts_dict,
                    target_dates=block_dates,
                    config=cfg_weekday,
                    queues=queues,
                    verbose=True,
                )
            else:
                # Pipeline detaylarını yutarak çağır — yalnız result lazım
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    week_results = run_week_all_queues(
                        df_calls=df_calls,
                        df_shifts_by_queue=df_shifts_dict,
                        target_dates=block_dates,
                        config=cfg_weekday,
                        queues=queues,
                        verbose=False,
                    )
        except Exception as e:
            print(f"  ✗ blok hatası: {e}")
            for d in block:
                results[d.strftime('%Y-%m-%d')] = None
            continue

        # Her gün için: kuyruk bazlı OK [not] / INFEASIBLE
        for d in block:
            date_str = d.strftime('%Y-%m-%d')
            day_label = DAY_LABELS_EN[d.weekday()]
            day_name = DAY_LABELS_TR[d.weekday()]

            day_result = {}
            parts = []
            for queue in queues:
                q_res = week_results.get(queue)
                if q_res is None:
                    parts.append(f"{queue}: INFEASIBLE")
                    continue
                info = q_res.get('info_per_day', {}).get(day_label)
                if info is None:
                    parts.append(f"{queue}: INFEASIBLE")
                    continue
                day_result[queue] = _wrap_weekly_info_as_daily(
                    info, df_calls_30, queue, date_str)
                note = _short_stage_note(
                    q_res.get('solution_stage'),
                    q_res.get('total_shortfall_week', 0),
                )
                parts.append(f"{queue}: OK [{note}]")

            if not day_result:
                results[date_str] = None
                print(f"  ✗ {date_str} ({day_name}) — tümü INFEASIBLE")
            else:
                results[date_str] = day_result
                # Shortfall varsa uyarı sembolü
                has_sf = any(
                    week_results.get(q, {}).get('total_shortfall_week', 0) > 0
                    for q in day_result
                )
                mark = "⚠" if has_sf else "✓"
                print(f"  {mark} {date_str} ({day_name}) — " + "  |  ".join(parts))

    # ---- HAFTASONU GÜNLERİ ----
    weekend_days = [d for d in all_days if d.weekday() >= 5]
    if weekend_days:
        print(f"\n▶ Haftasonu günleri: {len(weekend_days)} gün")
    for d in weekend_days:
        date_str = d.strftime('%Y-%m-%d')
        day_name = DAY_LABELS_TR[d.weekday()]
        try:
            if verbose:
                r = run_weekend_all(df_calls, df_actual, df_shifts_dict,
                                    date_str, config=cfg_weekend)
            else:
                r = _run_weekend_silent(df_calls, df_actual, df_shifts_dict,
                                        date_str, cfg_weekend)
            results[date_str] = r
            if r:
                parts = []
                for queue in queues:
                    if queue in r and r[queue] is not None:
                        parts.append(f"{queue}: OK")
                    else:
                        parts.append(f"{queue}: INFEASIBLE")
                print(f"  ✓ {date_str} ({day_name}) — " + "  |  ".join(parts))
            else:
                print(f"  ✗ {date_str} ({day_name}) — boş sonuç")
        except Exception as e:
            print(f"  ✗ {date_str} ({day_name}) — weekend hatası: {e}")
            results[date_str] = None

    return results


# %% [HÜCRE 7] — Aylık çalıştır + cache  (V9 — sade çıktı)
YEAR = 2026
MONTH = 2
CACHE_FILE = f"monthly_v9_{YEAR}_{MONTH:02d}.pkl"

if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, 'rb') as f:
        results = pickle.load(f)
    print(f"Cache'ten yüklendi: {len(results)} gün ({CACHE_FILE})")
else:
    # verbose=False → pipeline detayları yutulur, sadece gün/kuyruk özetleri çıkar
    results = run_month(YEAR, MONTH, df_calls, df_actual, df_shifts_dict,
                        CONFIG_WEEKDAY, CONFIG_WEEKEND, verbose=False)
    with open(CACHE_FILE, 'wb') as f:
        pickle.dump(results, f)
    print(f"\nKaydedildi: {CACHE_FILE}")


# %% [HÜCRE 8] — Haftasonu İnhouse Bütçe Kontrolü (part-time HARİÇ)
WEEKEND_BUDGET = {
    'kitle':    1200,
    'gold':     300,
    'kurumsal': 120,
}

weekend_days = []
for date_str in sorted(results.keys()):
    d = pd.to_datetime(date_str)
    if d.weekday() >= 5:
        weekend_days.append((date_str, d.weekday()))

print(f"\n{'='*100}")
print(f"HAFTA SONU İNHOUSE BÜTÇE KONTROLÜ — {YEAR}/{MONTH:02d}  (part-time HARİÇ)")
print(f"{'='*100}")

print(f"{'Kuyruk':<10} ", end='')
for date_str, wd in weekend_days:
    label = ('Cmt' if wd == 5 else 'Pzr') + date_str[-2:]
    print(f"{label:>7}", end=' ')
print(f"{'Toplam':>8} {'Bütçe':>7} {'Durum':>12}")
print('-' * 100)

for queue, budget in WEEKEND_BUDGET.items():
    inhouse_per_day = []
    for date_str, _ in weekend_days:
        r = results.get(date_str)
        if r and queue in r and r[queue] is not None:
            mi = r[queue]['mip_info']
            inhouse_ft = mi.get('total_inhouse_kisi', 0) - mi.get('total_part_time_kisi', 0)
            inhouse_ft = max(0, inhouse_ft)
        else:
            inhouse_ft = 0
        inhouse_per_day.append(inhouse_ft)

    total = sum(inhouse_per_day)
    diff = total - budget
    if diff > 0:
        status = f"+{diff} AŞIM ✗"
    else:
        status = f"{diff:+d} OK ✓"

    print(f"{queue:<10} ", end='')
    for v in inhouse_per_day:
        print(f"{v:>7}", end=' ')
    print(f"{total:>8} {budget:>7} {status:>12}")

print('-' * 100)
print("Not: total_inhouse_kisi'den total_part_time_kisi çıkarılarak hesaplandı.")


# =============================================================================
# Plan özet + vardiya planı — ortak fonksiyon
# (HÜCRE 9/10/11 bunu kuyruk bazında çağırır)
# =============================================================================

DAY_NAMES = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Pzr']


def print_queue_monthly_plan(plan_queue, results, year, month):
    """Tek kuyruk için aylık plan — gün özet metrikler + vardiya roster.

    V9 farkı: solution_stage ve shortfall bilgisini de gösterir.
    """
    print(f"\n{'='*120}")
    print(f"GÜN GÜN PLAN ÖZETİ — {plan_queue.upper()} — {year}/{month:02d}")
    print(f"{'='*120}")
    print(f"  {'Tarih':<11} {'Gün':<4} {'Çağrı':>7} {'Erl_Pk':>7} {'Erl_T':>7} "
          f"{'MIP_Pk':>7} {'In':>5} {'Out':>5} {'PT':>4} {'Toplam':>7} {'Out%':>5} "
          f"{'Eksik':>6}  {'Çözüm':<28}")
    print('  ' + '-' * 118)

    t_cagri = t_erl_t = 0
    t_in = t_out = t_pt = 0
    t_sf = 0
    days_ok = 0

    for date_str in sorted(results.keys()):
        r = results.get(date_str)
        d = pd.to_datetime(date_str)
        gun = DAY_NAMES[d.weekday()]

        if r is None or plan_queue not in r or r[plan_queue] is None:
            print(f"  {date_str:<11} {gun:<4} {'-':>7} {'-':>7} {'-':>7} "
                  f"{'-':>7} {'-':>5} {'-':>5} {'-':>4} {'-':>7} {'-':>5} "
                  f"{'-':>6}  INFEASIBLE")
            continue

        qr = r[plan_queue]
        mi = qr['mip_info']

        calls_by_slot = qr.get('calls_by_slot', {}) or {}
        cagri = int(sum(calls_by_slot.values()))

        erlang_by_slot = qr.get('erlang_by_slot', {}) or {}
        erl_pk = max(erlang_by_slot.values()) if erlang_by_slot else 0
        erl_t = sum(erlang_by_slot.values())

        mip_by_slot = mi.get('mip_by_slot', {}) or {}
        mip_pk = max(mip_by_slot.values()) if mip_by_slot else 0

        in_ft = max(0, mi.get('total_inhouse_kisi', 0) - mi.get('total_part_time_kisi', 0))
        out = mi.get('total_outsource_kisi', 0)
        pt = mi.get('total_part_time_kisi', 0)
        toplam = in_ft + out + pt
        out_pct = out / toplam if toplam > 0 else 0

        # V9: solution_stage notu + shortfall
        sol_stage = mi.get('solution_stage')
        sf_total = mi.get('total_shortfall', 0)
        note = _short_stage_note(sol_stage, sf_total) if sol_stage else 'weekend'
        sf_str = str(sf_total) if sf_total > 0 else '-'

        print(f"  {date_str:<11} {gun:<4} {cagri:>7,} {erl_pk:>7} {erl_t:>7} "
              f"{mip_pk:>7} {in_ft:>5} {out:>5} {pt:>4} {toplam:>7} {out_pct:>4.0%} "
              f"{sf_str:>6}  {note[:28]:<28}")

        t_cagri += cagri
        t_erl_t += erl_t
        t_in += in_ft
        t_out += out
        t_pt += pt
        t_sf += sf_total
        days_ok += 1

    t_toplam = t_in + t_out + t_pt
    t_out_pct = t_out / t_toplam if t_toplam > 0 else 0
    print('  ' + '-' * 118)
    print(f"  {'AYLIK':<11} {'-':<4} {t_cagri:>7,} {'-':>7} {t_erl_t:>7} "
          f"{'-':>7} {t_in:>5} {t_out:>5} {t_pt:>4} {t_toplam:>7} {t_out_pct:>4.0%} "
          f"{t_sf:>6}")
    print(f"\n  Erl_Pk=eşzamanlı Erlang peak  |  Erl_T=günlük Erlang toplamı")
    print(f"  Eksik=Stage 4 coverage shortfall (kişi-slot)  |  Çözüm=fallback aşaması")
    print(f"  Başarılı: {days_ok}/{len(results)} gün")

    # ---- Vardiya planı (roster) ----
    print(f"\n{'='*100}")
    print(f"GÜN GÜN VARDIYA PLANI — {plan_queue.upper()} — {year}/{month:02d}")
    print(f"{'='*100}")

    for date_str in sorted(results.keys()):
        r = results.get(date_str)
        d = pd.to_datetime(date_str)
        gun = DAY_NAMES[d.weekday()]

        if r is None or plan_queue not in r or r[plan_queue] is None:
            print(f"\n--- {date_str} ({gun}) ---  INFEASIBLE")
            continue

        qr = r[plan_queue]
        mi = qr['mip_info']
        assignments = mi.get('assignments', {})
        sc = mi.get('shift_coverage', {})

        in_ft = max(0, mi.get('total_inhouse_kisi', 0) - mi.get('total_part_time_kisi', 0))
        out = mi.get('total_outsource_kisi', 0)
        pt = mi.get('total_part_time_kisi', 0)
        toplam = in_ft + out + pt
        sf_total = mi.get('total_shortfall', 0)

        header = f"--- {date_str} ({gun}) ---  In={in_ft}  Out={out}  PT={pt}  Toplam={toplam}"
        if sf_total > 0:
            header += f"  ⚠ Eksik={sf_total} kişi-slot"
        print(f"\n{header}")

        active = [(s, c) for s, c in assignments.items() if c > 0]
        if not active:
            print(f"    (vardiya yok)")
            continue

        active.sort(key=lambda x: (sc.get(x[0], {}).get('start', '99:99'),
                                    sc.get(x[0], {}).get('company', 'zzz')))

        # V9: shortfall önerileri varsa kolon ekle
        sf_recs = mi.get('shortfall_recommendations', {}) or {}
        has_rec = bool(sf_recs)

        if has_rec:
            print(f"    {'Vardiya':<32} {'Saat':<14} {'Şirket':<10} "
                  f"{'Kişi':>5} {'+Öneri':>7} {'Önerilen':>9}")
            print(f"    {'-'*84}")
        else:
            print(f"    {'Vardiya':<32} {'Saat':<14} {'Şirket':<10} {'Kişi':>5}")
            print(f"    {'-'*68}")

        for s, cnt in active:
            info = sc.get(s, {})
            saat = f"{info.get('start','--:--')}-{info.get('end','--:--')}"
            comp = info.get('company', '-')
            if has_rec:
                rec = sf_recs.get(s, 0)
                rec_str = f"+{rec}" if rec > 0 else "-"
                new_total = cnt + rec
                mark = " ←" if rec > 0 else "  "
                print(f"    {s:<32} {saat:<14} {comp:<10} "
                      f"{cnt:>5} {rec_str:>7} {new_total:>8}{mark}")
            else:
                print(f"    {s:<32} {saat:<14} {comp:<10} {cnt:>5}")

        if has_rec:
            rec_total = sum(sf_recs.values())
            print(f"    → +{rec_total} kişi eklenirse {sf_total} kişi-slot eksik kapanır")


# %% [HÜCRE 9] — KİTLE — gün gün plan özeti + vardiya planı
print_queue_monthly_plan('kitle', results, YEAR, MONTH)


# %% [HÜCRE 10] — GOLD — gün gün plan özeti + vardiya planı
print_queue_monthly_plan('gold', results, YEAR, MONTH)


# %% [HÜCRE 11] — KURUMSAL — gün gün plan özeti + vardiya planı
print_queue_monthly_plan('kurumsal', results, YEAR, MONTH)


# %% [HÜCRE 12] — Excel'e aktar: vardiya planı + haftasonu bütçe
# Sheet 1 "Vardiya Planı": haftalara bölünmüş timetable (Pzt-Pzr 7 sütun)
#   - Her hafta başlığı, sonra kuyruk bazlı vardiya satırları, kişi sayıları
# Sheet 2 "Bütçe": haftasonu inhouse bütçe kontrolü tablosu

import pandas as pd


def export_monthly_plan_to_excel(results, year, month, weekend_budget,
                                  queues=('kitle', 'gold', 'kurumsal'),
                                  output_path=None):
    """Aylık vardiya planını + haftasonu bütçesini Excel'e yazar."""
    if output_path is None:
        output_path = f"monthly_v9_plan_{year}_{month:02d}.xlsx"

    all_dates = sorted(results.keys())
    if not all_dates:
        print("⚠ results boş, export atlandı")
        return None

    # Ayı kapsayan Pzt-Pzr haftaları (eksik günler boş kalır)
    first = pd.to_datetime(all_dates[0])
    last = pd.to_datetime(all_dates[-1])
    start_mon = first - pd.Timedelta(days=first.weekday())
    end_sun = last + pd.Timedelta(days=(6 - last.weekday()))

    weeks = []
    cur = start_mon
    while cur <= end_sun:
        week = [(cur + pd.Timedelta(days=i)).strftime('%Y-%m-%d')
                for i in range(7)]
        weeks.append(week)
        cur += pd.Timedelta(days=7)

    DAY_TR = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Pzr']

    # ---- Sheet 1: Vardiya Planı ----
    # Sabit kolonlar: # | Kuyruk | Vardiya | Saat | Şirket | <gün sütunları> | Toplam
    # Gün sütun başlığı her hafta için kendi tarihini taşır (örn. "Pzt 02-02")
    rows = []
    for week_idx, week in enumerate(weeks, 1):
        # Hafta ayraç satırı
        sep_row = {
            '#': f"HAFTA {week_idx}",
            'Kuyruk': f"{week[0]} → {week[-1]}",
            'Vardiya': '', 'Saat': '', 'Şirket': '',
        }
        for i in range(7):
            sep_row[f"{DAY_TR[i]} {week[i][-5:]}"] = ''
        sep_row['Toplam'] = ''
        rows.append(sep_row)

        for queue in queues:
            # O haftada aktif vardiyaları topla
            shifts_in_week = {}   # shift_key → {day_idx: count}
            shift_info = {}       # shift_key → {start, end, company}
            for i, ds in enumerate(week):
                r = results.get(ds)
                if not r or queue not in r or not r[queue]:
                    continue
                mi = r[queue]['mip_info']
                sc = mi.get('shift_coverage', {})
                for s, c in mi.get('assignments', {}).items():
                    if c <= 0:
                        continue
                    shifts_in_week.setdefault(s, {})[i] = c
                    if s not in shift_info:
                        shift_info[s] = sc.get(s, {})
            if not shifts_in_week:
                continue

            sorted_shifts = sorted(
                shifts_in_week.keys(),
                key=lambda x: (shift_info.get(x, {}).get('start', '99:99'),
                                shift_info.get(x, {}).get('company', 'zzz')),
            )
            for s in sorted_shifts:
                info = shift_info[s]
                saat = f"{info.get('start', '')}-{info.get('end', '')}"
                row = {
                    '#': '',
                    'Kuyruk': queue,
                    'Vardiya': s,
                    'Saat': saat,
                    'Şirket': info.get('company', ''),
                }
                total = 0
                for i in range(7):
                    c = shifts_in_week[s].get(i, 0)
                    row[f"{DAY_TR[i]} {week[i][-5:]}"] = c if c > 0 else ''
                    total += c
                row['Toplam'] = total
                rows.append(row)

        # Hafta sonunda boş ayraç
        rows.append({})

    df_plan = pd.DataFrame(rows)

    # ---- Sheet 2: Haftasonu Bütçe Kontrolü ----
    weekend_days = [(d, pd.to_datetime(d).weekday()) for d in all_dates
                    if pd.to_datetime(d).weekday() >= 5]

    budget_rows = []
    for queue, budget in weekend_budget.items():
        row = {'Kuyruk': queue}
        total = 0
        for date_str, wd in weekend_days:
            label = ('Cmt' if wd == 5 else 'Pzr') + date_str[-2:]
            r = results.get(date_str)
            if r and queue in r and r[queue]:
                mi = r[queue]['mip_info']
                inhouse_ft = max(0, mi.get('total_inhouse_kisi', 0)
                                  - mi.get('total_part_time_kisi', 0))
            else:
                inhouse_ft = 0
            row[label] = inhouse_ft
            total += inhouse_ft
        row['Toplam'] = total
        row['Bütçe'] = budget
        diff = total - budget
        row['Fark'] = diff
        row['Durum'] = 'AŞIM' if diff > 0 else 'OK'
        budget_rows.append(row)
    df_budget = pd.DataFrame(budget_rows)

    # ---- Excel'e yaz ----
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        df_plan.to_excel(writer, sheet_name='Vardiya Planı', index=False)
        df_budget.to_excel(writer, sheet_name='Bütçe', index=False)

        # Kolon genişliklerini biraz ayarla (okunabilirlik)
        ws = writer.sheets['Vardiya Planı']
        widths = {'A': 10, 'B': 12, 'C': 28, 'D': 14, 'E': 12,
                  'F': 11, 'G': 11, 'H': 11, 'I': 11, 'J': 11, 'K': 11, 'L': 11,
                  'M': 9}
        for col, w in widths.items():
            ws.column_dimensions[col].width = w

        ws2 = writer.sheets['Bütçe']
        ws2.column_dimensions['A'].width = 12
        for col_idx in range(2, 2 + len(weekend_days)):
            col_letter = ws2.cell(row=1, column=col_idx).column_letter
            ws2.column_dimensions[col_letter].width = 9

    print(f"✓ Excel kaydedildi: {output_path}")
    print(f"  Sheet 'Vardiya Planı': {len(weeks)} hafta, {len(df_plan)} satır")
    print(f"  Sheet 'Bütçe': {len(df_budget)} kuyruk, {len(weekend_days)} hafta sonu günü")
    return output_path


export_monthly_plan_to_excel(
    results=results,
    year=YEAR,
    month=MONTH,
    weekend_budget=WEEKEND_BUDGET,
    queues=('kitle', 'gold', 'kurumsal'),
)
