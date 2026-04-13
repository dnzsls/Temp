from actual_pipeline_v2_weekday import *

target_date = pd.to_datetime('2025-02-17')
queue = 'kitle'

df_calls_30 = prepare_calls_30(df_calls, CONFIG)
df_erlang = calculate_erlang_all(df_calls_30, CONFIG)
df_erlang_day = df_erlang[(df_erlang['date'] == target_date) & (df_erlang['queue'] == queue)]
erlang_by_slot = dict(zip(df_erlang_day['slot'], df_erlang_day['erlang_need']))

inhouse_min_by_slot, outsource_min_by_slot = _build_subqueue_min_slots(
    df_calls_30, queue, target_date, erlang_by_slot, CONFIG
)

# Analiz
for slot in sorted(erlang_by_slot.keys()):
    e = erlang_by_slot.get(slot, 0)
    i = inhouse_min_by_slot.get(slot, 0)
    o = outsource_min_by_slot.get(slot, 0)
    if e > 0:
        print(f"{slot}: erlang={e:>4}, in_min={i:>4}, out_min={o:>4}, toplam={i+o:>4}, oran={((i+o)/e):>6.1%}")
