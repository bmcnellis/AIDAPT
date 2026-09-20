import pandas as pd


def season_year(date_value, start_month, end_month):
    dt = pd.Timestamp(date_value)

    if start_month <= end_month:
        return dt.year if start_month <= dt.month <= end_month else None

    if dt.month >= start_month:
        return dt.year
    if dt.month <= end_month:
        return dt.year - 1
    return None
