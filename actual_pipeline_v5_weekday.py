continue
            starts_by_hour = {}
            for s in comp_shifts:
                st = shift_cov[s]['start']
                if sm_start <= st < sm_end:
                    starts_by_hour.setdefault(st, []).append(s)
            sorted_hours = sorted(starts_by_hour.keys())
            if len(sorted_hours) < 2:
                continue

            # >>> DEBUG: smoothing hangi saatlerde kuruluyor
            print(f"   🟰 [smoothing] {queue}/{comp}: aralık=[{sm_start},{sm_end}) "
                  f"→ kapsanan saatler ({len(sorted_hours)} adet): {sorted_hours}")
            # <

            yh = {}
            for h in sorted_hours:
                yh[h] = LpVariable(f"yh_{comp}_{h.replace(':', '')}", cat='Binary')
                for s in starts_by_hour[h]:
                    prob += yh[h] >= y[s]
