# 1) Sonuç var mı?
r = results.get('2026-02-16')
print(f"results['2026-02-16'] = {r}")   # None ise hata yakalanmış

# 2) df_calls'da o tarih var mı?
import pandas as pd
d = pd.to_datetime('2026-02-16')
print(f"df_calls'da satır: {len(df_calls[df_calls['data_date'] == d])}")

# 3) Manuel tekrar koş, traceback gör
import traceback
try:
    r = run_weekday_all(df_calls, df_actual, df_shifts_dict,
                        '2026-02-16', config=CONFIG_WEEKDAY)
    print("OK")
except Exception:
    traceback.print_exc()   # tam hata stack
