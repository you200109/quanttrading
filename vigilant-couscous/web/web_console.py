"""
自进化交易系统 - Web 图形界面控制台

零依赖: 使用 Python 内置 HTTP 服务, 前端用浏览器原生图表
访问: http://localhost:8765
"""
import contextlib
import json
import sys
import threading
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# 全局状态
trading_paused = False
evolution_running = False
_state_lock = threading.Lock()

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

PORT = 8765


# ==================== API 实现 ====================
def api_status():
    import config
    vf = config.NEXUS_DIR / "version.json"
    version = "?"
    if vf.exists():
        with contextlib.suppress(Exception):
            version = json.loads(vf.read_text(encoding="utf-8")).get("version", "?")
    deps = []
    for m, label in [("crewai", "多Agent"), ("torch", "深度学习"), ("ccxt", "交易所"), ("pandas", "数据处理")]:
        try:
            __import__(m); deps.append({"name": label, "ok": True})
        except ImportError:
            deps.append({"name": label, "ok": False})
    lib = 0
    lf = config.NEXUS_DIR / "gh_strategy_library.json"
    if lf.exists():
        with contextlib.suppress(Exception):
            lib = json.loads(lf.read_text(encoding="utf-8")).get("total_strategies", 0)
    return {
        "version": version,
        "symbols": config.SYMBOLS,
        "risk_threshold": config.RISK["min_confidence"],
        "deps": deps,
        "strategy_count": lib,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def api_cache():
    try:
        from data.cache_manager import MarketDataCache
        return MarketDataCache().get_status()
    except Exception as e:
        return {"error": str(e)[:150]}


def api_library():
    import config
    lf = config.NEXUS_DIR / "gh_strategy_library.json"
    if not lf.exists():
        return {"strategies": [], "total": 0}
    data = json.loads(lf.read_text(encoding="utf-8"))
    strats = data.get("strategies", [])[:20]
    return {"total": data.get("total_strategies", 0), "strategies": strats}


def api_analyze():
    import config
    from agents.researcher import ResearcherAgent
    from data.fetcher import DataFetcher
    fetcher = DataFetcher(okx_url=config.DATA_SOURCE["okx_url"])
    researcher = ResearcherAgent(verbose=False)
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    results = []
    for symbol in config.SYMBOLS:
        data = fetcher.fetch(symbol, start_date=start, end_date=end, source='ccxt')
        if data.empty:
            results.append({"symbol": symbol, "error": "数据获取失败"})
            continue
        r = researcher.analyze(symbol, data)
        s = r['signals']
        results.append({
            "symbol": symbol,
            "price": round(float(data['close'].iloc[-1]), 2),
            "trend": r['trend'],
            "recommendation": r['recommendation'],
            "confidence": r['confidence'],
            "indicators": s.get('total_indicators', 0),
            "rsi": s.get('rsi_14'),
            "adx": s.get('adx'),
            "macd": round(s.get('macd_12_26_hist', 0), 2),
            "prices": [round(float(v), 2) for v in data['close'].values[-90:]],
            "dates": [d.strftime('%m-%d') for d in data.index[-90:]],
        })
    return {"results": results, "time": datetime.now().strftime("%H:%M:%S")}


def api_trade():
    try:
        from auto_trade import AutoTradingSystem
        sys_ = AutoTradingSystem()
        sys_.run_once()
        summary = sys_.trader.get_portfolio_summary()
        return {"ok": True, "total_value": round(summary['total_value'], 2),
                "return": round(summary['total_return'], 4),
                "positions": summary['position_count'], "trades": len(sys_.trade_log)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:150]}


def api_evolve():
    global evolution_running
    with _state_lock:
        if evolution_running:
            return {"ok": False, "error": "进化任务正在运行中"}
        evolution_running = True
    try:
        import unified_evolve
        unified_evolve.cmd_once(generations=150, population=30)
        import config
        rf = config.NEXUS_DIR / "evolve_result.json"
        if rf.exists():
            return {"ok": True, **json.loads(rf.read_text(encoding="utf-8"))}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:150]}
    finally:
        with _state_lock:
            evolution_running = False


