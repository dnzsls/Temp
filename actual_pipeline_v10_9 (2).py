# Workforce Scheduling Optimization Pipeline
## Model Geliştirme + Forecast — Teknik Dokümantasyon

**Versiyon:** v10.9
**Tarih:** Nisan 2026

Bu doküman, çağrı merkezi vardiya optimizasyon sisteminin tam teknik dokümantasyonunu içerir. İki pipeline kapsar:
- **Model Geliştirme** (gerçekleşen veriyle analiz ve tuning)
- **Forecast** (gelecek tahminleriyle vardiya planlama)

### v10.9 Değişiklikler
- Pattern / geçmiş veri analizi **kaldırıldı**
- Occupancy **kaldırıldı** (Erlang-C'ye dahil)
- **Queue overrides** eklendi (kuyruk + gün tipi bazlı farklı config)
- **3 seviyeli RR penalty** eklendi (peak / gündüz / gece)
- **Slot Cap** eklendi (saat aralığı bazlı üst sınır)
- **Small Shift Penalty** eklendi (her aktif shift için sabit ceza)
- **Saatlik shrinkage** (saat bazlı dict)
- **Inhouse-only / Outsource-only alt kuyruk** kısıtları eklendi
- Excel'e kapasite raporu ve TOPLAM satırları eklendi

### İki Pipeline Farkı

| Özellik | Model Geliştirme (Actual) | Forecast |
|---------|--------------------------|----------|
| Çağrı verisi | Uzun format (15dk) | Geniş format (15dk) |
| Gerçek veri karşılaştırma | Var (MIP vs Gerçek) | Yok |
| Rapor | MIP vs Gerçek + kapasite raporu | Sadece MIP + kapasite raporu |
| Kullanım | Config tuning, parametre test | Üretim vardiya planı |

---

# 1. VERİ AKIŞI VE DATAFRAME BAĞLANTILARI

## 1.1 Adım Adım Akış

### Adım 0: Veri Yükleme

Excel dosyalarından DataFrame'ler oluşturulur ve CONFIG'e AHT yüklenir.

```python
df_calls = pd.read_excel('cagri.xlsx')        # 15dk, uzun format
df_actual = pd.read_excel('actual.xlsx')      # gerçekleşen vardiyalar
df_shifts_dict = {
    'kitle': pd.read_excel('vardiyalar_kitle.xlsx'),    # her kuyruk ayrı
    'kurumsal': pd.read_excel('vardiyalar_kurumsal.xlsx'),
    'gold': pd.read_excel('vardiyalar_gold.xlsx')
}
df_aht = pd.read_excel('aht.xlsx')

# AHT'yi CONFIG'e yükle:
CONFIG['sub_queues'] = load_aht_from_df(df_aht)
# → CONFIG['sub_queues']['kitle']['aht']['retention_line'][9] = 185
```

### Adım 1: Queue Override (Otomatik)

Pipeline başında tarih kontrol edilir. Cumartesi/pazar ise ilgili kuyruğun override'i CONFIG'e deep merge edilir.

```
Tarih: 2026-02-23 (Pazar)
→ override_key = 'pazar'
→ CONFIG['queue_overrides']['kitle']['pazar'] varsa merge et
→ Shrinkage, rr_penalty, hourly_report vs. pazar değerleri aktif
```

### Adım 2: prepare_calls_30(df_calls)

**Giriş:** df_calls — 15 dakikalık uzun format çağrı verisi.

**Ne yapar:** 15dk veriyi 30dk slotlara aggregate eder. Her kuyruk için toplam çağrı kolonu ve her alt kuyruk için ayrı çağrı kolonu oluşturur.

**Çıkış:** df_calls_30

```
GİRİŞ (df_calls):
data_date  | min_time_period_value | resource_group_key | nof_call
2026-01-15 | 09:00                 | retention_line     | 45
2026-01-15 | 09:15                 | retention_line     | 52
2026-01-15 | 09:00                 | kart_temel         | 120
2026-01-15 | 09:15                 | kart_temel         | 135

ÇIKIŞ (df_calls_30): 15dk → 30dk aggregate + kuyruk/sq kolonları
data_date  | slot_30 | retention_line_calls | kart_temel_calls | kitle_total
2026-01-15 | 09:00   | 97                   | 255              | 806
```

### Adım 3: calculate_erlang_all(df_calls_30)

**Giriş:** df_calls_30 + CONFIG (AHT, shrinkage).

**Ne yapar:** Her slot ve kuyruk için: (1) alt kuyruk bazlı weighted AHT hesaplar, (2) Erlang-C ile raw agent bulur, (3) shrinkage ekler.

**Çıkış:** erlang_by_slot dict ve weighted_aht_by_slot dict.

```
Slot 09:00, Kitle:
1. Weighted AHT: retention=97 çağrı*185sn + kart=255 çağrı*195sn
   → (97*185 + 255*195) / 352 = 192sn
2. Erlang: traffic = 352*(192/60)/30 = 37.5
   → raw = 52 agent (ASA<=30sn)
3. Shrinkage (saat 9) = 0.20
   → final = ceil(52 / 0.80) = 65

ÇIKIŞ: erlang_by_slot['09:00'] = 65
```

### Adım 3.5: _build_subqueue_min_slots()

**Giriş:** df_calls_30 + erlang_by_slot + CONFIG (inhouse/outsource_only_subqueues).

**Ne yapar:** Alt kuyruk çağrı payına oranlı inhouse/outsource minimum hesaplar.

**Çıkış:** inhouse_min_by_slot, outsource_min_by_slot dict.

```
Slot 09:00: Erlang=65, retention_line çağrı payı=97/352=%27.6
→ inhouse_min = ceil(65 * 0.276 * 1.0) = 18
→ Bu slotta en az 18 inhouse agent olmalı
```

### Adım 4: optimize_queue(erlang_by_slot, df_shifts)

**Giriş:** erlang_by_slot + df_shifts (vardiya tanımları) + inhouse/outsource min + CONFIG (mip, rr_penalty, slot_cap, small_shift_penalty).

**Ne yapar:**
1. Vardiya kapsamları hesaplar (hangi shift hangi slotları kapsar)
2. Hafta sonu ise part-time vardiyaları ekler
3. MIP modeli kurar:
   - Amaç: temel maliyet + small_shift_penalty + RR penalty + slot_cap penalty (minimize)
   - Hard kısıtlar: Erlang, shift aktivasyon+min, part-time toplam, outsource oranı, alt kuyruk min
   - Soft kısıtlar: RR penalty, slot cap, saat çarpanları
4. PuLP/CBC solver ile çözer

**Çıkış:** assignments{shift: kişi_sayısı}, mip_info dict.

```
Giriş: erlang_by_slot = {'09:00': 65, '09:30': 72, '10:00': 95, ...}
       df_shifts: V08 08:00-17:00 inhouse, V09 09:00-18:00 outsource, ...

create_shift_coverage():
  V08_inhouse  → slotlar: ['08:00','08:30','09:00',...,'16:30']
  V09_outsource → slotlar: ['09:00','09:30','10:00',...,'17:30']

MIP çözer:
  V08_inhouse: 35 kişi, V09_outsource: 50 kişi, ...

ÇIKIŞ:
  assignments = {'V08_inhouse': 35, 'V09_outsource': 50, ...}
  mip_by_slot = {'09:00': 85, '09:30': 85, '10:00': 120, ...}
```

### Adım 5: get_actual_summary(df_actual)

**Giriş:** df_actual (gerçekleşen vardiya verisi).

**Ne yapar:** Her slot için gerçekte kaç kişi çalışıyordu hesaplar (inhouse/outsource ayrı).

**Çıkış:** actual dict (slot_total, slot_in, slot_out, kisi_total).

```
df_actual satırları: V08 08:00-17:00 inhouse 35 kişi
→ slot 09:00'da bu 35 kişi aktif (çünkü 08:00-17:00 arası)
→ slot 18:00'da bu 35 kişi yok (çünkü vardiya bitmiş)

ÇIKIŞ: actual['slot_total']['09:00'] = 82 (35 inhouse + 47 outsource)
```

### Adım 6: print_queue_report()

**Giriş:** mip_info + actual + weighted_aht_by_slot + calls_by_slot + CONFIG (hourly_report).

**Ne yapar:**
1. MIP vs Gerçek karşılaştırma tablosu
2. Günlük kapasite hesabı + günlük RR
3. Erken saat başlangıçları, küçük atamalı shift'ler, RR penalty, slot cap raporları
4. Ek kapasite analizi (dış arama / atıl)
5. Slot bazlı detay (eşzamanlı çalışan)
6. Slot bazlı kapasite raporu (rapor etkisi + kapasite kaybı → Net MT → çağrı kapasitesi → RR)

```
Slot 12:00: MIP=316, Gerçek=310, Fark=+6
Kapasite raporu:
  Kapasite=316 - Rapor_Etkisi(316*0.04=13) - Kap_Kaybı(316*0.09=28)
  = Net_MT=275
  Cagri_Kap = 275 * (15/2) = 2062
  RR = 2062 / 2393 = 86%
```

## 1.2 Özet Akış Diyagramı

```
df_calls   ──→ prepare_calls_30()      ──→ df_calls_30 ─┐
                                                         ├──→ calculate_erlang_all()
df_aht     ──→ load_aht_from_df()      ──→ CONFIG AHT ──┘            │
                                                                       │
                                                                       ▼
                                                              erlang_by_slot,
                                                              weighted_aht_by_slot
                                                                       │
df_shifts_dict  ───────────────────────────────────────────────────────┤
                                                                       │
df_calls_30 ──→ _build_subqueue_min_slots() ──→ inhouse_min,         ──┤
                                                outsource_min          │
                                                                       │
CONFIG (mip, rr_penalty, slot_cap, small_shift_penalty) ──────────────┤
                                                                       ▼
                                                           optimize_queue()
                                                                       │
                                                          assignments, mip_info
                                                                       │
df_actual  ──→ get_actual_summary()    ──→ actual ─────────────────────┤
                                                                       ▼
CONFIG (hourly_report) ──→ print_queue_report() ──→ KONSOL RAPORU
                                                                       │
                                          export_to_excel() ──→ Excel Çıktı
```

---

# 2. GİRDİ VERİLERİ

## 2.1 df_calls — Çağrı Verisi (Model Geliştirme)

Uzun format, 15 dakikalık zaman dilimleri.

| Kolon | Tip | Örnek | Açıklama |
|-------|-----|-------|----------|
| data_date | datetime | 2026-01-15 | Çağrı tarihi |
| min_time_period_value | string | 09:15 | 15dk zaman dilimi |
| resource_group_key | string | retention_line | Alt kuyruk adı |
| line_based_main_group | string | kitle_cagrilar | Ana kuyruk adı |
| nof_call | int | 145 | Çağrı sayısı |

`prepare_calls_30()` ile 30dk slotlara aggregate edilir. Alt kuyruk kolonları (`{sq}_calls`) ve toplam (`{kuyruk}_total`) oluşturulur.

## 2.2 df_forecast — Çağrı Verisi (Forecast)

Geniş format, 15 dakikalık. Her satır tüm kuyruk çağrılarını içerir.

| Kolon | Tip | Örnek | Açıklama |
|-------|-----|-------|----------|
| model_data_date | string | 18.02.2026 09:15 | Timestamp (00:00 için saat yok) |
| truncddate | string | 18.02.2026 | Tarih |
| KITLE_NOF_CALL | int | 850 | Kitle toplam |
| KURUMSAL_NOF_CALL | int | 120 | Kurumsal toplam |
| GOLD_NOF_CALL | int | 45 | Gold toplam |

## 2.3 df_shifts — Vardiya Tanımları

| Kolon | Tip | Örnek | Açıklama |
|-------|-----|-------|----------|
| shift | string | V08 | Vardiya kodu |
| start | string | 08:00 | Başlangıç saati |
| end | string | 17:00 | Bitiş saati |
| company | string | inhouse | inhouse veya outsource |

```python
df_shifts_dict = {
    'kitle': pd.read_excel('vardiyalar_kitle.xlsx'),
    'kurumsal': pd.read_excel('vardiyalar_kurumsal.xlsx'),
    'gold': pd.read_excel('vardiyalar_gold.xlsx'),
}
```

Outsource bitiş saati otomatik +30dk uzatılır (molasız çalışma). `create_shift_coverage()` her shift'in hangi slotları kapladığını hesaplar.

## 2.4 df_actual — Gerçekleşen Vardiya

| Kolon | Tip | Açıklama |
|-------|-----|----------|
| working_date | datetime | Çalışma tarihi |
| line_based_main_group | string | Kuyruk adı (kitle_cagrilar) |
| shifts_start_hour | string | Vardiya başlangıç (08:00) |
| shifts_end_hour | string | Vardiya bitiş (17:00) |
| outsource_flg | int | 0=inhouse, 1=outsource |
| weekend_flg | int | 0=haftaiçi, 1=haftasonu |
| calisan_kisi_sayisi | int | Çalışan kişi sayısı |

`get_actual_summary()` ile slot bazlı gerçek veriye dönüştürülür. MIP sonuçlarıyla karşılaştırılır.

## 2.5 df_aht — AHT Verisi

| Kolon | Tip | Açıklama |
|-------|-----|----------|
| saat | int | Saat (0-23) |
| sub_queue | string | Alt kuyruk adı |
| line_based_main_group | string | Ana kuyruk adı |
| weighted_avg_aht | int | AHT (saniye) |

```python
CONFIG['sub_queues'] = load_aht_from_df(df_aht)
# → sub_queues[kuyruk]['aht'][alt_kuyruk][saat] = AHT
```

---

# 3. ÇALIŞAN TİPLERİ VE KUYRUK YAPISI

## 3.1 Kuyruklar

| Kuyruk | Çalışanlar | Out Oranı | Açıklama |
|--------|------------|-----------|----------|
| Kitle | Inhouse + Outsource + PT | %60-65 | Yüksek hacimli |
| Kurumsal | Sadece Inhouse | - | Kurumsal hat |
| Gold | Sadece Inhouse | - | Premium hat |

## 3.2 Çalışan Tipleri

| Tip | MIP Cost | Saat Çarpanı | Outsource Oranı | Açıklama |
|-----|----------|--------------|-----------------|----------|
| Inhouse | 1.0 | 07:00→1.5x, 07:30→1.3x | Inhouse tarafında | Şirket bünyesi |
| Outsource | 1.0 | - | Outsource tarafında | Dış kaynak, bitiş+30dk |
| Part-time | 1.0 | Inhouse çarpanları | Inhouse tarafında | Sadece haftasonu |

### Part-time Kuralları

| Kural | Açıklama |
|-------|----------|
| Haftaiçi | PT yok (`pt_available = 0`) |
| Ayın ilk 3 günü | PT yok (hafta sonu olsa bile) |
| Cumartesi | Toplam PT // 2 (yarım kadro) |
| Pazar | Toplam PT - yarım = kalan kadro |
| Ayın son cumartesisi | Tam kadro |

## 3.3 Alt Kuyruk Kısıtları

Bazı alt kuyruklar sadece inhouse veya sadece outsource tarafından karşılanabilir.

```
Minimum ihtiyaç = ⌈erlang × (sq_calls / total_calls) × min_ratio⌉
```

```python
'inhouse_only_subqueues': {
    'kitle': [
        # 'retention_line',                                # tüm Erlang oranı
        # {'sub_queue': 'kart_temel', 'min_ratio': 0.30}   # Erlang oranının %30'u
    ]
}

'outsource_only_subqueues': {
    'kitle': [
        {'sub_queue': 'kayipcalintisupheli', 'min_ratio': 1.0,
         'hours': {'start': '08:00', 'end': '00:00'}}
    ]
}
```

`hours` parametresi tanımlıysa kısıt sadece o aralıkta uygulanır.

---

# 4. ERLANG-C AGENT HESABI

## 4.1 Hesap Adımları

1. **Weighted AHT** hesapla (öncelik: override > sub-queue > default)
   ```
   calculate_weighted_aht(row, queue, slot)
   ```

2. **Traffic** = (çağrı × (AHT/60)) / 30
   ```
   Örnek: 2393 çağrı, AHT=190sn → traffic=252.6
   ```

3. **Raw agent**: ASA<=30sn sağlayan minimum
   ```
   280 agent → 252 meşgul + 28 tampon (bekleme için)
   ```

4. **Shrinkage** (mola kaybı):
   ```
   final = ceil(280 / (1 - 0.13)) = 322
   322 atanır, 42 molada, 280 hatta → Erlang karşılandı
   ```

## 4.2 Shrinkage

Saat bazlı dict. Mola, tuvalet, eğitim gibi 'hatta olmama' kayıplarını kapsar.

```python
'shrinkage': {
    0: 0.03, 1: 0.03, 2: 0.03, ..., 6: 0.03,
    7: 0.03, 8: 0.03, 9: 0.20, 10: 0.12,
    11: 0.11, 12: 0.13, 13: 0.20, 14: 0.17,
    15: 0.23, 16: 0.25, 17: 0.22, 18: 0.16,
    19: 0.13, 20: 0.16, 21: 0.11, 22: 0.14, 23: 0.12,
    'default': 0.0
}
```

## 4.3 Erlang ve Tampon

Erlang "280 agent hatta olsun" dediğinde hepsi aynı anda çağrı almaz. Ortalama 252 meşgul, 28 boşta bekler — yeni çağrıları hemen karşılar. Bu tampon (occupancy) Erlang'in içinde. Ayrıca occupancy parametresi eklemeye gerek yok (v10.9'da kaldırıldı).

