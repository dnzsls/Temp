# =============================================================================
# AYLIK ÇALIŞTIRMA + UYUM KONTROLÜ
# =============================================================================
# Bir ayın TÜM günlerini koşar:
#   - Haftaiçi → actual_pipeline_v6_weekday.run_all_queues (günlük MIP)
#   - Haftasonu → weekend_model_gelistirim_final.run_all_queues (günlük MIP)
#
# Sonuç: results = {date_str: {queue: pipeline_output}}
# Cache: monthly_YYYY_MM.pkl
#
# Sonunda haftasonu inhouse bütçe kontrolü basılır (part-time HARİÇ).
#
# DOSYALAR:
#   - actual_pipeline_v6_weekday.py   → haftaiçi MIP motoru
#   - weekend_model_gelistirim_final.py → haftasonu MIP motoru
#
# Hücre hücre çalıştır (# %% [HÜCRE N] ile işaretli).
# =============================================================================


# %% [HÜCRE 1] — Importlar
import os
import pickle
import calendar
import pandas as pd

# v6 daily — weekday için (run_all_queues'i alias ile)
from actual_pipeline_v6_weekday import (
    load_aht_from_df,
    run_all_queues as run_weekday_all,
)
# weekend pipeline
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
#
# Örnek:
#   df_calls   = pd.read_sql("SELECT ... FROM ...", conn)
#   df_aht     = pd.read_sql("SELECT ... FROM ...", conn)
#   df_actual  = pd.read_sql("SELECT ... FROM ...", conn)
#   df_shifts_dict = {
#       'kitle':    pd.read_excel('vardiyalar.xlsx', sheet_name='kitle'),
#       'kurumsal': pd.read_excel('vardiyalar.xlsx', sheet_name='kurumsal'),
#       'gold':     pd.read_excel('vardiyalar.xlsx', sheet_name='gold'),
#   }


# %% [HÜCRE 3] — CONFIG_WEEKDAY (inline ya da config_v6_weekday'den import)
# Örnek (inline):
#   from config_v6_weekday import CONFIG as CONFIG_WEEKDAY
# veya run_weekly_v7.py'deki CONFIG_WEEKDAY'i buraya kopyala.
# (Bu hücreyi kendi config'in ile doldur.)


# %% [HÜCRE 4] — CONFIG_WEEKEND (inline ya da weekend_config_final'den import)
# Örnek:
#   from weekend_config_final import CONFIG as CONFIG_WEEKEND
# (Bu hücreyi kendi haftasonu config'inle doldur.)


# %% [HÜCRE 5] — AHT yükle (her iki config için)
CONFIG_WEEKDAY['sub_queues'] = load_aht_from_df(df_aht, config=CONFIG_WEEKDAY)
CONFIG_WEEKEND['sub_queues'] = load_aht_from_df(df_aht, config=CONFIG_WEEKEND)


# %% [HÜCRE 6] — Aylık çalıştırma fonksiyonu
def run_month(year, month, df_calls, df_actual, df_shifts,
              cfg_weekday, cfg_weekend, verbose=False):
    """Bir ayın tüm günlerini koşar, results dict döner.

    Returns: {date_str: {queue: {mip_info, actual, ...}} | None}
    """
    results = {}
    cal = calendar.Calendar()

    for day in cal.itermonthdates(year, month):
        if day.month != month:
            continue
        date_str = day.strftime('%Y-%m-%d')

        try:
            if day.weekday() >= 5:   # cumartesi/pazar
                r = run_weekend_all(df_calls, df_actual, df_shifts,
                                     date_str, config=cfg_weekend)
            else:
                r = run_weekday_all(df_calls, df_actual, df_shifts,
                                     date_str, config=cfg_weekday)
            results[date_str] = r
            day_name = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Pzr'][day.weekday()]
            print(f"✓ {date_str} ({day_name}) tamamlandı")
        except Exception as e:
            print(f"✗ {date_str} hata: {e}")
            results[date_str] = None

    return results