def api_dashboard():
    """实时仪表盘数据"""
    import config
    result = {
        "timestamp": datetime.now().isoformat(),
        "trading_paused": trading_paused,
        "evolution_running": evolution_running,
        "version": "?",
        "symbols": config.SYMBOLS,
        "risk": config.RISK,
    }
    vf = config.NEXUS_DIR / "version.json"
    if vf.exists():
        with contextlib.suppress(Exception):
            result["version"] = json.loads(vf.read_text(encoding="utf-8")).get("version", "?")
    lf = config.NEXUS_DIR / "gh_strategy_library.json"
    if lf.exists():
        try:
            lib = json.loads(lf.read_text(encoding="utf-8"))
            result["strategy_count"] = lib.get("total_strategies", len(lib) if isinstance(lib, list) else 0)
        except Exception:
            result["strategy_count"] = 0
    ef = config.NEXUS_DIR / "evolve_result.json"
    if ef.exists():
        with contextlib.suppress(Exception):
            result["last_evolve"] = json.loads(ef.read_text(encoding="utf-8"))
    return result


def api_evolution_status():
    """进化过程状态"""
    import config
    status = {"evolution_running": evolution_running}
    vf = config.NEXUS_DIR / "version.json"
    if vf.exists():
        with contextlib.suppress(Exception):
            status["version_info"] = json.loads(vf.read_text(encoding="utf-8"))
    ef = config.NEXUS_DIR / "evolve_result.json"
    if ef.exists():
        with contextlib.suppress(Exception):
            status["last_result"] = json.loads(ef.read_text(encoding="utf-8"))
    lf = config.NEXUS_DIR / "gh_strategy_library.json"
    if lf.exists():
        try:
            lib = json.loads(lf.read_text(encoding="utf-8"))
            status["strategy_count"] = lib.get("total_strategies", len(lib) if isinstance(lib, list) else 0)
        except Exception:
            status["strategy_count"] = 0
    return status


def api_pause():
    global trading_paused
    trading_paused = True
    return {"ok": True, "message": "交易已暂停", "trading_paused": True}


def api_resume():
    global trading_paused
    trading_paused = False
    return {"ok": True, "message": "交易已恢复", "trading_paused": False}


def api_alerts():
    """告警历史查询"""
    alert_dir = Path("reports/alerts")
    alerts = []
    if alert_dir.exists():
        for f in sorted(alert_dir.glob("alerts_*.jsonl"), reverse=True)[:3]:
            for line in f.read_text(encoding="utf-8").strip().split("\n")[-50:]:
                if line:
                    with contextlib.suppress(Exception):
                        alerts.append(json.loads(line))
    return {"alerts": alerts[-50:], "total": len(alerts)}


def api_backtest(body: str = ""):
    """策略回测验证"""
    import config
    from data.fetcher import DataFetcher
    from evolution.backtest_validator import BacktestValidator
    params = json.loads(body) if body else {}
    symbol = params.get("symbol", "BTC/USDT")
    strategy_params = params.get("strategy", {
        "rsi_period": 14, "sma_fast": 5, "sma_slow": 20,
        "stop_loss": 0.05, "take_profit": 0.15,
        "rsi_oversold": 30, "rsi_overbought": 70,
    })
    fetcher = DataFetcher(okx_url=config.DATA_SOURCE["okx_url"])
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    data = fetcher.fetch(symbol, start_date=start, end_date=end, source='ccxt')
    if data.empty:
        return {"error": f"{symbol} 数据获取失败"}
    validator = BacktestValidator(data)
    result = validator.validate_strategy(strategy_params, strategy_params.get("name", "web_test"))
    rolling = validator.rolling_window_validation(strategy_params)
    monte_carlo = validator.monte_carlo_simulation(strategy_params)
    return {
        "backtest": {
            "total_return": result.total_return, "annual_return": result.annual_return,
            "sharpe_ratio": result.sharpe_ratio, "max_drawdown": result.max_drawdown,
            "win_rate": result.win_rate, "total_trades": result.total_trades,
            "profit_factor": result.profit_factor, "passed": result.passed,
            "score": result.score, "warnings": result.warnings,
        },
        "rolling_validation": rolling,
        "monte_carlo": monte_carlo,
    }


