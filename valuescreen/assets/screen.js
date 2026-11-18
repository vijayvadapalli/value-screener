// The growth screen's settings panel (lists with `screen_panel: true`, and the US screen page). The page carries every
// screen row as JSON (<script id="screen-data">) and the default rules (<script id="screen-rules">); this recomputes
// the tiers in the browser exactly as growth_screen.py does – expected_return() and judge() – for the values you set
// with the sliders, keeps them in the address (…?pe=20&growth=15#screen), and draws a funnel. With a backtest on the
// page (<script id="bt-data">, html_report.backtest_data) it re-picks every start date with the same settings and
// redoes the averages (backtestAll). What the server wrote stays untouched until a setting differs from the defaults,
// so the page reads the same without JavaScript.

const SCREEN_KEYS = ['pe', 'growth', 'ret', 'years', 'exit', 'promoters', 'prule', 'psu', 'mid', 'cyc', 'all'];
const SCREEN_PCT = new Set(['growth', 'ret', 'promoters']);   // shown and typed as %, stored as fractions
const SCREEN_BOOL = new Set(['prule', 'psu', 'mid', 'cyc', 'all']);

function expectedReturn(eps, nc, price, growth, s) {
  // growth_screen.expected_return
  if (eps === null || eps <= 0 || growth === null || !price) return [null, null];
  const assumed = Math.min(Math.max(growth, 0) * s.haircut, s.cap);
  const future = eps * Math.pow(1 + assumed, s.years) * s.exit + (nc || 0);
  return [future > 0 ? Math.pow(future / price, 1 / s.years) - 1 : null, assumed];
}

function judgeRow(r, s) {
  // growth_screen.judge, plus the panel's own rules (promoters, government-owned, Midcap 150 only, cyclicals)
  const growth = (r.c5 !== null && r.c3 !== null) ? Math.min(r.c5, r.c3) : null;
  const [ret, assumed] = expectedReturn(r.eps, r.nc, r.price, growth, s);
  const guards = r.guards.slice();
  if (s.prule && (r.promoters === null || r.promoters < s.promoters))
    guards.push(r.promoters === null ? 'no promoter holding' : `promoters ${(r.promoters * 100).toFixed(0)}% (< ${(s.promoters * 100).toFixed(0)}%)`);
  if (s.psu && r.state_owned) guards.push('government-owned');
  const checks = {
    pe: r.pe !== null && r.pe <= s.pe,
    growth: r.pos && growth !== null && growth >= s.growth,
    return: ret !== null && ret >= s.ret,
  };
  const missed = Object.keys(checks).filter(k => !checks[k]);
  // the near-miss bounds: as configured at the default rules, shifted with them otherwise (no float drift at defaults)
  const nearPeBound = s.pe === s.pe0 ? s.near_pe : s.pe + (s.near_pe - s.pe0);
  const nearGrowthBound = s.growth === s.growth0 ? s.near_growth : s.growth - (s.growth0 - s.near_growth);
  const nearPe = r.pe !== null && r.pe <= nearPeBound;
  const nearGrowth = r.pos && growth !== null && growth >= nearGrowthBound;
  let tier = '';
  if (guards.length) tier = '';
  else if (!missed.length) tier = 'shortlist';
  else if ((checks.pe && checks.growth) || (checks.growth && nearPe) || (checks.pe && nearGrowth)) tier = 'near miss';
  return {tier, missed, guards, ret, assumed, growth, checks};
}

function inUniverse(r, s) {
  return !(s.mid && r.extra) && !(s.cyc && r.cyclical);
}

function screenAll(rows, s) {
  // every row judged, best first: shortlist, near misses, then by expected return (growth_screen.sort_key)
  const order = {'shortlist': 0, 'near miss': 1, '': 2};
  return rows.filter(r => inUniverse(r, s)).map(r => Object.assign({}, r, judgeRow(r, s)))
    .sort((a, b) => (order[a.tier] - order[b.tier]) || ((b.ret === null ? -9 : b.ret) - (a.ret === null ? -9 : a.ret)));
}

