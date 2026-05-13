# =============================================================================
# KİTLE — gerçek (iş birimi) dağılımına yakın çıktı için config override önerisi
# =============================================================================
# Kullanım (notebook hücresinde):
#
#     from config_v6_weekday import CONFIG as CONFIG_WEEKDAY
#     from kitle_config_overrides import apply_kitle_overrides
#     apply_kitle_overrides(CONFIG_WEEKDAY)
#
# Sonra normal aylık akışına devam et.
#
# Dayanak (Şubat 9-13 gerçek kitle dağılımı):
#   - 460 inhouse + 450 outsource = 910 kişi, ~16 farklı vardiya saati aktif
#   - İki büyük inhouse bloğu: 09:00 (97 in) ve 15:00 (128 in) — sabah + ikindi
#   - Outsource gün boyu yayılı (07:00, 09:00, 10-13, 17-18, gece)
#   - Bitişik saatler arası BÜYÜK sıçramalar var (örn. 09:00=187 ↔ 09:30=33)
#   → Smoothing baskısı agresif olamaz, yoksa real-life sıçramaları siler
#   → slot_cap geniş tutulmalı, gerçekte erlang'in %50 üstüne çıkılıyor
#   → time_cost_multipliers ile 09:00 ve 15:00 saatlerini hafifçe TEŞVİK et
#     ki MIP doğal olarak buralara yığsın
# =============================================================================