---

# 5. MIP OPTİMİZASYON MODELİ

## 5.1 Değişkenler

| Değişken | Tip | Açıklama |
|----------|-----|----------|
| x[s] | Integer >= 0 | Shift s için atanan kişi sayısı |
| y[s] | Binary {0,1} | Shift s aktif mi |
| excess[slot] | Continuous >= 0 | Erlang üstü fazlalık (RR penalty için) |
| sc_excess[slot] | Continuous >= 0 | Slot cap aşımı |

## 5.2 Amaç Fonksiyonu (4 Bileşen)

```
MINIMIZE:
    Σ x[s] × cost × multiplier      # 1. Temel kişi maliyeti
  + Σ y[s] × small_shift_penalty    # 2. Shift açma cezası (10)
  + Σ excess[slot] × rr_penalty     # 3. 3 seviyeli RR penalty
  + Σ sc_excess[slot] × band_penalty  # 4. Slot cap penalty
```

### 3 Seviyeli RR Penalty

| Seviye | Koşul | Ceza | Mantık |
|--------|-------|------|--------|
| Peak | Erlang >= max × peak_threshold | 2.0/kişi | Yoğun saatlerde fazlalık normal |
| Gündüz | Peak değil, gece değil | 4.0/kişi | Orta ceza |
| Gece | night_multiplier saatleri (02:00-07:00) | 4.0 × 100.0 = 400/kişi | Gece fazlalık en pahalı |

