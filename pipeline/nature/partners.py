"""Manage partner keys for the nature-photo service (keys stored hashed).

    python -m pipeline.nature.partners add "CEN Normandie" --expert
    python -m pipeline.nature.partners list
    python -m pipeline.nature.partners remove "CEN Normandie"
"""
import argparse
import hashlib
import json
import secrets

from pipeline.nature.server import STORE


def load():
    f = STORE / 'partners.json'
    return json.loads(f.read_text()) if f.exists() else {}


def save(p):
    f = STORE / 'partners.json'
    f.write_text(json.dumps(p, ensure_ascii=False, indent=1))
    f.chmod(0o600)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('add')
    a.add_argument('name')
    a.add_argument('--expert', action='store_true')
    sub.add_parser('list')
    r = sub.add_parser('remove')
    r.add_argument('name')
    args = ap.parse_args()
    p = load()
    if args.cmd == 'add':
        key = secrets.token_urlsafe(24)
        p[hashlib.sha256(key.encode()).hexdigest()] = {'name': args.name, 'expert': args.expert}
        save(p)
        print(f'Partner "{args.name}" ({"expert" if args.expert else "partner"}) key (shown once): {key}')
    elif args.cmd == 'list':
        for v in p.values():
            print(v['name'], '(expert)' if v.get('expert') else '')
    else:
        p = {k: v for k, v in p.items() if v['name'] != args.name}
        save(p)
        print('removed', args.name)
