"""
Live market chart renderer - TradingView-style candlestick chart
(lightweight-charts) with the bot's trades DRAWN ON IT:
  - entry / TP / SL price lines for open positions
  - trade markers (arrows) where trades were opened/closed
  - the FINAL SETUP's planned entry/TP/SL as dashed lines
Returns a self-contained HTML string for st.components.html.
"""
import json


def chart_html(symbol, candles, positions=None, journal=None, plan=None,
               height=420, interval="5m"):
    data = [{"time": int(c["t"]), "open": c["o"], "high": c["h"],
             "low": c["l"], "close": c["c"]} for c in candles]
    vols = [{"time": int(c["t"]), "value": c["v"],
             "color": "#1c4d3a" if c["c"] >= c["o"] else "#4d1c28"}
            for c in candles]

    price_lines = []
    markers = []

    for p in (positions or []):
        if p["symbol"] != symbol:
            continue
        side_col = "#20e397" if p["side"] == "BUY" else "#ff4d67"
        price_lines += [
            {"price": p["entry"], "color": side_col, "style": 0, "width": 2,
             "title": f"{p['side']} ENTRY"},
            {"price": p["tp"], "color": "#20e397", "style": 2, "width": 1,
             "title": "TP"},
            {"price": p["sl"], "color": "#ff4d67", "style": 2, "width": 1,
             "title": "SL" + (" (BE)" if p.get("be_moved") else "")},
        ]
        markers.append({"time": int(p["opened"]), "position": "belowBar"
                        if p["side"] == "BUY" else "aboveBar",
                        "color": side_col,
                        "shape": "arrowUp" if p["side"] == "BUY" else "arrowDown",
                        "text": f"{p['side']} @{p['entry']:.6g}"})

    for t in (journal or [])[:20]:
        if t["symbol"] != symbol:
            continue
        win = t["outcome"] == "WIN"
        markers.append({"time": int(t["closed_at"]),
                        "position": "aboveBar" if t["side"] == "BUY" else "belowBar",
                        "color": "#20e397" if win else "#ff4d67",
                        "shape": "circle",
                        "text": f"{t['close_reason']} {t['pnl']:+.2f}"})
        markers.append({"time": int(t["opened_at"]),
                        "position": "belowBar" if t["side"] == "BUY" else "aboveBar",
                        "color": "#8ba3c4",
                        "shape": "arrowUp" if t["side"] == "BUY" else "arrowDown",
                        "text": f"{t['side']}"})

    if plan and plan.get("symbol") == symbol:
        price_lines += [
            {"price": plan["entry"], "color": "#f5b83d", "style": 1, "width": 1,
             "title": f"PLAN {plan['side']}"},
            {"price": plan["tp"], "color": "#20e397", "style": 1, "width": 1,
             "title": "PLAN TP"},
            {"price": plan["sl"], "color": "#ff4d67", "style": 1, "width": 1,
             "title": "PLAN SL"},
        ]

    markers.sort(key=lambda m: m["time"])

    return f"""
<!DOCTYPE html><html><head>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<style>body{{margin:0;background:#05080d}}
#wrap{{position:relative}}
#hdr{{position:absolute;z-index:5;top:8px;left:12px;font-family:monospace;
 color:#cfe1f5;font-size:13px;font-weight:700;letter-spacing:1px}}
#hdr span{{color:#51637f;font-size:10px}}</style></head>
<body><div id="wrap"><div id="hdr">{symbol} <span>· {interval} · JARVIS live chart
 · trades drawn on chart</span></div><div id="chart"></div></div>
<script>
const chart = LightweightCharts.createChart(document.getElementById('chart'), {{
  width: window.innerWidth-2, height: {height},
  layout: {{background: {{color:'#05080d'}}, textColor:'#8ba3c4',
           fontFamily:'monospace', fontSize:11}},
  grid: {{vertLines:{{color:'#0d1626'}}, horzLines:{{color:'#0d1626'}}}},
  crosshair: {{mode:0, vertLine:{{color:'#23405f'}}, horzLine:{{color:'#23405f'}}}},
  rightPriceScale: {{borderColor:'#16233c'}},
  timeScale: {{borderColor:'#16233c', timeVisible:true, secondsVisible:false}},
}});
const cs = chart.addCandlestickSeries({{
  upColor:'#20e397', downColor:'#ff4d67', borderUpColor:'#20e397',
  borderDownColor:'#ff4d67', wickUpColor:'#20e397', wickDownColor:'#ff4d67'}});
cs.setData({json.dumps(data)});
const vs = chart.addHistogramSeries({{priceScaleId:'vol',
  priceFormat:{{type:'volume'}}}});
chart.priceScale('vol').applyOptions({{scaleMargins:{{top:0.82,bottom:0}}}});
vs.setData({json.dumps(vols)});
const lines = {json.dumps(price_lines)};
for (const l of lines) {{
  cs.createPriceLine({{price:l.price, color:l.color, lineWidth:l.width,
    lineStyle:l.style, axisLabelVisible:true, title:l.title}});
}}
cs.setMarkers({json.dumps(markers)});
chart.timeScale().fitContent();
window.addEventListener('resize', () => chart.applyOptions({{width: window.innerWidth-2}}));
</script></body></html>"""
