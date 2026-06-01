'total_kadro': {
    'kitle': {
        'inhouse': {
            # Bu spesifik tarih TÜM diğer kuralları geçer
            '2026-02-09': 420,   # 2. hafta Pzt için kampanya, ekstra 20
            # Diğer Pzt'ler için fallback
            'Mon': 400,
            'Fri': 390,
            'default': 380,
        },
        'outsource': {
            '2026-02-09': 480,   # aynı gün outsource da artsın
            'Mon': 460,
            'default': 450,
        },
    },
    'kurumsal': {'inhouse': 47},
    'gold':     {'inhouse': 130},
},
