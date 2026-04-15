print("min_per_shift:", CONFIG['queue_configs']['kitle']['mip']['min_per_shift'])
result = run_queue_pipeline(df_calls, df_actual, df_shifts, '2026-02-17', 'kitle', config=CONFIG)
print("V04_outsource:", result['mip_info']['assignments'].get('V04_outsource'))

df_shifts['kitle'][df_shifts['kitle']['start'] == '08:00']
