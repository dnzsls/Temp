for q in ['kitle', 'kurumsal', 'gold']:
    mps = CONFIG['queue_configs'][q]['mip']['min_per_shift']
    asg = results[q]['mip_info']['assignments']
    kucuk = {s: c for s, c in asg.items() if 0 < c < mps}
    if kucuk:
        print(f"{q} (min={mps}): {kucuk}")
