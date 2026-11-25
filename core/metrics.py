"""Performance stats. Same functions are used for backtests and live results."""
import numpy as np
import pandas as pd

TD = 252

CRISES = {
    "GFC (2008)": ("2008-01-01", "2009-03-09"),
    "Euro crisis (2011)": ("2011-07-01", "2011-10-03"),
    "Taper/oil (2015-16)": ("2015-08-01", "2016-02-11"),
    "Q4 2018 selloff": ("2018-10-01", "2018-12-24"),
    "COVID crash (2020)": ("2020-02-19", "2020-03-23"),
    "2022 rates shock": ("2022-01-01", "2022-10-12"),
}


def drawdown(equity: pd.Series) -> pd.Series:
    return equity / equity.cummax() - 1


def summary(equity: pd.Series, bench: pd.Series = None) -> dict:
    r = equity.pct_change().dropna()
    years = len(r) / TD
    cagr = equity.iloc[-1] ** (1 / years) - 1 if years > 0 else np.nan
    vol = r.std() * np.sqrt(TD)
    downside = r[r < 0].std() * np.sqrt(TD)
    dd = drawdown(equity)
    out = {
        "CAGR": cagr,
        "Volatility": vol,
        "Sharpe": r.mean() / r.std() * np.sqrt(TD) if r.std() > 0 else np.nan,
        "Sortino": r.mean() * TD / downside if downside > 0 else np.nan,
        "Max drawdown": dd.min(),
        "Calmar": cagr / abs(dd.min()) if dd.min() < 0 else np.nan,
        "% positive months": (equity.resample("ME").last().pct_change().dropna() > 0).mean(),
        "Best year": equity.resample("YE").last().pct_change().max(),
        "Worst year": equity.resample("YE").last().pct_change().min(),
    }
    if bench is not None:
        br = bench.pct_change().reindex(r.index)
        out["Correlation to benchmark"] = r.corr(br)
    return out


def yearly(equity: pd.Series) -> pd.Series:
    y = equity.resample("YE").last()
    y = pd.concat([pd.Series([equity.iloc[0]], index=[equity.index[0]]), y])
    out = y.pct_change().dropna()
    out.index = out.index.year
    return out[~out.index.duplicated(keep="last")]


def crisis_table(curves: dict) -> pd.DataFrame:
    rows = {}
    for name, (a, b) in CRISES.items():
        row = {}
        for label, eq in curves.items():
            seg = eq.loc[a:b]
            row[label] = seg.iloc[-1] / seg.iloc[0] - 1 if len(seg) > 5 else np.nan
        rows[name] = row
    return pd.DataFrame(rows).T
