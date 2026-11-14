
const rows = () => [...document.querySelectorAll('#sum tbody tr')];
const pick = {signal: 'all', metal: 'all', stage: 'all', held: 'all'};
function apply() {
  const q = document.getElementById('q').value.toLowerCase(); let n = 0;
  rows().forEach(r => {
    const ok = (pick.signal === 'all' || r.dataset.signal === pick.signal) && (pick.metal === 'all' || r.dataset.metal.includes(pick.metal))
            && (pick.stage === 'all' || r.dataset.stage === pick.stage) && (pick.held === 'all' || r.dataset.held === pick.held)
            && (!q || r.dataset.text.includes(q));
    r.style.display = ok ? '' : 'none'; if (ok) n++; });
  document.getElementById('count').textContent = n + ' shown';
}
document.querySelectorAll('[data-k]').forEach(b => b.onclick = () => {
  pick[b.dataset.k] = b.dataset.v;
  document.querySelectorAll(`[data-k="${b.dataset.k}"]`).forEach(x => x.classList.toggle('on', x === b)); apply(); });
document.getElementById('q').oninput = apply;
document.querySelectorAll('#sum th').forEach((th, i) => th.onclick = () => {
  const asc = !th.classList.contains('asc');
  document.querySelectorAll('#sum th').forEach(x => x.classList.remove('asc', 'desc')); th.classList.add(asc ? 'asc' : 'desc');
  const key = r => { const v = r.children[i].dataset.v ?? ''; const n = parseFloat(v); return v === '' ? null : isNaN(n) ? v : n; };
  const body = document.querySelector('#sum tbody');
  rows().sort((a, b) => { const x = key(a), y = key(b); if (x === null) return 1; if (y === null) return -1;
    return (x < y ? -1 : x > y ? 1 : 0) * (asc ? 1 : -1); }).forEach(r => body.appendChild(r)); });
apply();
