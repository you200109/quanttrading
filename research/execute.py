"""Daily executor for the OKX *demo* account. Sandbox only: there is no live path.

Acts only when the lifecycle stage is 'approved' (a human set APPROVED_PARAMS) and
KILL_SWITCH is off. EXECUTE=1 is required to place orders; otherwise it only
prints what it would do. Run with TIMEFRAME=1d BARS=600.
"""
import os
from datetime import datetime, timezone

import ccxt

from agent_utils import create_issue, issue_titles
from lifecycle import load_state
from nightly import PAGES_URL, SYMBOL, fetch_close
from search import backtest
from strategy import decode
from trading import plan_order


def target_is_long(close, tf_s, strategy_id):
    name, params = decode(strategy_id)
    return bool(backtest(close, tf_s, name, params, 0).assets().iloc[-1] > 0)


def main():
    if os.getenv("KILL_SWITCH") == "1":
        return print("总开关已关闭，不下单")
    state = load_state(PAGES_URL)
    approved = os.getenv("APPROVED_PARAMS", "").strip()
    if state["stage"] != "approved" or not approved or state["frozen"] != approved:
        return print(f"当前阶段是 {state['stage']}，没有人工批准的策略，不下单")

    close, tf_s = fetch_close()
    want_long = target_is_long(close, tf_s, state["frozen"])
    print(f"策略 {state['frozen']} 在最近一根已收盘K线的目标：{'持有' if want_long else '空仓'}")

    key = os.getenv("OKX_DEMO_KEY")
    if not key:
        return print("未配置模拟盘 Key，只输出信号，不连接交易所")
    ex = ccxt.okx({"apiKey": key, "secret": os.environ["OKX_DEMO_SECRET"],
                   "password": os.environ["OKX_DEMO_PASSPHRASE"], "enableRateLimit": True})
    ex.set_sandbox_mode(True)  # the only mode this script ever uses
    ex.load_markets()
    m = ex.market(SYMBOL)
    bal = ex.fetch_balance()
    held = float((bal.get(m["base"]) or {}).get("total") or 0)
    usdt = float((bal.get(m["quote"]) or {}).get("free") or 0)
    last = float(ex.fetch_ticker(SYMBOL)["last"])
    if abs(last / float(close.iloc[-1]) - 1) > 0.15:
        return print("最新价与K线收盘价相差超过 15%，数据异常，不下单")

    action, amount, why = plan_order(
        want_long, held, last, usdt, float(os.getenv("MAX_USDT") or "1000"),
        float((m["limits"]["amount"] or {}).get("min") or 0),
        float((m["limits"]["cost"] or {}).get("min") or 0))
    print(f"持仓 {held} {m['base']}，可用 {usdt} {m['quote']}，决定：{action}（{why}）")
    if action == "hold":
        return
    amount = float(ex.amount_to_precision(SYMBOL, amount))
    if os.getenv("EXECUTE") != "1":
        return print(f"预演：会市价{action} {amount} {m['base']}。设置变量 EXECUTE=1 才会真正下模拟盘单")

    order = ex.create_order(SYMBOL, "market", action, amount, last if action == "buy" else None)
    print("已下模拟盘单：", order.get("id"))
    if os.getenv("GITHUB_TOKEN"):
        title = f"[下单] {datetime.now(timezone.utc):%Y-%m-%d} {action} {SYMBOL}（模拟盘）"
        body = (f"- 策略：{state['frozen']}\n- 动作：市价{action} {amount} {m['base']}，参考价 {last}\n"
                f"- 原因：{why}\n- 订单号：{order.get('id')}\n\n> 仅模拟盘，没有真实资金。")
        try:
            if title not in issue_titles():
                create_issue(title, body, ["execution"])
        except Exception as e:
            print("issue failed:", e)


if __name__ == "__main__":
    main()
