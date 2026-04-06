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

## 2.2 Standart Form ve Matris Gösterimi

LP problemleri **standart formda** yazılır:

```
min  z = c₁x₁ + c₂x₂ + ... + cₙxₙ

kısıtlar:
     a₁₁x₁ + a₁₂x₂ + ... ≤ b₁
     a₂₁x₁ + a₂₂x₂ + ... ≤ b₂
     x₁, x₂, ... ≥ 0
```

**Matris formunda:** `min z = cᵀx,  Ax ≤ b,  x ≥ 0`

| Sembol | Ne | Örnek |
|--------|-----|-------|
| **x** | Karar değişkenleri (aranan) | [x₁, x₂]ᵀ |
| **c** | Amaç katsayıları | [3, 2]ᵀ |
| **cᵀx** | Amaç fonksiyonu (iç çarpım) | 3x₁ + 2x₂ |
| **A** | Kısıt katsayıları matrisi | [[1,1], [2,1]] |
| **b** | Kısıt sağ tarafları | [10, 16]ᵀ |
| **ᵀ** | Transpoz (sütunu satıra çevir) | [3,2]ᵀ → [3 2] |

## 2.3 Standart Form → linprog → Simplex

| | **Standart Form** | **linprog** | **Simplex** |
|---|---|---|---|
| **Ne?** | Matematik gösterimi | Python fonksiyonu | Çözüm algoritması |
| **Kim yapar?** | Sen (kağıtta) | Sen (kodda) | linprog (otomatik) |

### Örnek Problem — 3 Format

**Problem:** 2 ürün üret, maliyeti minimize et, kapasiteyi aşma.

<table>
<tr>
<th>Standart Form</th>
<th>linprog Kodu</th>
<th>Simplex (arka plan)</th>
</tr>
<tr>
<td>

```
min z = 3x₁ + 2x₂

kısıtlar:
  x₁ + x₂ ≤ 10
  2x₁ + x₂ ≤ 16
  x₁, x₂ ≥ 0
```

</td>
<td>

```python
c = [3, 2]
A_ub = [[1,1], [2,1]]
b_ub = [10, 16]
bounds = [(0,None), (0,None)]

result = linprog(c, 
  A_ub=A_ub, 
  b_ub=b_ub, 
  bounds=bounds)
```

</td>
<td>

```
Köşe (0,0)  → z=0
Köşe (0,10) → z=20 ✓
Köşe (6,4)  → z=26

Optimal: (0,10)
z = 20
```

</td>
</tr>
<tr>
<td>

**Satır satır:**
- `3x₁ + 2x₂` → maliyet
- `x₁ + x₂ ≤ 10` → kapasite 1
- `2x₁ + x₂ ≤ 16` → kapasite 2

</td>
<td>

**Parametre eşleştirme:**
- `c` → amaç katsayıları
- `A_ub` → ≤ kısıt matrisi
- `b_ub` → ≤ sağ taraflar
- `bounds` → x ≥ 0

</td>
<td>

**Ne yapıyor:**
- Köşeleri geziyor
- z'yi karşılaştırıyor
- En küçük z'yi buluyor

</td>
</tr>
</table>

**Sonuç:** `result.x = [0, 10]`, `result.fun = 20`

## 2.4 Kısıt Formatları ve Dönüşümler

Standart form ve linprog farklı formatlar kabul eder. Dönüşüm gerekebilir:

| Yazmak İstediğin | Standart Form | linprog Karşılığı |
|------------------|---------------|-------------------|
| **minimize** | ✅ Direkt yaz | ✅ `c = [5, 3]` |
| **maximize** | ❌ Dönüştür: -c yap | ❌ `c = [-5, -3]`, sonucu -1 ile çarp |
| **≤ kısıtı** | ✅ Direkt yaz | ✅ `A_ub`, `b_ub` |
| **≥ kısıtı** | ❌ Dönüştür: -1 ile çarp | ❌ `A_ub`'a -1 ile çarpılmış ekle |
| **= kısıtı** | ✅ Direkt yaz | ✅ `A_eq`, `b_eq` (ayrı parametre) |