# %% [HÜCRE 7] — Aylık çalıştır + cache
YEAR = 2026
MONTH = 2
CACHE_FILE = f"monthly_{YEAR}_{MONTH:02d}.pkl"

if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, 'rb') as f:
        results = pickle.load(f)
    print(f"Cache'ten yüklendi: {len(results)} gün")
else:
    results = run_month(YEAR, MONTH, df_calls, df_actual, df_shifts_dict,
                        CONFIG_WEEKDAY, CONFIG_WEEKEND)
    with open(CACHE_FILE, 'wb') as f:
        pickle.dump(results, f)
    print(f"Kaydedildi: {CACHE_FILE}")


# %% [HÜCRE 8] — Özet
print(f"Toplam gün: {len(results)}")
print(f"Başarılı:   {sum(1 for r in results.values() if r is not None)}")
print(f"Başarısız:  {sum(1 for r in results.values() if r is None)}")

# Bir hafta sonu örneği — yapı kontrolü
sample_date = next(
    (d for d in sorted(results.keys())
     if pd.to_datetime(d).weekday() >= 5 and results[d] is not None),
    None,
)
if sample_date:
    sample = results[sample_date]
    print(f"\n{sample_date} key'leri: {list(sample.keys())}")


# %% [HÜCRE 9] — Haftasonu İnhouse Bütçe Kontrolü (part-time HARİÇ)
# Pipeline'da mip_info['total_inhouse_kisi'] ZATEN full-time only —
# part-time ayrı bir alanda (total_part_time_kisi) tutuluyor.
# Yine de defansif: explicit subtract yapıyoruz ki gelecekte yapı değişse de
# bütçe karşılaştırması part-time'ı saymasın.
WEEKEND_BUDGET = {
    'kitle':    1200,
    'gold':     300,
    'kurumsal': 120,
}

# Haftasonu günlerini topla
weekend_days = []
for date_str in sorted(results.keys()):
    d = pd.to_datetime(date_str)
    if d.weekday() >= 5:   # Cmt veya Pzr
        weekend_days.append((date_str, d.weekday()))

print(f"\n{'='*100}")
print(f"HAFTA SONU İNHOUSE BÜTÇE KONTROLÜ — {YEAR}/{MONTH:02d}  (part-time HARİÇ)")
print(f"{'='*100}")

# Tablo başlığı — günleri yan yana
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
            # Full-time inhouse = total_inhouse_kisi − total_part_time_kisi
            # (total_inhouse_kisi pipeline'da zaten PT'siz ama defansif çıkarıyoruz)
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


# %% [HÜCRE 10] — Aylık inhouse/outsource breakdown (haftalık + aylık + ratio)
# Her queue için: ISO hafta bazlı IN/OUT toplamları + ay sonu toplam + Out%.
# En altta tüm kuyrukların aylık özeti.
QUEUES = ['kitle', 'kurumsal', 'gold']

print(f"\n{'='*100}")
print(f"AYLIK İNHOUSE / OUTSOURCE BREAKDOWN — {YEAR}/{MONTH:02d}  (part-time HARİÇ)")
print(f"{'='*100}")

# Aylık özet için biriktir
overall = {q: {'in': 0, 'out': 0} for q in QUEUES}

