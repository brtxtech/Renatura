"""Reference-first ingestion: validate and route before explicit population."""
import json,uuid,hashlib,io
from pathlib import Path
from PIL import Image,ImageOps
from . import db
from .validation import validate

def batch_for(payload):
    value=db.get('batches',payload['batch_id'])
    if not value:raise ValueError('Unknown upload reference')
    return value

def guard_uncommitted(b):
    if b.get('state') in ('populated','removed'):
        raise ValueError('Committed references are immutable; create a new reference to revalidate')

def reference(payload,ctx):
    ctx.check();b=batch_for(payload);guard_uncommitted(b)
    if not b.get('reference'):raise ValueError('Upload reference is required')
    b['state']='checking';db.put('batches',b['id'],b)
    ctx.log(f"Reference registered: {b['reference']} · {b['filename']}")
    return payload

def type_check(payload,ctx):
    ctx.check();b=batch_for(payload);guard_uncommitted(b);raw=(db.DATA/'uploads'/b['stored_file']).read_bytes()
    try:
        if b['element_type']=='image':
            Image.MAX_IMAGE_PIXELS=24_000_000
            with Image.open(io.BytesIO(raw)) as im:
                if im.width*im.height>24_000_000:raise ValueError('Maximum 24 megapixels')
                im.verify()
            b['detected_type']='image'
        else:
            from .formats import normalize
            data,fmt=normalize(raw,b['filename'],b['element_type'])  # JSON / GeoJSON / CSV / ZIP (incl. shapefile)
            if not isinstance(data,(dict,list)):raise ValueError('Expected JSON object or array')
            # validation reads this canonical copy; the original upload stays untouched for provenance
            (db.DATA/'uploads'/(b['id']+'.norm.json')).write_text(json.dumps(data,ensure_ascii=False,allow_nan=False),encoding='utf-8')
            b['source_format']=fmt;ctx.log('File format: '+fmt)
            is_geo=isinstance(data,dict) and data.get('type')=='FeatureCollection'
            if b['element_type'] in ('geojson','foncier') and not is_geo:raise ValueError('This box requires a GeoJSON FeatureCollection')
            if b['element_type'] in ('json','climate') and is_geo:raise ValueError('This box expects JSON records; select a GeoJSON or land box for a FeatureCollection')
            b['detected_type']='geojson' if is_geo else 'json'
        ctx.log(f"Declared {b['element_type']} matches detected {b['detected_type']}")
    except Exception as e:
        b['state']='blocked';b['failure_node']='type_check';b['error']=str(e)[:600];b['accepted_count']=0;b['rejected_count']=1
        db.put('batches',b['id'],b);ctx.log('Type check blocked: '+b['error'],'error')
        return {**payload,'blocked':True}
    db.put('batches',b['id'],b);return payload

def detection(payload,ctx):
    """Species recognition (Renatura model) for image references: enriches the record, never blocks it."""
    if payload.get('blocked'):ctx.log('Skipped: type gate failed','warning');return payload
    ctx.check();b=batch_for(payload);guard_uncommitted(b)
    if b.get('detected_type')!='image':
        b['detection']={'status':'not_applicable'};db.put('batches',b['id'],b)
        ctx.log('Ignoré : la détection d’espèce ne concerne que les images');return payload
    from . import species
    ok,reason=species.available()
    if not ok:
        b['detection']={'status':'unavailable','reason':reason};db.put('batches',b['id'],b)
        ctx.log('Détection indisponible : '+reason,'warning');return payload
    raw=(db.DATA/'uploads'/b['stored_file']).read_bytes()
    try:
        with Image.open(io.BytesIO(raw)) as im:
            result=species.predict(ImageOps.exif_transpose(im))
    except Exception as e:  # a model failure must not block the image
        b['detection']={'status':'error','reason':f'{type(e).__name__}: {str(e)[:200]}'};db.put('batches',b['id'],b)
        ctx.log('Détection en échec : '+b['detection']['reason'],'warning');return payload
    b['detection']=result;db.put('batches',b['id'],b)
    sp=result['species']
    ctx.log(f"Espèce proposée : {sp['french_name'] or sp['scientific_name']} ({sp['scientific_name']}) · {sp['probability']:.0%} · {result['status_label']}")
    return payload

