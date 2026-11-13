"""Renatura assistant · chat loop (local open model through Ollama's OpenAI-compatible API) + HTTP routes.

The model never computes: every number comes from a tool (pipeline/assistant/tools.py).
Photos: the installed local models read text only, so a photo goes through
  1. EXIF GPS -> the matching 1 km² cell,
  2. the Renatura species model (EfficientNet, 739 Normandy species),
and both results are given to the model as text. A vision-language model can replace step 2 later.

Config (environment): RENATURA_LLM_URL (default http://localhost:11434/v1), RENATURA_LLM_MODEL
(default qwen2.5:7b-instruct). Nothing is sent outside the machine.
"""
from __future__ import annotations

import io
import json
import os
import re
import threading
import time

import requests
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from PIL import ExifTags, Image, ImageOps

from . import tools

BASE_URL = os.getenv('RENATURA_LLM_URL', 'http://localhost:11434/v1').rstrip('/')
MODEL = os.getenv('RENATURA_LLM_MODEL', 'qwen2.5:7b-instruct')
# Hugging Face option: RENATURA_LLM_URL=https://router.huggingface.co/v1 (Inference Providers) or a TGI endpoint .../v1,
# RENATURA_LLM_MODEL=<hub model id>, token in RENATURA_LLM_API_KEY or HF_TOKEN (sent as a header, never stored or logged).
API_KEY = os.getenv('RENATURA_LLM_API_KEY') or os.getenv('HF_TOKEN') or ''
PROVIDER = ('Hugging Face' if 'huggingface' in BASE_URL else 'Ollama (local)' if '11434' in BASE_URL else 'API compatible OpenAI')
LOCAL = BASE_URL.startswith(('http://localhost', 'http://127.0.0.1'))
MAX_IMAGE = 15 * 1024 * 1024

SYSTEM = """Tu es l'assistant IA de Renatura, l'atlas de restauration écologique de la Normandie.
Règles :
- Chaque chiffre vient d'un outil. N'invente jamais une valeur. Cite la couche (et son année quand elle est donnée).
- Une valeur absente s'écrit « donnée absente », jamais 0.
- Noms exacts des critères : V = Valeur écologique, D = Dégradation à réparer, P = Pression humaine, O = Opportunité d'action, RP = Priorité de restauration. N'emploie jamais d'autre nom.
- V, D, P, O et RP sont des rangs percentiles régionaux de 0 à 100 (comparaison aux 30 850 mailles), pas des pourcentages de surface. La part de forêt vient de BD Forêt V2, ce n'est pas un critère.
- N'invente pas le sens d'un sigle (APB, ZNIEFF, TVB, SRCE…) : écris-le tel quel.
- Signale une couche à couverture partielle (PARTIAL) quand elle intervient.
- Une corrélation n'est pas une cause : écris « ces indicateurs varient ensemble ici ».
- Ne propose jamais de boiser une prairie humide à maintenir, une zone humide, un site Ramsar ou un habitat ouvert protégé.
- Pour une photo : l'espèce proposée vient du modèle Renatura ; reste prudent (« probablement », « à confirmer par un naturaliste »).
- Tes recommandations sont une aide à la décision ; renvoie vers la DREAL, la DDTM ou l'ONF pour toute décision réglementaire.
- Si la question vise un lieu, appelle d'abord un outil avec la commune ou les coordonnées. N'utilise un cell_id que s'il apparaît dans la question, le contexte ou un résultat d'outil. Si le lieu manque, utilise le contexte de la page.
- Lis bien les unités : « part de surface » 0,30 = 30 % de la maille ; « part non bâtie » élevée = peu de bâti.
- Trois types de questions : (1) « que sait-on de cette zone » -> get_cell_profile / commune_summary ; (2) « quelle relation entre X et Y ici » -> correlate (écris « varient ensemble », jamais « cause ») ; (3) « que se passerait-il si la tendance continue » -> trend_projection (précise que c'est une extrapolation, pas une prévision).
- Pour justifier un score, utilise explain_index : il donne la formule, les poids et les couches.
- Pour une question qualitative (espèce, milieu, maladie, cohabitation, méthode), utilise search_knowledge et cite les titres des passages entre crochets [ainsi]. N'affirme rien qui ne soit dans un passage ou un résultat d'outil.
- Pour les modèles IA (risque d'artificialisation, de perte d'habitat, pression humaine), utilise run_models et model_status.
- Tu as accès à toutes les couches de l'Atlas régional (194 couches : biodiversité, eau, occupation du sol, paysages et patrimoine, littoral, énergie et climat, risques, carrières, mobilité, réglementation) : atlas_zone pour ce qui est présent autour d'un lieu, atlas_objects pour nommer les objets d'une couche (quelle ZNIEFF, quel parc éolien…), atlas_layers pour la liste. Une couche absente n'est pas une preuve d'absence.
- Prix des terrains (DVF 2021-2025) et bénéfice par euro (RP pour 10 000 €) : price_benefit. Cite la période, le nombre de ventes et le niveau (maille, voisinage, département) ; c'est un prix indicatif, pas une estimation.
- Le bénéfice par euro se donne en « points de RP pour 10 000 € », jamais en euros. Ne mentionne pas les carrés de 5 km pour une question de prix.
- Climat : climate_summary donne toutes les tendances observées d'un lieu (et le NDVI s'il est collecté) ; trend_projection prolonge un indicateur.
- Réponds en français, de façon concise (5 à 10 lignes), avec les identifiants de mailles cités tels quels.
Contexte de la page : {page_context}"""

