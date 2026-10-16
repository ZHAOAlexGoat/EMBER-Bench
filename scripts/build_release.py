"""Build the public evaluation-only dataset from the checked portable archive.

This reads the canonical media index and question banks, never the legacy runner
catalog or absolute paths embedded in original annotation exports.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def timeline(path, decision):
    objectives, events = set(), []
    for task in json.loads(path.read_text(encoding='utf-8')):
        for annotation in task['annotations']:
            for result in annotation['result']:
                value = result.get('value', {})
                if result['type'] == 'textarea':
                    for text in value.get('text', []):
                        match = re.search(r'overall_objective\s*[:：]\s*(.+)', text, re.I)
                        if match:
                            objectives.add(match[1].strip())
                if result['type'] != 'timelinelabels':
                    continue
                text = '\n'.join(result.get('meta', {}).get('text', []))
                match = re.search(r'subtask\s*\{(\d+)\}\s*[:：]\s*([^\n]+)', text, re.I)
                if not match:
                    continue
                ranges = value.get('ranges', [])
                if not ranges or max(v['end'] for v in ranges) > decision:
                    continue
                fields = dict(re.findall(r'^([a-z_]+)\s*[:：]\s*(.*)$', text, re.M))
                events.append(dict(subtask=int(match[1]), action=match[2].strip(),
                                   start_frame=min(v['start'] for v in ranges),
                                   end_frame=max(v['end'] for v in ranges), fields=fields))
    if len(objectives) != 1:
        raise ValueError(f'{path.name}: expected one overall_objective, found {objectives}')
    events.sort(key=lambda e: (e['end_frame'], e['start_frame'], e['subtask']))
    # Some exports repeat identical annotation records.
    events = list({json.dumps(e, sort_keys=True): e for e in events}.values())
    incidents = []
    for e in events:
        fields = e['fields']
        causes = {k: fields.get(k, '') for k in ('accident_cause', 'accident_consequence')}
        causes = {k: v for k, v in causes.items() if v.strip().lower() not in ('', 'false', 'none', '0')}
        if causes:
            incidents.append(dict(subtask=e['subtask'], action=e['action'], **causes))
    log = ('Completed action log (source-frame ranges; end_frame <= decision_frame).\n'
           'Anomaly stage, obligation, cause, and consequence fields are omitted.\n')
    log += '\n'.join(f"[{e['start_frame']}-{e['end_frame']}] subtask {e['subtask']}: {e['action']}" for e in events)
    return objectives.pop(), log, len(events), incidents


def build(source, output):
    source, output = source.resolve(), output.resolve()
    index = json.loads((source / 'evaluation/media_index.json').read_text(encoding='utf-8'))
    if len(index) != 699 or len({r['question_id'] for r in index}) != 699:
        raise ValueError('expected the checked 699-question release')
    banks, rows, files = {}, [], {}
    for entry in index:
        bank = entry['bank_path']
        if bank not in banks:
            banks[bank] = {r['question_id']: r for r in json.loads((source / bank).read_text(encoding='utf-8'))}
        q = banks[bank][entry['question_id']]
        assert q['decision_frame'] == entry['decision_frame']
        source_video = Path(entry['source_video'])
        timeline_path = source_video.parent.parent / 'timelines' / (source_video.stem + '.json')
        objective, log, n_events, incidents = timeline(source / timeline_path, entry['decision_frame'])
        row = {k: entry[k] for k in ('question_id', 'level', 'qa_type', 'decision_frame',
                                     'history_video', 'current_frame', 'history_sha256', 'current_sha256')}
        row.update(task_type='P' if entry['qa_type'] == 'NA' else 'C',
                   task_id=f"{entry['level']}_{source_video.stem}", objective=objective,
                   gold=q['correct_answer_option'], question=q.get('question') or q.get('question_en'),
                   m3_text=log, m3_n_events=n_events, incidents=incidents,
                   known_action='', paired_id='', is_paired=False, option_labels={})
        if row['task_type'] == 'P':
            row['options'] = q['options']
            assert len(row['options']) == 4 and all(isinstance(v, str) for v in row['options'])
        else:
            row['known_action'] = q.get('known_action') or q['known_action_en']
            row['paired_id'] = q['paired_next_action_question_id']
            row['options'] = [f'The event shown while OPTION {letter} appears in the history video.' for letter in 'ABCD']
            row['option_labels'] = {v['letter']: v['source_action'] for v in q.get('candidate_segments', [])}
        assert row['gold'] in 'ABCD' and row['question'] and row['objective']
        rows.append(row)
        for key, hashkey in [('history_video', 'history_sha256'), ('current_frame', 'current_sha256')]:
            rel = entry[key]
            src = (source / rel).resolve()
            if not src.is_relative_to(source) or '_not_blur' in rel or not src.is_file():
                raise ValueError(f'unsafe/missing evaluation media: {rel}')
            actual = sha(src)
            if actual != entry[hashkey]:
                raise ValueError(f'index checksum mismatch: {rel}')
            dst = output / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists() or sha(dst) != actual:
                shutil.copyfile(src, dst)
            assert sha(dst) == actual
            files[rel] = dict(sha256=actual, bytes=src.stat().st_size)
    by_id = {r['question_id']: r for r in rows}
    for row in rows:
        if row['task_type'] == 'C':
            paired = by_id[row['paired_id']]
            assert paired['task_type'] == 'P' and not paired['is_paired']
            assert (paired['task_id'], paired['decision_frame']) == (row['task_id'], row['decision_frame'])
            assert row['known_action'] == paired['options']['ABCD'.index(paired['gold'])]
            paired['is_paired'] = True
            paired['paired_id'] = row['question_id']
            row['is_paired'] = True
    counts = Counter(f"{r['level']}-{r['task_type']}" for r in rows)
    assert counts == {'L1-P': 205, 'L2-P': 113, 'L2-C': 58, 'L3-P': 128, 'L3-C': 60, 'L4-P': 102, 'L4-C': 33}
    write(output / 'catalog.json', rows)
    # JSON Lines is the portable annotation interchange format; media paths stay relative.
    (output / 'annotations.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
    (output / 'metadata.jsonl').write_text(''.join(json.dumps(dict(file_name=r['history_video'], **r), ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
    for name in ('catalog.json', 'annotations.jsonl', 'metadata.jsonl'):
        files[name] = dict(sha256=sha(output / name), bytes=(output / name).stat().st_size)
    release = dict(name='EMBER-Bench', version='2026.10.17', source_release='v20260922_final',
                   license='cc-by-nc-4.0', questions=len(rows), counts=dict(sorted(counts.items())),
                   paired_decisions=151, files=files,
                   source_question_bank_sha256={p: sha(source / p) for p in banks},
                   action_log_policy='Only canonical-timeline events ending at or before the decision frame; privileged fields only in incidents, not m3_text.',
                   exclusions=['raw source videos', 'unblurred backups', 'private absolute paths', 'annotation-tool user identities'])
    write(output / 'release.json', release)
    print(json.dumps(dict(questions=len(rows), counts=release['counts'], media_files=len(files)-3,
                          media_bytes=sum(v['bytes'] for k,v in files.items() if k.startswith('data/'))), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    build(args.source, args.out)
