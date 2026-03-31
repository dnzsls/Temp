# Optimizasyon Workshop
## Matematiğe Çevir, Koda Dök

---

# 1. OPTİMİZASYON NEDİR?

**Tanım:** Kısıtlı kaynaklar altında en iyi kararı bulmak.

Her optimizasyon problemi **3 parçadan** oluşur:

| Parça | Soru | Örnek |
|-------|------|-------|
| **Karar Değişkenleri** | Ne hakkında karar veriyoruz? | Kaç kişi atayalım? |
| **Amaç Fonksiyonu** | Neyi optimize ediyoruz? | Maliyeti minimize et |
| **Kısıtlar** | Sınırlarımız neler? | Her vardiyada en az 2 kişi |

---

# 2. PROBLEM TANIMI

## 2.1 Senaryo

Bir çağrı merkezinde günün farklı saatlerinde farklı personel ihtiyacı var. 4 farklı vardiya tipi mevcut. Her vardiyaya kaç kişi atayacağımıza karar vereceğiz.

**Zorluk:** Vardiyalar farklı zaman dilimlerini kapsıyor. Bir kişi V1'e atandığında 06:00-14:00 arası çalışıyor, yani hem S1 hem S2 slotunda aktif.

## 2.2 Veri

**Vardiyalar:**

| Vardiya | Saat | Maliyet (₺/kişi) |
|---------|------|------------------|
| V1 | 06:00-14:00 | 100 |
| V2 | 10:00-18:00 | 120 |
| V3 | 14:00-22:00 | 130 |
| V4 | 18:00-02:00 | 150 |

**Slotlar ve Personel İhtiyacı:**

| Slot | Saat | Min İhtiyaç |
|------|------|-------------|
| S1 | 06:00-10:00 | 8 kişi |
| S2 | 10:00-14:00 | 15 kişi |
| S3 | 14:00-18:00 | 20 kişi |
| S4 | 18:00-22:00 | 18 kişi |
| S5 | 22:00-02:00 | 10 kişi |

**Hangi Vardiya Hangi Slotu Kapsıyor?**

| Slot | Saat | Kapsayan Vardiyalar |
|------|------|---------------------|
| S1 | 06:00-10:00 | V1 |
| S2 | 10:00-14:00 | V1, V2 |
| S3 | 14:00-18:00 | V2, V3 |
| S4 | 18:00-22:00 | V3, V4 |
| S5 | 22:00-02:00 | V4 |

```
Zaman Çizelgesi:

       06    10    14    18    22    02
        |-----|-----|-----|-----|-----|
V1:     [===========]                      06-14, 100₺
V2:           [===========]                10-18, 120₺
V3:                 [===========]          14-22, 130₺
V4:                       [===========]    18-02, 150₺
        |-----|-----|-----|-----|-----|
Slot:    S1    S2    S3    S4    S5
İhtiyaç: 8     15    20    18    10
```

## 2.3 Amaç

**Toplam maliyeti minimize et** — ama her slotta minimum personel ihtiyacını karşılayarak.

## 2.4 Neden Zor?

- V1'e atadığın kişi hem S1 hem S2'de çalışıyor
- V2 hem S2 hem S3'ü kapsıyor — stratejik pozisyon
- V4 en pahalı (150₺) ama S5'i sadece o kapsıyor — mecbur kullanacaksın
- Solver tüm bunları dengelemeli

---

# 3. MATEMATİKSEL MODEL

## 3.1 Karar Değişkenleri

### Mantık
"Her vardiyaya kaç kişi atayacağız?" sorusunun cevabı.

### Tanım

```
x[V1] = V1 vardiyasına (06-14) atanan kişi sayısı
x[V2] = V2 vardiyasına (10-18) atanan kişi sayısı
x[V3] = V3 vardiyasına (14-22) atanan kişi sayısı
x[V4] = V4 vardiyasına (18-02) atanan kişi sayısı

Tümü için: x ∈ Z≥0 (sıfır veya pozitif tam sayı)
```

### Kod karşılığı (PuLP)