router = APIRouter(prefix='/api/assistant')
_store, _lock = None, threading.Lock()


def store():
    global _store
    with _lock:
        if _store is None:
            _store = tools.Store()
        return _store


def _llm(messages, use_tools=True, model=None):
    body = {'model': model or MODEL, 'messages': messages, 'temperature': 0.2, 'stream': False}
    if use_tools:
        body['tools'] = tools.TOOLS
    headers = {'Authorization': f'Bearer {API_KEY}'} if API_KEY else {}
    r = requests.post(f'{BASE_URL}/chat/completions', json=body, headers=headers, timeout=240)
    if r.status_code >= 400:
        raise HTTPException(502, f'modèle local : HTTP {r.status_code} {r.text[:200]}')
    return r.json()['choices'][0]['message']


def _gps(img):
    try:
        gps = img.getexif().get_ifd(0x8825)
        g = {ExifTags.GPSTAGS.get(k, k): v for k, v in (gps or {}).items()}

        def deg(v):
            return float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
        lat = deg(g['GPSLatitude']) * (-1 if g.get('GPSLatitudeRef') == 'S' else 1)
        lon = deg(g['GPSLongitude']) * (-1 if g.get('GPSLongitudeRef') == 'W' else 1)
        return round(lon, 6), round(lat, 6)
    except Exception:
        return None


def analyse_photo(raw):
    """GPS -> cell, species model -> candidates. Never fails the chat: errors are reported as text."""
    out = {}
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as e:
        return {'erreur': f'image illisible ({type(e).__name__})'}
    gps = _gps(img)
    if gps:
        out['gps'] = {'lon': gps[0], 'lat': gps[1]}
        cid = store().resolve(lon=gps[0], lat=gps[1])
        out['cell_id'] = cid or 'hors de la grille Renatura'
    else:
        out['gps'] = 'absent (pas de coordonnées dans la photo)'
    try:
        from pipeline.workbench import species
        ok, why = species.available()
        if ok:
            p = species.predict(ImageOps.exif_transpose(img))
            out['espece'] = {'proposition': p['species']['scientific_name'], 'nom_francais': p['species']['french_name'],
                             'probabilite': p['species']['probability'], 'statut': p['status_label'],
                             'protegee_france': p['species']['protected_france'],
                             'liste_rouge_normandie': p['species']['red_list_normandie'],
                             'autres_candidats': [(c['scientific_name'], c['french_name'], c['probability']) for c in p['top5'][1:]]}
        else:
            out['espece'] = f'modèle d’espèces indisponible : {why}'
    except Exception as e:
        out['espece'] = f'détection en échec : {type(e).__name__}'
    return out


