#!/usr/bin/env python3
"""Export the photo species classifier's real metrics for the « Modèles IA » page.

Reads datasets/normandie_species/model/ (metrics.json, classes.json, confusions.csv) and the
training_set folders, and writes dist/data/normandie/species_model_status.json. Nothing is invented:
if the model has not been trained, the file says so and the page shows the model as blocked.

    .venv-normandie/bin/python ml/export_species_status.py
"""
from __future__ import annotations

import collections
import csv
import datetime as dt
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODEL = ROOT / 'datasets/normandie_species/model'
DATA = ROOT / 'datasets/normandie_species/training_set'
OUT = ROOT / 'dist/data/normandie/species_model_status.json'
IMG = {'.jpg', '.jpeg', '.png', '.webp'}
GROUP_FR = {'amphibians': 'Amphibiens', 'arachnids': 'Arachnides', 'birds': 'Oiseaux', 'conifers': 'Conifères',
            'crustaceans': 'Crustacés', 'ferns': 'Fougères', 'fish': 'Poissons', 'flowering_plants': 'Plantes à fleurs',
            'insects': 'Insectes', 'mammals': 'Mammifères', 'molluscs': 'Mollusques', 'mosses': 'Mousses',
            'reptiles': 'Reptiles'}


def counts(split):
    root = DATA / split
    if not root.exists():
        return collections.Counter()
    return collections.Counter({d.name: sum(1 for f in d.iterdir() if f.suffix.lower() in IMG)
                                for d in root.iterdir() if d.is_dir()})


def main():
    if not (MODEL / 'metrics.json').exists() or not (MODEL / 'model.pt').exists():
        status = {'status': 'blocked', 'reason': 'Modèle non entraîné : lancer ml/train_species.py.'}
    else:
        m = json.loads((MODEL / 'metrics.json').read_text())
        classes = json.loads((MODEL / 'classes.json').read_text())
        names = {c['folder']: c.get('french_name') or c['scientific_name'] for c in classes}
        train, test = counts('train'), counts('test')
        n_test = sum(test.values()) or 1
        # Reference to beat: always answer the species most represented in the training photos.
        ranked = [k for k, _ in train.most_common()]
        base_top1 = test[ranked[0]] / n_test if ranked else None
        base_top5 = sum(test[k] for k in ranked[:5]) / n_test if ranked else None
        confusions = []
        if (MODEL / 'confusions.csv').exists():
            with open(MODEL / 'confusions.csv', newline='') as f:
                for r in list(csv.DictReader(f))[:8]:
                    confusions.append({'true': names.get(r['true'], r['true']), 'pred': names.get(r['predicted'], r['predicted']),
                                       'count': int(r['count'])})
        cal = m.get('calibration_auto_accept', {})
        status = {
            'status': 'trained_exploratory', 'beats_baseline': m['test_top1'] > (base_top1 or 0) * 2,
            'arch': m['arch'], 'image_size': m['image_size'], 'classes': m['classes'], 'images': m['images'],
            'epochs': len(m.get('history', [])), 'history': m.get('history', []),
            'test_top1': m['test_top1'], 'test_top5': m['test_top5'], 'val_top1_best': m.get('val_top1_best'),
            'baseline': {'name': f'Toujours répondre l’espèce la plus photographiée ({names.get(ranked[0], ranked[0]) if ranked else "—"})',
                         'top1': base_top1, 'top5': base_top5, 'chance_top1': 1 / m['classes']},
            'per_group': [{'group': GROUP_FR.get(g, g), **v} for g, v in sorted(m.get('per_group', {}).items(),
                                                                                key=lambda x: -x[1]['images'])],
            'calibration': {'threshold': cal.get('threshold'), 'test_precision': cal.get('test_precision'),
                            'test_coverage': cal.get('test_coverage'), 'target_precision': cal.get('target_precision')},
            'confusions': confusions,
            'worst_classes_zero': sum(1 for w in m.get('worst_classes', []) if w.get('top1') == 0),
        }
    status['built_at'] = dt.datetime.now().isoformat(timespec='seconds')
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(status, ensure_ascii=False, indent=1))
    print(f'wrote {OUT.relative_to(ROOT)} · {status["status"]}')


if __name__ == '__main__':
    main()