```python
from pulp import *

model = LpProblem("Vardiya", LpMinimize)

# Tek tek tanımlama
x_V1 = LpVariable("V1", lowBound=0, cat="Integer")
x_V2 = LpVariable("V2", lowBound=0, cat="Integer")
x_V3 = LpVariable("V3", lowBound=0, cat="Integer")
x_V4 = LpVariable("V4", lowBound=0, cat="Integer")

# veya dict ile toplu tanımlama (daha pratik)
vardiyalar = ["V1", "V2", "V3", "V4"]
x = LpVariable.dicts("x", vardiyalar, lowBound=0, cat="Integer")
```

**Eşleştirme:**

| Matematik | Python (tek tek) | Python (dict) |
|-----------|------------------|---------------|
| x[V1] ∈ Z≥0 | `LpVariable("V1", lowBound=0, cat="Integer")` | `x["V1"]` |
| x[V2] ∈ Z≥0 | `LpVariable("V2", lowBound=0, cat="Integer")` | `x["V2"]` |
| x[V3] ∈ Z≥0 | `LpVariable("V3", lowBound=0, cat="Integer")` | `x["V3"]` |
| x[V4] ∈ Z≥0 | `LpVariable("V4", lowBound=0, cat="Integer")` | `x["V4"]` |

---

## 3.2 Amaç Fonksiyonu

### Mantık
"Toplam maliyeti minimize et" = her vardiyaya atanan kişi × o vardiya maliyeti

### Maliyet Tablosu

| Vardiya | Maliyet | Açıklama |
|---------|---------|----------|
| V1 | 100₺ | En ucuz — sabahçı |
| V2 | 120₺ | Orta — gündüz |
| V3 | 130₺ | Orta — akşam |
| V4 | 150₺ | En pahalı — gece primi |

### Formül

```
MINIMIZE Z = 100·x[V1] + 120·x[V2] + 130·x[V3] + 150·x[V4]
```

### Açılımı

```
Z = (V1 kişi sayısı × 100₺) 
  + (V2 kişi sayısı × 120₺) 
  + (V3 kişi sayısı × 130₺)
  + (V4 kişi sayısı × 150₺)
```

### Kod karşılığı (PuLP)

```python
# Tek tek yazım
model += 100*x["V1"] + 120*x["V2"] + 130*x["V3"] + 150*x["V4"], "Toplam_Maliyet"

# veya dict ile
maliyet = {"V1": 100, "V2": 120, "V3": 130, "V4": 150}
model += lpSum(maliyet[v] * x[v] for v in vardiyalar), "Toplam_Maliyet"
```

**Eşleştirme:**

| Matematik | Python |
|-----------|--------|
| min Z = Σ maliyet[v] · x[v] | `lpSum(maliyet[v] * x[v] for v in vardiyalar)` |

---

## 3.3 Kısıtlar

### K1: Slot Bazlı Minimum Personel

**Mantık:** Her slotta, o slotu kapsayan vardiyaların toplam personeli >= ihtiyaç

**Kapsama tablosunu hatırla:**

| Slot | Saat | Kapsayan Vardiyalar | Min İhtiyaç |
|------|------|---------------------|-------------|
| S1 | 06-10 | V1 | 8 |
| S2 | 10-14 | V1, V2 | 15 |
| S3 | 14-18 | V2, V3 | 20 |
| S4 | 18-22 | V3, V4 | 18 |
| S5 | 22-02 | V4 | 10 |

**Formüller:**

```
K1-S1: x[V1] >= 8                       (06-10 arası sadece V1 çalışıyor)
K1-S2: x[V1] + x[V2] >= 15              (10-14 arası V1 ve V2 çalışıyor)
K1-S3: x[V2] + x[V3] >= 20              (14-18 arası V2 ve V3 çalışıyor)
K1-S4: x[V3] + x[V4] >= 18              (18-22 arası V3 ve V4 çalışıyor)
K1-S5: x[V4] >= 10                      (22-02 arası sadece V4 çalışıyor)
```

**Kod:**

```python
# Tek tek yazım
model += x["V1"] >= 8, "Slot_S1"
model += x["V1"] + x["V2"] >= 15, "Slot_S2"
model += x["V2"] + x["V3"] >= 20, "Slot_S3"
model += x["V3"] + x["V4"] >= 18, "Slot_S4"
model += x["V4"] >= 10, "Slot_S5"
```

