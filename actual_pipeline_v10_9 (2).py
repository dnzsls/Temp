# Outsource shift'leri ve kapsamları
scol = CONFIG['shift_columns']
ccfg = CONFIG['company']
outsource_value = ccfg['outsource']['shift_value']
allowed = CONFIG['queues']['kitle']['companies']
allowed_values = [ccfg[c]['shift_value'] for c in allowed]

df_sf = df_shifts_dict['kitle'][df_shifts_dict['kitle'][scol['company']].isin(allowed_values)]
shift_cov = create_shift_coverage(df_sf, CONFIG)

out_shifts = [s for s in shift_cov if shift_cov[s]['company'] == outsource_value]

print(f"Outsource shift sayısı: {len(out_shifts)}")
for s in sorted(out_shifts, key=lambda s: shift_cov[s]['start']):
    print(f"  {s}: {shift_cov[s]['start']}-{shift_cov[s]['end']} ({len(shift_cov[s]['slots'])} slot)")

# outsource_min olan ama hiç outsource shift kapsamında olmayan slotlar
for slot in sorted(outsource_min_by_slot.keys()):
    if outsource_min_by_slot[slot] <= 0:
        continue
    covering = [s for s in out_shifts if slot in shift_cov[s]['slots']]
    if not covering:
        print(f"⚠ {slot}: out_min={outsource_min_by_slot[slot]} ama kapsayan outsource shift YOK!")
