#!/usr/bin/env python3
"""Rebuild dist/data/species-observations.json (map « Où les espèces ont-elles été photographiées ? »)
from the full labelled photo set (datasets/normandie_species/labels/image_labels_full.csv).

Keeps the record format read by dist/species-map.js; only photos whose file exists are kept.
Sensitive species (protected in France or VU/EN/CR on the Normandy red list) are shown at
~10 km precision, as on the nature-photo page.
"""
import csv
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / 'datasets/normandie_species/labels/image_labels_full.csv'
IMAGES = ROOT / 'datasets/normandie_species/images'
OUT = ROOT / 'dist/data/species-observations.json'


def main():
    out, skipped = [], 0
    for r in csv.DictReader(open(SRC, encoding='utf-8')):
        rel = r['image_path'].removeprefix('images/')
        if not (IMAGES / rel).exists() or not r['latitude'] or not r['longitude']:
            skipped += 1
            continue
        lat, lon = float(r['latitude']), float(r['longitude'])
        protected = r['protected_france'] == 'True'
        red = r['red_list_normandie'] or ''
        sensitive = protected or any(code in red.split(';') for code in ('VU', 'EN', 'CR'))
        if sensitive:  # ~10 km grid
            lat, lon = round(lat / 0.09) * 0.09, round(lon / 0.135) * 0.135
        out.append({'lat': round(lat, 4), 'lon': round(lon, 4), 'group': r['group_fr'], 'sci': r['scientific_name'],
                    'fr': r['french_name'], 'en': r['english_name'], 'img': rel, 'src': r['source'],
                    'attr': r['attribution'], 'lic': r['license'], 'date': r['observed_on'], 'url': r['observation_url'],
                    'protected': protected, 'redlist': red.split(';')[0] if red else '', 'generalised': sensitive})
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'{len(out)} observations written ({skipped} skipped: missing file or position) -> {OUT.relative_to(ROOT)} '
          f'({OUT.stat().st_size / 1e6:.1f} MB)')


if __name__ == '__main__':
    main()
