
const PC_SMA = window.PC_SMA_COLOURS;
const PC_RANGE = {'6M': 0.5, '1Y': 1, '3Y': 3, '5Y': 5, '10Y': 10, 'Max': 100};
const PC_AUTO_IV = {'6M': 'D', '1Y': 'D', '3Y': 'W', '5Y': 'W', '10Y': 'M', 'Max': 'M'};
function pcColours() {
  const cs = getComputedStyle(document.documentElement), v = n => cs.getPropertyValue(n).trim();
  return {bg: v('--bg') || '#fff', ink: v('--ink2') || '#444', muted: v('--muted') || '#888', line: v('--line') || '#eee',
          green: v('--green'), red: v('--red'), blue: v('--blue'), price: v('--price')};
}
function pcSma(c, n) { const o = []; let s = 0; c.forEach((x, i) => { s += x; if (i >= n) s -= c[i - n]; o.push(i >= n - 1 ? s / n : null); }); return o; }
function pcRsi(c, n = 14) {
  const o = c.map(() => null); if (c.length <= n) return o;
  let ag = 0, al = 0;
  for (let i = 1; i <= n; i++) { const d = c[i] - c[i - 1]; ag += Math.max(d, 0); al += Math.max(-d, 0); }
  ag /= n; al /= n; o[n] = al === 0 ? 100 : 100 - 100 / (1 + ag / al);
  for (let i = n + 1; i < c.length; i++) { const d = c[i] - c[i - 1];
    ag = (ag * (n - 1) + Math.max(d, 0)) / n; al = (al * (n - 1) + Math.max(-d, 0)) / n; o[i] = al === 0 ? 100 : 100 - 100 / (1 + ag / al); }
  return o;
}
const pcDays = s => Date.parse(s) / 864e5;
function pcInit(box) {
  if (box.dataset.ready) return; box.dataset.ready = 1;
  const d = JSON.parse(document.getElementById(box.dataset.pc).textContent), col = pcColours(), LC = LightweightCharts;
  const base0 = d.D.length ? d.D : d.M, last = base0[base0.length - 1][4], prec = last < 1 ? 4 : last < 10 ? 3 : 2;
  const base = {autoSize: true, layout: {background: {type: 'solid', color: col.bg}, textColor: col.ink, fontSize: 11,
                fontFamily: 'Inter, -apple-system, system-ui, sans-serif'},
                grid: {vertLines: {color: col.line}, horzLines: {color: col.line}}, rightPriceScale: {borderColor: col.line, minimumWidth: 74},
                crosshair: {mode: 0}};
  const main = LC.createChart(box.querySelector('.pc-main'), {...base, timeScale: {borderColor: col.line}});
  const osc = LC.createChart(box.querySelector('.pc-rsi'), {...base, layout: {...base.layout, attributionLogo: false}, timeScale: {visible: false, borderColor: col.line}});
  const candle = main.addCandlestickSeries({upColor: col.green, downColor: col.red, borderVisible: false, wickUpColor: col.green,
    wickDownColor: col.red, priceLineColor: col.price, priceFormat: {type: 'price', precision: prec, minMove: 1 / 10 ** prec}});
  candle.priceScale().applyOptions({scaleMargins: {top: 0.06, bottom: 0.06}});
  let vol = null;   // volume: off by default, the Volume button adds it
  const volData = () => rows.map(r => ({time: r[0], value: r[5], color: r[4] >= r[1] ? col.green + '66' : col.red + '66'}));
  const toggleVol = () => { const b = box.querySelector('[data-vol]');
    if (vol) { main.removeSeries(vol); vol = null; candle.priceScale().applyOptions({scaleMargins: {top: 0.06, bottom: 0.06}}); }
    else { vol = main.addHistogramSeries({priceScaleId: 'vol', priceFormat: {type: 'volume'}, lastValueVisible: false, priceLineVisible: false});
           main.priceScale('vol').applyOptions({scaleMargins: {top: 0.84, bottom: 0}}); vol.setData(volData());
           candle.priceScale().applyOptions({scaleMargins: {top: 0.06, bottom: 0.2}}); }
    if (b) b.classList.toggle('on', !!vol); };
  const quiet = {priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false};
  const noScale = {autoscaleInfoProvider: () => null};   // averages and trend lines never stretch the price scale
  const avgLine = main.addLineSeries({color: col.ink, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false});
  const isAvg = r => r[5] === 0 && r[1] === r[2] && r[2] === r[3];   // a monthly average (long-term series), not a real bar
  const smaWidth = {20: 1, 50: 2, 200: 3};
  const smas = {}; for (const n in PC_SMA) smas[n] = main.addLineSeries({color: PC_SMA[n], lineWidth: smaWidth[n] || 1, ...quiet, ...noScale});
  const trends = d.trends.map(t => [t, main.addLineSeries({color: t.kind === 'resistance' ? '#B794F4' : '#4299E1', lineWidth: 2, ...quiet, ...noScale})]);
  const research = d.mode === 'research';
  // chart patterns drawn in the report (cup & handle, rounding bottoms): shown on their own timeframe, Patterns button
  const patCol = {cup: '#2F855A', handle: '#38A169', rim: '#22543D'};
  const pats = (d.patterns || []).map(p => [p, main.addLineSeries({color: patCol[p.kind] || '#2F855A', lineWidth: p.kind === 'rim' ? 2 : 3,
    lineStyle: p.kind === 'rim' ? LC.LineStyle.Dashed : LC.LineStyle.Solid, ...quiet, ...noScale})]);
  let showPats = true;
  const drawPatterns = () => pats.forEach(([p, s]) => {
    if (!showPats || p.tf !== iv) { s.setData([]); return; }
    const seen = new Set(), pts = [];
    p.points.forEach(([date, v]) => { const i = snap(date); if (i < 0 || seen.has(i)) return; seen.add(i); pts.push({time: rows[i][0], value: v}); });
    s.setData(pts); });   // private report: clean by default – their levels on, averages and trend lines behind a button
  const setOverlays = on => { for (const n in smas) smas[n].applyOptions({visible: on});
    trends.forEach(([, s]) => s.applyOptions({visible: on})); btn('data-ma')?.classList.toggle('on', on); };
  // buttons, all off at first: support / resistance (nearest), every level, and our value lines
  const nearest = ['support', 'resistance'].map(k => d.levels.find(l => l.kind === k)).filter(Boolean);
  let levelLines = [], valueLines = [], showValues = false, watchedLines = [], showWatched = false;
  const watchedPrices = (d.watched || []).flatMap(w => [w.lo, w.hi]);
  const btn = k => box.querySelector(`[${k}]`);
  const drawLevels = mode => {   // mode: '' (off), 'near', 'all'
    levelLines.forEach(x => candle.removePriceLine(x));
    levelLines = (mode === 'all' ? d.levels : mode === 'near' ? nearest : []).map(l => candle.createPriceLine({price: l.price,
      color: l.kind === 'support' ? col.green : col.red, lineWidth: 2, lineStyle: LC.LineStyle.Solid, axisLabelVisible: true,
      title: l.kind === 'support' ? 'Support' : 'Resistance'}));
    btn('data-sr')?.classList.toggle('on', mode === 'near'); btn('data-lv')?.classList.toggle('on', mode === 'all'); };
  btn('data-sr').onclick = () => drawLevels(btn('data-sr').classList.contains('on') ? '' : 'near');
  btn('data-lv').onclick = () => drawLevels(btn('data-lv').classList.contains('on') ? '' : 'all');
  if (!d.levels.length) { btn('data-sr').style.display = 'none'; btn('data-lv').style.display = 'none'; }
  else if (d.levels.length <= nearest.length) btn('data-lv').style.display = 'none';
  // value lines: shown on request, thick, and the price scale stretches so every one (25x too) is in view
  const valuePrices = d.values.map(v => v.price);
  candle.applyOptions({autoscaleInfoProvider: original => { const r = original();
    const tfPrices = (d.watched || []).filter(w => (({D: ['D', 'W'], W: ['D', 'W'], M: ['M']})[iv] || []).includes(w.tf || 'D')).flatMap(w => [w.lo, w.hi]);
    const extra = [...(showValues ? valuePrices : []), ...(showWatched ? tfPrices : [])];
    if (!r || !extra.length) return r;
    return {...r, priceRange: {minValue: Math.min(r.priceRange.minValue, ...extra) * 0.97,
                               maxValue: Math.max(r.priceRange.maxValue, ...extra) * 1.03}}; }});
  const toggleValues = () => { showValues = !showValues;
    valueLines.forEach(x => candle.removePriceLine(x));
    valueLines = showValues ? d.values.map(v => candle.createPriceLine({price: v.price, color: v.color, lineWidth: 3,
      lineStyle: v.solid ? LC.LineStyle.Solid : LC.LineStyle.Dashed, axisLabelVisible: true, title: v.label})) : [];
    btn('data-val').classList.toggle('on', showValues); main.timeScale().applyOptions({}); candle.applyOptions({}); };
  if (d.values.length) btn('data-val').onclick = toggleValues; else btn('data-val').style.display = 'none';
  // levels someone else is watching (plain support / resistance, zones as two lines): off at first
  const WATCH_TF = {D: ['D', 'W'], W: ['D', 'W'], M: ['M']};   // each chart shows the levels drawn on that timeframe
  const drawWatched = () => { watchedLines.forEach(x => candle.removePriceLine(x));
    const shown = (d.watched || []).filter(w => (WATCH_TF[iv] || []).includes(w.tf || 'D'));
    watchedLines = showWatched ? shown.flatMap(w => {
      const c = research ? (w.kind === 'support' ? '#1E6B3A' : '#9B2C2C') : (w.kind === 'support' ? '#2C9C94' : '#DD6B20');
      const t = w.kind === 'support' ? 'support' : 'resistance';
      return (w.hi - w.lo > 1e-9 ? [w.lo, w.hi] : [w.lo]).map(p => candle.createPriceLine({price: p, color: c, lineWidth: research ? 2 : 2,
        lineStyle: research ? LC.LineStyle.Solid : LC.LineStyle.LargeDashed, axisLabelVisible: true, title: t})); }) : [];
    candle.applyOptions({}); };
  const toggleWatched = () => { showWatched = !showWatched; btn('data-wl').classList.toggle('on', showWatched); drawWatched(); };
  if (watchedPrices.length) btn('data-wl').onclick = toggleWatched; else btn('data-wl').style.display = 'none';
  const rsi = osc.addLineSeries({color: col.blue, lineWidth: 1, priceLineVisible: false, lastValueVisible: true,
    autoscaleInfoProvider: () => ({priceRange: {minValue: 0, maxValue: 100}})});
  osc.applyOptions({watermark: {visible: true, text: 'RSI(14)', fontSize: 11, color: col.muted, horzAlign: 'left', vertAlign: 'top'}});
  rsi.createPriceLine({price: 70, color: col.red, lineWidth: 1, lineStyle: LC.LineStyle.Dashed, axisLabelVisible: false, title: '70'});
  rsi.createPriceLine({price: 30, color: col.green, lineWidth: 1, lineStyle: LC.LineStyle.Dashed, axisLabelVisible: false, title: '30'});
  let syncing = false;
  const link = (a, b) => a.timeScale().subscribeVisibleLogicalRangeChange(r => { if (!r || syncing) return; syncing = true;
    b.timeScale().setVisibleLogicalRange(r); syncing = false; });
  link(main, osc); link(osc, main);
  const legend = box.querySelector('.pc-legend'), fmt = x => x == null ? '–' : x.toLocaleString(undefined, {maximumFractionDigits: prec});
  const vfmt = x => x >= 1e9 ? (x / 1e9).toFixed(2) + 'B' : x >= 1e6 ? (x / 1e6).toFixed(2) + 'M' : x >= 1e3 ? (x / 1e3).toFixed(0) + 'K' : x;
  let rows = [], iv = 'D', range = '1Y';
  const show = r => { if (!r) return; const i = rows.findIndex(x => x[0] === r[0]), prev = i > 0 ? rows[i - 1][4] : r[1];
    const ch = (r[4] / prev - 1) * 100;
    legend.innerHTML = `<b>${r[0]}</b> O <b>${fmt(r[1])}</b> H <b>${fmt(r[2])}</b> L <b>${fmt(r[3])}</b> C <b>${fmt(r[4])}</b> ` +
      `<span class="${ch >= 0 ? 'pos' : 'neg'}">${ch >= 0 ? '+' : ''}${ch.toFixed(2)}%</span> Vol <b>${vfmt(r[5])}</b>`; };
  main.subscribeCrosshairMove(p => { const b = p.time ? rows.find(x => x[0] === p.time) : null; show(b || rows[rows.length - 1]); });
  const snap = date => { const i = rows.findIndex(x => x[0] >= date); return i < 0 ? -1 : i; };
  function setIv(next) {
    iv = next; rows = d[iv]; const c = rows.map(r => r[4]);
    candle.setData(rows.map(r => isAvg(r) ? {time: r[0]} : {time: r[0], open: r[1], high: r[2], low: r[3], close: r[4]}));
    const avg = rows.map((r, i) => isAvg(r) || (i > 0 && isAvg(rows[i - 1])) ? {time: r[0], value: r[4]} : {time: r[0]});
    avgLine.setData(avg);
    for (const n in PC_SMA) { const s = pcSma(c, +n); smas[n].setData(rows.map((r, i) => s[i] == null ? {time: r[0]} : {time: r[0], value: s[i]})); }
    if (vol) vol.setData(volData());
    const rs = pcRsi(c); rsi.setData(rows.map((r, i) => rs[i] == null ? {time: r[0]} : {time: r[0], value: rs[i]}));
    trends.forEach(([t, s]) => { const i0 = snap(t.from[0]), i1 = rows.length - 1;
      if (i0 < 0 || i0 >= i1) { s.setData([]); return; }
      const slope = (t.to[1] - t.from[1]) / Math.max(pcDays(t.to[0]) - pcDays(t.from[0]), 1);
      const at = date => t.from[1] + slope * (pcDays(date) - pcDays(t.from[0]));
      s.setData([{time: rows[i0][0], value: at(rows[i0][0])}, {time: rows[i1][0], value: at(rows[i1][0])}]); });
    const seen = new Set(), marks = [];
    d.markers.forEach(m => { const i = snap(m.date); if (i < 0) return; const key = rows[i][0] + m.kind; if (seen.has(key)) return; seen.add(key);
      marks.push({time: rows[i][0], position: m.kind === 'E' ? 'aboveBar' : 'belowBar', shape: m.kind === 'E' ? 'square' : 'circle',
                  color: m.kind === 'E' ? col.blue : m.kind === 'S' ? col.red : col.muted, text: m.kind}); });
    candle.setMarkers(marks.sort((a, b) => a.time < b.time ? -1 : 1));
    box.querySelectorAll('[data-iv]').forEach(b => b.classList.toggle('on', b.dataset.iv === iv));
    candle.priceScale().applyOptions({mode: iv === 'M' ? 1 : 0});   // monthly = log scale, like long-term charts
    if (showWatched) drawWatched();
    drawPatterns();
    show(rows[rows.length - 1]);
  }
  function setRange(next) {
    range = next; const end = rows[rows.length - 1][0], from = new Date(Date.parse(end) - PC_RANGE[range] * 365.25 * 864e5).toISOString().slice(0, 10);
    if (from <= rows[0][0]) main.timeScale().fitContent(); else main.timeScale().setVisibleRange({from, to: end});
    box.querySelectorAll('[data-rg]').forEach(b => b.classList.toggle('on', b.dataset.rg === range));
  }
  box.querySelectorAll('[data-iv]').forEach(b => b.onclick = () => { setIv(b.dataset.iv); setRange(range); });
  box.querySelectorAll('[data-rg]').forEach(b => b.onclick = () => { if (PC_AUTO_IV[b.dataset.rg] !== iv) setIv(PC_AUTO_IV[b.dataset.rg]); setRange(b.dataset.rg); });
  const vb = box.querySelector('[data-vol]'); if (vb) vb.onclick = toggleVol;
  const mab = btn('data-ma'); if (mab) mab.onclick = () => setOverlays(!mab.classList.contains('on'));
  const pb = btn('data-pat');
  if (pb) { if (!pats.length) pb.style.display = 'none'; else { pb.classList.add('on');
    pb.onclick = () => { showPats = !showPats; pb.classList.toggle('on', showPats); drawPatterns(); }; } }
  if (!d.D.length) { box.querySelectorAll('[data-iv=D],[data-iv=W],[data-rg="6M"],[data-rg="1Y"],[data-rg="3Y"]').forEach(b => b.style.display = 'none');
    setIv('M'); setRange('Max'); } else { setIv('D'); setRange('1Y'); }
  if (research) { setOverlays(false); if (watchedPrices.length) toggleWatched(); } else if (mab) mab.style.display = 'none';
}
if (window.LightweightCharts) {
  const io = 'IntersectionObserver' in window ? new IntersectionObserver(es => es.forEach(x => { if (x.isIntersecting) { pcInit(x.target); io.unobserve(x.target); } }),
                                                                           {rootMargin: '300px'}) : null;
  document.querySelectorAll('.pc').forEach(b => io ? io.observe(b) : pcInit(b));
}
