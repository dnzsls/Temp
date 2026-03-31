# Optimizasyon Konu Anlatımı
## Teori, Algoritmalar ve Gerçek Dünya

---

# 1. OPTİMİZASYON TEMELLERİ

## 1.1 Tanım

**Optimizasyon**, kısıtlı kaynaklar altında en iyi kararı bulma sürecidir.

```
Günlük hayat örnekleri:

"En kısa yoldan işe nasıl giderim?"
→ Shortest Path / VRP problemi
→ Çözüm: Graph algoritmaları, MIP

"Bütçemi nasıl dağıtayım?"
→ Resource Allocation problemi  
→ Çözüm: LP (lineer ise), MIP (tam sayı kararlar varsa)

"Hangi ürünleri ne kadar üreteyim?"
→ Production Planning problemi
→ Çözüm: LP (miktarlar kesirli olabilir), MIP (parti büyüklükleri)

"Çalışanları vardiyalara nasıl atayayım?"
→ Scheduling problemi
→ Çözüm: MIP veya CP (Constraint Programming)
```

## 1.2 Matematiksel Formülasyon

Her optimizasyon problemi 3 bileşenden oluşur:

```
1. KARAR DEĞİŞKENLERİ (x)
   Ne hakkında karar veriyoruz?
   Örnek: x₁ = üretilecek A ürünü miktarı

2. AMAÇ FONKSİYONU (z)
   Neyi optimize ediyoruz?
   Örnek: max z = 5x₁ + 3x₂  (kârı maksimize et)

3. KISITLAR
   Sınırlarımız neler?
   Örnek: x₁ + x₂ ≤ 100  (kapasite)
```

## 1.3 Optimizasyon Ailesi

```
                    Optimizasyon
                         │
         ┌───────────────┼───────────────┐
         │               │               │
      Exact          Heuristic       Nonlinear
    (Kesin)         (Sezgisel)       (Eğrisel)
         │               │               │
    ┌────┴────┐     ┌────┴────┐         │
    │         │     │         │         │
   LP     IP/MIP   GA    Simulated   Gradient
                        Annealing    Descent
```

| Yöntem | Garanti | Hız | Kullanım |
|--------|---------|-----|----------|
| **Exact** | Optimal | Yavaş olabilir | Küçük-orta problemler |
| **Heuristic** | İyi çözüm | Hızlı | Büyük/karmaşık problemler |
| **Nonlinear** | Lokal optimal | Değişken | Eğrisel fonksiyonlar |

---

# 2. LINEAR PROGRAMMING (LP)

## 2.1 Tanım

LP, hem amaç fonksiyonunun hem kısıtların **lineer** (doğrusal) olduğu optimizasyon problemidir.

**Lineer ne demek?**
```
✅ Lineer:     3x₁ + 5x₂ ≤ 100     (sabit × değişken + toplam)
✅ Lineer:     x₁ - 2x₂ + x₃ = 50

❌ Lineer DEĞİL: x₁² + x₂ ≤ 100    (kare → eğri)
❌ Lineer DEĞİL: x₁ · x₂ ≤ 100     (iki değişken çarpımı)
❌ Lineer DEĞİL: log(x₁) ≤ 100     (logaritma)
```

## 2.2 Standart Form

```
maksimize   z = c₁x₁ + c₂x₂ + ... + cₙxₙ

kısıtlar:
            a₁₁x₁ + a₁₂x₂ + ... ≤ b₁
            a₂₁x₁ + a₂₂x₂ + ... ≤ b₂
            ...
            x₁, x₂, ... ≥ 0
```

**Matris formunda:**
```
max  z = cᵀx
kısıtlar:  Ax ≤ b
           x ≥ 0
```

## 2.3 Simplex Algoritması

LP'nin çözüm yöntemi. 1947'de George Dantzig tarafından geliştirildi.

### Geometrik Anlam

Her kısıt, n-boyutlu uzayda bir **yarı-düzlem** tanımlar. Tüm kısıtların kesişimi bir **convex polytope** (dışbükey çokgen) oluşturur. Buna **feasible region** (uygun bölge) denir.

