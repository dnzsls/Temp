# Workforce Scheduling Optimization Pipeline
## Business Requirements Document (BRD)

**Versiyon:** v10.9
**Tarih:** Nisan 2026
**Doküman Sahibi:** _[DOLDURULACAK: Doküman sahibi adı/birimi]_
**Onaylayan:** _[DOLDURULACAK: Onay otoriteleri]_
**Durum:** _[DOLDURULACAK: Taslak / İnceleme / Onaylı]_

---

# 1. EXECUTIVE SUMMARY

## 1.1 Proje Tanımı

Workforce Scheduling Optimization Pipeline, çağrı merkezi operasyonu için **günlük vardiya planlamasını** otomatikleştiren, matematiksel optimizasyon (MIP) tabanlı bir karar destek sistemidir. Sistem, beklenen çağrı yoğunluğu ve servis seviyesi hedeflerine göre, **inhouse + outsource + part-time** çalışanların hangi vardiyalara kaç kişi atanacağını belirler.

## 1.2 İş Problemi

_[DOLDURULACAK: Mevcut süreçteki ana ağrı noktaları — örn. manuel planlamada harcanan süre, kapasite-talep uyumsuzluğu, outsource maliyeti dengesizliği, yanıtlama oranı düşüklüğü vb.]_

## 1.3 Çözüm Özeti

Sistem üç ana bileşenden oluşur:
1. **Erlang-C Hesabı** — Servis seviyesi hedefini sağlayacak personel ihtiyacını çıkarır
2. **MIP Optimizasyonu** — Bu ihtiyacı en düşük maliyetle ve operasyonel kısıtları gözeterek vardiyalara dağıtır
3. **Raporlama** — Plan vs. gerçekleşme karşılaştırması, kapasite analizi ve Excel çıktı

İki çalışma modu vardır:
- **Model Geliştirme (Actual):** Geçmiş çağrı + gerçekleşen vardiya verileriyle modelin doğruluğu test edilir, parametreler tune edilir
- **Forecast:** Gelecek tahmin verisiyle üretim için vardiya planı üretilir

## 1.4 Beklenen Faydalar

_[DOLDURULACAK: Hedeflenen iş faydaları — örn. planlama süresinde % azalma, maliyet tasarrufu, yanıtlama oranında artış, operasyon ekibi memnuniyeti vb. Mümkünse hedef metrikleri yaz]_

---

# 2. STAKEHOLDER'LAR

## 2.1 İş Tarafı

| Rol | İsim/Birim | Sorumluluk |
|-----|-----------|-----------|
| Sponsor | _[DOLDURULACAK]_ | Proje stratejik onayı, bütçe |
| İş Sahibi | _[DOLDURULACAK]_ | Gereksinim sahibi, kabul kriterleri |
| Operasyon Ekibi | _[DOLDURULACAK]_ | Günlük kullanıcı, vardiya planı uygulayıcı |
| WFM Ekibi | _[DOLDURULACAK]_ | Çağrı tahmini, AHT, shrinkage analizi |
| Outsource Yönetimi | _[DOLDURULACAK]_ | Outsource ekibi koordinasyonu |

## 2.2 Teknik Taraf

| Rol | İsim/Birim | Sorumluluk |
|-----|-----------|-----------|
| Geliştirici | _[DOLDURULACAK]_ | Kod geliştirme, bakım |
| Analist | _[DOLDURULACAK]_ | Veri hazırlama, parametre tuning |
| _[Ekle]_ | _[DOLDURULACAK]_ | _[DOLDURULACAK]_ |

---

# 3. KAPSAM

## 3.1 Kapsam İçi (In Scope)

Sistem aşağıdakileri kapsar:

