# =============================================================================
# HAFTALIK MIP V9 — KOŞTURMA + CONFIG (TEK DOSYA)
# =============================================================================
# V9 = V8 + Stage 4 (Coverage Shortfall — eksik kapsamaya izin)
#
# Bu config'de Stage 3 (min_per_shift azaltma) KAPALI — kullanıcı kuralı:
# min_per_shift=13 sert kısıt, düşürülmez.
#
# Aktif fallback akışı (run_week_all_queues içinde):
#   AŞAMA 1: Orijinal
#   AŞAMA 2: Per-day shrinkage azaltma — çağrı sırasıyla, en yoğun gün önce
#   AŞAMA 3: (KAPALI — min_per_shift kırılmaz)
#   AŞAMA 4: COVERAGE SHORTFALL (V9 YENİ)
#            Stage 1-2 hâlâ infeasible bıraktıysa coverage'ı soft yapar:
#            covered + shortfall ≥ erlang_need  (shortfall'a yüksek penalty)
#            → MIP çözebilir, raporda hangi gün/slot'ta ne kadar eksik kaldığı
#              ve kabaca ne kadar ek kadro gerektiği görünür.
#
# Geriye uyumlu: queue config'inde 'coverage_shortfall.enabled=False' ise
# V8 ile birebir aynı davranır.
#
# DOSYALAR:
#   - actual_pipeline_v9_weekly.py  → MIP motoru (elleme)
#   - run_weekly_v9.py              → BU DOSYA: config + akış
#
# Hücre hücre çalıştır (# %% [HÜCRE N] ile işaretli).
# =============================================================================


# %% [HÜCRE 1] — Importlar (HEPSI v9'dan, v8/v7/v6 ile bağlantı YOK)
import pandas as pd
import pickle

from actual_pipeline_v9_weekly import (
    # Haftalık MIP (V9 fallback ladder + Stage 4 shortfall ile)
    run_week_all_queues,
    optimize_week,
    print_weekly_summary,
    print_weekly_full_report,   # opsiyonel — manuel çağrı için
    print_weekly_daily_detail,  # v6 tarzı her gün için MIP(1)/MIP(2) yan yana
    # v9 içine alınmış v6 fonksiyonları (standalone)
    load_aht_from_df,
    prepare_calls_30,
    calculate_erlang_all,
    print_queue_report,
    get_actual_summary,
)


# %% [HÜCRE 2] — Veri çekme
# Mevcut aylık notebook'undaki veri çekme kodunu BURAYA YAPIŞTIR.
# Gereken:
#   - df_calls (en az hafta tarihlerini içermeli)
#   - df_aht
#   - df_shifts_dict = {'kitle': df, 'kurumsal': df, 'gold': df}
#   - df_actual (opsiyonel — gerçek karşılaştırması için)
#
# Örnek:
#   df_calls = pd.read_sql("SELECT ... FROM ...", conn)
#   df_aht   = pd.read_sql("SELECT ... FROM ...", conn)
#   df_shifts_dict = {
#       'kitle':    pd.read_excel('vardiyalar.xlsx', sheet_name='kitle'),
#       'kurumsal': pd.read_excel('vardiyalar.xlsx', sheet_name='kurumsal'),
#       'gold':     pd.read_excel('vardiyalar.xlsx', sheet_name='gold'),
#   }