**Veya veri yapısı ile:**

```python
# Hangi slot hangi vardiyaları kapsıyor
kapsama = {
    "S1": ["V1"],
    "S2": ["V1", "V2"],
    "S3": ["V2", "V3"],
    "S4": ["V3", "V4"],
    "S5": ["V4"]
}

ihtiyac = {"S1": 8, "S2": 15, "S3": 20, "S4": 18, "S5": 10}

# Döngü ile kısıt ekleme
for slot in kapsama:
    model += lpSum(x[v] for v in kapsama[slot]) >= ihtiyac[slot], f"Slot_{slot}"
```

**Eşleştirme:**

| Matematik | Python |
|-----------|--------|
| x[V1] >= 8 | `model += x["V1"] >= 8` |
| x[V1] + x[V2] >= 15 | `model += x["V1"] + x["V2"] >= 15` |
| Σ x[v] >= ihtiyaç[s], ∀s | `lpSum(x[v] for v in kapsama[slot]) >= ihtiyac[slot]` |

---

### K2: Maksimum Toplam Personel (Opsiyonel - Bütçe)

**Mantık:** Toplam 60 kişiden fazla atayamayız (bütçe kısıtı).

**Formül:**

```
K2: x[V1] + x[V2] + x[V3] + x[V4] <= 60
```

**Kod:**

```python
model += lpSum(x[v] for v in vardiyalar) <= 60, "Max_Toplam"
```

---

### K3: Gece Vardiyası Üst Limit (Opsiyonel)

**Mantık:** Gece vardiyasına (V4) en fazla 15 kişi atanabilir.

**Formül:**

```
K3: x[V4] <= 15
```

**Kod:**

```python
model += x["V4"] <= 15, "Max_Gece"
```

---

## 3.4 Tam Model — Özet

```
================================================================================
                         VARDİYA PLANLAMA MODELİ
================================================================================

DEĞİŞKENLER:
    x[V1], x[V2], x[V3], x[V4] ∈ Z≥0    (tam sayı, >= 0)

AMAÇ:
    MINIMIZE Z = 100·x[V1] + 120·x[V2] + 130·x[V3] + 150·x[V4]

KISITLAR:
    K1-S1: x[V1] >= 8                       (Slot 06-10)
    K1-S2: x[V1] + x[V2] >= 15              (Slot 10-14)
    K1-S3: x[V2] + x[V3] >= 20              (Slot 14-18)
    K1-S4: x[V3] + x[V4] >= 18              (Slot 18-22)
    K1-S5: x[V4] >= 10                      (Slot 22-02)
    
    K2:    x[V1] + x[V2] + x[V3] + x[V4] <= 60   (Bütçe limiti)
    K3:    x[V4] <= 15                           (Gece max)

================================================================================
```

### Model Analizi

**Solver şunları düşünmek zorunda:**

1. **S1 kısıtı:** x[V1] >= 8 → V1'e en az 8 kişi şart
2. **S2 kısıtı:** x[V1] + x[V2] >= 15 → V1 zaten 8 ise, V2'ye en az 7 lazım
3. **S3 kısıtı:** x[V2] + x[V3] >= 20 → V2=7 ise, V3'e en az 13 lazım
4. **S4 kısıtı:** x[V3] + x[V4] >= 18 → V3=13 ise, V4'e en az 5 lazım
5. **S5 kısıtı:** x[V4] >= 10 → ama V4'e en az 10 şart!

**Çelişki:** S4'ten V4 >= 5 çıkıyor ama S5'ten V4 >= 10 çıkıyor → V4 = 10 olmalı

**Geriye doğru hesap:**
- V4 = 10 (S5 kısıtı)
- V3 + 10 >= 18 → V3 >= 8
- V2 + V3 >= 20 → V2 + 8 >= 20 → V2 >= 12
- V1 + V2 >= 15 → V1 + 12 >= 15 → V1 >= 3, ama S1'den V1 >= 8

**Minimum atama:** V1=8, V2=12, V3=8, V4=10 → Toplam 38 kişi

