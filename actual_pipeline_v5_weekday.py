print(CONFIG_WEEKDAY['queue_configs']['kitle']['slot_cap'])
mi = results['2026-02-09']['kitle']['mip_info']
print("slot_cap_detail satır:", len(mi.get('slot_cap_detail', [])))
print("sc_excess_by_slot satır:", len(mi.get('sc_excess_by_slot', {})))
print(mi.get('slot_cap_detail', [])[:3])
