"""Pure order-planning logic (stdlib only, easy to test)."""


def plan_order(target_long, held, price, usdt_free, max_usdt, min_amount=0.0, min_cost=0.0):
    """Return (action, amount_in_base, reason). Dust below the exchange minimum counts as flat."""
    in_position = held >= max(min_amount, 1e-12)
    if target_long and not in_position:
        notional = min(max_usdt, usdt_free)
        amount = notional / price
        if amount < min_amount or notional < min_cost or notional <= 0:
            return "hold", 0.0, "可用资金不足以满足最小下单量"
        return "buy", amount, "信号为多头，当前空仓"
    if not target_long and in_position:
        return "sell", held, "信号为空，当前持仓"
    return "hold", 0.0, "仓位已与信号一致"
