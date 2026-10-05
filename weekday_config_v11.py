# -*- coding: utf-8 -*-
"""
WEEKDAY CONFIG — FORECAST  (haftaiçi weekly_weekday_pipeline için)
==================================================================
forecast_monthly_run_v9_final.py HÜCRE 3'ten AYNEN çıkarıldı — davranış
değişmedi, sadece config koddan ayrıldı (canlıda operasyon buradan düzenler).

KULLANIM (monthly run'da HÜCRE 3 yerine):
    from weekday_config_v11 import CONFIG_WEEKDAY

DEĞİŞTİRİLEBİLİR ANA PARAMETRELER (per-queue: kitle / kurumsal / gold):
  queue_configs[queue]['mip']['min_per_shift']              → 13 (V9 sert kısıt)
  queue_configs[queue]['mip']['weekly_shrinkage_fallback']  → Stage 2 (shrinkage)
  queue_configs[queue]['mip']['coverage_shortfall']         → Stage 3 (eksiğe izin)
  queue_configs[queue]['erlang']['shrinkage']               → saatlik shrinkage
  queue_configs[queue]['rr_penalty']                        → RR ceza ayarları
  surplus_distribution['total_kadro']                       → kuyruk kadro tavanı
  forecast_cols                                             → df_forecast kolon adları
"""

