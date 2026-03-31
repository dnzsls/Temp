# Optimizasyon Konu Anlatımı
## Teori, Algoritmalar ve Gerçek Dünya

---

# 1. OPTİMİZASYON TEMELLERİ

## 1.1 Tanım

**Optimizasyon**, kısıtlı kaynaklar altında en iyi kararı bulma sürecidir.

```
Günlük hayat örnekleri:
- "En kısa yoldan işe nasıl giderim?" → Route optimization
- "Bütçemi nasıl dağıtayım?" → Resource allocation
- "Hangi ürünleri ne kadar üreteyim?" → Production planning
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
maximize   z = c₁x₁ + c₂x₂ + ... + cₙxₙ
subject to:
           a₁₁x₁ + a₁₂x₂ + ... ≤ b₁
           a₂₁x₁ + a₂₂x₂ + ... ≤ b₂
           ...
           x₁, x₂, ... ≥ 0
```

**Matris formunda:**
```
max  z = cᵀx
s.t. Ax ≤ b
     x ≥ 0
```

## 2.3 Simplex Algoritması

LP'nin çözüm yöntemi. 1947'de George Dantzig tarafından geliştirildi.

### Geometrik Anlam

Her kısıt, n-boyutlu uzayda bir **yarı-düzlem** tanımlar. Tüm kısıtların kesişimi bir **convex polytope** (dışbükey çokgen) oluşturur. Buna **feasible region** denir.

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
         │    │    (yeşil alan)
      0 ─┼────┼────── x₁
         0    4    8
```

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

4. BOUND: 
   - Çözüm integer → kaydet (incumbent)
   - LP sonucu incumbent'tan kötü → budala (prune)
   - Çözüm kesirli → tekrar branch

5. OPTIMAL: Tüm dallar işlendi → en iyi incumbent optimal
```

### Görsel

```
                    LP Relaxation
                    x=3.7, z=42.8
                         │
            ┌────────────┴────────────┐
            │                         │
        x ≤ 3                     x ≥ 4
        z=40.2                    z=41.5
            │                         │
        (integer!)              ┌─────┴─────┐
        Incumbent=40.2          │           │
                            x ≤ 4       x ≥ 5
                            z=41.5      z=39.1
                            (integer!)  (< 41.5, prune!)
                            
        Optimal: x=4, z=41.5
```

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

Probleme özel, elle tasarlanmış kural.

**Greedy (Açgözlü):**
```
Her adımda lokal en iyiyi seç.

Örnek - Knapsack:
1. Değer/ağırlık oranına göre sırala
2. Sığdıkça ekle
3. Sığmayınca dur

Hızlı ama optimal garanti yok.
```

**Construction Heuristic:**
```
Çözümü adım adım inşa et.

Örnek - TSP (Nearest Neighbor):
1. Rastgele şehirden başla
2. En yakın ziyaret edilmemiş şehre git
3. Tüm şehirler bitene kadar tekrar
```

## 5.3 Metaheuristic (Üst-Sezgisel)

Probleme bağımsız, genel arama stratejisi.

### Simulated Annealing (SA)

Metal tavlama sürecinden esinlenme.

```
Fikir:
- Yüksek sıcaklık → Riskli adımlar kabul (keşif)
- Düşük sıcaklık → Sadece iyileştirme (sömürü)

Algoritma:
1. Rastgele başlangıç çözümü
2. Komşu çözüm üret
3. Daha iyiyse kabul et
4. Daha kötüyse olasılıkla kabul et: P = exp(-Δ/T)
5. Sıcaklığı azalt
6. Tekrar (2-5)

Avantaj: Lokal optimumdan kaçabilir
```

### Genetic Algorithm (GA)

Doğal evrimden esinlenme.

```
Terimler:
- Birey = Bir çözüm
- Gen = Çözümün bir parçası
- Popülasyon = Çözümler kümesi
- Fitness = Çözümün kalitesi

Algoritma:
1. Rastgele popülasyon oluştur
2. Fitness'a göre ebeveyn seç
3. Çaprazlama (crossover): İki ebeveyni birleştir
4. Mutasyon: Rastgele değişiklik
5. Yeni nesil oluştur
6. Tekrar (2-5)

Örnek:
Ebeveyn A: [1,0,1,1,0]
Ebeveyn B: [0,1,1,0,1]
Çocuk:     [1,0,1,0,1]  (A'nın ilk yarısı + B'nin ikinci yarısı)
Mutasyon:  [1,0,0,0,1]  (3. bit değişti)
```

### Tabu Search

Hafızalı yerel arama.

```
Fikir:
- Yerel aramada en iyi komşuya git
- Son N hamleyi "tabu" listesine ekle
- Tabu hamleler tekrar yapılamaz
- Döngüye girmez, yeni bölgeler keşfeder

Örnek:
Mevcut: A → B → C → D
Tabu listesi: [A↔B, C↔D]
Bu hamleler yasak, başka komşu dene
```

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

**Problem:** N müşteriye teslimat yap. Araç kapasitesi sınırlı. Toplam mesafeyi minimize et.

```
        ○ Müşteri 1
       /
Depo ●─────○ Müşteri 2
       \
        ○ Müşteri 3
```

**Değişkenler:**
```
x[i,j,k] ∈ {0,1} = Araç k, i'den j'ye gidiyor mu?
```

**Kısıtlar:**
```
- Her müşteri tam 1 kez ziyaret edilmeli
- Araç kapasitesi aşılmamalı
- Her rota depodan başlayıp depoya dönmeli
- Subtour elimination (alt-tur engelleme)
```

**Varyantlar:**
- CVRP: Kapasiteli VRP
- VRPTW: Zaman pencereli VRP
- PDVRP: Pickup & Delivery

**Çözüm:** Küçük (< 50 müşteri) → MIP, Büyük → Heuristic (Clarke-Wright, LNS)

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
