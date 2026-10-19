import test from 'node:test';
import assert from 'node:assert/strict';
import { AtlasMap } from '../dist/map.js';
const cells = {type:'FeatureCollection',features:[{geometry:{type:'Polygon',coordinates:[[[0,0],[1,0],[1,1],[0,0]]]},properties:{display:50}}]};
class FakeMap {
  constructor() { this.layers = new Map(); this.canvas={style:{},addEventListener(){}}; }
  addControl() {}
  once(name, fn) { if(name === 'load') queueMicrotask(fn); }
  addSource() {}
  addLayer(layer) { this.layers.set(layer.id, layer); }
  on() {}
  getCanvas() { return this.canvas; }
  getSource() { return {setData(){}}; }
  setLayoutProperty(id, prop, value) { this.layers.get(id).layout={ [prop]:value }; }
  setPaintProperty(id, prop, value) { this.layers.get(id).paint[prop]=value; }
  easeTo(options) { this.camera=options; }
  remove() {}
}
test('MapLibre without supported() loads, switches 3D and heat colours', async () => {
  globalThis.window={maplibregl:{Map:FakeMap, NavigationControl:class{}, ScaleControl:class{}, AttributionControl:class{}}};
  globalThis.matchMedia=()=>({matches:false});
  globalThis.document={querySelector:()=>({style:{}})};
  const atlas=new AtlasMap(()=>{});
  await atlas.initialise(cells);
  assert.equal(atlas.ready,true);
  assert.equal(atlas.set3d(true),true);
  assert.equal(atlas.map.layers.get('cells-3d').layout.visibility,'visible');
  assert.equal(atlas.map.camera.pitch,48);
  atlas.setHeatmap(false);
  assert.ok(JSON.stringify(atlas.map.layers.get('cells-3d').paint).includes('#164538'));
  atlas.setHeatmap(true);
  assert.ok(JSON.stringify(atlas.map.layers.get('cells-3d').paint).includes('#a50026'));
});
test('WebGL construction failure reaches fallback', async () => {
  globalThis.window={maplibregl:{Map:class {constructor(){throw new Error('No WebGL');}}}};
  const atlas=new AtlasMap(()=>{});
  let fallback=false;
  atlas.useFallback=()=>{fallback=true;};
  await atlas.initialise(cells);
  assert.equal(fallback,true);
});
