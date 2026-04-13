if LpStatus[prob.status] != 'Optimal':
    # --- INFEASIBILITY DEBUG ---
    print(f"\n🔍 INFEASIBILITY ANALİZİ:")
    
    # Her kısıt grubunu teker teker kaldırıp dene
    constraint_groups = {
        'erlang_coverage': [],
        'inhouse_min': [],
        'outsource_min': [],
        'kadro_inhouse': [],
        'kadro_outsource': [],
        'min_per_shift': [],
        'slot_cap': [],
    }
    
    for name, c in prob.constraints.items():
        if 'erlang' in name.lower() or name.startswith('_C') and 'coverage' in str(c):
            constraint_groups['erlang_coverage'].append(name)
        # vs...
    
    # Daha pratik yol: kısıtları sırayla kaldır
    all_constraints = list(prob.constraints.keys())
    print(f"   Toplam kısıt: {len(all_constraints)}")
    
    # Outsource kadro kısıtını bul ve kaldırıp dene
    test_prob = prob.copy()
    for name in list(test_prob.constraints.keys()):
        if 'kadro' in name.lower() or 'out_kadro' in name.lower():
            del test_prob.constraints[name]
            print(f"   Kaldırıldı: {name}")
    
    test_prob.solve(PULP_CBC_CMD(msg=0))
    print(f"   Kadro kısıtları olmadan: {LpStatus[test_prob.status]}")
