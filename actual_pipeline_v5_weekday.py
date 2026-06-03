run_week_all_queues(df_forecast, target_dates=[5 gün], config, queues=3)
│
├── df_calls_30_pre verildi → onu kullan (çevirmeye gerek yok)
│   YOKSA → prepare_forecast_calls_30(df_forecast, config)
│
└── for queue in (kitle, kurumsal, gold):
    │
    ├── config'i oku: min_per_shift, shrinkage, fallback ayarları, ...
    │
    ├── 5 günü çağrı sayısına göre sırala (en yoğun gün önce)
    │
    ├── inner function: _trial(stage_label, min_param, enable_shortfall)
    │   │   ← her aşamada bu fonksiyon çağrılıyor
    │   │
    │   ├── _build_erlang_per_day VEYA
    │   │   _build_erlang_per_day_individual ← shrinkage decrement uygulanmışsa
    │   │       │
    │   │       └── calculate_erlang_all(df_calls_30, config)
    │   │           │
    │   │           └── for her satır (gün × slot):
    │   │               ├── calculate_weighted_aht(row, queue, slot)
    │   │               │     └── get_sub_queue_aht(...)
    │   │               └── find_optimal_agents(calls, aht, slot)
    │   │                     ├── erlang_c(...)
    │   │                     └── calc_asa(...)
    │   │
    │   └── optimize_week(erlang_by_slot_per_day, df_shifts, ...)
    │       │   ← BU MIP'in kendisi (PuLP solver)
    │       │
    │       ├── create_shift_coverage(df_shifts)
    │       │   └── is_slot_in_shift(...)
    │       ├── _classify_shifts_by_days, _shift_available_on_day
    │       ├── _date_to_day_label(target_dates)
    │       ├── LpVariable + kısıt + cost terimleri kurma:
    │       │   ├── x[s], x_day[(s,d)], y[s], y_day[(s,d)] değişkenleri
    │       │   ├── _classify_shift(...) → maliyet hesabı
    │       │   ├── get_time_cost_multiplier(...) → saat çarpanı
    │       │   ├── Coverage kısıtı (Stage 4 açıksa shortfall var)
    │       │   ├── RR penalty, Slot cap, Balance penalty
    │       │   ├── min_per_shift (big-M)
    │       │   ├── Kadro tavanı:
    │       │   │   └── _resolve_kadro(kadro_value, date, day) ← per-day
    │       │   └── Surplus dağıtım kısıtları
    │       │
    │       └── PULP_CBC_CMD(...).solve() → çözüm gelir
    │           └── stable_assignments, day_specific_assignments, info_per_day döner
    │
    ├── Stage 1: _trial(orijinal config)
    │   ├── çözerse dur ✓
    │   └── INFEASIBLE → Stage 2'ye geç
    │
    ├── Stage 2: _trial(per-day shrinkage azalt)
    │   ├── çağrı yoğun günden başla, shrinkage'ı 0.10 azalt, _trial dene
    │   ├── hala olmazsa o günün shrinkage'ını 0.20 azalt, dene
    │   ├── floor'a (0) inene kadar tek tek günleri ekle
    │   └── çözerse dur ✓, yoksa Stage 3
    │
    ├── Stage 3: _trial(per-day min_per_shift azalt)
    │   └── KAPALI (V9'da `weekly_min_per_shift_fallback.enabled=False`)
    │       → atlanıyor
    │
    ├── Stage 4: _trial(coverage shortfall AKTİF)
    │   ├── Erlang'ı tam karşılamak zorunda değil
    │   ├── eksik kalan slot'lara yüksek penalty (1000) ile shortfall LpVar
    │   └── MIP yine de çözer (matematik garantisi)
    │
    ├── Sonuç bulunduysa:
    │   ├── _compute_shortfall_recommendations(info)
    │   │     → her gün için: hangi vardiyaya kaç kişi eklersek eksik kapanır
    │   │
    │   └── _distribute_surplus_per_day(stable, day_specific, info, ...)
    │       │   ← Surplus var mı? Kadro tavanı henüz dolmadıysa kalan kişiyi
    │       │     vardiyalara dağıt
    │       ├── _resolve_kadro(...) → o günün kadrosunu çöz
    │       ├── _allocate_within_pool(...) → kalan kişiyi vardiyalara böl
    │       └── info['mip_info_stage1'] olarak SURPLUS ÖNCESİ snapshot sakla
    │           (sonra Excel raporda MIP1 vs MIP2 göstermek için)
    │
    └── _print_trial_log_v8(...) → fallback aşama tablosunu bas
    
└── results[queue] = {stable, day_specific, info_per_day, solution_stage, ...}




df_forecast (15 dk geniş format)
        │
        ▼  prepare_forecast_calls_30()
df_calls_30 (30 dk: data_date | slot_30 | kitle_total | sq_calls | ...)
        │
        ▼  calculate_erlang_all() + AHT hesabı
erlang_by_slot_per_day = {
    'Mon': {'09:00': 100, '09:30': 120, ...},
    'Tue': {...}, ...
}
        │
        ▼  optimize_week()  [MIP solve]
stable_assignments = {'08:00-17:00_inhouse': 13, ...}     # Pzt-Cum aynı
day_specific_assignments = {                              # Her gün ayrı
    'Mon': {'10:00-19:00_outsource': 12, ...},
    'Tue': {...},
}
info_per_day = {                                          # Detaylı meta
    'Mon': {
        'mip_by_slot': {'09:00': 92, ...},
        'erlang_by_slot': {'09:00': 100, ...},
        'shortfall_by_slot': {'09:00': 8, ...},  # Stage 4 çıktıysa
        ...
    }
}
        │
        ▼  _distribute_surplus_per_day()  [kadro tavanına kadar doldur]
info_per_day güncellenir:
    'Mon': {
        ...,
        'mip_info_stage1': {sürplüs öncesi snapshot},  ← MIP1
        'surplus_added': {'09:00-18:00_outsource': 5, ...},  ← +N eklenen
        'assignments': {güncel + surplus},  ← MIP2
    }
        │
        ▼
results['kitle'] = {stable, day_specific, info_per_day, ...}