function funnel(rows, s) {
  // start N → after guards → + growth → + P/E → + 5-yr return (→ + promoters → + government-owned rule, when on)
  let left = rows.filter(r => inUniverse(r, s));
  const steps = [['Start', left.length]];
  const keep = (label, test) => { left = left.filter(test); steps.push([label, left.length]); };
  const j = new Map(left.map(r => [r.ticker, judgeRow(r, Object.assign({}, s, {prule: false, psu: false}))]));
  keep('after guards', r => !j.get(r.ticker).guards.length);
  keep('+ growth', r => j.get(r.ticker).checks.growth);
  keep('+ P/E', r => j.get(r.ticker).checks.pe);
  keep('+ 5-yr return', r => j.get(r.ticker).checks.return);
  // India only, and only when switched on: US companies have no promoter group or government-owned rule
  if (s.market !== 'us' && s.prule) keep('+ promoters', r => r.promoters !== null && r.promoters >= s.promoters);
  if (s.market !== 'us' && s.psu) keep('+ government-owned rule', r => !r.state_owned);
  return steps;
}

const FUNNEL_WORDS = {   // html_report.FUNNEL_WORDS
  'after guards': 'have clean books and a profit every year', '+ growth': 'grew fast enough', '+ P/E': 'are cheap enough',
  '+ 5-yr return': 'promise enough return', '+ promoters': 'have enough promoter holding',
  '+ government-owned rule': 'are not government-owned',
};

function funnelText(steps) {
  // html_report.funnel_text: the funnel as one sentence
  const [n0, rest] = [steps[0][1], steps.slice(1)];
  const parts = rest.map(([label, n], i) => `<b>${n}</b> ${i ? 'of those ' : ''}${FUNNEL_WORDS[label]}`);
  const body = parts.slice(0, -1).join(', ') + (parts.length > 1 ? ', and ' : '') + parts[parts.length - 1];
  return `Of <b>${n0}</b> companies, ${body} – the shortlist.`;
}

function shortOf(r) {
  // html_report._short_of: what a near miss falls short on, with its figure
  return r.missed.map(m => m === 'pe' ? (r.pe === null ? 'no P/E' : `P/E ${r.pe.toFixed(1)}`)
    : m === 'growth' ? (r.growth === null ? 'growth unknown' : `growth ${(r.growth * 100).toFixed(0)}%`)
    : (r.ret === null ? 'no return' : `return ${(r.ret * 100).toFixed(0)}% a year`)).join(', ');
}

function andList(xs) {
  return xs.length === 1 ? xs[0] : xs.slice(0, -1).join(', ') + ' and ' + xs[xs.length - 1];
}

function mean(xs) {
  const v = xs.filter(x => x !== null && x !== undefined);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}

function backtestAll(bt, s) {
  // backtest.py with the panel's settings: on each start date the stocks that could pass (no guard, a P/E and the
  // growth then) are judged again – stocks one year short of 5-year history hold a year less, as in backtest.run_start
  // – and the picks' average, best and worst redone; all screened (less the cyclicals if excluded) and the index stay.
  // The promoter rule applies where the holding then is known (the files keep 8 quarters): an unknown holding is not
  // a reason to leave a stock out years ago.
  const order = (a, b) => (b.ret === null ? -9 : b.ret) - (a.ret === null ? -9 : a.ret);
  return bt.starts.map(b => {
    const picks = b.rows.filter(r => !(s.cyc && r.cyc)).map(r => {
      const j = judgeRow({pe: r.pe, c5: r.c5, c3: r.c3, pos: true, guards: [], promoters: r.prom === undefined ? null : r.prom,
                          state_owned: !!r.so, eps: r.eps, nc: r.nc || 0, price: r.price},
                         Object.assign({}, s, {prule: s.prule && r.prom !== undefined}, r.short ? {years: s.years - 1} : {}));
      return Object.assign({}, r, {tier: j.tier, er: j.ret});
    }).filter(r => r.tier === 'shortlist').sort(order);
    return {label: b.label, years: b.years, picks, picks_ret: mean(picks.map(r => r.ret)),
            screened: s.cyc ? b.n_nocyc : b.n, all: s.cyc ? b.all_nocyc : b.all, median: s.cyc ? b.median_nocyc : b.median,
            index: b.index, best: picks[0] || null, worst: picks.length > 1 ? picks[picks.length - 1] : null,
            note: b.note};
  });
}

