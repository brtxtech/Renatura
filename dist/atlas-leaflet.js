/** Small renderer adapter: source/layer separation with a WebGL-independent 2D map. */
class Atlas2D {
 constructor(options){this.engine=window.L;this.map=L.map(options.container,{preferCanvas:true,zoomControl:false,minZoom:options.minZoom,maxZoom:options.maxZoom}).setView([options.center[1],options.center[0]],options.zoom);this.sources=new Map();this.layers=new Map();this.handlers=new Map();this.picked=[];this.map.on('click',e=>{this.picked=[];this.emitClick(e)});}
 emitClick(e){for(const fn of this.handlers.get('click')||[])fn({lngLat:{lng:e.latlng.lng,lat:e.latlng.lat},point:e.containerPoint})}
 once(name,fn){if(name==='load')queueMicrotask(fn);else this.map.once(name,fn)}
 on(name,fn){if(name==='click'){if(!this.handlers.has(name))this.handlers.set(name,[]);this.handlers.get(name).push(fn)}else this.map.on(name,fn)}
 addControl(control,position){if(control.kind==='navigation')L.control.zoom({position:'topright'}).addTo(this.map);if(control.kind==='scale')L.control.scale({position:'bottomright',imperial:false}).addTo(this.map)}
 addSource(id,config){const source={...config,data:typeof config.data==='string'?null:config.data};source.ready=typeof config.data==='string'?fetch(config.data).then(r=>{if(!r.ok)throw Error('Couche indisponible : '+config.data);return r.json()}).then(d=>source.data=d):Promise.resolve(source.data);source.setData=data=>{source.data=data;for(const [lid,l] of this.layers)if(l.config.source===id){if(l.drawn)this.map.removeLayer(l.drawn);this.render(lid,l)}};this.sources.set(id,source);if(config.attribution)this.map.attributionControl.addAttribution(config.attribution)}
 getSource(id){return this.sources.get(id)}
 removeSource(id){this.sources.delete(id)}
 getLayer(id){return this.layers.get(id)}
 addLayer(config){const entry={config,visible:true,drawn:null};this.layers.set(config.id,entry);const src=this.sources.get(config.source);src.ready.then(()=>{if(this.layers.get(config.id)===entry)this.render(config.id,entry)}).catch(e=>{document.getElementById('activity').textContent=e.message})}
 render(id,entry){const config=entry.config,src=this.sources.get(config.source);if(!src)return;
 if(config.type==='raster'){entry.drawn=L.tileLayer(src.tiles[0],{maxZoom:src.maxzoom||19,opacity:config.paint?.['raster-opacity']??1,attribution:src.attribution||''});if(entry.visible)entry.drawn.addTo(this.map);return}
 const type=g=>g?.type.replace(/^Multi/,'');
 const filter=feature=>{if(!config.filter)return true;const t=type(feature.geometry);if(config.type==='fill')return t==='Polygon';if(config.type==='circle')return t==='Point';return ['Polygon','LineString'].includes(t)};
 const p=config.paint||{},col=p['fill-color']||p['line-color']||p['circle-color']||'#315c42';
 const parts=f=>f.geometry?.type==='GeometryCollection'?f.geometry.geometries.flatMap(geometry=>parts({...f,geometry})):[f];
 const data=src.data?.features?{...src.data,features:src.data.features.flatMap(parts)}:src.data;
 entry.drawn=L.geoJSON(data||{type:'FeatureCollection',features:[]},{filter,style:()=>({color:col,weight:Number.isFinite(p['line-width'])?p['line-width']:2,opacity:p['line-opacity']??1,fill:config.type==='fill',fillColor:col,fillOpacity:p['fill-opacity']??0,stroke:config.type!=='fill',dashArray:p['line-dasharray']?'6 4':null,bubblingMouseEvents:false}),pointToLayer:(f,ll)=>L.circleMarker(ll,{radius:p['circle-radius']||5,color:p['circle-stroke-color']||'#fff',weight:p['circle-stroke-width']||1,fillColor:col,fillOpacity:1,bubblingMouseEvents:false}),onEachFeature:(feature,layer)=>{layer.options.bubblingMouseEvents=false;layer.on('click',e=>{this.picked=[{...feature,_renderer_layer:id}];this.emitClick(e)})}});
 if(entry.visible)entry.drawn.addTo(this.map);
 if(id.startsWith('analysis-zone')&&entry.drawn.bringToFront)entry.drawn.bringToFront();
 }
 removeLayer(id){const l=this.layers.get(id);if(l?.drawn)this.map.removeLayer(l.drawn);this.layers.delete(id)}
 setLayoutProperty(id,name,value){const l=this.layers.get(id);if(!l)return;l.visible=value!=='none';if(l.drawn){if(l.visible)l.drawn.addTo(this.map);else this.map.removeLayer(l.drawn)}}
 fitBounds(b,options={}){this.map.fitBounds([[b[0][1],b[0][0]],[b[1][1],b[1][0]]],{padding:[options.padding||20,options.padding||20],animate:options.duration!==0,maxZoom:options.maxZoom})}
 flyTo(o){this.map.flyTo([o.center[1],o.center[0]],o.zoom)}
 jumpTo(o){this.map.setView([o.center[1],o.center[0]],o.zoom,{animate:false})}
 getBounds(){const b=this.map.getBounds();return [b.getWest(),b.getSouth(),b.getEast(),b.getNorth()]}
 getCenter(){return this.map.getCenter()}
 getZoom(){return this.map.getZoom()}
 getCanvas(){return this.map.getContainer()}
 queryRenderedFeatures(point,options){return this.picked.filter(f=>!options?.layers||options.layers.includes(f._renderer_layer))}
}
export const regionalEngine={Map:Atlas2D,NavigationControl:class{constructor(){this.kind='navigation'}},ScaleControl:class{constructor(){this.kind='scale'}}};