Ama bu optimal mi? Belki V2'ye fazla atayıp V3'ü azaltmak daha ucuz?

---

# 4. TAM KOD — PuLP

```python
from pulp import *

# ========== VERİ ==========
vardiyalar = ["V1", "V2", "V3", "V4"]

maliyet = {"V1": 100, "V2": 120, "V3": 130, "V4": 150}

kapsama = {
    "S1": ["V1"],
    "S2": ["V1", "V2"],
    "S3": ["V2", "V3"],
    "S4": ["V3", "V4"],
    "S5": ["V4"]
}

ihtiyac = {"S1": 8, "S2": 15, "S3": 20, "S4": 18, "S5": 10}

# ========== MODEL ==========
model = LpProblem("Vardiya_Planlama", LpMinimize)

# Değişkenler
x = LpVariable.dicts("x", vardiyalar, lowBound=0, cat="Integer")

# Amaç fonksiyonu
model += lpSum(maliyet[v] * x[v] for v in vardiyalar), "Toplam_Maliyet"

# Kısıtlar - Slot bazlı minimum
for slot in kapsama:
    model += lpSum(x[v] for v in kapsama[slot]) >= ihtiyac[slot], f"Min_{slot}"

# Kısıt - Bütçe limiti
model += lpSum(x[v] for v in vardiyalar) <= 60, "Max_Toplam"

# Kısıt - Gece vardiyası üst limit
model += x["V4"] <= 15, "Max_Gece"

# ========== ÇÖZÜM ==========
model.solve(PULP_CBC_CMD(msg=0))

# ========== SONUÇLAR ==========
print("=" * 50)
print(f"Durum: {LpStatus[model.status]}")
print("=" * 50)

print("\nAtamalar:")
toplam_kisi = 0
for v in vardiyalar:
    kisi = int(x[v].varValue)
    toplam_kisi += kisi
    print(f"  {v}: {kisi:2d} kişi × {maliyet[v]}₺ = {kisi * maliyet[v]:,}₺")

print(f"\nToplam: {toplam_kisi} kişi")
print(f"Toplam Maliyet: {int(value(model.objective)):,}₺")

# Kısıt kontrolü
print("\nSlot Kontrolü:")
for slot in kapsama:
    atanan = sum(x[v].varValue for v in kapsama[slot])
    durum = "✓" if atanan >= ihtiyac[slot] else "✗"
    print(f"  {slot}: {int(atanan):2d} >= {ihtiyac[slot]:2d} {durum}")
```

**Çıktı:**

```
==================================================
Durum: Optimal
==================================================

Atamalar:
  V1:  8 kişi × 100₺ = 800₺
  V2: 12 kişi × 120₺ = 1,440₺
  V3:  8 kişi × 130₺ = 1,040₺
  V4: 10 kişi × 150₺ = 1,500₺

Toplam: 38 kişi
Toplam Maliyet: 4,780₺

Slot Kontrolü:
  S1:  8 >= 8 ✓
  S2: 20 >= 15 ✓
  S3: 20 >= 20 ✓
  S4: 18 >= 18 ✓
  S5: 10 >= 10 ✓
```

**Analiz:**
- S2'de 20 kişi var ama 15 yeterliydi → 5 kişi "fazlalık" (slack)
- Bunun nedeni: V1=8 (S1 için şart) + V2=12 (S3 için şart) = 20
- Model fazladan kişi atamadı, kısıtları tam sınırda karşıladı

---

# 5. LP vs IP vs MIP

## 5.1 Fark Nedir?

| Tip | Değişken Tipi | Örnek Sonuç | Kullanım |
|-----|---------------|-------------|----------|
| **LP** | Sürekli (kesirli) | x=12.7 kişi | Üretim miktarı, karışım |
| **IP** | Tam sayı | x=13 kişi | Kişi sayısı, araç sayısı |
| **MIP** | Karışık | x=13 kişi, y=0.65 oran | Gerçek dünya problemleri |

## 5.2 Kodda Fark

