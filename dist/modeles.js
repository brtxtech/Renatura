// Renatura · « Modèles IA »: one data-flow canvas per model (same look as the « Ajouter des données » workflow),
// built from data/normandie/ml_status.json (python -m pipeline.renatura_ai.run_normandie). No result is hard-coded.
import { $, esc, fmt } from './extensions-common.js';

const ORDER = ['territory_forecast', 'human_pressure', 'eco_vulnerability'];
const NW = 250, NH = 200, DX = 300;
// branch layout: the split feeds the trained model (top) and the persistence baseline (bottom), both feed validation
const LAYOUT = { sources: [0, 120], variables: [DX, 120], target: [2 * DX, 120], split: [3 * DX, 120],
  algo: [4 * DX, 0], baseline: [4 * DX, 250], validation: [5 * DX, 120], application: [6 * DX, 120] };
const EDGES = [['sources', 'variables'], ['variables', 'target'], ['target', 'split'],
  ['split', 'algo', 'apprentissage'], ['split', 'baseline', 'test'], ['algo', 'validation', 'prédiction'],
  ['baseline', 'validation', 'comparaison'], ['validation', 'application']];
const pts = v => fmt(100 * v, 2) + ' pt';
const num3 = v => (v == null ? '—' : fmt(v, 3));
const LABEL = { good: 'prêt', warn: 'réserve', bad: 'bloqué' };

function load(key) { try { return JSON.parse(localStorage.getItem(key) || '{}'); } catch { return {}; } }
function save(key, v) { try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* private mode */ } }

// rows: [{label, v, base}] ; scale = max value (1 for AUC / R²)
function bars(rows, format = num3, scale = null) {
  const peak = scale ?? Math.max(...rows.map(r => r.v ?? 0), 1e-9);
  return `<div class="mbars">${rows.map(r => `<div class="mbar ${r.base ? 'base' : ''}"><span>${esc(r.label)}</span>
    <i style="width:${Math.max(2, (r.v ?? 0) / peak * 100)}%"></i><b>${format(r.v)}</b></div>`).join('')}</div>`;
}

const ok = m => m.status === 'performant' ? 'good' : m.status === 'blocked' ? 'bad' : 'warn';
const STATUS_TEXT = { performant: 'Performant', trained_exploratory: 'Exploratoire', trained_not_better_than_baseline: 'Ne bat pas la référence', blocked: 'Non disponible' };

