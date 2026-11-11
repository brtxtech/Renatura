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
    <div class="coverage-note"><span>!</span><p>${label('Version régionale : maillage de toute la Normandie. V, D, P et O sont calculés pour toutes les mailles ; la priorité de restauration (RP) et la priorité de protection (PP) en découlent.', 'Regional grid across Normandy. V, D, P and O are computed for every cell; restoration priority (RP) and protection priority (PP) derive from them.')}</p></div>
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
        <p>${label('Dans la méthode originale, NetworkX relie les cellules adjacentes. Les connexions sont recalculées par complete_region.py sur les mailles ayant V et une surface boisée observés. Les mailles inconnues sont exclues. Aucune connexion du pilote n’est recopiée. Les groupes de cellules V≥60 sont des réservoirs structurels supposés. Les chemins de moindre coût connectent au maximum les douze plus grands groupes, mesurés par surface boisée. L’intermédiarité est échantillonnée au-delà de 128 mailles (graine 42).', 'NetworkX links adjacent cells. Groups of V≥60 cells are assumed structural habitat cores. Least-cost paths connect the twelve largest groups, measured by woodland area.')}</p>
        <div class="formula">résistance = distance × (1 + 4 × (1 − V moyen / 100))<br>gain brut = √(surface boisée A × surface boisée B)</div>
        <p>${label('Gain normalisé entre les connexions. Une route est créditée une fois, seulement si toutes ses cellules intermédiaires sont sélectionnées. Les gains entre paires ne représentent pas des hectares uniques. Aucune calibration par espèce ; pas de validation terrain.', 'Gain normalised across connections. A route earns credit once, only if every intermediate cell is selected. Pairwise gains do not represent unique hectares. No species calibration or field validation.')}</p>
      </article>
      <article class="document-card"><h2>04 · ${label('Optimiser sans surpromettre', 'Optimise without overclaiming')}</h2>
        <div class="formula">max Σ(RPᵢ × surfaceᵢ / surface d’une maille complète × xᵢ) + λ Σ(gainₚ × yₚ)<br>Σ(coûtᵢ × xᵢ) ≤ enveloppe · surfaceᵢ ≥ surface minimale<br>xᵢ, yₚ ∈ {0,1}</div>
        <p>${label('Dans le projet original, PuLP/CBC calcule les scénarios hors ligne. Aucun scénario du pilote n’est réutilisé comme résultat régional. Le moteur navigateur original est conservé. Dans le navigateur : recherche bornée à 3 secondes, solution réalisable et borne supérieure si la preuve est incomplète. Les comparaisons appliquent le même périmètre, les mêmes poids et le même budget.', 'PuLP/CBC computes offline scenarios. In the browser: search capped at 3 seconds, with a feasible result and upper bound when proof is incomplete. Comparisons use identical scope, weights and budget.')}</p>
        <p>${label('Trois enveloppes : nombre de mailles, surface en hectares, ou budget foncier en k€ (prix médian DVF 2021–2025 de la maille × surface ; prix d’achat indicatif du terrain, sans les travaux). Chaque maille vaut sa priorité multipliée par sa part de maille complète : un fragment côtier de 3 ha vaut 3 % d’une maille de 100 ha, et les mailles sous la surface minimale (50 ha par défaut) sont exclues. Sur la région, le navigateur complète la recherche par des échanges ciblés sur les corridors ; écart à l’optimum CBC inférieur à 1 % sur les cas testés (tests/scenarios/coherence.test.mjs).', 'Three envelopes: number of cells, area in hectares, or land budget in k€ (cell median DVF 2021–2025 price × area; indicative land price, works excluded). Each cell is worth its priority times its share of a complete cell: a 3 ha coastal sliver is worth 3 % of a 100 ha cell, and cells below the minimum area (50 ha by default) are excluded. Regionally, the browser adds targeted corridor swaps; gap to the CBC optimum below 1 % on tested cases (tests/scenarios/coherence.test.mjs).')}</p>
        <p>${label('Aucune hypothèse de disponibilité foncière. Les cellules sont des unités de planification, pas des parcelles prêtes à restaurer.', 'No assumption of land availability. Cells are planning units, not restoration-ready parcels.')}</p>
      </article>
      <article class="document-card"><h2>05 · ${label('Protéger avant de restaurer', 'Protect before restoring')}</h2>
        <p>${label('Le bouton « Protection » répond à une autre question que « Restauration » : où se trouve une nature de valeur, encore peu dégradée et soumise à une pression humaine, qu’il faudrait protéger avant qu’elle ne se dégrade ?', 'The “Protection” view answers a different question from “Restoration”: where is valuable, still intact nature under human pressure that should be protected before it degrades?')}</p>
        <div class="formula">PP brut = V × (1 − D / 100) × P / 100<br>PP = rang percentile du PP brut parmi les 30 850 mailles (0–100)<br>lacune de protection = PP ≥ 70 et ni réserve naturelle, ni APB, ni Natura 2000, ni ORE</div>
        <p>${label('Même formule que protection_score() du modèle régional Python. Elle ne dépend pas des pondérations de RP. Statut actuel d’après les désignations touchant la maille (même partiellement) : protection forte (réserve naturelle nationale ou régionale, arrêté de protection de biotope), Natura 2000 / ORE, inventaire seul (ZNIEFF, qui n’est pas une protection), aucune.', 'Same formula as protection_score() in the Python regional model. Independent of the RP weights. Current status from the designations touching the cell (even partially): strong (national or regional nature reserve, biotope protection order), Natura 2000 / easement, inventory only (ZNIEFF, not a protection), none.')}</p>
        <p>${label('Contrôle de cohérence : les mailles déjà protégées ont une PP moyenne nettement plus élevée (≈ 74 en protection forte, 59 en Natura 2000, 54 en ZNIEFF seule, 37 sans désignation) ; la formule retrouve donc les secteurs que les politiques publiques ont déjà jugés à protéger. Les lacunes sont des pistes à vérifier sur le terrain, pas une proposition de classement réglementaire.', 'Consistency check: already protected cells have a much higher mean PP (≈ 74 strong, 59 Natura 2000, 54 ZNIEFF only, 37 none), so the formula recovers areas public policy already protects. Gaps are leads to verify on the ground, not a proposal for regulatory designation.')}</p>

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

