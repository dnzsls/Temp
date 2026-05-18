# =============================================================================
# GERÇEK vs MODEL — RUNNER (HAFTALIK V7)
# =============================================================================
# Manuel girilen Pzt-Cum vardiya planını v7 weekly modelin çıktısıyla yan yana
# karşılaştırır. 5 gün × her queue için ayrı tablo basar.
#
# pkl yapısı (run_weekly_v7.py'nin kaydettiği):
#   {'week_dates': [...], 'results': {queue: {'info_per_day': {day_label: info}}}}
#
# Önkoşul:
#   - weekly_v7_<start>_<end>.pkl mevcut
#   - df_calls erişilebilir
#   - CONFIG_WEEKDAY tanımlı (weekly yalnız haftaiçi)
# =============================================================================


# %% [HÜCRE 1] — Importlar
import pandas as pd
import pickle

from actual_pipeline_v7_weekly import (
    prepare_calls_30,
    calculate_erlang_all,
    is_slot_in_shift,
    add_30min,
    load_aht_from_df,
    SLOTS_30,
    _date_to_day_label,
)


# %% [HÜCRE 2] — Veri çekme
# Mevcut weekly notebook'tan veri çekme kodunu BURAYA YAPIŞTIR.
# En azından df_calls lazım. df_aht da gerekirse (sub_queues için).
#
# Örnek:
# df_calls = pd.read_sql("SELECT ... FROM ...", conn)
# df_aht   = pd.read_sql("SELECT ... FROM ...", conn)


# %% [HÜCRE 3] — Config (haftaiçi)
# Mevcut run_weekly_v7.py'deki CONFIG_WEEKDAY'i BURAYA YAPIŞTIR.
# AHT yükleme satırını da unutma:
#
# CONFIG_WEEKDAY['sub_queues'] = load_aht_from_df(df_aht, config=CONFIG_WEEKDAY)


# %% [HÜCRE 4] — Karşılaştırma fonksiyonu
def _aggregate_shifts_to_slots(shifts_dict):
    """{'08:00-17:00': {'inhouse': 10, 'outsource': 5}, ...} →
    (by_slot_in, by_slot_out, by_slot_total) ayrı dict'ler.
    Outsource bitiş saatine +30dk eklenir (pipeline'daki add_30min kuralına uygun).
    """
    by_slot_in = {s: 0 for s in SLOTS_30}
    by_slot_out = {s: 0 for s in SLOTS_30}
    for shift_str, counts in shifts_dict.items():
        start, raw_end = shift_str.split('-')
        in_kisi = counts.get('inhouse', 0)
        out_kisi = counts.get('outsource', 0)
        out_end = add_30min(raw_end)   # outsource için bitiş +30dk
        for s in SLOTS_30:
            if in_kisi and is_slot_in_shift(s, start, raw_end):
                by_slot_in[s] += in_kisi
            if out_kisi and is_slot_in_shift(s, start, out_end):
                by_slot_out[s] += out_kisi
    by_slot_total = {s: by_slot_in[s] + by_slot_out[s] for s in SLOTS_30}
    return by_slot_in, by_slot_out, by_slot_total


def _capacity_calc(kap, hour, cagri, re_cfg, kk_cfg, ca_cfg):
    re_oran = re_cfg.get(hour, re_cfg.get('default', 0))
    kk_oran = kk_cfg.get(hour, kk_cfg.get('default', 0))
    ca = ca_cfg.get(hour, ca_cfg.get('default', 15))
    re = round(kap * re_oran)
    kk = round(kap * kk_oran)
    nmt = kap - re - kk
    ck = nmt * (ca / 2)
    rr = ck / cagri if cagri > 0 else 0
    return re, kk, nmt, ck, rr


