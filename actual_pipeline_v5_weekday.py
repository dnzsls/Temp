# 1) Hangi shift'ler 07:00'i kapsıyor?
queue = 'kitle'
shift_cov = results[queue]['info_per_day']['Mon']['shift_coverage']
for s, sc in shift_cov.items():
    if '07:00' in sc['slots']:
        print(f"  {s:<32} start={sc['start']} company={sc['company']}")

# 2) 07:00 başlangıçlı shift'lerin etkin maliyetleri
mcfg = CONFIG_WEEKDAY['queue_configs'][queue]['mip']
tm = CONFIG_WEEKDAY.get('time_cost_multipliers', {}).get(queue,
       CONFIG_WEEKDAY['time_cost_multipliers'].get('default', {}))
print(f"\ninhouse  07:00 maliyet: {mcfg['cost_inhouse']} × {tm.get('inhouse',{}).get('07:00',1.0)}"
      f" = {mcfg['cost_inhouse']*tm.get('inhouse',{}).get('07:00',1.0):.2f}")
print(f"outsource 07:00 maliyet: {mcfg['cost_outsource']} × {tm.get('outsource',{}).get('07:00',1.0)}"
      f" = {mcfg['cost_outsource']*tm.get('outsource',{}).get('07:00',1.0):.2f}")

# 3) Pzt 07:00'de Erlang ne kadar?
print(f"\nErlang Mon 07:00 = {results[queue]['info_per_day']['Mon']['erlang_by_slot'].get('07:00', 0)}")
