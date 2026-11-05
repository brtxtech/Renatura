import test from 'node:test';
import assert from 'node:assert/strict';
import {pickCityLabels} from '../dist/orientation.js';
test('city labels stay in view, prioritise large places and avoid colliding names',()=>{
 const cities=[{name:'Caen',population:100000,center:[100,100]},{name:'Nearby',population:500,center:[105,100]},{name:'Village',population:200,center:[220,180]},{name:'Offscreen',center:[-50,20]}];
 const labels=pickCityLabels(cities,11,([x,y])=>({x,y}),400,300);
 assert.deepEqual(labels.map(l=>l.city.name),['Caen','Village']);
});
test('a rural viewport keeps a named commune even without a large city',()=>{
 assert.equal(pickCityLabels([{name:'Gacé',center:[100,100],population:1800}],12,([x,y])=>({x,y}),400,300)[0].city.name,'Gacé');
});
