
(() => {
  if (document.getElementById('renatura-header')) return;
  // Embedded inside another page (e.g. the photos tab of data.html): no site header.
  if (new URLSearchParams(location.search).has('embed')) return;

  const old = document.querySelector('body > header')
    || document.querySelector('header');
  if (!old) return;

  const header = document.createElement('header');
  header.id = 'renatura-header';
  header.innerHTML = `
    <a class="rh-brand" href="atlas.html">
      <svg class="rh-logo" viewBox="0 0 192 192" aria-hidden="true"><rect width="192" height="192" rx="40" fill="#173d31"/><path d="M96 151V76M96 116C40 119 35 68 40 42c55 0 73 32 56 74Zm0-35c-4-40 24-55 56-55 4 36-16 63-56 55Z" fill="none" stroke="#d2e5ac" stroke-width="10" stroke-linecap="round"/></svg>
      <span class="rh-name">renatura<small>NORMANDIE</small></span>
    </a>
    <nav aria-label="Navigation principale">
      <a href="atlas.html">Atlas régional</a>
      <button type="button" class="rh-menu-button" id="rh-explorer-btn" aria-haspopup="true" aria-expanded="false" aria-controls="rh-explorer-panel">Explorer ▾</button>
      <a href="species-map.html">Observations &amp; images</a>
      <a href="acheteur-normandie.html">Prix &amp; bénéfice</a>
      <a href="climat-normandie.html">Climat</a>
      <a href="ville-normandie.html">Analyse par commune</a>
      <a href="assistant.html">Assistant IA</a>
      <a href="modeles.html">Modèles IA</a>
      <a href="connaissances.html">Connaissances</a>
      <a href="data.html">Ajouter des données</a>
    </nav>
  `;

  // Pages in a sub-folder (e.g. /workbench/) need '../' in front of the site's relative links.
  const base = /\/workbench\//.test(location.pathname) ? '../' : '';
  const rebase = root => { if (base) root.querySelectorAll('a[href]').forEach(a => { const h = a.getAttribute('href'); if (!/^(https?:|#|\/|\.\.\/)/.test(h)) a.setAttribute('href', base + h); }); };
  rebase(header);

  // Page-specific controls (tabs, language, share, sources) are moved, with their ids and listeners, into a
  // plain always-visible bar under the site header (no "Outils de cette page" fold-out).
  const tools = document.createElement('div');
  tools.id = 'renatura-page-tools';
  for (const element of [...old.querySelectorAll('[data-page]'), ...old.querySelectorAll('.top-actions'), ...old.querySelectorAll('#sources')]) {
    if (!tools.contains(element)) tools.append(element);
  }
  old.setAttribute('data-renatura-old-header', '');
  old.hidden = true;
  old.before(header);
  if (tools.childElementCount) old.after(tools);

  // Explorer menu: a floating layer appended to <body> (outside the scrolling nav), opened by the button.
  const button = header.querySelector('#rh-explorer-btn');
  if (button) {
    const panel = document.createElement('div');
    panel.id = 'rh-explorer-panel';
    panel.className = 'rh-menu-panel';
    panel.setAttribute('role', 'menu');
    panel.hidden = true;
    panel.innerHTML = `
      <a role="menuitem" href="explorer-normandie.html" data-page-file="explorer-normandie.html">
        <b>Normandie · territoire régional</b>
        <span>30 850 mailles de 1 km² · V, D, P, O calculés à partir des couches de l’atlas · scénarios régionaux</span></a>
      <a role="menuitem" href="pays-auge.html" data-page-file="pays-auge.html">
        <b>Pays d’Auge · site pilote FR2502014</b>
        <span>Bocages et vergers du sud Pays d’Auge · haies 1947 / 2010 / 2016 observées · méthode de référence</span></a>`;
    document.body.append(panel);
    rebase(panel);
    const page = location.pathname.split('/').pop() || 'index.html';
    panel.querySelectorAll('[data-page-file]').forEach(a => a.classList.toggle('current', a.dataset.pageFile === page));
    const close = () => { panel.hidden = true; button.setAttribute('aria-expanded', 'false'); };
    button.addEventListener('click', e => {
      e.stopPropagation();
      if (!panel.hidden) return close();
      const r = button.getBoundingClientRect();
      panel.hidden = false;
      panel.style.top = (r.bottom + 8) + 'px';
      panel.style.left = Math.max(8, Math.min(r.left, innerWidth - panel.offsetWidth - 8)) + 'px';
      button.setAttribute('aria-expanded', 'true');
    });
    document.addEventListener('click', e => { if (!panel.hidden && !panel.contains(e.target)) close(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && !panel.hidden) { close(); button.focus(); } });
    addEventListener('resize', close);
  }
})();
