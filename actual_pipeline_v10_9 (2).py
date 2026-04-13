# En kötü slot
worst = max(erlang_by_slot.keys(), 
            key=lambda s: (inhouse_min_by_slot.get(s,0) + outsource_min_by_slot.get(s,0)) / max(erlang_by_slot.get(s,1),1))
e = erlang_by_slot[worst]
i = inhouse_min_by_slot.get(worst, 0)
o = outsource_min_by_slot.get(worst, 0)
print(f"En kötü slot: {worst}, erlang={e}, in_min={i}, out_min={o}, oran={(i+o)/e:.2%}")
