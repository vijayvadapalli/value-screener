// The growth screen's settings panel (lists with `screen_panel: true`). The page carries every screen row as JSON
// (<script id="screen-data">) and the default rules (<script id="screen-rules">); this recomputes the tiers in the
// browser exactly as growth_screen.py does – expected_return() and judge() – for the values you set, keeps them in
// the address (…?pe=20&growth=15#screen), and draws a funnel. The table the server wrote stays untouched until a
// setting differs from the defaults, so the page reads the same without JavaScript.

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
  // start N → after guards → + growth → + P/E → + 5-yr return → + promoters → + government-owned rule
  let left = rows.filter(r => inUniverse(r, s));
  const steps = [['Start', left.length]];
  const keep = (label, test) => { left = left.filter(test); steps.push([label, left.length]); };
  const j = new Map(left.map(r => [r.ticker, judgeRow(r, Object.assign({}, s, {prule: false, psu: false}))]));
  keep('after guards', r => !j.get(r.ticker).guards.length);
  keep('+ growth', r => j.get(r.ticker).checks.growth);
  keep('+ P/E', r => j.get(r.ticker).checks.pe);
  keep('+ 5-yr return', r => j.get(r.ticker).checks.return);
  keep('+ promoters', r => !s.prule || (r.promoters !== null && r.promoters >= s.promoters));
  keep('+ government-owned rule', r => !s.psu || !r.state_owned);
  return steps;
}

function readSettings(search, defaults) {
  const s = Object.assign({}, defaults), q = new URLSearchParams(search);
  for (const k of SCREEN_KEYS) {
    if (!q.has(k)) continue;
    const v = q.get(k);
    if (SCREEN_BOOL.has(k)) s[k] = v === '1';
    else if (v !== '' && !isNaN(+v)) s[k] = SCREEN_PCT.has(k) ? +v / 100 : +v;
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

if (typeof module !== 'undefined') module.exports = {expectedReturn, judgeRow, screenAll, funnel, readSettings, writeSettings};

// ---- the page
if (typeof document !== 'undefined') (function () {
  const dataEl = document.getElementById('screen-data'), rulesEl = document.getElementById('screen-rules');
  const section = document.getElementById('screen');
  if (!dataEl || !rulesEl || !section) return;
  const rows = JSON.parse(dataEl.textContent), defaults = JSON.parse(rulesEl.textContent);
  const panel = section.querySelector('.panel'), fun = section.querySelector('.funnel');
  const heading = section.querySelector('h2'), serverHtml = section.querySelector('.screen-tables').innerHTML;
  let s = readSettings(location.search, defaults);
  const esc = x => String(x).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const pct = (x, nd) => x === null ? '–' : `<span class="${x >= 0 ? 'pos' : 'neg'}">${x >= 0 ? '+' : '-'}${Math.abs(x * 100).toFixed(nd || 0)}%</span>`;
  const short = a => a.replace(/ – .*/, '');

  function row(r) {
    const tier = {'shortlist': '<span class="pill green">Shortlist</span>', 'near miss': '<span class="pill blue">Near miss</span>'}[r.tier] || '';
    const names = {pe: 'P/E', growth: 'growth', return: '5-yr return'};
    const why = r.tier !== 'shortlist' ? r.missed.map(m => names[m]) : [];
    const notes = (why.length ? 'misses: ' + why.join(', ') : '') + (why.length && r.guards.length ? ' · ' : '') + r.guards.join(', ');
    const pillFlags = ['cyclical', 'state-owned'];   // html_report.screen_pills: pills on shortlist and near-miss rows
    const pills = r.tier ? pillFlags.filter(f => r.flags.includes(f)).map(f =>
      `<br><span class="pill" style="${f === 'cyclical' ? 'background:#B7791F' : 'background:#5A6474'};font-size:11px;padding:1px 8px">${f}</span>`).join('') : '';
    const flags = r.flags.filter(f => !(r.tier && pillFlags.includes(f))).map(f => `[${esc(f)}]`).join(' ');
    return `<tr><td><a href="${esc(r.link)}"><b>${esc(r.ticker)}</b></a><br><small>${esc(r.name)}</small>${pills}` +
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

  function sameAsDefaults() { return SCREEN_KEYS.every(k => s[k] === defaults[k]); }

  function render() {
    const judged = screenAll(rows, s);
    const top = judged.filter(r => r.tier), rest = judged.filter(r => !r.tier);
    const nShort = judged.filter(r => r.tier === 'shortlist').length;
    heading.textContent = `Screen – ${nShort} shortlisted, ${top.length - nShort} near misses of ${judged.length}`;
    const tables = section.querySelector('.screen-tables');
    if (sameAsDefaults()) tables.innerHTML = serverHtml;   // exactly what the server wrote
    else tables.innerHTML = s.all ? table(judged)
      : (top.length ? table(top) : '<p class="notes">No company passes, or nearly passes, with these settings.</p>') +
        `<details><summary>All ${rest.length} others</summary>${table(rest)}</details>`;
    fun.innerHTML = funnel(rows, s).map(([label, n]) => `<span><b>${n}</b> ${esc(label)}</span>`).join('<i>→</i>');
    const q = writeSettings(s, defaults);   // the address carries the settings, so a link opens with them
    if (q) history.replaceState(null, '', location.pathname + '?' + q + '#screen');
    else if (location.search) history.replaceState(null, '', location.pathname + location.hash);
  }

  function sync() {   // the panel's inputs ← the settings
    panel.querySelectorAll('[data-k]').forEach(el => {
      const k = el.dataset.k;
      if (el.type === 'checkbox') el.checked = !!s[k];
      else el.value = SCREEN_PCT.has(k) ? +(s[k] * 100).toFixed(2) : s[k];
    });
  }
  panel.querySelectorAll('[data-k]').forEach(el => el.addEventListener(el.type === 'checkbox' ? 'change' : 'input', () => {
    const k = el.dataset.k;
    if (el.type === 'checkbox') s[k] = el.checked;
    else if (el.value !== '' && !isNaN(+el.value)) s[k] = SCREEN_PCT.has(k) ? +el.value / 100 : +el.value;
    render();
  }));
  panel.querySelector('[data-reset]').addEventListener('click', () => { s = Object.assign({}, defaults); sync(); render(); });
  panel.hidden = false;
  sync();
  render();
})();
