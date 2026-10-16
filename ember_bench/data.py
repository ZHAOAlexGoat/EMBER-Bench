"""Revision-pinned, subset-aware dataset downloads with SHA-256 verification."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re

REPO_ID = 'Alexzhao0605gt/EMBER-Bench'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def local_path(root, relative):
    p = PurePosixPath(relative)
    if not relative or p.is_absolute() or '..' in p.parts or '\\' in relative or ':' in relative or '_not_blur' in relative:
        raise ValueError(f'unsafe dataset path: {relative!r}')
    target = (Path(root) / relative).resolve()
    if not target.is_relative_to(Path(root).resolve()):
        raise ValueError(f'path escapes dataset directory: {relative!r}')
    return target


def select(rows, levels=None, tasks=None, limit=None):
    if levels and set(levels) - {'L1', 'L2', 'L3', 'L4'}:
        raise ValueError('levels must be L1, L2, L3, L4')
    if tasks and set(tasks) - {'P', 'C'}:
        raise ValueError('tasks must be P or C')
    if limit is not None and limit < 1:
        raise ValueError('limit must be positive')
    wanted = [r for r in rows if (not levels or r['level'] in levels) and
              (not tasks or ('P' if r['qa_type'] == 'NA' else 'C') in tasks)]
    wanted = wanted[:limit] if limit else wanted
    if not wanted:
        raise ValueError('No questions selected. L1 contains only P; C is available in L2-L4.')
    return wanted


def media_files(rows):
    files = {}
    for r in rows:
        for key, hkey in [('history_video', 'history_sha256'), ('current_frame', 'current_sha256')]:
            rel, checksum = r[key], r[hkey]
            if not rel.startswith('data/') or not re.fullmatch(r'[a-f0-9]{64}', checksum):
                raise ValueError(f'invalid media entry for {r["question_id"]}')
            if rel in files and files[rel] != checksum:
                raise ValueError(f'conflicting checksum: {rel}')
            files[rel] = checksum
    return files


def verify(root, rows):
    files = media_files(rows)
    for rel, checksum in files.items():
        path = local_path(root, rel)
        if not path.is_file():
            raise ValueError(f'Missing {rel}. Run download with the same --levels/--tasks selection.')
        if sha(path) != checksum:
            raise ValueError(f'SHA-256 mismatch: {rel}. Run download again to repair it.')
    return len(files)


def atomic_json(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temp, path)


def download(root, repo_id=REPO_ID, revision=None, levels=None, tasks=None, limit=None, workers=4):
    from huggingface_hub import HfApi, hf_hub_download
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    receipt_path = root / 'download_receipt.json'
    previous = json.loads(receipt_path.read_text(encoding='utf-8')) if receipt_path.exists() else {}
    if previous and previous['repo_id'] != repo_id:
        raise ValueError('This directory belongs to another dataset; use a new --data-root.')
    # Incremental subset downloads keep the first resolved revision unless explicitly changed.
    requested = revision or previous.get('revision') or 'main'
    try:
        commit = HfApi().dataset_info(repo_id, revision=requested).sha
    except Exception as exc:
        raise ValueError(f'Cannot access {repo_id} at {requested}. Check that the dataset is published and the revision exists; private access requires hf auth login.') from exc
    if previous and previous['revision'] != commit:
        raise ValueError('Dataset revision changed. Use a new --data-root to avoid mixing releases.')
    def fetch(name, checksum=None):
        target = local_path(root, name)
        if checksum and target.is_file() and sha(target) == checksum:
            return target
        path = Path(hf_hub_download(repo_id, name, repo_type='dataset', revision=commit,
                                   local_dir=str(root), force_download=bool(target.exists())))
        if checksum and sha(path) != checksum:
            raise ValueError(f'download checksum mismatch: {name}')
        return path
    release = json.loads(fetch('release.json').read_text(encoding='utf-8'))
    if release.get('name') != 'EMBER-Bench':
        raise ValueError('release.json is not an EMBER-Bench release')
    catalog_path = fetch('catalog.json', release['files']['catalog.json']['sha256'])
    rows = json.loads(catalog_path.read_text(encoding='utf-8'))
    chosen = select(rows, levels, tasks, limit)
    files = media_files(chosen)
    for name in ('README.md', 'LICENSE', 'known_limitations.json', 'audit.json'):
        if name in release['files']:
            fetch(name, release['files'][name]['sha256'])
    for name, checksum in files.items():
        local_path(root, name)
        if release['files'].get(name, {}).get('sha256') != checksum:
            raise ValueError(f'catalog/release disagreement: {name}')
    total = sum(release['files'][name]['bytes'] for name in files)
    print(f'{repo_id}@{commit}: {len(chosen)} questions, {len(files)} media files, {total / 2**30:.2f} GiB', flush=True)
    # Pin the metadata immediately, so an interrupted download cannot silently change version.
    receipt = dict(repo_id=repo_id, revision=commit, release_sha256=sha(root / 'release.json'),
                   verified_question_ids=previous.get('verified_question_ids', []))
    atomic_json(receipt_path, receipt)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda pair: fetch(*pair), files.items()))
    verify(root, chosen)
    receipt['verified_question_ids'] = sorted(set(receipt['verified_question_ids']) | {r['question_id'] for r in chosen})
    atomic_json(receipt_path, receipt)
    print(f'Verified {len(chosen)} selected questions. Dataset: {root}')
    return receipt
