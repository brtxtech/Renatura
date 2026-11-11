import { escapeHTML as e, formatNumber as number } from './core.js';

export function methodology(language, sensitivity, cells, summary) {
  const en = language === 'en';
  const label = (fr, english) => en ? english : fr;
  const names = new Map(cells.map(s => [s.id, s.commune]));
  const rows = sensitivity.sites.slice(0, 20).map(site => `
    <div class="stability-row">
      <span>${e(names.get(site.id))}<small> · #${site.baseline_rank}</small></span>
      <div class="stability-track"><i style="width:${site.top20_frequency * 100}%"></i></div>
      <span>${number(site.top20_frequency * 100, 0, language)}%</span>
    </div>`).join('');
  return `
    <div class="eyebrow">${label('TRANSPARENCE PAR CONSTRUCTION', 'TRANSPARENCY BY DESIGN')}</div>
    <h1>${label('Comprendre avant de décider.', 'Understand before deciding.')}</h1>
    <p class="lead">${label('Un outil d’aide à la décision, pas une vérité écologique. Chaque chiffre est lié à une observation, une formule ou une hypothèse explicite.', 'A decision-support tool, not ecological truth. Every figure is connected to an observation, a formula or an explicit assumption.')}</p>
    <div class="coverage-note"><span>!</span><p>${label('Version régionale : maillage de toute la Normandie. Les scores restent absents hors couverture des observations. Le RP complet et la protection ne sont pas calculables sans critères suffisants.', 'Regional grid across Normandy. Scores remain missing outside survey coverage. Complete RP and protection require adequate observations.')}</p></div>
    <div class="document-grid">
      <article class="document-card"><h2>01 · ${label('Mesurer le territoire', 'Measure the landscape')}</h2>
        <p>${label('Maillage hexagonal de 1 km², découpé au contour régional de Normandie. Les fragments de moins de 1 ha sont exclus et leur surface est rapportée. Les communes servent à la recherche, pas d’unité de calcul.', 'A 1 km² hexagonal grid clipped to the Normandy regional boundary. Fragments below 1 ha are excluded and their area reported. Municipalities support search, not computation.')}</p>
        <p>${label('EPSG:2154 pour les longueurs et surfaces ; EPSG:4326 pour la carte. Géométries réparées, doublons géométriques supprimés. Seules les lignes Nature=haie sont comptées.', 'EPSG:2154 for lengths and areas; EPSG:4326 for display. Geometries repaired and exact duplicates removed. Only Nature=haie lines contribute to hedgerow length.')}</p>
        <p>${label('Fragments exclus', 'Excluded slivers')}: ${number(summary.omitted_slivers_ha, 2, language)} ha.</p>
      </article>
      <article class="document-card"><h2>02 · ${label('Des scores explicables', 'Explainable scores')}</h2>
        <div class="formula">V = ½ percentile(haies / ha) + ½ percentile(bois / ha)<br>D = 100 × max(0, 1 − longueur2016 / longueur2010)<br>RP = Σ(w × critère disponible) / Σ(w disponible)</div>
        <p>${label('Les percentiles utilisent les rangs moyens ; une mesure nulle reste à zéro. Si la longueur 2010 est nulle, D est absent. V représente une structure boisée, pas une richesse spécifique mesurée.', 'Percentiles use midranks; zero measurements stay zero. If 2010 length is zero, D is missing. V represents woody structure, not measured species richness.')}</p>
        <p>${label('RP partiel nécessite une activation explicite. Seuil V≥10. Couverture = nombre de critères disponibles / 4 ; ce n’est pas une probabilité de fiabilité. Un recul net de haies ne démontre ni sa cause ni une perte de biodiversité.', 'Partial RP requires explicit activation. V≥10 eligibility threshold. Coverage = available criteria / 4; this is not a reliability probability. Net hedgerow decline does not establish its cause or biodiversity loss.')}</p>
      </article>
      <article class="document-card"><h2>03 · ${label('Reconnecter des habitats', 'Reconnect habitats')}</h2>
        <p>${label('Dans la méthode originale, NetworkX relie les cellules adjacentes. Cette version ne réutilise aucun chemin du pilote comme connexion régionale : les connexions régionales restent à préparer. Les groupes de cellules V≥60 sont des réservoirs structurels supposés. Les chemins de moindre coût connectent les douze plus grands groupes, mesurés par surface boisée.', 'NetworkX links adjacent cells. Groups of V≥60 cells are assumed structural habitat cores. Least-cost paths connect the twelve largest groups, measured by woodland area.')}</p>
        <div class="formula">résistance = distance × (1 + 4 × (1 − V moyen / 100))<br>gain brut = √(surface boisée A × surface boisée B)</div>
        <p>${label('Gain normalisé entre les connexions. Une route est créditée une fois, seulement si toutes ses cellules intermédiaires sont sélectionnées. Les gains entre paires ne représentent pas des hectares uniques. Aucune calibration par espèce ; pas de validation terrain.', 'Gain normalised across connections. A route earns credit once, only if every intermediate cell is selected. Pairwise gains do not represent unique hectares. No species calibration or field validation.')}</p>
      </article>
      <article class="document-card"><h2>04 · ${label('Optimiser sans surpromettre', 'Optimise without overclaiming')}</h2>
        <div class="formula">max Σ(RPᵢ × xᵢ) + λ Σ(gainₚ × yₚ)<br>Σ(coûtᵢ × xᵢ) ≤ enveloppe<br>xᵢ, yₚ ∈ {0,1}</div>
        <p>${label('Dans le projet original, PuLP/CBC calcule les scénarios hors ligne. Aucun scénario du pilote n’est réutilisé comme résultat régional. Le moteur navigateur original est conservé. Dans le navigateur : recherche bornée à 3 secondes, solution réalisable et borne supérieure si la preuve est incomplète. Les comparaisons appliquent le même périmètre, les mêmes poids et le même budget.', 'PuLP/CBC computes offline scenarios. In the browser: search capped at 3 seconds, with a feasible result and upper bound when proof is incomplete. Comparisons use identical scope, weights and budget.')}</p>
        <p>${label('Le budget proxy vaut la surface en hectares : ce n’est pas un devis. Aucune hypothèse de disponibilité foncière. Les cellules sont des unités de planification, pas des parcelles prêtes à restaurer.', 'Proxy budget equals area in hectares: it is not a quotation. No assumption of land availability. Cells are planning units, not restoration-ready parcels.')}</p>
      </article>
    </div>
    <article class="document-card">
      <div class="eyebrow">MONTE CARLO · ±20% · SEED 42</div>
      <h2>${label('Le classement résiste-t-il aux poids ?', 'How stable is the ranking?')}</h2>
      <p>${number(sensitivity.runs)} ${label('tirages indépendants des poids, renormalisés. La barre indique la fréquence dans le top 20. Il s’agit de sensibilité aux préférences, pas d’incertitude écologique.', 'independent weight draws, renormalised. Bars show top-20 inclusion frequency. This measures preference sensitivity, not ecological uncertainty.')}</p>
      <p>${label('Jaccard moyen du top 20', 'Mean top-20 Jaccard')}: <strong>${number(sensitivity.mean_top20_jaccard, 3, language)}</strong> · ${label('Corrélation des rangs', 'Rank correlation')}: <strong>${number(sensitivity.mean_rank_correlation, 3, language)}</strong></p>
      <p id="sensitivity-context" class="micro"></p>
      <button id="live-sensitivity" class="outline-button">${label('Recalculer 200 tirages avec mes poids', 'Recalculate 200 draws with my weights')}</button>
      <button id="export-sensitivity" class="outline-button">JSON ↓</button>
      <div>${rows}</div>
    </article>
    <div class="document-grid">
      <article class="document-card"><h2>${label('Sobriété et iPad', 'Low-impact design and iPad')}</h2>
        <p>${label('Application statique, sans pisteur ni appel IA. Données lourdes préparées une fois. Couches chargées à la demande, calculs dans un Web Worker. Le cache hors ligne est explicite ; le système peut supprimer des données mises en cache.', 'Static application, no trackers or AI calls. Heavy processing runs once. Layers load on demand, calculations run in a Web Worker. Offline caching is explicit; the operating system may evict cached data.')}</p>
        <p>${label('Les calculs réguliers se lancent pendant que l’application est ouverte. Les actualisations automatiques régionales doivent tourner sur un ordinateur. Les performances sur iPad physique ne sont pas encore mesurées.', 'Regular computations run while the app is open. Automated regional refreshes should run on a computer. Performance on a physical iPad has not yet been measured.')}</p>
        <button id="cache-offline" class="outline-button">${label('Préparer les couches hors ligne', 'Prepare layers for offline use')}</button>
      </article>
      <article class="document-card"><h2>${label('Prochaines validations', 'Next validation steps')}</h2>
        <p>${label('Valider MOS/RPG pour P, les friches et le foncier pour O, puis intégrer le SRCE. Comparer au moins trois résultats avec des situations documentées et un écologue. Étendre à toute la Normandie uniquement après contrôle de couverture.', 'Validate MOS/RPG for P, brownfields and land availability for O, then integrate SRCE. Compare at least three results against documented situations with an ecologist. Extend across Normandy only after coverage checks.')}</p>
        <p>${label('NSGA-II reste une extension optionnelle non implémentée. Hadoop/Spark ne sont pas utilisés ; le traitement distribué ne serait pertinent qu’à une échelle bien supérieure.', 'NSGA-II remains an optional, unimplemented extension. Hadoop/Spark are not used; distributed processing would only be relevant at substantially larger scales.')}</p>
      </article>
    </div>`;
}