def _print_day_table(date_str, day_label, queue, calls_by_slot, erlang_by_slot,
                     gercek_in, gercek_out, gercek_tot,
                     model_in, model_out, model_tot,
                     re_cfg, kk_cfg, ca_cfg):
    """Tek bir gün × queue tablosunu bas."""
    gun_adi = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Pzr'][
        pd.to_datetime(date_str).weekday()
    ]
    line_w = 130
    print(f"\n{'='*line_w}")
    print(f"GERÇEK vs MODEL — {queue.upper()} — {date_str} ({day_label}/{gun_adi})")
    print(f"{'='*line_w}")
    print(f"  {'Slot':<6} {'Çağrı':>6} {'Erl':>5} | "
          f"{'──────── GERÇEK ────────':^34} | "
          f"{'──────── MODEL ─────────':^34} | "
          f"{'─ FARK ─':^11}")
    print(f"  {'':>6} {'':>6} {'':>5} | "
          f"{'In':>4} {'Out':>4} {'Kap':>4} {'NMT':>4} {'Ç.Kap':>7} {'RR':>5} | "
          f"{'In':>4} {'Out':>4} {'Kap':>4} {'NMT':>4} {'Ç.Kap':>7} {'RR':>5} | "
          f"{'NMT':>4} {'RR':>5}")
    print('-' * line_w)

    t_g_in = t_g_out = t_g_kap = t_g_nmt = t_g_ck = 0
    t_m_in = t_m_out = t_m_kap = t_m_nmt = t_m_ck = 0
    t_cagri = t_erl = 0

    for slot in SLOTS_30:
        cagri = int(calls_by_slot.get(slot, 0))
        erl = erlang_by_slot.get(slot, 0)
        g_in = gercek_in.get(slot, 0)
        g_out = gercek_out.get(slot, 0)
        g_kap = gercek_tot.get(slot, 0)
        m_in = model_in.get(slot, 0)
        m_out = model_out.get(slot, 0)
        m_kap = model_tot.get(slot, 0)

        if cagri == 0 and g_kap == 0 and m_kap == 0:
            continue

        h = int(slot[:2])
        _, _, g_nmt, g_ck, g_rr = _capacity_calc(g_kap, h, cagri, re_cfg, kk_cfg, ca_cfg)
        _, _, m_nmt, m_ck, m_rr = _capacity_calc(m_kap, h, cagri, re_cfg, kk_cfg, ca_cfg)

        t_cagri += cagri; t_erl += erl
        t_g_in += g_in; t_g_out += g_out
        t_g_kap += g_kap; t_g_nmt += g_nmt; t_g_ck += g_ck
        t_m_in += m_in; t_m_out += m_out
        t_m_kap += m_kap; t_m_nmt += m_nmt; t_m_ck += m_ck

        print(f"  {slot:<6} {cagri:>6} {erl:>5} | "
              f"{g_in:>4} {g_out:>4} {g_kap:>4} {g_nmt:>4} {g_ck:>7.0f} {g_rr:>5.0%} | "
              f"{m_in:>4} {m_out:>4} {m_kap:>4} {m_nmt:>4} {m_ck:>7.0f} {m_rr:>5.0%} | "
              f"{m_nmt - g_nmt:>+4} {(m_rr - g_rr):>+5.0%}")

    t_g_rr = t_g_ck / t_cagri if t_cagri > 0 else 0
    t_m_rr = t_m_ck / t_cagri if t_cagri > 0 else 0
    print('-' * line_w)
    print(f"  {'TOPLAM':<6} {t_cagri:>6} {t_erl:>5} | "
          f"{t_g_in:>4} {t_g_out:>4} {t_g_kap:>4} {t_g_nmt:>4} {t_g_ck:>7.0f} {t_g_rr:>5.0%} | "
          f"{t_m_in:>4} {t_m_out:>4} {t_m_kap:>4} {t_m_nmt:>4} {t_m_ck:>7.0f} {t_m_rr:>5.0%} | "
          f"{t_m_nmt - t_g_nmt:>+4} {(t_m_rr - t_g_rr):>+5.0%}")

    return {
        'gercek': {'in': t_g_in, 'out': t_g_out, 'kap': t_g_kap,
                   'nmt': t_g_nmt, 'ck': t_g_ck, 'rr': t_g_rr},
        'model': {'in': t_m_in, 'out': t_m_out, 'kap': t_m_kap,
                  'nmt': t_m_nmt, 'ck': t_m_ck, 'rr': t_m_rr},
        'cagri': t_cagri, 'erlang': t_erl,
    }