```python
# LP - Sürekli (kesirli olabilir)
x = LpVariable("x", lowBound=0)  # cat default = "Continuous"

# IP - Tam sayı
x = LpVariable("x", lowBound=0, cat="Integer")

# Binary (0 veya 1) - IP'nin özel hali
y = LpVariable("y", cat="Binary")
```

## 5.3 Aynı Problemi LP vs IP Çözelim

**LP olarak:**
```python
x = LpVariable.dicts("x", vardiyalar, lowBound=0)  # Continuous
```

**Sonuç (kesirli olabilir):**
```
V1: 8.0 kişi
V2: 12.0 kişi
V3: 8.0 kişi
V4: 10.0 kişi
Maliyet: 4,780₺
```

**IP olarak:**
```python
x = LpVariable.dicts("x", vardiyalar, lowBound=0, cat="Integer")
```

**Sonuç (tam sayı):**
```
V1: 8 kişi
V2: 12 kişi
V3: 8 kişi
V4: 10 kişi
Maliyet: 4,780₺
```

Bu örnekte sonuç aynı çünkü LP zaten tam sayı verdi. Ama her zaman böyle olmaz!

## 5.4 Farkın Önemli Olduğu Durum

Eğer ihtiyaçları değiştirirsek:

```python
ihtiyac = {"S1": 8, "S2": 17, "S3": 20, "S4": 18, "S5": 10}  # S2: 15→17
```

**LP sonucu:** V2 = 9.0 (tam)
**IP sonucu:** V2 = 9 (tam)

Ama bazı problemlerde LP sonucu V2 = 9.3 çıkabilir. O zaman:
- Aşağı yuvarlama (9) → kısıt ihlali riski
- Yukarı yuvarlama (10) → suboptimal
- **Doğru yöntem:** IP olarak çözmek

---

# 6. ÖLÇEKLENDİRME — Sigma Notasyonu

Gerçek problemlerde 4 değil 40 vardiya, 5 değil 48 slot olabilir. Matematik notasyonu ve kod buna uygun olmalı.

## 6.1 Küme Tanımları

```
V = {V1, V2, V3, V4, ...}     Vardiyalar kümesi
S = {S1, S2, S3, S4, S5, ...} Slotlar kümesi

cover(s) ⊆ V                   Slot s'i kapsayan vardiyalar alt kümesi
```

## 6.2 Matematik — Sigma Notasyonu

```
DEĞİŞKENLER:
    x[v] ∈ Z≥0,  ∀v ∈ V

AMAÇ:
    MINIMIZE Z = Σ (maliyet[v] · x[v])
                v∈V

KISITLAR:
    Σ x[v] >= ihtiyac[s],  ∀s ∈ S
  v∈cover(s)
```

**Açıklama:**
- `∀v ∈ V` = "V kümesindeki her v için"
- `Σ` = toplam (sum)
- `v∈cover(s)` = "s slotunu kapsayan vardiyalar üzerinden topla"

## 6.3 Kod — Veri Yapısı ile

```python
from pulp import *

# ========== VERİ (gerçek projede Excel/DB'den gelir) ==========
vardiyalar = ["V1", "V2", "V3", "V4"]
slotlar = ["S1", "S2", "S3", "S4", "S5"]

maliyet = {"V1": 100, "V2": 120, "V3": 130, "V4": 150}

kapsama = {
    "S1": ["V1"],
    "S2": ["V1", "V2"],
    "S3": ["V2", "V3"],
    "S4": ["V3", "V4"],
    "S5": ["V4"]
}

ihtiyac = {"S1": 8, "S2": 15, "S3": 20, "S4": 18, "S5": 10}

# ========== MODEL ==========
model = LpProblem("Vardiya", LpMinimize)

# x[v] ∈ Z≥0, ∀v ∈ V
x = LpVariable.dicts("x", vardiyalar, lowBound=0, cat="Integer")

# min Σ maliyet[v] · x[v]
model += lpSum(maliyet[v] * x[v] for v in vardiyalar)

# Σ x[v] >= ihtiyac[s], ∀s ∈ S
for s in slotlar:
    model += lpSum(x[v] for v in kapsama[s]) >= ihtiyac[s], f"K1_{s}"

model.solve(PULP_CBC_CMD(msg=0))
```

## 6.4 Eşleştirme Tablosu

