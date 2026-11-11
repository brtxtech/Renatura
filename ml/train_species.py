#!/usr/bin/env python3
"""Train + evaluate the Normandy species classifier (Extension 1 · photos).

Fine-tunes a pretrained EfficientNet-B0 (timm) on datasets/normandie_species/training_set
(ImageFolder: train/val/test, one folder per species). Selects the best epoch on validation,
then evaluates once on the untouched test split.

Outputs (datasets/normandie_species/model/):
  model.pt                weights + class list + preprocessing
  classes.json            class index -> scientific name, French name, group
  metrics.json            top-1/top-5 overall and per group, per-class accuracy, calibration
  confusions.csv          most frequent confusions on the test split
  test_predictions.csv    every test image: true label, top-5, confidence

    .venv-normandie/bin/python ml/train_species.py --epochs 8
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import math
import pathlib
import time

import numpy as np
import timm
import torch
from torch import nn
from torch.utils.data import DataLoader
from torchvision import datasets, transforms

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / 'datasets/normandie_species/training_set'
OUT = ROOT / 'datasets/normandie_species/model'
MEAN, STD = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)


def safe_loader(path):
    """Never crash a multi-hour run on one unreadable file: log it and use a blank image."""
    from PIL import Image
    try:
        with open(path, 'rb') as f:
            return Image.open(f).convert('RGB')
    except Exception as e:
        print(f'  ! unreadable image skipped: {path} ({type(e).__name__})', flush=True)
        return Image.new('RGB', (256, 256))


def loaders(size, batch, workers):
    train_tf = transforms.Compose([
        transforms.RandomResizedCrop(size, scale=(0.5, 1.0)), transforms.RandomHorizontalFlip(),
        transforms.ColorJitter(0.2, 0.2, 0.2), transforms.ToTensor(), transforms.Normalize(MEAN, STD)])
    eval_tf = transforms.Compose([
        transforms.Resize(int(size * 1.14)), transforms.CenterCrop(size), transforms.ToTensor(),
        transforms.Normalize(MEAN, STD)])
    sets = {s: datasets.ImageFolder(DATA / s, train_tf if s == 'train' else eval_tf, loader=safe_loader) for s in ('train', 'val', 'test')}
    # same class order everywhere (ImageFolder sorts folder names; val/test may miss rare classes)
    classes = sets['train'].classes
    for s in ('val', 'test'):
        remap = {i: classes.index(c) for i, c in enumerate(sets[s].classes)}
        sets[s].samples = [(p, remap[t]) for p, t in sets[s].samples]
        sets[s].targets = [t for _, t in sets[s].samples]
    dl = {s: DataLoader(ds, batch_size=batch, shuffle=(s == 'train'), num_workers=workers,
                        persistent_workers=workers > 0) for s, ds in sets.items()}
    return sets, dl, classes


@torch.no_grad()
def predict(model, loader, device):
    model.eval()
    probs, targets = [], []
    for x, y in loader:
        probs.append(torch.softmax(model(x.to(device)), 1).cpu())
        targets.append(y)
    return torch.cat(probs).numpy(), torch.cat(targets).numpy()


def topk(probs, targets, k):
    return float((np.argsort(-probs, 1)[:, :k] == targets[:, None]).any(1).mean())


def calibration(probs, targets, precision=0.95):
    """Lowest confidence threshold whose auto-accepted predictions reach the target precision."""
    conf, pred = probs.max(1), probs.argmax(1)
    order = np.argsort(-conf)
    correct = (pred[order] == targets[order]).astype(float)
    prec = np.cumsum(correct) / np.arange(1, len(correct) + 1)
    ok = np.flatnonzero(prec >= precision)
    if not len(ok):
        return {'target_precision': precision, 'threshold': None, 'coverage': 0.0}
    i = ok.max()
    return {'target_precision': precision, 'threshold': float(conf[order][i]),
            'coverage': float((i + 1) / len(conf)), 'precision': float(prec[i])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--epochs', type=int, default=8)
    ap.add_argument('--size', type=int, default=224)
    ap.add_argument('--batch', type=int, default=64)
    ap.add_argument('--lr', type=float, default=5e-4)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--arch', default='efficientnet_b0')
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    device = 'mps' if torch.backends.mps.is_available() else 'cuda' if torch.cuda.is_available() else 'cpu'
    torch.manual_seed(42)
    sets, dl, classes = loaders(a.size, a.batch, a.workers)
    info = {r['folder']: r for r in csv.DictReader(open(DATA / 'classes.csv', encoding='utf-8'))}
    print(f'device={device} classes={len(classes)} train={len(sets["train"])} val={len(sets["val"])} test={len(sets["test"])}', flush=True)

    model = timm.create_model(a.arch, pretrained=True, num_classes=len(classes)).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=0.05)
    steps = a.epochs * len(dl['train'])
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr, total_steps=steps, pct_start=0.1)
    loss_fn = nn.CrossEntropyLoss(label_smoothing=0.1)
    best, history = -1.0, []
    for epoch in range(1, a.epochs + 1):
        model.train()
        t0, seen, run_loss = time.time(), 0, 0.0
        for x, y in dl['train']:
            x, y = x.to(device), y.to(device)
            opt.zero_grad(set_to_none=True)
            loss = loss_fn(model(x), y)
            loss.backward()
            opt.step()
            sched.step()
            seen += len(y)
            run_loss += float(loss.detach()) * len(y)
            if (seen // len(y)) % 100 == 0:
                print(f'  epoch {epoch} step {seen // len(y)}/{len(dl["train"])} loss {run_loss / seen:.3f} '
                      f'{seen / (time.time() - t0):.0f} img/s', flush=True)
        vp, vt = predict(model, dl['val'], device)
        v1, v5 = topk(vp, vt, 1), topk(vp, vt, 5)
        history.append({'epoch': epoch, 'train_loss': run_loss / seen, 'val_top1': v1, 'val_top5': v5,
                        'seconds': round(time.time() - t0)})
        print(json.dumps(history[-1]), flush=True)
        if v1 > best:
            best = v1
            torch.save({'arch': a.arch, 'size': a.size, 'mean': MEAN, 'std': STD, 'classes': classes,
                        'state_dict': model.state_dict()}, OUT / 'model.pt')

    # final evaluation on the untouched test split with the best checkpoint
    ckpt = torch.load(OUT / 'model.pt', map_location=device)
    model.load_state_dict(ckpt['state_dict'])
    tp, tt = predict(model, dl['test'], device)
    vp, vt = predict(model, dl['val'], device)
    cal = calibration(vp, vt, 0.95)  # threshold chosen on validation...
    conf, pred = tp.max(1), tp.argmax(1)
    if cal['threshold'] is not None:  # ...and checked on test
        acc = conf >= cal['threshold']
        cal['test_coverage'] = float(acc.mean())
        cal['test_precision'] = float((pred[acc] == tt[acc]).mean()) if acc.any() else None
    group = {i: info.get(c, {}).get('group_en', '?') for i, c in enumerate(classes)}
    per_group = collections.defaultdict(lambda: [0, 0, 0])
    per_class = collections.defaultdict(lambda: [0, 0])
    top5 = np.argsort(-tp, 1)[:, :5]
    for t, p, t5 in zip(tt, pred, top5):
        g = per_group[group[t]]
        g[0] += 1
        g[1] += int(p == t)
        g[2] += int(t in t5)
        per_class[t][0] += 1
        per_class[t][1] += int(p == t)
    conf_pairs = collections.Counter((classes[t], classes[p]) for t, p in zip(tt, pred) if t != p)
    metrics = {
        'arch': a.arch, 'image_size': a.size, 'device': device, 'classes': len(classes),
        'images': {s: len(ds) for s, ds in sets.items()},
        'test_top1': topk(tp, tt, 1), 'test_top5': topk(tp, tt, 5),
        'val_top1_best': best, 'history': history,
        'per_group': {g: {'images': v[0], 'top1': v[1] / v[0], 'top5': v[2] / v[0]} for g, v in sorted(per_group.items())},
        'calibration_auto_accept': cal,
        'worst_classes': sorted(({'species': classes[c], 'images': v[0], 'top1': v[1] / v[0]} for c, v in per_class.items() if v[0] >= 5),
                                key=lambda r: r['top1'])[:25],
    }
    (OUT / 'metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=1), encoding='utf-8')
    json.dump([{'index': i, 'folder': c, 'scientific_name': info.get(c, {}).get('scientific_name') or info.get(c, {}).get('label', c),
                'french_name': info.get(c, {}).get('french_name', ''), 'group_en': group[i],
                'kingdom': info.get(c, {}).get('kingdom', '')} for i, c in enumerate(classes)],
              open(OUT / 'classes.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    with open(OUT / 'confusions.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['true', 'predicted', 'count'])
        w.writerows([(a_, b_, n) for (a_, b_), n in conf_pairs.most_common(100)])
    paths = [p for p, _ in dl['test'].dataset.samples]
    with open(OUT / 'test_predictions.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['path', 'true', 'pred', 'confidence', 'top5'])
        for p, t, row in zip(paths, tt, tp):
            o = np.argsort(-row)[:5]
            w.writerow([pathlib.Path(p).relative_to(DATA), classes[t], classes[o[0]], f'{row[o[0]]:.4f}', '|'.join(classes[i] for i in o)])
    print(json.dumps({k: metrics[k] for k in ('test_top1', 'test_top5', 'calibration_auto_accept')}, indent=1))


if __name__ == '__main__':
    main()