def apply_kitle_overrides(config):
    """config_v6_weekday içindeki 'kitle' queue'sunu gerçek-dağılıma yakın
    parametrelerle ezer. Diğer kuyruklara dokunmaz."""

    qc = config['queue_configs']['kitle']

    # --- min_per_shift = 13 (kullanıcı zorunluluğu) ----------------------------
    qc['mip']['min_per_shift'] = 13
    qc['mip']['min_per_shift_fallback'] = {
        'enabled': True, 'floor': 5, 'step': 2,
    }

    # --- RR penalty: ılımlı, RR ~110% hedef ------------------------------------
    # penalty_per_person=4 → her ekstra ajan 4 birim ceza
    # peak_penalty=2 → peak slotlarda daha gevşek (over-coverage'a izin)
    qc['rr_penalty'] = {
        'enabled': True,
        'peak_exempt': False,
        'penalty_per_person': 4.0,
        'peak_penalty': 2.0,
        'peak_threshold': 0.70,
        'night_multiplier': {
            'enabled': True,
            'hours': {'start': '00:00', 'end': '07:00'},
            'multiplier': 100.0,
        },
    }

    # --- slot_cap: gerçeğin gözlemlenen oranlarına göre genişletildi ----------
    # Gerçek: slot 09:00 erlang ~200, toplam coverage ~305 → ratio 1.5
    # Bu yüzden 09-11 bantı 1.55, 15-18 bantı 1.50 kullanıyoruz.
    # Gece sıkı (yığılma istenmez), öğle peak orta sıkı.
    qc['slot_cap'] = {
        'enabled': True,
        'bands': [
            {'start': '05:00', 'end': '07:00', 'max_ratio': 1.30, 'penalty': 80.0},
            {'start': '07:00', 'end': '09:00', 'max_ratio': 1.30, 'penalty': 50.0},
            {'start': '09:00', 'end': '11:00', 'max_ratio': 1.55, 'penalty': 50.0},
            {'start': '11:00', 'end': '15:00', 'max_ratio': 1.25, 'penalty': 80.0},
            {'start': '15:00', 'end': '18:00', 'max_ratio': 1.50, 'penalty': 50.0},
            {'start': '18:00', 'end': '22:00', 'max_ratio': 1.30, 'penalty': 80.0},
            {'start': '22:00', 'end': '05:00', 'max_ratio': 1.20, 'penalty': 120.0},
        ],
    }

    # --- start_smoothing: pencere bazlı, GERÇEKTEKİ sıçramalara izin verir ----
    # sabah (07-10): gerçekte 30/58/30/187/33 — büyük varyans → düşük penalty
    # ogle  (10-15): gerçekte 73/87/32/60/60/30 — daha düz → orta penalty
    # aksam (15-20): gerçekte 128/0/50/40 — varyans → düşük penalty
    qc['start_smoothing'] = {
        'enabled': True,
        'companies': ['inhouse', 'outsource'],
        'windows': [
            {'name': 'sabah', 'start': '07:00', 'end': '10:00', 'penalty': 2.0},
            {'name': 'ogle',  'start': '10:00', 'end': '15:00', 'penalty': 8.0},
            {'name': 'aksam', 'start': '15:00', 'end': '20:00', 'penalty': 3.0},
        ],
    }

    # --- balance_penalty: düşük tut (gerçekte outsource > inhouse var) --------
    qc['balance_penalty'] = {
        'enabled': True,
        'penalty_per_diff': 1.0,
        'windows': [
            {'name': 'sabah', 'start': '07:00', 'end': '11:59', 'penalty': 1.0},
            {'name': 'aksam', 'start': '12:00', 'end': '23:30', 'penalty': 1.0},
        ],
    }

    # --- time_cost_multipliers: iki ana inhouse bloğunu TEŞVİK et -------------
    # Gerçekte 09:00 ve 15:00 ana yığılma noktaları. Diğer saatleri hafifçe
    # pahalı tutarak MIP'in oraya tercih etmesini sağlarız.
    # 1.00 = teşvikli (en ucuz), 1.05 = nötr+, 1.10 = hafif caydırıcı
    config['time_cost_multipliers']['kitle'] = {
        'inhouse': {
            # Çok erken: caydırıcı (mevcut)
            '07:00': 25.0, '07:30': 10.0,
            # Sabah ana blok başlangıçları — 09:00 EN UCUZ
            '08:00': 1.05, '08:30': 1.05, '09:00': 1.00, '09:30': 1.05,
            '10:00': 1.05, '10:30': 1.05,
            # Öğle — caydırıcı (inhouse genelde 09:00'da girer)
            '11:00': 1.10, '11:30': 1.10, '12:00': 1.10, '13:00': 1.10,
            '14:00': 1.10,
            # İkindi-akşam ana blok — 15:00 EN UCUZ
            '15:00': 1.00,
            # Akşam-gece: gerçekte çok az inhouse var, caydırıcı
            '17:00': 1.15, '18:00': 1.15, '19:00': 1.20, '22:00': 1.30,
        },
        'outsource': {
            # Outsource'da multiplier yok (default 1.0) — outsource gün boyu yayılı
            '07:00': 2.0, '07:30': 2.0,
        },
    }


# Hızlı doğrulama: parametreyi gerçek değerlerle karşılaştır
def print_overrides_summary(config):
    qc = config['queue_configs']['kitle']
    print("KİTLE override özet:")
    print(f"  min_per_shift: {qc['mip']['min_per_shift']}")
    print(f"  rr_penalty (normal/peak): "
          f"{qc['rr_penalty']['penalty_per_person']}/{qc['rr_penalty']['peak_penalty']}")
    print(f"  slot_cap bantları: {len(qc['slot_cap']['bands'])}")
    for b in qc['slot_cap']['bands']:
        print(f"    {b['start']}-{b['end']}: max_ratio={b['max_ratio']}, "
              f"penalty={b['penalty']}")
    print(f"  start_smoothing pencereleri:")
    for w in qc['start_smoothing']['windows']:
        print(f"    {w['name']} {w['start']}-{w['end']}: penalty={w['penalty']}")
    print(f"  time_cost_multipliers (inhouse): "
          f"{len(config['time_cost_multipliers']['kitle']['inhouse'])} saat tanımlı")


if __name__ == '__main__':
    from config_v6_weekday import CONFIG
    apply_kitle_overrides(CONFIG)
    print_overrides_summary(CONFIG)
