# V9 MONTHLY FORECAST — Model Rehberi

`monthly_run_v9_forecast.py` için kapsamlı rehber.

İçindekiler:
1. Problem Tanımı
2. Veri Akışı (Yüksek Seviye)
3. MIP Modeli
4. Cascading Fallback (Stage 1-4)
5. Def'ler ve İşlevleri
6. Veri Yapıları
7. Hücre Akışı
8. Excel Çıktısı
9. Hata Durumları

---

# 1. PROBLEM TANIMI

Çağrı merkezi için **aylık vardiya planlaması** yapılır. Girdi: gelecek aya ait
çağrı tahmini. Amaç:

- Her gün × her 30dk slot için Erlang-C'den hesaplanan agent ihtiyacını
  karşılamak
- Toplam maliyeti minimize etmek (saat ve şirket türüne göre farklı maliyet)
- Kadro tavanını aşmamak (haftaiçi 380 inhouse / 450 outsource gibi)
- Stable inhouse roster'ı korumak (Pzt-Cum aynı kişi sayısı)
- Outsource ekibinin gün gün esnek olmasına izin vermek
- Erlang yetmediği durumlarda eksik kapsamayı raporlamak (Stage 4)

---

# 2. VERİ AKIŞI (YÜKSEK SEVİYE)

```
ham_girdiler:
   df_forecast      (15dk geniş format, KITLE_NOF_CALL, ...)
   df_aht           (saat × alt-kuyruk → AHT)
   df_shifts_dict   (kuyruk → vardiya tanımları)
   CONFIG           (kuyruk başı parametre seti)
        │
        ▼
   prepare_forecast_calls_30()      ───►  df_calls_30 (internal format)
        │
        ▼
   calculate_erlang_all()           ───►  erlang_by_slot_per_day
        │                                  {day_label: {slot: ihtiyaç}}
        ▼
   optimize_week()                  ───►  MIP çöz, atamalar al
        │
        ▼
   run_week_all_queues()            ───►  4 aşamalı fallback ile
        │                                  haftayı çöz (3 kuyruk × 5 gün)
        ▼
   run_month_forecast()             ───►  ayın tüm haftaları + haftasonu
        │
        ▼
   results = {date_str: {queue: çözüm}}
        │
        ├──► HÜCRE 8: Bütçe kontrolü (terminal)
        ├──► HÜCRE 9-11: Plan özeti (terminal)
        └──► HÜCRE 12: Excel raporu
```

---

# 3. MIP MODELİ

V9 haftaiçi MIP modeli `optimize_week()` içinde kurulur. 5 günlük blok için
tek modelde çözülür.

## 3.1 Karar Değişkenleri

### Stable Inhouse (haftanın 5 günü aynı kişi)

```
x[s]   ∈ {0, 1, 2, ...}    Integer, lowBound=0
y[s]   ∈ {0, 1}            Binary (vardiya açık mı?)

s ∈ stable_shifts = INHOUSE + her gün aktif olan vardiyalar
```

Stable: aynı Pzt günü 13 kişi açtıysan, Cuma günü de aynı 13 kişi (V7'den
beri stable staffing prensibi).

### Day-Specific (her gün ayrı)

```
x_day[(s, d)] ∈ {0, 1, 2, ...}    Integer, lowBound=0
y_day[(s, d)] ∈ {0, 1}            Binary

(s, d) ∈ day_shift_pairs = OUTSOURCE × {Pzt..Cum}
                           ∪ Gün-kısıtlı inhouse (örn. `_fri` vardiyası)
```

Day-specific: outsource ekibinin günlük kapasitesi farklı olabilir
(Pzt 50 kişi, Sal 35 kişi gibi).

### Slack / Penalty Değişkenleri (Continuous, ≥ 0)

```
excess[(d, slot)]         RR penalty (Erlang üstüne çıkma)
sc_excess[(d, slot)]      Slot cap penalty (tavan aşma)
bp_diff_pos/neg[(d, win)] Balance penalty (in/out denge)
shortfall[(d, slot)]      Stage 4 — eksik kapsama
```

---

## 3.2 Amaç Fonksiyonu

**Toplam maliyet + tüm penalty'lerin toplamını minimize et:**