| Matematik | Python |
|-----------|--------|
| x[v] ∈ Z≥0, ∀v ∈ V | `x = LpVariable.dicts("x", vardiyalar, lowBound=0, cat="Integer")` |
| Σ maliyet[v] · x[v] | `lpSum(maliyet[v] * x[v] for v in vardiyalar)` |
| Σ x[v] >= ihtiyac[s], ∀s | `for s in slotlar: model += lpSum(x[v] for v in kapsama[s]) >= ihtiyac[s]` |

## 6.5 Yeni Vardiya/Slot Eklemek

**Matematik değişmez**, sadece veri değişir:

```python
# 2 yeni vardiya ekle
vardiyalar = ["V1", "V2", "V3", "V4", "V5", "V6"]
maliyet["V5"] = 110
maliyet["V6"] = 140
kapsama["S2"].append("V5")  # V5 de S2'yi kapsıyor
kapsama["S3"].append("V5")
kapsama["S4"].append("V6")

# Aynı model kodu çalışır!
```

---

# 7. DÖRT ARAÇLA ÇÖZÜM KARŞILAŞTIRMA

Aynı problemi farklı kütüphanelerle çözelim.

## 7.1 Problem (Tekrar)

```
DEĞİŞKENLER:  x[V1], x[V2], x[V3], x[V4] >= 0, integer

AMAÇ:         min 100·x[V1] + 120·x[V2] + 130·x[V3] + 150·x[V4]

KISITLAR:
    S1: x[V1] >= 8
    S2: x[V1] + x[V2] >= 15
    S3: x[V2] + x[V3] >= 20
    S4: x[V3] + x[V4] >= 18
    S5: x[V4] >= 10
```

## 7.2 SciPy (linprog) — Sadece LP

```python
from scipy.optimize import linprog

# SciPy minimize eder, matris formunda çalışır
# Integer desteklemez — sadece LP!

# Maliyet vektörü (V1, V2, V3, V4)
c = [100, 120, 130, 150]

# A_ub @ x <= b_ub formatı → >= kısıtlarını çevir
# x[V1] >= 8  →  -x[V1] <= -8
A_ub = [
    [-1,  0,  0,  0],   # -x[V1] <= -8                (S1)
    [-1, -1,  0,  0],   # -x[V1] - x[V2] <= -15       (S2)
    [ 0, -1, -1,  0],   # -x[V2] - x[V3] <= -20       (S3)
    [ 0,  0, -1, -1],   # -x[V3] - x[V4] <= -18       (S4)
    [ 0,  0,  0, -1],   # -x[V4] <= -10               (S5)
]
b_ub = [-8, -15, -20, -18, -10]

bounds = [(0, None), (0, None), (0, None), (0, None)]

result = linprog(c, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method='highs')

print(f"V1: {result.x[0]:.1f}, V2: {result.x[1]:.1f}, V3: {result.x[2]:.1f}, V4: {result.x[3]:.1f}")
print(f"Maliyet: {result.fun:.1f}₺")
```

**Çıktı:**
```
V1: 8.0, V2: 12.0, V3: 8.0, V4: 10.0
Maliyet: 4780.0₺
```

**Not:** linprog integer desteklemez. Bu örnekte şanslıyız, LP zaten tam sayı verdi.

## 7.3 PuLP

```python
from pulp import *

model = LpProblem("Vardiya", LpMinimize)

vardiyalar = ["V1", "V2", "V3", "V4"]
maliyet = {"V1": 100, "V2": 120, "V3": 130, "V4": 150}
x = LpVariable.dicts("x", vardiyalar, lowBound=0, cat="Integer")

model += lpSum(maliyet[v] * x[v] for v in vardiyalar)

model += x["V1"] >= 8
model += x["V1"] + x["V2"] >= 15
model += x["V2"] + x["V3"] >= 20
model += x["V3"] + x["V4"] >= 18
model += x["V4"] >= 10

model.solve(PULP_CBC_CMD(msg=0))

for v in vardiyalar:
    print(f"{v}: {int(x[v].varValue)}", end="  ")
print(f"\nMaliyet: {int(value(model.objective))}₺")
```

