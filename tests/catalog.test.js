import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {chooseVariants} from '../dist/catalog-ui.js';
import {normaliseFeatures} from '../dist/custom-data.js';
const tree=JSON.parse(fs.readFileSync(new URL('../dist/data/atlas/catalog-v2.json',import.meta.url)));
const groups=tree.themes.flatMap(t=>t.groups),variants=groups.flatMap(g=>g.layers.flatMap(l=>l.variants));
test('every original source is retained exactly once in catalogue or audit',()=>{
 const ids=[...variants.flatMap(v=>v.source_ids),...tree.hidden_sources.map(s=>s.source_id)];assert.equal(ids.length,354);assert.equal(new Set(ids).size,354);
});
test('hydrographic formats become one logical layer with source alternatives',()=>{
 const layers=groups.flatMap(g=>g.layers).filter(l=>l.display_name==='Bassins hydrographiques');assert.equal(layers.length,1);assert.equal(layers[0].variants.length,1);assert.ok(layers[0].variants[0].source_ids.length>=6);
});
test('Nature en Ville selects one year per sublayer',()=>{
 const g=groups.find(g=>g.display_name==='Nature en Ville');g.selection={year:'2023'};assert.equal(g.layers.length,4);for(const l of g.layers){const selected=chooseVariants(l,g);assert.equal(selected.length,1);assert.equal(selected[0].dimensions.year,'2023')}
});
test('CSV / GeoJSON coordinates are not guessed or accepted in a projected CRS',()=>{
 assert.throws(()=>normaliseFeatures({type:'Feature',geometry:{type:'Point',coordinates:[450000,6900000]},properties:{}}),/WGS84/);const fc=normaliseFeatures({type:'Feature',geometry:null,properties:{name:'table only'}});assert.equal(fc.features[0].geometry,null);
});
