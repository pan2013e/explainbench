def register_handlers():
    try:
        import pandas as pd
        from jsonpickle.ext import pandas as jp
        from jsonpickle.handlers import register
        register(pd.DataFrame, jp.PandasDfHandler, base=True)
        register(pd.Series, jp.PandasSeriesHandler, base=True)
        register(pd.Index, jp.PandasIndexHandler, base=True)
        register(pd.PeriodIndex, jp.PandasPeriodIndexHandler, base=True)
        register(pd.MultiIndex, jp.PandasMultiIndexHandler, base=True)
        register(pd.Timestamp, jp.PandasTimestampHandler, base=True)
        register(pd.Period, jp.PandasPeriodHandler, base=True)
        register(pd.Interval, jp.PandasIntervalHandler, base=True)
        return [
            pd.DataFrame, pd.Series, pd.Index, pd.PeriodIndex,
            pd.MultiIndex, pd.Timestamp, pd.Period, pd.Interval,
        ]
    except ImportError:
        return []