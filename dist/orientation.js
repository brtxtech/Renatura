/** Shared geographic landmarks. Context only; never inputs to ecological scores. */
const ROOT='data/orientation/';
export const TRANSPORT_OPTIONS=[{id:'roads',label:'Autoroutes & axes routiers',color:'#bb7439'},{id:'rail',label:'Voies ferrées & tramways',color:'#685b72'},{id:'stops',label:'Gares & arrêts de transport',color:'#236a9a'}];
const empty={type:'FeatureCollection',features:[]};
let citiesPromise;const dataCache=new Map();
async function read(path){const r=await fetch(path);if(!r.ok)throw Error('Repères indisponibles ('+r.status+')');if(path.endsWith('.gz')&&!r.headers.get('Content-Encoding')?.includes('gzip'))return new Response(r.body.pipeThrough(new DecompressionStream('gzip'))).json();return r.json()}
function network(id){if(!dataCache.has(id))dataCache.set(id,read(ROOT+id+'.geojson.gz').catch(e=>{dataCache.delete(id);throw e}));return dataCache.get(id)}
function preferences(){try{return JSON.parse(localStorage.getItem('renatura-landmarks-v1'))||{}}catch{return {}}}
export function pickCityLabels(cities,zoom,project,width,height){
 const max=zoom<9?22:zoom<11?35:60, gap=zoom<9?72:60,chosen=[];
 for(const city of cities){const p=project(city.center);if(p.x<10||p.y<14||p.x>width-12||p.y>height-12)continue;
  const w=Math.max(gap,Math.min(150,city.name.length*6+15));if(chosen.some(q=>Math.abs(q.point.x-p.x)<(q.width+w)/2&&Math.abs(q.point.y-p.y)<24))continue;
  chosen.push({city,point:p,width:w});if(chosen.length>=max)break;
 }return chosen;
}
export function attachOrientation(map,kind){
 const leaflet=kind==='leaflet', host=map.getContainer(), selected=preferences(), layers=new Map(),pending=new Set(),collections=new Map();
 host.classList.add('has-orientation');
 const control=document.createElement('details');control.className='orientation-control';control.innerHTML='<summary>⌖ Repères</summary><p class="cities-fixed">● Villes · toujours visibles</p>'+TRANSPORT_OPTIONS.map(o=>`<label><input type="checkbox" data-context="${o.id}" ${selected[o.id]?'checked':''}><span class="orientation-swatch" style="background:${o.color}"></span>${o.label}</label>`).join('')+'<p class="orientation-note">Réseaux OSM · arrêts détaillés en zoomant</p><p class="orientation-status" role="status"></p>';
 host.append(control);const status=control.querySelector('.orientation-status');
 // Keep « Repères » clear of the map's +/− (and compass) buttons, wherever a page puts them.
 const place=()=>{control.style.top='';const own=control.getBoundingClientRect();let bottom=-1;for(const z of host.querySelectorAll('.leaflet-control-zoom,.maplibregl-ctrl-group')){const r=z.getBoundingClientRect();if(r.width&&r.left<own.right&&r.right>own.left&&r.top<own.bottom+8)bottom=Math.max(bottom,r.bottom)}if(bottom>=0)control.style.top=Math.round(bottom-host.getBoundingClientRect().top+10)+'px'};
 requestAnimationFrame(place);setTimeout(place,300);setTimeout(place,1500);addEventListener('resize',place);
 new MutationObserver(place).observe(host.querySelector('.leaflet-control-container,.maplibregl-control-container')||host,{childList:true,subtree:true});
 control.addEventListener('pointerdown',e=>e.stopPropagation());control.addEventListener('dblclick',e=>e.stopPropagation());
 if(leaflet){L.DomEvent.disableClickPropagation(control);L.DomEvent.disableScrollPropagation(control);map.createPane('orientationNetworks');map.getPane('orientationNetworks').style.zIndex=610;map.createPane('orientationPlaces');map.getPane('orientationPlaces').style.zIndex=650;map.getPane('orientationPlaces').style.pointerEvents='none'}
 const labels=document.createElement('div');labels.className='orientation-labels';labels.setAttribute('aria-label','Villes et communes');labels.style.pointerEvents='none';(leaflet?map.getPane('orientationPlaces'):host).append(labels);
 let cities=[],frame;
 const draw=()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(()=>{if(!host.isConnected)return;const size=leaflet?map.getSize():{x:host.clientWidth,y:host.clientHeight};const project=c=>leaflet?map.latLngToContainerPoint([c[1],c[0]]):map.project(c);const chosen=pickCityLabels(cities,map.getZoom(),project,size.x,size.y);labels.replaceChildren();if(leaflet){const origin=map.containerPointToLayerPoint([0,0]);labels.style.transform=`translate(${origin.x}px,${origin.y}px)`}
 for(const {city,point} of chosen){const label=document.createElement('span');label.className='orientation-city'+(city.population>=50000?' major':'');label.style.left=point.x+'px';label.style.top=point.y+'px';label.textContent=city.name;labels.append(label)}})};
 if(!citiesPromise)citiesPromise=read(ROOT+'cities.json');citiesPromise.then(d=>{cities=d.slice().sort((a,b)=>(b.population||0)-(a.population||0)||a.name.localeCompare(b.name));draw()}).catch(e=>status.textContent='Villes : '+e.message);
 for(const event of ['move','zoom','resize'])map.on(event,draw);
 const visibleData=(id,fc)=>{if(!leaflet)return fc;const b=map.getBounds(),z=map.getZoom();return {type:'FeatureCollection',features:fc.features.filter(f=>{const q=f.bbox;if(q&&(q[0]>b.getEast()||q[2]<b.getWest()||q[1]>b.getNorth()||q[3]<b.getSouth()))return false;if(id==='roads'&&z<9&&!/motorway|trunk|primary/.test(f.properties.highway||''))return false;if(id==='stops'&&z<11&&!f.properties.railway&&f.properties.amenity!=='ferry_terminal')return false;return true})}};
 if(leaflet)map.on('moveend',()=>{for(const [id,layer] of layers)if(selected[id]&&collections.has(id))layer.clearLayers().addData(visibleData(id,collections.get(id)))});
 async function toggle(id,on,input){selected[id]=on;try{localStorage.setItem('renatura-landmarks-v1',JSON.stringify(selected))}catch{}
  if(!on){if(leaflet&&layers.has(id))map.removeLayer(layers.get(id));if(!leaflet&&map.getLayer('context-'+id))map.setLayoutProperty('context-'+id,'visibility','none');return}
  if(pending.has(id))return;pending.add(id);status.textContent='Chargement des repères…';
  try{if(!layers.has(id)){const fc=await network(id);const o=TRANSPORT_OPTIONS.find(x=>x.id===id);
   if(leaflet){collections.set(id,fc);layers.set(id,L.geoJSON(visibleData(id,fc),{pane:'orientationNetworks',interactive:false,style:f=>({color:o.color,weight:id==='roads'?(/motorway|trunk/.test(f.properties.highway)?3:1.6):2,opacity:.85,dashArray:id==='rail'?'7 4':undefined}),pointToLayer:(f,ll)=>L.circleMarker(ll,{pane:'orientationNetworks',radius:f.properties.railway==='station'?5:3,color:'#fff',weight:1,fillColor:o.color,fillOpacity:.95,interactive:false})}));}
   else{map.addSource('context-'+id,{type:'geojson',data:fc,attribution:'© OpenStreetMap contributors · ODbL · Repères hors calcul de score'});map.addLayer({id:'context-'+id,source:'context-'+id,type:id==='stops'?'circle':'line',paint:id==='stops'?{'circle-color':o.color,'circle-radius':['interpolate',['linear'],['zoom'],8,2,14,4],'circle-stroke-color':'#fff','circle-stroke-width':1}:{'line-color':o.color,'line-width':id==='roads'?['case',['in',['get','highway'],['literal',['motorway','motorway_link','trunk','trunk_link']]],3,1.6]:2,'line-opacity':.85,...(id==='rail'?{'line-dasharray':[4,2]}:{})}});layers.set(id,true)}
  }
  if(selected[id]){if(leaflet)layers.get(id).addTo(map);else map.setLayoutProperty('context-'+id,'visibility','visible')}
  status.textContent=TRANSPORT_OPTIONS.filter(o=>selected[o.id]).map(o=>o.label).join(' · ')||'Villes affichées';
  }catch(e){selected[id]=false;input.checked=false;status.textContent=e.message;try{localStorage.setItem('renatura-landmarks-v1',JSON.stringify(selected))}catch{}}
  finally{pending.delete(id)}
 }
 control.querySelectorAll('input').forEach(input=>{input.onchange=()=>toggle(input.dataset.context,input.checked,input);if(input.checked)toggle(input.dataset.context,true,input)});
 if(leaflet)map.attributionControl?.addAttribution('Repères : © OpenStreetMap contributors · ODbL ; communes : API Géo / Etalab');
 else{let ordering=false;map.on('styledata',()=>{if(ordering)return;const ids=map.getStyle().layers.map(l=>l.id),active=[...layers.keys()].map(id=>'context-'+id).filter(id=>map.getLayer(id));if(!active.length)return;const lastThematic=Math.max(-1,...ids.map((id,i)=>id.startsWith('context-')?-1:i));if(active.every(id=>ids.indexOf(id)>lastThematic))return;ordering=true;for(const id of active)map.moveLayer(id);ordering=false})}
 return {refresh:draw};
}