MAX_JSON = 5 * 1024 * 1024
JSON_CHARS = 12000  # what the model receives from an attached JSON file (local models have a small context)


def read_json_attachment(filename, raw):
    """Attached .json / .geojson -> readable text for the model: structure summary + content, truncated."""
    try:
        data = json.loads(raw.decode('utf-8-sig'))
    except (UnicodeDecodeError, ValueError) as e:
        raise ValueError(f'JSON invalide ({e})')
    head = []
    if isinstance(data, dict) and data.get('type') == 'FeatureCollection' and isinstance(data.get('features'), list):
        feats = data['features']
        geoms = sorted({(f.get('geometry') or {}).get('type') or 'sans géométrie' for f in feats if isinstance(f, dict)})
        keys = sorted({k for f in feats if isinstance(f, dict) for k in (f.get('properties') or {})})
        head.append(f'GeoJSON FeatureCollection : {len(feats)} objets ; géométries : {", ".join(geoms) or "aucune"} ; '
                    f'attributs : {", ".join(keys[:60]) or "aucun"}')
        # coordinates are long and useless to read: keep the attributes of the objects
        data = {'objets (attributs)': [(f.get('properties') or {}) for f in feats if isinstance(f, dict)]}
    elif isinstance(data, list):
        head.append(f'Liste JSON de {len(data)} éléments')
    elif isinstance(data, dict):
        head.append(f'Objet JSON ; clés : {", ".join(list(data)[:60])}')
    body = json.dumps(data, ensure_ascii=False, separators=(', ', ': '), default=str)
    truncated = len(body) > JSON_CHARS
    text = '\n'.join(head) + '\n' + body[:JSON_CHARS] + ('\n… (contenu tronqué)' if truncated else '')
    return {'nom': filename, 'resume': head[0] if head else 'JSON', 'tronque': truncated, 'texte': text}


