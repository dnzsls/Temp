# MIP MODELİ DOKÜMANTASYONU
## Workforce Scheduling — Vardiya Optimizasyonu v10.9

---

# 1. PROBLEM TANIMI

Çağrı merkezi için günlük vardiya planlaması yapılacak. Amaç:
- Erlang-C ile hesaplanan personel ihtiyacını karşılamak
- Toplam maliyeti minimize etmek
- Outsource oranını hedef aralıkta tutmak
- Fazla atamayı (RR penalty) cezalandırarak verimli dağılım sağlamak
- Slot bazlı üst sınırlarla (slot cap) aşırı yığılmayı önlemek
- Alt kuyruk bazında inhouse/outsource minimum kısıtlarını sağlamak

**v10.9 Değişiklikler:**
- Pattern / geçmiş veri analizi **kaldırıldı** (excluded_starts, shift_bounds yok)
- Occupancy **kaldırıldı** (Erlang-C'ye dahil edildi)
- RR Penalty: 3 seviyeli (peak / gündüz / gece) fazla atama ceza mekanizması eklendi
- Slot Cap: saat aralığı bazlı üst sınır eklendi
- Small Shift Penalty: her aktif shift için sabit maliyet cezası eklendi
- Part-time çalışan desteği (hafta sonu, inhouse çarpanı ile)
- Saatlik shrinkage (saat bazlı farklı shrinkage oranları)
- Queue Override: gün tipi (haftaiçi/cumartesi/pazar) + kuyruk bazlı config override
- Inhouse-only / Outsource-only alt kuyruk kısıtları

---

# 2. ÖRNEK VERİ SETİ

## 2.1 Vardiyalar (10 adet + 3 part-time)

| Shift | Başlangıç | Bitiş | Company | Kapsadığı Slotlar |
|-------|-----------|-------|---------|-------------------|
| S1 | 07:00 | 16:00 | inhouse | 07:00, 07:30, 08:00, ..., 15:30 |
| S2 | 07:00 | 16:00 | outsource | 07:00, 07:30, 08:00, ..., 15:30 |
| S3 | 08:00 | 17:00 | inhouse | 08:00, 08:30, 09:00, ..., 16:30 |
| S4 | 08:00 | 17:00 | outsource | 08:00, 08:30, 09:00, ..., 16:30 |
| S5 | 09:00 | 18:00 | inhouse | 09:00, 09:30, 10:00, ..., 17:30 |
| S6 | 09:00 | 18:00 | outsource | 09:00, 09:30, 10:00, ..., 17:30 |
| S7 | 10:00 | 19:00 | inhouse | 10:00, 10:30, 11:00, ..., 18:30 |
| S8 | 10:00 | 19:00 | outsource | 10:00, 10:30, 11:00, ..., 18:30 |
| S9 | 00:00 | 08:00 | inhouse | 00:00, 00:30, 01:00, ..., 07:30 |
| S10 | 17:00 | 01:30 | outsource | 17:00, 17:30, ..., 01:00 |
| PT1 | 09:00 | 13:00 | part_time | 09:00, 09:30, 10:00, ..., 12:30 |
| PT2 | 10:00 | 14:00 | part_time | 10:00, 10:30, 11:00, ..., 13:30 |
| PT3 | 19:00 | 23:00 | part_time | 19:00, 19:30, 20:00, ..., 22:30 |

Part-time vardiyalar sadece hafta sonu aktif olur ve toplam sayıları config'ten gelir (örn. kitle: 32 kişi). Cumartesi yarısı, pazar tamamı çalışır. Maliyet olarak inhouse çarpanını kullanır.

**Part-time Müsaitlik Kuralları:**

| Gün Tipi | Kullanılabilir PT |
|----------|-------------------|
| Haftaiçi | 0 (part-time çalışmaz) |
| Cumartesi | total_pt // 2 (yarısı) |
| Pazar | total_pt (tamamı) |
| Ayın son cumartesisi | total_pt (tamamı) |
| Ayın ilk 3 günü (hafta sonu bile) | 0 |

## 2.2 Erlang İhtiyacı (Slot Bazlı)

| Slot | Erlang Need |
|------|-------------|
| 00:00 | 8 |
| 00:30 | 7 |
| ... | ... |
| 03:00 | 5 |
| ... | ... |
| 07:00 | 20 |
| 07:30 | 25 |
| 08:00 | 45 |
| 08:30 | 60 |
| 09:00 | 80 |
| 09:30 | 90 |
| 10:00 | 95 |
| 10:30 | 100 |
| 11:00 | 100 |
| 11:30 | 95 |
| 12:00 | 85 |
| 12:30 | 80 |
| 13:00 | 75 |
| 13:30 | 70 |
| 14:00 | 65 |
| 14:30 | 60 |
| 15:00 | 55 |
| 15:30 | 50 |
| 16:00 | 45 |
| 16:30 | 40 |
| 17:00 | 35 |
| 17:30 | 30 |
| 18:00 | 25 |
| 18:30 | 20 |
| 19:00 | 18 |
| 19:30 | 15 |
| 20:00 | 12 |
| ... | ... |

## 2.3 Slot Kapsam Tablosu

Hangi vardiya hangi slotu kapsıyor (tablo tüm modelde referans alınacak):

| Slot | Kapsayan Vardiyalar |
|------|---------------------|
| 00:00 | S9 |
| 00:30 | S9, S10 |
| 01:00 | S9, S10 |
| ... | ... |
| 07:00 | S1, S2, S9 |
| 07:30 | S1, S2, S9 |
| 08:00 | S1, S2, S3, S4 |
| 08:30 | S1, S2, S3, S4 |
| 09:00 | S1, S2, S3, S4, S5, S6, PT1 |
| 09:30 | S1, S2, S3, S4, S5, S6, PT1 |
| 10:00 | S1, S2, S3, S4, S5, S6, S7, S8, PT1, PT2 |
| 10:30 | S1, S2, S3, S4, S5, S6, S7, S8, PT1, PT2 |
| 11:00 | S1, S2, S3, S4, S5, S6, S7, S8, PT1, PT2 |
| 11:30 | S1, S2, S3, S4, S5, S6, S7, S8, PT1, PT2 |
| 12:00 | S1, S2, S3, S4, S5, S6, S7, S8, PT1, PT2 |
| 12:30 | S1, S2, S3, S4, S5, S6, S7, S8, PT2 |
| 13:00 | S1, S2, S3, S4, S5, S6, S7, S8, PT2 |
| 13:30 | S1, S2, S3, S4, S5, S6, S7, S8, PT2 |
| 14:00 | S1, S2, S3, S4, S5, S6, S7, S8 |
| 14:30 | S1, S2, S3, S4, S5, S6, S7, S8 |
| 15:00 | S1, S2, S3, S4, S5, S6, S7, S8 |
| 15:30 | S1, S2, S3, S4, S5, S6, S7, S8 |
| 16:00 | S3, S4, S5, S6, S7, S8 |
| 16:30 | S3, S4, S5, S6, S7, S8 |
| 17:00 | S5, S6, S7, S8, S10 |
| 17:30 | S5, S6, S7, S8, S10 |
| 18:00 | S7, S8, S10 |
| 18:30 | S7, S8, S10 |
| 19:00 | S10, PT3 |
| 19:30 | S10, PT3 |
| 20:00 | S10, PT3 |
| ... | ... |
| 22:30 | S10, PT3 |
| 23:00 | S10 |
| ... | ... |

## 2.4 Inhouse / Outsource / Part-time Ayrımı

| Tip | Shift'ler |
|-----|-----------|
| Inhouse | S1, S3, S5, S7, S9 |
| Outsource | S2, S4, S6, S8, S10 |
| Part-time | PT1, PT2, PT3 (inhouse sayılır) |

## 2.5 CONFIG Parametreleri

```python
cost_inhouse = 1.0            # İnhouse birim maliyet
cost_outsource = 1.0          # Outsource birim maliyet
min_per_shift = 5             # Shift kullanılırsa minimum kişi

time_cost_multipliers = {
    'kitle': {
        'inhouse': {'07:00': 1.5, '07:30': 1.3},
        'outsource': {}
    },
    'default': {
        'inhouse': {'07:00': 1.5, '07:30': 1.3},
        'outsource': {}
    }
}

outsource_ratio = {
    'kitle': {'min': 0.60, 'max': 0.65},
    'kurumsal': None,
    'gold': None
}

rr_penalty = {
    'enabled': True,
    'penalty_per_person': 4.0,
    'peak_penalty': 2.0,
    'peak_threshold': 0.90,
    'night_multiplier': {
        'enabled': True,
        'hours': {'start': '02:00', 'end': '07:00'},
        'multiplier': 100.0
    }
}

slot_cap = {
    'enabled': True,
    'queues': ['kitle'],
    'bands': [
        {'start': '07:00', 'end': '09:00', 'max_ratio': 1.05, 'penalty': 50.0},
        {'start': '09:00', 'end': '10:00', 'max_ratio': 1.25, 'penalty': 50.0},
        {'start': '10:00', 'end': '11:00', 'max_ratio': 1.30, 'penalty': 50.0},
    ]
}

small_shift_penalty = {
    'enabled': True,
    'penalty': 10
}

erlang = {
    'target_asa': 30,
    'shrinkage': {
        9: 0.20, 10: 0.12, 11: 0.11, 12: 0.13,
        13: 0.20, 14: 0.17, 15: 0.23, 16: 0.25,
        17: 0.22, 18: 0.16, 19: 0.13, 20: 0.16,
        'default': 0.0
    },
    'interval_minutes': 30
}
```

## 2.6 Örnek Inhouse/Outsource-Only Alt Kuyruk Verileri

Bu örnekte `kayipcalintisupheli` alt kuyruğu outsource-only olarak tanımlı (08:00-00:00 arası):

| Slot | kayipcalintisupheli_calls | toplam_calls | Erlang | call_ratio | min_outsource |
|------|--------------------------|-------------|--------|------------|---------------|
| 08:00 | 3 | 120 | 45 | 0.025 | ⌈45×0.025×1.0⌉ = 2 |
| 09:00 | 5 | 200 | 80 | 0.025 | ⌈80×0.025×1.0⌉ = 2 |
| 10:00 | 8 | 250 | 95 | 0.032 | ⌈95×0.032×1.0⌉ = 4 |
| 11:00 | 10 | 260 | 100 | 0.038 | ⌈100×0.038×1.0⌉ = 4 |
| ... | ... | ... | ... | ... | ... |

---

# 3. AHT HESAPLAMA

## 3.1 Weighted AHT (Ağırlıklı Ortalama İşlem Süresi)

v10.9'da AHT hesabı alt kuyruk (sub-queue) bazında yapılır. Her slotta çağrı dağılımına göre ağırlıklı ortalama hesaplanır:

```
weighted_aht(slot) = Σ(sq_calls × sq_aht) / Σ(sq_calls)
```

Burada `sq_calls` o slottaki alt kuyruğun çağrı sayısı, `sq_aht` ise o alt kuyruğun o saatteki AHT değeridir.

**Öncelik sırası:**
1. `aht_overrides` — Manuel saat bazlı override (varsa doğrudan kullanılır)
2. Sub-queue bazlı weighted hesap (çağrı dağılımına göre)
3. `default_aht` — Hiçbiri yoksa fallback (150 sn)

## 3.2 Sub-Queue AHT Yükleme

`load_aht_from_df()` fonksiyonu ile dışarıdan DataFrame olarak yüklenir:

```
df_aht gereklilikleri:
  - saat: saat değeri (int)
  - sub_queue: alt kuyruk adı
  - line_based_main_group: ana kuyruk adı (actual_name)
  - weighted_avg_aht: AHT değeri (saniye)
```

Her alt kuyruk için saat bazlı AHT dict'i ve bir `default` (ortalama) değer oluşturulur.

---

# 4. ERLANG-C HESAPLAMA

## 4.1 Temel Formül

Her 30 dakikalık slot için:

```
traffic = (calls × aht/60) / interval_minutes
```

Erlang-C formülü ile ASA (Average Speed of Answer) hesaplanır. `target_asa` (30 sn) hedefini sağlayan minimum ajan sayısı bulunur.

## 4.2 Saatlik Shrinkage

v10.9'da shrinkage saat bazlı dict olarak tanımlanır:

```python
shrinkage = {9: 0.20, 10: 0.12, 11: 0.11, ..., 'default': 0.0}
```

Hesaplama:
```
final_agents = ⌈raw_agents / (1 - shrinkage_hour)⌉
```

**Örnek:**
```
Saat 09:00 — raw=80, shrinkage=0.20 → final = ⌈80 / 0.80⌉ = 100
Saat 10:00 — raw=80, shrinkage=0.12 → final = ⌈80 / 0.88⌉ = 91
Saat 02:00 — raw=10, shrinkage=0.03 → final = ⌈10 / 0.97⌉ = 11
```

## 4.3 Queue Override — Gün Tipi Bazlı Shrinkage

`queue_overrides` mekanizmasıyla her kuyruk + gün tipi (haftaiçi / cumartesi / pazar) kombinasyonu için farklı shrinkage tanımlanabilir. Override uygulandığında deep merge ile sadece değişen değerler yazılır, diğerleri ana CONFIG'ten gelir.

---

# 5. MIP MODELİ

## 5.1 Karar Değişkenleri

### Ana Değişkenler (Integer)
```
x[S1]  = 07:00 inhouse vardiyasına atanacak kişi sayısı
x[S2]  = 07:00 outsource vardiyasına atanacak kişi sayısı
x[S3]  = 08:00 inhouse vardiyasına atanacak kişi sayısı
x[S4]  = 08:00 outsource vardiyasına atanacak kişi sayısı
x[S5]  = 09:00 inhouse vardiyasına atanacak kişi sayısı
x[S6]  = 09:00 outsource vardiyasına atanacak kişi sayısı
x[S7]  = 10:00 inhouse vardiyasına atanacak kişi sayısı
x[S8]  = 10:00 outsource vardiyasına atanacak kişi sayısı
x[S9]  = 00:00 inhouse vardiyasına atanacak kişi sayısı
x[S10] = 17:00 outsource vardiyasına atanacak kişi sayısı

Tümü için: x[Si] ∈ {0, 1, 2, 3, ...} (Integer, >= 0)
```

### Part-time Değişkenleri (Integer, hafta sonu)
```
x[PT1] = 09:00-13:00 part_time vardiyasına atanacak kişi sayısı
x[PT2] = 10:00-14:00 part_time vardiyasına atanacak kişi sayısı
x[PT3] = 19:00-23:00 part_time vardiyasına atanacak kişi sayısı
```

### Yardımcı Değişkenler (Binary)
```
y[S1], y[S2], ..., y[S10], y[PT1], y[PT2], y[PT3] ∈ {0, 1}

y[Si] = 1 → Shift kullanılıyor
y[Si] = 0 → Shift kullanılmıyor
```

### Fazla Atama Değişkenleri (Continuous) — RR Penalty
```
excess[07:00], excess[07:30], excess[08:00], ..., excess[22:30] ∈ ℝ+

excess[slot] >= 0   (her aktif slot için)
Yakaladığı: toplam atama - Erlang ihtiyacı (pozitif kısım)
```

### Slot Cap Aşım Değişkenleri (Continuous)
```
sc_excess[07:00], sc_excess[07:30], sc_excess[08:00], sc_excess[08:30],
sc_excess[09:00], sc_excess[09:30], sc_excess[10:00], sc_excess[10:30] ∈ ℝ+

sc_excess[slot] >= 0   (slot cap bandına giren slotlar için)
Yakaladığı: toplam atama - cap değeri (pozitif kısım)
```

---

## 5.2 Amaç Fonksiyonu

**AMAÇ: Toplam maliyeti minimize et**

Toplam maliyet **4 bileşenden** oluşur:

### Bileşen 1: Temel Atama Maliyeti

Her shift'e atanan kişi sayısı × birim maliyet × zaman çarpanı:

#### Maliyet Hesaplama Tablosu

| Shift | Başlangıç | Company | Base Cost | Time Mult | Final Cost |
|-------|-----------|---------|-----------|-----------|------------|
| S1 | 07:00 | inhouse | 1.0 | 1.5 | **1.50** |
| S2 | 07:00 | outsource | 1.0 | 1.0 | **1.00** |
| S3 | 08:00 | inhouse | 1.0 | 1.0 | **1.00** |
| S4 | 08:00 | outsource | 1.0 | 1.0 | **1.00** |
| S5 | 09:00 | inhouse | 1.0 | 1.0 | **1.00** |
| S6 | 09:00 | outsource | 1.0 | 1.0 | **1.00** |
| S7 | 10:00 | inhouse | 1.0 | 1.0 | **1.00** |
| S8 | 10:00 | outsource | 1.0 | 1.0 | **1.00** |
| S9 | 00:00 | inhouse | 1.0 | 1.0 | **1.00** |
| S10 | 17:00 | outsource | 1.0 | 1.0 | **1.00** |
| PT1 | 09:00 | part_time | 1.0 | 1.0 | **1.00** |
| PT2 | 10:00 | part_time | 1.0 | 1.0 | **1.00** |
| PT3 | 19:00 | part_time | 1.0 | 1.0 | **1.00** |

#### Formül
```
Temel Maliyet = 1.50×x[S1] + 1.00×x[S2] + 1.00×x[S3] + 1.00×x[S4] +
                1.00×x[S5] + 1.00×x[S6] + 1.00×x[S7] + 1.00×x[S8] +
                1.00×x[S9] + 1.00×x[S10] +
                1.00×x[PT1] + 1.00×x[PT2] + 1.00×x[PT3]
```

**Not:** S1 (07:00 inhouse) maliyeti 1.50 olduğu için model bu vardiyayı tercih etmeyecek (soft constraint).

### Bileşen 2: Small Shift Penalty (Küçük Atama Cezası)

Her aktif shift (y[s]=1) için sabit bir ceza eklenir. Model, 2-3 kişilik yeni shift açmak yerine mevcut shift'e eklemeyi tercih eder.

**Parametre:** `ssp_penalty = 10`

**Part-time hariç:** PT shift'lerine small shift penalty uygulanmaz.

#### Formül
```
SSP = 10×y[S1] + 10×y[S2] + 10×y[S3] + 10×y[S4] + 10×y[S5] +
      10×y[S6] + 10×y[S7] + 10×y[S8] + 10×y[S9] + 10×y[S10]
```

**Örnek:** 8 farklı shift aktifse → 8 × 10 = 80 ek maliyet.

### Bileşen 3: RR Penalty (Fazla Atama Cezası)

Erlang ihtiyacının üstüne çıkan atamaları cezalandırır. 3 farklı seviye vardır.

#### Peak Slotların Belirlenmesi

```
max_erlang = max(20, 25, 45, 60, 80, 90, 95, 100, 100, ...) = 100
peak_threshold = 0.90
peak_eşik = 100 × 0.90 = 90

Peak slotlar (Erlang >= 90):
  09:30 (90), 10:00 (95), 10:30 (100), 11:00 (100), 11:30 (95)
```

#### Ceza Seviyeleri

| Slot Türü | Koşul | Ceza/kişi |
|-----------|-------|-----------|
| **Peak** | Erlang ≥ 90 | 2.0 |
| **Gece** | 02:00-07:00 arası | 4.0 × 100.0 = **400.0** |
| **Gündüz (off-peak)** | Geri kalan | 4.0 |

#### Formül (slot slot)

```
# Gece slotları (02:00-07:00) — ceza = 400.0
RR_gece = 400.0×excess[02:00] + 400.0×excess[02:30] + 400.0×excess[03:00] +
          400.0×excess[03:30] + 400.0×excess[04:00] + 400.0×excess[04:30] +
          400.0×excess[05:00] + 400.0×excess[05:30] + 400.0×excess[06:00] +
          400.0×excess[06:30]

# Peak slotları (Erlang >= 90) — ceza = 2.0
RR_peak = 2.0×excess[09:30] + 2.0×excess[10:00] + 2.0×excess[10:30] +
          2.0×excess[11:00] + 2.0×excess[11:30]

# Gündüz off-peak (geri kalan aktif slotlar) — ceza = 4.0
RR_gunduz = 4.0×excess[00:00] + 4.0×excess[00:30] + 4.0×excess[01:00] +
            4.0×excess[01:30] +
            4.0×excess[07:00] + 4.0×excess[07:30] +
            4.0×excess[08:00] + 4.0×excess[08:30] +
            4.0×excess[09:00] +
            4.0×excess[12:00] + 4.0×excess[12:30] +
            4.0×excess[13:00] + 4.0×excess[13:30] +
            4.0×excess[14:00] + 4.0×excess[14:30] +
            4.0×excess[15:00] + 4.0×excess[15:30] +
            4.0×excess[16:00] + 4.0×excess[16:30] +
            4.0×excess[17:00] + 4.0×excess[17:30] +
            4.0×excess[18:00] + 4.0×excess[18:30] +
            4.0×excess[19:00] + 4.0×excess[19:30] +
            4.0×excess[20:00] + ...

RR_toplam = RR_gece + RR_peak + RR_gunduz
```

### Bileşen 4: Slot Cap Penalty (Aralık Bazlı Üst Sınır Cezası)

#### Cap Hesaplama

| Slot | Erlang | Band | max_ratio | cap = max(⌈Erlang×ratio⌉, 3) | Penalty |
|------|--------|------|-----------|-------------------------------|---------|
| 07:00 | 20 | 07:00-09:00 | 1.05 | max(⌈20×1.05⌉, 3) = 21 | 50.0 |
| 07:30 | 25 | 07:00-09:00 | 1.05 | max(⌈25×1.05⌉, 3) = 27 | 50.0 |
| 08:00 | 45 | 07:00-09:00 | 1.05 | max(⌈45×1.05⌉, 3) = 48 | 50.0 |
| 08:30 | 60 | 07:00-09:00 | 1.05 | max(⌈60×1.05⌉, 3) = 63 | 50.0 |
| 09:00 | 80 | 09:00-10:00 | 1.25 | max(⌈80×1.25⌉, 3) = 100 | 50.0 |
| 09:30 | 90 | 09:00-10:00 | 1.25 | max(⌈90×1.25⌉, 3) = 113 | 50.0 |
| 10:00 | 95 | 10:00-11:00 | 1.30 | max(⌈95×1.30⌉, 3) = 124 | 50.0 |
| 10:30 | 100 | 10:00-11:00 | 1.30 | max(⌈100×1.30⌉, 3) = 130 | 50.0 |

#### Formül
```
SC = 50.0×sc_excess[07:00] + 50.0×sc_excess[07:30] +
     50.0×sc_excess[08:00] + 50.0×sc_excess[08:30] +
     50.0×sc_excess[09:00] + 50.0×sc_excess[09:30] +
     50.0×sc_excess[10:00] + 50.0×sc_excess[10:30]
```

### Tam Amaç Fonksiyonu

```
MINIMIZE Z = Temel Maliyet + SSP + RR_toplam + SC

           = [1.50×x[S1] + 1.00×x[S2] + 1.00×x[S3] + 1.00×x[S4] +
              1.00×x[S5] + 1.00×x[S6] + 1.00×x[S7] + 1.00×x[S8] +
              1.00×x[S9] + 1.00×x[S10] +
              1.00×x[PT1] + 1.00×x[PT2] + 1.00×x[PT3]]

           + [10×y[S1] + 10×y[S2] + 10×y[S3] + 10×y[S4] + 10×y[S5] +
              10×y[S6] + 10×y[S7] + 10×y[S8] + 10×y[S9] + 10×y[S10]]

           + [400.0×excess[02:00] + ... + 400.0×excess[06:30] +
              2.0×excess[09:30] + ... + 2.0×excess[11:30] +
              4.0×excess[07:00] + ... + 4.0×excess[diğer_gündüz]]

           + [50.0×sc_excess[07:00] + 50.0×sc_excess[07:30] +
              50.0×sc_excess[08:00] + 50.0×sc_excess[08:30] +
              50.0×sc_excess[09:00] + 50.0×sc_excess[09:30] +
              50.0×sc_excess[10:00] + 50.0×sc_excess[10:30]]
```

---

## 5.3 Kısıtlar

### K1: Erlang İhtiyacını Karşıla (Hard Constraint)

**Mantık:** Her slotta, o slotu kapsayan tüm vardiyaların toplamı >= Erlang ihtiyacı

#### MIP Formülleri

```
Slot 00:00:  x[S9] >= 8
Slot 00:30:  x[S9] + x[S10] >= 7
Slot 01:00:  x[S9] + x[S10] >= 7
...
Slot 03:00:  x[S9] >= 5
...
Slot 07:00:  x[S1] + x[S2] + x[S9] >= 20
Slot 07:30:  x[S1] + x[S2] + x[S9] >= 25
Slot 08:00:  x[S1] + x[S2] + x[S3] + x[S4] >= 45
Slot 08:30:  x[S1] + x[S2] + x[S3] + x[S4] >= 60
Slot 09:00:  x[S1] + x[S2] + x[S3] + x[S4] + x[S5] + x[S6] + x[PT1] >= 80
Slot 09:30:  x[S1] + x[S2] + x[S3] + x[S4] + x[S5] + x[S6] + x[PT1] >= 90
Slot 10:00:  x[S1] + x[S2] + x[S3] + x[S4] + x[S5] + x[S6] + x[S7] + x[S8] + x[PT1] + x[PT2] >= 95
Slot 10:30:  x[S1] + x[S2] + x[S3] + x[S4] + x[S5] + x[S6] + x[S7] + x[S8] + x[PT1] + x[PT2] >= 100
Slot 11:00:  x[S1] + x[S2] + x[S3] + x[S4] + x[S5] + x[S6] + x[S7] + x[S8] + x[PT1] + x[PT2] >= 100
Slot 11:30:  x[S1] + x[S2] + x[S3] + x[S4] + x[S5] + x[S6] + x[S7] + x[S8] + x[PT1] + x[PT2] >= 95
Slot 12:00:  x[S1] + x[S2] + x[S3] + x[S4] + x[S5] + x[S6] + x[S7] + x[S8] + x[PT1] + x[PT2] >= 85
Slot 12:30:  x[S1] + x[S2] + x[S3] + x[S4] + x[S5] + x[S6] + x[S7] + x[S8] + x[PT2] >= 80
Slot 13:00:  x[S1] + x[S2] + x[S3] + x[S4] + x[S5] + x[S6] + x[S7] + x[S8] + x[PT2] >= 75
Slot 13:30:  x[S1] + x[S2] + x[S3] + x[S4] + x[S5] + x[S6] + x[S7] + x[S8] + x[PT2] >= 70
Slot 14:00:  x[S1] + x[S2] + x[S3] + x[S4] + x[S5] + x[S6] + x[S7] + x[S8] >= 65
Slot 14:30:  x[S1] + x[S2] + x[S3] + x[S4] + x[S5] + x[S6] + x[S7] + x[S8] >= 60
Slot 15:00:  x[S1] + x[S2] + x[S3] + x[S4] + x[S5] + x[S6] + x[S7] + x[S8] >= 55
Slot 15:30:  x[S1] + x[S2] + x[S3] + x[S4] + x[S5] + x[S6] + x[S7] + x[S8] >= 50
Slot 16:00:  x[S3] + x[S4] + x[S5] + x[S6] + x[S7] + x[S8] >= 45
Slot 16:30:  x[S3] + x[S4] + x[S5] + x[S6] + x[S7] + x[S8] >= 40
Slot 17:00:  x[S5] + x[S6] + x[S7] + x[S8] + x[S10] >= 35
Slot 17:30:  x[S5] + x[S6] + x[S7] + x[S8] + x[S10] >= 30
Slot 18:00:  x[S7] + x[S8] + x[S10] >= 25
Slot 18:30:  x[S7] + x[S8] + x[S10] >= 20
Slot 19:00:  x[S10] + x[PT3] >= 18
Slot 19:30:  x[S10] + x[PT3] >= 15
Slot 20:00:  x[S10] + x[PT3] >= 12
... (diğer slotlar)
```

**Not:** Part-time vardiyalar sadece hafta sonu aktiftir. Haftaiçi PT değişkenleri modelde yer almaz.

---

### K2: Outsource Oranı Hedefi %60-%65 (Hard Constraint)

**Mantık:** Toplam personelde outsource oranı belirlenen aralıkta olmalı. Part-time, inhouse tarafında sayılır.

```
t_in  = x[S1] + x[S3] + x[S5] + x[S7] + x[S9] + x[PT1] + x[PT2] + x[PT3]
t_out = x[S2] + x[S4] + x[S6] + x[S8] + x[S10]

İstenen: 0.60 <= t_out / (t_in + t_out) <= 0.65
```

**Dönüştürme (lineer form):**

```
Minimum %60 outsource:
  t_out >= 0.60 × (t_in + t_out)
  t_out - 0.60×t_out >= 0.60×t_in
  0.40×t_out >= 0.60×t_in

Maksimum %65 outsource:
  t_out <= 0.65 × (t_in + t_out)
  t_out - 0.65×t_out <= 0.65×t_in
  0.35×t_out <= 0.65×t_in
```

#### MIP Formülleri

```
# Minimum %60 outsource
0.40×(x[S2]+x[S4]+x[S6]+x[S8]+x[S10]) >= 0.60×(x[S1]+x[S3]+x[S5]+x[S7]+x[S9]+x[PT1]+x[PT2]+x[PT3])

# Maksimum %65 outsource
0.35×(x[S2]+x[S4]+x[S6]+x[S8]+x[S10]) <= 0.65×(x[S1]+x[S3]+x[S5]+x[S7]+x[S9]+x[PT1]+x[PT2]+x[PT3])
```

**Not:** `outsource_ratio = None` olan kuyruklar (kurumsal, gold) için bu kısıt eklenmez.

---

### K3: Shift Aktivasyon + Minimum Kişi (Hard Constraint)

**Mantık:** Shift kullanılıyorsa (y=1) en az `min_per_shift` kişi atanmalı, kullanılmıyorsa (y=0) hiç atama yapılamamalı.

**Parametreler:** M = 500, min_per_shift = 5

#### MIP Formülleri — Üst Sınır

```
x[S1]  <= 500 × y[S1]      # y[S1]=0 ise x[S1]=0,  y[S1]=1 ise x[S1]<=500
x[S2]  <= 500 × y[S2]
x[S3]  <= 500 × y[S3]
x[S4]  <= 500 × y[S4]
x[S5]  <= 500 × y[S5]
x[S6]  <= 500 × y[S6]
x[S7]  <= 500 × y[S7]
x[S8]  <= 500 × y[S8]
x[S9]  <= 500 × y[S9]
x[S10] <= 500 × y[S10]
x[PT1] <= 500 × y[PT1]
x[PT2] <= 500 × y[PT2]
x[PT3] <= 500 × y[PT3]
```

#### MIP Formülleri — Alt Sınır

```
x[S1]  >= 5 × y[S1]        # y[S1]=1 ise x[S1]>=5,  y[S1]=0 ise x[S1]>=0
x[S2]  >= 5 × y[S2]
x[S3]  >= 5 × y[S3]
x[S4]  >= 5 × y[S4]
x[S5]  >= 5 × y[S5]
x[S6]  >= 5 × y[S6]
x[S7]  >= 5 × y[S7]
x[S8]  >= 5 × y[S8]
x[S9]  >= 5 × y[S9]
x[S10] >= 5 × y[S10]
x[PT1] >= 5 × y[PT1]
x[PT2] >= 5 × y[PT2]
x[PT3] >= 5 × y[PT3]
```

**Etki:** Bir shift açılacaksa en az 5 kişi atanmak zorunda. Bu, 1-2 kişilik micro-shift'lerin oluşmasını engeller.

---

### K4: Part-time Toplam Kısıt (Hard Constraint, hafta sonu)

**Mantık:** Tüm part-time shift'lere atanan toplam kişi, config'teki müsait sayıya eşit olmalı.

**Örnek:** Pazar, kitle kuyruğu, `pt_available = 32`

#### MIP Formülleri

```
x[PT1] + x[PT2] + x[PT3] == 32
```

**Not:** Haftaiçi pt_available = 0 olduğundan PT değişkenleri modelde yer almaz.

---

### K5: Inhouse-Only Alt Kuyruk Minimumu (Hard Constraint)

**Mantık:** Belirli alt kuyruklardaki çağrılar sadece inhouse tarafından karşılanmalı. Her slotta bu alt kuyruğun çağrı oranı kadar minimum inhouse personel gerekir.

**Hesaplama:**
```
call_ratio = sq_calls / total_calls
min_need = ⌈erlang_need × call_ratio × min_ratio⌉
```

#### Hangi inhouse + part-time vardiya hangi slotu kapsıyor?

| Slot | Inhouse + Part-time Vardiyalar |
|------|-------------------------------|
| 07:00 | S1, S9 |
| 07:30 | S1, S9 |
| 08:00 | S1, S3 |
| 08:30 | S1, S3 |
| 09:00 | S1, S3, S5, PT1 |
| 09:30 | S1, S3, S5, PT1 |
| 10:00 | S1, S3, S5, S7, PT1, PT2 |
| 10:30 | S1, S3, S5, S7, PT1, PT2 |
| 11:00 | S1, S3, S5, S7, PT1, PT2 |
| ... | ... |
| 16:00 | S3, S5, S7 |
| 16:30 | S3, S5, S7 |
| 17:00 | S5, S7 |
| 17:30 | S5, S7 |
| 18:00 | S7 |
| 18:30 | S7 |
| 19:00 | PT3 |
| ... | ... |

#### MIP Formülleri (Örnek: `retention_line` min_ratio=1.0)

Diyelim `retention_line` 09:00'da çağrı oranı = 15/100, Erlang = 80 → min_need = ⌈80 × 0.15 × 1.0⌉ = 12

```
Slot 09:00:  x[S1] + x[S3] + x[S5] + x[PT1] >= 12
Slot 09:30:  x[S1] + x[S3] + x[S5] + x[PT1] >= 14
Slot 10:00:  x[S1] + x[S3] + x[S5] + x[S7] + x[PT1] + x[PT2] >= 15
Slot 10:30:  x[S1] + x[S3] + x[S5] + x[S7] + x[PT1] + x[PT2] >= 16
Slot 11:00:  x[S1] + x[S3] + x[S5] + x[S7] + x[PT1] + x[PT2] >= 16
... (her aktif slot için)
```

---

### K6: Outsource-Only Alt Kuyruk Minimumu (Hard Constraint)

**Mantık:** Belirli alt kuyruklardaki çağrılar sadece outsource tarafından karşılanmalı. Belirli saat aralığında outsource minimum personel gerekir.

#### Hangi outsource vardiya hangi slotu kapsıyor?

| Slot | Outsource Vardiyalar |
|------|---------------------|
| 07:00 | S2 |
| 07:30 | S2 |
| 08:00 | S2, S4 |
| 08:30 | S2, S4 |
| 09:00 | S2, S4, S6 |
| 09:30 | S2, S4, S6 |
| 10:00 | S2, S4, S6, S8 |
| 10:30 | S2, S4, S6, S8 |
| ... | ... |
| 16:00 | S4, S6, S8 |
| 16:30 | S4, S6, S8 |
| 17:00 | S6, S8, S10 |
| 17:30 | S6, S8, S10 |
| 18:00 | S8, S10 |
| 18:30 | S8, S10 |
| 19:00 | S10 |
| ... | ... |

#### MIP Formülleri (Örnek: `kayipcalintisupheli` 08:00-00:00, min_ratio=1.0)

Yukarıdaki 2.6 tablosundaki değerlerle:

```
Slot 08:00:  x[S2] + x[S4] >= 2
Slot 08:30:  x[S2] + x[S4] >= 2
Slot 09:00:  x[S2] + x[S4] + x[S6] >= 2
Slot 09:30:  x[S2] + x[S4] + x[S6] >= 3
Slot 10:00:  x[S2] + x[S4] + x[S6] + x[S8] >= 4
Slot 10:30:  x[S2] + x[S4] + x[S6] + x[S8] >= 4
Slot 11:00:  x[S2] + x[S4] + x[S6] + x[S8] >= 4
... (her aktif slot, sadece 08:00-00:00 arası)
Slot 17:00:  x[S6] + x[S8] + x[S10] >= 2
Slot 17:30:  x[S6] + x[S8] + x[S10] >= 2
Slot 18:00:  x[S8] + x[S10] >= 1
Slot 18:30:  x[S8] + x[S10] >= 1
Slot 19:00:  x[S10] >= 1
... (00:00'a kadar devam eder)
```

**Not:** 08:00 öncesi slotlar (07:00, 07:30) için outsource minimum kısıtı uygulanmaz (`hours` kısıtı).

---

### K7: RR Penalty — Excess Tanımı (Soft Constraint, amaç fonksiyonunda)

**Mantık:** Her aktif slotta, atamanın Erlang üstüne çıkan kısmını yakala. Excess değişkeni her zaman >= 0 olduğu ve amaç fonksiyonunda minimize edildiği için, atama Erlang'ın altındaysa excess otomatik olarak 0 olur.

#### MIP Formülleri (slot slot)

```
excess[00:00] >= x[S9] - 8
excess[00:30] >= x[S9] + x[S10] - 7
excess[01:00] >= x[S9] + x[S10] - 7
...
excess[03:00] >= x[S9] - 5
...
excess[07:00] >= x[S1] + x[S2] + x[S9] - 20
excess[07:30] >= x[S1] + x[S2] + x[S9] - 25
excess[08:00] >= x[S1] + x[S2] + x[S3] + x[S4] - 45
excess[08:30] >= x[S1] + x[S2] + x[S3] + x[S4] - 60
excess[09:00] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[PT1] - 80
excess[09:30] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[PT1] - 90
excess[10:00] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT1]+x[PT2] - 95
excess[10:30] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT1]+x[PT2] - 100
excess[11:00] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT1]+x[PT2] - 100
excess[11:30] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT1]+x[PT2] - 95
excess[12:00] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT1]+x[PT2] - 85
excess[12:30] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT2] - 80
excess[13:00] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT2] - 75
excess[13:30] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT2] - 70
excess[14:00] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8] - 65
excess[14:30] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8] - 60
excess[15:00] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8] - 55
excess[15:30] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8] - 50
excess[16:00] >= x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8] - 45
excess[16:30] >= x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8] - 40
excess[17:00] >= x[S5]+x[S6]+x[S7]+x[S8]+x[S10] - 35
excess[17:30] >= x[S5]+x[S6]+x[S7]+x[S8]+x[S10] - 30
excess[18:00] >= x[S7]+x[S8]+x[S10] - 25
excess[18:30] >= x[S7]+x[S8]+x[S10] - 20
excess[19:00] >= x[S10]+x[PT3] - 18
excess[19:30] >= x[S10]+x[PT3] - 15
excess[20:00] >= x[S10]+x[PT3] - 12
... (diğer aktif slotlar)

# Tüm excess değişkenleri >= 0 (tanım gereği)
excess[slot] >= 0    ∀ aktif slot
```

**Sayısal Örnek:**

Slot 09:30 (peak slot, Erlang=90):
- Diyelim model çözümünde: x[S1]=0, x[S2]=0, x[S3]=35, x[S4]=45, x[S5]=5, x[S6]=5, x[PT1]=5
- Toplam = 0+0+35+45+5+5+5 = 95
- excess[09:30] >= 95 - 90 = 5
- Peak ceza: 5 × 2.0 = 10.0

Slot 03:00 (gece slot, Erlang=5):
- Diyelim model çözümünde: x[S9]=8
- excess[03:00] >= 8 - 5 = 3
- Gece ceza: 3 × 400.0 = 1200.0 → çok yüksek, model gece fazla atamayı ciddi şekilde caydırır

---

### K8: Slot Cap — Cap Aşım Tanımı (Soft Constraint, amaç fonksiyonunda)

**Mantık:** Belirli saat aralıklarında Erlang ihtiyacının belirli bir oranını aşan atamaları cezalandır.

#### MIP Formülleri (slot slot)

```
# Band 07:00-09:00 (max_ratio=1.05)
sc_excess[07:00] >= x[S1]+x[S2]+x[S9] - 21                              # cap=⌈20×1.05⌉
sc_excess[07:30] >= x[S1]+x[S2]+x[S9] - 27                              # cap=⌈25×1.05⌉
sc_excess[08:00] >= x[S1]+x[S2]+x[S3]+x[S4] - 48                        # cap=⌈45×1.05⌉
sc_excess[08:30] >= x[S1]+x[S2]+x[S3]+x[S4] - 63                        # cap=⌈60×1.05⌉

# Band 09:00-10:00 (max_ratio=1.25)
sc_excess[09:00] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[PT1] - 100   # cap=⌈80×1.25⌉
sc_excess[09:30] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[PT1] - 113   # cap=⌈90×1.25⌉

# Band 10:00-11:00 (max_ratio=1.30)
sc_excess[10:00] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT1]+x[PT2] - 124  # cap=⌈95×1.30⌉
sc_excess[10:30] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT1]+x[PT2] - 130  # cap=⌈100×1.30⌉

# Tüm sc_excess değişkenleri >= 0 (tanım gereği)
sc_excess[slot] >= 0    ∀ slot in band
```

**Sayısal Örnek:**

Slot 08:00: cap = 48, atama = 50 → sc_excess = 2, penalty = 2 × 50.0 = 100.0
Slot 08:30: cap = 63, atama = 60 → sc_excess = 0 (aşım yok, ceza yok)

---

# 6. TAM MIP MODELİ (Özet)

```
================================================================================
                              MIP MODELİ v10.9
================================================================================

MINIMIZE:
    Z = 1.50×x[S1] + 1.00×x[S2] + 1.00×x[S3] + 1.00×x[S4] +
        1.00×x[S5] + 1.00×x[S6] + 1.00×x[S7] + 1.00×x[S8] +
        1.00×x[S9] + 1.00×x[S10] +
        1.00×x[PT1] + 1.00×x[PT2] + 1.00×x[PT3]

      + 10×y[S1] + 10×y[S2] + 10×y[S3] + 10×y[S4] + 10×y[S5] +
        10×y[S6] + 10×y[S7] + 10×y[S8] + 10×y[S9] + 10×y[S10]

      + 400.0×excess[02:00] + 400.0×excess[02:30] + 400.0×excess[03:00] +
        400.0×excess[03:30] + 400.0×excess[04:00] + 400.0×excess[04:30] +
        400.0×excess[05:00] + 400.0×excess[05:30] + 400.0×excess[06:00] +
        400.0×excess[06:30]
      + 2.0×excess[09:30] + 2.0×excess[10:00] + 2.0×excess[10:30] +
        2.0×excess[11:00] + 2.0×excess[11:30]
      + 4.0×excess[00:00] + 4.0×excess[00:30] + 4.0×excess[01:00] +
        4.0×excess[01:30] +
        4.0×excess[07:00] + 4.0×excess[07:30] +
        4.0×excess[08:00] + 4.0×excess[08:30] + 4.0×excess[09:00] +
        4.0×excess[12:00] + 4.0×excess[12:30] +
        4.0×excess[13:00] + 4.0×excess[13:30] +
        4.0×excess[14:00] + 4.0×excess[14:30] +
        4.0×excess[15:00] + 4.0×excess[15:30] +
        4.0×excess[16:00] + 4.0×excess[16:30] +
        4.0×excess[17:00] + 4.0×excess[17:30] +
        4.0×excess[18:00] + 4.0×excess[18:30] +
        4.0×excess[19:00] + 4.0×excess[19:30] +
        4.0×excess[20:00] + ...

      + 50.0×sc_excess[07:00] + 50.0×sc_excess[07:30] +
        50.0×sc_excess[08:00] + 50.0×sc_excess[08:30] +
        50.0×sc_excess[09:00] + 50.0×sc_excess[09:30] +
        50.0×sc_excess[10:00] + 50.0×sc_excess[10:30]


SUBJECT TO:

    # ===== K1: ERLANG KARŞILA =====
    x[S9] >= 8                                                                 # 00:00
    x[S9] + x[S10] >= 7                                                       # 00:30
    x[S9] + x[S10] >= 7                                                       # 01:00
    ...
    x[S9] >= 5                                                                 # 03:00
    ...
    x[S1] + x[S2] + x[S9] >= 20                                               # 07:00
    x[S1] + x[S2] + x[S9] >= 25                                               # 07:30
    x[S1] + x[S2] + x[S3] + x[S4] >= 45                                      # 08:00
    x[S1] + x[S2] + x[S3] + x[S4] >= 60                                      # 08:30
    x[S1] + x[S2] + x[S3] + x[S4] + x[S5] + x[S6] + x[PT1] >= 80            # 09:00
    x[S1] + x[S2] + x[S3] + x[S4] + x[S5] + x[S6] + x[PT1] >= 90            # 09:30
    x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT1]+x[PT2] >= 95     # 10:00
    x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT1]+x[PT2] >= 100    # 10:30
    x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT1]+x[PT2] >= 100    # 11:00
    x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT1]+x[PT2] >= 95     # 11:30
    x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT1]+x[PT2] >= 85     # 12:00
    x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT2] >= 80            # 12:30
    x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT2] >= 75            # 13:00
    x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT2] >= 70            # 13:30
    x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8] >= 65                   # 14:00
    x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8] >= 60                   # 14:30
    x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8] >= 55                   # 15:00
    x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8] >= 50                   # 15:30
    x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8] >= 45                                # 16:00
    x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8] >= 40                                # 16:30
    x[S5]+x[S6]+x[S7]+x[S8]+x[S10] >= 35                                     # 17:00
    x[S5]+x[S6]+x[S7]+x[S8]+x[S10] >= 30                                     # 17:30
    x[S7]+x[S8]+x[S10] >= 25                                                  # 18:00
    x[S7]+x[S8]+x[S10] >= 20                                                  # 18:30
    x[S10]+x[PT3] >= 18                                                        # 19:00
    x[S10]+x[PT3] >= 15                                                        # 19:30
    x[S10]+x[PT3] >= 12                                                        # 20:00
    ... (diğer slotlar)

    # ===== K2: OUTSOURCE ORANI %60-65 =====
    0.40×(x[S2]+x[S4]+x[S6]+x[S8]+x[S10]) >= 0.60×(x[S1]+x[S3]+x[S5]+x[S7]+x[S9]+x[PT1]+x[PT2]+x[PT3])
    0.35×(x[S2]+x[S4]+x[S6]+x[S8]+x[S10]) <= 0.65×(x[S1]+x[S3]+x[S5]+x[S7]+x[S9]+x[PT1]+x[PT2]+x[PT3])

    # ===== K3: SHIFT AKTİVASYON + MİNİMUM 5 =====
    x[S1]  <= 500 × y[S1]        x[S1]  >= 5 × y[S1]
    x[S2]  <= 500 × y[S2]        x[S2]  >= 5 × y[S2]
    x[S3]  <= 500 × y[S3]        x[S3]  >= 5 × y[S3]
    x[S4]  <= 500 × y[S4]        x[S4]  >= 5 × y[S4]
    x[S5]  <= 500 × y[S5]        x[S5]  >= 5 × y[S5]
    x[S6]  <= 500 × y[S6]        x[S6]  >= 5 × y[S6]
    x[S7]  <= 500 × y[S7]        x[S7]  >= 5 × y[S7]
    x[S8]  <= 500 × y[S8]        x[S8]  >= 5 × y[S8]
    x[S9]  <= 500 × y[S9]        x[S9]  >= 5 × y[S9]
    x[S10] <= 500 × y[S10]       x[S10] >= 5 × y[S10]
    x[PT1] <= 500 × y[PT1]       x[PT1] >= 5 × y[PT1]
    x[PT2] <= 500 × y[PT2]       x[PT2] >= 5 × y[PT2]
    x[PT3] <= 500 × y[PT3]       x[PT3] >= 5 × y[PT3]

    # ===== K4: PART-TIME TOPLAM (hafta sonu) =====
    x[PT1] + x[PT2] + x[PT3] == 32

    # ===== K5: INHOUSE-ONLY ALT KUYRUK (örnek: retention_line) =====
    x[S1] + x[S3] + x[S5] + x[PT1] >= 12                                     # 09:00
    x[S1] + x[S3] + x[S5] + x[PT1] >= 14                                     # 09:30
    x[S1] + x[S3] + x[S5] + x[S7] + x[PT1] + x[PT2] >= 15                   # 10:00
    x[S1] + x[S3] + x[S5] + x[S7] + x[PT1] + x[PT2] >= 16                   # 10:30
    x[S1] + x[S3] + x[S5] + x[S7] + x[PT1] + x[PT2] >= 16                   # 11:00
    ... (her aktif slot için)

    # ===== K6: OUTSOURCE-ONLY ALT KUYRUK (kayipcalintisupheli 08:00-00:00) =====
    x[S2] + x[S4] >= 2                                                        # 08:00
    x[S2] + x[S4] >= 2                                                        # 08:30
    x[S2] + x[S4] + x[S6] >= 2                                                # 09:00
    x[S2] + x[S4] + x[S6] >= 3                                                # 09:30
    x[S2] + x[S4] + x[S6] + x[S8] >= 4                                       # 10:00
    x[S2] + x[S4] + x[S6] + x[S8] >= 4                                       # 10:30
    x[S2] + x[S4] + x[S6] + x[S8] >= 4                                       # 11:00
    ... (her aktif slot, sadece 08:00-00:00 arası)
    x[S6] + x[S8] + x[S10] >= 2                                               # 17:00
    x[S6] + x[S8] + x[S10] >= 2                                               # 17:30
    x[S8] + x[S10] >= 1                                                       # 18:00
    x[S8] + x[S10] >= 1                                                       # 18:30
    x[S10] >= 1                                                                # 19:00
    ... (00:00'a kadar devam eder)

    # ===== K7: RR PENALTY — EXCESS TANIMI =====
    excess[00:00] >= x[S9] - 8
    excess[00:30] >= x[S9] + x[S10] - 7
    ...
    excess[07:00] >= x[S1] + x[S2] + x[S9] - 20
    excess[07:30] >= x[S1] + x[S2] + x[S9] - 25
    excess[08:00] >= x[S1] + x[S2] + x[S3] + x[S4] - 45
    excess[08:30] >= x[S1] + x[S2] + x[S3] + x[S4] - 60
    excess[09:00] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[PT1] - 80
    excess[09:30] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[PT1] - 90
    excess[10:00] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT1]+x[PT2] - 95
    excess[10:30] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT1]+x[PT2] - 100
    excess[11:00] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT1]+x[PT2] - 100
    excess[11:30] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT1]+x[PT2] - 95
    excess[12:00] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT1]+x[PT2] - 85
    excess[12:30] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT2] - 80
    excess[13:00] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT2] - 75
    excess[13:30] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT2] - 70
    excess[14:00] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8] - 65
    excess[14:30] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8] - 60
    excess[15:00] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8] - 55
    excess[15:30] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8] - 50
    excess[16:00] >= x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8] - 45
    excess[16:30] >= x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8] - 40
    excess[17:00] >= x[S5]+x[S6]+x[S7]+x[S8]+x[S10] - 35
    excess[17:30] >= x[S5]+x[S6]+x[S7]+x[S8]+x[S10] - 30
    excess[18:00] >= x[S7]+x[S8]+x[S10] - 25
    excess[18:30] >= x[S7]+x[S8]+x[S10] - 20
    excess[19:00] >= x[S10]+x[PT3] - 18
    excess[19:30] >= x[S10]+x[PT3] - 15
    excess[20:00] >= x[S10]+x[PT3] - 12
    ... (diğer aktif slotlar)

    excess[slot] >= 0    ∀ aktif slot

    # ===== K8: SLOT CAP — SC_EXCESS TANIMI =====
    # Band 07:00-09:00 (max_ratio=1.05)
    sc_excess[07:00] >= x[S1]+x[S2]+x[S9] - 21                                # cap=⌈20×1.05⌉
    sc_excess[07:30] >= x[S1]+x[S2]+x[S9] - 27                                # cap=⌈25×1.05⌉
    sc_excess[08:00] >= x[S1]+x[S2]+x[S3]+x[S4] - 48                          # cap=⌈45×1.05⌉
    sc_excess[08:30] >= x[S1]+x[S2]+x[S3]+x[S4] - 63                          # cap=⌈60×1.05⌉

    # Band 09:00-10:00 (max_ratio=1.25)
    sc_excess[09:00] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[PT1] - 100     # cap=⌈80×1.25⌉
    sc_excess[09:30] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[PT1] - 113     # cap=⌈90×1.25⌉

    # Band 10:00-11:00 (max_ratio=1.30)
    sc_excess[10:00] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT1]+x[PT2] - 124  # cap=⌈95×1.30⌉
    sc_excess[10:30] >= x[S1]+x[S2]+x[S3]+x[S4]+x[S5]+x[S6]+x[S7]+x[S8]+x[PT1]+x[PT2] - 130  # cap=⌈100×1.30⌉

    sc_excess[slot] >= 0    ∀ slot in band


VARIABLES:
    x[S1], x[S2], x[S3], x[S4], x[S5], x[S6], x[S7], x[S8], x[S9], x[S10] >= 0, Integer
    x[PT1], x[PT2], x[PT3] >= 0, Integer
    y[S1], y[S2], y[S3], y[S4], y[S5], y[S6], y[S7], y[S8], y[S9], y[S10] ∈ {0, 1}
    y[PT1], y[PT2], y[PT3] ∈ {0, 1}
    excess[00:00], excess[00:30], ..., excess[23:30] >= 0, Continuous
    sc_excess[07:00], sc_excess[07:30], ..., sc_excess[10:30] >= 0, Continuous

================================================================================
```

---

# 7. CONFIG PARAMETRELERİ (v10.9)

```python
CONFIG = {
    'queues': {
        'kitle': {
            'label': 'Kitle',
            'actual_name': 'kitle_cagrilar',
            'companies': ['inhouse', 'outsource'],
        },
        'kurumsal': {
            'label': 'Kurumsal',
            'actual_name': 'kurumsal_cagrilar',
            'companies': ['inhouse'],
        },
        'gold': {
            'label': 'Gold',
            'actual_name': 'gold_cagrilar',
            'companies': ['inhouse'],
        }
    },

    'sub_queues': {},          # load_aht_from_df() ile doldurulur
    'aht_overrides': {...},    # Manuel saat bazlı AHT override
    'default_aht': 150,

    'part_time': {
        'enabled': True,
        'shifts': ['09:00-13:00', '10:00-14:00', '19:00-23:00'],
        'count': {'kitle': 32, 'kurumsal': 0, 'gold': 0}
    },

    'erlang': {
        'target_asa': 30,
        'shrinkage': {9: 0.20, 10: 0.12, ..., 'default': 0.0},
        'interval_minutes': 30,
    },

    'outsource_ratio': {
        'kitle': {'min': 0.60, 'max': 0.65},
        'kurumsal': None,
        'gold': None
    },

    'mip': {
        'cost_inhouse': 1.0,
        'cost_outsource': 1.0,
        'min_per_shift': 5
    },

    'rr_penalty': {
        'enabled': True,
        'peak_exempt': True,
        'penalty_per_person': 4.0,
        'peak_penalty': 2.0,
        'peak_threshold': 0.90,
        'night_multiplier': {
            'enabled': True,
            'hours': {'start': '02:00', 'end': '07:00'},
            'multiplier': 100.0
        }
    },

    'slot_cap': {
        'enabled': True,
        'queues': ['kitle'],
        'bands': [
            {'start': '07:00', 'end': '09:00', 'max_ratio': 1.05, 'penalty': 50.0},
            {'start': '09:00', 'end': '10:00', 'max_ratio': 1.25, 'penalty': 50.0},
            {'start': '10:00', 'end': '11:00', 'max_ratio': 1.30, 'penalty': 50.0},
        ]
    },

    'small_shift_penalty': {
        'enabled': True,
        'penalty': 10
    },

    'time_cost_multipliers': {
        'kitle': {
            'inhouse': {'07:00': 1.5, '07:30': 1.3},
            'outsource': {}
        },
        'default': {
            'inhouse': {'07:00': 1.5, '07:30': 1.3},
            'outsource': {}
        }
    },

    'inhouse_only_subqueues': {
        'kitle': [],
        'kurumsal': [],
        'gold': []
    },

    'outsource_only_subqueues': {
        'kitle': [
            {'sub_queue': 'kayipcalintisupheli', 'min_ratio': 1.0,
             'hours': {'start': '08:00', 'end': '00:00'}},
        ],
        'kurumsal': [],
        'gold': []
    },

    'hourly_report': {
        'rapor_etkisi': {9: 0.04, ..., 'default': 0.04},
        'kapasite_kaybi': {9: 0.16, 10: 0.08, ..., 'default': 0.08},
        'cagri_adedi': {'default': 15},
    },

    'queue_overrides': {
        'kitle': {
            'cumartesi': {'erlang': {'shrinkage': {...}}},
            'pazar': {'erlang': {'shrinkage': {...}}},
        }
    }
}
```

---

# 8. PİPELİNE AKIŞI

## 8.1 Ana Akış: `run_queue_pipeline()`

```
[1/4] VERİ HAZIRLAMA
      │
      ├── Gün tipi belirleme (haftaiçi / cumartesi / pazar)
      ├── Queue override uygulama (deep merge)
      ├── prepare_calls_30(): Çağrı verisini 30dk slotlara dönüştür
      │     └── Alt kuyruk bazında çağrı sayıları
      └── Weighted AHT hesaplama (sub-queue × çağrı ağırlıklı)
      │
      ▼
[2/4] ERLANG HESAPLAMA
      │
      ├── calculate_erlang_all(): Her slot + kuyruk için Erlang-C
      │     ├── traffic = (calls × aht/60) / 30
      │     ├── ASA hedefini sağlayan minimum ajan bul
      │     └── Saatlik shrinkage uygula
      ├── _build_subqueue_min_slots(): Alt kuyruk minimumları hesapla
      │     ├── Inhouse-only alt kuyruk minimumları
      │     └── Outsource-only alt kuyruk minimumları
      │
      ▼
[3/4] MIP OPTİMİZASYON
      │
      ├── create_shift_coverage(): Vardiya → slot eşleştirmesi
      ├── Part-time vardiya ekleme (hafta sonu ise)
      ├── Maliyet hesaplama (base × time_multiplier)
      ├── RR Penalty excess değişkenleri ve maliyetleri
      ├── Slot Cap excess değişkenleri ve maliyetleri
      ├── Kısıtlar:
      │     ├── K1: Erlang ≥ ihtiyaç
      │     ├── K2: Outsource oran aralığı
      │     ├── K3: Shift aktivasyon + minimum kişi
      │     ├── K4: Part-time toplam (hafta sonu)
      │     ├── K5: Inhouse-only alt kuyruk min
      │     └── K6: Outsource-only alt kuyruk min
      ├── PuLP CBC Solver
      │
      ▼
[4/4] RAPOR
      │
      ├── get_actual_summary(): Gerçek çalışan verisi
      ├── print_queue_report(): Detaylı rapor
      │     ├── Kişi bazlı MIP vs Gerçek karşılaştırma
      │     ├── Günlük kapasite hesabı
      │     ├── Erken saat başlangıçları raporu
      │     ├── Küçük atamalı shift'ler raporu
      │     ├── RR Penalty raporu
      │     ├── Slot Cap raporu
      │     ├── Ek kapasite analizi (dış arama / atıl)
      │     ├── Shift atamaları listesi
      │     ├── Slot bazlı detay (eşzamanlı çalışan)
      │     └── Slot bazlı kapasite raporu (30dk)
      └── Sonuç dict döndür
```

## 8.2 Çoklu Kuyruk: `run_all_queues()`

Tüm kuyrukları sırasıyla çalıştırır ve toplu özet rapor üretir. Her kuyruk kendi override config'i ile çalışır.

## 8.3 Excel Export: `export_to_excel()`

Birden fazla tarih ve kuyruk için:
- **Vardiya_Atamaları**: shift bazlı atamalar
- **Slot_Karşılaştırma**: slot bazlı MIP vs Gerçek + kapasite raporu
- **Özet**: günlük toplam metrikler

---

# 9. ÇIKTI YAPISI

## 9.1 assignments dict

```python
assignments = {
    'shift_08_00_inhouse': 35,
    'shift_08_00_outsource': 45,
    'shift_09_00_inhouse': 50,
    'shift_09_00_outsource': 70,
    'shift_10_00_inhouse': 25,
    'shift_10_00_outsource': 40,
    'shift_00_00_inhouse': 20,
    'shift_17_00_outsource': 30,
    'pt_09_00_13_00': 10,
    'pt_10_00_14_00': 12,
    'pt_19_00_23_00': 10,
}
```

## 9.2 mip_info dict

```python
mip_info = {
    'assignments': {...},
    'shift_coverage': {...},
    'mip_by_slot': {'07:00': 20, '08:00': 80, ...},
    'mip_in_by_slot': {'07:00': 20, '08:00': 35, ...},
    'mip_out_by_slot': {'07:00': 0, '08:00': 45, ...},
    'mip_pt_by_slot': {'09:00': 10, '10:00': 22, ...},
    'total_kisi': 315,
    'total_inhouse_kisi': 130,
    'total_outsource_kisi': 155,
    'total_part_time_kisi': 32,
    'pt_available': 32,
    'outsource_ratio': 0.587,
    'cost_details': [...],
    'early_starts': {...},
    'early_total': 0,
    'early_penalty': 0,
    'inhouse_min_by_slot': {...},
    'outsource_min_by_slot': {...},

    # Small shift penalty
    'small_shift_penalty_enabled': True,
    'small_shift_count': 8,
    'small_shift_total_penalty': 80.0,
    'small_shifts_detail': [...],

    # RR Penalty
    'rr_penalty_enabled': True,
    'rr_excess_by_slot': {'09:30': 3, '14:00': 2, ...},
    'rr_total_excess': 12,
    'rr_total_penalty_cost': 38.0,
    'rr_penalized_slots': 5,
    'rr_peak_slots': {'10:00', '10:30', '11:00', ...},

    # Slot Cap
    'slot_cap_detail': [...],
    'sc_total_excess': 0,
    'sc_total_penalty_cost': 0,
    'sc_penalized_slots': 0,
}
```

---

# 10. KAPASİTE HESABI

## 10.1 Günlük Kapasite

`calculate_daily_capacity()` fonksiyonu, MIP atamaları üzerinden günlük çağrı kapasitesini hesaplar:

```
cap_per_person = (duration_sn / avg_aht) × efficiency
total_capacity = Σ cap_per_person × count
```

| Company | Efficiency |
|---------|-----------|
| inhouse | 0.70 |
| outsource | 0.70 |
| part_time | 0.80 |

## 10.2 Slot Bazlı Kapasite Raporu

`hourly_report` config'i ile 30 dakikalık slot bazında detaylı kapasite analizi:

```
rapor_etkisi = kapasite × re_oran[saat]       (personel rapor zamanı kaybı)
kapasite_kaybi = kapasite × kk_oran[saat]     (shrinkage kaynaklı kayıp)
net_mt = kapasite - rapor_etkisi - kapasite_kaybi
cagri_kapasitesi = net_mt × (cagri_adedi / 2)  (30dk slottaki çağrı kapasitesi)
response_rate = cagri_kapasitesi / gelen_cagri
```

## 10.3 Ek Kapasite Analizi

MIP atamasının Erlang'ı aştığı slotlarda fazla kapasite raporlanır:

| Metrik | Saat Aralığı | Açıklama |
|--------|-------------|----------|
| Dış Arama Kapasitesi | 09:00-20:00 | Gündüz saatlerindeki fazla personel → dış arama yapılabilir |
| Atıl Kapasite | 20:00-09:00 | Gece saatlerindeki fazla personel → atıl, önlenemez |

---

# 11. ÖZET

MIP modeli v10.9 şu adımlarla çalışır:

1. **Veri hazırlama** — çağrıları 30dk slotlara dönüştür, weighted AHT hesapla
2. **Erlang-C** ile slot bazlı personel ihtiyacı hesapla (saatlik shrinkage ile)
3. **Alt kuyruk analizi** — inhouse/outsource minimum ihtiyaçları hesapla
4. **MIP modeli** kur:
   - Amaç: Temel maliyet + small shift penalty + RR penalty + slot cap penalty → minimize et
   - Hard kısıtlar: Erlang karşılama, outsource oranı, shift aktivasyon, part-time toplam, alt kuyruk minimumları
   - Soft kısıtlar: RR penalty (3 seviyeli ceza), slot cap (aralık bazlı üst sınır)
5. **PuLP CBC Solver** ile optimal çözümü bul
6. **Rapor** — MIP vs gerçek karşılaştırma, kapasite analizi, detaylı metrikler

Model, tüm hard kısıtları sağlayan ve soft kısıtların toplam cezasını minimize eden **en düşük maliyetli** vardiya dağılımını bulur.