**Dönüşüm örnekleri:**

```
MAXIMIZE → MINIMIZE:
    max z = 5x₁ + 3x₂
    ↓
    min z' = -5x₁ - 3x₂
    (sonucu -1 ile çarp: z = -z')

≥ → ≤:
    x₁ + x₂ ≥ 10
    ↓
    -x₁ - x₂ ≤ -10
    (her iki tarafı -1 ile çarp)

= KISITI:
    x₁ + x₂ = 10
    ↓
    linprog'da: A_eq = [[1, 1]], b_eq = [10]
    (ayrı parametre, dönüşüm yok)
```

## 2.5 SciPy linprog Kullanımı

**Örnek problem:**
```
max  z = 5x₁ + 4x₂

kısıtlar:
     x₁ + x₂ ≤ 10      (≤ kısıtı)
     2x₁ + x₂ ≤ 15     (≤ kısıtı)
     x₁ + x₂ = 8       (= kısıtı)
     x₁, x₂ ≥ 0
```

**linprog kodu:**
```python
from scipy.optimize import linprog

# 1. AMAÇ: max → min dönüşümü (katsayıları negatif yap)
c = [-5, -4]  # max 5x₁+4x₂ → min -5x₁-4x₂

# 2. ≤ KISITLARI: A_ub @ x ≤ b_ub
A_ub = [
    [1, 1],   # x₁ + x₂ ≤ 10
    [2, 1],   # 2x₁ + x₂ ≤ 15
]
b_ub = [10, 15]

# 3. = KISITLARI: A_eq @ x = b_eq
A_eq = [
    [1, 1],   # x₁ + x₂ = 8
]
b_eq = [8]

# 4. DEĞİŞKEN SINIRLARI: x ≥ 0
bounds = [(0, None), (0, None)]

# 5. ÇÖZ
result = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=bounds)

# 6. SONUÇ
if result.success:
    print(f"x₁ = {result.x[0]:.2f}")
    print(f"x₂ = {result.x[1]:.2f}")
    print(f"max z = {-result.fun:.2f}")  # min sonucunu -1 ile çarp → max
else:
    print("Çözüm bulunamadı!")
```

**Çıktı:**
```
x₁ = 7.00
x₂ = 1.00
max z = 39.00
```

**linprog özellikleri:**