**Çıktı:**
```
V1: 8  V2: 12  V3: 8  V4: 10
Maliyet: 4780₺
```

## 7.4 OR-Tools (CP-SAT)

```python
from ortools.sat.python import cp_model

model = cp_model.CpModel()

# CP-SAT sadece integer — new_int_var kullan
x = {
    "V1": model.new_int_var(0, 100, "V1"),
    "V2": model.new_int_var(0, 100, "V2"),
    "V3": model.new_int_var(0, 100, "V3"),
    "V4": model.new_int_var(0, 100, "V4"),
}

maliyet = {"V1": 100, "V2": 120, "V3": 130, "V4": 150}

# Kısıtlar
model.add(x["V1"] >= 8)
model.add(x["V1"] + x["V2"] >= 15)
model.add(x["V2"] + x["V3"] >= 20)
model.add(x["V3"] + x["V4"] >= 18)
model.add(x["V4"] >= 10)

# Amaç
model.minimize(sum(maliyet[v] * x[v] for v in x))

solver = cp_model.CpSolver()
status = solver.solve(model)

if status == cp_model.OPTIMAL:
    for v in x:
        print(f"{v}: {solver.value(x[v])}", end="  ")
    print(f"\nMaliyet: {int(solver.objective_value)}₺")
```

**Çıktı:**
```
V1: 8  V2: 12  V3: 8  V4: 10
Maliyet: 4780₺
```

## 7.5 Pyomo

```python
import pyomo.environ as pyo

model = pyo.ConcreteModel()

# Değişkenler
model.V = pyo.Set(initialize=["V1", "V2", "V3", "V4"])
model.x = pyo.Var(model.V, within=pyo.NonNegativeIntegers)

maliyet = {"V1": 100, "V2": 120, "V3": 130, "V4": 150}

# Amaç
model.obj = pyo.Objective(
    expr=sum(maliyet[v] * model.x[v] for v in model.V),
    sense=pyo.minimize
)

# Kısıtlar
model.s1 = pyo.Constraint(expr=model.x["V1"] >= 8)
model.s2 = pyo.Constraint(expr=model.x["V1"] + model.x["V2"] >= 15)
model.s3 = pyo.Constraint(expr=model.x["V2"] + model.x["V3"] >= 20)
model.s4 = pyo.Constraint(expr=model.x["V3"] + model.x["V4"] >= 18)
model.s5 = pyo.Constraint(expr=model.x["V4"] >= 10)

# Çöz (glpk veya cbc kurulu olmalı)
solver = pyo.SolverFactory('glpk')
solver.solve(model)

for v in model.V:
    print(f"{v}: {int(pyo.value(model.x[v]))}", end="  ")
print(f"\nMaliyet: {int(pyo.value(model.obj))}₺")
```

**Çıktı:**
```
V1: 8  V2: 12  V3: 8  V4: 10
Maliyet: 4780₺
```

## 7.6 Karşılaştırma Tablosu

| Özellik | SciPy | PuLP | OR-Tools | Pyomo |
|---------|-------|------|----------|-------|
| **Kurulum** | Zaten var | `pip install pulp` | `pip install ortools` | `pip install pyomo` + solver |
| **LP** | ✅ | ✅ | ✅ | ✅ |
| **IP/MIP** | ❌ | ✅ | ✅ | ✅ |
| **Syntax** | Matris (A, b, c) | Algebraik | Algebraik | AML (Set, Param) |
| **Öğrenme** | Kolay | Kolay | Orta | Zor |
| **En iyi kullanım** | Hızlı LP denemesi | Genel LP/MIP | Scheduling, CP | Büyük parametrik model |

## 7.7 Syntax Karşılaştırması

**Aynı kısıt (S2: x[V1] + x[V2] >= 15) dört araçta:**

```python
# SciPy — matris satırı
A_ub[1] = [-1, -1, 0, 0]    # negatif çünkü <= formatı
b_ub[1] = -15

# PuLP — algebraik
model += x["V1"] + x["V2"] >= 15

# OR-Tools — algebraik
model.add(x["V1"] + x["V2"] >= 15)

# Pyomo — algebraik
model.s2 = pyo.Constraint(expr=model.x["V1"] + model.x["V2"] >= 15)
```