for queue in QUEUES:
    # Günleri ISO haftaya grupla
    weeks = {}   # iso_week → [(date_str, in, out)]
    for date_str in sorted(results.keys()):
        r = results.get(date_str)
        if r is None or queue not in r or r[queue] is None:
            continue
        mi = r[queue]['mip_info']
        in_ft = max(0, mi.get('total_inhouse_kisi', 0)
                       - mi.get('total_part_time_kisi', 0))
        out = mi.get('total_outsource_kisi', 0)
        d = pd.to_datetime(date_str)
        iso_week = int(d.isocalendar().week)
        weeks.setdefault(iso_week, []).append((date_str, in_ft, out))

    if not weeks:
        print(f"\n{queue.upper()} — veri yok")
        continue

    print(f"\n{queue.upper()}")
    print(f"  {'Hafta':<8} {'Tarih aralığı':<24} {'Gün':>4} "
          f"{'Inhouse':>9} {'Outsrc':>9} {'Toplam':>9} {'Out%':>6}")
    print(f"  {'-'*78}")

    tot_in = tot_out = tot_days = 0
    for iso_week in sorted(weeks.keys()):
        days = weeks[iso_week]
        first = days[0][0]
        last = days[-1][0]
        range_str = f"{first[5:]} → {last[5:]}"   # MM-DD → MM-DD
        w_in = sum(x[1] for x in days)
        w_out = sum(x[2] for x in days)
        w_total = w_in + w_out
        w_ratio = w_out / w_total if w_total > 0 else 0
        print(f"  Hafta {iso_week:<2} {range_str:<24} {len(days):>4} "
              f"{w_in:>9} {w_out:>9} {w_total:>9} {w_ratio:>5.0%}")
        tot_in += w_in
        tot_out += w_out
        tot_days += len(days)

    tot_total = tot_in + tot_out
    tot_ratio = tot_out / tot_total if tot_total > 0 else 0
    print(f"  {'-'*78}")
    print(f"  {'AYLIK':<8} {'TOPLAM':<24} {tot_days:>4} "
          f"{tot_in:>9} {tot_out:>9} {tot_total:>9} {tot_ratio:>5.0%}")

    overall[queue]['in'] = tot_in
    overall[queue]['out'] = tot_out

# Tüm kuyrukların aylık özeti
print(f"\n{'='*100}")
print(f"TÜM KUYRUKLAR — AYLIK ÖZET")
print(f"{'='*100}")
print(f"  {'Queue':<10} {'Inhouse':>10} {'Outsrc':>10} {'Toplam':>10} {'Out%':>7}")
print(f"  {'-'*52}")
grand_in = grand_out = 0
for q in QUEUES:
    o = overall[q]
    t = o['in'] + o['out']
    r = o['out'] / t if t > 0 else 0
    print(f"  {q:<10} {o['in']:>10} {o['out']:>10} {t:>10} {r:>6.0%}")
    grand_in += o['in']
    grand_out += o['out']
grand_total = grand_in + grand_out
grand_ratio = grand_out / grand_total if grand_total > 0 else 0
print(f"  {'-'*52}")
print(f"  {'TOPLAM':<10} {grand_in:>10} {grand_out:>10} {grand_total:>10} "
      f"{grand_ratio:>6.0%}")
print(f"\nNot: Inhouse=full-time (part-time hariç) | "
      f"Out%=Outsource/(Inhouse+Outsource) | Hafta=ISO hafta numarası")


# %% [HÜCRE 11] — Gün gün plan — KİTLE — özet metrikler
# Her gün için: çağrı, Erlang peak/toplam, MIP peak, kişi sayıları, Out%
PLAN_QUEUE = 'kitle'
DAY_NAMES = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Pzr']

print(f"\n{'='*112}")
print(f"GÜN GÜN PLAN ÖZETİ — {PLAN_QUEUE.upper()} — {YEAR}/{MONTH:02d}")
print(f"{'='*112}")
print(f"  {'Tarih':<11} {'Gün':<4} {'Çağrı':>7} {'Erl_Pk':>7} {'Erl_T':>7} "
      f"{'MIP_Pk':>7} {'In':>5} {'Out':>5} {'PT':>4} {'Toplam':>7} {'Out%':>6}")
print('  ' + '-' * 110)

t_cagri = t_erl_t = 0
t_in = t_out = t_pt = 0
days_ok = 0

