/**
 * QuantTrading 前端应用逻辑
 * - K线图表渲染与多周期切换
 * - WebSocket 实时数据接收
 * - 盘口深度更新
 * - 技术指标叠加
 * - 交易面板交互
 * - 策略参数配置
 * - 底部数据表格加载
 */

const API_BASE = window.location.origin.replace(/:\d+$/, ':8000');
const WS_BASE = API_BASE.replace('http', 'ws');

// 全局状态
const state = {
    instId: 'BTC-USDT',
    bar: '1H',
    simulated: true,
    chart: null,
    candleSeries: null,
    volumeSeries: null,
    indicatorSeries: [],
    activeIndicators: [],
    wsMarket: null,
    wsTrade: null,
    indicators: [],
};

// ==================== K线图表 ====================

function initChart() {
    const chartContainer = document.getElementById('klineChart');
    state.chart = LightweightCharts.createChart(chartContainer, {
        layout: { background: { color: '#0d1117' }, textColor: '#8b949e' },
        grid: { vertLines: { color: '#1c2128' }, horzLines: { color: '#1c2128' } },
        timeScale: { borderColor: '#30363d', timeVisible: true, secondsVisible: false },
        priceScale: { borderColor: '#30363d' },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    });

    state.candleSeries = state.chart.addCandlestickSeries({
        upColor: '#2ea043', downColor: '#f85149',
        borderUpColor: '#2ea043', borderDownColor: '#f85149',
        wickUpColor: '#2ea043', wickDownColor: '#f85149',
    });

    state.volumeSeries = state.chart.addHistogramSeries({
        priceFormat: { type: 'volume' }, priceScaleId: 'volume',
    });
    state.chart.priceScale('volume').applyOptions({
        scaleMargins: { top: 0.8, bottom: 0 },
    });

    const resizeObserver = new ResizeObserver(() => {
        state.chart.applyOptions({ width: chartContainer.clientWidth, height: chartContainer.clientHeight });
    });
    resizeObserver.observe(chartContainer);
}

async function loadKlines() {
    try {
        const resp = await fetch(`${API_BASE}/api/klines/${state.instId}?bar=${state.bar}&limit=300`);
        const json = await resp.json();
        if (json.code === 0 && json.data.length > 0) {
            const candles = json.data.reverse().map(k => ({
                time: Math.floor(parseFloat(k[0]) / 1000),
                open: parseFloat(k[1]), high: parseFloat(k[2]),
                low: parseFloat(k[3]), close: parseFloat(k[4]),
            }));
            state.candleSeries.setData(candles);

            const volumes = json.data.reverse().map(k => ({
                time: Math.floor(parseFloat(k[0]) / 1000),
                value: parseFloat(k[5]),
                color: parseFloat(k[4]) >= parseFloat(k[1]) ? 'rgba(46,160,67,0.4)' : 'rgba(248,81,73,0.4)',
            }));
            state.volumeSeries.setData(volumes);

            updateTickerInfo(json.data[json.data.length - 1]);
        }
    } catch (e) { console.error('Load klines failed:', e); }
}

function updateTickerInfo(kline) {
    const el = document.getElementById('tickerInfo');
    const open = parseFloat(kline[1]);
    const close = parseFloat(kline[4]);
    const change = ((close - open) / open * 100).toFixed(2);
    const cls = close >= open ? 'price-up' : 'price-down';
    el.innerHTML = `${state.instId} <span class="${cls}">${close} (${change >= 0 ? '+' : ''}${change}%)</span>`;
}

// ==================== 盘口深度 ====================

async function loadOrderbook() {
    try {
        const resp = await fetch(`${API_BASE}/api/orderbook/${state.instId}?depth=5`);
        const json = await resp.json();
        if (json.code === 0 && json.data) {
            renderOrderbook(json.data);
        }
    } catch (e) { console.error('Load orderbook failed:', e); }
}