```
        x₂
         │
      7 ─┤      ╱
         │     ╱
      6 ─┤    ● ← Optimal (köşede!)
         │   /│
      4 ─┤  / │
         │ /  │    Feasible
      2 ─┤/   │    Region
         │    │    
      0 ─┼────┼────── x₁
         0    4    8
```

**Feasible region:** Tüm kısıtları sağlayan noktaların kümesi. Yukarıdaki şekilde çizgilerle sınırlanan alan.

### Algoritma Adımları

```
1. BAŞLA: Orijin veya bir köşe noktasından başla

2. KONTROL: Komşu köşelere bak
   - Daha iyi (daha yüksek z) köşe var mı?

3. HAREKET: Varsa o köşeye git, yoksa DUR

4. TEKRAR: Adım 2'ye dön
```

**Neden çalışır?**
- LP'de optimal çözüm her zaman bir köşededir (convexity)
- Simplex köşeleri gezer, içeriyi taramaz → çok hızlı
- Her adımda z artar → sonlu adımda biter

### Karmaşıklık

- Worst case: Exponential (ama pratikte nadir)
- Average case: O(n²) ile O(n³) arası
- 100.000 değişkenli LP saniyeler içinde çözülebilir

---

# 3. INTEGER PROGRAMMING (IP)

## 3.1 Tanım

IP, LP ile aynı yapıdadır ama değişkenler **tam sayı** olmak zorundadır.

```
LP:  x ∈ ℝ≥0     (0, 0.5, 1.7, 2.33, ...)
IP:  x ∈ ℤ≥0     (0, 1, 2, 3, ...)
```

## 3.2 Neden IP Lazım?

Bazı kararlar doğası gereği tam sayıdır:

```
- Kaç kamyon kullanacağız? → 3.7 kamyon olmaz
- Kaç kişi atayacağız? → 12.5 kişi olmaz
- Fabrikayı açacak mıyız? → 0.6 açık olmaz (binary)
```

## 3.3 Binary Değişkenler

IP'nin özel hali. Sadece 0 veya 1 değeri alır.

```
y ∈ {0, 1}

y = 1 → Evet (fabrika açık, proje seçildi, çalışan atandı)
y = 0 → Hayır
```

**Kullanım örneği:**
```
Fabrika açılırsa üretim yapabilir:
    x ≤ M · y

y = 0 → x ≤ 0 → üretim yok
y = 1 → x ≤ M → üretim yapılabilir (M = büyük sayı)
```

## 3.4 LP Relaxation

IP'yi çözmeden önce, integer kısıtını **gevşetip** LP olarak çözeriz.

```
IP:  x ∈ {0, 1, 2, 3, ...}
        ↓ gevşet
LP:  x ∈ [0, ∞)
```

**Neden önemli?**
- LP çözümü, IP için **bound** verir
- Maximization: LP ≥ IP (LP bir üst sınır)
- Minimization: LP ≤ IP (LP bir alt sınır)

---

# 4. MIXED INTEGER PROGRAMMING (MIP)

## 4.1 Tanım

MIP, aynı modelde hem **continuous** hem **integer** değişkenlerin bulunduğu problemdir.

```
Örnek:
- x[fabrika] ∈ ℤ≥0     (kaç işçi) → integer
- y[fabrika] ∈ {0,1}   (açık mı) → binary
- ratio ∈ [0,1]        (oran) → continuous
```

## 4.2 Branch and Bound

MIP'in ana çözüm algoritması.

### Temel Kavramlar

```
Incumbent (mevcut en iyi): Şu ana kadar bulunan en iyi tam sayı çözüm.
                           Başta yok, ilk integer çözüm bulununca güncellenir.

Bound (sınır): LP relaxation sonucu. Gerçek optimal bundan iyi olamaz.

Prune (budama): Bir dalı atmak. O dalda daha iyi çözüm olmayacağı kesin.
```

### Fikir

LP relaxation çöz. Sonuç kesirli mi? Değişkeni ikiye böl ve iki alt problem oluştur.