- **3 ana kuyruk** için vardiya planlaması: Kitle, Kurumsal, Gold
- **3 çalışan tipi:** Inhouse, Outsource, Part-time
- **30 dakikalık slot bazında** günlük (00:00-23:30) personel atama
- **Alt kuyruk bazlı** AHT ve çağrı dağılımına göre weighted hesap
- **Hard kısıtlar:** Erlang karşılama, outsource oranı, alt kuyruk minimumları, part-time toplam
- **Soft kısıtlar:** Maliyet minimizasyonu, fazla atama cezası, slot cap, küçük shift cezası, saat bazlı maliyet çarpanı
- **Gün tipi bazlı** farklı parametre uygulaması (haftaiçi / cumartesi / pazar)
- **Konsol raporu** ve **Excel çıktı** (vardiya atamaları, slot karşılaştırma, özet)
- **Çağrı kapasitesi raporu** (rapor etkisi, kapasite kaybı, çağrı kapasitesi, response rate)
- **Ek kapasite analizi** (dış arama / atıl kapasite ayrımı)

## 3.2 Kapsam Dışı (Out of Scope)

Sistem aşağıdakileri **kapsamaz** (mevcut versiyonda):

- Çağrı tahmini (forecast modeli) — dışarıdan girdi olarak alınır
- Çalışan bazlı atama (kim hangi vardiyaya) — sadece kişi sayısı atanır, isim atama HR sistemlerinde yapılır
- Mola/yemek planlaması
- Vardiya değişim/swap mekanizması
- Real-time intra-day yeniden planlama
- Multi-skill / cross-training optimizasyonu
- _[DOLDURULACAK: Başka kapsam dışı maddeler varsa ekle]_

---

# 4. İŞ HEDEFLERİ

| # | Hedef | Mevcut Durum | Hedef Değer | Ölçüm Yöntemi |
|---|-------|--------------|-------------|---------------|
| 1 | Servis seviyesi (ASA) | _[DOLDURULACAK]_ | ≤ 30 saniye | Erlang-C target_asa |
| 2 | Yanıtlama oranı (RR) | _[DOLDURULACAK]_ | _[DOLDURULACAK]_ | Çağrı kapasitesi / Gelen çağrı |
| 3 | Outsource oranı | _[DOLDURULACAK]_ | %60-65 (Kitle) | MIP toplam outsource / toplam |
| 4 | Planlama süresi | _[DOLDURULACAK]_ | _[DOLDURULACAK]_ | Manuel süre vs. otomatik süre |
| 5 | Toplam personel maliyeti | _[DOLDURULACAK]_ | _[DOLDURULACAK]_ | MIP amaç fonksiyonu çıktısı |
| _[Ekle]_ | _[DOLDURULACAK]_ | _[DOLDURULACAK]_ | _[DOLDURULACAK]_ | _[DOLDURULACAK]_ |

---

# 5. İŞ GEREKSİNİMLERİ (BUSINESS REQUIREMENTS)

## 5.1 Fonksiyonel Gereksinimler

### BR-001: Çağrı Bazlı Personel İhtiyacı Hesabı

**İhtiyaç:** Sistem, beklenen çağrı yoğunluğuna ve hedef servis seviyesine göre her 30 dakikalık slotta gerekli minimum personel sayısını hesaplamalıdır.

**Karşılama:** Erlang-C formülü + saatlik shrinkage uygulanır. Alt kuyruk bazlı çağrı ağırlıklı AHT kullanılır.

**Kabul Kriteri:** _[DOLDURULACAK: Örn. ASA ≤ 30 saniye sağlanmalı, hesap her slot için tutarlı olmalı]_

---

### BR-002: Vardiya Atama Optimizasyonu

**İhtiyaç:** Hesaplanan personel ihtiyacını, mevcut vardiya tanımları üzerinden en düşük maliyetle karşılayacak şekilde kişi sayısı dağıtımı yapılmalıdır.

**Karşılama:** MIP modeli (PuLP + CBC solver) ile çözülür. Her shift için integer karar değişkeni.

**Kabul Kriteri:** _[DOLDURULACAK: Örn. çözüm süresi < 30sn, infeasibility durumunda anlaşılır mesaj]_

---

### BR-003: Outsource Oran Kontrolü

