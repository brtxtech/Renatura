/** Self-hosted MapLibre map with local data and an SVG fallback. */
import { escapeHTML, formatNumber } from './core.js';
import { attachOrientation } from './orientation.js';

const palette = ['#e6e9b4', '#a5c784', '#659d70', '#326f59', '#164538'];
const empty = { type: 'FeatureCollection', features: [] };

export class AtlasMap {
  constructor(onSelect) {
    this.onSelect = onSelect;
    this.map = null;
    this.features = empty;
    this.selected = new Set();
    this.layers = new Map();
    this.view3d = false;
    this.popup = null;
    this.ready = false;
    this.bounds = null;
    this.fallback = false;
  }

  async initialise(collection) {
    this.features = collection;
    this.bounds = this.calculateBounds(collection);
    if (!window.maplibregl?.Map || (typeof window.maplibregl.supported === 'function' && !window.maplibregl.supported())) {
      this.useFallback();
      return;
    }
    try {
      this.map = new window.maplibregl.Map({
        container: 'map',
        style: {
          version: 8,
          sources: {},
          layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#e9eee4' } }],
        },
        bounds: this.bounds,
        fitBoundsOptions: { padding: 45 },
        attributionControl: false,
        maxZoom: 16,
        minZoom: 8,
        maxPitch: 65,
        renderWorldCopies: false,
        antialias: false,
      });
      this.map.addControl(new window.maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');
      this.map.addControl(new window.maplibregl.ScaleControl({ maxWidth: 100, unit: 'metric' }), 'bottom-right');
      this.map.addControl(new window.maplibregl.AttributionControl({
        compact: true,
        customAttribution: 'DREAL Normandie · Licence Ouverte 2.0 · Modèle exploratoire',
      }));
      await new Promise((resolve, reject) => {
        this.map.once('load', resolve);
        this.map.once('error', event => reject(event.error));
      });
      this.map.addSource('cells', { type: 'geojson', data: collection });
      const colour = ['case', ['==', ['get', 'missing'], true], '#c7cdc3',
        ['interpolate', ['linear'], ['get', 'display'],
          0, palette[0], 25, palette[1], 50, palette[2], 75, palette[3], 100, palette[4]]];
      this.map.addLayer({
        id: 'cells-flat', type: 'fill', source: 'cells',
        paint: { 'fill-color': colour, 'fill-opacity': .82 },
      });
      this.map.addLayer({
        id: 'cells-3d', type: 'fill-extrusion', source: 'cells',
        layout: { visibility: 'none' },
        paint: {
          'fill-extrusion-color': colour,
          'fill-extrusion-height': ['*', ['get', 'display'], 8],
          'fill-extrusion-opacity': .9,
        },
      });
      this.map.addLayer({
        id: 'cells-lines', type: 'line', source: 'cells',
        paint: { 'line-color': '#f6f7eb', 'line-width': .6, 'line-opacity': .85 },
      });
      this.map.addLayer({
        id: 'selection', type: 'line', source: 'cells',
        filter: ['==', ['get', 'selected'], true],
        paint: { 'line-color': '#c27028', 'line-width': 3 },
      });
      for (const layer of ['cells-flat', 'cells-3d']) {
        this.map.on('click', layer, event => this.onSelect(event.features[0].properties.id));
        this.map.on('mouseenter', layer, () => { this.map.getCanvas().style.cursor = 'pointer'; });
        this.map.on('mouseleave', layer, () => {
          this.map.getCanvas().style.cursor = '';
          this.popup?.remove();
        });
        this.map.on('mousemove', layer, event => {
          const p = event.features[0].properties;
          this.popup?.remove();
          this.popup = new window.maplibregl.Popup({ closeButton: false, closeOnClick: false })
            .setLngLat(event.lngLat)
            .setHTML(`<strong>${escapeHTML(p.commune)}</strong><br>${escapeHTML(p.id)}<br>Score: ${p.missing ? '—' : formatNumber(p.display, 1)} · ${p.coverage}%`)
            .addTo(this.map);
        });
      }
      this.map.getCanvas().addEventListener('webglcontextlost', event => {
        event.preventDefault();
        this.useFallback();
      });
      attachOrientation(this.map,'maplibre');
      this.ready = true;
      this.update(collection);
    } catch (error) {
      console.warn('Map fallback:', error.message);
      this.map?.remove();
      this.map = null;
      this.useFallback();
    }
  }

  calculateBounds(collection) {
    // Loop instead of Math.min(...points): spreading hundreds of thousands of vertices overflows the call stack.
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    function collect(coords) {
      if (typeof coords[0] === 'number') {
        if (coords[0] < minX) minX = coords[0];
        if (coords[0] > maxX) maxX = coords[0];
        if (coords[1] < minY) minY = coords[1];
        if (coords[1] > maxY) maxY = coords[1];
      } else coords.forEach(collect);
    }
    collection.features.forEach(feature => collect(feature.geometry.coordinates));
    return [[minX, minY], [maxX, maxY]];
  }

  update(collection) {
    this.features = collection;
    if (this.fallback) this.drawFallback();
    else if (this.ready) this.map.getSource('cells').setData(collection);
  }

  set3d(value) {
    if (this.fallback || !this.ready) return false;
    this.view3d = value;
    this.map.setLayoutProperty('cells-flat', 'visibility', value ? 'none' : 'visible');
    this.map.setLayoutProperty('cells-3d', 'visibility', value ? 'visible' : 'none');
    this.map.easeTo({ pitch: value ? 48 : 0, bearing: value ? -12 : 0, duration: this.duration() });
    return true;
  }

  duration() {
    return matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 650;
  }

  resize() { this.leaflet?.invalidateSize(); this.map?.resize(); }

  reset() {
    if(this.leaflet){this.leaflet.fitBounds([[this.bounds[0][1],this.bounds[0][0]],[this.bounds[1][1],this.bounds[1][0]]],{padding:[45,45]});return;}
    if (this.map && !this.fallback) {
      this.map.fitBounds(this.bounds, { padding: 45, duration: this.duration(), pitch: this.view3d ? 48 : 0 });
    }
  }

  focus(feature) {
    if(this.leaflet){const b=this.calculateBounds({type:"FeatureCollection",features:[feature]});this.leaflet.fitBounds([[b[0][1],b[0][0]],[b[1][1],b[1][0]]],{padding:[75,75],maxZoom:13});return;}
    if (!this.map || this.fallback) return;
    const bounds = this.calculateBounds({ type: 'FeatureCollection', features: [feature] });
    this.map.fitBounds(bounds, { padding: 100, maxZoom: 13, duration: this.duration() });
  }

  async toggleLayer(name, visible, year = '2016') {
    if (this.leaflet) {
      this.leafletLayers ||= new Map();
      if(name==='hedges')for(const [key,l] of this.leafletLayers)if(key.startsWith('hedges-'))this.leaflet.removeLayer(l);
      const id=name==='hedges'?`hedges-${year}`:name;
      if(!this.leafletLayers.has(id)&&visible){const r=await fetch(`data/${id}.geojson`);if(!r.ok)throw Error('Couche indisponible : '+id);const data=await r.json();this.leafletLayers.set(id,L.geoJSON(data,{interactive:false,style:{color:name==='routes'?'#b57e43':name==='boundary'?'#56774e':'#294e34',weight:name==='hedges'?1:2,fillColor:'#294e34',fillOpacity:.6,dashArray:name==='boundary'?'6 4':name==='routes'?'4 4':undefined}}));}
      const layer=this.leafletLayers.get(id);if(layer){if(visible)layer.addTo(this.leaflet);else this.leaflet.removeLayer(layer)}return true;
    }
    if (this.fallback) return false;
    if (!this.ready) return false;
    if (name === 'hedges') {
      for (const id of this.layers.keys()) {
        if (id.startsWith('hedges-')) this.map.setLayoutProperty(id, 'visibility', 'none');
      }
    }
    const id = name === 'hedges' ? `hedges-${year}` : name;
    if (!this.layers.has(id) && visible) {
      const response = await fetch(`data/${id}.geojson`);
      if (!response.ok) throw new Error(`Layer unavailable: ${id}`);
      const data = await response.json();
      if (!this.layers.has(id)) {
        this.map.addSource(id, { type: 'geojson', data });
        const paints = {
          boundary: { 'line-color': '#56774e', 'line-width': 2.5, 'line-dasharray': [3, 2] },
          routes: { 'line-color': '#b57e43', 'line-width': 2, 'line-dasharray': [2, 2] },
          woodland: { 'fill-color': '#294e34', 'fill-opacity': .6 },
          hedges: { 'line-color': '#193e30', 'line-width': 1 },
        };
        this.map.addLayer({ id, source: id, type: name === 'woodland' ? 'fill' : 'line', paint: paints[name] });
        this.layers.set(id, data);
      }
    }
    if (this.layers.has(id)) this.map.setLayoutProperty(id, 'visibility', visible ? 'visible' : 'none');
    return true;
  }

  useFallback() {
    this.fallback = true;
    if(window.L?.map){
      this.map?.remove();this.map=null;document.getElementById('map').hidden=false;document.getElementById('fallback').hidden=true;document.getElementById('mode-3d').disabled=true;
      if(!this.leaflet){this.leaflet=L.map('map',{preferCanvas:true,zoomControl:false,zoomSnap:.25,zoomDelta:.5,minZoom:8,maxZoom:16}).fitBounds([[this.bounds[0][1],this.bounds[0][0]],[this.bounds[1][1],this.bounds[1][0]]],{padding:[45,45]});L.control.zoom({position:'topright'}).addTo(this.leaflet);L.control.scale({position:'bottomright',imperial:false}).addTo(this.leaflet);this.leaflet.attributionControl.addAttribution('DREAL Normandie · Licence Ouverte 2.0 · Modèle exploratoire');attachOrientation(this.leaflet,'leaflet');}
      this.ready=true;this.drawFallback();return;
    }
    document.getElementById('map').hidden = true;
    document.getElementById('fallback').hidden = false;
    document.getElementById('mode-3d').disabled = true;
    this.drawFallback();
  }

  drawFallback() {
    if(this.leaflet){
      if(this.cellLayer)this.leaflet.removeLayer(this.cellLayer);
      this.cellLayer=L.geoJSON(this.features,{style:f=>{const p=f.properties;return {fillColor:p.missing?'#c7cdc3':palette[Math.min(4,Math.floor(p.display/25))],fillOpacity:.82,color:p.selected?'#c27028':'#fafbee',weight:p.selected?3:.7}},onEachFeature:(f,l)=>{l.bindTooltip(escapeHTML(f.properties.commune)+' · '+escapeHTML(f.properties.id));l.on('click',()=>this.onSelect(f.properties.id))}}).addTo(this.leaflet);return;
    }
    const svg = document.getElementById('fallback-map');
    svg.replaceChildren();
    const [[west, south], [east, north]] = this.bounds;
    const cosine = Math.cos((south + north) / 2 * Math.PI / 180);
    const scale = Math.min(900 / ((east - west) * cosine), 580 / (north - south));
    const project = point => [50 + (point[0] - west) * cosine * scale, 650 - (point[1] - south) * scale];
    for (const feature of this.features.features) {
      const geometry = feature.geometry;
      const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates;
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      const d = polygons.map(rings => rings.map(ring => ring.map((point, index) =>
        `${index ? 'L' : 'M'}${project(point).join(',')}`).join(' ') + 'Z').join(' ')).join(' ');
      const p = feature.properties;
      path.setAttribute('d', d);
      path.setAttribute('fill-rule', 'evenodd');
      path.setAttribute('fill', p.missing ? '#c7cdc3' : palette[Math.min(4, Math.floor(p.display / 25))]);
      path.setAttribute('stroke', p.selected ? '#c27028' : '#fafbee');
      path.setAttribute('stroke-width', p.selected ? '3' : '.7');
      path.setAttribute('tabindex', '0');
      path.setAttribute('role', 'button');
      path.setAttribute('aria-label', `${p.commune}, ${p.id}`);
      path.addEventListener('click', () => this.onSelect(p.id));
      path.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          this.onSelect(p.id);
        }
      });
      svg.append(path);
    }
  }
}