### Algoritma

```
1. ROOT: LP relaxation çöz
   Örnek: x = 3.7, z = 42.8

2. BRANCH: Kesirli değişkeni seç, ikiye böl
   Sol dal: x ≤ 3
   Sağ dal: x ≥ 4

3. SOLVE: Her dalda yeni LP çöz

4. BOUND & PRUNE: 
   - Çözüm tam sayı → incumbent olarak kaydet
   - LP sonucu incumbent'tan kötü → bu dalı buda (daha iyi çözüm çıkamaz)
   - Çözüm kesirli ve umut var → tekrar branch

5. OPTIMAL: Tüm dallar işlendi → incumbent kesin optimal
```

### Görsel Örnek

```
                    LP Relaxation
                    x=3.7, z=42.8  (kesirli, bound=42.8)
                         │
            ┌────────────┴────────────┐
            │                         │
        x ≤ 3                     x ≥ 4
        z=40.2                    z=41.5
        (tam sayı!)               (tam sayı!)
        incumbent=40.2            incumbent=41.5 (daha iyi!)
            │                         │
            │                    ┌────┴────┐
        Budandı                  │         │
        (40.2 < 41.5,        x ≤ 4     x ≥ 5
        daha iyi olamaz)     z=41.5    z=39.1
                             Optimal!   Budandı
                                       (39.1 < 41.5)
        
Final: x=4, z=41.5 (incumbent = optimal)
```