function renderOrderbook(data) {
    const asksEl = document.getElementById('asksList');
    const bidsEl = document.getElementById('bidsList');
    const midEl = document.getElementById('midPrice');

    if (data.asks) {
        asksEl.innerHTML = data.asks.slice(0, 8).reverse().map(a =>
            `<div class="ask-row"><span class="price">${parseFloat(a[0]).toFixed(2)}</span><span>${parseFloat(a[1]).toFixed(4)}</span><span>${(parseFloat(a[0]) * parseFloat(a[1])).toFixed(2)}</span></div>`
        ).join('');
    }
    if (data.bids) {
        bidsEl.innerHTML = data.bids.slice(0, 8).map(b =>
            `<div class="bid-row"><span class="price">${parseFloat(b[0]).toFixed(2)}</span><span>${parseFloat(b[1]).toFixed(4)}</span><span>${(parseFloat(b[0]) * parseFloat(b[1])).toFixed(2)}</span></div>`
        ).join('');
    }
    if (data.asks && data.asks.length > 0 && data.bids && data.bids.length > 0) {
        const mid = (parseFloat(data.asks[0][0]) + parseFloat(data.bids[0][0])) / 2;
        midEl.textContent = mid.toFixed(2);
    }
}

// ==================== WebSocket 实时数据 ====================

function connectMarketWS() {
    if (state.wsMarket) state.wsMarket.close();
    state.wsMarket = new WebSocket(`${WS_BASE}/ws/market?inst_id=${state.instId}`);
    state.wsMarket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.arg && data.data) {
            handleWSData(data);
        }
    };
    state.wsMarket.onclose = () => { setTimeout(connectMarketWS, 3000); };
}

function handleWSData(msg) {
    const channel = msg.arg?.channel;
    const d = msg.data[0];
    if (!d) return;

    if (channel && channel.startsWith('candle')) {
        const time = Math.floor(parseFloat(d[0]) / 1000);
        state.candleSeries.update({
            time, open: parseFloat(d[1]), high: parseFloat(d[2]),
            low: parseFloat(d[3]), close: parseFloat(d[4]),
        });
    } else if (channel === 'books5') {
        renderOrderbook(d);
    } else if (channel === 'tickers') {
        const el = document.getElementById('tickerInfo');
        const last = parseFloat(d.last);
        const open = parseFloat(d.open24h);
        const change = ((last - open) / open * 100).toFixed(2);
        const cls = last >= open ? 'price-up' : 'price-down';
        el.innerHTML = `${state.instId} <span class="${cls}">${last} (${change >= 0 ? '+' : ''}${change}%)</span>`;
    }
}

// ==================== 技术指标 ====================

async function loadIndicators() {
    try {
        const resp = await fetch(`${API_BASE}/api/indicators`);
        const json = await resp.json();
        if (json.code === 0) {
            state.indicators = json.data;
            renderIndicatorList();
            document.getElementById('indicatorCategories').textContent = `共 ${json.count} 个指标`;
        }
    } catch (e) { console.error('Load indicators failed:', e); }
}

function renderIndicatorList(filter = '') {
    const listEl = document.getElementById('indicatorList');
    const filtered = state.indicators.filter(i =>
        i.name.toLowerCase().includes(filter.toLowerCase())
    );
    listEl.innerHTML = filtered.slice(0, 100).map(i =>
        `<div class="indicator-item ${state.activeIndicators.includes(i.name) ? 'active' : ''}" data-name="${i.name}">
            <span>${i.name}</span><span class="cat-tag">${i.category}</span>
        </div>`
    ).join('');

    listEl.querySelectorAll('.indicator-item').forEach(item => {
        item.onclick = () => toggleIndicator(item.dataset.name);
    });
}

async function toggleIndicator(name) {
    if (state.activeIndicators.includes(name)) {
        state.activeIndicators = state.activeIndicators.filter(n => n !== name);
    } else {
        state.activeIndicators.push(name);
        await calculateAndOverlay(name);
    }
    renderIndicatorList(document.getElementById('indicatorSearch').value);
}