| Özellik | Durum |
|---------|-------|
| minimize | ✅ Direkt |
| maximize | ❌ Dönüşüm lazım (c'yi negatif yap) |
| ≤ kısıtı | ✅ `A_ub`, `b_ub` |
| ≥ kısıtı | ❌ Dönüşüm lazım (-1 ile çarp) |
| = kısıtı | ✅ `A_eq`, `b_eq` |
| Integer | ❌ Desteklemez (sadece continuous) |
| Solver | HiGHS (çok hızlı) |
| Kurulum | Gereksiz (SciPy ile gelir) |

## 2.6 Simplex Algoritması

LP'nin çözüm yöntemi. 1947'de George Dantzig tarafından geliştirildi. linprog (ve diğer LP solver'lar) arka planda bunu kullanır.

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

**Feasible region:** Tüm kısıtları sağlayan noktaların kümesi.

### Algoritma Adımları

```
1. BAŞLA: Bir köşe noktasından başla (feasible region'ın köşesi)

2. KONTROL: Komşu köşelere bak
   - Daha iyi (daha düşük z) köşe var mı?

3. HAREKET: Varsa o köşeye git, yoksa DUR (optimal buldun)

4. TEKRAR: Adım 2'ye dön
```

**Neden çalışır?**
- LP'de optimal çözüm her zaman bir köşededir (convexity özelliği)
- Simplex köşeleri gezer, içeriyi taramaz → çok hızlı
- Her adımda z azalır (min) veya artar (max) → sonlu adımda biter

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

## 3.4 Araçlarda Integer Tanımlama

**PuLP:**
```python
# Integer (tam sayı)
x = LpVariable("x", lowBound=0, cat="Integer")

# Binary (0 veya 1)
y = LpVariable("y", cat="Binary")

# Continuous (kesirli - default)
z = LpVariable("z", lowBound=0)  # cat="Continuous"
```

**OR-Tools CP-SAT:**
```python
# CP-SAT sadece integer destekler (continuous yok!)
x = model.new_int_var(0, 100, "x")

# Binary
y = model.new_bool_var("y")
```

**Pyomo:**
```python
# Integer
model.x = Var(within=NonNegativeIntegers)

# Binary
model.y = Var(within=Binary)

# Continuous
model.z = Var(within=NonNegativeReals)
```

**SciPy linprog:**
```python
# ❌ Integer desteklemez!
# Sadece continuous çözer
# IP/MIP için PuLP veya OR-Tools kullan
```

## 3.5 LP Relaxation

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

MIP her zaman çalışmaz. Problem çok büyükse (100,000+ değişken) veya zaman kısıtlıysa (saniyeler içinde cevap lazım) **heuristic** yöntemler kullanılır.

| Yöntem | Ne Yapar | Örnek |
|--------|----------|-------|
| **Heuristic** | Probleme özel kural, hızlı ama optimal garanti yok | Greedy, Nearest Neighbor |
| **Metaheuristic** | Genel arama stratejisi, lokal optimumdan kaçabilir | Simulated Annealing, Genetic Algorithm, Tabu Search |

**Pratikte:**
```
1. Önce MIP dene
2. Yavaşsa → gap toleransı ekle (%1-5)
3. Hala yavaşsa → heuristic ile başlangıç çözümü bul, MIP'e ver
4. MIP hiç bitmiyorsa → saf heuristic/metaheuristic kullan
```

Bu workshop'ta MIP'e odaklanıyoruz. Heuristic/Metaheuristic ayrı bir konu.

---

# 6. SOLVER VE MODELLEME ARAÇLARI

## 6.1 İki Farklı Kavram

```
MODELLEME ARACI              SOLVER
(Modeli yazar)               (Modeli çözer)
                    
PuLP, Pyomo, OR-Tools   →    CBC, Gurobi, CPLEX, HiGHS
                    
"Ben problemi tanımlıyorum"  "Ben optimal çözümü buluyorum"
```

**Analoji:**
- Modelleme aracı = Word (yazı yazarsın)
- Solver = Yazıcı (çıktı alırsın)

Aynı modeli farklı solver'larla çözebilirsin.

## 6.2 Python Modelleme Araçları

### SciPy (linprog)

```
Ne: Python'un bilimsel kütüphanesinin optimizasyon modülü
Kurulum: Zaten var (pip install scipy ile gelir)
Format: Matris formunda (A, b, c)
LP: ✅   MIP: ❌
```

**Özellikler:**
- En basit, kurulum gerektirmez
- Sadece LP çözer (integer yok!)
- Matris formatı: küçük problemler için tamam, büyüklerde karışık

**Ne zaman kullan:**
- Hızlı LP denemesi
- Integer gerekmiyorsa
- Ekstra kurulum istemiyorsan

```python
from scipy.optimize import linprog

c = [100, 120]  # maliyet
A_ub = [[-1, 0], [0, -1]]  # kısıtlar (matris)
b_ub = [-2, -2]
result = linprog(c, A_ub=A_ub, b_ub=b_ub)
```

---

### PuLP

```
Ne: LP/MIP için Python modelleme kütüphanesi
Kurulum: pip install pulp
Format: Algebraik (matematiksel yazım)
LP: ✅   MIP: ✅
Default Solver: CBC (ücretsiz, birlikte gelir)
```

**Özellikler:**
- Öğrenmesi çok kolay
- Kod matematiğe benziyor
- CBC solver dahil, ekstra kurulum yok
- Gurobi, CPLEX gibi ticari solver'larla da çalışır

**Ne zaman kullan:**
- Genel LP/MIP problemleri
- Hızlı prototip
- Öğrenme aşaması

```python
from pulp import *

model = LpProblem("Ornek", LpMinimize)
x = LpVariable("x", lowBound=0, cat="Integer")
model += 100 * x  # amaç
model += x >= 2   # kısıt
model.solve()
```

---

### OR-Tools (Google)

```
Ne: Google'ın açık kaynak optimizasyon paketi
Kurulum: pip install ortools
Format: Algebraik
LP: ✅   MIP: ✅   CP: ✅
Solver: GLOP (LP), SCIP (MIP), CP-SAT (Constraint Programming)
```

**Özellikler:**
- CP-SAT: Scheduling için çok güçlü
- Native kısıtlar: `add_exactly_one()`, `add_no_overlap()`
- Routing için özel modül (VRP)
- Google tarafından aktif geliştiriliyor

**Ne zaman kullan:**
- Scheduling, atama problemleri
- VRP (Vehicle Routing)
- Mantıksal kısıtlar çok olduğunda

```python
from ortools.sat.python import cp_model

model = cp_model.CpModel()
x = model.new_int_var(0, 100, "x")
model.add(x >= 2)
model.minimize(100 * x)
solver = cp_model.CpSolver()
solver.solve(model)
```

**CP-SAT vs MIP:**
```
MIP'te "her çalışan tam 1 vardiya":
  model += lpSum(x[e,v] for v in vardiyalar) == 1

CP-SAT'ta:
  model.add_exactly_one(x[e,v] for v in vardiyalar)

→ CP-SAT bu tür kısıtları daha verimli çözer
```

---

### Pyomo

```
Ne: Algebraic Modeling Language (AML) - AMPL/GAMS'ın Python versiyonu
Kurulum: pip install pyomo + ayrı solver kurulumu
Format: Set, Parameter, Var, Constraint yapıları
LP: ✅   MIP: ✅   NLP: ✅
Solver: Harici (CBC, GLPK, Gurobi, CPLEX, IPOPT...)
```

**Özellikler:**
- En esnek ve güçlü
- Büyük, parametrik modeller için ideal
- Veriyi modelden ayırır (aynı model, farklı veri)
- Solver'ı tek satırda değiştirebilirsin
- Öğrenme eğrisi dik

**Ne zaman kullan:**
- Büyük, karmaşık modeller
- Akademik araştırma
- Farklı solver'ları test etmek istersen
- Nonlinear problemler (IPOPT ile)

```python
import pyomo.environ as pyo

model = pyo.ConcreteModel()
model.x = pyo.Var(within=pyo.NonNegativeIntegers)
model.obj = pyo.Objective(expr=100 * model.x, sense=pyo.minimize)
model.c1 = pyo.Constraint(expr=model.x >= 2)

solver = pyo.SolverFactory('cbc')  # veya 'gurobi', 'cplex'
solver.solve(model)
```

## 6.3 Karşılaştırma Tablosu

| Özellik | SciPy | PuLP | OR-Tools | Pyomo |
|---------|-------|------|----------|-------|
| **Kurulum** | Zaten var | Kolay | Kolay | Orta (solver ayrı) |
| **Öğrenme** | Kolay | Kolay | Orta | Zor |
| **LP** | ✅ | ✅ | ✅ | ✅ |
| **MIP** | ❌ | ✅ | ✅ | ✅ |
| **CP** | ❌ | ❌ | ✅ | ❌ |
| **NLP** | ❌ | ❌ | ❌ | ✅ |
| **Syntax** | Matris | Algebraik | Algebraik | AML |
| **Dahil Solver** | HiGHS | CBC | GLOP, CP-SAT | Yok |

## 6.4 Solver'lar

### Açık Kaynak (Ücretsiz)

| Solver | Tür | Hız | Notlar |
|--------|-----|-----|--------|
| **CBC** | LP/MIP | Orta | PuLP default, güvenilir |
| **HiGHS** | LP/MIP | Yüksek | SciPy default, yeni ve hızlı |
| **GLPK** | LP/MIP | Düşük | Akademik, basit |
| **SCIP** | MIP | Yüksek | Akademik ücretsiz |
| **CP-SAT** | CP | Yüksek | Scheduling için en iyi |

### Ticari (Paralı ama Çok Hızlı)

| Solver | Tür | Notlar |
|--------|-----|--------|
| **Gurobi** | LP/MIP/QP | En hızlılardan, akademik ücretsiz |
| **CPLEX** | LP/MIP/QP | IBM, kurumsal |
| **Xpress** | LP/MIP | FICO |

**Ticari vs Açık Kaynak:**
```
Küçük problem (< 1,000 değişken):
  CBC ve Gurobi arasında fark az

Büyük problem (> 100,000 değişken):
  Gurobi 10-100x daha hızlı olabilir
```

## 6.5 Hangisini Seçmeliyim?

```
Başlangıç / Öğrenme:
  → PuLP (kolay, CBC dahil)

Sadece LP, hızlı deneme:
  → SciPy linprog

Scheduling / Atama:
  → OR-Tools CP-SAT

Büyük model, farklı solver'lar:
  → Pyomo

Performans kritik, bütçe var:
  → Gurobi veya CPLEX
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

4. Subtour elimination (alt-tur engelleme)
   Depoyu içermeyen kapalı tur yasak
```

**Çözüm Yöntemi:**

| Problem Boyutu | Yöntem | Süre |
|----------------|--------|------|
| < 30 müşteri | MIP | Dakikalar |
| 30-100 müşteri | MIP + Heuristic hybrid | Dakikalar-saat |
| > 100 müşteri | Saf Heuristic (Clarke-Wright, LNS) | Saniyeler |

**Neden MIP büyük problemlerde yavaş?**
```
20 müşteri, 3 araç → ~1,200 binary değişken → MIP çözer
100 müşteri, 10 araç → ~100,000 binary değişken → Saatler sürer
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

**Çözüm Yöntemi:**

| Problem Boyutu | Yöntem | Araç |
|----------------|--------|------|
| Küçük (< 50 çalışan) | MIP | PuLP, Gurobi |
| Orta (50-500 çalışan) | MIP + gap toleransı | Gurobi, CPLEX |
| Büyük (> 500 çalışan) | CP-SAT veya Heuristic | OR-Tools CP-SAT |

**Neden CP-SAT iyi?**
```
Scheduling problemlerinde özel kısıtlar var:
- "Her çalışan tam 1 vardiya" → add_exactly_one()
- "Vardiyalar çakışmasın" → add_no_overlap()

CP-SAT bu kısıtları native destekler, MIP'ten hızlı çözer.
```

## 7.5 Facility Location (Tesis Yerleşimi)

**Problem:** Potansiyel lokasyonlardan hangilerine fabrika/depo açalım?

```
Senaryo:
- 3 potansiyel fabrika lokasyonu (F1, F2, F3)
- 4 müşteri (M1, M2, M3, M4)
- Her fabrikanın açılış maliyeti ve kapasitesi var
- Müşterilere taşıma maliyeti mesafeye bağlı

    Fabrika?          Müşteriler
       │
 ┌─────┼─────┐
 ○     ○     ○       ●  ●  ●  ●
F1    F2    F3       M1 M2 M3 M4
```

**Değişkenler:**
```
y[f] ∈ {0,1} = Fabrika f açık mı?
x[f,m] ≥ 0 = Fabrika f'den müşteri m'ye gönderim miktarı
```

**Amaç:**
```
min Σ açılış_maliyeti[f] · y[f] + Σ taşıma_maliyeti[f,m] · x[f,m]

(Açılış maliyeti + Taşıma maliyeti toplamını minimize et)
```

**Kısıtlar:**
```
1. Talep karşılansın: Σ x[f,m] = talep[m], ∀m
2. Kapasite: Σ x[f,m] ≤ kapasite[f] · y[f], ∀f
3. Kapalı fabrikadan gönderemezsin: x[f,m] ≤ M · y[f]
```

**Çözüm Yöntemi:**

| Problem Boyutu | Yöntem | Süre |
|----------------|--------|------|
| < 50 lokasyon, < 200 müşteri | MIP | Saniyeler-dakikalar |
| 50-500 lokasyon | MIP + gap toleransı (%1-5) | Dakikalar |
| > 500 lokasyon | Lagrangian Relaxation, Heuristic | Değişken |

**Not:** Facility Location genelde MIP ile iyi çözülür çünkü binary değişken sayısı (y[f]) lokasyon sayısı kadar, çok fazla değil.

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

## 8.3 Solver Seçim Kriterleri

### Açık Kaynak Solver'lar

| Solver | LP | MIP | Güçlü Yönü | Zayıf Yönü |
|--------|-----|-----|-----------|-----------|
| **CBC** | ✅ | ✅ | Ücretsiz, PuLP ile gelir, genel amaç | Büyük MIP'te yavaş |
| **HiGHS** | ✅ | ✅ | Çok hızlı LP, SciPy default | MIP'te CBC kadar olgun değil |
| **GLPK** | ✅ | ✅ | Hafif, her yerde çalışır | Performans düşük |
| **SCIP** | ✅ | ✅ | Akademik ücretsiz, güçlü MIP | Ticari kullanım paralı |
| **CP-SAT** | ❌ | ✅ | Scheduling'de çok hızlı, native kısıtlar | Sadece integer, LP yok |

### Ticari Solver'lar

| Solver | LP | MIP | Güçlü Yönü | Fiyat |
|--------|-----|-----|-----------|-------|
| **Gurobi** | ✅ | ✅ | En hızlı MIP, paralel, akademik ücretsiz | Ticari: $$$$ |
| **CPLEX** | ✅ | ✅ | Kurumsal destek, IBM ekosistemi | Ticari: $$$$ |
| **Xpress** | ✅ | ✅ | Hızlı, FICO entegrasyonu | Ticari: $$$ |

### Performans Farkı (Örnek)

```
10,000 binary değişkenli MIP:

CBC:    45 dakika
HiGHS:  30 dakika  
SCIP:   20 dakika
Gurobi: 3 dakika   ← 15x daha hızlı

Küçük problemlerde fark yok, büyüdükçe açılır.
```

### Hangi Durumda Hangisi?

| Durum | Önerilen Solver |
|-------|-----------------|
| Öğrenme / prototip | CBC (PuLP ile gelir) |
| Hızlı LP lazım | HiGHS (SciPy) |
| Scheduling / atama | CP-SAT (OR-Tools) |
| Büyük MIP, zaman kritik | Gurobi (akademik ücretsiz) |
| Kurumsal proje, destek lazım | Gurobi veya CPLEX |
| Akademik araştırma | SCIP (ücretsiz) |

### Solver Değiştirmek

**PuLP'ta:**
```python
model.solve(PULP_CBC_CMD())      # CBC
model.solve(GUROBI_CMD())        # Gurobi
model.solve(CPLEX_CMD())         # CPLEX
```

**Pyomo'da:**
```python
SolverFactory('cbc').solve(model)
SolverFactory('gurobi').solve(model)
SolverFactory('cplex').solve(model)
```

**OR-Tools'ta:**
```python
# LP/MIP
solver = pywraplp.Solver.CreateSolver('CBC')
solver = pywraplp.Solver.CreateSolver('SCIP')
solver = pywraplp.Solver.CreateSolver('GUROBI')
```

Model kodu aynı kalır, sadece solver ismi değişir.

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