**Akış:**
1. Root LP: z=42.8 (kesirli) → branch
2. Sol dal: z=40.2 (tam sayı) → incumbent=40.2
3. Sağ dal: z=41.5 (tam sayı, 40.2'den iyi) → incumbent=41.5
4. Sol dal budandı (40.2 < 41.5, o daldan daha iyi çıkamaz)
5. Sağ dalda devam, ama alt dallar da kötü → budandı
6. Bitti → incumbent=41.5 optimal

### Gap Kavramı

```
Gap = (Upper Bound - Lower Bound) / Lower Bound × 100

Maximization:
  Upper Bound = En iyi LP relaxation
  Lower Bound = En iyi integer çözüm (incumbent)

Gap = %0 → Kesin optimal
Gap = %1 → Optimal'in %1 içindeyiz
```

**Pratikte:** Büyük problemlerde %0 beklemek saatler sürebilir. %1-5 gap toleransı kabul edilir.

---

# 5. HEURISTIC & METAHEURISTIC

## 5.1 Neden Lazım?

Exact yöntemler (LP/MIP) her zaman çalışmaz:

```
1. Problem çok büyük
   - 1 milyon binary değişken → Branch & Bound patlar

2. Zaman kısıtlı
   - Gerçek zamanlı karar: saniyeler içinde cevap lazım

3. Problem lineer değil
   - Amaç fonksiyonu x², sin(x) içeriyor
```

## 5.2 Heuristic (Sezgisel)

Probleme özel, elle tasarlanmış kural. Optimal garanti etmez ama hızlı çözüm verir.

### Greedy (Açgözlü)

Her adımda o an en iyi görüneni seç. Geleceği düşünme.

**Örnek — Sırt Çantası Problemi:**

```
Çanta kapasitesi: 10 kg
Eşyalar:
  A: 6 kg, 30₺ değer  → ₺/kg = 5.0
  B: 4 kg, 24₺ değer  → ₺/kg = 6.0  ← en iyi oran
  C: 3 kg, 15₺ değer  → ₺/kg = 5.0
  D: 2 kg, 8₺ değer   → ₺/kg = 4.0

Greedy çözüm (₺/kg sırasıyla):
  1. B'yi al (4 kg, 24₺) → kalan kapasite: 6 kg
  2. A'yı al (6 kg, 30₺) → kalan kapasite: 0 kg
  Toplam: 54₺

Optimal çözüm:
  B + C + D = 4+3+2 = 9 kg, 24+15+8 = 47₺
  veya A + B = 6+4 = 10 kg, 30+24 = 54₺ ✓

Bu örnekte Greedy optimal buldu, ama her zaman bulmaz!
```

### Construction Heuristic

Boş çözümden başla, adım adım inşa et.

**Örnek — Gezgin Satıcı (TSP) için Nearest Neighbor:**

```
Şehirler: A, B, C, D
Mesafeler: A-B=10, A-C=15, A-D=20, B-C=35, B-D=25, C-D=30

Adımlar:
  1. A'dan başla
  2. En yakın ziyaret edilmemiş: B (10 km) → A→B
  3. B'den en yakın ziyaret edilmemiş: D (25 km) → A→B→D
  4. D'den en yakın ziyaret edilmemiş: C (30 km) → A→B→D→C
  5. Başa dön: C→A (15 km)
  
Toplam: 10+25+30+15 = 80 km

Optimal olabilir de olmayabilir de. Ama çok hızlı!
```

## 5.3 Metaheuristic (Üst-Sezgisel)

Probleme bağımsız, genel arama stratejisi. Farklı problemlere uygulanabilir.

### Simulated Annealing (SA) — Tavlama Benzetimi

Metal tavlama sürecinden esinlenme. Sıcak metal yavaş soğutulunca kristal yapısı düzgün olur.

**Problem:** Yerel arama (her adımda daha iyiye git) **lokal optimuma** takılır.

```
        ^
Değer   │    /\
        │   /  \  ← Lokal optimum (takılırsın)
        │  /    \
        │ /      \    /\
        │/        \  /  \ ← Global optimum (asıl hedef)
        └──────────\/─────────→ Çözüm uzayı
```

**SA'nın çözümü:** Bazen kötü adımları da kabul et → lokal optimumdan kaç.

**Algoritma:**

```
1. Rastgele bir çözüm seç (x)
2. Sıcaklık T'yi yüksek başlat (örn: T=1000)
3. Tekrar et:
   a) Komşu çözüm üret (x')
   b) Δ = f(x') - f(x)  (yeni - eski)
   c) Eğer Δ > 0 (daha iyi): kabul et, x = x'
   d) Eğer Δ < 0 (daha kötü): olasılıkla kabul et
      - P = exp(Δ/T)
      - T yüksekken P yüksek (riskli adım)
      - T düşükken P düşük (temkinli)
   e) T'yi azalt (soğut): T = T × 0.99
4. T çok düşünce dur
```

**Örnek:**

```
Mevcut çözüm: x, değer = 100
Yeni çözüm:   x', değer = 95 (daha kötü, Δ = -5)
Sıcaklık: T = 100

Kabul olasılığı: P = exp(-5/100) = exp(-0.05) = 0.95 → %95 kabul

Sıcaklık: T = 10
Kabul olasılığı: P = exp(-5/10) = exp(-0.5) = 0.60 → %60 kabul

Sıcaklık: T = 1
Kabul olasılığı: P = exp(-5/1) = exp(-5) = 0.007 → %0.7 kabul

→ Başta riskli, sonra temkinli. Lokal optimumdan kaçıp global'e ulaşabilir.
```

### Genetic Algorithm (GA) — Genetik Algoritma

Doğal evrimden esinlenme. En uygun bireyler hayatta kalır ve çoğalır.

**Terimler:**
```
Birey (Chromosome) = Bir çözüm (örn: [1,0,1,1,0])
Gen = Çözümün bir parçası (örn: ilk eleman = 1)
Popülasyon = Çözümler kümesi (örn: 100 farklı çözüm)
Fitness = Çözümün kalitesi (yüksek = iyi)
```

**Algoritma:**

```
1. BAŞLAT: Rastgele 100 çözüm oluştur (popülasyon)

2. DEĞERLENDİR: Her çözümün fitness'ını hesapla

3. SEÇ: En iyi çözümleri ebeveyn olarak seç
   (fitness yüksek olanlar daha çok seçilir)

4. ÇAPRAZLA (Crossover): İki ebeveyni birleştir
   Ebeveyn A: [1,0,1,1,0]
   Ebeveyn B: [0,1,1,0,1]
   Kesim noktası: 3
   Çocuk:     [1,0,1|0,1]  ← A'nın ilk 3'ü + B'nin son 2'si

5. MUTASYON: Rastgele değişiklik (küçük olasılıkla)
   Çocuk:     [1,0,1,0,1]
   Mutasyon:  [1,0,0,0,1]  ← 3. gen değişti

6. YENİ NESİL: Çocuklar yeni popülasyonu oluşturur

7. TEKRAR: Adım 2'ye dön (100 nesil boyunca)

8. BİTİR: En iyi çözümü döndür
```

**Neden çalışır?**
- İyi çözümlerin özellikleri bir sonraki nesle aktarılır
- Çaprazlama: iyi parçaları birleştirir
- Mutasyon: çeşitlilik sağlar, lokal optimumdan kaçar
- Doğal seleksiyon: kötüler elenir

### Tabu Search — Tabu Arama

Hafızalı yerel arama. Aynı yere tekrar gitmemeyi garanti eder.

**Problem:** Yerel arama döngüye girebilir: A → B → A → B → ...

**Tabu Search çözümü:** Son N hamleyi "yasaklı" listesine koy.

**Algoritma:**

```
1. Başlangıç çözümü seç (x)
2. Tabu listesi = [] (boş)
3. Tekrar et:
   a) Tüm komşu çözümleri listele
   b) Tabu listesindeki hamleleri çıkar
   c) Kalanlar arasından en iyisini seç
   d) O hamleyi tabu listesine ekle
   e) Liste N'den uzunsa en eskiyi sil
4. Belirli adım sonra dur
```

**Örnek — TSP:**

```
Mevcut tur: A → B → C → D → A
Komşu hamleler (iki şehri değiştir):
  - A↔B: B → A → C → D → B (maliyet: 120)
  - B↔C: A → C → B → D → A (maliyet: 115)  ← en iyi
  - C↔D: A → B → D → C → A (maliyet: 125)

Tabu listesi: [A↔B, D↔C]  (son 2 hamle)

B↔C yasak değil → seç
Yeni tabu listesi: [D↔C, B↔C]  (A↔B düştü, B↔C eklendi)

→ Döngüye girmez, yeni bölgeler keşfeder
```

**Ne zaman kullanılır?**
- Kombinatoryal problemler (TSP, VRP, Scheduling)
- Komşuluk yapısı net tanımlı problemler

## 5.4 Karşılaştırma

| Yöntem | Optimal Garanti | Hız | En İyi Kullanım |
|--------|-----------------|-----|-----------------|
| Exact (MIP) | ✅ Evet | Yavaş olabilir | Küçük-orta, kesinlik şart |
| Greedy | ❌ Hayır | Çok hızlı | Başlangıç çözümü |
| SA | ❌ Hayır | Hızlı | Continuous, sürekli uzay |
| GA | ❌ Hayır | Orta | Kombinatoryal, paralel |
| Tabu | ❌ Hayır | Hızlı | Scheduling, routing |

---

# 6. SOLVER MİMARİSİ

## 6.1 Solver Nedir?

Solver, matematiksel modeli alıp optimal çözümü bulan yazılımdır.

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Model     │ →   │   Solver    │ →   │   Çözüm     │
│  (değişken, │     │  (Simplex,  │     │  (x*, z*)   │
│   amaç,     │     │   Branch &  │     │             │
│   kısıt)    │     │   Bound)    │     │             │
└─────────────┘     └─────────────┘     └─────────────┘
```

## 6.2 Solver Türleri

### Açık Kaynak

| Solver | Tür | Güç | Kullanım |
|--------|-----|-----|----------|
| **CBC** | LP/MIP | Orta | PuLP default, genel amaç |
| **GLPK** | LP/MIP | Düşük | Akademik, basit problemler |
| **HiGHS** | LP/MIP | Yüksek | SciPy default, hızlı LP |
| **SCIP** | MIP | Yüksek | Akademik ücretsiz |
| **OR-Tools** | CP/MIP | Yüksek | Google, scheduling |

### Ticari

| Solver | Tür | Güç | Lisans |
|--------|-----|-----|--------|
| **Gurobi** | LP/MIP/QP | Çok yüksek | Akademik ücretsiz |
| **CPLEX** | LP/MIP/QP | Çok yüksek | IBM, pahalı |
| **Xpress** | LP/MIP | Yüksek | FICO |

**Fark:** Ticari solver'lar büyük problemlerde 10-100x daha hızlı olabilir.

## 6.3 Modelleme Dili vs Solver

```
Modelleme Dili          Solver
(Model yazar)           (Model çözer)
      │                      │
    PuLP  ─────────────→   CBC
    Pyomo ─────────────→   Gurobi
    OR-Tools ──────────→   SCIP
      │                      │
      └──── Aynı model, ─────┘
           farklı solver
```

**Avantaj:** Pyomo'da model yaz, solver'ı tek satırda değiştir:
```python
solver = SolverFactory('cbc')    # açık kaynak
solver = SolverFactory('gurobi') # ticari (daha hızlı)
```

## 6.4 Çözüm Süreci

```
1. PRESOLVE
   - Gereksiz kısıtları kaldır
   - Sabit değişkenleri tespit et
   - Model küçült

2. LP RELAXATION
   - Integer kısıtlarını gevşet
   - Simplex ile çöz
   - Bound hesapla

3. BRANCH & BOUND
   - Ağaç oluştur
   - Node'ları çöz
   - Prune et

4. HEURISTICS
   - Erken feasible çözüm bul
   - Bound'ları sıkılaştır

5. CUTTING PLANES
   - Ekstra kısıtlar ekle
   - LP relaxation'ı güçlendir

6. POSTSOLVE
   - Orijinal forma dön
   - Çözümü raporla
```

## 6.5 Performans İpuçları

```
1. TIGHT FORMULATION
   - Gevşek kısıt yerine sıkı kısıt
   - LP relaxation güçlü olsun

2. SİMETRİ KIRMA
   - Eşdeğer çözümleri eleme
   - x[1] ≤ x[2] ≤ x[3]

3. WARM START
   - Bilinen iyi çözümü başlangıç yap
   - Heuristic → MIP

4. GAP TOLERANSI
   - %0 yerine %1 yeterli mi?
   - Zaman kazancı büyük

5. PARALEL
   - Çok çekirdek kullan
   - Gurobi/CPLEX otomatik yapar
```

---

# 7. GERÇEK DÜNYA PROBLEMLERİ

## 7.1 Vehicle Routing Problem (VRP)

**Problem:** Bir depodan N müşteriye teslimat yap. Araç kapasitesi sınırlı. Toplam mesafeyi minimize et.

```
Senaryo:
- 1 depo, 5 müşteri, 2 araç
- Her araç max 100 kg taşıyabilir
- Müşteri talepleri: 30, 40, 25, 35, 20 kg
- Amaç: En kısa toplam rota

        ○ M1 (30kg)
       /
Depo ●─────○ M2 (40kg)
      \
       ○ M3 (25kg)
```

**Değişkenler:**
```
x[i,j,k] ∈ {0,1} = Araç k, i noktasından j noktasına gidiyor mu?

Örnek:
x[Depo, M1, Araç1] = 1 → Araç 1, depodan M1'e gidiyor
x[M1, M3, Araç1] = 1 → Araç 1, M1'den M3'e gidiyor
```

**Kısıtlar:**
```
1. Her müşteri tam 1 kez ziyaret edilmeli
   Σ x[i,j,k] = 1, ∀j (her müşteri için)

2. Araç kapasitesi aşılmamalı
   Σ talep[j] · x[i,j,k] ≤ 100, ∀k (her araç için)

3. Her rota depodan başlayıp depoya dönmeli
   Araç çıktıysa dönmeli

4. Subtour elimination (alt-tur engelleme)
   Depoyu içermeyen kapalı tur yasak
   (M1→M2→M1 gibi, depoya uğramadan döngü olmaz)
```

**Varyantlar (Problem Çeşitleri):**

| Varyant | Ek Kısıt | Örnek |
|---------|----------|-------|
| **CVRP** | Kapasite | Araç max 100 kg |
| **VRPTW** | Zaman penceresi | M1'e 09:00-11:00 arası git |
| **PDVRP** | Al-götür | M1'den al, M3'e bırak |
| **MDVRP** | Çoklu depo | 3 farklı depo var |

**Çözüm Yöntemi:**

```
Küçük problem (< 20-30 müşteri):
→ MIP ile optimal çözüm bulunabilir
→ Dakikalar içinde çözülür

Orta problem (30-100 müşteri):
→ MIP çok yavaş kalır (saatler)
→ MIP + heuristic hybrid: önce heuristic başlangıç çözümü, sonra MIP iyileştir

Büyük problem (> 100 müşteri):
→ MIP pratik değil
→ Saf heuristic: Clarke-Wright savings, LNS (Large Neighborhood Search)
→ Saniyeler-dakikalar içinde "iyi" çözüm (optimal garanti yok)
```

**Neden MIP büyük problemlerde patlar?**
```
20 müşteri, 3 araç:
  Değişken sayısı ≈ 20 × 20 × 3 = 1,200 binary
  → MIP çözebilir

100 müşteri, 10 araç:
  Değişken sayısı ≈ 100 × 100 × 10 = 100,000 binary
  → Branch & Bound çok dal açar, saatler sürer
```

## 7.2 Job Shop Scheduling

**Problem:** N iş, M makine. Her iş belirli sırayla makinelerden geçmeli. Toplam süreyi (makespan) minimize et.

```
İş 1: Makine A (3dk) → Makine B (2dk) → Makine C (4dk)
İş 2: Makine B (2dk) → Makine A (3dk) → Makine C (1dk)
İş 3: Makine C (2dk) → Makine B (3dk) → Makine A (2dk)

Amaç: Tüm işler en erken ne zaman biter?
```

**Değişkenler:**
```
s[i,j] = İş i'nin makine j'deki başlama zamanı
y[i,k,j] ∈ {0,1} = Makine j'de iş i, iş k'den önce mi?
```

**Kısıtlar:**
```
- Operasyon sırası (precedence)
- Makine çakışma yok (no overlap)
- Başlama zamanı ≥ 0
```

**Çözüm:** CP-SAT (OR-Tools) bu tip problemlerde çok güçlü.

## 7.3 Knapsack Problem

**Problem:** N eşya var. Her birinin değeri ve ağırlığı var. Çanta kapasitesi W. Toplam değeri maksimize et.

```
Eşya     Değer   Ağırlık
─────────────────────────
Laptop    100      3
Tablet     80      2
Telefon    60      1
Kitap      20      1
─────────────────────────
Kapasite: 4 kg
```

**Model:**
```
max  Σ değer[i] · x[i]
s.t. Σ ağırlık[i] · x[i] ≤ W
     x[i] ∈ {0,1}
```

**Optimal:** Laptop + Telefon + Kitap = 180 değer, 5 kg... sığmıyor!
Laptop + Tablet = 180 değer, 5 kg... sığmıyor!
Tablet + Telefon + Kitap = 160 değer, 4 kg ✓

**Varyantlar:**
- 0-1 Knapsack: Her eşya 1 kez
- Bounded: Her eşyadan sınırlı sayıda
- Unbounded: Her eşyadan sınırsız

## 7.4 Workforce Scheduling (Vardiya Planlama)

**Problem:** Çalışanları vardiyalara ata. İhtiyaçları karşıla, maliyeti minimize et.

```
Slot bazlı ihtiyaç:
06:00-10:00 → 8 kişi
10:00-14:00 → 15 kişi
14:00-18:00 → 20 kişi
...

Vardiyalar:
V1: 06:00-14:00 (100₺)
V2: 10:00-18:00 (120₺)
V3: 14:00-22:00 (130₺)
```

**Değişkenler:**
```
x[v] = Vardiya v'ye atanan kişi sayısı (integer)
y[e,v] = Çalışan e, vardiya v'ye atandı mı? (binary)
```

**Kısıtlar:**
```
- Slot ihtiyacı karşılansın
- Her çalışan max 1 vardiya
- Ardışık gün kuralları
- Skill gereksinimleri
```

## 7.5 Facility Location

**Problem:** Potansiyel lokasyonlardan hangilerine fabrika/depo açalım?

```
        Fabrika?          Müşteriler
           │
    ┌──────┼──────┐
    ○      ○      ○       ●  ●  ●
   F1     F2     F3       M1 M2 M3
```

**Değişkenler:**
```
y[f] ∈ {0,1} = Fabrika f açık mı?
x[f,m] ≥ 0 = Fabrika f'den müşteri m'ye gönderim
```

**Amaç:**
```
min Σ açılış_maliyeti[f] · y[f] + Σ taşıma_maliyeti[f,m] · x[f,m]
```

**Kısıtlar:**
```
- Talep karşılansın: Σ x[f,m] = talep[m]
- Kapasite: Σ x[f,m] ≤ kapasite[f] · y[f]
- Açık değilse gönderemezsin: x[f,m] ≤ M · y[f]
```

---

# 8. PROBLEM TİPİ SEÇİM REHBERİ

## 8.1 Karar Ağacı

```
Problem lineer mi?
    │
    ├─ Evet → Değişkenler tam sayı mı?
    │              │
    │              ├─ Hayır → LP (Simplex)
    │              │
    │              ├─ Bazıları → MIP (Branch & Bound)
    │              │
    │              └─ Hepsi → IP (Branch & Bound)
    │
    └─ Hayır → Problem convex mi?
                   │
                   ├─ Evet → Convex NLP
                   │
                   └─ Hayır → Metaheuristic veya Global NLP
```

## 8.2 Boyut Rehberi

| Problem Boyutu | LP | IP/MIP | Önerilen |
|----------------|-----|--------|----------|
| < 1,000 değişken | Saniyeler | Saniyeler-dakikalar | Exact |
| 1,000 - 100,000 | Saniyeler | Dakikalar-saatler | Exact + Gap |
| > 100,000 | Dakikalar | Saatler-günler | Heuristic hybrid |

## 8.3 Checklist

Bir optimizasyon projesi başlatırken:

```
□ Problemi net tanımla (amaç ne?)
□ Karar değişkenlerini belirle
□ Kısıtları listele (hard vs soft)
□ Lineerlik kontrolü yap
□ Boyut tahmini yap
□ Doğru solver/yöntem seç
□ Basit versiyonla başla, karmaşıklaştır
□ Sonuçları doğrula (sanity check)
□ Sensitivity analizi yap
```

---

# 9. ÖZET

## Temel Kavramlar

| Kavram | Açıklama |
|--------|----------|
| **LP** | Lineer amaç + lineer kısıt + sürekli değişken |
| **IP** | LP + tam sayı değişken |
| **MIP** | LP + karışık değişken (integer + continuous) |
| **Relaxation** | Integer kısıtını gevşetip LP olarak çözme |
| **Branch & Bound** | MIP çözüm algoritması |
| **Gap** | Optimal'e uzaklık ölçüsü |
| **Heuristic** | Probleme özel sezgisel kural |
| **Metaheuristic** | Genel arama stratejisi (SA, GA, Tabu) |

## Algoritma Özeti

| Algoritma | Problem | Optimal | Karmaşıklık |
|-----------|---------|---------|-------------|
| Simplex | LP | ✅ | O(n²) - O(n³) |
| Branch & Bound | MIP | ✅ | Exponential (worst) |
| Simulated Annealing | Genel | ❌ | Parametre bağımlı |
| Genetic Algorithm | Genel | ❌ | O(g × p × n) |

## Solver Seçimi

| İhtiyaç | Solver |
|---------|--------|
| Hızlı LP | HiGHS (SciPy) |
| Genel MIP, ücretsiz | CBC (PuLP) |
| Scheduling | CP-SAT (OR-Tools) |
| Büyük MIP, hız kritik | Gurobi / CPLEX |
| Akademik araştırma | SCIP |