**İhtiyaç:** Kitle kuyruğunda outsource personelin toplam personele oranı, yönetim tarafından belirlenen aralıkta tutulmalıdır.

**Karşılama:** Hard kısıt (K2) — `min_ratio ≤ outsource / (inhouse + outsource + part_time) ≤ max_ratio`

**Konfigürasyon:** `outsource_ratio = {'kitle': {'min': 0.60, 'max': 0.65}}`

**Kabul Kriteri:** _[DOLDURULACAK: Örn. her gün için oran tolerans aralığında, raporda gösteriliyor]_

---

### BR-004: Kuyruk Bazlı Ayrı Planlama

**İhtiyaç:** Her kuyruk (Kitle, Kurumsal, Gold) farklı çalışan tipleri ve farklı vardiya havuzları kullanır. Kurumsal ve Gold sadece inhouse'dur.

**Karşılama:** `queues` config'inde her kuyruk için `companies` listesi tanımlanır. `outsource_ratio = None` olan kuyruklar için K2 kısıtı uygulanmaz.

**Kabul Kriteri:** _[DOLDURULACAK]_

---

### BR-005: Part-time Çalışan Yönetimi (Hafta Sonu)

**İhtiyaç:** Hafta sonları (Cumartesi/Pazar) part-time çalışanlar belirli kurallarla planlanmalıdır.

**Karşılama:** `get_part_time_availability()` fonksiyonu ile günlük müsait PT sayısı hesaplanır. PT toplamı sabit kısıt olarak modele eklenir (K4).

**Kurallar:**
- Haftaiçi: 0
- Ayın ilk 3 günü: 0 (hafta sonu olsa bile)
- Cumartesi: total_pt // 2
- Pazar: total_pt - cumartesi
- Ayın son cumartesisi: tam kadro

**Kabul Kriteri:** _[DOLDURULACAK]_

---

### BR-006: Alt Kuyruk Bazlı Inhouse/Outsource Zorunluluğu

**İhtiyaç:** Belirli alt kuyruklar (örn. retention_line, kayipcalintisupheli) sadece inhouse veya sadece outsource tarafından karşılanmalıdır.

**Karşılama:** `inhouse_only_subqueues` ve `outsource_only_subqueues` config'leri. Alt kuyruğun çağrı payına göre slot bazlı minimum kişi kısıtı.

**Hesap:** `min_need = ⌈erlang × (sq_calls / total_calls) × min_ratio⌉`

**Kabul Kriteri:** _[DOLDURULACAK: Örn. her aktif slotta minimum karşılanmalı]_

---

### BR-007: Gün Tipi Bazlı Farklı Parametreler

**İhtiyaç:** Haftaiçi, Cumartesi ve Pazar günleri için farklı shrinkage, RR penalty, kapasite kaybı vb. parametreler kullanılabilmelidir.

**Karşılama:** `queue_overrides` mekanizması — kuyruk + gün tipi bazlı deep merge.