// ---------- step content: short text on the box, full detail in the inspector
function steps(id, m, d) {
  const trained = m.status && m.status !== 'blocked', cls = m.task === 'classification', b = m.baseline || {};
  const tOk = m.target_spec?.available, after = trained ? 'good' : 'bad';
  const headline = !trained ? '—' : cls ? `AUC ${num3(m.auc)} · référence ${num3(b.auc)}` : `R² ${num3(m.r2)} · référence ${num3(b.r2)}`;
  return {
    sources: { icon: 'SRC', title: 'Sources de données', state: 'good', footer: 'observations',
      desc: (m.sources || []).join(' · '), inner: `${fmt(d.cells)} mailles de 1 km²`,
      detail: `<ul>${(m.sources || []).map(x => `<li>${esc(x)}</li>`).join('')}<li>${esc(d.grid)}</li></ul>
        <div class="note">Une maille non observée reste vide (NaN), jamais 0.</div>` },
    variables: { icon: 'VAR', title: `Variables (${m.features.length})`, state: m.features.every(f => f.available) ? 'good' : 'warn',
      footer: 'entrées du modèle', desc: m.features.slice(0, 3).map(f => f.label.replace(/ \(.*\)/, '')).join(' · ') + (m.features.length > 3 ? '…' : ''),
      inner: `${m.features.filter(f => f.available).length}/${m.features.length} disponibles`,
      detail: `<ul>${m.features.map(f => `<li class="${f.available ? '' : 'missing'}">${esc(f.label)} <code>${esc(f.id)}</code></li>`).join('')}</ul>` },
    target: { icon: 'Y', title: 'Cible observée', state: tOk ? 'good' : 'bad', footer: tOk ? 'mesure indépendante' : 'manquante',
      desc: m.target_spec?.label || '', inner: cls ? 'événement (oui / non)' : 'valeur continue',
      detail: tOk ? `<p>${esc(m.target_spec.label)}</p>
          <div class="note">La cible est une observation (CORINE, INSEE), pas un score calculé par Renatura : pas de circularité avec V, D, P, O.</div>`
        : `<div class="note bad">${esc(m.reason || 'Cible manquante')}</div>` },
    split: { icon: 'T/T', title: 'Découpage apprentissage / test', state: after, footer: 'temps + espace',
      desc: trained ? 'Test plus récent que l’apprentissage, sur des mailles jamais vues' : 'Impossible sans cible',
      inner: trained ? `${fmt(m.n_train)} exemples · ${fmt(m.n_test)} en test` : '—',
      detail: trained ? `<div class="k">apprentissage</div><p>${esc(m.train)} · ${fmt(m.n_train)} exemples</p>
          <div class="k">test</div><p>${esc(m.test)} · ${fmt(m.n_test)} mailles</p>
          <div class="note">Partition des mailles par hachage (20 % en test). Des blocs géographiques seraient plus stricts.</div>`
        : '<div class="note bad">Il faut des observations de la cible sur au moins deux dates et des mailles séparées.</div>' },
    algo: { icon: 'ML', title: 'Modèle appris', state: trained ? 'good' : 'warn', footer: 'scikit-learn',
      desc: cls ? 'HistGradientBoostingClassifier' : 'HistGradientBoostingRegressor', inner: trained ? 'entraîné' : 'prêt, non entraîné',
      detail: `<p>${esc(m.algorithm)}</p><div class="note">Valeurs manquantes : médiane apprise sur l’apprentissage seulement + indicateur d’absence. Jamais remplacées par 0.</div>` },
    baseline: { icon: 'REF', title: 'Référence simple', state: after, footer: 'à battre',
      desc: b.name || '—', inner: trained ? (cls ? `AUC ${num3(b.auc)}` : `R² ${num3(b.r2)}`) : '—',
      detail: `<p>${esc(b.name || '')}</p><p>Le modèle n’est jugé utile que s’il fait nettement mieux que cette règle simple sur la période de test.</p>` },
    validation: { icon: 'VAL', title: 'Validation', state: trained ? ok(m) : 'bad', footer: cls ? 'AUC · précision moyenne' : 'R² · erreur moyenne',
      desc: trained ? (m.beats_baseline ? 'Le modèle bat nettement la référence' : 'Le modèle ne bat pas la référence') : 'Pas de validation possible',
      inner: headline,
      detail: !trained ? '<div class="note bad">Aucune métrique sans cible observée.</div>' : cls
        ? `<div class="k">AUC (0,5 = hasard, 1 = parfait)</div>${bars([{ label: 'Modèle', v: m.auc }, { label: 'Référence', v: b.auc, base: true }], num3, 1)}
           <div class="k">précision moyenne (mailles réellement concernées)</div>${bars([{ label: 'Modèle', v: m.average_precision }, { label: 'Référence', v: b.average_precision, base: true }, { label: 'Hasard', v: m.base_rate, base: true }])}
           <p class="micro">Taux de base : ${fmt(100 * m.base_rate, 1)} % des mailles de test ont connu l’événement.</p>${id === 'territory_forecast' ? periodsChart(d) : ''}
           <ul>${(m.caveats || []).map(c => `<li>${esc(c)}</li>`).join('')}</ul>`
        : `<div class="k">R² (part de la variation expliquée)</div>${bars([{ label: 'Modèle', v: m.r2 }, { label: 'Référence', v: b.r2, base: true }], num3, 1)}
           <div class="k">erreur moyenne (log10 hab/km²)</div>${bars([{ label: 'Modèle', v: m.mae }, { label: 'Référence', v: b.mae, base: true }])}
           <ul>${(m.caveats || []).map(c => `<li>${esc(c)}</li>`).join('')}</ul>` },
    application: { icon: 'OUT', title: 'Application', state: trained ? ok(m) : 'bad', footer: STATUS_TEXT[m.status] || m.status,
      desc: trained ? (m.output || '') : 'Répond « Non disponible / données insuffisantes »',
      inner: trained ? 'CLI · API · Assistant IA' : 'aucun chiffre produit',
      detail: trained ? `<p>${esc(m.output || '')}</p><ul><li>Ligne de commande : <code>python -m pipeline.renatura_ai.apply --commune Caen</code></li>
          <li>API : <code>POST /predict/${esc(id)}</code></li><li>Assistant IA : outil <code>run_models</code></li></ul>`
        : '<p>L’API renvoie 503 et l’assistant « Non disponible ».</p>' },
  };
}

function periodsChart(d) {
  const p = d.periods || [], peak = Math.max(...p.map(x => x.changement_moyen_pts), 1e-9);
  return `<div class="k">changement moyen observé par période</div><div class="mperiods">${p.map((x, i) => `<div class="${i === p.length - 1 ? 'test' : ''}">
    <b style="height:${Math.max(4, x.changement_moyen_pts / peak * 60)}px"></b>${esc(x.periode)}<br>+${fmt(x.changement_moyen_pts, 2)} pt</div>`).join('')}</div>
    <p class="micro">Vert : apprentissage · orange : test.</p>`;
}

