# V3: Overflow ayarları
'overflow': {
    'donors': ['gold', 'kurumsal'],   # fazlalığını kitleye veren kuyruklar
    'receiver': 'kitle',               # overflow alan kuyruk
},


from actual_pipeline_v3_weekday import *

results = run_all_queues(df_calls, df_actual, df_shifts_dict, '2025-02-17', config=CONFIG)
