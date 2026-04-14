# =============================================================================
# CONFIG V3 WEEKDAY
# =============================================================================
# V2 config üzerine V3 değişiklikleri:
#   - balance_penalty: pencere bazlı inhouse/outsource denge penalty
#   - cross_queue: gold/kurumsal fazlası → kitle Erlang düşürme
#   - surplus_distribution: outsource kadro + outsource_enabled eklendi
#   - kitle mip cost_outsource: 2.0 → 1.0 (eşit maliyet, balans penalty ile denge)
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

    # ---- OUTSOURCE HEDEF (V3: tüm kuyruklar için kısıt pasif — balans penalty ile sağlanır) ----
    'outsource_ratio': {
        'kitle': None,
        'kurumsal': None,
        'gold': None,
    },

    # ---- SAAT BAZLI MALİYET ÇARPANLARI (zaten queue-aware, kuyruk key'li) ----
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
    # Pipeline bu değerleri doğrudan config['queue_configs'][queue][...] olarak
    # okur. Her kuyruk bağımsızdır, şablon yoktur — ilgili kuyruğun bloğunda
    # değişiklik yaparsan diğer kuyrukları etkilemez.
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
                'cost_outsource': 1.0,      # V3: eşit maliyet (V2'de 2.0 idi)
                'min_per_shift': 5,
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
                'enabled': False,
                'penalty': 10,
            },
            'slot_cap': {
                'enabled': True,
                'bands': [
                    #{'start': '07:00', 'end': '10:00', 'max_ratio': 1.15, 'penalty': 50.0},
                    #{'start': '08:00', 'end': '09:00', 'max_ratio': 1.15, 'penalty': 50.0},
                    #{'start': '09:00', 'end': '10:00', 'max_ratio': 1.15, 'penalty': 50.0},
                    #{'start': '10:00', 'end': '11:00', 'max_ratio': 1.15, 'penalty': 50.0},
                    {'start': '16:00', 'end': '18:30', 'max_ratio': 1.20, 'penalty': 50.0},
                    #{'start': '17:30', 'end': '18:00', 'max_ratio': 1.20, 'penalty': 50.0},
                    {'start': '18:30', 'end': '22:00', 'max_ratio': 1.25, 'penalty': 50.0},
                    {'start': '22:00', 'end': '00:00', 'max_ratio': 1.10, 'penalty': 50.0},
                ],
            },
            # V3: Pencere bazlı balans penalty (sadece kitle'de inhouse+outsource var)
            'balance_penalty': {
                'enabled': True,
                'penalty_per_diff': 2.0,
                'windows': [
                    {'name': 'sabah', 'start': '07:00', 'end': '11:30', 'penalty': 2.0},
                    {'name': 'aksam', 'start': '12:00', 'end': '23:30', 'penalty': 2.0},
                ],
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
                'enabled': False,       # kurumsal/gold'da varsayılan pasif
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

    # ---- CROSS-QUEUE KAPASİTE AKTARIMI (V3'e özel) ----
    # Gold/kurumsal'ın MIP(1) fazlası kitle'nin Erlang ihtiyacından düşülür
    'cross_queue': {
        'enabled': True,
        'donors': ['gold', 'kurumsal'],
        'receiver': 'kitle',
        'transfer_ratio': 1.0,       # fazlanın tamamı aktarılır (0.0-1.0)
    },

    # ---- SURPLUS DAĞITIM (Aşama 2) ----
    # MIP min ihtiyacı çıkardıktan sonra, configdeki kadro ile MIP atamasının
    # farkı kadar fazla kişiyi uygun shift'lere yayar.
    # V3: hem inhouse hem outsource surplus dağıtılır.
    'surplus_distribution': {
        'enabled': True,
        'outsource_enabled': True,     # V3: outsource surplus de dağıtılsın

        # PT hariç kadro
        'total_kadro': {
            'kitle':    {'inhouse': 380, 'outsource': 450},   # V3: outsource eklendi
            'kurumsal': {'inhouse': 47},
            'gold':     {'inhouse': 130},
        },

        # Surplus dağıtım pencereleri. Her pencerenin kendi pay oranı var.
        # Oranlar toplamı 1.0 olmalı. Saatler dahil-dahil (start <= shift_start <= end).
        'windows': [
            {'name': 'sabah', 'start': '09:00', 'end': '11:00', 'ratio': 2/3},
            {'name': 'aksam', 'start': '11:00', 'end': '20:00', 'ratio': 1/3},
        ],

        # Aday seçimi: True ise sadece MIP'in atadığı (>0) shift'ler aday
        'only_assigned_shifts': True,

        # Tüm pencerelerde aday yoksa: True → tüm atanmış inhouse shift'lere yay
        'fallback_all_inhouse': True,

        # Dağıtım yöntemi (her pencere içinde):
        #   'rr_first' → önce RR<%100 olan slotları kapatan shift'lere greedy,
        #                 kalanı eşit dağıtılır (bölünsmeyen kalan küçük shift'lere öncelik)
        #   'equal'    → direkt eşit dağıtım (RR-fix yok)
        'method': 'rr_first',
    },
}