```
MINIMIZE Z = Σ_s x[s] × cost(s) × n_days              ← stable cost (×5 gün)
           + Σ_(s,d) x_day[(s,d)] × cost(s)           ← day-specific cost
           + Σ_(d,slot) excess × rr_penalty            ← Erlang fazlalık
           + Σ_(d,slot) sc_excess × sc_penalty         ← slot cap aşımı
           + Σ_(d,win) (diff_pos + diff_neg) × bp_pen  ← in/out denge
           + Σ_(d,slot) shortfall × 1000               ← Stage 4 (V9 YENİ)
```

**cost(s)** formülü:
```
cost(s) = base_cost(company) × time_multiplier(start_hour)

base_cost('inhouse')   = mcfg['cost_inhouse']     (örn. 1.0)
base_cost('outsource') = mcfg['cost_outsource']   (örn. 1.0)
time_multiplier        = config['time_cost_multipliers'][queue][company][start_hour]
                          (varsayılan 1.0; örn. 07:00 inhouse = 25.0 → erken
                           saat tercih edilmesin)
```

**Stable cost neden n_days ile çarpılıyor?** Stable inhouse haftanın 5 günü
çalışır ama tek `x[s]` değişkeni var. Day-specific her gün için ayrı
maliyet eklenir. Eşitlemezsen MIP yanlışlıkla inhouse'u 5 kat ucuz görür.

---

## 3.3 Kısıtlar

### K1 — Coverage (Erlang Karşıla)

Her gün × her aktif slot için, o slot'u kapsayan vardiyaların toplamı Erlang
ihtiyacını karşılamalı:

```
Σ_(s ∈ stable, slot ∈ s.slots) x[s]
  + Σ_((s,d) ∈ day_pairs, d=day_label, slot ∈ s.slots) x_day[(s,d)]
  + shortfall[(d, slot)]                              ← Stage 4 açıksa
  ≥ erlang_need[day_label][slot]
```

Stage 4 KAPALI olduğunda `shortfall` yok, kısıt sert (hard).
Stage 4 AÇIK olduğunda `shortfall` ≥ 0 serbest değişken — MIP eksik bırakabilir
ama her birim 1000 ceza yer.

### K2 — min_per_shift (Vardiya Açıksa Min Kişi)

Big-M tekniği ile `y[s]` ve `x[s]` birbirine bağlanır:

```
# Stable shift'ler
x[s] ≤ M × y[s]              (M = 500 yeterince büyük)
x[s] ≥ min_v × y[s]          (vardiya açıksa min N kişi, V9'da N=13)

# Day-specific shift'ler
x_day[(s,d)] ≤ M × y_day[(s,d)]
x_day[(s,d)] ≥ min_v × y_day[(s,d)]
```

`min_v` saat-özel istisna olabilir (`min_per_shift_overrides`).

### K3 — Kadro Tavanı (Her Gün)

**Inhouse kadrosu** (stable + day-specific inhouse):
```
∀ d ∈ {Pzt..Cum}:
  Σ_(s ∈ stable) x[s]
    + Σ_((s,d) ∈ day_pairs, s.company='inhouse') x_day[(s,d)]
    ≤ kadro_in_d
```

**Outsource kadrosu**:
```
∀ d ∈ {Pzt..Cum}:
  Σ_((s,d) ∈ day_pairs, s.company='outsource') x_day[(s,d)]
    ≤ kadro_out_d
```