function readSettings(search, defaults) {
  const s = Object.assign({}, defaults), q = new URLSearchParams(search);
  for (const k of SCREEN_KEYS) {
    if (!q.has(k)) continue;
    const v = q.get(k);
    if (SCREEN_BOOL.has(k)) s[k] = v === '1';
    else if (v !== '' && !isNaN(+v)) {
      const x = SCREEN_PCT.has(k) ? +v / 100 : +v, b = (defaults.bounds || {})[k];   // kept within the sliders' range
      s[k] = b ? Math.min(Math.max(x, b[0]), b[1]) : x;
    }
  }
  return s;
}

function writeSettings(s, defaults) {
  const q = new URLSearchParams();
  for (const k of SCREEN_KEYS) {
    if (s[k] === defaults[k]) continue;
    q.set(k, SCREEN_BOOL.has(k) ? (s[k] ? '1' : '0') : String(SCREEN_PCT.has(k) ? +(s[k] * 100).toFixed(4) : s[k]));
  }
  return q.toString();
}

if (typeof module !== 'undefined') module.exports = {expectedReturn, judgeRow, screenAll, funnel, funnelText, shortOf, readSettings, writeSettings, backtestAll};

// ---- the page
function screenPage() {
  const dataEl = document.getElementById('screen-data'), rulesEl = document.getElementById('screen-rules');
  const section = document.getElementById('screen');
  if (!dataEl || !rulesEl || !section) return;
  const rows = JSON.parse(dataEl.textContent), defaults = JSON.parse(rulesEl.textContent);
  const panel = section.querySelector('.panel'), fun = section.querySelector('.funnel'), tweak = panel.closest('details');
  const heading = section.querySelector('h2'), serverHtml = section.querySelector('.screen-tables').innerHTML;
  const answerEl = document.getElementById('answer'), answerServer = answerEl ? answerEl.innerHTML : '';
  const answerBelow = !!answerEl && answerEl.hasAttribute('data-below');   // under the results: an empty shortlist is said there
  const ruleServer = {};   // each setting's number as the server wrote it (the rules, their summary, the return column)
  section.querySelectorAll('[data-r]').forEach(el => { if (!(el.dataset.r in ruleServer)) ruleServer[el.dataset.r] = el.textContent; });
  const btEl = document.getElementById('bt-data'), btSection = document.getElementById('backtest');
  const bt = btEl && btSection ? JSON.parse(btEl.textContent) : null;
  const btServer = bt ? {sum: btSection.querySelector('.bt-summary').innerHTML, det: btSection.querySelector('.bt-details').innerHTML} : null;
  let s = readSettings(location.search, defaults);
  const esc = x => String(x).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const pct = (x, nd) => x === null ? '–' : `<span class="${x >= 0 ? 'pos' : 'neg'}">${x >= 0 ? '+' : '-'}${Math.abs(x * 100).toFixed(nd || 0)}%</span>`;
  const short = a => a.replace(/ – .*/, '');
  const linked = (link, ticker) => link ? `<a href="${esc(link)}"><b>${esc(ticker)}</b></a>` : `<b>${esc(ticker)}</b>`;

  function row(r) {
    const tier = {'shortlist': '<span class="pill green">Shortlist</span>', 'near miss': '<span class="pill blue">Near miss</span>'}[r.tier] || '';
    const names = {pe: 'P/E', growth: 'growth', return: '5-yr return'};
    const why = r.tier !== 'shortlist' ? r.missed.map(m => names[m]) : [];
    const notes = (why.length ? 'misses: ' + why.join(', ') : '') + (why.length && r.guards.length ? ' · ' : '') + r.guards.join(', ');
    const pillFlags = ['cyclical', 'state-owned'];   // html_report.screen_pills: pills on shortlist and near-miss rows
    const pills = r.tier ? pillFlags.filter(f => r.flags.includes(f)).map(f =>
      `<br><span class="pill" style="${f === 'cyclical' ? 'background:#B7791F' : 'background:#5A6474'};font-size:11px;padding:1px 8px">${f}</span>`).join('') : '';
    const flags = r.flags.filter(f => !(r.tier && pillFlags.includes(f))).map(f => `[${esc(f)}]`).join(' ');
    return `<tr><td>${linked(r.link, r.ticker)}<br><small>${esc(r.name)}</small>${pills}` +
      (flags ? `<br><small class=late>${flags}</small>` : '') + `</td><td>${tier}</td>` +
      `<td data-v="${r.pe === null ? '' : r.pe}">${r.pe === null ? '–' : r.pe.toFixed(1)}${r.pe_trailing === null ? '' : `<br><small>trailing ${r.pe_trailing.toFixed(1)}</small>`}</td>` +
      `<td>${r.quality}</td>` +
      `<td>${pct(r.c5)} / ${pct(r.c3)}${r.pos ? '' : '<br><small class=neg>a loss year</small>'}</td>` +
      `<td>${pct(r.growth_needed, 1)}</td><td>${pct(r.ret, 1)}${r.assumed === null ? '' : `<br><small>at ${(r.assumed * 100).toFixed(0)}%/yr growth</small>`}</td>` +
      `<td>${r.promoters === null ? '–' : (r.promoters * 100).toFixed(0) + '%'}</td>` +
      `<td><span class="pill ${r.signal}">${esc(short(r.action))}</span></td><td><small>${esc(notes)}</small></td></tr>`;
  }
  const head = section.querySelector('table.sum thead').outerHTML;
  const table = rs => `<div class="wrap"><table class="sum">${head}<tbody>${rs.map(row).join('')}</tbody></table></div>`;
  const nearLine = near => near.length   // html_report.near_line_html
    ? '<p class="near"><b>Near misses:</b> ' + near.map(r => `${linked(r.link, r.ticker)} <small>(${esc(shortOf(r))})</small>`).join(' · ') + '</p>'
    : '<p class="near"><b>Near misses:</b> none.</p>';

  function renderRules() {   // the five rules show the panel's numbers (html_report.rules_html)
    const nearPe = s.pe === s.pe0 ? s.near_pe : s.pe + (s.near_pe - s.pe0);
    const nearGrowth = s.growth === s.growth0 ? s.near_growth : s.growth - (s.growth0 - s.near_growth);
    const v = {pe: `${+s.pe.toFixed(2)}`, growth: `${+(s.growth * 100).toFixed(1)}%`, ret: `${+(s.ret * 100).toFixed(1)}%`,
               years: `${s.years}`, exit: `${s.exit}x`, promoters: `${+(s.promoters * 100).toFixed(1)}%`, near_pe: `${+nearPe.toFixed(2)}`, near_growth: `${+(nearGrowth * 100).toFixed(1)}%`};
    const same = sameAsDefaults();   // looked up afresh: the tables, with their headers, are rewritten on every change
    section.querySelectorAll('[data-r]').forEach(el => { el.textContent = same ? ruleServer[el.dataset.r] : v[el.dataset.r]; });
    section.querySelectorAll('[data-off]').forEach(el => { el.hidden = !!s[el.dataset.off]; });   // a rule switched off says so
  }

  function renderAnswer(judged, same) {   // html_report.answer_html, for the settings set here
    if (!answerEl) return;
    if (same) { answerEl.innerHTML = answerServer; answerEl.hidden = !answerServer; return; }
    const passed = judged.filter(r => r.tier === 'shortlist'), near = judged.filter(r => r.tier === 'near miss');
    const names = rs => andList(rs.map(r => linked(r.link, r.ticker)));
    let today = passed.length ? `<b>With your settings, ${passed.length} ${passed.length === 1 ? 'stock passes' : 'stocks pass'} all five rules:</b> ${names(passed)}.`
      : '<b>With your settings, no stock passes all five rules.</b>';
    if (near.length) today += ` ${near.length} more ${near.length === 1 ? 'misses' : 'miss'} by one rule: ${names(near)}.`;
    let html = answerBelow && !passed.length ? '' : `<p data-ans="today">${today}</p>`;
    if (bt) {
      const res = backtestAll(bt, s), b = res.find(x => x.picks.length), what = bt.us ? 'price only' : 'with dividends';
      const aYear = x => x === null || b.years <= 0 || x <= -1 ? '' : ` (${pct(Math.pow(1 + x, 1 / b.years) - 1, 1)} a year)`;
      html += '<p data-ans="bt">' + (b ? `<b>Backtest:</b> the ${b.picks.length} pick${b.picks.length > 1 ? 's' : ''} of ${esc(b.label)} ${b.picks.length > 1 ? 'are' : 'is'} up ` +
        `${pct(b.picks_ret)}${aYear(b.picks_ret)} ${what}, against ${pct(b.all)} for every stock screened and ${pct(b.index)} for the ` +
        `${esc(bt.index || 'index')} (price only). <a href="#backtest">Details below</a>.`
        : '<b>Backtest:</b> no stock passed these settings on any of the past dates tested.') + '</p>';
    }
    answerEl.innerHTML = html;
    answerEl.className = html ? 'answer' : '';
    answerEl.hidden = !html;
  }

  function sameAsDefaults() { return SCREEN_KEYS.every(k => s[k] === defaults[k]); }

  function renderBacktest(same) {
    // html_report.backtest_html, for the settings set here
    if (!bt) return;
    btSection.querySelector('.bt-custom').hidden = same;
    btSection.querySelectorAll('.bt-default').forEach(el => { el.hidden = !same; });   // about the default picks only
    if (same) {
      btSection.querySelector('.bt-summary').innerHTML = btServer.sum;
      btSection.querySelector('.bt-details').innerHTML = btServer.det;
      return;
    }
    const aYear = (x, y) => x === null || y <= 0 || x <= -1 ? '' : `<br><small>${(Math.pow(1 + x, 1 / y) * 100 - 100 >= 0 ? '+' : '-')}${Math.abs(Math.pow(1 + x, 1 / y) * 100 - 100).toFixed(1)}% a year</small>`;
    const res = backtestAll(bt, s), what = bt.us ? 'price only' : 'with dividends';
    const sumRows = res.map(b => `<tr><td><b>${esc(b.label)}</b><br><small>${b.years.toFixed(0)} years</small></td>` +
      `<td>${b.picks.length} of ${b.screened}</td><td>${pct(b.picks_ret)}${aYear(b.picks_ret, b.years)}</td>` +
      `<td>${pct(b.all)} · median ${pct(b.median)}</td><td>${pct(b.index)}</td>` +
      `<td>${b.best ? esc(b.best.t) + ' ' + pct(b.best.ret) : '–'}</td><td>${b.worst ? esc(b.worst.t) + ' ' + pct(b.worst.ret) : '–'}</td></tr>`).join('');
    const sum = btSection.querySelector('.bt-summary');
    sum.querySelector('tbody').innerHTML = sumRows;
    const det = res.map(b => {
      const body = b.picks.map(r => `<tr><td>${linked(bt.links[r.t], r.t)}<br><small>${esc(bt.names[r.t])}</small></td>` +
        `<td>${r.pe.toFixed(1)}<br><small>${bt.us ? 'figures to' : 'FY to'} ${esc(r.lfy)}</small></td>` +
        `<td>${pct(r.c5)} / ${pct(r.c3)}${bt.us ? '' : `<br><small>${r.short ? bt.years - 1 : bt.years} and 3 years</small>`}</td><td>${pct(r.er, 1)}</td>` +
        `<td>${pct(r.ret)}${aYear(r.ret, b.years)}</td>${bt.us ? '' : `<td>${pct(r.pr)}</td>`}</tr>`).join('');
      const head = bt.us ? '<th>Pick</th><th>P/E then</th><th>EPS growth then (5 / 3 years)</th><th>Expected then</th><th>Return, price only</th>'
        : '<th>Pick</th><th>P/E then</th><th>EPS growth then</th><th>Expected then</th><th>Return, with dividends</th><th>Price only</th>';
      const tbl = b.picks.length ? `<div class="wrap"><table class="sum"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`
        : '<p class="notes">No stock passed these settings on this date.</p>';
      const got = b.picks.length ? `${b.picks.length} pick${b.picks.length > 1 ? 's' : ''}, ${pct(b.picks_ret)} ${what}` : 'no picks';
      return `<details><summary>Since ${esc(b.label)}: ${got}</summary><p class="small">${esc(b.note)}</p>${tbl}</details>`;
    }).join('');
    btSection.querySelector('.bt-details').innerHTML = det;
  }

  function render() {
    const judged = screenAll(rows, s);
    const passed = judged.filter(r => r.tier === 'shortlist'), near = judged.filter(r => r.tier === 'near miss');
    const others = judged.filter(r => r.tier !== 'shortlist');
    document.querySelectorAll('[data-tab-count]').forEach(el => { el.textContent = passed.length; });   // the tab's count
    // html_report.left_out_html: why the screen counts fewer companies than the page header
    const extra = rows.filter(r => s.mid && r.extra).length, cyc = rows.filter(r => !(s.mid && r.extra) && s.cyc && r.cyclical).length;
    const parts = (extra ? [`${extra} added by hand`] : []).concat(cyc ? [`${cyc} cyclical${cyc > 1 ? 's' : ''}`] : []);
    heading.innerHTML = `Screen – ${passed.length} shortlisted, ${near.length} near miss${near.length === 1 ? '' : 'es'} of ${judged.length}` +
      (parts.length ? ` <span>· ${parts.join(' and ')} left out</span>` : '');
    const tables = section.querySelector('.screen-tables'), same = sameAsDefaults();
    if (same) tables.innerHTML = serverHtml;   // exactly what the server wrote
    else tables.innerHTML = s.all ? table(judged)
      : (passed.length ? table(passed) : '<p class="nopass">No company passes all five rules with these settings.</p>') + nearLine(near) +
        (others.length ? `<details><summary>Near misses and the other ${others.length - near.length}, in full</summary>${table(others)}</details>` : '');
    fun.innerHTML = funnelText(funnel(rows, s));
    renderRules();
    renderAnswer(judged, same);
    renderBacktest(same);
    const q = writeSettings(s, defaults);   // the address carries the settings, so a link opens with them
    if (q) history.replaceState(null, '', location.pathname + '?' + q + (location.hash || '#screen'));
    else if (location.search) history.replaceState(null, '', location.pathname + location.hash);
  }

  const shown = (k, v) => SCREEN_PCT.has(k) ? `${+(v * 100).toFixed(2)}%` : k === 'exit' ? `${v}x` : `${v}`;
  function out(k) { const o = panel.querySelector(`[data-out="${k}"]`); if (o) o.textContent = shown(k, s[k]); }
  function sync() {   // the panel's sliders and boxes ← the settings
    panel.querySelectorAll('[data-k]').forEach(el => {
      const k = el.dataset.k;
      if (el.type === 'checkbox') el.checked = !!s[k];
      else { el.value = SCREEN_PCT.has(k) ? +(s[k] * 100).toFixed(2) : s[k]; out(k); }
    });
  }
  panel.querySelectorAll('[data-k]').forEach(el => el.addEventListener(el.type === 'checkbox' ? 'change' : 'input', () => {
    const k = el.dataset.k;
    if (el.type === 'checkbox') s[k] = el.checked;
    else if (el.value !== '' && !isNaN(+el.value)) { s[k] = SCREEN_PCT.has(k) ? +el.value / 100 : +el.value; out(k); }
    render();
  }));
  panel.querySelector('[data-reset]').addEventListener('click', () => { s = Object.assign({}, defaults); sync(); render(); });
  tweak.hidden = false;
  if (!sameAsDefaults()) tweak.open = true;   // a shared link with settings opens with the panel showing them
  sync();
  render();
}

if (typeof document !== 'undefined') {
  // the script sits in the screen section, before the backtest further down: start once the page is read
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', screenPage);
  else screenPage();
}