---

# 8. SONUÇ

## 8.1 Workshop Akışı Özeti

```
1. Problemi sözlü tanımla
   "Her slotta yeterli personel lazım, maliyeti minimize et"
        ↓
2. Veriyi tablola
   - Vardiyalar: V1, V2, V3, V4 (saat + maliyet)
   - Slotlar: S1-S5 (saat + ihtiyaç)
   - Kapsama: hangi vardiya hangi slotu kapsıyor
        ↓
3. Matematiğe çevir
   - Değişkenler: x[v] ∈ Z≥0
   - Amaç: min Σ maliyet[v] · x[v]
   - Kısıtlar: Σ x[v] >= ihtiyaç[s], ∀s
        ↓
4. Koda çevir
   - LpVariable.dicts() → değişkenler
   - lpSum() → toplam
   - model += ... → kısıt
        ↓
5. Çöz ve sonuçları oku
   - model.solve()
   - x[v].varValue
   - value(model.objective)
```

## 8.2 Matematik ↔ Kod Eşleştirme Özeti

| Matematik | Python (PuLP) |
|-----------|---------------|
| x[v] ∈ Z≥0, ∀v ∈ V | `x = LpVariable.dicts("x", V, lowBound=0, cat="Integer")` |
| y[v] ∈ {0,1} | `y = LpVariable.dicts("y", V, cat="Binary")` |
| min Σ c[v]·x[v] | `model += lpSum(c[v]*x[v] for v in V)` |
| Σ x[v] >= b | `model += lpSum(x[v] for v in subset) >= b` |
| x[v] <= M·y[v] | `model += x[v] <= M * y[v]` |

## 8.3 Ne Zaman Hangi Araç?

| Durum | Tercih | Neden |
|-------|--------|-------|
| Hızlı LP denemesi | SciPy linprog | Kurulum yok, matris gir çöz |
| Genel MIP, kolay syntax | PuLP | Öğrenmesi kolay, CBC dahil |
| Scheduling, atama | OR-Tools CP-SAT | Native kısıtlar (exactly_one, no_overlap) |
| Büyük/parametrik model | Pyomo | Set/Param yapısı, solver değiştirme |
| Ticari solver (Gurobi) | Pyomo veya direkt API | Performans kritik |

## 8.4 Kontrol Listesi

Bir optimizasyon problemi çözerken:

- [ ] Karar değişkenlerini belirle (ne hakkında karar veriyoruz?)
- [ ] Değişken tipini seç (continuous / integer / binary)
- [ ] Amaç fonksiyonunu yaz (minimize / maximize)
- [ ] Kısıtları listele (hard constraints)
- [ ] Soft constraint varsa penalty olarak amaça ekle
- [ ] Modeli kodla
- [ ] Çöz ve sonuçları doğrula (kısıtlar sağlanıyor mu?)
- [ ] Slack'leri incele (hangi kısıtlar binding?)

## 8.5 İleri Konular (Bu Workshop'ta Yok)

- **MIP Gap:** Optimal'e ne kadar yakınız? (%1 gap yeterli mi?)
- **Branch & Bound:** MIP nasıl çözülüyor?
- **Heuristic:** Exact çözüm çok yavaşsa ne yapılır?
- **Sensitivity Analysis:** Parametre değişince çözüm nasıl değişir?
- **Column Generation:** Çok büyük problemler için decomposition

---

# 9. KAYNAKLAR

**Kütüphaneler:**
- PuLP: https://coin-or.github.io/pulp/
- OR-Tools: https://developers.google.com/optimization
- Pyomo: https://www.pyomo.org/
- SciPy: https://docs.scipy.org/doc/scipy/reference/optimize.html

**Kitaplar:**
- "Model Building in Mathematical Programming" — H. Paul Williams
- "Introduction to Linear Optimization" — Bertsimas & Tsitsiklis

**Ücretsiz Solver'lar:**
- CBC (PuLP ile gelir)
- GLPK (Pyomo ile kullanılabilir)
- HiGHS (SciPy'da default)
- SCIP (akademik kullanım ücretsiz)

