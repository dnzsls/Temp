# V9 Monthly Forecast — Model Rehberi

`monthly_run_v9_forecast.py` dosyasının pratik rehberi: nedir, ne yapar,
veri akışı, def'lerin işlevleri.

İlgili dosyalar:
- [monthly_run_v9_forecast.py](monthly_run_v9_forecast.py) — bu rehberin konusu
- [weekly_weekday_pipeline_forecast.py](weekly_weekday_pipeline_forecast.py) — haftaiçi MIP
- [weekend_forecast_final.py](weekend_forecast_final.py) — haftasonu MIP

---

## 1. Model nedir, ne amaçlar?

**Amaç:** Gelecek aya ait **çağrı tahminlerinden (forecast)** yola çıkarak,
her gün için optimal **vardiya planı + agent dağılımı** üret.

Çıktılar:
1. Her gün × her kuyruk için kaç inhouse / outsource agent
2. Hangi vardiyada kaç kişi
3. Eksik kalıyorsa nerede + ne kadar ek kadro gerekli
4. RR raporu (karşılama oranı), bütçe karşılaştırması
5. Aylık Excel raporu

**Girdiler:**
- Tahmin edilmiş çağrı sayıları (15 dk granularitede)
- AHT (alt-kuyruk × saat ortalama görüşme süresi)
- Vardiya tanımları (saat aralıkları, inhouse/outsource)
- Kapasite kısıtları (kadro tavanı), saat-bazlı maliyet, fallback ayarları

**Çekirdek mantık:** Erlang-C ile slot bazlı agent ihtiyacı hesabı → MIP (Mixed
Integer Programming) ile optimal vardiya × kişi dağılımı.

---

## 2. Yüksek seviye akış

```
┌──────────────┐  ┌────────────┐  ┌──────────────────────┐
│ df_forecast  │  │  df_aht    │  │  df_shifts_dict      │
│ (15dk, geniş │  │ (alt-kuyruk│  │ {kitle, gold,        │
│  format)     │  │  AHT'leri) │  │  kurumsal}           │
└──────┬───────┘  └─────┬──────┘  └──────────┬───────────┘
       │                │                    │
       │       ┌────────▼─────────┐          │
       │       │ load_aht_from_df │ ◀────────┘
       │       │  AHT'yi config'e │
       │       │  yerleştir       │
       │       └──────────────────┘
       │                │
       │       ┌────────▼─────────────┐
       │       │  CONFIG_WEEKDAY +    │
       │       │  CONFIG_WEEKEND      │  (sub_queues dolduruldu)
       │       └────────┬─────────────┘
       │                │
       ▼                ▼
┌──────────────────────────────────────────┐
│  run_month_forecast(year, month, ...)    │   ← TEK GİRİŞ NOKTASI
│                                          │
│  Ayın TÜM günlerini sırayla çözer:       │
│    • Haftaiçi (Pzt-Cum) → V9 weekly MIP  │
│    • Haftasonu (Cmt-Pzr) → forecast MIP  │
└────────────────────┬─────────────────────┘
                     │
                     ▼
        ┌────────────────────────┐
        │  results               │   ← {date_str: {queue: {...}}}
        │  (her gün × kuyruk     │
        │   için MIP çözümü)     │
        └────────┬───────────────┘
                 │
       ┌─────────┴──────────┬──────────────────┐
       ▼                    ▼                  ▼
  ┌─────────┐         ┌──────────┐        ┌──────────┐
  │ Bütçe   │         │  Plan    │        │  Excel   │
  │ kontrol │         │  özeti   │        │  export  │
  │(HÜCRE 8)│         │ (9-11)   │        │(HÜCRE 12)│
  └─────────┘         └──────────┘        └──────────┘
```

---

## 3. Hücreler ve görevleri