def gercek_vs_model_haftalik(week_dates, gercek_per_day, df_calls,
                              cfg_weekday, weekly_results,
                              queues=('kitle', 'kurumsal', 'gold')):
    """Haftalık (Pzt-Cum) gerçek vs v7 weekly model karşılaştırması.

    Args:
        week_dates: ['YYYY-MM-DD', ...] 5 günün tarihleri
        gercek_per_day: {date_str: {queue: {shift_str: {'inhouse': N, 'outsource': N}}}}
            Eksik tarih/queue'lar 0 kabul edilir.
        df_calls: çağrı verisi
        cfg_weekday: weekly config
        weekly_results: pkl'dan yüklenen results dict
            ({queue: {'info_per_day': {day_label: info}, ...}})
        queues: bakılacak kuyruklar
    """
    df_calls_30 = prepare_calls_30(df_calls, config=cfg_weekday)
    df_erlang_orig = calculate_erlang_all(df_calls_30, config=cfg_weekday)

    # haftalık özet tablosu için biriktir
    weekly_totals = {q: {'gercek_ck': 0, 'model_ck': 0, 'cagri': 0,
                          'gercek_kap': 0, 'model_kap': 0}
                      for q in queues}

    for date_str in week_dates:
        d = pd.to_datetime(date_str)
        day_label = _date_to_day_label(date_str)
        df_calls_day = df_calls_30[df_calls_30['data_date'] == d]
        gercek_today = gercek_per_day.get(date_str, {})

        for queue in queues:
            calls_col = f"{queue}_total"
            calls_by_slot = (
                dict(zip(df_calls_day['slot_30'], df_calls_day[calls_col]))
                if calls_col in df_calls_day.columns else {}
            )

            # Gerçek vardiyalar → slot
            gercek_in, gercek_out, gercek_tot = _aggregate_shifts_to_slots(
                gercek_today.get(queue, {})
            )

            # Model çıktısı (info_per_day'den)
            q_results = weekly_results.get(queue, {})
            info_per_day = q_results.get('info_per_day', {})
            info = info_per_day.get(day_label)

            if info is None:
                # Model bu gün/queue için sonuç üretmedi (atlanmış olabilir)
                model_in = model_out = model_tot = {}
                # Erlang yine orijinal config'ten
                df_q = df_erlang_orig[(df_erlang_orig['date'] == d) &
                                       (df_erlang_orig['queue'] == queue)]
                erlang_by_slot = dict(zip(df_q['slot'], df_q['erlang_need']))
            else:
                model_in = info.get('mip_in_by_slot', {})
                model_out = info.get('mip_out_by_slot', {})
                model_tot = info.get('mip_by_slot', {})
                # Modelin fiilen çözdüğü Erlang (shrinkage fallback sonrası)
                erlang_by_slot = info.get('erlang_by_slot')
                if not erlang_by_slot:
                    df_q = df_erlang_orig[(df_erlang_orig['date'] == d) &
                                           (df_erlang_orig['queue'] == queue)]
                    erlang_by_slot = dict(zip(df_q['slot'], df_q['erlang_need']))

            # hourly_report config'i
            hr_cfg = cfg_weekday.get('queue_configs', {}).get(queue, {}).get('hourly_report', {})
            re_cfg = hr_cfg.get('rapor_etkisi', {})
            kk_cfg = hr_cfg.get('kapasite_kaybi', {})
            ca_cfg = hr_cfg.get('cagri_adedi', {})

            totals = _print_day_table(
                date_str, day_label, queue,
                calls_by_slot, erlang_by_slot,
                gercek_in, gercek_out, gercek_tot,
                model_in, model_out, model_tot,
                re_cfg, kk_cfg, ca_cfg,
            )

            weekly_totals[queue]['gercek_ck'] += totals['gercek']['ck']
            weekly_totals[queue]['model_ck'] += totals['model']['ck']
            weekly_totals[queue]['cagri'] += totals['cagri']
            weekly_totals[queue]['gercek_kap'] += totals['gercek']['kap']
            weekly_totals[queue]['model_kap'] += totals['model']['kap']

    # -----------------------------------------------------------
    # Haftalık özet
    # -----------------------------------------------------------
    print(f"\n{'='*90}")
    print(f"HAFTALIK ÖZET — {week_dates[0]} → {week_dates[-1]}")
    print(f"{'='*90}")
    print(f"  {'Queue':<10} {'Çağrı':>8} | "
          f"{'Gerçek Kap':>11} {'Gerçek Ç.K':>11} {'Gerçek RR':>10} | "
          f"{'Model Kap':>10} {'Model Ç.K':>10} {'Model RR':>9} | "
          f"{'ΔRR':>6}")
    print('-' * 90)
    for queue in queues:
        t = weekly_totals[queue]
        g_rr = t['gercek_ck'] / t['cagri'] if t['cagri'] > 0 else 0
        m_rr = t['model_ck'] / t['cagri'] if t['cagri'] > 0 else 0
        print(f"  {queue:<10} {t['cagri']:>8} | "
              f"{t['gercek_kap']:>11} {t['gercek_ck']:>11.0f} {g_rr:>9.0%} | "
              f"{t['model_kap']:>10} {t['model_ck']:>10.0f} {m_rr:>8.0%} | "
              f"{(m_rr - g_rr):>+6.0%}")