def ask(question, page_context=None, history=None, photo=None, max_steps=6, model=None, attachment=None):
    s = store()
    trace = []
    text = question.strip() or ('Que contient ce fichier ?' if attachment else 'Que montre cette photo ?')
    if attachment is not None:
        text += f"\n\n[Fichier JSON joint : {attachment['nom']}]\n{attachment['texte']}"
    if photo is not None:
        text += '\n\n[Analyse automatique de la photo jointe] ' + json.dumps(photo, ensure_ascii=False)
    messages = [{'role': 'system', 'content': SYSTEM.format(page_context=json.dumps(page_context or {}, ensure_ascii=False))},
                *[m for m in (history or []) if m.get('role') in ('user', 'assistant') and isinstance(m.get('content'), str)][-8:],
                {'role': 'user', 'content': text}]
    # Grounding: small local models often answer "from memory". When the question, the page context or the
    # photo names a place, the server runs the tool itself and hands the result to the model first.
    for name, args in _prefetch(s, question, page_context or {}, photo):
        result = tools.FUNCS[name](s, **args)
        call_id = f'pre_{len(trace)}'
        trace.append({'tool': name, 'args': args, 'result': result, 'auto': True})
        messages.append({'role': 'assistant', 'content': '', 'tool_calls': [
            {'id': call_id, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args, ensure_ascii=False)}}]})
        messages.append({'role': 'tool', 'tool_call_id': call_id, 'content': json.dumps(result, ensure_ascii=False, default=str)})
    nudged = False
    known_text = question + (' ' + attachment['texte'] if attachment else '')
    for _ in range(max_steps):
        msg = _llm(messages, model=model)
        calls = msg.get('tool_calls') or []
        if not calls:
            answer = msg.get('content') or ''
            if not trace and not nudged and attachment is None and _has_numbers(answer):  # numbers without any tool result: retry once
                nudged = True
                messages.append({'role': 'user', 'content': "Tu n'as appelé aucun outil : appelle d'abord l'outil adapté "
                                 "(commune_summary, get_cell_profile, explain_index ou similar_cells), puis réponds."})
                continue
            return {'answer': answer, 'tools': trace, 'unverified': _unverified(answer, trace, known_text, photo)}
        messages.append({'role': 'assistant', 'content': msg.get('content') or '', 'tool_calls': calls})
        for tc in calls:
            name = tc['function']['name']
            fn = tools.FUNCS.get(name)
            try:
                args = tc['function'].get('arguments') or '{}'
                args = json.loads(args) if isinstance(args, str) else args
                args = {k: v for k, v in args.items() if v not in (None, '')}
                # small models invent plausible cell ids: keep one only if it was seen in the conversation
                if args.get('cell_id') and args['cell_id'] not in json.dumps(messages, ensure_ascii=False):
                    trace.append({'tool': name, 'note': f"cell_id {args['cell_id']} ignoré (inventé par le modèle)"})
                    args.pop('cell_id')
                result = fn(s, **args) if fn else {'erreur': 'outil inconnu'}
            except Exception as e:  # a tool error goes back to the model, it is not invented away
                args, result = locals().get('args', {}), {'erreur': f'{type(e).__name__}: {e}'}
            trace.append({'tool': name, 'args': args, 'result': result})
            messages.append({'role': 'tool', 'tool_call_id': tc.get('id', name),
                             'content': json.dumps(result, ensure_ascii=False, default=str)})
    final = _llm(messages + [{'role': 'user', 'content': 'Réponds maintenant avec les résultats obtenus.'}], use_tools=False, model=model)
    answer = final.get('content') or "Je n'ai pas pu terminer l'analyse."
    return {'answer': answer, 'tools': trace, 'unverified': _unverified(answer, trace, known_text, photo)}


VAR_WORDS = [(('pression',), 'P'), (('valeur ecologique', 'biodiversite'), 'V'), (('degradation',), 'D'),
             (('opportunite',), 'O'), (('priorite',), 'RP'), (('foret', 'bois'), 'foret'),
             (('croissance du bati', 'urbanisation'), 'croissance_bati_2006_2017'), (('bati', 'construit'), 'bati_2025')]
TREND_WORDS = [(('temperature', 'chaleur', 'rechauff'), 'tmean'), (('jours chauds', 'canicule'), 'hot_days'),
               (('gel',), 'frost_days'), (('pluie d ete', 'pluie estivale'), 'summer_rain_mm'), (('pluie', 'precipitation'), 'rain_mm'),
               (('secheresse', 'sec'), 'max_dry_spell'), (('bati', 'urbanisation', 'construit'), 'bati')]
PRICE_WORDS = ('prix', 'cout', 'euro', 'benefice', 'acheter', 'achat', 'foncier', 'dvf', 'budget')
ATLAS_WORDS = ('eolien', 'eolienne', 'methanis', 'photovolta', 'solaire', 'hydroelectri', 'geothermie', 'chaufferie', 'pcaet', 'energie',
               'paysage', 'patrimoine', 'grand site', 'znieff', 'natura 2000', 'ramsar', 'reserve naturelle', 'biotope',
               'masse d eau', 'piezo', 'hydrometr', 'zone vulnerable', 'captage', 'carriere', 'inondation', 'pprt', 'icpe',
               'littoral', 'urbanisme', 'srce', 'tvb')
