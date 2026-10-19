/** Self-hosted MapLibre map with local data and an SVG fallback. */
import { escapeHTML, formatNumber } from './core.js';

const palette = ['#e6e9b4', '#a5c784', '#659d70', '#326f59', '#164538'];
const heatPalette = ['#313695', '#74add1', '#ffffbf', '#f46d43', '#a50026'];
const empty = { type: 'FeatureCollection', features: [] };

export class AtlasMap {
  constructor(onSelect) {
    this.onSelect = onSelect;
    this.map = null;
    this.features = empty;
    this.selected = new Set();
    this.layers = new Map();
    this.view3d = false;
    this.palette = heatPalette;
    this.popup = null;
    this.ready = false;
    this.bounds = null;
    this.fallback = false;
  }

  async initialise(collection) {
    this.features = collection;
    this.bounds = this.calculateBounds(collection);
    try {
      // MapLibre 5 does not export supported(). Construction detects WebGL failure.
      if (typeof window.maplibregl?.Map !== 'function') {
        this.useFallback();
        return;
      }
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
      const colour = this.colourExpression();
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
    const points = [];
    function collect(coords) {
      if (typeof coords[0] === 'number') points.push(coords);
      else coords.forEach(collect);
    }
    collection.features.forEach(feature => collect(feature.geometry.coordinates));
    return [
      [Math.min(...points.map(p => p[0])), Math.min(...points.map(p => p[1]))],
      [Math.max(...points.map(p => p[0])), Math.max(...points.map(p => p[1]))],
    ];
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

  colourExpression() {
    return ['case', ['==', ['get', 'missing'], true], '#c7cdc3',
      ['interpolate', ['linear'], ['coalesce', ['get', 'display'], 0],
        0, this.palette[0], 25, this.palette[1], 50, this.palette[2],
        75, this.palette[3], 100, this.palette[4]]];
  }

  setHeatmap(enabled) {
    this.palette = enabled ? heatPalette : palette;
    document.querySelector('.gradient').style.background =
      `linear-gradient(90deg, ${this.palette.join(', ')})`;
    if (this.fallback) this.drawFallback();
    else if (this.ready) {
      this.map.setPaintProperty('cells-flat', 'fill-color', this.colourExpression());
      this.map.setPaintProperty('cells-3d', 'fill-extrusion-color', this.colourExpression());
    }
  }

  duration() {
    return matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 650;
  }

  reset() {
    if (this.map && !this.fallback) {
      this.map.fitBounds(this.bounds, { padding: 45, duration: this.duration(), pitch: this.view3d ? 48 : 0 });
    }
  }

  focus(feature) {
    if (!this.map || this.fallback) return;
    const bounds = this.calculateBounds({ type: 'FeatureCollection', features: [feature] });
    this.map.fitBounds(bounds, { padding: 100, maxZoom: 13, duration: this.duration() });
  }

  async toggleLayer(name, visible, year = '2016') {
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
    this.map?.remove();
    this.map = null;
    this.ready = false;
    this.fallback = true;
    document.getElementById('map').hidden = true;
    document.getElementById('fallback').hidden = false;
    document.getElementById('mode-3d').disabled = true;
    this.drawFallback();
  }

  drawFallback() {
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
      path.setAttribute('fill', p.missing ? '#c7cdc3' : this.palette[Math.max(0, Math.min(4, Math.floor(p.display / 25)))]);
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