def validation(payload,ctx):
    if payload.get('blocked'):ctx.log('Skipped: type gate failed','warning');return payload
    ctx.check();b=batch_for(payload);guard_uncommitted(b);raw=(db.DATA/'uploads'/b['stored_file']).read_bytes()
    try:
        if b['detected_type']=='image':
            with Image.open(io.BytesIO(raw)) as im:
                im=ImageOps.exif_transpose(im).convert('RGB');im.thumbnail((2000,2000));directory=db.DATA/'images';directory.mkdir(exist_ok=True)
                filename=b['id']+'.jpg';im.save(directory/filename,quality=88)
                image={'id':b['id'],'filename':filename,'original_name':b['filename'],'width':im.width,'height':im.height,'url':'api/images/'+b['id']}
            db.put('images',b['id'],image)
            props={'reference':b['reference'],'image_id':b['id'],'width':image['width'],'height':image['height']}
            det=b.get('detection') or {}
            if det.get('species'):  # enrichment from the species-recognition model
                sp=det['species']
                props.update(species_scientific_name=sp['scientific_name'],species_french_name=sp['french_name'],species_group=sp['group'],
                             detection_confidence=sp['probability'],detection_status=det['status_label'],protected_france=sp['protected_france'],
                             red_list_normandie=sp['red_list_normandie'],is_invasive=sp['is_invasive'],
                             detection_candidates=[{'scientific_name':c['scientific_name'],'probability':c['probability']} for c in det['top5']],
                             detection_model=f"{det['model']['arch']} · {det['model']['classes']} espèces")
            elif det.get('status'):props['detection_status']={'unavailable':'modèle indisponible','error':'échec de la détection'}.get(det['status'],det['status'])
            result=validate([props],b.get('expected_schema'),b.get('required_fields',[]),ctx.stop,ctx.log)
            result['image_id']=b['id']
        else:
            norm=db.DATA/'uploads'/(b['id']+'.norm.json')
            data=json.loads(norm.read_text(encoding='utf-8')) if norm.exists() else json.loads(raw.decode('utf-8-sig'))
            if isinstance(data,dict) and data.get('crs') and not str(data['crs']).upper().count('4326') and 'CRS84' not in str(data['crs']).upper():raise ValueError('Reproject legacy CRS to WGS84 before importing')
            result=validate(data,b.get('expected_schema'),b.get('required_fields',[]),ctx.stop,ctx.log)
        b['validation']=result;b['accepted_count']=result['valid_count'];b['rejected_count']=result['rejected_count'];b['warning_count']=sum(bool(a['warnings']) for a in result['anomalies']);b['state']='validated'
        ctx.log(f"{b['accepted_count']} accepted · {b['rejected_count']} rejected · {b['warning_count']} warnings")
    except InterruptedError:raise
    except Exception as e:
        b['state']='blocked';b['failure_node']='validation';b['error']=str(e)[:600];b['accepted_count']=0;b['rejected_count']=1;payload={**payload,'blocked':True};ctx.log('Validation blocked: '+b['error'],'error')
    db.put('batches',b['id'],b);return payload

def routing(payload,ctx):
    ctx.check();b=batch_for(payload);guard_uncommitted(b)
    if payload.get('blocked') or not b.get('accepted_count'):
        b['state']='blocked';ctx.log('Bad elements routed to quarantine. Population is blocked.','warning')
    else:
        b['state']='partial_ready' if b.get('rejected_count') else 'ready'
        ctx.log('Good elements are ready. Choose Populate to commit them to the target category.')
    db.put('batches',b['id'],b);return {**payload,'state':b['state'],'accepted_count':b.get('accepted_count',0),'rejected_count':b.get('rejected_count',0)}

def populate(payload,ctx):
    ctx.check();b=batch_for(payload)
    if b['state'] not in ('ready','partial_ready'):raise ValueError('Only validated, unpopulated references can be populated')
    if not db.get('categories',b['category_id']):raise ValueError('Target category no longer exists')
    r=b['validation'];key=b['id'];revision=uuid.uuid4().hex
    doc={'id':key,'name':b['reference'],'reference':b['reference'],'source_uri':b.get('source_uri'),'category':b['category_name'],'category_id':b['category_id'],'catalog_id':b.get('catalog_id'),'collection_state':b['collection_state'],'kind':'image' if b['element_type']=='image' else ('geojson' if r['is_geojson'] else 'json'),'element_type':b['element_type'],'source_filename':b['filename'],'sha256':b['sha256'],'revision':revision,'schema':r['schema'],'schema_origin':r['schema_origin'],'profile':r['profile'],'valid_count':r['valid_count'],'rejected_count':r['rejected_count'],'total_count':r['total_count'],'anomalies':r['anomalies'],'data':r['data'],'batch_id':b['id'],'image_id':r.get('image_id')}
    # Dataset and batch state commit atomically to prevent duplicate population.
    with db.LOCK,db.connect() as conn:
        latest=json.loads(conn.execute("SELECT body FROM documents WHERE kind='batches' AND id=?",(b['id'],)).fetchone()['body'])
        if latest['state'] not in ('ready','partial_ready'):raise ValueError('Reference already populated or no longer ready')
        b['state']='populated';b['dataset_id']=key
        conn.execute('INSERT OR REPLACE INTO documents VALUES (?,?,?)',('datasets',key,json.dumps(doc,ensure_ascii=False,allow_nan=False)))
        conn.execute('INSERT OR REPLACE INTO documents VALUES (?,?,?)',('batches',key,json.dumps(b,ensure_ascii=False,allow_nan=False)))
    ctx.log(f"Populated {doc['valid_count']} valid elements into {b['category_name']}. Quarantined elements were excluded.")
    return {**payload,'dataset_id':key,'state':'populated'}

def datastore(payload,ctx):
    ctx.check()
    from .calculation import calculate
    cfg=db.get('config','active') or {'rules':[]}
    db.put('calculation','latest',calculate(cfg));ctx.log('Datastore state and category indicators refreshed')
    if payload.get('dataset_id'):
        from .publish import publish
        doc=db.get('datasets',payload['dataset_id'])
        name=publish(doc) if doc else None
        ctx.log(f'Published to the Renatura atlas as {name}' if name else 'Non-geographic dataset: kept in the workbench datastore (not an atlas layer)')
    return payload

NODES={n:f for n,f in [('reference',reference),('type_check',type_check),('detection',detection),('validation',validation),('routing',routing),('populate',populate),('datastore',datastore)]}