const CRITERION_LABELS = {
  V: { fr: 'V · Valeur écologique reconnue', en: 'V · Recognised ecological value' },
  D: { fr: 'D · Dégradation / besoin de restauration', en: 'D · Degradation / restoration need' },
  P: { fr: 'P · Pression anthropique', en: 'P · Anthropogenic pressure' },
  O: { fr: "O · Opportunité d'action documentée", en: 'O · Documented action opportunity' },
};
const AGG_LABELS = {
  area: { fr: 'surface', en: 'area' }, length: { fr: 'linéaire', en: 'length' },
  count: { fr: 'points', en: 'points' }, inverse_area: { fr: '1 − surface', en: '1 − area' },
  growth: { fr: 'croissance', en: 'growth' }, pilot: { fr: 'pilote FR2502014', en: 'FR2502014 pilot' },
};
const COVERAGE_LABELS = {
  regional: { fr: 'régionale (absence = 0)', en: 'regional (absence = 0)' },
  territorial: { fr: 'territoriale (hors zone = non couvert)', en: 'territorial (outside zone = uncovered)' },
  presence: { fr: 'présence seulement (absence = inconnu)', en: 'presence-only (absence = unknown)' },
};

export function pressureMethodology(language, summary, layerScoring) {
  const en = language === 'en';
  const label = (fr, english) => en ? english : fr;
  const audit = summary?.scoring_audit;
  const cfg = layerScoring;

  if (!cfg || !audit) {
    return `<div class="eyebrow">${label('MÉTHODOLOGIE', 'METHODOLOGY')}</div>
      <h1>${label('Comment V, D, P et O sont calculés.', 'How V, D, P and O are calculated.')}</h1>
      <p class="lead">${label('Chargement du détail des couches…', 'Loading layer detail…')}</p>`;
  }

  const byCriterion = {};
  for (const l of cfg.layers) (byCriterion[l.c] ||= []).push(l);
  for (const c of Object.keys(byCriterion)) byCriterion[c].sort((a, b) => b.w - a.w);

  const layerRow = (l) => `
    <tr>
      <td>${e(l.label)}</td>
      <td class="num">${l.w.toFixed(1)}</td>
      <td>${e((AGG_LABELS[l.agg] || {})[en ? 'en' : 'fr'] || l.agg)}</td>
      <td>${e((COVERAGE_LABELS[l.coverage] || {})[en ? 'en' : 'fr'] || l.coverage)}${l.territory ? ` · ${e(l.territory)}` : ''}</td>
    </tr>`;

  const criterionBlock = (c) => {
    const layers = byCriterion[c] || [];
    const stats = audit.criteria[c];
    return `
      <article class="document-card">
        <h2>${e(CRITERION_LABELS[c][en ? 'en' : 'fr'])}</h2>
        <p class="micro">${label(`${layers.length} couches pondérées · ${number(stats.covered_pct, 0, language)}% des mailles couvertes · ${number(stats.distinct_values)} valeurs distinctes · plus grande valeur partagée : ${stats.modal_share_pct}% des mailles`,
          `${layers.length} weighted layers · ${number(stats.covered_pct, 0, language)}% of cells covered · ${number(stats.distinct_values)} distinct values · largest shared value: ${stats.modal_share_pct}% of cells`)}</p>
        <div class="table-scroll"><table class="source-table">
          <tr><th>${label('Couche', 'Layer')}</th><th>${label('Poids', 'Weight')}</th><th>${label('Mesure', 'Measured as')}</th><th>${label('Couverture', 'Coverage')}</th></tr>
          ${layers.map(layerRow).join('')}
        </table></div>
      </article>`;
  };

  return `
    <div class="eyebrow">${label('MÉTHODOLOGIE RÉGIONALE · 78 COUCHES', 'REGIONAL METHODOLOGY · 78 LAYERS')}</div>
    <h1>${label('Comment V, D, P et O sont calculés.', 'How V, D, P and O are calculated.')}</h1>
    <p class="lead">${label('Les 4 critères sont des indices composites construits à partir de couches réelles du catalogue régional (pas de données inventées). Cette page détaille, pour chacun, les couches utilisées, leur poids, et la formule qui les combine.', 'All 4 criteria are composite indices built from real layers in the regional catalogue (no invented data). This page details, for each, the layers used, their weight, and the formula that combines them.')}</p>

    <article class="document-card">
      <h2>01 · ${label('Avant / après', 'Before / after')}</h2>
      <table class="source-table">
        <tr><th></th><th>${label('Avant', 'Before')}</th><th>${label('Après', 'After')}</th></tr>
        <tr><td>${label('Mailles avec V / D / P / O', 'Cells with V / D / P / O')}</td><td>145 / 145 / 30 850 / 0</td><td>30 850 ${label('pour chacun', 'for each')}</td></tr>
        <tr><td>${label('Mailles avec les 4 critères', 'Cells with all 4 criteria')}</td><td>0</td><td>30 850</td></tr>
        <tr><td>${label('Éligibles au classement (V ≥ 10)', 'Eligible for ranking (V ≥ 10)')}</td><td>145</td><td>${number(audit.eligible_cells)} (${number(audit.eligible_pct,0,language)}%)</td></tr>
        <tr><td>${label('Couches alimentant les scores', 'Layers feeding the scores')}</td><td>3 (+ pilote)</td><td>${audit.distinct_sources} ${label('sources', 'sources')}, ${audit.layers_used} ${label('rôles', 'roles')}</td></tr>
        <tr><td>${label('Valeurs distinctes par critère', 'Distinct values per criterion')}</td><td>P ${label('surtout 0', 'mostly 0')}</td><td>≈ 9 600–9 900</td></tr>
      </table>
      <p class="micro">${label('Avant la correction, V et D n’existaient que pour les 145 mailles du pilote Pays d’Auge (FR2502014) ; P ne venait que de 3 couches ; O était toujours absent. Le score global (RP) exige V ≥ 10 pour être calculé, donc 99,5% des mailles affichaient « — ».', 'Before the fix, V and D only existed for the 145 cells of the Pays d’Auge pilot (FR2502014); P came from only 3 layers; O was always absent. The overall score (RP) requires V ≥ 10 to compute, so 99.5% of cells showed "—".')}</p>
    </article>

    <article class="document-card">
      <h2>02 · ${label('La formule, en 3 étapes', 'The formula, in 3 steps')}</h2>
      <div class="formula">
        1) rang(couche) = percentile 0–100 de la valeur brute de CETTE couche sur les mailles qu’elle couvre<br>
        &nbsp;&nbsp;&nbsp;(0 réel reste 0 ; hors couverture = absent, jamais 0)<br><br>
        2) critère = Σ(poids × rang(couche)) / Σ(poids des couches qui couvrent la maille)<br>
        &nbsp;&nbsp;&nbsp;${label('calculé seulement si ≥', 'computed only if ≥')} ${Math.round(cfg.min_weight_coverage * 100)}% ${label('du poids total couvre la maille', 'of total weight covers the cell')}<br><br>
        3) ${label('résultat final = nouveau rang percentile régional de ce critère composite', 'final result = new regional percentile rank of that composite criterion')}
      </div>
      <p>${label('Chaque couche est d’abord classée en rang percentile indépendamment, pour ne jamais mélanger des unités incomparables (hectares, mètres, nombre de points). Les couches sont ensuite combinées par une moyenne pondérée par critère, puis le résultat repasse une dernière fois en rang percentile régional pour que V, D, P et O restent comparables entre eux.', 'Each layer is first ranked into a percentile independently, so incomparable units (hectares, metres, point counts) are never mixed. Layers are then combined with a weighted average per criterion, and the result passes through one final regional percentile rank so V, D, P and O stay comparable with each other.')}</p>
      <h3 style="font-size:.82rem;margin:14px 0 6px;color:var(--muted);text-transform:uppercase;letter-spacing:.02em">${label('Trois classes de couverture', 'Three coverage classes')}</h3>
      <p><b>${label('Régionale', 'Regional')}</b> — ${label('couche complète sur toute la région : une maille sans objet vaut vraiment 0.', 'layer complete across the whole region: a cell with no object genuinely scores 0.')}</p>
      <p><b>${label('Territoriale', 'Territorial')}</b> — ${label('couche complète sur un territoire connu (ex. un EPCI avec sa propre TVB) : 0 dans le territoire, mais absente (jamais 0) hors de ce territoire.', 'layer complete over a known territory (e.g. an EPCI with its own TVB): 0 inside the territory, but absent (never 0) outside it.')}</p>
      <p><b>${label('Présence seulement', 'Presence-only')}</b> — ${label('extraction partielle (limite de pages WFS) : un objet trouvé ajoute une preuve, mais une absence reste inconnue — elle ne peut jamais faire baisser un score.', 'partial extraction (WFS page limit): a found object adds evidence, but absence stays unknown — it can never lower a score.')}</p>
      <p class="micro">${label('Diffusion pour O : chaque maille reçoit aussi 40% de la moyenne pondérée (distance-décroissante, portée 5 km) des mailles voisines — une opportunité documentée profite un peu à son voisinage, pas seulement à la maille exacte.', 'Diffusion for O: each cell also receives 40% of the distance-weighted average (5 km reach) of neighbouring cells — a documented opportunity benefits its surroundings a little, not only the exact cell.')}</p>
    </article>

    <div class="document-grid">
      ${criterionBlock('V')}
      ${criterionBlock('D')}
      ${criterionBlock('P')}
      ${criterionBlock('O')}
    </div>

    <article class="document-card">
      <h2>03 · ${label('Validation : est-ce que ça correspond au pilote ?', 'Validation: does this agree with the pilot?')}</h2>
      <p>${label('Le pilote Pays d’Auge (FR2502014) a des haies et boisements mesurés sur le terrain — c’est la référence la plus fiable disponible. La corrélation de rang (Spearman) entre les nouveaux V/D régionaux et le V/D original du pilote, sur les 145 mailles pilote :', 'The Pays d’Auge pilot (FR2502014) has field-measured hedgerows and woodland — the most reliable reference available. The rank correlation (Spearman) between the new regional V/D and the pilot’s original V/D, on the 145 pilot cells:')}</p>
      <table class="source-table">
        <tr><th></th><th>${label('Avec la couche pilote incluse', 'With the pilot layer included')}</th><th>${label('Couches régionales seules (sans le pilote)', 'Regional layers only (pilot excluded)')}</th></tr>
        <tr><td>V</td><td class="num">${audit.pilot_agreement.spearman_V_vs_pilot_V?.toFixed(2)}</td><td class="num">${audit.pilot_agreement.independent_spearman_V_regional_layers_only?.toFixed(2)}</td></tr>
        <tr><td>D</td><td class="num">${audit.pilot_agreement.spearman_D_vs_pilot_D?.toFixed(2)}</td><td class="num">${audit.pilot_agreement.independent_spearman_D_regional_layers_only?.toFixed(2)}</td></tr>
      </table>
      <p class="micro">${label('Honnêteté : sans la couche pilote elle-même, les couches régionales seules ne reproduisent PAS la structure fine haies/bois du pilote (corrélation proche de 0). Aucun inventaire régional de haies ou de bois comparable n’existe encore dans le catalogue — c’est la prochaine donnée la plus utile à collecter, pas un défaut caché.', 'Honesty: without the pilot layer itself, the regional layers alone do NOT reproduce the pilot’s fine hedgerow/woodland structure (correlation near 0). No comparable regional hedgerow/woodland inventory exists yet in the catalogue — that is the single most valuable next dataset to collect, not a hidden flaw.')}</p>
    </article>

    <div class="coverage-note"><span>!</span><p>${label('Les poids sont des valeurs expertes, documentées et modifiables (tools/normandie/layer_scoring.json), pas calibrées sur des résultats de terrain. La sensibilité Monte-Carlo (±20%) mesure l’incertitude de préférence, pas la qualité des données. Les couches « présence seulement » ne peuvent que faire monter un score ; leur absence n’est jamais une pénalité.', 'Weights are documented, editable expert values (tools/normandie/layer_scoring.json), not calibrated against field outcomes. Monte-Carlo sensitivity (±20%) measures preference uncertainty, not data quality. "Presence-only" layers can only raise a score; their absence is never a penalty.')}</p></div>`;
}

export function sourcesPage(language, catalogue, summary) {
  const en = language === 'en';
  return `
    <div class="eyebrow">${en ? 'TRACEABLE OPEN DATA' : 'DONNÉES OUVERTES ET TRAÇABLES'}</div>
    <h1>${en ? 'Every layer has a source.' : 'Chaque couche a une source.'}</h1>
    <p class="lead">${en ? 'Original producers, observation years, processing and limitations. No synthetic landscape values.' : 'Producteurs, millésimes, traitements et limites. Aucune valeur territoriale synthétique.'}</p>
    <p class="micro">Build: ${e(summary.built_at)} · ${e(summary.site)}</p>
    <a class="outline-button" href="data/normandie/data_catalog.json" download>data_catalog.json ↓</a>
    <a class="outline-button" href="data/normandie/manifest.json" download>SHA-256 manifest ↓</a>
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
