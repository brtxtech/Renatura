import {escapeHTML as esc} from './core.js';
const fmt=n=>Number(n||0).toLocaleString('fr-FR'),normal=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
export function allVariants(tree){return tree.themes.flatMap(t=>t.groups.flatMap(g=>g.layers.flatMap(l=>l.variants)))}
export function chooseVariants(layer,group){return layer.variants.filter(v=>Object.entries(group.selection).every(([k,value])=>value==='Tous'||!v.dimensions[k]||v.dimensions[k]===value))}
export function renderGroupedCatalog(state,toggle,sourceDetail,saveView){
 const $=id=>document.getElementById(id),root=$('layers');root.replaceChildren();const q=normal($('search').value),themeFilter=$('category').value,origin=$('origin').value,status=$('status').value,only=$('active-only').checked;let shown=0;
 const meta=new Map(state.catalog.layers.map(l=>[l.id,l]));
 function primary(v){const candidates=v.source_ids.map(id=>meta.get(id)).filter(Boolean).filter(l=>(!origin||(origin==='FILE'?l.kind==='FILE':origin==='USER'?l.kind==='USER':l.kind!=='FILE'&&l.kind!=='USER'))&&(!status||l.status===status));return candidates.find(l=>l.id===v.source_id)||candidates.sort((a,b)=>b.map_count-a.map_count)[0]}
 function selected(layer,g){return chooseVariants(layer,g).map(primary).filter(Boolean)}
 for(const theme of state.tree.themes){if(themeFilter&&theme.id!==themeFilter)continue;const themeNode=document.createElement('details');themeNode.className='catalog-theme';let themeRows=0;themeNode.innerHTML=`<summary>${esc(theme.display_name)}</summary>`;
  for(const g of theme.groups){
   const rows=g.layers.filter(layer=>{const chosen=selected(layer,g);return chosen.length&&(!only||layer.variants.some(v=>v.source_ids.some(id=>state.active.has(id))))&&(!q||normal([theme.display_name,g.display_name,layer.display_name,...layer.variants.map(v=>Object.values(v.dimensions).join(' '))].join(' ')).includes(q))});if(!rows.length)continue;
   const groupNode=document.createElement('details');groupNode.className='catalog-group';groupNode.open=Boolean(q||only||rows.some(l=>l.variants.some(v=>v.source_ids.some(id=>state.active.has(id)))));groupNode.innerHTML=`<summary>${esc(g.display_name)} <span>${rows.length}</span></summary>`;
   const controls=document.createElement('div');controls.className='variant-controls';
   for(const key of ['mode','year','territory','level']){if(!g.facets[key]||g.facets[key].length<2)continue;let values=g.facets[key];if(key==='year'&&g.facets.mode)values=[...new Set(g.layers.flatMap(l=>l.variants).filter(v=>v.dimensions.mode===g.selection.mode).map(v=>v.dimensions.year))].sort();if(!values.includes(g.selection[key])&&g.selection[key]!=='Tous')g.selection[key]=values.at(-1);
    const label=({mode:'Mode',year:'Millésime / période',territory:'Territoire / département',level:'Niveau / profondeur'})[key];
    const wrap=document.createElement(key==='level'?'fieldset':'label');
    if(key==='level')wrap.innerHTML='<legend>'+esc(label)+'</legend>'+values.map(v=>`<label><input type="radio" name="level-${g.id}" value="${esc(v)}" ${g.selection[key]===v?'checked':''}>${esc(v)}</label>`).join('');
    else wrap.innerHTML=esc(label)+`<select aria-label="${esc(label+' · '+g.display_name)}">`+(key==='territory'&&g.display_name!=='TVB locales'?'<option value="Tous">Tous les territoires</option>':'')+values.map(v=>`<option ${g.selection[key]===v?'selected':''}>${esc(v)}</option>`).join('')+'</select>';
    if(key==='territory'&&g.selection[key]==='Tous'&&wrap.querySelector('select'))wrap.querySelector('select').value='Tous';
    wrap.querySelectorAll('input,select').forEach(input=>input.onchange=async()=>{const active=g.layers.filter(l=>l.variants.some(v=>v.source_ids.some(id=>state.active.has(id))));for(const l of active)for(const v of l.variants)for(const id of v.source_ids)if(state.active.has(id))await toggle(meta.get(id),false);g.selection[key]=input.value;if(key==='mode'){const years=g.layers.flatMap(l=>l.variants).filter(v=>v.dimensions.mode===input.value).map(v=>v.dimensions.year).filter(Boolean).sort();if(years.length)g.selection.year=years.at(-1)}for(const l of active)for(const m of selected(l,g))await toggle(m,true);renderGroupedCatalog(state,toggle,sourceDetail,saveView)});
    controls.append(wrap);
   }
   groupNode.append(controls);
   for(const layer of rows){const chosen=selected(layer,g),ids=chosen.map(l=>l.id);const active=ids.some(id=>state.active.has(id));const partial=chosen.some(l=>l.status==='PARTIAL');const row=document.createElement('article');row.className='layer';const dims=chooseVariants(layer,g).map(v=>Object.values(v.dimensions).join(' · ')).filter(Boolean).join(' / ');
    row.innerHTML=`<div class="layer-main"><input type="checkbox" aria-label="Afficher ${esc(layer.display_name+' · '+g.display_name)}" ${active?'checked':''} ${chosen.some(l=>l.map_count)?'':'disabled'}><button class="layer-name">${esc(layer.display_name)}</button></div><div class="layer-meta"><span class="badge ${partial?'partial':''}">${partial?'Partiel':chosen.every(l=>l.kind==='FILE')?'Fichier vérifié':'Collecte complète'}</span><span class="layer-count">${fmt(chosen.reduce((s,l)=>s+l.map_count,0))} objets${dims?' · '+esc(dims):''}</span></div>${chosen.some(l=>l.map_count>50000)?'<p class="micro zoom-note">Mailles à petite échelle · objets au zoom 13+</p>':''}`;
    row.querySelector('input').onchange=async e=>{for(const m of chosen)await toggle(m,e.target.checked);saveView()};row.querySelector('button').onclick=()=>sourceDetail({...chosen[0],display_name:layer.display_name,alternative_source_ids:[...new Set(chooseVariants(layer,g).flatMap(v=>v.source_ids))],catalog_theme:theme.display_name,catalog_group:g.display_name});groupNode.append(row);shown++;themeRows++;
   }
   themeNode.append(groupNode);
  }
  if(themeRows){themeNode.open=Boolean(themeFilter||q||only||themeNode.querySelector('details[open]'));root.append(themeNode)}
 }
 $('result-count').textContent=fmt(shown)+' couches thématiques · '+fmt(state.active.size)+' sources activées';if(!shown)root.innerHTML='<p class="micro">Aucune couche pour ces filtres. Les sources techniques et téléchargements restent dans Sources & méthode.</p>';
 $('visible-count').textContent=fmt(state.active.size)+' sources activées · '+fmt([...state.active].reduce((s,id)=>s+(meta.get(id)?.map_count||0),0))+' objets disponibles';
}
export function hydrateSelections(tree,sourceIds){
 const wanted=new Set(sourceIds);
 for(const theme of tree.themes)for(const g of theme.groups){const chosen=g.layers.flatMap(l=>l.variants).filter(v=>wanted.has(v.source_id));for(const key of Object.keys(g.facets)){const values=[...new Set(chosen.map(v=>v.dimensions[key]).filter(Boolean))].sort();if(values.length)g.selection[key]=key==='territory'&&values.length>1&&g.display_name!=='TVB locales'?'Tous':values.at(-1)}}
 return tree.themes.flatMap(t=>t.groups.flatMap(g=>g.layers.flatMap(l=>chooseVariants(l,g).filter(v=>wanted.has(v.source_id)).map(v=>v.source_id))));
}
