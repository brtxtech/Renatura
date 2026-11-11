"""Renatura species-recognition model inside the workbench (image references).

Model: datasets/normandie_species/model (trained by ml/train_species.py, EfficientNet-B0, 739 Normandy
species). Labels / statuses: datasets/normandie_species/labels/species_labels_full.csv (TAXREF).
The prediction ENRICHES the image record; it never blocks it. Below the calibrated threshold
(95 % precision on the validation split) the species is only « à confirmer ».
"""
from __future__ import annotations

import csv
import json
from functools import lru_cache

from . import db

MODEL_DIR = db.PROJECT / 'datasets' / 'normandie_species' / 'model'
LABELS = db.PROJECT / 'datasets' / 'normandie_species' / 'labels' / 'species_labels_full.csv'


def available() -> tuple[bool, str]:
    if not (MODEL_DIR / 'model.pt').exists():
        return False, 'Modèle absent (datasets/normandie_species/model/model.pt) : lancer ml/train_species.py'
    try:
        import timm  # noqa: F401
        import torch  # noqa: F401
    except ImportError as e:
        return False, f'Dépendance manquante pour le modèle : {e.name}'
    return True, ''


@lru_cache(maxsize=1)
def _load():
    import timm
    import torch
    from torchvision import transforms
    ck = torch.load(MODEL_DIR / 'model.pt', map_location='cpu')
    net = timm.create_model(ck['arch'], pretrained=False, num_classes=len(ck['classes']))
    net.load_state_dict(ck['state_dict'])
    net.eval()
    tf = transforms.Compose([transforms.Resize(int(ck['size'] * 1.14)), transforms.CenterCrop(ck['size']),
                             transforms.ToTensor(), transforms.Normalize(ck['mean'], ck['std'])])
    classes = json.loads((MODEL_DIR / 'classes.json').read_text(encoding='utf-8'))
    metrics = json.loads((MODEL_DIR / 'metrics.json').read_text(encoding='utf-8'))
    labels = {}
    if LABELS.exists():
        with open(LABELS, encoding='utf-8') as f:
            labels = {r['scientific_name']: r for r in csv.DictReader(f)}
    return torch, net, tf, classes, metrics, labels


def predict(image) -> dict:
    """image: PIL image (any mode). Returns the enrichment stored on the reference and the record."""
    torch, net, tf, classes, metrics, labels = _load()
    with torch.no_grad():
        p = torch.softmax(net(tf(image.convert('RGB')).unsqueeze(0)), 1)[0].numpy()
    order = p.argsort()[::-1][:5]
    top5 = []
    for i in order:
        c = classes[int(i)]
        lab = labels.get(c['scientific_name'], {})
        top5.append({'scientific_name': c['scientific_name'], 'french_name': c.get('french_name') or lab.get('french_name', ''),
                     'group': c.get('group_en', ''), 'probability': round(float(p[i]), 4),
                     'protected_france': lab.get('protected_france') == 'True',
                     'red_list_normandie': lab.get('red_list_normandie') or None,
                     'is_invasive': lab.get('is_invasive') == 'True'})
    cal = metrics.get('calibration_auto_accept') or {}
    threshold = cal.get('threshold')
    best = top5[0]
    confident = threshold is not None and best['probability'] >= threshold
    return {'status': 'proposed_high_confidence' if confident else 'to_confirm',
            'status_label': 'proposée (confiance haute)' if confident else 'à confirmer par un expert',
            'species': best, 'top5': top5, 'threshold': threshold,
            'model': {'arch': metrics.get('arch'), 'classes': metrics.get('classes'), 'test_top1': metrics.get('test_top1'),
                      'test_top5': metrics.get('test_top5'), 'precision_above_threshold': cal.get('test_precision')},
            'note': 'Proposition automatique : à confirmer par un naturaliste avant tout usage réglementaire.'}