# %% [HÜCRE 5] — Haftalık model sonuçlarını pickle'dan yükle
WEEK_START = '2026-02-09'   # Pazartesi
WEEK_END = '2026-02-13'     # Cuma
PKL_FILE = f"weekly_v7_{WEEK_START}_{WEEK_END}.pkl"

with open(PKL_FILE, 'rb') as f:
    pkl = pickle.load(f)

WEEK_DATES = pkl['week_dates']
results = pkl['results']
print(f"{PKL_FILE} yüklendi: {len(WEEK_DATES)} gün, {len(results)} queue")


# %% [HÜCRE 6] — MANUEL GİRİŞ (her çalıştırmada burayı düzenle)
# Her gün için ayrı vardiya planı gir. Eksik bırakılan gün/queue için
# "gerçek=0" kabul edilir (model çıktısı yine basılır).
GERCEK_VARDIYALAR = {
    '2026-02-09': {   # Pzt
        'kitle': {
            '08:00-17:00': {'inhouse': 10, 'outsource': 5},
            '09:00-18:00': {'inhouse': 20, 'outsource': 8},
            '14:00-23:00': {'inhouse': 12, 'outsource': 6},
        },
        'kurumsal': {
            '09:00-18:00': {'inhouse': 5, 'outsource': 0},
        },
        'gold': {
            '08:00-17:00': {'inhouse': 8, 'outsource': 0},
            '14:00-23:00': {'inhouse': 6, 'outsource': 0},
        },
    },
    '2026-02-10': {   # Sal
        'kitle': {
            '09:00-18:00': {'inhouse': 22, 'outsource': 8},
        },
        'kurumsal': {},
        'gold': {},
    },
    '2026-02-11': {   # Çar
        'kitle': {},
        'kurumsal': {},
        'gold': {},
    },
    '2026-02-12': {   # Per
        'kitle': {},
        'kurumsal': {},
        'gold': {},
    },
    '2026-02-13': {   # Cum
        'kitle': {},
        'kurumsal': {},
        'gold': {},
    },
}


# %% [HÜCRE 7] — Raporu çalıştır
gercek_vs_model_haftalik(
    week_dates=WEEK_DATES,
    gercek_per_day=GERCEK_VARDIYALAR,
    df_calls=df_calls,
    cfg_weekday=CONFIG_WEEKDAY,
    weekly_results=results,
)