def api_multi_timeframe(query: str = ""):
    """多时间框架分析"""
    import config
    from agents.multi_timeframe import MultiTimeframeAnalyzer
    from data.fetcher import DataFetcher
    params = parse_qs(query)
    symbol = params.get("symbol", ["BTC/USDT"])[0]
    fetcher = DataFetcher(okx_url=config.DATA_SOURCE["okx_url"])
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    data = fetcher.fetch(symbol, start_date=start, end_date=end, source='ccxt')
    if data.empty:
        return {"error": f"{symbol} 数据获取失败"}
    analyzer = MultiTimeframeAnalyzer(data, symbol)
    result = analyzer.analyze()
    recommendation = analyzer.get_trade_recommendation(result)
    signal_matrix = analyzer.get_signal_matrix(result)
    return {
        "symbol": symbol, "resonance_score": result.resonance_score,
        "consensus_trend": result.consensus_trend, "confidence": result.confidence,
        "entry_zones": result.entry_zones, "exit_zones": result.exit_zones,
        "divergence_warnings": result.divergence_warnings,
        "recommendation": recommendation,
        "signal_matrix": signal_matrix.to_dict("records"),
    }


# ==================== HTTP 处理 ====================
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, obj, code=200, ctype="application/json; charset=utf-8"):
        body = obj.encode("utf-8") if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path in ("/", "/index.html"):
                self._send(INDEX_HTML, ctype="text/html; charset=utf-8")
            elif path == "/api/status":
                self._send(api_status())
            elif path == "/api/cache":
                self._send(api_cache())
            elif path == "/api/library":
                self._send(api_library())
            elif path == "/api/analyze":
                self._send(api_analyze())
            elif path == "/api/dashboard":
                self._send(api_dashboard())
            elif path == "/api/evolution/status":
                self._send(api_evolution_status())
            elif path == "/api/alerts":
                self._send(api_alerts())
            elif path == "/api/multi-timeframe":
                self._send(api_multi_timeframe(urlparse(self.path).query))
            else:
                self._send({"error": "not found"}, 404)
        except Exception as e:
            self._send({"error": str(e)[:200]}, 500)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/trade":
                self._send(api_trade())
            elif path == "/api/evolve":
                self._send(api_evolve())
            elif path == "/api/control/pause":
                self._send(api_pause())
            elif path == "/api/control/resume":
                self._send(api_resume())
            elif path == "/api/backtest":
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8") if length > 0 else ""
                self._send(api_backtest(body))
            else:
                self._send({"error": "not found"}, 404)
        except Exception as e:
            self._send({"error": str(e)[:200]}, 500)


INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>自进化交易系统 - 控制台</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0d1117;color:#c9d1d9;padding:20px}
.header{text-align:center;padding:20px;border-bottom:1px solid #30363d;margin-bottom:24px}
.header h1{font-size:24px;color:#58a6ff;margin-bottom:6px}
.header p{color:#8b949e;font-size:13px}
.toolbar{display:flex;gap:10px;flex-wrap:wrap;justify-content:center;margin-bottom:24px}
button{background:#238636;color:#fff;border:none;padding:10px 20px;border-radius:6px;cursor:pointer;font-size:14px;transition:.2s}
button:hover{background:#2ea043}
button.blue{background:#1f6feb}button.blue:hover{background:#388bfd}
button.purple{background:#8957e5}button.purple:hover{background:#a371f7}
button:disabled{background:#30363d;cursor:not-allowed}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;margin-bottom:24px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:18px}
.card h2{font-size:15px;color:#58a6ff;margin-bottom:14px;padding-bottom:10px;border-bottom:1px solid #30363d}
.metrics{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}
.metric{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:12px;text-align:center}
.metric .v{font-size:20px;font-weight:bold;color:#58a6ff}
.metric .l{font-size:11px;color:#8b949e;margin-top:4px}
.chart-box{position:relative;height:260px}
.result{margin-top:14px;padding:12px;background:#0d1117;border-radius:6px;border-left:3px solid #58a6ff;font-size:13px;line-height:1.8;max-height:300px;overflow-y:auto;white-space:pre-wrap}
.sig{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #21262d}
.sig:last-child{border-bottom:none}
.buy{color:#3fb950;font-weight:bold}
.sell{color:#f85149;font-weight:bold}
.hold{color:#d29922;font-weight:bold}
.dep{display:inline-block;margin:3px 6px 3px 0;padding:3px 10px;border-radius:12px;font-size:12px}
.dep.ok{background:#1a3a24;color:#3fb950}
.dep.no{background:#3a1a1a;color:#f85149}
#loading{display:none;text-align:center;padding:20px;color:#58a6ff}
</style>
</head>
<body>
<div class="header">
  <h1>🧬 自进化交易系统 - 控制台</h1>
  <p id="subtitle">加载中...</p>
</div>

<div class="toolbar">
  <button class="blue" onclick="runAnalyze()">📊 分析行情</button>
  <button onclick="runTrade()">💰 执行交易</button>
  <button class="purple" onclick="runEvolve()">🧬 进化优化</button>
  <button class="blue" onclick="loadAll()">🔄 刷新</button>
</div>

<div id="loading">处理中，请稍候...</div>

<div class="grid">
  <div class="card">
    <h2>系统状态</h2>
    <div class="metrics" id="statusMetrics"></div>
    <div style="margin-top:12px" id="deps"></div>
  </div>
  <div class="card">
    <h2>行情缓存</h2>
    <div class="metrics" id="cacheMetrics"></div>
    <div class="result" id="cacheDetail" style="margin-top:12px">-</div>
  </div>
</div>

<div class="grid">
  <div class="card" style="grid-column:1/-1">
    <h2>行情走势与信号</h2>
    <div class="chart-box"><canvas id="priceChart"></canvas></div>
    <div id="signals" style="margin-top:14px"></div>
  </div>
</div>

<div class="card">
  <h2>策略知识库</h2>
  <div id="library"></div>
</div>

<script>
let chart=null;

function fmt(n){return n==null?'-':Number(n).toLocaleString()}

async function get(url){const r=await fetch(url);return await r.json()}
async function post(url){const r=await fetch(url,{method:'POST'});return await r.json()}

async function loadStatus(){
  const d=await get('/api/status');
  document.getElementById('subtitle').textContent=`版本 ${d.version} | 币种 ${d.symbols.join(', ')} | 风控阈值 ${d.risk_threshold} | ${d.time}`;
  document.getElementById('statusMetrics').innerHTML=`
    <div class="metric"><div class="v">${d.version}</div><div class="l">系统版本</div></div>
    <div class="metric"><div class="v">${d.strategy_count}</div><div class="l">策略数量</div></div>
    <div class="metric"><div class="v">${d.symbols.length}</div><div class="l">监控币种</div></div>
    <div class="metric"><div class="v">${d.risk_threshold}</div><div class="l">风控阈值</div></div>`;
  document.getElementById('deps').innerHTML=d.deps.map(x=>`<span class="dep ${x.ok?'ok':'no'}">${x.ok?'✓':'✗'} ${x.name}</span>`).join('');
}

async function loadCache(){
  const d=await get('/api/cache');
  if(d.error){document.getElementById('cacheDetail').textContent=d.error;return}
  document.getElementById('cacheMetrics').innerHTML=`
    <div class="metric"><div class="v">${d.symbols||0}</div><div class="l">缓存交易对</div></div>
    <div class="metric"><div class="v">${fmt(d.total_rows)}</div><div class="l">缓存总条数</div></div>
    <div class="metric"><div class="v">${(d.fresh_ttl/60).toFixed(0)}分</div><div class="l">新鲜TTL</div></div>
    <div class="metric"><div class="v">${(d.stale_ttl/3600).toFixed(0)}时</div><div class="l">陈旧TTL</div></div>`;
  const det=d.details||{};
  document.getElementById('cacheDetail').textContent=Object.entries(det).map(([s,v])=>`${s}: ${fmt(v.rows)} 条  ${(v.first_ts||'').slice(0,10)} ~ ${(v.last_ts||'').slice(0,10)}`).join('\n')||'暂无缓存';
}

async function loadLibrary(){
  const d=await get('/api/library');
  const rows=(d.strategies||[]).map(s=>`<div class="sig"><span>${s.name}</span><span style="color:#8b949e">RSI${s.rsi_period} SMA(${s.sma_fast}/${s.sma_slow}) SL${(s.stop_loss*100).toFixed(0)}%</span></div>`).join('');
  document.getElementById('library').innerHTML=`<div style="margin-bottom:10px;color:#8b949e;font-size:13px">共 ${d.total} 个策略</div>${rows}`;
}

async function runAnalyze(){
  document.getElementById('loading').style.display='block';
  try{
    const d=await get('/api/analyze');
    const res=d.results||[];
    let sigHtml='';
    const datasets=[];
    const colors=['#58a6ff','#3fb950','#f0883e'];
    res.forEach((r,i)=>{
      if(r.error){sigHtml+=`<div class="sig"><span>${r.symbol}</span><span class="hold">${r.error}</span></div>`;return}
      const cls=r.recommendation.includes('买')?'buy':(r.recommendation.includes('卖')?'sell':'hold');
      sigHtml+=`<div class="sig"><span><b>${r.symbol}</b> $${fmt(r.price)}</span><span>${r.trend} | <span class="${cls}">${r.recommendation}</span> | 置信度 ${(r.confidence*100).toFixed(0)}% | 指标 ${r.indicators} | RSI ${r.rsi} | ADX ${r.adx}</span></div>`;
      datasets.push({label:r.symbol,data:r.prices,borderColor:colors[i%3],backgroundColor:'transparent',tension:.3,pointRadius:0});
    });
    document.getElementById('signals').innerHTML=sigHtml;
    if(res[0]&&res[0].dates){
      if(chart)chart.destroy();
      chart=new Chart(document.getElementById('priceChart'),{type:'line',data:{labels:res[0].dates,datasets:datasets},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{color:'#c9d1d9'}}},scales:{x:{ticks:{color:'#8b949e',maxTicksLimit:10}},y:{ticks:{color:'#8b949e'}}}}});
    }
  }finally{document.getElementById('loading').style.display='none'}
}

async function runTrade(){
  document.getElementById('loading').style.display='block';
  try{
    const d=await post('/api/trade');
    document.getElementById('signals').innerHTML=`<div class="result">交易执行结果:\n${JSON.stringify(d,null,2)}</div>`;
    await loadStatus();await loadCache();
  }finally{document.getElementById('loading').style.display='none'}
}

async function runEvolve(){
  document.getElementById('loading').style.display='block';
  document.getElementById('loading').textContent='进化优化中（150代），请稍候...';
  try{
    const d=await post('/api/evolve');
    document.getElementById('signals').innerHTML=`<div class="result">进化结果:\n${JSON.stringify(d,null,2)}</div>`;
    await loadStatus();await loadLibrary();
  }finally{document.getElementById('loading').style.display='none';document.getElementById('loading').textContent='处理中，请稍候...'}
}

function loadAll(){loadStatus();loadCache();loadLibrary()}
loadAll();
</script>
</body>
</html>"""


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("=" * 56)
    print("  自进化交易系统 - Web 图形界面控制台")
    print(f"  访问地址: http://localhost:{PORT}")
    print("  按 Ctrl+C 停止服务")
    print("=" * 56)
    threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
        server.shutdown()


if __name__ == "__main__":
    main()
