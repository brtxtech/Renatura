/** Browser-persistent user data. Imported coordinates are never guessed. */
const DB='renatura-user-datasets-v1';
async function database(){return new Promise((ok,no)=>{const r=indexedDB.open(DB,1);r.onupgradeneeded=()=>r.result.createObjectStore('datasets',{keyPath:'metadata.id'});r.onsuccess=()=>ok(r.result);r.onerror=()=>no(r.error)})}
export async function listImports(){const db=await database();const local=await new Promise((ok,no)=>{const r=db.transaction('datasets').objectStore('datasets').getAll();r.onsuccess=()=>ok(r.result);r.onerror=()=>no(r.error)});db.close();let remote=[];try{const r=await fetch('api/datasets');if(r.ok)remote=await r.json()}catch{}return [...new Map([...local,...remote].map(d=>[d.metadata.id,d])).values()]}
export async function saveImport(record){let actual=record;const health=await fetch('api/health').then(r=>r.json()).catch(()=>null);if(health?.status==='ok'){const r=await fetch('api/datasets',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(record)});const d=await r.json();if(!r.ok)throw Error(d.detail||'Import refusé');actual=d}
 const db=await database();await new Promise((ok,no)=>{const t=db.transaction('datasets','readwrite');t.objectStore('datasets').put(actual);t.oncomplete=ok;t.onerror=()=>no(t.error)});db.close();return actual}
export function normaliseFeatures(data){if(data.crs&&!/4326|CRS84/i.test(JSON.stringify(data.crs)))throw Error('Projection déclarée différente de WGS84 : convertir les coordonnées avant import.');const fc=data.type==='FeatureCollection'?data:data.type==='Feature'?{type:'FeatureCollection',features:[data]}:null;if(!fc||!Array.isArray(fc.features))throw Error('Fournir un GeoJSON FeatureCollection ou Feature.');if(fc.features.length>250000)throw Error('Import navigateur limité à 250 000 objets.');
 function coords(c){if(!Array.isArray(c)||!c.length)throw Error('Coordonnées vides');if(typeof c[0]==='number'){if(c.length<2||!c.every(Number.isFinite)||Math.abs(c[0])>180||Math.abs(c[1])>90)throw Error('Coordonnées longitude–latitude WGS84 attendues.')}else c.forEach(coords)}
 function geometry(g){if(!g)return;if(g.type==='GeometryCollection'){g.geometries.forEach(geometry);return}if(!['Point','MultiPoint','LineString','MultiLineString','Polygon','MultiPolygon'].includes(g.type))throw Error('Géométrie non reconnue');coords(g.coordinates)}
 fc.features.forEach(f=>{if(f.type!=='Feature')throw Error('Objet GeoJSON non valide');geometry(f.geometry)});return fc;
}
export function attachImports(state,records){state.customFeatures=new Map();
 const norm=s=>String(s).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
 for(const record of records){
  const m=record.metadata,fc=record.data;if(!m?.id||fc?.type!=='FeatureCollection')continue;
  const features=fc.features.filter(f=>f.geometry).map((f,i)=>({...f,properties:{...(f.properties||{}),_layer:m.id,_id:m.id+':'+i,_source_id:f.id||i,_collection_status:m.status||'PARTIAL'}}));state.customFeatures.set(m.id,{type:'FeatureCollection',features});
  const raw={id:m.id,name:m.display_name,display_name:m.display_name,kind:'USER',origin:'Import utilisateur',status:m.status||'PARTIAL',map_count:features.length,entry_ids:[],categories:[m.theme],category_ids:[],use_cases:[m.description||'Import utilisateur à qualifier'],collected_at:m.updated,url:m.source,license:m.license||'À renseigner',map_state:features.length?'READY':'NO_NORMANDY_GEOMETRY',crs_observed:['EPSG:4326'],errors:[],chunks:['browser:'+m.id]};state.catalog.layers.push(raw);
  const theme=state.tree.themes.find(t=>t.id===m.theme)||state.tree.themes[0],gid='custom-group:'+m.group;
  let group=theme.groups.find(g=>norm(g.display_name)===norm(m.group));if(!group){group={id:gid,display_name:m.group,facets:{},selection:{},layers:[]};theme.groups.push(group)}
  let layer=group.layers.find(l=>norm(l.display_name)===norm(m.display_name));if(!layer){layer={id:'custom-layer:'+m.id,display_name:m.display_name,variants:[]};group.layers.push(layer);state.tree.statistics.logical_layers++}
  const dims=m.variant_type&&m.variant_type!=='none'?{[m.variant_type]:m.variant_value}:{};
  const existing=layer.variants.find(v=>JSON.stringify(v.dimensions)===JSON.stringify(dims));
  if(existing){existing.source_ids.push(m.id)}else layer.variants.push({id:m.id,dimensions:dims,source_id:m.id,source_ids:[m.id],map_count:features.length,status:raw.status==='COMPLETE'?'complete':'partial'});
  for(const [key,value] of Object.entries(dims)){group.facets[key]=[...new Set([...(group.facets[key]||[]),value])].sort();if(!group.selection[key]||key==='year')group.selection[key]=group.facets[key].at(-1)}
 }
}