// ---------- one canvas
function canvas(section, id, m, d) {
  const S = steps(id, m, d), key = `renatura-models-pos-${id}`;
  let pos = load(key), zoom = null, scale = 1, selected = 'target', moved = false;
  const L = () => Object.fromEntries(Object.keys(LAYOUT).map(k => [k, pos[k] || LAYOUT[k]]));
  const geom = (P, a, c) => {
    const x1 = P[a][0] + NW, y1 = P[a][1] + NH / 2, x2 = P[c][0], y2 = P[c][1] + NH / 2, dx = Math.max(60, Math.abs(x2 - x1) / 2);
    return { d: `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`, mx: (x1 + x2) / 2, my: (y1 + y2) / 2 };
  };
  const inspector = section.querySelector('.inspector'), graph = section.querySelector('.graph');
  function inspect() {
    const s = S[selected];
    inspector.innerHTML = `<div class="eyebrow">Configuration de l’étape</div><h3>${esc(s.title)}</h3>
      <span class="status s-${s.state}">${LABEL[s.state]}</span>${s.detail}`;
  }
  // « Ajuster » = the whole workflow fits the frame width and is centred; +/− zoom from there (scrolls when larger).
  function fit() {
    const vp = graph.querySelector('.n8n-viewport'), sizer = graph.querySelector('.n8n-sizer'), st = graph.querySelector('.n8n-stage');
    const w = parseFloat(st.style.width), h = parseFloat(st.style.height), pad = 32, top = 56;
    scale = zoom ?? Math.min(1, Math.max(.3, (vp.clientWidth - pad) / w));
    st.style.transform = `scale(${scale})`;
    sizer.style.width = Math.ceil(w * scale) + 'px';
    sizer.style.height = Math.ceil(h * scale) + 'px';
    vp.style.height = Math.ceil(h * scale + top + 16 + 2) + 'px';
    const label = graph.querySelector('[data-z="fit"]');
    if (label) label.textContent = `Ajuster · ${Math.round(scale * 100)} %`;
  }
  function render() {
    const P = L(), W = Math.max(...Object.values(P).map(p => p[0])) + NW + 12, H = Math.max(...Object.values(P).map(p => p[1])) + NH + 12;
    const edges = EDGES.map(([a, c, lab]) => {
      const g = geom(P, a, c), st = S[c].state === 'bad' || S[a].state === 'bad' ? 'bad' : S[c].state === 'warn' ? 'warn' : 'done';
      return `<path class="n8n-edge ${st}" data-a="${a}" data-c="${c}" d="${g.d}"/>` + (lab ? `<g class="n8n-edge-label ${st === 'bad' ? 'bad' : ''}" data-a="${a}" data-c="${c}">
        <rect x="${g.mx - 52}" y="${g.my - 12}" width="104" height="24" rx="12"/><text x="${g.mx}" y="${g.my + 5}" text-anchor="middle">${lab}</text></g>` : '');
    }).join('');
    const boxes = Object.entries(S).map(([k, s], i) => `<article class="box ${s.state} ${k === selected ? 'selected' : ''}" data-box="${k}" tabindex="0" role="button"
        aria-label="Étape ${esc(s.title)}" style="left:${P[k][0]}px;top:${P[k][1]}px;width:${NW}px;height:${NH}px">
        ${k !== 'sources' ? '<span class="port in"></span>' : ''}${k !== 'application' ? '<span class="port out"></span>' : ''}
        <div class="box-head"><span class="box-icon">${s.icon}</span><div><h4>${esc(s.title)}</h4><small>étape ${i + 1}</small></div>
          <span class="status s-${s.state}">${LABEL[s.state]}</span></div>
        <div class="box-description">${esc(s.desc)}</div><div class="box-inner">${esc(s.inner)}</div>
        <div class="box-footer">${esc(s.footer)}</div></article>`).join('');
    graph.innerHTML = `<div class="n8n-frame"><span class="hint">Cliquer une étape pour son détail · glisser pour déplacer</span>
        <div class="zoom"><button data-z="-" title="Dézoomer">−</button><button data-z="fit" title="Tout le flux dans le cadre">Ajuster</button>
        <button data-z="+" title="Zoomer">+</button><button data-z="reset" title="Remettre les boîtes à leur place">Disposition</button></div>
      <div class="n8n-viewport"><div class="n8n-sizer"><div class="n8n-stage" style="width:${W}px;height:${H}px">
        <svg class="n8n-edges" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" aria-hidden="true"><defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5"
          markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z"/></marker></defs>${edges}</svg>${boxes}</div></div></div></div>
      <div class="legend"><span class="k"></span> étape prête <span class="k warn"></span> avec réserve <span class="k bad"></span> bloquée (aucun chiffre produit)</div>`;
    fit();
    graph.querySelectorAll('[data-z]').forEach(b => b.onclick = () => {
      const v = b.dataset.z;
      if (v === 'reset') { pos = {}; save(key, pos); render(); return; }
      zoom = v === 'fit' ? null : Math.min(1.6, Math.max(.4, (zoom ?? scale) + (v === '+' ? .1 : -.1)));
      fit();
    });
    graph.querySelectorAll('.box').forEach(el => {
      el.addEventListener('click', () => { if (moved) { moved = false; return; } selected = el.dataset.box; render(); inspect(); });
      el.addEventListener('keydown', e => { if (e.key === 'Enter') { selected = el.dataset.box; render(); inspect(); } });
      el.addEventListener('pointerdown', e => {
        if (e.button !== 0) return;
        const k = el.dataset.box, sx = e.clientX, sy = e.clientY, [ox, oy] = P[k];
        let dragging = false;
        const move = ev => {
          const dx = (ev.clientX - sx) / scale, dy = (ev.clientY - sy) / scale;
          if (!dragging && Math.hypot(dx, dy) < 4) return;
          dragging = true; el.classList.add('dragging');
          P[k] = [Math.max(0, Math.round((ox + dx) / 5) * 5), Math.max(0, Math.round((oy + dy) / 5) * 5)];
          el.style.left = P[k][0] + 'px'; el.style.top = P[k][1] + 'px';
          graph.querySelectorAll(`[data-a="${k}"],[data-c="${k}"]`).forEach(p => {
            const g = geom(P, p.dataset.a, p.dataset.c);
            if (p.tagName === 'path') p.setAttribute('d', g.d);
            else { const r = p.querySelector('rect'), t = p.querySelector('text'); r.setAttribute('x', g.mx - 52); r.setAttribute('y', g.my - 12); t.setAttribute('x', g.mx); t.setAttribute('y', g.my + 5); }
          });
        };
        const up = () => {
          removeEventListener('pointermove', move); removeEventListener('pointerup', up); removeEventListener('pointercancel', up);
          if (!dragging) return;
          moved = true; setTimeout(() => { moved = false; }, 0);
          pos[k] = P[k]; save(key, pos); render();
        };
        addEventListener('pointermove', move); addEventListener('pointerup', up); addEventListener('pointercancel', up);
      });
    });
  }
  render(); inspect();
  addEventListener('resize', () => { if (zoom == null) fit(); });
}

