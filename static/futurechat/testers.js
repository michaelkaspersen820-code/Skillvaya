/* TST-01 (owner 2026-11-19): the owner's Testers screen, shared by the Skillvaya owner app and Future Chat Control.
   Google Play only shows how many testers opted in; this shows who: account or not, when they last opened each app,
   which version, and whether it came from Google Play. Server: testers.py (/api/tst/*). */
(function () {
  'use strict';
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const DAY = 86400000, QUIET_DAYS = 2;
  const ago = iso => {
    if (!iso) return '';
    const s = Math.max(0, (Date.now() - new Date(iso)) / 1000);
    if (s < 600) return 'just now';
    if (s < 3600) return Math.round(s / 60) + ' min ago';
    if (s < 86400) return Math.round(s / 3600) + ' h ago';
    const d = Math.round(s / 86400); return d === 1 ? 'yesterday' : d + ' days ago';
  };
  const active = a => !!(a && a.last_seen && Date.now() - new Date(a.last_seen) < QUIET_DAYS * DAY);
  function appLine(name, a) {
    if (!a) return '<div class="tst-app"><span class="tst-dot tst-no"></span><b>' + name + ':</b> never opened</div>';
    const bits = ['opened ' + ago(a.last_seen)];
    if (a.version) bits.push('v' + esc(a.version));
    if (a.from_play) bits.push('from Google Play');
    else if (a.installer) bits.push('NOT from Google Play (' + esc(a.installer) + ')');
    return '<div class="tst-app"><span class="tst-dot ' + (active(a) ? 'tst-ok' : 'tst-quiet') + '"></span><b>' + name + ':</b> ' + bits.join(' · ') + '</div>';
  }
  function status(t) {
    const fc = t.apps && t.apps.futurechat, sv = t.apps && t.apps.skillvaya;
    if (!t.account) return { k: 'none', label: 'No account with this email' };
    if (!fc && !sv) return { k: 'none', label: 'Has an account but never opened the phone apps' };
    if (!active(fc) && !active(sv)) return { k: 'quiet', label: 'Gone quiet (nothing in ' + QUIET_DAYS + ' days)' };
    return { k: 'ok', label: 'Testing' };
  }
  const CSS = '.tst{font-size:14.5px;line-height:1.4}.tst-sum{display:flex;flex-wrap:wrap;gap:8px;margin:4px 0 12px}.tst-chip{border:1px solid rgba(127,155,176,.45);background:transparent;color:inherit;border-radius:999px;padding:7px 13px;font:inherit;cursor:pointer}' +
    '.tst-chip.on{background:#12a89c;border-color:#12a89c;color:#fff}.tst-card{border:1px solid rgba(127,155,176,.35);border-radius:12px;padding:12px 14px;margin:8px 0;background:rgba(127,155,176,.08)}' +
    '.tst-top{display:flex;justify-content:space-between;gap:8px;align-items:flex-start}.tst-email{font-weight:700;word-break:break-all}.tst-who{opacity:.85;margin-top:2px}.tst-who a{color:inherit}' +
    '.tst-badge{font-size:12px;font-weight:700;border-radius:999px;padding:3px 9px;white-space:nowrap}.tst-b-ok{background:#d6f5e3;color:#11643a}.tst-b-quiet{background:#fff1cc;color:#7a5600}.tst-b-none{background:#ffdcdc;color:#8a1c1c}' +
    '.tst-app{margin-top:6px;font-size:13.5px}.tst-dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;vertical-align:middle}.tst-ok{background:#22c55e}.tst-quiet{background:#f5b301}.tst-no{background:#ef4444}' +
    '.tst-x{border:0;background:transparent;color:inherit;opacity:.6;font-size:18px;cursor:pointer;padding:0 4px}.tst-add textarea{width:100%;box-sizing:border-box;min-height:70px;border-radius:10px;padding:10px;font:inherit;border:1px solid rgba(127,155,176,.5);background:rgba(127,155,176,.08);color:inherit}' +
    '.tst-add button{margin-top:8px;border:0;border-radius:10px;padding:10px 16px;background:#12a89c;color:#fff;font:inherit;font-weight:700;cursor:pointer}.tst-note{opacity:.75;font-size:12.5px;margin:10px 0}.tst h3{margin:18px 0 6px;font-size:16px}';

  async function render(el, get, post) {
    if (!el) return;
    if (!document.getElementById('tstCss')) { const st = document.createElement('style'); st.id = 'tstCss'; st.textContent = CSS; document.head.appendChild(st); }
    let filter = 'all', d = null;
    async function load() {
      el.innerHTML = '<div class="tst"><p>Loading testers…</p></div>';
      try { d = await get('/api/tst/list'); } catch (e) { el.innerHTML = '<div class="tst"><p>' + esc(e.message) + '</p></div>'; return; }
      draw();
    }
    function draw() {
      const items = (d.items || []).map(t => Object.assign({ st: status(t) }, t));
      const n = k => items.filter(t => t.st.k === k).length;
      const fcN = items.filter(t => t.apps && t.apps.futurechat).length, svN = items.filter(t => t.apps && t.apps.skillvaya).length;
      const shown = items.filter(t => filter === 'all' || t.st.k === filter);
      el.innerHTML = '<div class="tst">' +
        '<p><b>' + items.length + '</b> testers on your list · <b>' + svN + '</b> have opened Skillvaya · <b>' + fcN + '</b> have opened Future Chat</p>' +
        '<div class="tst-sum">' + [['all', 'All (' + items.length + ')'], ['ok', '✅ Testing (' + n('ok') + ')'], ['quiet', '⚠️ Gone quiet (' + n('quiet') + ')'], ['none', '❌ Not started (' + n('none') + ')']]
          .map(([k, l]) => '<button class="tst-chip' + (filter === k ? ' on' : '') + '" data-f="' + k + '">' + l + '</button>').join('') + '</div>' +
        (shown.length ? shown.map(t => {
          const a = t.account;
          const who = a ? esc(a.name) + (a.phone ? ' · <a href="tel:' + esc(a.phone) + '">' + esc(a.phone) + '</a>' : '') + ' · joined ' + esc(a.joined) : 'Nobody has signed up with this email yet';
          return '<div class="tst-card"><div class="tst-top"><div><div class="tst-email">' + esc(t.email) + '</div><div class="tst-who">' + who + '</div></div>' +
            '<div style="display:flex;gap:4px;align-items:center"><span class="tst-badge tst-b-' + t.st.k + '">' + esc(t.st.label) + '</span><button class="tst-x" title="Remove from list" data-rm="' + esc(t.email) + '">×</button></div></div>' +
            (a ? appLine('Skillvaya', t.apps.skillvaya) + appLine('Future Chat', t.apps.futurechat) : '') + '</div>';
        }).join('') : '<p>Nobody in this group.</p>') +
        '<div class="tst-add"><h3>Add testers</h3><textarea id="tstNew" placeholder="Paste email addresses, separated by commas or new lines"></textarea><button id="tstAddBtn">Add to list</button></div>' +
        ((d.others || []).length ? '<h3>Using the apps with an email that isn\'t on your list</h3><p class="tst-note">They might be testers who signed up with a different email.</p>' +
          d.others.map(o => '<div class="tst-card"><div class="tst-email">' + esc(o.account.name) + '</div><div class="tst-who">' + esc(o.account.email) + (o.account.phone ? ' · <a href="tel:' + esc(o.account.phone) + '">' + esc(o.account.phone) + '</a>' : '') + '</div>' +
            appLine('Skillvaya', o.apps.skillvaya) + appLine('Future Chat', o.apps.futurechat) + '</div>').join('') : '') +
        '<p class="tst-note">"Testing" = opened Skillvaya or Future Chat on their phone in the last ' + QUIET_DAYS + ' days. A person only matches if they sign into the app with the same email they joined the Google Play test with. "From Google Play" shows once they have the next app update. Tracking started on 19 Nov 2026, so earlier use isn\'t counted.</p></div>';
      el.querySelectorAll('[data-f]').forEach(b => b.onclick = () => { filter = b.dataset.f; draw(); });
      el.querySelectorAll('[data-rm]').forEach(b => b.onclick = async () => {
        if (!confirm('Remove ' + b.dataset.rm + ' from your tester list?')) return;
        try { await post('/api/tst/remove', { email: b.dataset.rm }); load(); } catch (e) { alert(e.message); }
      });
      const add = el.querySelector('#tstAddBtn');
      add.onclick = async () => {
        const v = el.querySelector('#tstNew').value; if (!v.trim()) return;
        add.disabled = true;
        try { const r = await post('/api/tst/add', { emails: v }); alert(r.added + ' added' + (r.skipped ? ', ' + r.skipped + ' already on the list' : '') + '.'); load(); }
        catch (e) { alert(e.message); add.disabled = false; }
      };
    }
    load();
  }
  window.SVTesters = { render };
})();