# %% [HÜCRE 3] — CONFIG_WEEKDAY (inline)
# Kitle = gerçek dağılım uyumlu tuned değerler.
# Kurumsal & Gold = v6 default değerleri.
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

    # ---- AHT (load_aht_from_df ile doldurulur, HÜCRE 5'te) ----
    'sub_queues': {},
    'aht_overrides': {'kitle': {}, 'kurumsal': {}, 'gold': {}},
    'default_aht': 150,

    # ---- PART-TIME ----
    'part_time': {
        'enabled': False,
        'shifts': ['09:00-13:00', '10:00-14:00', '19:00-23:00'],
        'count': {'kitle': 42, 'kurumsal': 4, 'gold': 10},
    },

    'outsource_ratio': {'kitle': None, 'kurumsal': None, 'gold': None},

    # ---- SAAT BAZLI MALİYET ÇARPANLARI ----
    # Kitle inhouse'da 09:00 ve 15:00 saatleri EN UCUZ → MIP buralara yığsın.
    'time_cost_multipliers': {
        'kitle': {
            'inhouse': {
                '07:00': 25.0, '07:30': 10.0,
                '08:00': 1.05, '08:30': 1.05, '09:00': 1.00, '09:30': 1.05,
                '10:00': 1.05, '10:30': 1.05,
                '11:00': 1.10, '11:30': 1.10, '12:00': 1.10, '13:00': 1.10,
                '14:00': 1.10,
                '15:00': 1.00,
                '17:00': 1.15, '18:00': 1.15, '19:00': 1.20, '22:00': 1.30,
            },
            'outsource': {'07:00': 2.0, '07:30': 2.0},
        },
        'kurumsal': {'inhouse': {'07:00': 1.8, '07:30': 1.5}, 'outsource': {}},
        'gold':     {'inhouse': {'07:00': 2.0, '07:30': 1.7}, 'outsource': {}},
        'default':  {'inhouse': {'07:00': 1.8, '07:30': 1.5}, 'outsource': {}},
    },

    'company': {
        'inhouse':   {'shift_value': 'inhouse',   'outsource_flg': 0},
        'outsource': {'shift_value': 'outsource', 'outsource_flg': 1},
    },
    'shift_columns': {'shift': 'shift', 'start': 'start', 'end': 'end',
                      'company': 'company'},
    'calls_columns': {'date': 'data_date', 'time': 'min_time_period_value',
                      'sub_queue': 'resource_group_key',
                      'main_queue': 'line_based_main_group', 'calls': 'not_call'},
    'actual_columns': {'date': 'working_date', 'queue': 'line_based_main_group',
                       'location': 'working_main_group',
                       'shift_start': 'shifts_start_hour',
                       'shift_end': 'shifts_end_hour',
                       'outsource': 'outsource_flg', 'weekend': 'weekend_flg',
                       'count': 'calisan_kisi_sayisi'},
    'report': {'peak_threshold': 0.70},

    'inhouse_only_subqueues': {
        'kitle': ['retention_line',
                  {'sub_queue': 'karttemelbankaclik', 'min_ratio': 0.20}],
        'kurumsal': [], 'gold': [],
    },
    'outsource_only_subqueues': {
        'kitle': [{'sub_queue': 'kayipcalintisupheli', 'min_ratio': 1.0,
                   'hours': {'start': '08:00', 'end': '00:00'}}],
        'kurumsal': [], 'gold': [],
    },

    # =========================================================================
    # QUEUE CONFIGS
    # =========================================================================
    'queue_configs': {

        # ----------- KİTLE (gerçek-dağılım uyumlu tuned) -----------
        'kitle': {
            'erlang': {
                'target_asa': 30, 'target_seconds': 30,
                'shrinkage': {
                    0: 0.07, 1: 0.07, 2: 0.07, 3: 0.07, 4: 0.07, 5: 0.07,
                    6: 0.07, 7: 0.07, 8: 0.07, 9: 0.24, 10: 0.17, 11: 0.17,
                    12: 0.16, 13: 0.19, 14: 0.21, 15: 0.25, 16: 0.26, 17: 0.29,
                    18: 0.18, 19: 0.17, 20: 0.18, 21: 0.14, 22: 0.13, 23: 0.19,
                    'default': 0.0,
                },
                'interval_minutes': 30,
            },
            'mip': {
                'cost_inhouse': 1.0, 'cost_outsource': 1.0,
                'min_per_shift': 13,              # KULLANICI ZORUNLULUĞU — kırılmaz
                # Düşük talepli saatler için saat-özel istisna gir.
                # Örn. {'22:00': 1, '00:00': 1, '01:00': 1} → gece vardiyalarında min 1
                'min_per_shift_overrides': {},
                # Haftalık MIP infeasible olursa shrinkage'ı kademeli azaltır
                # (her saatten -step puan, floor'da kıs) ve Erlang'ı tüm günler
                # için yeniden hesaplayıp tekrar dener. min_per_shift sabit kalır.
                'weekly_shrinkage_fallback': {
                    'enabled': True,
                    'step': 0.10,
                    'floor': 0.0,
                    'per_day': True,    # V8: çağrı en yüksek gün önce azalsın
                },
                # V9: min_per_shift SERT KISIT — düşürülmez. Stage 3 KAPALI.
                # Akış: Stage 1 (orijinal) → Stage 2 (shrinkage) → Stage 4 (shortfall)
                'weekly_min_per_shift_fallback': {
                    'enabled': False,
                    'step': 1,
                    'floor': 1,
                },
                # V9: Stage 4 — Stage 1-3 hâlâ infeasible bıraktıysa
                # coverage'ı soft yap (covered + shortfall ≥ erlang_need).
                # Pazartesi gibi yoğun günlerde kadro yetmediğinde model
                # yine de çözüm verir, raporda eksik kapsama görünür.
                'coverage_shortfall': {
                    'enabled': True,
                    'penalty': 1000.0,
                },
            },
            'rr_penalty': {
                'enabled': True, 'peak_exempt': False,
                'penalty_per_person': 4.0, 'peak_penalty': 2.0,
                'peak_threshold': 0.70,
                'night_multiplier': {
                    'enabled': True,
                    'hours': {'start': '00:00', 'end': '07:00'},
                    'multiplier': 100.0,
                },
            },
            'small_shift_penalty': {'enabled': True, 'penalty': 10},
            # Gerçeğin gözlemlenen oranlarına göre genişletilmiş bantlar
            'slot_cap': {
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
            },
            'balance_penalty': {
                'enabled': True, 'penalty_per_diff': 1.0,
                'windows': [
                    {'name': 'sabah', 'start': '07:00', 'end': '11:59', 'penalty': 1.0},
                    {'name': 'aksam', 'start': '12:00', 'end': '23:30', 'penalty': 1.0},
                ],
            },
            # Pencere bazlı smoothing — gerçekteki sıçramaları korumak için kademeli
            'start_smoothing': {
                'enabled': True,
                'companies': ['inhouse', 'outsource'],
                'windows': [
                    {'name': 'sabah', 'start': '07:00', 'end': '10:00', 'penalty': 2.0},
                    {'name': 'ogle',  'start': '10:00', 'end': '15:00', 'penalty': 8.0},
                    {'name': 'aksam', 'start': '15:00', 'end': '20:00', 'penalty': 3.0},
                ],
            },
            'hourly_report': {
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

        # ----------- KURUMSAL -----------
        'kurumsal': {
            'erlang': {
                'target_asa': 30, 'target_seconds': 30,
                'shrinkage': {
                    0: 0.07, 1: 0.07, 2: 0.07, 3: 0.07, 4: 0.07, 5: 0.07,
                    6: 0.07, 7: 0.07, 8: 0.07, 9: 0.24, 10: 0.17, 11: 0.17,
                    12: 0.16, 13: 0.19, 14: 0.21, 15: 0.25, 16: 0.26, 17: 0.29,
                    18: 0.18, 19: 0.17, 20: 0.18, 21: 0.14, 22: 0.13, 23: 0.19,
                    'default': 0.0,
                },
                'interval_minutes': 30,
            },
            'mip': {
                'cost_inhouse': 1.0, 'cost_outsource': 1.0,
                'min_per_shift': 13,
                'min_per_shift_overrides': {},
                'weekly_shrinkage_fallback': {
                    'enabled': True,
                    'step': 0.10,
                    'floor': 0.0,
                    'per_day': True,    # V8: çağrı en yüksek gün önce azalsın
                },
                # V9: min_per_shift SERT KISIT — düşürülmez. Stage 3 KAPALI.
                # Akış: Stage 1 (orijinal) → Stage 2 (shrinkage) → Stage 4 (shortfall)
                'weekly_min_per_shift_fallback': {
                    'enabled': False,
                    'step': 1,
                    'floor': 1,
                },
                # V9: Stage 4 — Stage 1-3 hâlâ infeasible bıraktıysa
                # coverage'ı soft yap (covered + shortfall ≥ erlang_need).
                # Pazartesi gibi yoğun günlerde kadro yetmediğinde model
                # yine de çözüm verir, raporda eksik kapsama görünür.
                'coverage_shortfall': {
                    'enabled': True,
                    'penalty': 1000.0,
                },
            },
            'rr_penalty': {
                'enabled': True, 'peak_exempt': True,
                'penalty_per_person': 4.0, 'peak_penalty': 2.0,
                'peak_threshold': 0.70,
                'night_multiplier': {
                    'enabled': True,
                    'hours': {'start': '00:00', 'end': '07:00'},
                    'multiplier': 100.0,
                },
            },
            'small_shift_penalty': {'enabled': True, 'penalty': 10},
            'slot_cap': {'enabled': False, 'bands': []},
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

        # ----------- GOLD -----------
        'gold': {
            'erlang': {
                'target_asa': 30, 'target_seconds': 30,
                'shrinkage': {
                    0: 0.07, 1: 0.07, 2: 0.07, 3: 0.07, 4: 0.07, 5: 0.07,
                    6: 0.07, 7: 0.07, 8: 0.07, 9: 0.24, 10: 0.17, 11: 0.17,
                    12: 0.16, 13: 0.19, 14: 0.21, 15: 0.25, 16: 0.26, 17: 0.29,
                    18: 0.18, 19: 0.17, 20: 0.18, 21: 0.14, 22: 0.13, 23: 0.19,
                    'default': 0.0,
                },
                'interval_minutes': 30,
            },
            'mip': {
                'cost_inhouse': 1.0, 'cost_outsource': 1.0,
                'min_per_shift': 13,
                'min_per_shift_overrides': {},
                'weekly_shrinkage_fallback': {
                    'enabled': True,
                    'step': 0.10,
                    'floor': 0.0,
                    'per_day': True,    # V8: çağrı en yüksek gün önce azalsın
                },
                # V9: min_per_shift SERT KISIT — düşürülmez. Stage 3 KAPALI.
                # Akış: Stage 1 (orijinal) → Stage 2 (shrinkage) → Stage 4 (shortfall)
                'weekly_min_per_shift_fallback': {
                    'enabled': False,
                    'step': 1,
                    'floor': 1,
                },
                # V9: Stage 4 — Stage 1-3 hâlâ infeasible bıraktıysa
                # coverage'ı soft yap (covered + shortfall ≥ erlang_need).
                # Pazartesi gibi yoğun günlerde kadro yetmediğinde model
                # yine de çözüm verir, raporda eksik kapsama görünür.
                'coverage_shortfall': {
                    'enabled': True,
                    'penalty': 1000.0,
                },
            },
            'rr_penalty': {
                'enabled': True, 'peak_exempt': True,
                'penalty_per_person': 2.0, 'peak_penalty': 4.0,
                'peak_threshold': 0.70,
                'night_multiplier': {
                    'enabled': True,
                    'hours': {'start': '00:00', 'end': '07:00'},
                    'multiplier': 100.0,
                },
            },
            'small_shift_penalty': {'enabled': True, 'penalty': 10},
            'slot_cap': {'enabled': False, 'bands': []},
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

    # ---- SURPLUS DAĞITIM (v7 ikinci iterasyonda devreye girecek) ----
    # V9: total_kadro per-day destekli — her değer int VEYA dict olabilir.
    # Dict format: {'YYYY-MM-DD': N, 'Mon'..'Sun': N, 'default': N}
    # Çözümleme önceliği: tarih > gün-of-week > default
    #
    # Örnekler:
    #   'inhouse': 380                              → tüm günlerde 380 (mevcut)
    #   'inhouse': {'Mon': 400, 'default': 380}      → her Pzt 400, diğer 380
    #   'outsource': {
    #       '2026-02-02': 470,    # bu spesifik Pzt için 470
    #       '2026-02-09': 460,    # sonraki Pzt için 460
    #       'Mon': 450,           # diğer Pzt'ler için 450
    #       'default': 440,       # geri kalan günler 440
    #   }
    'surplus_distribution': {
        'enabled': True, 'outsource_enabled': True,
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


# %% [HÜCRE 4] — AHT yükle
CONFIG_WEEKDAY['sub_queues'] = load_aht_from_df(df_aht, config=CONFIG_WEEKDAY)


# %% [HÜCRE 5] — Cuma-özel inhouse ek shift
# Standart Excel listesinde olmayan, sadece Cuma aktif olacak shift'leri ekle.
# 'available_days' kolonu yoksa pipeline default'ta tüm günler aktif sayar.
extra_friday_kitle = pd.DataFrame([
    {
        'shift': '14:00-23:00_fri',
        'start': '14:00', 'end': '23:00', 'company': 'inhouse',
        'available_days': ['Fri'],
    },
])

df_shifts_dict['kitle'] = pd.concat(
    [df_shifts_dict['kitle'], extra_friday_kitle],
    ignore_index=True,
)


# %% [HÜCRE 6] — Hafta tarihlerini belirle ve MIP koştur
WEEK_DATES = [
    '2026-02-09',   # Pzt
    '2026-02-10',   # Sal
    '2026-02-11',   # Çar
    '2026-02-12',   # Per
    '2026-02-13',   # Cum
]

results = run_week_all_queues(
    df_calls=df_calls,
    df_shifts_by_queue=df_shifts_dict,
    target_dates=WEEK_DATES,
    config=CONFIG_WEEKDAY,
    queues=('kitle', 'kurumsal', 'gold'),
    verbose=True,
)
# results['<queue>']['stable']         → {shift_key: count}  (Pzt-Cum aynı)
# results['<queue>']['day_specific']   → {day_label: {shift_key: count}}
# results['<queue>']['info_per_day']   → {day_label: mip_info (v6 uyumlu)}


# %% [HÜCRE 7] — Pickle olarak kaydet (opsiyonel)
PKL_FILE = f"weekly_v9_{WEEK_DATES[0]}_{WEEK_DATES[-1]}.pkl"
with open(PKL_FILE, 'wb') as f:
    pickle.dump({
        'week_dates': WEEK_DATES,
        'results': results,
    }, f)
print(f"\nKaydedildi: {PKL_FILE}")


# %% [HÜCRE 8] — Günlük detay raporu fonksiyonu (tek gün için)
def print_daily_detail(queue, day_label):
    """v6 print_queue_report'u tek bir gün için çağırır.
    info içinde mip_info_stage1 varsa MIP(1)/MIP(2) yan yana basılır.
    """
    info = results[queue]['info_per_day'].get(day_label)
    if info is None:
        print(f"  {queue} {day_label}: veri yok")
        return
    target_date = info['target_date']
    df_calls_30 = prepare_calls_30(df_calls, config=CONFIG_WEEKDAY)
    df_erlang = calculate_erlang_all(df_calls_30, config=CONFIG_WEEKDAY)
    d = pd.to_datetime(target_date)
    df_q = df_erlang[(df_erlang['date'] == d) & (df_erlang['queue'] == queue)]
    # Erlang: MIP'in fiilen çözdüğü değer (shrinkage fallback sonrası).
    # Aksi halde Hücre 9 ile tutarsız çıkıyor.
    erlang_by_slot = info.get('erlang_by_slot')
    if not erlang_by_slot:
        erlang_by_slot = dict(zip(df_q['slot'], df_q['erlang_need']))
    weighted_aht_by_slot = dict(zip(df_q['slot'], df_q['weighted_aht']))
    df_calls_day = df_calls_30[df_calls_30['data_date'] == d]
    calls_col = f"{queue}_total"
    calls_by_slot = (dict(zip(df_calls_day['slot_30'], df_calls_day[calls_col]))
                     if calls_col in df_calls_day.columns else {})

    actual = None
    try:
        actual = get_actual_summary(df_actual, target_date, queue, CONFIG_WEEKDAY)
    except Exception:
        pass

    print_queue_report(
        target_date, queue, erlang_by_slot, info, actual,
        weighted_aht_by_slot=weighted_aht_by_slot,
        calls_by_slot=calls_by_slot,
        mip_info_stage1=info.get('mip_info_stage1'),  # MIP(1)/MIP(2) yan yana
        config=CONFIG_WEEKDAY,
    )


# Örnek: print_daily_detail('kitle', 'Fri')


# %% [HÜCRE 9] — TÜM KUYRUKLAR için v6 mantığında her güne ayrı detay rapor
# Inhouse + outsource beraber, MIP(1) vs MIP(2) (surplus öncesi/sonrası) yan yana,
# slot bazlı detay, kapasite raporu, RR%, peak işaretleri — v6 print_queue_report.
# df_actual opsiyonel: kullanıcı ayrıca yüklediyse gerçek karşılaştırması da gelir.
df_actual_for_detail = globals().get('df_actual')

print_weekly_daily_detail(
    queue=('kitle', 'kurumsal', 'gold'),
    results=results,
    df_calls=df_calls,
    df_actual=df_actual_for_detail,
    config=CONFIG_WEEKDAY,
)
