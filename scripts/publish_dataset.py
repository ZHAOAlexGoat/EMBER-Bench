"""Upload a verified release, verify remote objects, then optionally publish it.

Requires `hf auth login`. The first upload creates a private repository. No
backups or files outside release.json's allowlist are uploaded.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ember_bench.data import REPO_ID, local_path, sha, atomic_json


def publish(folder, repo_id, make_public):
    from huggingface_hub import HfApi, RepoFile, hf_hub_download
    folder = folder.resolve()
    api = HfApi()
    identity = api.whoami()
    if identity['name'] != repo_id.split('/')[0]:
        raise ValueError(f'Log in as dataset owner {repo_id.split("/")[0]}; current account is {identity["name"]}')
    release = json.loads((folder / 'release.json').read_text(encoding='utf-8'))
    audit = json.loads((folder / 'audit.json').read_text(encoding='utf-8'))
    if release['license'] != 'cc-by-nc-4.0' or release['questions'] != 699:
        raise ValueError('unexpected release scope/license')
    if audit['summary']['status'] != 'PASS' or audit['summary']['videos'] != 699 or audit['visual_review']['status'] != 'PASS':
        raise ValueError('media audit is incomplete')
    allowed = set(release['files']) | {'release.json'}
    for name in allowed:
        path = local_path(folder, name)
        if '/source/' in name:
            raise ValueError('raw source files are not part of the evaluation release')
        if name in release['files']:
            meta = release['files'][name]
            if path.stat().st_size != meta['bytes'] or sha(path) != meta['sha256']:
                raise ValueError(f'local release changed: {name}')
    print(f'Validated {len(allowed)} release files for {repo_id}.', flush=True)
    api.create_repo(repo_id, repo_type='dataset', private=True, exist_ok=True)
    existing = set(api.list_repo_files(repo_id, repo_type='dataset')) - {'.gitattributes'}
    if existing - allowed:
        raise ValueError('remote repository contains unrelated files; refusing to mix releases')
    head = api.dataset_info(repo_id).sha
    commit = api.upload_folder(repo_id=repo_id, repo_type='dataset', folder_path=folder,
                              allow_patterns=sorted(allowed), parent_commit=head,
                              commit_message='Release checked EMBER-Bench evaluation data (2026.10.17)')
    revision = commit.oid
    remote = {f.path: f for f in api.list_repo_tree(repo_id, repo_type='dataset', revision=revision, recursive=True) if isinstance(f, RepoFile)}
    if set(remote) - {'.gitattributes'} != allowed:
        raise ValueError('remote file inventory differs from release allowlist')
    for name in allowed:
        path, obj = folder / name, remote[name]
        if obj.size != path.stat().st_size:
            raise ValueError(f'remote size mismatch: {name}')
        if obj.lfs:
            if obj.lfs.sha256 != sha(path):
                raise ValueError(f'remote LFS SHA-256 mismatch: {name}')
        else:
            blob = path.read_bytes()
            git_hash = hashlib.sha1(f'blob {len(blob)}\0'.encode() + blob).hexdigest()
            if obj.blob_id != git_hash:
                raise ValueError(f'remote Git object mismatch: {name}')
    # Read back metadata through the public download API at the exact commit.
    remote_release = hf_hub_download(repo_id, 'release.json', repo_type='dataset', revision=revision, force_download=True)
    if sha(remote_release) != sha(folder / 'release.json'):
        raise ValueError('downloaded release manifest differs')
    if make_public:
        api.update_repo_settings(repo_id, repo_type='dataset', private=False)
    receipt = dict(repo_id=repo_id, revision=revision, public=not api.dataset_info(repo_id).private,
                   remote_files_verified=len(allowed), release_sha256=sha(folder / 'release.json'))
    atomic_json(folder.parent / 'hf_publish_receipt.json', receipt)
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--folder', type=Path, required=True)
    p.add_argument('--repo-id', default=REPO_ID)
    p.add_argument('--publish', action='store_true', help='make the verified repository public')
    args = p.parse_args()
    publish(args.folder, args.repo_id, args.publish)