### Slot Cap (Bands)

```python
'slot_cap': {
    'enabled': True,
    'queues': ['kitle'],
    'bands': [
        {'start': '07:00', 'end': '09:00', 'max_ratio': 1.05, 'penalty': 50.0},
        {'start': '09:00', 'end': '10:00', 'max_ratio': 1.25, 'penalty': 50.0},
        {'start': '10:00', 'end': '11:00', 'max_ratio': 1.30, 'penalty': 50.0},
    ]
}
```

Her band için:
```
cap[slot] = max(⌈erlang_need[slot] × max_ratio⌉, 3)
sc_excess[slot] = max(0, atama - cap)
```

---

# 6. KISITLAR

| Kısıt | Tip | Açıklama |
|-------|-----|----------|
| **K1**: Erlang | HARD | Her aktif slotta toplam atama >= Erlang (shrinkage dahil) |
| **K2**: Outsource Oranı | HARD | (1-min)×t_out >= min×t_in ve (1-max)×t_out <= max×t_in |
| **K3**: Shift Aktivasyon | HARD | x[s] <= 500×y[s] ve x[s] >= min_per_shift×y[s] |
| **K4**: Part-time Toplam | HARD | Σ x[pt] == pt_available (hafta sonu) |
| **K5**: Inhouse-only Min | HARD | Alt kuyruk bazlı inhouse+PT minimum |
| **K6**: Outsource-only Min | HARD | Alt kuyruk bazlı outsource minimum |
| **RR Penalty** | SOFT | excess[slot] >= Σx - erlang, amaç fonksiyonunda 3 seviyeli ceza |
| **Slot Cap** | SOFT | sc_excess[slot] >= Σx - cap, band bazlı ceza |
| **Saat Maliyet Çarpanı** | SOFT | 07:00 inhouse 1.5x gibi çarpanlar (final cost'ta) |
| **Shift Açma Cezası** | SOFT | Her aktif shift için sabit ceza (small_shift_penalty=10) |

**Not:** K2 sadece `outsource_ratio[queue]` tanımlı kuyruklarda (kitle) uygulanır. Kurumsal ve gold sadece inhouse'dur.

---

# 7. QUEUE OVERRIDES (Kuyruk + Gün Tipi Bazlı)

Farklı kuyruklar ve gün tipleri (haftaiçi/cumartesi/pazar) için farklı CONFIG değerleri kullanılabilir. Deep merge ile sadece değişen anahtarlar yazılır, geri kalan ana CONFIG'ten gelir.

## 7.1 Gün Tipi Belirleme

Pipeline başında tarih kontrol edilir:
- Pazartesi-Cuma → `'haftalici'`
- Cumartesi → `'cumartesi'`
- Pazar → `'pazar'`

Override varsa CONFIG deep merge edilir (deepcopy ile, orijinal bozulmaz).

## 7.2 Deep Merge Mantığı

Sadece değişen anahtarlar yazılır. İç içe dict'ler recursive merge edilir.

```python
# Ana CONFIG:
rr_penalty: {
    enabled: True, penalty_per_person: 4.0, peak_penalty: 2.0,
    night_multiplier: {enabled: True, multiplier: 100.0}
}

# Override (sadece penalty değişti):
cumartesi: {rr_penalty: {penalty_per_person: 6.0}}

# Sonuç (merge):
rr_penalty: {
    enabled: True, penalty_per_person: 6.0, peak_penalty: 2.0,
    night_multiplier: {enabled: True, multiplier: 100.0}
}
# → sadece penalty_per_person değişti, geri kalan korundu
```

## 7.3 Override Örneği

```python
'queue_overrides': {
    'kitle': {
        'cumartesi': {
            'erlang': {
                'shrinkage': {9: 0.15, 10: 0.10, ..., 'default': 0.05}
            },
        },
        'pazar': {
            'erlang': {
                'shrinkage': {9: 0.12, 10: 0.08, ..., 'default': 0.03}
            },
            # 'rr_penalty': {'penalty_per_person': 6.0},
            # 'hourly_report': {
            #     'kapasite_kaybi': {9: 0.12, 12: 0.07, 'default': 0.05}
            # },
        },
        # 'haftalici': {} → boş bırakılırsa ana CONFIG kullanılır
    },
    # 'kurumsal': {...},
    # 'gold': {...},
}
```

Override tanımlanmayan kuyruk/gün için ana CONFIG kullanılır. Raporda `📌 Override aktif: kitle/cumartesi → ['erlang']` gösterilir.

---

# 8. RAPOR VE EXCEL ÇIKTI

## 8.1 Konsol Raporu

| Bölüm | İçerik |
|-------|--------|
| Özet | MIP vs Gerçek: toplam, inhouse, outsource, PT, outsource %, peak |
| Günlük Kapasite | Avg AHT, toplam kapasite (in/out/pt), response rate |
| Erken Saat Başlangıçları | Time multiplier > 1 olan shift'ler ve ek penalty |
| Küçük Atamalı Shift'ler | Aktif shift'ler ve her birinin small_shift_penalty katkısı |
| RR Penalty | 3 seviyeli detay (peak, gündüz, gece) — slot bazlı fazlalık |
| Slot Cap | Band bazlı cap aşımları ve penalty |
| Ek Kapasite Analizi | Dış arama (09:00-20:00) vs Atıl (20:00-09:00) fazla kapasite |
| Shift Atamaları | Her shift: saat, tip, kişi, maliyet |
| Slot Bazlı (30dk) | AHT, Erlang, In/Out Min, MIP (Toplam/In/Out), Gerçek (Toplam/In/Out), Fark, RR, E.Fark |
| Slot Kapasite Raporu | Çağrı, Kap, R.Etk, K.Kay, NetMT, Ç.Kap, RR |

## 8.2 Kapasite Raporu Hesabı

```
Kapasite = MIP atamasi (slot bazlı)
Rapor_Etkisi = Kapasite × rapor_etkisi[saat]
Kap_Kaybı = Kapasite × kapasite_kaybi[saat]
Net_MT = Kapasite - Rapor_Etkisi - Kap_Kaybı
Cagri_Kap = Net_MT × (cagri_adedi / 2)
RR = Cagri_Kap / Gelen_Cagri
```

## 8.3 Excel Sheet'leri

| Sheet | İçerik | TOPLAM Satırı |
|-------|--------|---------------|
| Vardiya_Atamaları | Her shift: tarih, kuyruk, başlangıç, bitiş, company, kişi sayısı | Yok |
| Slot_Karşılaştırma | Her 30dk slot: AHT, Erlang, MIP (Toplam/In/Out/PT), Gerçek (Toplam/In/Out), Fark, RR, kapasite raporu (Çağrı, R.Etk, K.Kay, NetMT, Ç.Kap, Kap_RR) | Var (tüm kuyruklar toplanmış) |
| Özet | Her tarih/kuyruk: toplam kişi, çağrı, kapasite, Response_Rate_Günlük, Kapasite_RR_Günlük | Var (tüm kuyruklar toplanmış) |

## 8.4 TOPLAM Satırları

- **Özet TOPLAM**: Her tarih için tüm kuyrukların toplamı. Kapasite_RR_Günlük = tüm slot çağrı kapasitesi toplamı / tüm gelen çağrı toplamı (weighted average).
- **Slot TOPLAM**: Her slot için tüm kuyrukların MIP atamaları, çağrıları, rapor etkisi, kapasite kaybı, Net MT ve çağrı kapasitesi toplanır. Slot bazlı birleşik Kapasite_RR hesaplanır.

Her kuyruk **kendi override config'i** ile çalıştığı için TOPLAM hesabında her kuyruğun kapasite parametreleri ayrı uygulanır.

## 8.5 Dosya Adlandırma

```python
# Otomatik tarih bazlı:
export_to_excel(..., dates=['2026-02-22'])
# → vardiya_actual_20260222.xlsx

export_to_excel(..., dates=['2026-02-22', '2026-02-23'])
# → vardiya_actual_20260222_20260223.xlsx

# Manuel:
export_to_excel(..., output_file='benim_raporum.xlsx')
```

---

# 9. CONFIG REFERANS

| Bölüm | Parametreler |
|-------|--------------|
| **erlang** | `target_asa` (30), `shrinkage` (saat bazlı dict), `interval_minutes` (30) |
| **AHT** | `sub_queues` (load_aht_from_df), `aht_overrides` (manuel saat bazlı), `default_aht` (150) |
| **mip** | `cost_inhouse` (1.0), `cost_outsource` (1.0), `min_per_shift` (5) |
| **rr_penalty** | `enabled`, `peak_exempt`, `penalty_per_person` (4.0), `peak_penalty` (2.0), `peak_threshold` (0.90), `night_multiplier` (enabled, hours, multiplier=100.0) |
| **slot_cap** | `enabled`, `queues`, `bands` [{start, end, max_ratio, penalty}] |
| **small_shift_penalty** | `enabled`, `penalty` (10) |
| **outsource_ratio** | kitle: {min: 0.60, max: 0.65}, kurumsal: None, gold: None |
| **time_cost_multipliers** | Kuyruk bazlı saat çarpanları (07:00→1.5x, 07:30→1.3x); `default` fallback'i var |
| **hourly_report** | `rapor_etkisi`, `kapasite_kaybi`, `cagri_adedi` (saat bazlı dict) |
| **part_time** | `enabled`, `shifts`, `count` (kuyruk bazlı: kitle=32) |
| **inhouse_only_subqueues** | Kuyruk bazlı liste — string veya {sub_queue, min_ratio} |
| **outsource_only_subqueues** | Kuyruk bazlı liste — {sub_queue, min_ratio, hours?} |
| **capacity** | `efficiency`: inhouse=0.70, outsource=0.70, part_time=0.80 |
| **report** | `peak_threshold` (0.70) — slot bazlı raporda peak işareti için |
| **queue_overrides** | Kuyruk + gün tipi bazlı override (deep merge) |

---

# 10. PIPELINE AKIŞI

## 10.1 Model Geliştirme (4 Adım)

```
[1/4] Veri hazırlama
      prepare_calls_30(df_calls) → df_calls_30
      (Override ve gün tipi belirleme bu adımdan önce yapılır)

[2/4] Erlang hesaplama
      calculate_erlang_all(df_calls_30) → erlang_by_slot
                                        + weighted_aht_by_slot
      _build_subqueue_min_slots() → inhouse_min_by_slot
                                  → outsource_min_by_slot

[3/4] MIP optimizasyon
      optimize_queue(erlang_by_slot, df_shifts,
                     inhouse_min, outsource_min, target_date)
      → assignments, mip_info

[4/4] Rapor
      get_actual_summary() + print_queue_report()
```

## 10.2 Forecast (4 Adım — aynı mantık)

```
[1/4] prepare_forecast_calls_30(df_forecast)
[2/4] calculate_erlang_all()
[3/4] optimize_queue()
[4/4] print_queue_report_forecast() (gerçek veri yok)
```

---

# 11. JUPYTER KULLANIMI

## 11.1 Model Geliştirme

```python
# Hücre 1: CONFIG (config_v10_9.py yapıştır)
CONFIG = { ... }

# Hücre 2: Pipeline kodu (actual_pipeline_v10_9.py yapıştır)

# Hücre 3: Veri yükle
df_calls = pd.read_excel('cagri.xlsx')
df_actual = pd.read_excel('actual.xlsx')
df_shifts_dict = {
    'kitle': pd.read_excel('vardiyalar_kitle.xlsx'),
    'kurumsal': pd.read_excel('vardiyalar_kurumsal.xlsx'),
    'gold': pd.read_excel('vardiyalar_gold.xlsx'),
}
df_aht = pd.read_excel('aht.xlsx')
CONFIG['sub_queues'] = load_aht_from_df(df_aht)

# Hücre 4: Tek gün, tek kuyruk (override otomatik uygulanır)
result = run_queue_pipeline(
    df_calls, df_actual, df_shifts_dict, '2026-02-22', 'kitle')

# Hücre 5: Tüm kuyruklar
results = run_all_queues(
    df_calls, df_actual, df_shifts_dict, '2026-02-22')

# Hücre 6: Birden fazla gün
for d in ['2026-02-22', '2026-02-23']:
    results = run_all_queues(df_calls, df_actual, df_shifts_dict, d)

# Hücre 7: Excel export (tarih bazlı dosya adı)
dates = get_weekends(2026, 'subat')
export_to_excel(df_calls, df_actual, df_shifts_dict, dates)
```

---

# 12. BİLİNEN KONULAR

## 12.1 Vardiya Yapısı ve RR

MIP **vardiya bazlı atama** yapar, slot bazlı değil. Bir vardiya birden fazla slotu kapsar. Bazı slotlarda fazla, bazılarında tam Erlang olabilir. RR penalty dağılımı iyileştirir ama tam denge için uygun vardiya çeşitliliği gerekir.

3 seviyeli RR penalty + slot cap kombinasyonu:
- **Peak slotlar:** düşük ceza (2.0) → zirvede biraz fazlalık tolere edilir
- **Gündüz off-peak:** orta ceza (4.0) → gereksiz fazlalık caydırılır
- **Gece (02:00-07:00):** çok yüksek ceza (400.0) → gece fazla atama neredeyse imkansız
- **Slot Cap:** sabah saatlerinde (07:00-11:00) bant bazlı sıkı üst sınır

## 12.2 Shrinkage

Gerçek mola verisinden hesaplanır: molaya çıkan / çalışan oranı.
- **Düşük** → yetersiz agent (Erlang karşılanmaz)
- **Yüksek** → fazla maliyet (gereksiz personel)
- **3sn wrap-up** eklenebilir (+%1.6 etki)

Saat bazlı değerler ile gün boyu farklı dinamiklere uyum sağlanır (örn. öğle saatlerinde mola yoğunluğu artar).

## 12.3 Infeasibility Kontrol Sırası

Çözüm bulunamazsa kontrol et:
1. **min_per_shift** — çok yüksekse az kapsamlı slotlar karşılanamaz
2. **Shift dosyasında kapsanmayan slot** — örn. 03:00 slotunu kapsayan vardiya yoksa Erlang>0 ise infeasible
3. **Outsource oranı çelişkisi** — çok dar aralık (örn. min=max=0.65) infeasible olabilir
4. **Part-time kısıtı çelişkisi** — pt_available > toplam ihtiyaç olabilir
5. **Inhouse-only / outsource-only minimumlar** — toplamı Erlang'ı aşıyor olabilir

## 12.4 Override Dikkat

`queue_overrides` yapısında girintiye dikkat edilmeli:

```python
# DOĞRU
'queue_overrides': {
    'kitle': {
        'pazar': {
            'hourly_report': {                      # ← pazar'ın İÇİNDE
                'kapasite_kaybi': {9: 0.12}
            }
        }
    }
}

# YANLIŞ — hourly_report pazar'ın DIŞINDA → uygulanmaz
'queue_overrides': {
    'kitle': {
        'pazar': {
            'erlang': {...}
        },
        'hourly_report': {...}                      # ← burada olmamalı
    }
}
```

Override tanımlanmayan kuyruk/gün tipi için **ana CONFIG** kullanılır. Pipeline başında konsola override durumu yazılır.

## 12.5 Small Shift Penalty Etkisi

`small_shift_penalty: 10` parametresi ile her aktif shift için sabit 10 birim ek maliyet eklenir. Bu, modeli **az sayıda ama büyük** shift açmaya yönlendirir:

- 8 farklı shift × 10 = 80 ek maliyet → MIP, mevcut shift'e 5 kişi daha eklemeyi tercih eder, yeni shift açmaktansa
- Part-time shift'lere uygulanmaz (haftasonu zorunlu PT atamalarını engellememek için)
- Çok düşük → çok shift açılır, operasyonel zorluk
- Çok yüksek → tek shift'te yığılma, optimum dağılımdan sapma

## 12.6 Slot Cap Mantığı

Slot Cap, sabah erken saatlerde (özellikle 07:00-09:00) Erlang ihtiyacının çok az üstüne çıkılmasına izin verir. Mantık:

- 07:00-09:00 bandında `max_ratio=1.05` → sadece %5 fazla atama tolere edilir, ötesi penalty
- 10:00-11:00 bandında `max_ratio=1.30` → %30 fazlalığa kadar tolerans (peak ısınma dönemi)
- Penalty: 50.0/kişi → çok yüksek, model bant sınırını ciddiyetle dikkate alır

Bu kısıt, MIP'in büyük inhouse vardiyaları sabah erken saatlerde başlatıp gün boyu yığılma yaratmasını engeller.