| Hücre | Görev |
|---|---|
| **1** | Import: V9 weekly + weekend forecast pipeline'ları |
| **2** | df_forecast, df_aht, df_shifts_dict'i yükle (sen doldur) |
| **3** | CONFIG_WEEKDAY tanımla (queue, mip, erlang, kadro, forecast_cols vs.) |
| **4** | CONFIG_WEEKEND tanımla |
| **5** | AHT'yi config'e yükle (sub_queues field'ı dolar) |
| **6** | `run_month_forecast` fonksiyonu tanımla |
| **7** | Ayı koştur, pickle cache'e kaydet |
| **8** | Haftasonu inhouse bütçe karşılaştırması (terminal çıktısı) |
| **9-11** | Kitle / Gold / Kurumsal aylık plan özeti (terminal) |
| **12** | Excel'e aktar (5 tip sheet) |

---

## 4. Def'ler — sırayla, ne giriyor, ne çıkıyor

### 4.1. Pipeline'a köprü def'leri (HÜCRE 6 içinde)

#### `_wrap_weekly_info_as_daily(info, df_calls_30, queue, date_str)`
**Amaç:** V9 weekly pipeline'ının dönen `info_per_day[day_label]` yapısını,
aylık `results` dict'inin beklediği gün-bazlı yapıya çevirir.

| Girdi | Açıklama |
|---|---|
| `info` | V9 weekly'den dönen `{assignments, mip_by_slot, total_shortfall, ...}` |
| `df_calls_30` | 30dk'ya çevrilmiş çağrı tablosu (calls_by_slot için) |
| `queue` | `'kitle'` / `'gold'` / `'kurumsal'` |
| `date_str` | `'2026-02-09'` |

**Çıktı:**
```python
{
    'mip_info': info,                    # MIP çözüm detayı
    'erlang_by_slot': {slot: need},      # slot bazlı Erlang ihtiyacı
    'calls_by_slot':  {slot: count},     # slot bazlı çağrı
    'actual': None,                       # forecast'ta gerçek yok
    'date': Timestamp,
    'queue': queue,
}
```

#### `_short_stage_note(solution_stage, total_shortfall_week=0)`
**Amaç:** V9 weekly'nin uzun stage adını kısa nota çevirir (rapor için).

| Girdi | Çıktı |
|---|---|
| `'STAGE 1: original'` | `'orijinal'` |
| `'STAGE 2 (per-day): Mon=-0.10'` | `'shrinkage Mon=-0.10'` |
| `'STAGE 4: coverage_shortfall'` | `'shortfall 47 kişi-slot'` |
| `None` | `'?'` |

#### `_run_weekend_silent(df_forecast, df_shifts_dict, date_str, config)`
**Amaç:** Haftasonu pipeline'ını stdout'u **yutarak** çağırır
(`run_all_queues_forecast` çok yazdırır; aylık run'da temiz çıktı için).

| Girdi | Açıklama |
|---|---|
| `df_forecast` | Forecast tablosu (15dk geniş format) |
| `df_shifts_dict` | Kuyruk → vardiya df'i |
| `date_str` | `'2026-02-07'` (Cmt) gibi tek gün |
| `config` | CONFIG_WEEKEND (forecast_cols + sub_queues dahil) |

**Çıktı:** `{queue: {date, mip_info, erlang_by_slot, calls_by_slot, ...}}`

### 4.2. Ana orkestratör

#### `run_month_forecast(year, month, df_forecast, df_shifts_dict, cfg_weekday, cfg_weekend, queues, verbose)`

**Amaç:** Ayın TÜM günlerini sırayla çözer — haftaiçi blokları + haftasonu
günleri. Aylık modelin **tek giriş noktası**.

**Akış:**

```
1. Ayın günlerini listele
2. Haftaiçi günleri ardışık bloklara böl (Pzt-Cum blokları)
3. df_forecast'i tek seferlik 30dk'ya çevir (prepare_forecast_calls_30)
4. Her haftaiçi blok için:
   - run_week_all_queues(df_forecast, block_dates, cfg_weekday, ...)
   - 3 kuyruk × 5 gün için V9 MIP'i çalıştırır
   - Her gün için sonucu _wrap_weekly_info_as_daily ile sarmala
   - results[date_str] = {queue: ...}
5. Her haftasonu günü için:
   - _run_weekend_silent(df_forecast, df_shifts_dict, date_str, cfg_weekend)
   - results[date_str] = {queue: ...}
6. Return results
```

| Girdi | Açıklama |
|---|---|
| `year, month` | Hangi ay (örn. 2026, 2) |
| `df_forecast` | 15dk forecast tablosu |
| `df_shifts_dict` | `{kitle, gold, kurumsal}` vardiya df'leri |
| `cfg_weekday` | CONFIG_WEEKDAY |
| `cfg_weekend` | CONFIG_WEEKEND |
| `queues` | Çözülecek kuyruklar (default 3'ü de) |
| `verbose` | True → tüm pipeline detaylarını bas; False → sadece özet |

**Çıktı:** `results = {date_str: {queue: {mip_info, ...}} | None}`
- Çözülmüş gün → dict
- Tüm kuyruklar başarısız → None

**Konsol çıktısı** (verbose=False):
```
▶ Haftaiçi blok: 2026-02-02 → 2026-02-06 (5 gün)
  ✓ 2026-02-02 (Pzt) — kitle: OK [orijinal] | kurumsal: OK [orijinal] | gold: OK [orijinal]
  ⚠ 2026-02-03 (Sal) — kitle: OK [shortfall 47 kişi-slot] | ...
  ...
▶ Haftasonu günleri: 8 gün
  ✓ 2026-02-07 (Cmt) — kitle: OK | kurumsal: OK | gold: OK
```

### 4.3. Plan özeti def'i (HÜCRE 9-11 kullanır)

#### `print_queue_monthly_plan(plan_queue, results, year, month)`

**Amaç:** Bir kuyruğun ay boyunca günlük metriklerini + vardiya rosterini
terminale basar.

| Girdi | Açıklama |
|---|---|
| `plan_queue` | `'kitle'` / `'gold'` / `'kurumsal'` |
| `results` | run_month_forecast çıktısı |
| `year, month` | Başlık için |

**Çıktı (terminal):**
1. **Tablo 1**: Tarih × Gün × (Çağrı, Erl_Pk, Erl_T, MIP_Pk, In, Out, PT, Toplam,
   Out%, Eksik, Çözüm)
2. **Tablo 2**: Her gün için açılan vardiyalar (saat, şirket, kişi sayısı)
   - Stage 4 çıktıysa +Öneri kolonu

### 4.4. Excel export — ana fonksiyon

#### `export_monthly_plan_to_excel(results, year, month, weekend_budget, cfg_weekday, cfg_weekend, queues, output_path)`

**Amaç:** Tüm aylık planı 1 Excel dosyasına çıkarır (~5 farklı sheet türü).

**Girdi:**
- `results` — run_month çıktısı
- `weekend_budget` — `{queue: int}` (örn. `{'kitle': 1200, ...}`)
- `cfg_weekday`, `cfg_weekend` — Kap_RR hesabı için (hourly_report config'i)

**Çıktı (dosya):** `vardiya_plani_forecast_YYYY_MM_AyAdı.xlsx`

**Sheet yapısı:**

| Sheet | İçerik |
|---|---|
| **1. Vardiya Planı** | 7 gün yan yana timetable, haftalar üst üste. Her gün 8 kolon: SHIFT, kitle inhouse, kitle outsource, gold, kurumsal, INH Total, OS Total, Total. Sağda PT bloğu (Kuyruk × Cmt/Pzr) |
| **2. Bütçe** | Haftasonu inhouse bütçe karşılaştırması (kuyruk × Cmt/Pzr günleri) |
| **3. Hafta 1, 4. Hafta 2, ...** | Hafta detayı: 3 kuyruk için MIP1/MIP2/Surplus/Eksik özeti + Surplus dağıtımı + Eksik kapsama + **Slot bazlı RR** |
| **Son: RR Raporu** | Aylık RR özeti: günlük Erl_Pk, MIP2_Pk, RR2 Avg/Min/Max, Kap_RR (3 kuyruk yan yana) |

### 4.5. Excel helper def'leri

#### `_compute_rr_metrics_for_day(r_queue, queue, cfg_weekday, cfg_weekend, is_weekend)`

**Amaç:** Bir gün × bir kuyruk için **slot-bazlı RR metrikleri** hesapla.

| Girdi | Açıklama |
|---|---|
| `r_queue` | `results[date_str][queue]` — tek gün tek kuyruk sonucu |
| `queue` | `'kitle'` vs. (config'ten hourly_report okuma için) |
| `cfg_weekday`, `cfg_weekend` | Kap_RR için config |
| `is_weekend` | True → weekend config'i kullan |

**Çıktı:** `(slot_rows, day_summary)`

`slot_rows` = aktif slotların listesi (Erlang > 0):
```python
[{slot, calls, erlang, mip1, mip2, rr1, rr2, nmt, ck, kap_rr}, ...]
```

`day_summary`:
```python
{
    'erl_pk': max Erlang,
    'mip2_pk': max MIP2,
    'rr2_at_peak': peak slot'taki RR2,
    'rr2_min': günün en kötü slot RR'i,
    'rr2_max': günün en bol slot RR'i,
    'rr2_avg': Erlang-ağırlıklı slot ortalaması = ΣMIP2/ΣErlang,
    'kap_rr_day': günlük kapasite RR = ΣÇağrı_Kapasitesi/ΣÇağrı,
    'total_calls': günlük çağrı toplamı,
    'total_ck': günlük çağrı kapasitesi toplamı,
}
```

**Kap_RR formülü** (her slot için):
```
RE = round(MIP × rapor_etkisi[saat])        # raporlamada harcanan
KK = round(MIP × kapasite_kaybi[saat])      # mola/eğitim
NMT = MIP - RE - KK                          # net müsait time
CK = NMT × (çağrı_adedi[saat] / 2)           # 30dk çağrı kapasitesi
Kap_RR = CK / çağrı
```

#### `_rr_color(rr2)`
**Amaç:** Excel hücresine RR değerine göre renk verir.
- `< 100%` → **kırmızı kalın** (eksik)
- `> 105%` → **mavi** (fazla)
- arası → **yeşil** (hedefte)

#### `_add_weekly_detail_sheet(wb, week_idx, week_dates, results, queues, ...)`
**Amaç:** Bir hafta için detay sheet'i (Hafta 1, Hafta 2, ...) oluştur.

Her kuyruk için (kitle → gold → kurumsal):
1. A — Günlük MIP1/MIP2/Surplus/Eksik tablosu
2. B — Surplus dağıtımı (varsa)
3. C — Eksik kapsama (varsa, Stage 4 çıktıysa)
4. D — **Slot bazlı RR tablosu**: Gün × Slot × Çağrı/Erlang/MIP1/MIP2/RR1/RR2/Kap_RR
   - Her günün altında ÖZET satırı (avg/min/max RR2 + Kap_RR)

#### `_add_rr_report_sheet(wb, results, queues, all_dates, ...)`
**Amaç:** Aylık RR özet sheet'i. Her gün × her kuyruk için 6 metrik:

| Kolon | Anlamı |
|---|---|
| `Erl_Pk` | Günün peak Erlang ihtiyacı |
| `MIP2_Pk` | Günün peak MIP2 |
| `RR2 Avg` | Erlang-ağırlıklı slot RR ortalaması |
| `RR2 Min` | En kötü slot RR (worst case) |
| `RR2 Max` | En iyi slot RR |
| `Kap_RR` | Günlük kapasite RR |

Aylık özet satırı: Erlang-ağırlıklı `RR2 Avg`, ay boyu görülen `RR2 Min/Max`,
çağrı-ağırlıklı `Kap_RR`.

---

## 5. Önemli veri yapıları

### 5.1. `df_forecast` (Forecast — HÜCRE 2)

15 dakikalık granularitede, geniş format:

| Kolon | Örnek değer |
|---|---|
| `model_data_date` (datetime) | `'09.02.2026 09:15:00'` |
| `truncddate` (date) | `'09.02.2026'` |
| `KITLE_NOF_CALL` | 47 |
| `KURUMSAL_NOF_CALL` | 12 |
| `GOLD_NOF_CALL` | 3 |
| `{sub_queue}_NOF_CALL` | (opsiyonel alt-kuyruk dağılımı) |

Kolon adlarını `config['forecast_cols']` ile pipeline'a tanıtırsın:
```python
'forecast_cols': {
    'datetime':       'model_data_date',
    'date':           'truncddate',
    'kitle_total':    'KITLE_NOF_CALL',
    'kurumsal_total': 'KURUMSAL_NOF_CALL',
    'gold_total':     'GOLD_NOF_CALL',
}
```

### 5.2. `df_aht`

| Kolon |
|---|
| `saat` (0-23) |
| `sub_queue` |
| `line_based_main_group` |
| `weighted_avg_aht` (saniye) |

`load_aht_from_df()` bunu `config['sub_queues'][queue]['aht']` altına dönüştürür.

### 5.3. `df_shifts_dict`

```python
{
    'kitle':    pd.DataFrame,    # vardiya bilgisi
    'gold':     pd.DataFrame,
    'kurumsal': pd.DataFrame,
}
```

Her df'in kolonları: `shift`, `start`, `end`, `company` (`inhouse`/`outsource`/`part_time`),
opsiyonel `available_days` (örn. `['Fri']`).

### 5.4. `results` (run_month_forecast çıktısı)

```python
results = {
    '2026-02-02': {
        'kitle': {
            'mip_info': {
                'assignments': {shift_key: count},        # vardiya → kişi
                'shift_coverage': {shift_key: info},      # vardiya saat/şirket
                'mip_by_slot': {slot: count},             # MIP2 (surplus sonrası)
                'mip_in_by_slot': {slot: count},
                'mip_out_by_slot': {slot: count},
                'mip_info_stage1': {...},                 # SURPLUS ÖNCESİ snapshot
                'surplus_added': {shift_key: count},      # vardiyaya eklenen
                'erlang_by_slot': {slot: need},
                'total_kisi': N,
                'total_inhouse_kisi': N,
                'total_outsource_kisi': N,
                'total_shortfall': N,                     # Stage 4 eksik
                'shortfall_by_slot': {slot: count},
                'shortfall_recommendations': {shift: +N}, # öneri
                'solution_stage': 'STAGE 1: original',
                ...
            },
            'erlang_by_slot': {...},   # top-level kopya
            'calls_by_slot':  {...},
            'actual': None,             # forecast'ta gerçek yok
            'date': Timestamp,
            'queue': 'kitle',
        },
        'gold': {...},
        'kurumsal': {...},
    },
    '2026-02-03': {...},
    ...
}
```

Bir gün **tamamen başarısız** olduysa: `results[date_str] = None`.

### 5.5. CONFIG (Weekday/Weekend) — kritik alanlar

```python
{
    'queues': {kitle, kurumsal, gold},
    'forecast_cols': {...},
    'sub_queues': {...},                # load_aht_from_df ile dolar
    'queue_configs': {
        kitle: {
            'erlang': {target_asa, shrinkage, ...},
            'mip': {
                'min_per_shift': 13,
                'weekly_shrinkage_fallback': {enabled, step, ...},
                'coverage_shortfall': {enabled: True, penalty: 1000.0},
                ...
            },
            'rr_penalty': {...},
            'slot_cap': {...},
            'hourly_report': {                 # Kap_RR için kritik
                'rapor_etkisi': {saat: oran},
                'kapasite_kaybi': {saat: oran},
                'cagri_adedi':   {saat: int},
            },
        },
        ...
    },
    'surplus_distribution': {
        'enabled': True,
        'total_kadro': {kitle: {inhouse, outsource}, ...},  # per-day dict de olabilir
        'windows': [{name, start, end, ratio}, ...],
    },
}
```

---

## 6. Excel çıktısı — özet

`vardiya_plani_forecast_YYYY_MM_AyAdı.xlsx` aşağıdaki sheet'leri içerir:

| Sheet | Amaç | Layout |
|---|---|---|
| **Vardiya Planı** | Operasyon haftalık görünüm | 7 gün yan yana, kuyruk bazlı kişi sayıları |
| **Bütçe** | Haftasonu inhouse hedef vs. gerçekleşen | Kuyruk × Cmt/Pzr matris |
| **Hafta 1, Hafta 2, ...** | Hafta detayı (3 kuyruk) | MIP1/MIP2 + Surplus + Eksik + Slot bazlı RR |
| **RR Raporu** | Aylık karşılama oranı | Günlük Erl_Pk, RR2 Avg/Min/Max, Kap_RR (3 kuyruk yan yana) |

---

## 7. Hata durumları

| Durum | Sebep | Çözüm |
|---|---|---|
| `Cache'ten yüklendi: 28 gün` | `monthly_v9_forecast_YYYY_MM.pkl` mevcut | Yeniden koşturmak için `os.remove(CACHE_FILE)` |
| `KeyError: 'forecast_datetime'` | CONFIG'de `forecast_cols.datetime` df_forecast'taki kolon adıyla eşleşmiyor | Doğru kolon adını yaz |
| Tüm haftaiçi günlerde `INFEASIBLE` | V9 fallback'leri (Stage 1-2-4) bile çözemedi | `verbose=True` ile koş, hangi aşamada bittiğini gör |
| RR raporda 0 değerleri | `mip_info` içinde `erlang_by_slot` yok (eski cache); helper top-level'a fallback yapar | Cache silip yeniden koştur |
| `Sheet 'RR Raporu'` Kap_RR 0% | `cfg_weekday` / `cfg_weekend` HÜCRE 12 çağrısında geçilmemiş | Geçtiğinden emin ol |

---

## 8. İş akışı — adım adım koştur

1. **HÜCRE 1** — import (1 kere)
2. **HÜCRE 2** — `df_forecast`, `df_aht`, `df_shifts_dict`'i SQL/Excel'den çek
3. **HÜCRE 3-4** — CONFIG_WEEKDAY ve CONFIG_WEEKEND tanımla
   (`forecast_cols`'ı df_forecast kolon adlarına göre düzenle)
4. **HÜCRE 5** — AHT'yi config'e yükle
5. **HÜCRE 6** — `run_month_forecast` fonksiyonu yüklenir (otomatik)
6. **HÜCRE 7** — Aylık çalıştır
   - Cache yoksa: 5-15 dk sürer (kuyruğa ve fallback derinliğine göre)
   - Cache varsa: hemen yüklenir
7. **HÜCRE 8** — Bütçe kontrolü terminalde
8. **HÜCRE 9-11** — Plan özetleri (kitle, gold, kurumsal)
9. **HÜCRE 12** — Excel'e aktarım, çalışma dizinine `.xlsx` çıkar

---

## 9. İlişkili dosyalar

| Dosya | Görevi |
|---|---|
| [monthly_run_v9_forecast.py](monthly_run_v9_forecast.py) | Bu doc'un konusu — aylık orkestrasyon |
| [weekly_weekday_pipeline_forecast.py](weekly_weekday_pipeline_forecast.py) | Haftaiçi V9 MIP (Stage 4 dahil) |
| [weekend_forecast_final.py](weekend_forecast_final.py) | Haftasonu forecast MIP |

V9 weekday MIP iç işleyişi için ayrıca: [V9 weekday daha derin matematik
referansı için actual_pipeline_v9_weekly](actual_pipeline_v9_weekly.py)
incelenebilir.