KNOWLEDGE_WORDS = ('espece', 'habitat', 'milieu', 'maladie', 'cohabit', 'ecosysteme', 'faune', 'flore', 'oiseau', 'plante',
                   'arbre', 'haie', 'zone humide', 'marais', 'comment', 'pourquoi', 'qu est', 'methode', 'restaur')
CELL_RE = re.compile(r'\bH1_\d+_\d+\b')
NUM_RE = re.compile(r'(?<![\w.])\d+(?:[.,]\d+)?')


def _prefetch(s, question, ctx, photo):
    """Tool calls the server makes before the model answers (place named in the question / context / photo)."""
    calls, seen = [], set()

    def add(name, args):
        key = (name, json.dumps(args, sort_keys=True))
        if key not in seen and len(calls) < 4:
            seen.add(key)
            calls.append((name, args))
    for cid in CELL_RE.findall(question):
        if cid in s.index:
            add('get_cell_profile', {'cell_id': cid})
    if photo and isinstance(photo.get('cell_id'), str) and photo['cell_id'] in s.index:
        add('get_cell_profile', {'cell_id': photo['cell_id']})
    j = _commune_in(s, question)
    place = {'commune': s.communes[j]['name']} if j is not None else (
        {'commune': ctx['commune']} if ctx.get('commune') and s.commune(ctx['commune']) is not None else {})
    q = tools._norm(question)
    dept = next((c for w, c in (('seine maritime', '76'), ('seine-maritime', '76'), ('calvados', '14'), ('manche', '50'),
                                ('orne', '61'), (' eure', '27')) if w in ' ' + q), None)
    if dept and not place:
        place = {'departement': dept}
    found = [v for words, v in VAR_WORDS if any(w in q for w in words)]
    found = list(dict.fromkeys(found))
    if len(found) >= 2 and any(w in q for w in ('relation', 'correl', 'lien', 'entre', 'varie')):  # question 2
        add('correlate', {'x': found[0], 'y': found[1], **place, **({'rayon_km': 10} if 'commune' in place else {})})
    elif any(w in q for w in ('tendance', 'continue', 'futur', 'avenir', 'evolu', 'projection')) or re.search(r'\b20[3-9]\d\b', q):
        ind = next((v for words, v in TREND_WORDS if any(w in q for w in words)), None)  # question 3
        year = re.search(r'\b(20[3-9]\d|2100)\b', q)
        if ind and 'commune' in place:
            add('trend_projection', {'indicateur': ind, 'horizon': int(year.group(1)) if year else 2050, **place})
    target = place if 'commune' in place else ({'cell_id': CELL_RE.findall(question)[0]} if CELL_RE.findall(question) else {})
    if any(w in q for w in ('risque', 'modele', 'prevision', 'predi', 'artificialis', 'perte d habitat', 'population')) and target:
        add('run_models', target)                                   # Renatura AI predictions for the place
    if any(w in q for w in PRICE_WORDS) and (target or dept):
        add('price_benefit', target if 'commune' in target or 'cell_id' in target else {'departement': dept})
    if any(w in q for w in ('climat', 'meteo')) and target and not any(n == 'trend_projection' for n, _ in calls):
        add('climate_summary', target)
    atlas_word = next((w for w in ATLAS_WORDS if w in q), None)
    if atlas_word and target:
        add('atlas_zone', {**target, 'recherche': atlas_word})
    if j is not None and not calls:
        add('commune_summary', {'commune': s.communes[j]['name']})
    knowledge = any(w in q for w in KNOWLEDGE_WORDS)
    if not calls and not knowledge:  # « ici » : fall back on the page context
        if ctx.get('cell_id') in s.index:
            add('get_cell_profile', {'cell_id': ctx['cell_id']})
        elif ctx.get('commune') and s.commune(ctx['commune']) is not None:
            add('commune_summary', {'commune': ctx['commune']})
    if knowledge or not calls:  # qualitative question: retrieve knowledge passages
        add('search_knowledge', {'query': question[:300], 'k': 4})
    return calls


