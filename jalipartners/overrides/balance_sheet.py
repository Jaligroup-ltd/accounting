# jalipartners/jalipartners/overrides/balance_sheet.py
import erpnext.accounts.report.balance_sheet.balance_sheet as std_bs

if not getattr(std_bs, "_jali_original_execute", None):
    std_bs._jali_original_execute = std_bs.execute

    def _jali_execute(filters=None):
        result = std_bs._jali_original_execute(filters)
        columns = result[0]
        if not columns:
            return result

        leading, periods, trailing = [], [], []
        for col in columns:
            fieldname = col.get("fieldname")
            if fieldname in ("account", "account_name", "currency"):
                leading.append(col)          # Account + hidden currency stay first
            elif fieldname == "total":
                trailing.append(col)         # "Total" column (non-yearly) stays last
            else:
                periods.append(col)          # the fiscal-year columns

        periods.reverse()                    # 2026, 2025, 2024
        return (leading + periods + trailing,) + tuple(result[1:])

    std_bs.execute = _jali_execute