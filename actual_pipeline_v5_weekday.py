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