def _commune_in(s, text):
    """Longest commune name written in the question (whole words, accents ignored)."""
    t = ' ' + re.sub(r'[^a-z0-9]+', ' ', tools._norm(text)) + ' '
    best = None
    for name, j in s.commune_lookup.items():
        n = ' ' + re.sub(r'[^a-z0-9]+', ' ', name) + ' '
        if len(n) > 5 and n in t and (best is None or len(n) > best[0]):
            best = (len(n), j)
    return best[1] if best else None


def _has_numbers(text):
    return any(len(n.replace(',', '').replace('.', '')) >= 2 for n in NUM_RE.findall(CELL_RE.sub('', text)))


def _unverified(answer, trace, question, photo=None):
    """Numbers of the answer that appear neither in a tool result nor in the question (shown as a warning)."""
    known = json.dumps([t.get('result') for t in trace] + [photo], ensure_ascii=False, default=str) + ' ' + question
    known_vals = set()
    for n in NUM_RE.findall(CELL_RE.sub('', known)):
        try:
            v = float(n.replace(',', '.'))
        except ValueError:
            continue
        known_vals.update({round(v, 1), round(v), round(v * 100, 1), round(v * 100)})  # 0.2967 -> 29.7 %
    out = []
    for n in NUM_RE.findall(CELL_RE.sub('', answer)):
        v = float(n.replace(',', '.'))
        if v < 10 and '.' not in n and ',' not in n:  # small integers: list markers, counts
            continue
        if round(v, 1) not in known_vals and round(v) not in known_vals and n not in out:
            out.append(n)
    return out


@router.get('/health')
def health():
    try:
        r = requests.get(BASE_URL.replace('/v1', '') + '/api/tags', timeout=3)
        names = [m['name'] for m in r.json().get('models', [])]
        ok = MODEL in names
        return {'ok': ok, 'model': MODEL, 'available_models': names, 'provider': PROVIDER, 'local': LOCAL,
                'detail': '' if ok else f'modèle {MODEL} absent : ollama pull {MODEL}'}
    except Exception:
        if not LOCAL:  # remote OpenAI-compatible provider (e.g. Hugging Face): no Ollama tag list
            return {'ok': bool(API_KEY), 'model': MODEL, 'available_models': [MODEL], 'provider': PROVIDER, 'local': False,
                    'detail': '' if API_KEY else 'jeton manquant : RENATURA_LLM_API_KEY ou HF_TOKEN'}
        return {'ok': False, 'model': MODEL, 'provider': PROVIDER, 'local': True,
                'detail': f'serveur de modèle injoignable ({BASE_URL}) : lancer « ollama serve »'}


@router.post('/chat')
async def chat(message: str = Form(''), history: str = Form('[]'), page_context: str = Form('{}'),
               model: str = Form(''), photo: UploadFile | None = File(None), file: UploadFile | None = File(None)):
    try:
        hist = json.loads(history or '[]')
        ctx = json.loads(page_context or '{}')
    except ValueError:
        raise HTTPException(422, 'history / page_context : JSON invalide')
    if not message.strip() and photo is None and file is None:
        raise HTTPException(422, 'message vide')
    if len(message) > 4000:
        raise HTTPException(413, 'message trop long (4 000 caractères maximum)')
    analysed = None
    if photo is not None:
        raw = await photo.read(MAX_IMAGE + 1)
        if len(raw) > MAX_IMAGE:
            raise HTTPException(413, 'photo trop lourde (15 Mo maximum)')
        analysed = analyse_photo(raw)
    attachment = None
    if file is not None:
        if not (file.filename or '').lower().endswith(('.json', '.geojson')):
            raise HTTPException(415, 'fichier joint : seuls .json et .geojson sont acceptés')
        raw = await file.read(MAX_JSON + 1)
        if len(raw) > MAX_JSON:
            raise HTTPException(413, 'fichier JSON trop lourd (5 Mo maximum)')
        try:
            attachment = read_json_attachment(file.filename, raw)
        except ValueError as e:
            raise HTTPException(422, str(e))
    t = time.time()
    chosen = model.strip() or MODEL
    if not all(c.isalnum() or c in ':._-/' for c in chosen) or len(chosen) > 80:
        raise HTTPException(422, 'nom de modèle invalide')
    result = ask(message, ctx, hist, analysed, model=chosen, attachment=attachment)
    fichier = {k: attachment[k] for k in ('nom', 'resume', 'tronque')} if attachment else None
    return {**result, 'photo': analysed, 'fichier': fichier, 'model': chosen, 'seconds': round(time.time() - t, 1)}


