result = run_all_queues(df_calls, df_actual, df_shifts, '<tarih>', config=CONFIG)
kitle_mip = result['kitle']['mip_info']

for d in kitle_mip.get('slot_cap_detail', []):
    if d['slot'] == '09:00':
        print(d)