function badge(m) {
  if (m.status === 'blocked') return '<span class="badge bad">Bloqué · cible manquante</span>';
  return m.status === 'performant' ? '<span class="badge ok">Performant · bat nettement la référence</span>'
    : m.beats_baseline ? '<span class="badge warn">Exploratoire · bat la référence</span>' : '<span class="badge warn">Entraîné · ne bat pas la référence</span>';
}

try {
  const r = await fetch('data/normandie/ml_status.json', { cache: 'no-store' });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const s = await r.json(), d = s.data_summary;
  $('#data-card').innerHTML = `<strong>Données d’apprentissage</strong>
    <p class="micro" style="margin:6px 0 0">${fmt(d.cells)} mailles de 1 km². Sources : ${esc(d.source)}.
      Chaque modèle apprend d’une cible observée et indépendante, et il est testé sur une période plus récente, sur des mailles jamais vues.
      Calculé le ${esc(new Date(s.built_at).toLocaleString('fr-FR'))}.</p>`;
  for (const id of ORDER.filter(k => s.models[k])) {
    const m = s.models[id], sec = document.createElement('section');
    sec.className = 'card model';
    sec.innerHTML = `<div class="model-head"><h2>${esc(m.title || id)}</h2>${badge(m)}<code>${esc(id)}</code></div>
      <p class="question">${esc(m.question || '')}</p><div class="layout"><aside class="inspector" aria-live="polite"></aside><div class="graph"></div></div>`;
    $('#models').append(sec);
    canvas(sec, id, m, d);
  }
} catch (e) {
  $('#status').hidden = false;
  $('#status').textContent = `Statut des modèles indisponible (${e.message}) : lancer python -m pipeline.renatura_ai.run_normandie.`;
}