# ---------------------------------------------------------------- knowledge base management (RAG)
# Local tool: anyone who can reach the server can edit the base. Set RENATURA_KNOWLEDGE_KEY to require the header
# X-Knowledge-Key for every change (the key is compared, never stored or logged).
from fastapi import Header  # noqa: E402
from . import knowledge  # noqa: E402

KNOWLEDGE_KEY = os.getenv('RENATURA_KNOWLEDGE_KEY', '')


def _guard(key):
    if KNOWLEDGE_KEY and key != KNOWLEDGE_KEY:
        raise HTTPException(403, 'clé de modification requise (en-tête X-Knowledge-Key)')


@router.get('/knowledge/status')
def knowledge_status():
    return {**knowledge.stats(), 'llm': {'provider': PROVIDER, 'model': MODEL, 'url': BASE_URL, 'local': LOCAL,
                                         'token_configured': bool(API_KEY)}, 'edit_requires_key': bool(KNOWLEDGE_KEY)}


@router.get('/knowledge/documents')
def knowledge_documents(q: str = '', origin: str = '', limit: int = 100, offset: int = 0):
    return knowledge.list_documents(q[:100], origin[:20], max(1, min(limit, 500)), max(0, offset))


@router.get('/knowledge/documents/{did}')
def knowledge_document(did: str):
    d = knowledge.get_document(did)
    if d is None:
        raise HTTPException(404, 'document inconnu')
    return d


@router.post('/knowledge/documents')
async def knowledge_add(title: str = Form(''), text: str = Form(''), source: str = Form(''), category: str = Form('ajout'),
                        file: UploadFile | None = File(None), x_knowledge_key: str = Header('')):
    _guard(x_knowledge_key)
    if file is not None:
        raw = await file.read(10 * 1024 * 1024 + 1)
        if len(raw) > 10 * 1024 * 1024:
            raise HTTPException(413, 'fichier trop lourd (10 Mo maximum)')
        try:
            text = knowledge.extract_text(file.filename or '', raw)
        except Exception as e:
            raise HTTPException(422, f'lecture impossible : {e}')
        title = title or (file.filename or 'document')
        source = source or f'fichier : {file.filename}'
    try:
        did = knowledge.add_document(title, text, source, 'user', category[:60] or 'ajout')
    except ValueError as e:
        raise HTTPException(422, str(e))
    return knowledge.get_document(did)


@router.patch('/knowledge/documents/{did}')
def knowledge_toggle(did: str, enabled: bool, x_knowledge_key: str = Header('')):
    _guard(x_knowledge_key)
    if not knowledge.set_enabled(did, enabled):
        raise HTTPException(404, 'document inconnu')
    return {'id': did, 'enabled': enabled}


@router.delete('/knowledge/documents/{did}')
def knowledge_delete(did: str, x_knowledge_key: str = Header('')):
    _guard(x_knowledge_key)
    if not knowledge.delete_document(did):
        raise HTTPException(404, 'document inconnu')
    return {'id': did, 'deleted': True}


@router.get('/knowledge/search')
def knowledge_search(q: str, k: int = 5):
    return {'query': q, 'results': knowledge.search(q[:300], k=max(1, min(k, 20)))}
