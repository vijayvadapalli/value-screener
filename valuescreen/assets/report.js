
const rows = () => [...document.querySelectorAll('#sum tbody tr')];
let sig = 'all', grd = 'all';
function apply() {
  const q = document.getElementById('q').value.toLowerCase();
  let n = 0;
  rows().forEach(r => {
    const ok = (sig === 'all' || r.dataset.signal === sig) && (grd === 'all' || r.dataset.grade === grd)
               && (!q || r.dataset.text.includes(q));
    r.style.display = ok ? '' : 'none'; if (ok) n++;
  });
  document.getElementById('count').textContent = n + ' shown';
}
document.querySelectorAll('[data-sig]').forEach(b => b.onclick = () => {
  sig = b.dataset.sig; document.querySelectorAll('[data-sig]').forEach(x => x.classList.toggle('on', x === b)); apply(); });
document.querySelectorAll('[data-grd]').forEach(b => b.onclick = () => {
  grd = b.dataset.grd; document.querySelectorAll('[data-grd]').forEach(x => x.classList.toggle('on', x === b)); apply(); });
document.getElementById('q').oninput = apply;
document.querySelectorAll('#sum th').forEach((th, i) => th.onclick = () => {
  const asc = !th.classList.contains('asc');
  document.querySelectorAll('#sum th').forEach(x => x.classList.remove('asc', 'desc'));
  th.classList.add(asc ? 'asc' : 'desc');
  const key = r => { const v = r.children[i].dataset.v ?? ''; const n = parseFloat(v); return v === '' ? null : isNaN(n) ? v : n; };
  const body = document.querySelector('#sum tbody');
  rows().sort((a, b) => { const x = key(a), y = key(b);
    if (x === null) return 1; if (y === null) return -1;
    return (x < y ? -1 : x > y ? 1 : 0) * (asc ? 1 : -1); }).forEach(r => body.appendChild(r));
});
apply();

// Tabs (India growth-screen lists): one pane at a time, the tab in the address (#picks, #values, #growth). A link to
// anything inside a pane (#backtest, #pvp, #screen …) opens that pane first. Without JavaScript the panes stack.
(() => {
  const bar = document.querySelector('nav.tabs');
  if (!bar) return;
  const tabs = [...bar.querySelectorAll('a')], panes = tabs.map(a => document.getElementById(a.hash.slice(1)));
  const show = id => tabs.forEach((a, i) => { const on = panes[i].id === id; a.classList.toggle('on', on); panes[i].hidden = !on; });
  const target = () => { try { return location.hash && document.getElementById(decodeURIComponent(location.hash.slice(1))); } catch (e) { return null; } };
  function fromHash() {
    const el = target(), pane = el && el.closest('.tabpane');
    if (el && !pane) { show(panes[0].id); return; }   // outside the tabs (#markets, #summary): leave the first open
    show(pane ? pane.id : panes[0].id);
    if (el && el !== pane) el.scrollIntoView();
  }
  bar.addEventListener('click', ev => {
    const a = ev.target.closest('a');
    if (!a) return;
    ev.preventDefault();
    history.replaceState(null, '', location.pathname + location.search + a.hash);
    show(a.hash.slice(1));
  });
  window.addEventListener('hashchange', fromHash);
  fromHash();
})();