CONFIG_WEEKDAY = {

    # ---- KUYRUKLAR ----
    'queues': {
        'kitle':    {'label': 'kitle',    'actual_name': 'kitle_cagrilar',
                     'companies': ['inhouse', 'outsource']},
        'kurumsal': {'label': 'kurumsal', 'actual_name': 'kurumsal_cagrilar',
                     'companies': ['inhouse']},
        'gold':     {'label': 'gold',     'actual_name': 'gold_cagrilar',
                     'companies': ['inhouse']},
    },

    # ---- FORECAST KOLON İSİMLERİ (forecast_cols) ----
    # df_forecast'taki kolon adlarına göre düzenle (V9 rehberi 7.1 örneği).
    'forecast_cols': {
        'datetime':       'model_data_date',   # tam timestamp kolon adı
        'date':           'truncddate',         # tarih kolon adı
        'kitle_total':    'kitle_nof_call',
        'kurumsal_total': 'kurumsal_nof_call',
        'gold_total':     'gold_total_call',
    },

    # ---- AHT ----
    'sub_queues': {},                 # load_aht_from_df() ile doldurulur
    'aht_overrides': {'kitle': {}, 'kurumsal': {}, 'gold': {}},
    'default_aht': 150,

    # ---- SAAT BAZLI MALİYET ÇARPANLARI ----
    'time_cost_multipliers': {
        'kitle': {
            'inhouse':   {'07:00': 15.0, '07:30': 10.0},
            'outsource': {},
        },
        'kurumsal': {'inhouse': {'07:00': 15.0, '07:30': 10.0}, 'outsource': {}},
        'gold':     {'inhouse': {'07:00': 15.0, '07:30': 10.0}, 'outsource': {}},
        'default':  {'inhouse': {'07:00': 3.8, '07:30': 2.0}, 'outsource': {}},
    },

    # ---- COMPANY ----
    'company': {
        'inhouse':   {'shift_value': 'inhouse'},
        'outsource': {'shift_value': 'outsource'},
    },

    # ---- VARDİYA KOLON İSİMLERİ ----
    'shift_columns': {
        'shift': 'shift', 'start': 'start', 'end': 'end', 'company': 'company',
    },

    # ---- ALT-KUYRUK MIN (K5) ----
    # Belirli alt-kuyrukların inhouse/outsource minimum coverage zorlaması.
    # min_ratio: o alt-kuyruğun slot çağrı payı kadar Erlang'ın bu katı min.
    # outsource_only'de 'hours' opsiyonel (sadece o saat aralığında zorla).
    'inhouse_only_subqueues': {
        'kitle': [
            {'sub_queue': 'retention_line', 'min_ratio': 1.0,
                         'hours': {'start': '08:00', 'end': '00:00'}},
            {'sub_queue': 'karttemelbankaclik', 'min_ratio': 0.20,
                          'hours': {'start': '08:00', 'end': '00:00'}},
        ],
        'kurumsal': [],
        'gold': [],
    },
    'outsource_only_subqueues': {
        'kitle': [
            {'sub_queue': 'kayipcalintisupheli', 'min_ratio': 1.0},
        ],
        'kurumsal': [],
        'gold': [],
    },

    # =========================================================================
    # QUEUE CONFIGS
    # =========================================================================
    'queue_configs': {

        # ----------- KİTLE -----------
        'kitle': {
            'erlang': {
                'target_asa': 30,
                'shrinkage': {
                    0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0, 6: 0.0,
                    7: 0.0, 8: 0.0, 9: 0.18, 10: 0.17, 11: 0.17, 12: 0.16,
                    13: 0.19, 14: 0.21, 15: 0.25, 16: 0.26, 17: 0.29, 18: 0.18,
                    19: 0.17, 20: 0.18, 21: 0.14, 22: 0.13, 23: 0.19,
                    'default': 0.0,
                },
                'interval_minutes': 30,
            },
            'mip': {
                'cost_inhouse': 1.0,
                'cost_outsource': 1.0,
                'min_per_shift': 13,                 # V9 sert kısıt — düşürülmez
                'min_per_shift_overrides': {'00:00':0},       # başlangıç saati bazlı override
                'weekly_shrinkage_fallback': {       # Stage 2
                    'enabled': False, 'per_day': False, 'step': 0.10, 'floor': 0.0,
                },
                'coverage_shortfall': {              # Stage 4
                    'enabled': True, 'penalty': 1000.0,
                },
            },
            'rr_penalty': {
                'enabled': True,
                'peak_exempt': True,
                'penalty_per_person': 4.0,
                'peak_penalty': 2.0,
                'peak_threshold': 0.85,
                'night_multiplier': {
                    'enabled': False,
                    'hours': {'start': '00:00', 'end': '07:00'},
                    'multiplier': 100.0,
                },
            },
            'slot_cap': {
                'enabled': True,
                'bands': [
                    {'start': '07:00', 'end': '08:00', 'max_ratio': 1.20, 'penalty': 120.0},
                    {'start': '08:00', 'end': '09:00', 'max_ratio': 1.40, 'penalty': 100.0},
                    {'start': '09:00', 'end': '11:00', 'max_ratio': 1.30, 'penalty': 80.0},
                    {'start': '22:00', 'end': '00:00', 'max_ratio': 1.15, 'penalty': 100.0},
                    {'start': '00:00', 'end': '07:00', 'max_ratio': 1.0, 'penalty': 500.0},

                ],
            },
            'balance_penalty': {
                'enabled': True,
                'penalty_per_diff': 2.0,
                'windows': [
                    {'name': 'sabah', 'start': '07:00', 'end': '11:59', 'penalty': 2.0},
                    {'name': 'aksam', 'start': '12:00', 'end': '23:30', 'penalty': 2.0},
                ],
            },
            'hourly_report': {                       # Kap_RR (monthly run) için
                'rapor_etkisi': {'default': 0.00},
                'kapasite_kaybi': {
                    0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0, 6: 0.0,
                    7: 0.0, 8: 0.0, 9: 0.17, 10: 0.10, 11: 0.10, 12: 0.09,
                    13: 0.12, 14: 0.14, 15: 0.18, 16: 0.19, 17: 0.22, 18: 0.11,
                    19: 0.10, 20: 0.11, 21: 0.08, 22: 0.07, 23: 0.12,
                    'default': 0.08,
                },
                'cagri_adedi': {'default': 15},
            },
        },

        # ----------- KURUMSAL (inhouse-only) -----------
        'kurumsal': {
            'erlang': {
                'target_asa': 30,
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
                'weekly_shrinkage_fallback': {
                    'enabled': False, 'per_day': False, 'step': 0.10, 'floor': 0.0,
                },
                'coverage_shortfall': {
                    'enabled': True, 'penalty': 1000.0,
                },
            },
            'rr_penalty': {
                'enabled': False,
                'peak_exempt': False,
                'penalty_per_person': 4.0,
                'peak_penalty': 2.0,
                'peak_threshold': 0.70,
                'night_multiplier': {
                    'enabled': False,
                    'hours': {'start': '00:00', 'end': '07:00'},
                    'multiplier': 100.0,
                },
            },
            'slot_cap': {'enabled': True, 'bands': [
                {'start': '20:00', 'end': '00:00', 'max_ratio': 1.20, 'penalty': 80.0},
                {'start': '00:00', 'end': '07:00', 'max_ratio': 1.0, 'penalty': 100.0},
            
            ]},
            'hourly_report': {
                'rapor_etkisi': {'default': 0.0},
                'kapasite_kaybi': {
                    0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0, 6: 0.0,
                    7: 0.0, 8: 0.0, 9: 0.17, 10: 0.10, 11: 0.10, 12: 0.09,
                    13: 0.12, 14: 0.14, 15: 0.18, 16: 0.19, 17: 0.22, 18: 0.11,
                    19: 0.10, 20: 0.11, 21: 0.08, 22: 0.07, 23: 0.12,
                    'default': 0.08,
                },
                'cagri_adedi': {'default': 15},
            },
        },

        # ----------- GOLD (inhouse-only) -----------
        'gold': {
            'erlang': {
                'target_asa': 30,
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
                'min_per_shift': 13,
                'min_per_shift_overrides': {'18:00':0, '19:00':0, '00:00':0},
                'weekly_shrinkage_fallback': {
                    'enabled': False, 'per_day': False, 'step': 0.10, 'floor': 0.0,
                },
                'coverage_shortfall': {
                    'enabled': True, 'penalty': 1000.0,
                },
            },
            'rr_penalty': {
                'enabled': False,
                'peak_exempt': False,
                'penalty_per_person': 2.0,
                'peak_penalty': 4.0,
                'peak_threshold': 0.70,
                'night_multiplier': {
                    'enabled': False,
                    'hours': {'start': '00:00', 'end': '07:00'},
                    'multiplier': 100.0,
                },
            },
            'slot_cap': {'enabled': False, 'bands': [
                {'start': '07:00', 'end': '08:00', 'max_ratio': 1.15, 'penalty': 50.0},
                {'start': '09:00', 'end': '10:00', 'max_ratio': 1.30, 'penalty': 50.0},
                {'start': '00:00', 'end': '07:00', 'max_ratio': 1.0, 'penalty': 100.0},
            ]},
            'hourly_report': {
                'rapor_etkisi': {'default': 0.0},
                'kapasite_kaybi': {
                    0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0, 6: 0.0,
                    7: 0.0, 8: 0.0, 9: 0.17, 10: 0.10, 11: 0.10, 12: 0.09,
                    13: 0.12, 14: 0.14, 15: 0.18, 16: 0.19, 17: 0.22, 18: 0.11,
                    19: 0.10, 20: 0.11, 21: 0.08, 22: 0.07, 23: 0.12,
                    'default': 0.08,
                },
                'cagri_adedi': {'default': 15},
            },
        },

    },

    # ---- SURPLUS DAĞITIM (kadro tavanı + dağıtım) ----
    'surplus_distribution': {
        'enabled': True,
        'outsource_enabled': True,

        # ==== V10 — OUTSOURCE: HAFTALIK ADAM-GÜN (kişi DEĞİL) ====
        # Operasyon buraya vendor'un o hafta çalıştırabileceği ADAM-GÜN'ü girer.
        # Günlük kişi sayısı KODDA türetilir (_derive_outsource_kadro):
        #     kadro/gün = (adam-gün − o haftanın hafta sonu outsource'u)
        #                 ÷ o haftanın hafta içi gün sayısı
        # Hafta anahtarı `_week_of_month` ile aynı (ay sınırına saygılı, Pzt başlangıçlı).
        # 2026 Eylül: hafta_1=1-6(4 h.içi) hafta_2=7-13(5) hafta_3=14-20(5)
        #             hafta_4=21-27(5) hafta_5=28-30(3)
        # ÖNCELİK: burada hafta_N VARSA total_kadro[...]['outsource'] üzerine YAZILIR.
        # MANUEL kişi sayısına dönmek istersen (3 seviye):
        #   tek hafta → o hafta_N'i buradan SİL ya da None yap
        #   kuyruk    → o kuyruğu buradan sil
        #   tamamen   → 'outsource_adam_gun' anahtarını hiç yazma (V9 davranışı)
        # Türetilmeyen haftalar total_kadro'daki elle girilen değeri KORUR.
        # kurumsal/gold: outsource agent çalışmıyor → giriş yok.
        'outsource_adam_gun': {
            # AÇMA/KAPAMA — hangi girişin kullanılacağını BU belirler:
            #   True  → ADAM-GÜN girişi kullanılır, günlük kişi KODDA türetilir
            #           ve total_kadro[...]['outsource'] üzerine yazılır.
            #   False → türetme HİÇ çalışmaz; günlük KİŞİ SAYISI doğrudan
            #           total_kadro[kuyruk]['outsource']'tan okunur (hafta_N/default).
            # Anahtar yoksa True kabul edilir (geriye uyumlu).
            'enabled': True,
            'kitle': {
                'hafta_1': 1613,
                'hafta_2': 1978,
                'hafta_3': 2042,
                'hafta_4': 2106,
                'hafta_5': 950,
            },
        },
        # Hafta sonu PART-TIME, outsource adam-gün bütçesinden düşülsün mü?
        # KARAR (operasyon, 2026-09-01): DÜŞÜLMEZ — PT ayrı bir hat.
        'outsource_adam_gun_pt_dahil': False,

        'total_kadro': {
            'kitle':    {
                'inhouse': {
                    'hafta_1': 412,
                    'hafta_2': 413,
                    'hafta_3': 414,
                    'hafta_4': 420,
                    'hafta_5': 428,
                    'default': 420,      # diğer haftalar
                },
                # OUTSOURCE — günlük KİŞİ sayısı. SÖZLÜK olmalı (düz sayı YAZMA):
                #   enabled=True  → adam-günden türetilen bu değerlerin ÜZERİNE yazar;
                #                   burası yalnızca adam-günü GİRİLMEMİŞ haftalar için
                #                   yedektir. 'default' olmazsa o hafta 0'a düşer.
                #   enabled=False → kişi sayısı DOĞRUDAN buradan okunur; hafta hafta
                #                   gir, ör: 'hafta_1': 274, 'hafta_2': 287, ...
                'outsource': {
                    'default': 450,      # tüm haftalar (hafta_N yazılmadıkça)
                },
            },
            'kurumsal': {
                'inhouse': {
                    'hafta_1': 47,
                    'hafta_2': 49,
                    'hafta_3': 46,
                    'hafta_4': 44,
                    'hafta_5': 48,
                    'default': 52,       # diğer haftalar
                },
            },
            'gold':     {
                'inhouse': {
                    'hafta_1': 115,
                    'hafta_2': 112,
                    'hafta_3': 112,
                    'hafta_4': 116,
                    'hafta_5': 124,
                    'default': 129,      # diğer haftalar
                },
            },
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
