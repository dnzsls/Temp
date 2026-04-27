# =============================================================================
# CONFIG V4 WEEKDAY — Cross-queue kaldırıldı
# =============================================================================
# V3 config üzerine V4 değişiklikleri:
#   - cross_queue bloğu kaldırıldı (gold/kurumsal fazlası artık kitle'den düşülmüyor)
#   - Her kuyruk kendi Erlang ihtiyacı ile bağımsız çözülüyor
# =============================================================================

CONFIG = {

    # ---- KUYRUKLAR ----
    'queues': {
        'kitle': {
            'label': 'kitle',
            'actual_name': 'kitle_cagrilar',
            'companies': ['inhouse', 'outsource'],
        },
        'kurumsal': {
            'label': 'kurumsal',
            'actual_name': 'kurumsal_cagrilar',
            'companies': ['inhouse'],
        },
        'gold': {
            'label': 'gold',
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
        'enabled': False,
        'shifts': ['09:00-13:00', '10:00-14:00', '19:00-23:00'],
        'count': {'kitle': 42, 'kurumsal': 4, 'gold': 10}
    },

    # ---- OUTSOURCE HEDEF (V4: tüm kuyruklar için kısıt pasif — balans penalty ile sağlanır) ----
    'outsource_ratio': {
        'kitle': None,
        'kurumsal': None,
        'gold': None,
    },

    # ---- SAAT BAZLI MALİYET ÇARPANLARI ----
    'time_cost_multipliers': {
        'kitle': {
            'inhouse': {'07:00': 25.0, '07:30': 10.0},
            'outsource': {'07:00': 2.0, '07:30': 2.0}
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
            'inhouse': {'07:00': 1.8, '07:30': 1.5},
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
        'calls': 'not_call'
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

    # ---- RAPOR ----
    'report': {
        'peak_threshold': 0.70,
    },

    # ---- INHOUSE-ONLY ALT KUYRUKLAR ----
    'inhouse_only_subqueues': {
        'kitle': [
            'retention_line',
            {'sub_queue': 'karttemelbankaclik', 'min_ratio': 0.20},
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
    # QUEUE CONFIGS
    # =========================================================================

    'queue_configs': {

        # ----------- KİTLE -----------
        'kitle': {
            'erlang': {
                'target_asa': 30,
                'target_seconds': 30,
                'shrinkage': {
                    0: 0.07, 1: 0.07, 2: 0.07, 3: 0.07, 4: 0.07, 5: 0.07, 6: 0.07,
                    7: 0.07, 8: 0.07, 9: 0.24, 10: 0.17, 11: 0.17, 12: 0.16,
                    13: 0.19, 14: 0.21, 15: 0.25, 16: 0.26, 17: 0.29, 18: 0.18,
                    19: 0.17, 20: 0.18, 21: 0.14, 22: 0.13, 23: 0.19,
                    'default': 0.0,
                },
                'interval_minutes': 30,
            },
            'mip': {
                'cost_inhouse': 1.0,
                'cost_outsource': 1.0,
                'min_per_shift': 5,
                # Başlangıç saati bazlı override — listelenmeyen saatler default'u kullanır.
                # Örn. {'00:00': 1, '01:00': 1} → gece 00:00/01:00 vardiyalarında min 1.
                'min_per_shift_overrides': {},
                # Infeasible durumda default min'i kademeli düşürerek yeniden dener.
                # Overrides'a dokunmaz, sadece default ezilir.
                'min_per_shift_fallback': {
                    'enabled': True,
                    'floor': 1,
                    'step': 1,
                },
                # Son kademe: min fallback de başaramazsa, shrinkage parametresini
                # hourly_report.kapasite_kaybi değerleriyle değiştirip Erlang'ı
                # yeniden hesapla ve default min ile dene.
                'capacity_loss_fallback': {
                    'enabled': True,
                },
            },
            'rr_penalty': {
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
            },
            'small_shift_penalty': {
                'enabled': True,
                'penalty': 10,
            },
            'slot_cap': {
                'enabled': True,
                'bands': [
                    {'start': '07:00', 'end': '08:00', 'max_ratio': 1.10, 'penalty': 50.0},
                    {'start': '08:00', 'end': '09:00', 'max_ratio': 1.30, 'penalty': 50.0},
                    {'start': '09:00', 'end': '10:30', 'max_ratio': 1.20, 'penalty': 50.0},
                    {'start': '15:00', 'end': '17:00', 'max_ratio': 1.20, 'penalty': 50.0},
                    {'start': '18:30', 'end': '22:00', 'max_ratio': 1.25, 'penalty': 50.0},
                    {'start': '22:00', 'end': '05:00', 'max_ratio': 1.30, 'penalty': 80.0},
                ],
            },
            # V3: Pencere bazlı balans penalty
            'balance_penalty': {
                'enabled': True,
                'penalty_per_diff': 2.0,
                'windows': [
                    {'name': 'sabah', 'start': '07:00', 'end': '11:59', 'penalty': 2.0},
                    {'name': 'aksam', 'start': '12:00', 'end': '23:30', 'penalty': 2.0},
                ],
            },
            # Sabah shift başlangıç dağılımını düzgünleştir
            'start_smoothing': {
                'enabled': True,
                'hours': {'start': '07:00', 'end': '12:00'},
                'companies': ['inhouse', 'outsource'],
                'penalty_per_diff': 5.0,
            },
            'hourly_report': {
                'rapor_etkisi': {
                    'default': 0.00,
                },
                'kapasite_kaybi': {
                    0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0, 6: 0.0,
                    7: 0.0, 8: 0.0, 9: 0.17, 10: 0.10, 11: 0.10, 12: 0.09,
                    13: 0.12, 14: 0.14, 15: 0.18, 16: 0.19, 17: 0.22, 18: 0.11,
                    19: 0.10, 20: 0.11, 21: 0.08, 22: 0.07, 23: 0.12,
                    'default': 0.08,
                },
                'cagri_adedi': {
                    'default': 15,
                },
            },
        },

        # ----------- KURUMSAL -----------
        'kurumsal': {
            'erlang': {
                'target_asa': 30,
                'target_seconds': 30,
                'shrinkage': {
                    0: 0.07, 1: 0.07, 2: 0.07, 3: 0.07, 4: 0.07, 5: 0.07, 6: 0.07,
                    7: 0.07, 8: 0.07, 9: 0.24, 10: 0.17, 11: 0.17, 12: 0.16,
                    13: 0.19, 14: 0.21, 15: 0.25, 16: 0.26, 17: 0.29, 18: 0.18,
                    19: 0.17, 20: 0.18, 21: 0.14, 22: 0.13, 23: 0.19,
                    'default': 0.0,
                },
                'interval_minutes': 30,
            },
            'mip': {
                'cost_inhouse': 1.0,
                'cost_outsource': 1.0,
                'min_per_shift': 0,
                'min_per_shift_overrides': {},
                'min_per_shift_fallback': {
                    'enabled': True,
                    'floor': 1,
                    'step': 1,
                },
                # Son kademe: min fallback de başaramazsa, shrinkage parametresini
                # hourly_report.kapasite_kaybi değerleriyle değiştirip Erlang'ı
                # yeniden hesapla ve default min ile dene.
                'capacity_loss_fallback': {
                    'enabled': True,
                },
            },
            'rr_penalty': {
                'enabled': True,
                'peak_exempt': True,
                'penalty_per_person': 4.0,
                'peak_penalty': 2.0,
                'peak_threshold': 0.70,
                'night_multiplier': {
                    'enabled': True,
                    'hours': {'start': '00:00', 'end': '07:00'},
                    'multiplier': 100.0,
                },
            },
            'small_shift_penalty': {
                'enabled': True,
                'penalty': 10,
            },
            'slot_cap': {
                'enabled': False,
                'bands': [],
            },
            'hourly_report': {
                'rapor_etkisi': {
                    'default': 0.0,
                },
                'kapasite_kaybi': {
                    0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0, 6: 0.0,
                    7: 0.0, 8: 0.0, 9: 0.17, 10: 0.10, 11: 0.10, 12: 0.09,
                    13: 0.12, 14: 0.14, 15: 0.18, 16: 0.19, 17: 0.22, 18: 0.11,
                    19: 0.10, 20: 0.11, 21: 0.08, 22: 0.07, 23: 0.12,
                    'default': 0.08,
                },
                'cagri_adedi': {
                    'default': 15,
                },
            },
        },

        # ----------- GOLD -----------
        'gold': {
            'erlang': {
                'target_asa': 30,
                'target_seconds': 30,
                'shrinkage': {
                    0: 0.07, 1: 0.07, 2: 0.07, 3: 0.07, 4: 0.07, 5: 0.07, 6: 0.07,
                    7: 0.07, 8: 0.07, 9: 0.24, 10: 0.17, 11: 0.17, 12: 0.16,
                    13: 0.19, 14: 0.21, 15: 0.25, 16: 0.26, 17: 0.29, 18: 0.18,
                    19: 0.17, 20: 0.18, 21: 0.14, 22: 0.13, 23: 0.19,
                    'default': 0.0,
                },
                'interval_minutes': 30,
            },
            'mip': {
                'cost_inhouse': 1.0,
                'cost_outsource': 1.0,
                'min_per_shift': 0,
                'min_per_shift_overrides': {},
                'min_per_shift_fallback': {
                    'enabled': True,
                    'floor': 1,
                    'step': 1,
                },
                # Son kademe: min fallback de başaramazsa, shrinkage parametresini
                # hourly_report.kapasite_kaybi değerleriyle değiştirip Erlang'ı
                # yeniden hesapla ve default min ile dene.
                'capacity_loss_fallback': {
                    'enabled': True,
                },
            },
            'rr_penalty': {
                'enabled': True,
                'peak_exempt': True,
                'penalty_per_person': 2.0,
                'peak_penalty': 4.0,
                'peak_threshold': 0.70,
                'night_multiplier': {
                    'enabled': True,
                    'hours': {'start': '00:00', 'end': '07:00'},
                    'multiplier': 100.0,
                },
            },
            'small_shift_penalty': {
                'enabled': True,
                'penalty': 10,
            },
            'slot_cap': {
                'enabled': False,
                'bands': [],
            },
            'hourly_report': {
                'rapor_etkisi': {
                    'default': 0.0,
                },
                'kapasite_kaybi': {
                    0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0, 6: 0.0,
                    7: 0.0, 8: 0.0, 9: 0.17, 10: 0.10, 11: 0.10, 12: 0.09,
                    13: 0.12, 14: 0.14, 15: 0.18, 16: 0.19, 17: 0.22, 18: 0.11,
                    19: 0.10, 20: 0.11, 21: 0.08, 22: 0.07, 23: 0.12,
                    'default': 0.08,
                },
                'cagri_adedi': {
                    'default': 15,
                },
            },
        },

    },

    # ---- SURPLUS DAĞITIM (Aşama 2) ----
    'surplus_distribution': {
        'enabled': True,
        'outsource_enabled': True,

        'total_kadro': {
            'kitle':    {'inhouse': 380, 'outsource': 450},
            'kurumsal': {'inhouse': 47},
            'gold':     {'inhouse': 130},
        },

        'windows': [
            {'name': 'sabah', 'start': '09:00', 'end': '11:00', 'ratio': 2/3},
            {'name': 'aksam', 'start': '11:00', 'end': '20:00', 'ratio': 1/3},
        ],

        'only_assigned_shifts': True,
        'fallback_all_inhouse': True,
        'method': 'rr_first',
    },
}
