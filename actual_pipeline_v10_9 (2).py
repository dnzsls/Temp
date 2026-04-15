results = run_all_queues(df_calls, df_actual, df_shifts, '2026-02-17', config=CONFIG)

print("min_per_shift:", CONFIG['queue_configs']['kitle']['mip']['min_per_shift'])
print("V04_outsource:", results['kitle']['mip_info']['assignments'].get('V04_outsource'))

# Catalog'da V04 kaç satır?
print(df_shifts['kitle'][df_shifts['kitle']['start'] == '08:00'])