**Kabul Kriteri:** _[DOLDURULACAK: Örn. override aktif olduğunda raporda gösterilmeli, override olmayan parametreler ana CONFIG'ten gelmeli]_

---

### BR-008: Erken Saat ve Gece Vardiyalarının Ekonomik Kontrolü

**İhtiyaç:** 07:00 öncesi inhouse vardiyaları operasyonel olarak istenmeyen, 02:00-07:00 arası fazla atama da maliyetli olmalıdır.

**Karşılama:**
- Saat bazlı maliyet çarpanı (`time_cost_multipliers`): 07:00 → 1.5x, 07:30 → 1.3x
- Gece RR penalty çarpanı (`night_multiplier`): 02:00-07:00 arası 100x → fazla atamada 400/kişi ceza

**Kabul Kriteri:** _[DOLDURULACAK]_

---

### BR-009: Sabah Saatlerinde Yığılma Önleme

**İhtiyaç:** Sabah erken saatlerde (07:00-11:00) Erlang ihtiyacının çok üstünde personel atanmamalıdır (gereksiz maliyet).

**Karşılama:** Slot Cap mekanizması — saat aralığı bazlı `max_ratio` ile üst sınır, aşımda yüksek penalty (50/kişi).

**Konfigürasyon:** Bands (07:00-09:00 → %5 tolerans, 09:00-10:00 → %25, 10:00-11:00 → %30)

**Kabul Kriteri:** _[DOLDURULACAK]_

---

### BR-010: Operasyonel Olarak Yönetilebilir Vardiya Sayısı

**İhtiyaç:** MIP'in çok sayıda küçük (2-3 kişilik) vardiya açması operasyonel zorluk yaratır. Az sayıda ama yeterli büyüklükte vardiya tercih edilmelidir.

**Karşılama:**
- `min_per_shift = 5` → bir shift açılırsa en az 5 kişi
- `small_shift_penalty = 10` → her aktif shift için sabit ek maliyet

**Kabul Kriteri:** _[DOLDURULACAK: Örn. ortalama vardiya başı kişi sayısı, toplam aktif vardiya sayısı]_

---

### BR-011: Plan vs. Gerçekleşme Karşılaştırma (Model Geliştirme)

**İhtiyaç:** Geçmiş tarih için MIP planı ile gerçek çalışma karşılaştırılarak modelin doğruluğu ölçülmelidir.

**Karşılama:** `get_actual_summary()` fonksiyonu + `print_queue_report()` raporu.

**Rapor İçeriği:** Toplam kişi farkı, slot bazlı eşzamanlı çalışan farkı, RR farkı.

**Kabul Kriteri:** _[DOLDURULACAK]_

---

### BR-012: Excel Çıktı

**İhtiyaç:** Birden fazla tarih ve kuyruk için tek Excel çıktı üretilmelidir.

**Karşılama:** `export_to_excel()` fonksiyonu — 3 sheet (Vardiya_Atamaları, Slot_Karşılaştırma, Özet) + her tarih için TOPLAM satırı.

**Kabul Kriteri:** _[DOLDURULACAK: Örn. dosya formatı, sheet isimleri, hangi kolonlar zorunlu]_

---

### BR-013: Çağrı Kapasitesi ve Response Rate Hesabı

**İhtiyaç:** MIP atamasına göre slot bazında ne kadar çağrı karşılanabileceği ve yanıtlama oranı raporlanmalıdır.

**Karşılama:** `hourly_report` config'i + slot bazlı kapasite raporu.

**Hesap:**
```
Net_MT = Kapasite - Rapor_Etkisi - Kapasite_Kaybı
Çağrı_Kapasitesi = Net_MT × (Çağrı_Adedi / 2)
Response_Rate = Çağrı_Kapasitesi / Gelen_Çağrı
```

**Kabul Kriteri:** _[DOLDURULACAK]_

---

### BR-014: Forecast Pipeline (Üretim Vardiya Planı)

**İhtiyaç:** Gelecek tarih için tahmin verisi ile vardiya planı üretilebilmelidir (gerçek veri olmadan).

**Karşılama:** `forecast_pipeline_v10_9.py` — geniş format çağrı verisi alır, aynı MIP mantığını uygular.

**Kabul Kriteri:** _[DOLDURULACAK]_

---

### _[BR-XXX: Yeni gereksinim eklemek için bu şablonu kullan]_

**İhtiyaç:** _[DOLDURULACAK]_

**Karşılama:** _[DOLDURULACAK]_

**Kabul Kriteri:** _[DOLDURULACAK]_

---

## 5.2 Fonksiyonel Olmayan Gereksinimler

### NFR-001: Performans
- Tek gün, tek kuyruk için MIP çözüm süresi: _[DOLDURULACAK: Örn. < 30 saniye]_
- Tek gün, 3 kuyruk için toplam süre: _[DOLDURULACAK]_
- Aylık Excel export (4 hafta sonu × 3 kuyruk): _[DOLDURULACAK]_

### NFR-002: Kullanılabilirlik
- Jupyter notebook üzerinden hücre bazlı çalıştırılabilir olmalı
- Konsol çıktısı operasyon ekibinin anlayacağı düzeyde olmalı (Türkçe başlıklar)

### NFR-003: Bakım
- Konfigürasyon kodla ayrı dosyada (`config_v10_9.py`)
- Yeni kuyruk veya yeni alt kuyruk eklenmesi sadece config değişikliği gerektirmeli

### NFR-004: Veri Bütünlüğü
- Eksik AHT verisi durumunda fallback (`default_aht`)
- Eksik shrinkage saati için `default` değer
- Boş çağrı slotları için 0 atama

### NFR-005: _[DOLDURULACAK: Başka NFR varsa ekle — örn. güvenlik, log, monitoring]_

---

# 6. İŞ KURALLARI (BUSINESS RULES)

| Kural ID | Açıklama | Uygulama |
|----------|----------|----------|
| BK-001 | Kurumsal ve Gold kuyrukları sadece inhouse çalışan kullanır | Config: `companies: ['inhouse']`, `outsource_ratio: None` |
| BK-002 | Outsource bitiş saati operasyonel olarak +30 dakika uzatılır (molasız çalışma) | `prepare_actual()` ve shift coverage |
| BK-003 | Kitle kuyruğunda outsource oranı %60-65 aralığında olmalı | K2 hard constraint |
| BK-004 | Bir vardiya açıldıysa en az 5 kişi atanmalı | K3 + `min_per_shift=5` |
| BK-005 | Hafta sonu part-time toplam sayısı sabittir (config'ten gelir) | K4 hard constraint |
| BK-006 | Ayın ilk 3 günü part-time çalışmaz | `get_part_time_availability()` |
| BK-007 | Servis hedefi: ASA ≤ 30 saniye | `target_asa = 30` |
| BK-008 | Erlang sonucu shrinkage ile büyütülür | `final = ceil(raw / (1 - shrinkage))` |
| BK-009 | Saat bazlı shrinkage farklı uygulanır (örn. öğle saati daha yüksek) | `shrinkage` saatlik dict |
| BK-010 | _[DOLDURULACAK: Diğer iş kuralları]_ | _[DOLDURULACAK]_ |

---

# 7. KABULLER (ASSUMPTIONS)

| # | Kabul | Risk |
|---|-------|------|
| A-001 | Çağrı tahmin verisi (df_forecast) doğrudur, planlama bu veri üzerinden yapılır | Tahmin sapması → plan hatası |
| A-002 | AHT değerleri (df_aht) geçmiş ortalamayı temsil eder ve yakın gelecekte stabil kalır | AHT değişimi → kapasite hatası |
| A-003 | Shrinkage oranları (config) gerçek mola davranışını yansıtır | Yanlış shrinkage → over/under planning |
| A-004 | Vardiya tanımları (df_shifts) operasyonun kullanabileceği gerçek vardiyalardır | Eksik vardiya → infeasibility |
| A-005 | Part-time çalışan toplam sayısı operasyon tarafından doğru girilir | Yanlış sayı → atama dengesizliği |
| A-006 | Inhouse/outsource sınıflandırması (`outsource_flg`) tutarlıdır | Yanlış flag → oran hatası |
| A-007 | _[DOLDURULACAK: Başka kabuller varsa ekle]_ | _[DOLDURULACAK]_ |

---

# 8. KISITLAMALAR (CONSTRAINTS)

| # | Kısıtlama | Açıklama |
|---|-----------|----------|
| C-001 | 30 dakika minimum slot | Daha hassas (15dk) planlama yapılmaz |
| C-002 | Tek günlük optimizasyon | Çok günlü (haftalık) ortak optimizasyon yok; her gün bağımsız çözülür |
| C-003 | Çalışan bazlı atama yok | Sadece kişi sayısı, isim atama HR sisteminde yapılır |
| C-004 | Multi-skill desteklenmez | Bir çalışan tek bir kuyruğa atanır |
| C-005 | PuLP/CBC solver bağımlılığı | Açık kaynak solver — büyük problemlerde performans sınırı |
| C-006 | Real-time replanning yok | Gün içi yeniden planlama desteklenmez |
| C-007 | _[DOLDURULACAK: Başka teknik/iş kısıtlamaları]_ | _[DOLDURULACAK]_ |

---

# 9. BAĞIMLILIKLAR (DEPENDENCIES)

## 9.1 Veri Bağımlılıkları

| Veri | Kaynak | Sıklık | Sahibi |
|------|--------|--------|--------|
| Geçmiş çağrı verisi | _[DOLDURULACAK: Örn. CCaaS sistemi, raporlama DB]_ | Günlük | _[DOLDURULACAK]_ |
| Forecast çağrı verisi | _[DOLDURULACAK: Örn. tahmin modeli çıktısı]_ | Haftalık | _[DOLDURULACAK]_ |
| AHT verisi | _[DOLDURULACAK]_ | Aylık | _[DOLDURULACAK]_ |
| Vardiya tanımları | _[DOLDURULACAK: Örn. operasyon ekibi Excel]_ | Gerektiğinde | _[DOLDURULACAK]_ |
| Gerçekleşen vardiya verisi | _[DOLDURULACAK]_ | Günlük | _[DOLDURULACAK]_ |

## 9.2 Sistem Bağımlılıkları

- Python 3.x ortamı
- Kütüphaneler: pandas, numpy, pulp, openpyxl
- CBC Solver (PuLP içinde)
- Jupyter Notebook (kullanım için)

## 9.3 Diğer Bağımlılıklar

_[DOLDURULACAK: Entegrasyonlar, downstream sistemler — örn. WFM aracı, HR sistemi vb.]_

---

# 10. BAŞARI KRİTERLERİ

| # | Kriter | Hedef | Ölçüm |
|---|--------|-------|-------|
| SK-001 | Optimizasyon başarı oranı | %100 günde feasible çözüm | Infeasible çözüm sayısı |
| SK-002 | Çözüm süresi | _[DOLDURULACAK]_ | Pipeline runtime |
| SK-003 | Plan-gerçek sapma (kişi bazlı) | _[DOLDURULACAK: Örn. < %5]_ | (MIP - Gerçek) / Gerçek |
| SK-004 | Yanıtlama oranı | _[DOLDURULACAK]_ | Kapasite RR |
| SK-005 | Outsource oran uyumu | %60-65 (Kitle) | MIP outsource_ratio |
| SK-006 | Operasyon ekibi kabul | _[DOLDURULACAK: Örn. anketle]_ | Kullanıcı geri bildirimi |
| SK-007 | _[DOLDURULACAK]_ | _[DOLDURULACAK]_ | _[DOLDURULACAK]_ |

---

# 11. RİSKLER

| # | Risk | Etki | Olasılık | Önlem |
|---|------|------|----------|-------|
| R-001 | Çağrı tahmin sapması → yanlış kapasite | Yüksek | Orta | Gerçek vs. tahmin karşılaştırma raporu, geriye dönük doğrulama |
| R-002 | AHT'nin değişmesi (yeni ürün, kampanya) → modelin gerçeği yansıtmaması | Orta | Orta | Aylık AHT güncelleme, manuel override desteği |
| R-003 | Shrinkage'ın yanlış kalibre olması → over/under staffing | Orta | Yüksek | Düzenli shrinkage analizi, override mekanizması |
| R-004 | Part-time sayısının operasyonel değişimi | Düşük | Orta | Config kolay güncellenebilir |
| R-005 | Solver performans sınırı (büyük problemler) | Düşük | Düşük | Problem boyutu izleme |
| R-006 | Operasyon ekibinin sistemi benimsememesi | Yüksek | _[DOLDURULACAK]_ | Eğitim, kullanıcı dokümantasyonu, kademeli geçiş |
| R-007 | _[DOLDURULACAK]_ | _[DOLDURULACAK]_ | _[DOLDURULACAK]_ | _[DOLDURULACAK]_ |

---

# 12. FONKSİYONEL ÖZELLİKLER MAPPİNG

İş gereksiniminin sistemde nasıl karşılandığını gösteren özet eşleştirme:

| İş İhtiyacı | Sistem Mekanizması | CONFIG Parametresi | Fonksiyon |
|-------------|-------------------|--------------------|-----------|
| Çağrıya göre personel ihtiyacı | Erlang-C + saatlik shrinkage | `erlang.target_asa`, `erlang.shrinkage` | `find_optimal_agents()`, `calculate_erlang_all()` |
| Alt kuyruk bazlı doğru AHT | Çağrı ağırlıklı weighted AHT | `sub_queues`, `aht_overrides`, `default_aht` | `calculate_weighted_aht()` |
| Vardiya atama optimizasyonu | MIP modeli + CBC solver | `mip.cost_inhouse`, `mip.cost_outsource`, `mip.min_per_shift` | `optimize_queue()` |
| Outsource oran kontrolü | K2 Hard Constraint | `outsource_ratio[queue]` | `optimize_queue()` içi K2 |
| Kuyruk bazlı çalışan tipi sınırlama | `companies` listesi | `queues[q].companies` | `optimize_queue()` shift filtreleme |
| Hafta sonu part-time | K4 Hard Constraint + müsaitlik kuralı | `part_time.enabled`, `part_time.count`, `part_time.shifts` | `get_part_time_availability()`, `get_part_time_shifts()` |
| Alt kuyruk inhouse zorunluluğu | K5 Hard Constraint | `inhouse_only_subqueues` | `_build_subqueue_min_slots()` |
| Alt kuyruk outsource zorunluluğu | K6 Hard Constraint (saat kısıtlı) | `outsource_only_subqueues` | `_build_subqueue_min_slots()` |
| Erken saat caydırıcılığı | Saat bazlı maliyet çarpanı | `time_cost_multipliers` | `get_time_cost_multiplier()` |
| Fazla atama önleme | RR Penalty (Soft, 3 seviyeli) | `rr_penalty.penalty_per_person`, `peak_penalty`, `night_multiplier` | `optimize_queue()` excess değişkenleri |
| Sabah yığılma önleme | Slot Cap (Soft, band bazlı) | `slot_cap.bands` | `optimize_queue()` sc_excess değişkenleri |
| Az sayıda büyük vardiya tercihi | Small Shift Penalty (Soft) | `small_shift_penalty.penalty` | `optimize_queue()` y[s] çarpımı |
| Gün tipi bazlı farklı parametreler | Queue Override (Deep Merge) | `queue_overrides` | `run_queue_pipeline()` `_deep_merge()` |
| Plan-gerçek karşılaştırma | Gerçek veri özet + slot bazlı tablo | `actual_columns` | `get_actual_summary()`, `print_queue_report()` |
| Çağrı kapasitesi raporu | Slot bazlı kapasite hesabı | `hourly_report.rapor_etkisi`, `kapasite_kaybi`, `cagri_adedi` | `print_queue_report()` slot kapasite bölümü |
| Günlük kapasite & RR | Vardiya süresi × verimlilik | `capacity.efficiency` | `calculate_daily_capacity()` |
| Excel çıktı | 3 sheet + TOPLAM satırları | - | `export_to_excel()` |
| _[Ekle]_ | _[DOLDURULACAK]_ | _[DOLDURULACAK]_ | _[DOLDURULACAK]_ |

---

# 13. SÜREÇ AKIŞI

## 13.1 Günlük Operasyonel Akış

```
1. WFM Ekibi → Çağrı tahmini hazırlar (df_forecast)
2. Operasyon → Vardiya tanımlarını günceller (df_shifts) [varsa değişiklik]
3. Sistem → Forecast Pipeline çalıştırılır → günlük plan üretilir
4. Operasyon → Plan onaylanır, HR sistemine aktarılır
5. Gün içi → Plan uygulanır
6. Gün sonu → Gerçekleşen veri çekilir (df_actual)
7. Analist → Model Geliştirme Pipeline çalıştırılır → plan vs gerçek karşılaştırılır
8. Analist → Sapma analizi, gerekirse parametre ayarı
```

_[DOLDURULACAK: Detayları, sorumlular, SLA'lar — eğer daha resmi süreç yazılacaksa]_

## 13.2 Aylık Tuning Akışı

```
1. AHT verisi yenilenir (geçmiş ay)
2. Shrinkage analizi yapılır (gerçek mola/çalışma oranı)
3. Override config'leri güncellenir (gerekirse)
4. Geriye dönük test (son 4 hafta) — Excel export
5. Sapma raporu → karar
```

_[DOLDURULACAK]_

---

# 14. GLOSSARY (TERİMLER SÖZLÜĞÜ)

| Terim | Açıklama |
|-------|----------|
| AHT | Average Handle Time — Ortalama Görüşme Süresi (saniye) |
| ASA | Average Speed of Answer — Ortalama Cevaplama Süresi (hedef: ≤ 30sn) |
| Erlang-C | Çağrı merkezi personel ihtiyacı hesaplama formülü |
| MIP | Mixed Integer Programming — Karma Tamsayılı Programlama |
| Slot | 30 dakikalık zaman dilimi (toplam 48 slot/gün) |
| Shift / Vardiya | Belirli başlangıç-bitiş saati olan çalışma blogu (örn. 08:00-17:00) |
| Inhouse | Şirket bünyesi çalışan |
| Outsource | Dış kaynak çalışan |
| Part-time | Yarı zamanlı çalışan (sadece hafta sonu) |
| Shrinkage | Mola, eğitim vb. nedeniyle hatta olmama oranı |
| Occupancy | Bir agentın aktif konuşma süresi oranı (Erlang'a dahil edildi) |
| Response Rate (RR) | Yanıtlama oranı — karşılanan çağrı / gelen çağrı |
| Sub-queue / Alt Kuyruk | Ana kuyruk içindeki spesifik çağrı tipleri (örn. retention_line) |
| RR Penalty | Erlang üstü atamaları cezalandıran mekanizma |
| Slot Cap | Saat aralığı bazlı atama üst sınırı |
| Hard Constraint | Kesin uyulması gereken kısıt |
| Soft Constraint | Amaç fonksiyonunda ceza ile yönetilen kısıt |
| Queue Override | Kuyruk + gün tipi bazlı parametre değiştirme |
| Deep Merge | İç içe dict yapısının seçici güncellemesi |
| Net MT | Net Müsait Trafik — kapasiteden rapor etkisi ve kayıplar düşüldükten sonra kalan |
| _[Ekle]_ | _[DOLDURULACAK]_ |

---

# 15. EKLER

## 15.1 İlgili Dokümanlar

- **Teknik Dokümantasyon:** `actual_pipeline_v10_9.py` kod akışı dokümanı
- **MIP Modeli Dokümantasyonu:** `mip_documentation_v10_9.md` — matematiksel model detayı
- **CONFIG Referansı:** `config_v10_9.py`
- _[DOLDURULACAK: Diğer ilgili dokümanlar]_

## 15.2 Onay Kayıtları

| Versiyon | Tarih | Onaylayan | Notlar |
|----------|-------|-----------|--------|
| v10.9 | _[DOLDURULACAK]_ | _[DOLDURULACAK]_ | İlk yayın |
| _[Ekle]_ | _[DOLDURULACAK]_ | _[DOLDURULACAK]_ | _[DOLDURULACAK]_ |

## 15.3 Versiyon Geçmişi (Doküman)

| Versiyon | Tarih | Değişiklik | Yazar |
|----------|-------|-----------|-------|
| 1.0 | _[DOLDURULACAK]_ | İlk taslak | _[DOLDURULACAK]_ |
| _[Ekle]_ | _[DOLDURULACAK]_ | _[DOLDURULACAK]_ | _[DOLDURULACAK]_ |
