'balance_penalty': {
    'enabled': True,
    'penalty_per_diff': 2.0,
    'windows': [
        {'name': 'sabah', 'start': '07:00', 'end': '11:30', 'penalty': 2.0},
        {'name': 'aksam', 'start': '12:00', 'end': '23:30', 'penalty': 2.0},
    ]
},

'cross_queue': {
    'enabled': True,
    'donors': ['gold', 'kurumsal'],
    'receiver': 'kitle',
    'transfer_ratio': 1.0,
},