async function calculateAndOverlay(name) {
    try {
        const resp = await fetch(`${API_BASE}/api/indicators/calculate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ inst_id: state.instId, bar: state.bar, indicators: [name], limit: 300 }),
        });
        const json = await resp.json();
        if (json.code === 0 && json.data.length > 0) {
            const colName = Object.keys(json.data[0]).find(k =>
                k.startsWith(name) && k !== 'ts' && k !== 'open' && k !== 'high' && k !== 'low' && k !== 'close'
            );
            if (colName) {
                const lineSeries = state.chart.addLineSeries({ color: getRandomColor(), lineWidth: 1 });
                const data = json.data.filter(d => d[colName] !== '').map(d => ({
                    time: Math.floor(new Date(d.ts).getTime() / 1000),
                    value: parseFloat(d[colName]),
                }));
                lineSeries.setData(data);
                state.indicatorSeries.push({ name, series: lineSeries });
            }
        }
    } catch (e) { console.error('Calculate indicator failed:', e); }
}

function getRandomColor() {
    const colors = ['#58a6ff', '#bc8cff', '#d29922', '#2ea043', '#f778ba', '#79c0ff'];
    return colors[Math.floor(Math.random() * colors.length)];
}

// ==================== 交易数据表格 ====================

async function loadPendingOrders() {
    try {
        const resp = await fetch(`${API_BASE}/api/orders/pending?inst_type=SPOT`);
        const json = await resp.json();
        const body = document.getElementById('pendingBody');
        if (json.code === 0 && json.data.length > 0) {
            body.innerHTML = json.data.map(o =>
                `<tr><td>${fmtTime(o.cTime)}</td><td>${o.instId}</td><td class="${o.side === 'buy' ? 'price-up' : 'price-down'}">${o.side}</td><td>${o.ordType}</td><td>${o.px}</td><td>${o.sz}</td><td>${o.fillSz || '0'}</td><td>${o.state}</td><td><button onclick="cancelOrder('${o.instId}','${o.ordId}')">撤单</button></td></tr>`
            ).join('');
        } else { body.innerHTML = '<tr><td colspan="9" style="text-align:center;color:#8b949e">暂无挂单</td></tr>'; }
    } catch (e) { console.error('Load pending failed:', e); }
}

async function loadOrderHistory() {
    try {
        const resp = await fetch(`${API_BASE}/api/orders/history?inst_type=SPOT&limit=50`);
        const json = await resp.json();
        const body = document.getElementById('historyBody');
        if (json.code === 0 && json.data.length > 0) {
            body.innerHTML = json.data.map(o =>
                `<tr><td>${fmtTime(o.cTime)}</td><td>${o.instId}</td><td class="${o.side === 'buy' ? 'price-up' : 'price-down'}">${o.side}</td><td>${o.ordType}</td><td>${o.px}</td><td>${o.sz}</td><td>${o.fillSz || '0'}</td><td>${o.avgPx || '--'}</td><td>${o.state}</td></tr>`
            ).join('');
        } else { body.innerHTML = '<tr><td colspan="9" style="text-align:center;color:#8b949e">暂无历史委托</td></tr>'; }
    } catch (e) { console.error('Load history failed:', e); }
}

async function loadFills() {
    try {
        const resp = await fetch(`${API_BASE}/api/fills?inst_type=SPOT&limit=50`);
        const json = await resp.json();
        const body = document.getElementById('fillsBody');
        if (json.code === 0 && json.data.length > 0) {
            body.innerHTML = json.data.map(f =>
                `<tr><td>${fmtTime(f.ts)}</td><td>${f.instId}</td><td class="${f.side === 'buy' ? 'price-up' : 'price-down'}">${f.side}</td><td>${f.fillPx}</td><td>${f.fillSz}</td><td>${f.fee} ${f.feeCcy}</td><td>${f.tradeId}</td></tr>`
            ).join('');
        } else { body.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#8b949e">暂无成交明细</td></tr>'; }
    } catch (e) { console.error('Load fills failed:', e); }
}

async function loadBills() {
    try {
        const resp = await fetch(`${API_BASE}/api/bills?limit=50`);
        const json = await resp.json();
        const body = document.getElementById('billsBody');
        if (json.code === 0 && json.data.length > 0) {
            body.innerHTML = json.data.map(b =>
                `<tr><td>${fmtTime(b.ts)}</td><td>${b.type}</td><td>${b.ccy}</td><td class="${parseFloat(b.balChg) >= 0 ? 'price-up' : 'price-down'}">${b.balChg}</td><td>${b.bal}</td><td>${b.billId}</td></tr>`
            ).join('');
        } else { body.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#8b949e">暂无账单流水</td></tr>'; }
    } catch (e) { console.error('Load bills failed:', e); }
}

function fmtTime(ts) {
    if (!ts) return '--';
    return new Date(parseInt(ts)).toLocaleString('zh-CN', { hour12: false });
}

// ==================== 策略参数配置 ====================

const strategyParamsConfig = {
    ma_cross: [{ key: 'fast', label: '快线周期', default: 5 }, { key: 'slow', label: '慢线周期', default: 20 }],
    rsi_oversold: [{ key: 'period', label: 'RSI周期', default: 14 }, { key: 'threshold', label: '超卖阈值', default: 30 }],
    bbands_break: [{ key: 'length', label: '布林带周期', default: 20 }, { key: 'std', label: '标准差', default: 2.0 }],
    macd_divergence: [{ key: 'fast', label: '快线', default: 12 }, { key: 'slow', label: '慢线', default: 26 }, { key: 'signal', label: '信号线', default: 9 }],
};

function renderStrategyParams() {
    const strategy = document.getElementById('strategySelect').value;
    const params = strategyParamsConfig[strategy] || [];
    const container = document.getElementById('strategyParams');
    container.innerHTML = params.map(p =>
        `<div class="param-row"><label>${p.label}</label><input type="number" class="control-input" id="param_${p.key}" value="${p.default}" step="0.1"></div>`
    ).join('');
}

// ==================== 事件绑定 ====================

function bindEvents() {
    // 产品切换
    document.getElementById('instIdSelect').onchange = (e) => {
        state.instId = e.target.value;
        loadKlines(); loadOrderbook();
        if (state.wsMarket) { state.wsMarket.close(); connectMarketWS(); }
    };

    // 周期切换
    document.querySelectorAll('.period-btn').forEach(btn => {
        btn.onclick = () => {
            document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.bar = btn.dataset.bar;
            loadKlines();
        };
    });

    // 模拟/实盘切换
    document.getElementById('simModeBtn').onclick = () => {
        state.simulated = true;
        document.getElementById('simModeBtn').classList.add('active');
        document.getElementById('liveModeBtn').classList.remove('active');
    };
    document.getElementById('liveModeBtn').onclick = () => {
        state.simulated = false;
        document.getElementById('liveModeBtn').classList.add('active');
        document.getElementById('simModeBtn').classList.remove('active');
    };

    // 指标面板
    document.getElementById('addIndicatorBtn').onclick = () => {
        document.getElementById('indicatorPanel').classList.toggle('hidden');
    };
    document.getElementById('indicatorSearch').oninput = (e) => {
        renderIndicatorList(e.target.value);
    };

    // 交易面板
    document.getElementById('buyBtn').onclick = () => {
        document.getElementById('buyBtn').classList.add('active');
        document.getElementById('sellBtn').classList.remove('active');
    };
    document.getElementById('sellBtn').onclick = () => {
        document.getElementById('sellBtn').classList.add('active');
        document.getElementById('buyBtn').classList.remove('active');
    };

    // 底部 Tab 切换
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.onclick = () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-pane').forEach(p => p.classList.add('hidden'));
            btn.classList.add('active');
            document.getElementById(btn.dataset.tab + 'Tab').classList.remove('hidden');
            if (btn.dataset.tab === 'pending') loadPendingOrders();
            else if (btn.dataset.tab === 'history') loadOrderHistory();
            else if (btn.dataset.tab === 'fills') loadFills();
            else if (btn.dataset.tab === 'bills') loadBills();
        };
    });

    // 策略选择
    document.getElementById('strategySelect').onchange = renderStrategyParams;
}

// ==================== 初始化 ====================

async function init() {
    initChart();
    bindEvents();
    renderStrategyParams();
    await loadKlines();
    await loadOrderbook();
    await loadIndicators();
    await loadPendingOrders();
    connectMarketWS();

    // 定时刷新
    setInterval(loadOrderbook, 5000);
    setInterval(loadPendingOrders, 10000);
}

window.onload = init;