for date_str in sorted(results.keys()):
    r = results.get(date_str)
    d = pd.to_datetime(date_str)
    gun = DAY_NAMES[d.weekday()]

    if r is None or PLAN_QUEUE not in r or r[PLAN_QUEUE] is None:
        print(f"  {date_str:<11} {gun:<4} {'-':>7} {'-':>7} {'-':>7} "
              f"{'-':>7} {'-':>5} {'-':>5} {'-':>4} {'-':>7} {'-':>6}  (veri yok)")
        continue

    qr = r[PLAN_QUEUE]
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

    print(f"  {date_str:<11} {gun:<4} {cagri:>7,} {erl_pk:>7} {erl_t:>7} "
          f"{mip_pk:>7} {in_ft:>5} {out:>5} {pt:>4} {toplam:>7} {out_pct:>5.0%}")

    t_cagri += cagri
    t_erl_t += erl_t
    t_in += in_ft
    t_out += out
    t_pt += pt
    days_ok += 1

t_toplam = t_in + t_out + t_pt
t_out_pct = t_out / t_toplam if t_toplam > 0 else 0
print('  ' + '-' * 110)
print(f"  {'AYLIK':<11} {'-':<4} {t_cagri:>7,} {'-':>7} {t_erl_t:>7} "
      f"{'-':>7} {t_in:>5} {t_out:>5} {t_pt:>4} {t_toplam:>7} {t_out_pct:>5.0%}")
print(f"\n  Erl_Pk=eşzamanlı Erlang peak  |  Erl_T=günlük Erlang toplamı (kişi-slot)")
print(f"  MIP_Pk=eşzamanlı MIP peak  |  In=full-time inhouse (PT hariç)")
print(f"  Out%=Outsource/(In+Out+PT)  |  Başarılı: {days_ok}/{len(results)} gün")


# %% [HÜCRE 12] — Gün gün vardiya planı — KİTLE — detaylı roster
# Her gün için açılan vardiyaların listesi (saat, şirket, kişi sayısı)
print(f"\n{'='*100}")
print(f"GÜN GÜN VARDIYA PLANI — {PLAN_QUEUE.upper()} — {YEAR}/{MONTH:02d}")
print(f"{'='*100}")

for date_str in sorted(results.keys()):
    r = results.get(date_str)
    d = pd.to_datetime(date_str)
    gun = DAY_NAMES[d.weekday()]

    if r is None or PLAN_QUEUE not in r or r[PLAN_QUEUE] is None:
        print(f"\n--- {date_str} ({gun}) ---  (veri yok)")
        continue

    qr = r[PLAN_QUEUE]
    mi = qr['mip_info']
    assignments = mi.get('assignments', {})
    sc = mi.get('shift_coverage', {})

    in_ft = max(0, mi.get('total_inhouse_kisi', 0) - mi.get('total_part_time_kisi', 0))
    out = mi.get('total_outsource_kisi', 0)
    pt = mi.get('total_part_time_kisi', 0)
    toplam = in_ft + out + pt

    print(f"\n--- {date_str} ({gun}) ---  "
          f"In={in_ft}  Out={out}  PT={pt}  Toplam={toplam}")

    active = [(s, c) for s, c in assignments.items() if c > 0]
    if not active:
        print(f"    (vardiya yok)")
        continue

    # Saat sırasına göre sırala, oradan da şirkete göre
    active.sort(key=lambda x: (sc.get(x[0], {}).get('start', '99:99'),
                                sc.get(x[0], {}).get('company', 'zzz')))

    print(f"    {'Vardiya':<32} {'Saat':<14} {'Şirket':<10} {'Kişi':>5}")
    print(f"    {'-'*68}")
    for s, cnt in active:
        info = sc.get(s, {})
        saat = f"{info.get('start','--:--')}-{info.get('end','--:--')}"
        comp = info.get('company', '-')
        print(f"    {s:<32} {saat:<14} {comp:<10} {cnt:>5}")

print(f"\n{'='*100}")
print(f"NOT: Sadece kitle. Diğer kuyrukları (kurumsal/gold) sonra ekleyeceğiz.")
