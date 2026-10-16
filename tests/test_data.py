import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ember_bench import data


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rows = []
        self.remote = {}
        for i, (level, task) in enumerate([('L1', 'NA'), ('L2', 'NA'), ('L2', 'CB'), ('L4', 'CB')]):
            row = dict(question_id=f'q{i}', level=level, qa_type=task)
            for key, hkey, suffix in [('history_video', 'history_sha256', 'mp4'), ('current_frame', 'current_sha256', 'jpg')]:
                name = f'data/{i}.{suffix}'
                payload = f'test-{name}'.encode()
                self.remote[name] = payload
                row[key], row[hkey] = name, hashlib.sha256(payload).hexdigest()
            self.rows.append(row)
        self.remote['catalog.json'] = json.dumps(self.rows).encode()
        files = {k: dict(sha256=hashlib.sha256(v).hexdigest(), bytes=len(v)) for k, v in self.remote.items()}
        self.remote['release.json'] = json.dumps(dict(name='EMBER-Bench', files=files)).encode()
        self.calls = []
        self.commit = 'a' * 40

    def fake_fetch(self, repo_id, name, **kwargs):
        self.assertEqual(kwargs['repo_type'], 'dataset')
        self.assertEqual(kwargs['revision'], self.commit)
        self.calls.append(name)
        path = Path(kwargs['local_dir']) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.remote[name])
        return str(path)

    def hub(self):
        return SimpleNamespace(HfApi=lambda: SimpleNamespace(dataset_info=lambda *a, **k: SimpleNamespace(sha=self.commit)),
                               hf_hub_download=self.fake_fetch)

    def test_subset_download_resume_and_repair(self):
        with patch.dict('sys.modules', {'huggingface_hub': self.hub()}):
            data.download(self.root, levels=['L2'], tasks=['C'])
            self.assertEqual(set(self.calls), {'release.json', 'catalog.json', 'data/2.mp4', 'data/2.jpg'})
            (self.root / 'data/2.mp4').write_bytes(b'corrupt')
            self.calls.clear()
            data.download(self.root, levels=['L2'], tasks=['C'])
            self.assertIn('data/2.mp4', self.calls)
            self.assertNotIn('data/2.jpg', self.calls)
            self.assertEqual(data.verify(self.root, [self.rows[2]]), 2)
            receipt = json.loads((self.root / 'download_receipt.json').read_text())
            self.assertEqual(receipt['verified_question_ids'], ['q2'])
            self.assertEqual(receipt['revision'], 'a' * 40)

    def test_version_mix_is_rejected(self):
        with patch.dict('sys.modules', {'huggingface_hub': self.hub()}):
            data.download(self.root, limit=1)
            self.commit = 'b' * 40
            with self.assertRaisesRegex(ValueError, 'revision changed'):
                data.download(self.root, revision='new')

    def test_download_does_not_accept_wrong_bytes(self):
        self.remote['data/0.mp4'] = b'corrupt server content'
        with patch.dict('sys.modules', {'huggingface_hub': self.hub()}):
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                data.download(self.root, limit=1)

    def test_path_escape_and_originals_rejected(self):
        for path in ['../x', '/x', 'C:/x', 'data\\x', 'data/x_not_blur.mp4']:
            with self.assertRaises(ValueError):
                data.local_path(self.root, path)

    def test_subsets_and_empty_l1_c(self):
        self.assertEqual([r['question_id'] for r in data.select(self.rows, ['L2'], ['C'])], ['q2'])
        self.assertEqual(len(data.select(self.rows)), 4)
        with self.assertRaisesRegex(ValueError, 'L1 contains only P'):
            data.select(self.rows, ['L1'], ['C'])
        with self.assertRaises(ValueError):
            data.select(self.rows, limit=0)


if __name__ == '__main__':
    unittest.main()
