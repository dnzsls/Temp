# =============================================================================
# CONFIG V2 — WEEKDAY
# =============================================================================
# V2 (sadece haftaiçi) için config.
#
# Yapı değişiklikleri (v10.9 → v2):
#   - Kuyruk bazlı olmasını istediğimiz bloklar 'queue_overrides' altına taşındı:
#       erlang, mip, rr_penalty, small_shift_penalty, hourly_report
#   - Bu blokların GLOBAL versiyonları silindi.
#   - queue_overrides yapısı 2-seviyeli oldu: queue > section
#     (eski 3-seviyeli queue > gün_tipi > section kaldırıldı,
#      cumartesi/pazar blokları silindi).
#   - V2 default'ları:
#       * outsource_ratio hepsi None (kısıt pasif)
#       * mip.cost_outsource = 10.0 (inhouse öncelikli)
#
# NOT: Kurumsal ve gold şu an kitle ile aynı değerlerle başlıyor. Her kuyruğu
#      bağımsız olarak değiştirebilirsin — biri diğerini etkilemez.
# =============================================================================

CONFIG = {

    # ---- KUYRUKLAR ----
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

    # ---- AHT ----
    # load_aht_from_df() ile doldurulur
    'sub_queues': {},

    # Manuel saat bazlı AHT override (varsa weighted AHT yerine kullanılır)
    'aht_overrides': {
        'kitle': {},
        'kurumsal': {},
        'gold': {},
    },

    # Sub-queue ve override yoksa fallback
    'default_aht': 150,

    # ---- PART-TIME ----
    'part_time': {
        'enabled': True,
        'shifts': ['09:00-13:00', '10:00-14:00', '19:00-23:00'],
        'count': {'kitle': 32, 'kurumsal': 0, 'gold': 0}
    },

    # ---- OUTSOURCE HEDEF (V2: tüm kuyruklar için kısıt pasif) ----
    'outsource_ratio': {
        'kitle': None,
        'kurumsal': None,
        'gold': None,
    },

    # ---- SLOT CAP (zaten 'queues' flag'i ile filtreli, queue-aware) ----
    'slot_cap': {
        'enabled': True,
        'queues': ['kitle'],
        'bands': [
            {'start': '07:00', 'end': '09:00', 'max_ratio': 1.05, 'penalty': 50.0},
            {'start': '09:00', 'end': '10:00', 'max_ratio': 1.25, 'penalty': 50.0},
            {'start': '10:00', 'end': '11:00', 'max_ratio': 1.30, 'penalty': 50.0},
            #{'start': '18:00', 'end': '19:00', 'max_ratio': 1.20, 'penalty': 50.0},
        ],
    },

    # ---- SAAT BAZLI MALİYET ÇARPANLARI (zaten queue-aware) ----
    'time_cost_multipliers': {
        'kitle': {
            'inhouse': {'07:00': 1.5, '07:30': 1.3},
            'outsource': {}
        },
        'kurumsal': {
            'inhouse': {'07:00': 1.8, '07:30': 1.5},
            'outsource': {}
        },
        'gold': {
            'inhouse': {'07:00': 2.0, '07:30': 1.7},
            'outsource': {}
        },
        'default': {
            'inhouse': {'07:00': 1.5, '07:30': 1.3},
            'outsource': {}
        }
    },

    # ---- COMPANY ----
    'company': {
        'inhouse': {'shift_value': 'inhouse', 'outsource_flg': 0},
        'outsource': {'shift_value': 'outsource', 'outsource_flg': 1}
    },

    # ---- KOLON İSİMLERİ ----
    'shift_columns': {
        'shift': 'shift',
        'start': 'start',
        'end': 'end',
        'company': 'company'
    },

    'calls_columns': {
        'date': 'data_date',
        'time': 'min_time_period_value',
        'sub_queue': 'resource_group_key',
        'main_queue': 'line_based_main_group',
        'calls': 'nof_call'
    },

    'actual_columns': {
        'date': 'working_date',
        'queue': 'line_based_main_group',
        'location': 'working_main_group',
        'shift_start': 'shifts_start_hour',
        'shift_end': 'shifts_end_hour',
        'outsource': 'outsource_flg',
        'weekend': 'weekend_flg',
        'count': 'calisan_kisi_sayisi'
    },

    # ---- FORECAST KOLON İSİMLERİ ----
    'forecast_cols': {
        'datetime': 'model_data_date',
        'date': 'truncddate',
        'kitle_total': 'KITLE_NOF_CALL',
        'kurumsal_total': 'KURUMSAL_NOF_CALL',
        'gold_total': 'GOLD_NOF_CALL',
    },

    # ---- RAPOR ----
    'report': {
        'peak_threshold': 0.70
    },

    # ---- INHOUSE-ONLY ALT KUYRUKLAR ----
    'inhouse_only_subqueues': {
        'kitle': [
            #'retention_line',
            #{'sub_queue': 'kart_temel', 'min_ratio': 0.30},
        ],
        'kurumsal': [],
        'gold': []
    },

    # ---- OUTSOURCE-ONLY ALT KUYRUKLAR ----
    'outsource_only_subqueues': {
        'kitle': [
            {'sub_queue': 'kayipcalintisupheli', 'min_ratio': 1.0,
             'hours': {'start': '08:00', 'end': '00:00'}},
        ],
        'kurumsal': [],
        'gold': []
    },

    # =========================================================================
    # ---- QUEUE OVERRIDES (KUYRUK BAZLI AYARLAR) ----
    # =========================================================================
    # Yapı 2-seviyeli: queue_overrides[<queue>][<section>]
    # Pipeline bu değerleri CONFIG'in üstüne deep-merge ile yazar.
    # Bu bloklar (erlang, mip, rr_penalty, small_shift_penalty, hourly_report)
    # GLOBAL'de YOK — her kuyruk için tanımlı olmalı.
    # =========================================================================
    'queue_overrides': {

        # -----------------------------------------------------------------
        'kitle': {
            'erlang': {
                'target_asa': 30,
                'target_seconds': 30,
                'shrinkage': {
                    0: 0.03, 1: 0.03, 2: 0.03, 3: 0.03, 4: 0.03, 5: 0.03, 6: 0.03,
                    7: 0.03, 8: 0.03, 9: 0.20, 10: 0.12, 11: 0.11, 12: 0.13,
                    13: 0.20, 14: 0.17, 15: 0.23, 16: 0.25, 17: 0.22, 18: 0.16,
                    19: 0.13, 20: 0.16, 21: 0.11, 22: 0.14, 23: 0.12,
                    'default': 0.0,
                },
                'interval_minutes': 30,
            },
            'mip': {
                'cost_inhouse': 1.0,
                'cost_outsource': 10.0,
                'min_per_shift': 5,
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
                    'multiplier': 100.0,
                },
            },
            'small_shift_penalty': {
                'enabled': True,
                'penalty': 10,
            },
            'hourly_report': {
                'rapor_etkisi': {
                    0: 0.03, 1: 0.03, 2: 0.03, 3: 0.03, 4: 0.03, 5: 0.03, 6: 0.03,
                    7: 0.03, 8: 0.03, 9: 0.04, 10: 0.04, 11: 0.04, 12: 0.04,
                    13: 0.04, 14: 0.04, 15: 0.04, 16: 0.04, 17: 0.04, 18: 0.04,
                    19: 0.04, 20: 0.04, 21: 0.04, 22: 0.04, 23: 0.04,
                    'default': 0.04,
                },
                'kapasite_kaybi': {
                    0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0, 6: 0.0,
                    7: 0.0, 8: 0.0, 9: 0.16, 10: 0.08, 11: 0.07, 12: 0.09,
                    13: 0.16, 14: 0.13, 15: 0.19, 16: 0.21, 17: 0.18, 18: 0.12,
                    19: 0.09, 20: 0.12, 21: 0.07, 22: 0.10, 23: 0.08,
                    'default': 0.08,
                },
                'cagri_adedi': {
                    'default': 15,
                },
            },
        },

        # -----------------------------------------------------------------
        'kurumsal': {
            'erlang': {
                'target_asa': 30,
                'target_seconds': 30,
                'shrinkage': {
                    0: 0.03, 1: 0.03, 2: 0.03, 3: 0.03, 4: 0.03, 5: 0.03, 6: 0.03,
                    7: 0.03, 8: 0.03, 9: 0.20, 10: 0.12, 11: 0.11, 12: 0.13,
                    13: 0.20, 14: 0.17, 15: 0.23, 16: 0.25, 17: 0.22, 18: 0.16,
                    19: 0.13, 20: 0.16, 21: 0.11, 22: 0.14, 23: 0.12,
                    'default': 0.0,
                },
                'interval_minutes': 30,
            },
            'mip': {
                'cost_inhouse': 1.0,
                'cost_outsource': 10.0,
                'min_per_shift': 5,
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
                    'multiplier': 100.0,
                },
            },
            'small_shift_penalty': {
                'enabled': True,
                'penalty': 10,
            },
            'hourly_report': {
                'rapor_etkisi': {
                    0: 0.03, 1: 0.03, 2: 0.03, 3: 0.03, 4: 0.03, 5: 0.03, 6: 0.03,
                    7: 0.03, 8: 0.03, 9: 0.04, 10: 0.04, 11: 0.04, 12: 0.04,
                    13: 0.04, 14: 0.04, 15: 0.04, 16: 0.04, 17: 0.04, 18: 0.04,
                    19: 0.04, 20: 0.04, 21: 0.04, 22: 0.04, 23: 0.04,
                    'default': 0.04,
                },
                'kapasite_kaybi': {
                    0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0, 6: 0.0,
                    7: 0.0, 8: 0.0, 9: 0.16, 10: 0.08, 11: 0.07, 12: 0.09,
                    13: 0.16, 14: 0.13, 15: 0.19, 16: 0.21, 17: 0.18, 18: 0.12,
                    19: 0.09, 20: 0.12, 21: 0.07, 22: 0.10, 23: 0.08,
                    'default': 0.08,
                },
                'cagri_adedi': {
                    'default': 15,
                },
            },
        },

        # -----------------------------------------------------------------
        'gold': {
            'erlang': {
                'target_asa': 30,
                'target_seconds': 30,
                'shrinkage': {
                    0: 0.03, 1: 0.03, 2: 0.03, 3: 0.03, 4: 0.03, 5: 0.03, 6: 0.03,
                    7: 0.03, 8: 0.03, 9: 0.20, 10: 0.12, 11: 0.11, 12: 0.13,
                    13: 0.20, 14: 0.17, 15: 0.23, 16: 0.25, 17: 0.22, 18: 0.16,
                    19: 0.13, 20: 0.16, 21: 0.11, 22: 0.14, 23: 0.12,
                    'default': 0.0,
                },
                'interval_minutes': 30,
            },
            'mip': {
                'cost_inhouse': 1.0,
                'cost_outsource': 10.0,
                'min_per_shift': 5,
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
                    'multiplier': 100.0,
                },
            },
            'small_shift_penalty': {
                'enabled': True,
                'penalty': 10,
            },
            'hourly_report': {
                'rapor_etkisi': {
                    0: 0.03, 1: 0.03, 2: 0.03, 3: 0.03, 4: 0.03, 5: 0.03, 6: 0.03,
                    7: 0.03, 8: 0.03, 9: 0.04, 10: 0.04, 11: 0.04, 12: 0.04,
                    13: 0.04, 14: 0.04, 15: 0.04, 16: 0.04, 17: 0.04, 18: 0.04,
                    19: 0.04, 20: 0.04, 21: 0.04, 22: 0.04, 23: 0.04,
                    'default': 0.04,
                },
                'kapasite_kaybi': {
                    0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0, 6: 0.0,
                    7: 0.0, 8: 0.0, 9: 0.16, 10: 0.08, 11: 0.07, 12: 0.09,
                    13: 0.16, 14: 0.13, 15: 0.19, 16: 0.21, 17: 0.18, 18: 0.12,
                    19: 0.09, 20: 0.12, 21: 0.07, 22: 0.10, 23: 0.08,
                    'default': 0.08,
                },
                'cagri_adedi': {
                    'default': 15,
                },
            },
        },
    },

    # ---- SURPLUS DAĞITIM (Aşama 2) ----
    # MIP min ihtiyacı çıkardıktan sonra, configdeki kadro ile MIP atamasının
    # farkı kadar fazla kişiyi (sadece inhouse) uygun shift'lere yayar.
    'surplus_distribution': {
        'enabled': True,
        # PT hariç inhouse kadro
        'total_kadro': {
            'kitle':    {'inhouse': 400},
            'kurumsal': {'inhouse': 80},
            'gold':     {'inhouse': 50},
        },
        # Surplus dağıtım pencereleri. Her pencerenin kendi pay oranı var.
        # Oranlar toplamı 1.0 olmalı. Saatler dahil-dahil.
        'windows': [
            {'name': 'sabah', 'start': '09:00', 'end': '13:00', 'ratio': 2/3},
            {'name': 'aksam', 'start': '13:00', 'end': '20:00', 'ratio': 1/3},
        ],
        # Aday seçimi: True ise sadece MIP'in atadığı (>0) shift'ler aday
        'only_assigned_shifts': True,
        # Tüm pencerelerde aday yoksa: True → tüm atanmış inhouse shift'lere yay
        'fallback_all_inhouse': True,
        # Dağıtım yöntemi (her pencere içinde):
        #   'rr_first'  → önce RR<%100 olan slotları kapatan shift'lere greedy,
        #                 kalanı eşit dağıtılır (bölünemeyen kalan küçük shift'lere öncelik)
        #   'equal'     → direkt eşit dağıtım (RR-fix yok)
        'method': 'rr_first',
    },
}
