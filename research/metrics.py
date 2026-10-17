"""Pure helpers for the strategy search (no vectorbt/optuna, so CI stays light)."""
import math


def sharpe(returns, periods_per_year):
    sd = returns.std(ddof=1)
    if len(returns) < 3 or not sd or sd != sd:
        return 0.0
    return float(returns.mean() / sd * math.sqrt(periods_per_year))


def hurdle(oos_years, n_families, floor=0.5):
    """Sharpe needed to beat the luckiest of n random strategies.

    Approximation: the standard error of an annualised Sharpe is about
    1/sqrt(years); the expected best of n noise strategies is about
    sqrt(2*ln(n)) standard errors (Bailey & Lopez de Prado style).
    """
    if oos_years <= 0:
        return math.inf
    return max(floor, math.sqrt(2 * math.log(max(n_families, 1))) / math.sqrt(oos_years))