`kadro_in_d` ve `kadro_out_d` per-day çözümlenir (V9'da 4 katmanlı):
1. Belirli tarih (`'2026-02-09': 400`) varsa onu kullan
2. Yoksa hafta_N (`'hafta_2': 410`) varsa onu kullan
3. Yoksa gün-of-week (`'Mon': 380`) varsa onu kullan
4. Yoksa `'default'` değerini kullan

**hafta_N tanımı:** Ay sınırına saygılı, Pzt başlangıçlı. Ayın 1'i hangi gün
düşerse hafta_1 oradan başlar; bir sonraki Pzt → hafta_2.

```
Şubat 2026 örneği (02-01 = Pzr):
  hafta_1: 02-01            (sadece o tek gün)
  hafta_2: 02-02 → 02-08
  hafta_3: 02-09 → 02-15
  hafta_4: 02-16 → 02-22
  hafta_5: 02-23 → 02-28
```

```
Hafta hafta giriş örneği:
'kitle': {
    'inhouse': {
        'hafta_1': 400,    # 1. hafta
        'hafta_2': 410,    # 2. hafta
        'hafta_3': 405,
        'hafta_4': 400,
        'default': 380,    # belirtilmeyen haftalar
    },
    'outsource': {
        'hafta_1': 390,
        'hafta_2': 400,
        'default': 450,
    }
}
```

Pzt için 400 verirsen, Sal için 380 alırsen: stable inhouse en kısıtlı günü
(380) çözer, Pzt'ye 20 kişi day-specific inhouse eklenebilir.

### K4 — Alt-Kuyruk Min (Opsiyonel)

`inhouse_only_subqueues` config'te tanımlıysa, belirli slotlarda min inhouse
kapsama zorunlu:

```
Σ_(inhouse stable + day_specific kapsayan) ≥ inhouse_min[d][slot]
Σ_(outsource ... ) ≥ outsource_min[d][slot]
```

Örnek: `karttemelbankaclik` alt-kuyruğunun çağrılarının en az %20'sini
inhouse karşılamak zorunda → ilgili slotlarda inhouse min hesaplanır.

### K5 — RR Penalty (Soft)

Her aktif slot için Erlang üstüne çıkma cezası:

```
excess[(d, slot)] ≥ covered_slot - erlang_need

cost += excess × rr_penalty_per
```

Peak slot'ta `peak_penalty`, gece slot'ta `night_multiplier` ile çarpılır.

### K6 — Slot Cap Penalty (Soft)

`slot_cap.bands` tanımlıysa, saat bantlarına göre `max_ratio × erlang`
tavanı aşılırsa ceza:

```
cap = ceil(erlang × max_ratio)
sc_excess[(d, slot)] ≥ covered_slot - cap

cost += sc_excess × band_penalty
```

### K7 — Balance Penalty (Soft)

Pencere bazlı in/out dengesi (örn. sabah 07:00-12:00):

```
diff_pos - diff_neg = in_total - out_total       (window içinde)

cost += (diff_pos + diff_neg) × balance_penalty
```

---

# 4. CASCADING FALLBACK (Stage 1-4)

`run_week_all_queues` bir kuyruğu şu sırayla dener. İlk çözen aşamada durur.

## Aşama 1 — Orijinal config

Config'in olduğu hali ile MIP'i çağır. Erlang config'teki shrinkage ile
hesaplanır, min_per_shift=13 ile.

```python
stable, day_specific, info = optimize_week(
    erlang_by_slot_per_day=_build_erlang_per_day(...),
    min_per_shift_override=None,
    enable_coverage_shortfall=False,
)
```

Çözerse: `solution_stage = 'STAGE 1: original'`.

## Aşama 2 — Per-Day Shrinkage Azaltma

Stage 1 INFEASIBLE → en yoğun günden başlayarak shrinkage'ı kademeli azalt.

```
1. days_by_calls sırala (çok çağrılan gün önce, örn. Pzt > Per > Cum > Sal > Çar)
2. for target_day in days_by_calls:
     while infeasible and decrements_per_day[target_day] < max_shr:
       decrements_per_day[target_day] += step    (örn. +0.10)
       Erlang'ı bu günün için decrement uygulayarak yeniden hesapla
       _trial()  → MIP'i dene
3. floor'a (0) inerse, sıradaki güne geç
```

Çözerse: `'STAGE 2 (per-day): Mon=-0.10, Thu=-0.05'`.

## Aşama 3 — min_per_shift Azaltma

V9'da `'weekly_min_per_shift_fallback': {'enabled': False}` → **bu aşama
ATLANIR**. min_per_shift=13 sert kısıt; düşürülmez.

## Aşama 4 — Coverage Shortfall (V9 YENİ)

Stage 1-3 hâlâ INFEASIBLE → coverage kısıtını yumuşat.

```python
# Her slot için soft constraint:
covered_slot + shortfall_slot ≥ erlang_need

# Amaç fonksiyonuna ekstra terim:
+ Σ shortfall_slot × 1000          # yüksek penalty
```

MIP iki seçenek arasında karar verir:
- Daha çok kişi atamak (kadro tavanı izin veriyorsa, maliyet ~1)
- Eksik bırakmak (her birim 1000 birim ceza)

Kadro tavanına takıldığı için kişi ekleyemiyorsa MIP **mecburen** shortfall
kullanır. Bu yüzden Stage 4 **HER ZAMAN çözer** (matematik garantisi).

Çıktı:
```python
info['shortfall_by_slot'] = {'10:00': 8, '10:30': 12, ...}
info['total_shortfall'] = 47   # toplam kişi-slot
info['shortfall_recommendations'] = {
    '09:00-18:00_inhouse': 5,   # bu vardiyaya 5 kişi ek
    '10:00-19:00_inhouse': 3,
}
```

`shortfall_recommendations` greedy heuristic: hangi vardiyaya kaç kişi
eklersen eksiği kapatırsın hesabı.

---

# 5. DEF'LER VE İŞLEVLERİ

## 5.1 Köprü Def'leri (HÜCRE 6 içinde)

### `_wrap_weekly_info_as_daily(info, df_calls_30, queue, date_str)`

V9 weekly'nin `info_per_day[day_label]` çıktısını aylık results'un beklediği
gün-bazlı yapıya çevirir.

**Girdi:**
```python
info = {                          # optimize_week'ten dönen
    'assignments': {shift: count},
    'mip_by_slot': {slot: count},
    'erlang_by_slot': {slot: need},
    'total_shortfall': N,
    ...
}
```

**Çıktı:**
```python
{
    'mip_info': info,             # olduğu gibi
    'erlang_by_slot': {...},      # top-level kopya
    'calls_by_slot': {...},       # df_calls_30'dan
    'actual': None,
    'date': Timestamp,
    'queue': 'kitle',
}
```

### `_short_stage_note(solution_stage, total_shortfall_week=0)`

Solution stage string'ini kısa nota çevirir.

| Girdi | Çıktı |
|-------|-------|
| `'STAGE 1: original'` | `'orijinal'` |
| `'STAGE 2 (per-day): Mon=-0.10'` | `'shrinkage Mon=-0.10'` |
| `'STAGE 4: coverage_shortfall'` | `'shortfall 47 kişi-slot'` |
| `None` | `'?'` |

### `_run_weekend_silent(df_forecast, df_shifts_dict, date_str, config)`

Haftasonu pipeline'ını stdout'u yutarak çağırır. `run_all_queues_forecast`
çok verbose; aylık run'da temiz çıktı için sessiz çalıştırılır.

**Çıktı:** Haftasonu MIP sonucu — `{queue: {mip_info, erlang_by_slot, ...}}`.

---

## 5.2 Ana Orkestratör

### `run_month_forecast(year, month, df_forecast, df_shifts_dict, cfg_weekday, cfg_weekend, queues, verbose)`

Ayın TÜM günlerini sırayla çözer. Tek giriş noktası.

**Akış:**

```
1. Ayın gün listesini çıkar
2. Haftaiçi günleri ardışık bloklara böl (Pzt-Cum blokları)
3. df_forecast → df_calls_30 (1 kere)
4. Her haftaiçi blok için:
   a. run_week_all_queues(...) çağır
   b. Her gün × kuyruk için sonucu sarmala
   c. results[date_str][queue] = wrapped
5. Her haftasonu günü için:
   a. _run_weekend_silent(...) çağır
   b. results[date_str] = r  (zaten queue dict)
6. Return results
```

**Konsol çıktısı** (verbose=False):
```
▶ Haftaiçi blok: 2026-02-02 → 2026-02-06 (5 gün)
  ✓ 2026-02-02 (Pzt) — kitle: OK [orijinal] | kurumsal: OK [orijinal] | gold: OK [orijinal]
  ⚠ 2026-02-03 (Sal) — kitle: OK [shortfall 47 kişi-slot] | ...
▶ Haftasonu günleri: 8 gün
  ✓ 2026-02-07 (Cmt) — kitle: OK | kurumsal: OK | gold: OK
```

---

## 5.3 Plan Özeti (HÜCRE 9-11 kullanır)

### `print_queue_monthly_plan(plan_queue, results, year, month)`

Bir kuyruğun ay boyunca günlük metriklerini + vardiya rosterini terminale
basar.

İki bölüm çıkarır:
1. Günlük özet tablosu (Tarih × Çağrı, Erl_Pk, MIP_Pk, In, Out, Eksik, Çözüm)
2. Her gün için açılan vardiyaların listesi

---

## 5.4 Excel Export

### `export_monthly_plan_to_excel(results, year, month, weekend_budget, cfg_weekday, cfg_weekend, queues, output_path)`

Tüm aylık planı 1 Excel dosyasına çıkarır.

**Çıktı dosya adı:** `vardiya_plani_forecast_YYYY_MM_AyAdı.xlsx`

**Sheet'ler:**

| Sheet | İçerik |
|-------|--------|
| Vardiya Planı | 7 gün yan yana timetable, haftalar üst üste |
| Bütçe | Haftasonu inhouse bütçe karşılaştırması |
| Hafta 1, 2, ... | Hafta detayı (3 kuyruk için MIP1/MIP2/Eksik/Slot RR) |
| RR Raporu | Aylık RR özeti (günlük min/max/avg + Kap_RR) |

---

## 5.5 Excel Helper Def'leri

### `_compute_rr_metrics_for_day(r_queue, queue, cfg_weekday, cfg_weekend, is_weekend)`

Bir gün × bir kuyruk için slot-bazlı RR metrikleri.

**Çıktı:** `(slot_rows, day_summary)`

`slot_rows` — aktif slotlar listesi:
```python
[
    {
        'slot': '09:00',
        'calls': 142,
        'erlang': 95,
        'mip1': 90, 'mip2': 95,
        'rr1': 0.947, 'rr2': 1.000,
        'nmt': 78, 'ck': 585,
        'kap_rr': 4.12
    },
    ...
]
```

`day_summary`:
```python
{
    'erl_pk': 100,                # peak Erlang
    'mip2_pk': 105,
    'rr2_at_peak': 1.05,
    'rr2_min': 0.85,              # günün en kötü slot RR'i
    'rr2_max': 1.30,
    'rr2_avg': 0.98,              # Erlang-ağırlıklı = ΣMIP/ΣErlang
    'kap_rr_day': 0.95,           # kapasite RR (çağrı bazlı)
    'total_calls': 1234,
    'total_ck': 5870
}
```

**Kap_RR formülü** (slot bazlı):
```
RE = round(MIP × rapor_etkisi[saat])      # raporlamada harcanan
KK = round(MIP × kapasite_kaybi[saat])    # mola/eğitim
NMT = MIP - RE - KK                        # net müsait agent
CK = NMT × (çağrı_adedi[saat] / 2)         # 30dk çağrı kapasitesi
Kap_RR = CK / çağrı
```

### `_rr_color(rr2)`

RR2 değerine göre Excel hücre rengi:
- `< 100%` → kırmızı kalın (eksik)
- `> 105%` → mavi (fazla)
- arası → yeşil (hedefte)

### `_add_weekly_detail_sheet(...)`

Bir hafta için detay sheet'i (Hafta 1, Hafta 2, ...) oluşturur. Her kuyruk
için 4 bölüm:

1. A — Günlük MIP1/MIP2/Surplus/Eksik tablosu
2. B — Surplus dağıtımı (varsa)
3. C — Eksik kapsama (Stage 4 çıktıysa)
4. D — Slot bazlı RR tablosu (her aktif slot için RR1/RR2/Kap_RR)

### `_add_rr_report_sheet(...)`

Aylık RR özet sheet'i. Her gün × her kuyruk için 6 kolon:
`Erl_Pk | MIP2_Pk | RR2 Avg | RR2 Min | RR2 Max | Kap_RR`

Aylık özet satırı: Erlang-ağırlıklı `RR2 Avg`, ay boyu görülen `RR2 Min/Max`,
çağrı-ağırlıklı `Kap_RR`.

---

# 6. VERİ YAPILARI

## 6.1 df_forecast (Girdi)

15 dakikalık granularitede, geniş format.

```
Kolon                       Örnek
─────────────────────────────────────────────
model_data_date (datetime)  '09.02.2026 09:15:00'
truncddate (date)           '09.02.2026'
KITLE_NOF_CALL              47
KURUMSAL_NOF_CALL           12
GOLD_NOF_CALL               3
{sub_queue}_NOF_CALL        (opsiyonel — alt-kuyruk dağılımı)
```

CONFIG'de kolon adları tanıtılır:
```python
'forecast_cols': {
    'datetime':       'model_data_date',
    'date':           'truncddate',
    'kitle_total':    'KITLE_NOF_CALL',
    'kurumsal_total': 'KURUMSAL_NOF_CALL',
    'gold_total':     'GOLD_NOF_CALL',
}
```

## 6.2 df_aht (Girdi)

```
Kolon                       Örnek
─────────────────────────────────────────────
saat                        9        (0-23)
sub_queue                   karttemelbankaclik
line_based_main_group       kitle_cagrilar
weighted_avg_aht            157      (saniye)
```

## 6.3 df_shifts_dict (Girdi)

```python
{
    'kitle':    pd.DataFrame,    # kitle vardiyaları
    'gold':     pd.DataFrame,
    'kurumsal': pd.DataFrame,
}
```

Her df'in kolonları:

```
Kolon              Örnek değer        Açıklama
──────────────────────────────────────────────────────────
shift              '08:00-17:00'      Vardiya adı
start              '08:00'            Başlangıç
end                '17:00'            Bitiş
company            'inhouse'          inhouse/outsource/part_time
available_days     ['Fri']            (opsiyonel, hangi günler)
```

## 6.4 CONFIG — Kritik Alanlar

```python
{
    'queues': {
        'kitle':    {'companies': ['inhouse', 'outsource']},
        'kurumsal': {'companies': ['inhouse']},
        'gold':     {'companies': ['inhouse']},
    },
    'forecast_cols': {...},
    'sub_queues': {...},          # load_aht_from_df ile dolar
    'queue_configs': {
        'kitle': {
            'erlang': {
                'target_asa': 30,
                'shrinkage': {0: 0.07, ...} or 0.10,
                'interval_minutes': 30,
            },
            'mip': {
                'cost_inhouse': 1.0,
                'cost_outsource': 1.0,
                'min_per_shift': 13,
                'weekly_shrinkage_fallback': {
                    'enabled': True, 'step': 0.10, 'floor': 0.0,
                    'per_day': True,
                },
                'weekly_min_per_shift_fallback': {'enabled': False},
                'coverage_shortfall': {
                    'enabled': True, 'penalty': 1000.0,
                },
            },
            'rr_penalty': {...},
            'slot_cap': {...},
            'balance_penalty': {...},
            'hourly_report': {                    # Kap_RR için
                'rapor_etkisi':  {saat: oran},
                'kapasite_kaybi':{saat: oran},
                'cagri_adedi':   {saat: int},
            },
        },
        ...
    },
    'surplus_distribution': {
        'enabled': True,
        'total_kadro': {
            'kitle': {
                'inhouse':  380,           # int VEYA dict
                'outsource': 450,
            },
            'gold':     {'inhouse': 130},
            'kurumsal': {'inhouse': 47},
        },
        'windows': [
            {'name': 'sabah', 'start': '09:00', 'end': '11:00', 'ratio': 2/3},
            {'name': 'aksam', 'start': '11:00', 'end': '20:00', 'ratio': 1/3},
        ],
    },
}
```

**Per-day kadro örneği:**
```python
'total_kadro': {
    'kitle': {
        'inhouse': 380,                # tüm günlerde sabit
        'outsource': {                  # gün gün değişken
            '2026-02-02': 470,         # belirli tarih
            'Mon':        460,         # gün-of-week fallback
            'default':    450,         # belirtilmeyen günler
        }
    }
}
```

Çözümleme önceliği: **tarih > gün-of-week > default**.

## 6.5 results (Çıktı)

```python
results = {
    '2026-02-02': {
        'kitle': {
            'mip_info': {
                'assignments': {shift_key: count},
                'shift_coverage': {shift_key: info},
                'mip_by_slot':     {slot: count},  # MIP2 (surplus sonrası)
                'mip_in_by_slot':  {slot: count},
                'mip_out_by_slot': {slot: count},
                'mip_info_stage1': {...},          # MIP1 snapshot (surplus öncesi)
                'surplus_added':   {shift: N},
                'erlang_by_slot':  {slot: need},
                'total_kisi':           N,
                'total_inhouse_kisi':   N,
                'total_outsource_kisi': N,
                'total_shortfall':      N,
                'shortfall_by_slot':    {slot: count},
                'shortfall_recommendations': {shift: +N},
                'solution_stage':  'STAGE 1: original',
            },
            'erlang_by_slot': {...},
            'calls_by_slot':  {...},
            'actual': None,
            'date': Timestamp,
            'queue': 'kitle',
        },
        'gold':     {...},
        'kurumsal': {...},
    },
    '2026-02-03': {...},
    ...
}
```

Bir gün **tamamen başarısız** olduysa: `results[date_str] = None`.

---

# 7. HÜCRE AKIŞI

```
HÜCRE 1   importlar
            ↓
HÜCRE 2   df_forecast, df_aht, df_shifts_dict çek (SQL / Excel)
            ↓
HÜCRE 3   CONFIG_WEEKDAY tanımla
            ↓
HÜCRE 4   CONFIG_WEEKEND tanımla
            ↓
HÜCRE 5   load_aht_from_df() ile sub_queues doldur
            ↓
HÜCRE 6   run_month_forecast fonksiyonu yüklenir (otomatik)
            ↓
HÜCRE 7   results = run_month_forecast(...)
            • Cache yoksa çalıştır + pkl'ye yaz
            • Cache varsa pkl'den oku
            ↓
HÜCRE 8   Bütçe kontrolü terminale yazdır
            ↓
HÜCRE 9   print_queue_monthly_plan('kitle', ...)
HÜCRE 10  print_queue_monthly_plan('gold', ...)
HÜCRE 11  print_queue_monthly_plan('kurumsal', ...)
            ↓
HÜCRE 12  export_monthly_plan_to_excel(...)
            → vardiya_plani_forecast_YYYY_MM_AyAdı.xlsx
```

---

# 8. EXCEL ÇIKTISI

`vardiya_plani_forecast_YYYY_MM_AyAdı.xlsx` aşağıdaki sheet'leri içerir.

## Sheet 1 — Vardiya Planı

7 gün yan yana timetable, haftalar üst üste. Her gün için 8 kolon:

```
SHIFT  |  kitle inh  |  kitle out  |  gold  |  kurumsal  |  INH Total  |  OS Total  |  Total
```

Sağda PT bölümü: `SHIFT | Kuyruk | Cmt | Pzr` (sadece haftasonu PT için).

## Sheet 2 — Bütçe

Haftasonu inhouse bütçe karşılaştırması:

```
Kuyruk  |  Pzr01  |  Cmt07  |  Pzr08  |  ...  |  Toplam  |  Bütçe  |  Fark  |  Durum
```

## Sheet 3-N — Hafta 1, Hafta 2, ...

Her hafta için 1 sheet. 3 kuyruk için sırayla:

```
=== KITLE ===
A) Günlük MIP1/MIP2/Surplus/Eksik tablosu
B) Surplus dağıtımı (varsa)
C) Eksik kapsama (Stage 4 çıktıysa)
D) Slot bazlı RR tablosu

=== GOLD ===
(aynı 4 bölüm)

=== KURUMSAL ===
(aynı)
```

## Son Sheet — RR Raporu

Tüm ay için tek tablo. Her gün × her kuyruk için 6 metrik:

```
Tarih  |  Gün  |  [KITLE: Erl_Pk MIP2_Pk RR2_Avg RR2_Min RR2_Max Kap_RR]
                |  [GOLD: ...]
                |  [KURUMSAL: ...]
AYLIK  |  —   |  (aylık özet: Erlang-ağırlıklı avg + ay min/max + çağrı-ağırlıklı Kap_RR)
```

Renk kodu (RR2 Avg, RR2 Min, Kap_RR sütunlarında):
- Kırmızı kalın → < 100%
- Mavi → > 105%
- Yeşil → 100-105%

---

# 9. HATA DURUMLARI

| Durum | Sebep | Çözüm |
|-------|-------|-------|
| Cache'ten yüklendi | `monthly_v9_forecast_YYYY_MM.pkl` mevcut | `os.remove(CACHE_FILE)` sonra HÜCRE 7'yi koştur |
| `KeyError: forecast_datetime` | CONFIG'de `forecast_cols.datetime` df_forecast'taki kolon adıyla eşleşmiyor | Doğru kolon adını yaz |
| Tüm günler INFEASIBLE | Stage 1-2-4 dahi çözemedi | `verbose=True` ile koş, hangi aşamada bittiğini gör |
| RR raporda 0 değerleri | Eski cache + farklı pipeline (V9 weekday vs weekend) | Cache silip yeniden koştur |
| Sheet RR Raporu Kap_RR 0% | `cfg_weekday`/`cfg_weekend` HÜCRE 12 çağrısında geçilmemiş | `cfg_weekday=CONFIG_WEEKDAY` ekle |

---

# 10. İLİŞKİLİ DOSYALAR

| Dosya | Görev |
|-------|-------|
| monthly_run_v9_forecast.py | Bu rehberin konusu — aylık orkestrasyon |
| weekly_weekday_pipeline_forecast.py | Haftaiçi V9 MIP (Stage 4 dahil) |
| weekend_forecast_final.py | Haftasonu forecast MIP |

V9 weekday MIP iç matematiği için ek referans:
`actual_pipeline_v9_weekly.py` (eski actual-mode dosyası — aynı MIP mantığı).
