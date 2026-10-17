"""Behavior tests: safe inputs, protocol isolation, scoring, resume and export."""
import argparse
import contextlib
import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import ember_eval as ev
from scripts.export_submission import validate_run


class EvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.catalog_path = HERE / 'fixtures' / 'synthetic' / 'catalog.json'
        self.args = argparse.Namespace(catalog=str(self.catalog_path), condition='V1M0', path_map=[],
                                       questions=None, limit=None, verify_sha=True, summarize=False,
                                       out=str(self.root / 'runs'), workers=1, min_interval=0)
        self.catalog = ev.load_catalog(self.args)
        self.model = next(iter(ev.CFG['models']))
        self.out = Path(self.args.out) / 'V1M0' / self.model

    def tearDown(self):
        ev.STATE.update(next_post=0, cooldown=0)
        self.tmp.cleanup()

    def custom_catalog(self, rows):
        # Preserve fixture paths when moving catalog into the temporary directory.
        rows = copy.deepcopy(rows)
        for row in rows:
            for key in ('current_frame', 'history_video'):
                if key in row:
                    row[key] = str((self.catalog_path.parent / row[key]).resolve())
        path = self.root / 'catalog.json'
        path.write_text(json.dumps(rows), encoding='utf-8')
        self.args.catalog = str(path)
        return path

    def attempt(self, item, pred='A', stage=1, tries=1, error='', status=200):
        return dict(model=self.model, condition='V1M0', question_id=item['question_id'],
                    level=item['level'], qa_type=item['qa_type'], gold=item['gold'], stage=stage,
                    tries=tries, fps=ev.DEF['fps_ladder'][stage - 1], http_status=status,
                    raw_text=f'Final Answer: [{pred}]' if pred else '', finish_reason='stop',
                    prediction=pred if not error else '', valid_answer=bool(pred and not error),
                    api_error=error, prompt_sha256=ev.hashlib.sha256(ev.prompt(item, 'V1M0').encode()).hexdigest())

    def initialize(self, rows, catalog=None):
        catalog = catalog or self.catalog[:1]
        self.out.mkdir(parents=True)
        ev.ensure_manifest(self.model, catalog, self.out, self.args)
        (self.out / 'attempts.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()):
            ev.summarize_model(self.model, catalog, self.out, 'V1M0')

    def test_safe_legacy_options(self):
        self.assertEqual(ev.options({'options': "['a', 'b', 'c', 'd']"}), ['a', 'b', 'c', 'd'])

    def test_image_mime_uses_bytes_not_filename(self):
        misleading = self.root / 'frame.jpg'
        misleading.write_bytes(b'\x89PNG\r\n\x1a\n' + b'xxxx')
        self.assertEqual(ev.image_mime(misleading), 'image/png')
        misleading.write_bytes(b'RIFF0000WEBP')
        self.assertEqual(ev.image_mime(misleading), 'image/webp')
        misleading.write_bytes(b'not an image')
        with self.assertRaises(ValueError):
            ev.image_mime(misleading)

    def test_options_never_execute_expression(self):
        sentinel = self.root / 'executed'
        expression = f"__import__('pathlib').Path({str(sentinel)!r}).touch() or ['a','b','c','d']"
        with self.assertRaises(ValueError):
            ev.options({'options': expression})
        self.assertFalse(sentinel.exists())

    def test_four_options_required(self):
        for invalid in (['a'], {'A': 'a'}, ['a', 'b', 'c', 4], ['a', 'b', 'c', '']):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                ev.options({'options': invalid})

    def test_answer_parser_rejects_conflicting_final_answers(self):
        self.assertEqual(ev.parse_answer('Final Answer: A\nFinal Answer: B'), '')
        self.assertEqual(ev.parse_answer('Final Answer: [c]'), 'C')
        self.assertEqual(ev.parse_answer('B. Synthetic action B', self.catalog[0]), 'B')
        self.assertEqual(ev.parse_answer('B. invented answer text', self.catalog[0]), '')

    def test_answer_parser_rejects_echoed_template_and_multichoice(self):
        for raw in ('Final Answer: [A/B/C/D]', 'Final Answer: [A, B]', 'Final Answer: A or B',
                    'Final Answer: A/B', 'Final Answer: [A', 'Final Answer: A\nFinal Answer: [A/B/C/D]'):
            with self.subTest(raw=raw):
                self.assertEqual(ev.parse_answer(raw), '')
        self.assertEqual(ev.parse_answer('Final Answer: **A**'), 'A')
        self.assertEqual(ev.parse_answer('Assessment: synthetic.\nFinal Answer: A.'), 'A')

    def test_cot_excludes_action_log_and_annotations(self):
        item = {**self.catalog[0], 'm3_text': 'PRIVATE_ACTION_LOG_MARKER',
                'incidents': [{'subtask': 18, 'action': 'moved', 'accident_cause': 'PRIVATE_CAUSE_MARKER'}]}
        for condition in ('V1M0', 'V0M0', 'CoT'):
            text = ev.prompt(item, condition)
            self.assertNotIn('PRIVATE_ACTION_LOG_MARKER', text)
            self.assertNotIn('PRIVATE_CAUSE_MARKER', text)
        self.assertIn('PRIVATE_ACTION_LOG_MARKER', ev.prompt(item, 'V1M3'))
        self.assertNotIn('PRIVATE_CAUSE_MARKER', ev.prompt(item, 'V1M3'))
        self.assertIn('PRIVATE_CAUSE_MARKER', ev.prompt(item, 'V1M3C'))

    def test_cb_video_only_prompt_has_no_annotation_text(self):
        item = {**self.catalog[2], 'option_labels': {'A': 'LEAKED_LABEL'}, 'm3_text': 'LEAKED_LOG'}
        self.assertNotIn('LEAKED', ev.prompt(item, 'V1M0'))

    def test_catalog_duplicate_ids_rejected(self):
        self.custom_catalog([self.catalog[0], self.catalog[0]])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            ev.load_catalog(self.args)

    def test_catalog_sha_mismatch_fails_before_transport(self):
        rows = copy.deepcopy(self.catalog)
        rows[0]['current_sha256'] = '0' * 64
        self.custom_catalog(rows)
        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            ev.load_catalog(self.args)

    def test_memory_subset_does_not_guess_from_level(self):
        rows = copy.deepcopy(self.catalog)
        for row in rows:
            row.pop('is_paired', None)
        self.custom_catalog(rows)
        self.args.condition = 'CoT'
        with self.assertRaisesRegex(ValueError, 'matched NA ids'):
            ev.load_catalog(self.args)

    def test_unknown_question_list_rejected(self):
        path = self.root / 'questions.txt'
        path.write_text('unknown-id', encoding='utf-8')
        self.args.questions = str(path)
        with self.assertRaisesRegex(ValueError, 'unknown ids'):
            ev.load_catalog(self.args)

    def test_v0m0_needs_no_history_media(self):
        row = copy.deepcopy(self.catalog[0])
        del row['history_video']
        del row['history_sha256']
        self.custom_catalog([row])
        self.args.condition = 'V0M0'
        self.assertEqual(len(ev.load_catalog(self.args)), 1)

    def test_annotation_subtask_integer_is_compatible(self):
        row = copy.deepcopy(self.catalog[1])
        row['incidents'] = [{'subtask': 18, 'action': 'move', 'accident_cause': 'synthetic'}]
        self.custom_catalog([row])
        self.args.condition = 'V1M3C'
        self.assertEqual(ev.load_catalog(self.args)[0]['incidents'][0]['subtask'], 18)

    def test_unsafe_model_output_path_rejected(self):
        cfg = copy.deepcopy(ev.CFG)
        cfg['models']['../escape'] = next(iter(cfg['models'].values()))
        with self.assertRaisesRegex(ValueError, 'unsafe model id'):
            ev.validate_config(cfg)

    def test_plaintext_remote_endpoint_rejected(self):
        ep = copy.deepcopy(next(iter(ev.CFG['endpoints'].values())))
        ep['base_url'] = 'http://remote.example/v1'
        ep.pop('base_url_env', None)
        with self.assertRaisesRegex(ValueError, 'HTTPS'):
            ev.endpoint_url(ep)

    def test_first_valid_answer_kept_even_when_wrong(self):
        item = self.catalog[0]
        self.initialize([self.attempt(item, 'B'), self.attempt(item, 'A', tries=2)])
        candidate = validate_run(self.out)
        self.assertEqual(candidate['accuracy']['overall'], 0.0)
        self.assertEqual(ev.load(self.out / 'selected.jsonl')[0]['prediction'], 'B')

    def test_unanswered_is_wrong_and_counts_remain(self):
        item = self.catalog[0]
        self.initialize([self.attempt(item, '', error='empty_response')])
        candidate = validate_run(self.out)
        self.assertEqual(candidate['unanswered'], 1)
        self.assertEqual(candidate['accuracy']['overall'], 0.0)
        self.assertEqual(candidate['counts']['total'], 1)
        self.assertEqual(candidate['run_status'], 'incomplete')

    def test_exhausted_retries_complete_unanswered_question(self):
        item = self.catalog[0]
        self.initialize([self.attempt(item, '', stage=stage, error='empty_response') for stage in (1, 2, 3)])
        candidate = validate_run(self.out)
        self.assertEqual(candidate['run_status'], 'complete')
        self.assertEqual(candidate['unanswered'], 1)

    def test_resume_reports_exhausted_questions_as_done(self):
        item = self.catalog[0]
        self.initialize([self.attempt(item, '', stage=stage, error='empty_response') for stage in (1, 2, 3)])
        output = io.StringIO()
        with patch.object(ev, 'attempt') as transport, contextlib.redirect_stdout(output):
            self.assertTrue(ev.run_model(self.model, [item], self.args))
        transport.assert_not_called()
        self.assertIn('1 done, 0 to run', output.getvalue())
        self.assertIn('Unanswered: 1 | Pending: 0', output.getvalue())

    def test_terminal_summary_matches_artifacts_and_flags_incomplete(self):
        self.initialize([self.attempt(self.catalog[0], '', error='empty_response')])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            summary = ev.summarize_model(self.model, self.catalog[:1], self.out, 'V1M0')
        text = output.getvalue()
        self.assertIn('Status: INCOMPLETE | Questions: 1 | Valid answers: 0 | Unanswered: 1 | Pending: 1', text)
        self.assertIn('INCOMPLETE RUN', text)
        self.assertIn('N/A', text)
        self.assertIn(str((self.out / 'summary.json').resolve()), text)
        self.assertEqual(summary, json.loads((self.out / 'summary.json').read_text()))

    def test_summarize_missing_run_fails_visibly(self):
        result = subprocess.run([sys.executable, str(HERE / 'ember_eval.py'), '--catalog', str(self.catalog_path),
                                 '--out', str(self.root / 'missing'), '--models', self.model, '--summarize'],
                                capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no attempts.jsonl', result.stderr)

    def test_changed_subset_cannot_resume(self):
        self.initialize([self.attempt(self.catalog[0])])
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            ev.ensure_manifest(self.model, self.catalog[:2], self.out, self.args)

    def test_mixed_condition_journal_rejected(self):
        row = self.attempt(self.catalog[0])
        row['condition'] = 'CoT'
        with self.assertRaisesRegex(ValueError, 'condition'):
            ev.validate_attempts([row], self.model, self.catalog[:1], 'V1M0')

    def test_forged_valid_flag_rejected(self):
        row = self.attempt(self.catalog[0])
        row['raw_text'] = 'unparseable'
        with self.assertRaisesRegex(ValueError, 'validity'):
            ev.validate_attempts([row], self.model, self.catalog[:1], 'V1M0')

    def test_fatal_authorization_failure_resumes_after_fix(self):
        item = self.catalog[0]
        fatal = self.attempt(item, '', error='HTTP 401', status=401)
        success = self.attempt(item)
        with patch.object(ev, 'attempt', side_effect=[fatal, success]) as mock, contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(ev.run_model(self.model, [item], self.args))
            self.assertTrue(ev.run_model(self.model, [item], self.args))
        self.assertEqual(mock.call_count, 2)
        self.assertEqual(validate_run(self.out)['accuracy']['overall'], 100.0)

    def test_export_rejects_changed_selected_artifact(self):
        self.initialize([self.attempt(self.catalog[0])])
        with (self.out / 'selected.jsonl').open('a', encoding='utf-8') as stream:
            stream.write('{}\n')
        with self.assertRaisesRegex(ValueError, 'changed since summary'):
            validate_run(self.out)

    def test_export_recomputes_metrics(self):
        self.initialize([self.attempt(self.catalog[0])])
        path = self.out / 'summary.json'
        summary = json.loads(path.read_text())
        summary['overall'] = 10.0
        path.write_text(json.dumps(summary), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'accuracies disagree'):
            validate_run(self.out)

    def test_secret_redacted_recursively(self):
        key_env = next(iter(ev.CFG['endpoints'].values()))['key_env']
        with patch.dict(os.environ, {key_env: 'TEST_SECRET_MARKER'}):
            self.assertEqual(ev.redact_tree({'raw_text': 'TEST_SECRET_MARKER', 'usage': ['TEST_SECRET_MARKER']}),
                             {'raw_text': '[REDACTED]', 'usage': ['[REDACTED]']})

    def test_real_offline_pipeline_all_transports(self):
        completed = subprocess.run([sys.executable, str(HERE / 'scripts' / 'smoke.py'), '--out', str(self.root / 'smoke')],
                                   text=True, capture_output=True, timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn('OFFLINE SMOKE OK', completed.stdout)
        candidate = json.loads((self.root / 'smoke' / 'mock-responses.candidate.json').read_text())
        self.assertTrue(candidate['synthetic'])
        self.assertEqual(candidate['review_status'], 'review-required')


if __name__ == '__main__':
    unittest.main()