export function sourcesPage(language, catalogue, summary) {
  const en = language === 'en';
  return `
    <div class="eyebrow">${en ? 'TRACEABLE OPEN DATA' : 'DONNÉES OUVERTES ET TRAÇABLES'}</div>
    <h1>${en ? 'Every layer has a source.' : 'Chaque couche a une source.'}</h1>
    <p class="lead">${en ? 'Original producers, observation years, processing and limitations. No synthetic landscape values.' : 'Producteurs, millésimes, traitements et limites. Aucune valeur territoriale synthétique.'}</p>
    <p class="micro">Build: ${e(summary.built_at)} · ${e(summary.site)}</p>
    <a class="outline-button" href="data/data_catalog.json" download>data_catalog.json ↓</a>
    <a class="outline-button" href="data/manifest.json" download>SHA-256 manifest ↓</a>
    ${catalogue.map(source => `
      <article class="source-card">
        <span class="result-status">${source.status === 'used' ? (en ? 'INGESTED' : 'INTÉGRÉ') : source.status === 'context' ? (en ? 'CONTEXT' : 'CONTEXTE') : (en ? 'UNAVAILABLE' : 'INDISPONIBLE')}</span>
        <h2>${e(source.title)}</h2>
        ${source.issue ? `<p>${e(source.issue)}</p>` : `
          <p>${e(source.producer)} · ${e(source.licence)} · ${source.years.length ? source.years.join(' / ') : (en ? 'Reference year not verified' : 'Année de référence non vérifiée')}</p>
          <p>${e(source.resolution)}<br>${e(source.crs)}</p>
          <p>${e(source.processing)}</p>
          <a href="${e(source.url)}" target="_blank" rel="noopener noreferrer">${en ? 'Open producer catalogue' : 'Consulter le catalogue du producteur'} ↗</a>
          <code>SHA-256 ${e(source.sha256)}</code>`}
      </article>`).join('')}`;
}
