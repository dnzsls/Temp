# 1) 07:00'de kaç inhouse, kaç outsource atanmış?
info = results['kitle']['info_per_day']['Mon']
print(f"07:00 mip_in = {info['mip_in_by_slot']['07:00']}")
print(f"07:00 mip_out = {info['mip_out_by_slot']['07:00']}")
print(f"v02 (inhouse 07:00) atama: {info['assignments'].get('v02_inhouse', 0)}")
print(f"v03 (outsource 07:00) atama: {info['assignments'].get('v03_outsource', 0)}")

# 2) Time multiplier ve min override kontrol
qcfg = CONFIG_WEEKDAY['queue_configs']['kitle']
print(f"min_per_shift = {qcfg['mip']['min_per_shift']}")
print(f"min_per_shift_overrides = {qcfg['mip'].get('min_per_shift_overrides', {})}")
tm = CONFIG_WEEKDAY.get('time_cost_multipliers', {}).get('kitle',
       CONFIG_WEEKDAY['time_cost_multipliers'].get('default', {}))
print(f"inhouse 07:00 mult = {tm.get('inhouse',{}).get('07:00',1.0)}")
print(f"outsource 07:00 mult = {tm.get('outsource',{}).get('07:00',1.0)}")

# 3) 07:00 Erlang & v01 kapsama
print(f"Erlang 07:00 = {info['erlang_by_slot']['07:00']}")
print(f"v01 inhouse 00:00 atama: {info['assignments'].get('v01_inhouse', 0)}")
