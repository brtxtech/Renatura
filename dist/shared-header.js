
(() => {
  if (document.getElementById('renatura-header')) return;

  const old = document.querySelector('body > header')
    || document.querySelector('header');
  if (!old) return;

  const header = document.createElement('header');
  header.id = 'renatura-header';
  header.innerHTML = `
    <a class="rh-brand" href="index.html">
      renatura<small>NORMANDIE</small>
    </a>
    <nav aria-label="Navigation principale">
      <a href="atlas.html">Atlas régional</a>
      <a href="index.html">Explorer · Pays d’Auge</a>
      <a href="explorer-normandie.html">Explorer · Normandie</a>
      <a href="species-map.html">Observations &amp; images</a>
      <a href="photos-normandie.html">Photos nature</a>
      <a href="acheteur-normandie.html">Prix &amp; bénéfice</a>
      <a href="climat-normandie.html">Climat</a>
      <a href="graph.html">Neo4j</a>
      <a href="data.html">Ajouter des données</a>
    </nav>
  `;

  // Conserva los elementos originales y sus identificadores:
  // los scripts existentes pueden seguir utilizándolos.
  const tools = document.createElement('details');
  tools.id = 'renatura-page-tools';

  const summary = document.createElement('summary');
  summary.textContent = 'Outils de cette page';
  tools.append(summary);

  const content = document.createElement('div');
  content.className = 'rh-tools-content';

  const controls = [
    ...old.querySelectorAll('[data-page]'),
    ...old.querySelectorAll('.top-actions'),
    ...old.querySelectorAll('#sources')
  ];

  for (const element of controls) {
    if (!content.contains(element)) content.append(element);
  }

  old.setAttribute('data-renatura-old-header', '');
  old.hidden = true;
  old.before(header);

  if (content.childElementCount) {
    tools.append(content);
    old.after(tools);
  }
})();
