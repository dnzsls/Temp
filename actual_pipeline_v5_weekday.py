# =============================================================================
# AYLIK ÇALIŞTIRMA + UYUM KONTROLÜ
# =============================================================================
# Bir ayın TÜM günlerini koşar:
#   - Haftaiçi → actual_pipeline_v7_weekly.run_week_all_queues
#     (Pzt-Cum bloklarına ayırıp HER HAFTAYI tek MIP'te çözer)
#   - Haftasonu → weekend_model_gelistirim_final.run_all_queues (günlük MIP)
#
# Davranış: v7 weekly bir hafta için infeasible verirse o haftanın 5 günü de
# None gelir (tutarlı). Daily ile karışan yanıltıcı kısmi sonuçlar yok.
#
# Sonuç: results = {date_str: {queue: pipeline_output} | None}
# Cache: monthly_YYYY_MM.pkl
#
# DOSYALAR:
#   - actual_pipeline_v7_weekly.py     → haftaiçi MIP motoru (haftalık)
#   - weekend_model_gelistirim_final.py → haftasonu MIP motoru (günlük)
#
# Hücre hücre çalıştır (# %% [HÜCRE N] ile işaretli).
# =============================================================================


# %% [HÜCRE 1] — Importlar
import os
import pickle
import calendar
import pandas as pd

# v7 weekly — haftaiçi 5 günlük blok için
from actual_pipeline_v7_weekly import (
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
DAY_LABELS_EN = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
DAY_LABELS_TR = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Pzr']


def _wrap_weekly_info_as_daily(info, df_calls_30, queue, date_str):
    """v7 weekly info_per_day[d] çıktısını v6 daily benzeri dict'e çevirir.

    Sonraki hücrelerin (bütçe kontrolü, plan) beklediği yapı:
      r[queue] = {'mip_info': {...}, 'erlang_by_slot': {...},
                  'calls_by_slot': {...}, 'actual': None}
    """
    d = pd.to_datetime(date_str)
    calls_col = f"{queue}_total"
    df_day = df_calls_30[df_calls_30['data_date'] == d]
    calls_by_slot = (dict(zip(df_day['slot_30'], df_day[calls_col]))
                     if calls_col in df_day.columns else {})
    return {
        'mip_info': info,                              # mip_info-uyumlu
        'erlang_by_slot': info.get('erlang_by_slot', {}),
        'calls_by_slot': calls_by_slot,
        'actual': None,                                # aylık'ta gerekmiyor
        'date': d,
        'queue': queue,
    }


def run_month(year, month, df_calls, df_actual, df_shifts_dict,
              cfg_weekday, cfg_weekend, verbose=False):
    """Bir ayın tüm günlerini koşar, results dict döner.

    Haftaiçi (Pzt-Cum) → v7 weekly tek MIP (ardışık bloklara ayrılır)
    Haftasonu (Cmt-Pzr) → v6 weekend günlük

    Returns: {date_str: {queue: {mip_info, ...}} | None}
        - Hafta infeasible ise o haftanın 5 günü de None
        - Queue infeasible ise o queue'nun anahtarı r'de yok
    """
    results = {}
    cal = calendar.Calendar()

    # 1) Ayın tüm günlerini sırala
    all_days = [d for d in cal.itermonthdates(year, month) if d.month == month]

    # 2) Haftaiçi günleri ARDIŞIK bloklara grupla (haftasonu blokları keser)
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

    # 3) Veri hazırlama (calls_30 bir kere)
    df_calls_30 = prepare_calls_30(df_calls, config=cfg_weekday)

    queues = ('kitle', 'kurumsal', 'gold')

    # 4) Haftaiçi blokları — v7 weekly
    for block in weekday_blocks:
        block_dates = [d.strftime('%Y-%m-%d') for d in block]
        block_label = f"{block_dates[0]} → {block_dates[-1]} ({len(block)} gün)"
        print(f"\n▶ Haftaiçi blok: {block_label}")

        try:
            week_results = run_week_all_queues(
                df_calls=df_calls,
                df_shifts_by_queue=df_shifts_dict,
                target_dates=block_dates,
                config=cfg_weekday,
                queues=queues,
                verbose=verbose,
            )
        except Exception as e:
            # Blok komple hata aldı — 5 gün de None
            print(f"  ✗ blok hatası: {e}")
            for d in block:
                results[d.strftime('%Y-%m-%d')] = None
            continue

        # Her gün için per-day dict oluştur
        for d in block:
            date_str = d.strftime('%Y-%m-%d')
            day_label = DAY_LABELS_EN[d.weekday()]   # 'Mon'..'Fri'
            day_name = DAY_LABELS_TR[d.weekday()]

            day_result = {}
            for queue, q_results in week_results.items():
                info = q_results.get('info_per_day', {}).get(day_label)
                if info is None:
                    continue
                day_result[queue] = _wrap_weekly_info_as_daily(
                    info, df_calls_30, queue, date_str)

            if not day_result:
                # Bu blokta hiçbir queue çözülmedi → None (consistent)
                results[date_str] = None
                print(f"  ⚠ {date_str} ({day_name}) — tüm queue'lar infeasible")
            else:
                results[date_str] = day_result
                feasible_qs = ','.join(day_result.keys())
                missing = set(queues) - set(day_result.keys())
                if missing:
                    print(f"  ✓ {date_str} ({day_name}) — OK: {feasible_qs}  "
                          f"| infeasible: {','.join(missing)}")
                else:
                    print(f"  ✓ {date_str} ({day_name}) — tamamı OK")

    # 5) Haftasonu günleri — v6 weekend daily
    weekend_days = [d for d in all_days if d.weekday() >= 5]
    if weekend_days:
        print(f"\n▶ Haftasonu günleri: {len(weekend_days)} gün")
    for d in weekend_days:
        date_str = d.strftime('%Y-%m-%d')
        day_name = DAY_LABELS_TR[d.weekday()]
        try:
            r = run_weekend_all(df_calls, df_actual, df_shifts_dict,
                                date_str, config=cfg_weekend)
            results[date_str] = r
            print(f"  ✓ {date_str} ({day_name}) — weekend")
        except Exception as e:
            print(f"  ✗ {date_str} ({day_name}) — weekend hatası: {e}")
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


# %% [HÜCRE 10] — Gün gün plan — KİTLE — özet metrikler
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


# %% [HÜCRE 11] — Gün gün vardiya planı — KİTLE — detaylı roster
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
