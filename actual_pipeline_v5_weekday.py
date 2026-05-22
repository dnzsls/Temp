# Tanı: results dict gerçekte ne içeriyor?
print(f"Toplam gün: {len(results)}")
print(f"None günler: {sum(1 for r in results.values() if r is None)}")

# Hafta içi örnek
print("\n--- Haftaiçi örnek ---")
for d in sorted(results.keys()):
    r = results[d]
    if r is None:
        continue
    if pd.to_datetime(d).weekday() < 5:
        print(f"{d}: keys = {list(r.keys())}")
        for q in ('kitle', 'kurumsal', 'gold'):
            v = r.get(q)
            if v is None:
                print(f"   {q}: NONE ⚠")
            else:
                mi = v.get('mip_info', {})
                print(f"   {q}: in={mi.get('total_inhouse_kisi')}, out={mi.get('total_outsource_kisi')}, sf={mi.get('total_shortfall', 0)}, stage={mi.get('solution_stage')}")
        break

# Haftasonu örnek
print("\n--- Haftasonu örnek ---")
for d in sorted(results.keys()):
    r = results[d]
    if r is None:
        continue
    if pd.to_datetime(d).weekday() >= 5:
        print(f"{d}: keys = {list(r.keys())}")
        for q in ('kitle', 'kurumsal', 'gold'):
            v = r.get(q)
            if v is None:
                print(f"   {q}: NONE ⚠")
            else:
                # weekend pipeline'ın yapısı farklı olabilir
                if 'mip_info' in v:
                    mi = v['mip_info']
                    print(f"   {q}: in={mi.get('total_inhouse_kisi')}, out={mi.get('total_outsource_kisi')}")
                else:
                    print(f"   {q}: keys = {list(v.keys())}  (mip_info YOK ⚠)")
        break
