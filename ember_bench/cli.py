"""User-facing download, configuration, validation, and evaluation commands."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys

from . import data


def selection_options(parser):
    parser.add_argument('--data-root', type=Path, default=Path('data/EMBER-Bench'))
    parser.add_argument('--levels', nargs='+', choices=['L1', 'L2', 'L3', 'L4'])
    parser.add_argument('--tasks', nargs='+', choices=['P', 'C'])
    parser.add_argument('--limit', type=int)


def run_evaluator(arguments):
    return subprocess.call([sys.executable, '-m', 'evaluation.ember_eval', *map(str, arguments)])


def subset_flags(args):
    flags = []
    for name in ('levels', 'tasks'):
        if getattr(args, name, None):
            flags += ['--' + name, *getattr(args, name)]
    if args.limit is not None:
        flags += ['--limit', str(args.limit)]
    return flags


def main(argv=None):
    p = argparse.ArgumentParser(description='EMBER-Bench: download data, test an API, and evaluate a model.')
    sub = p.add_subparsers(dest='command', required=True)
    d = sub.add_parser('download', help='download only selected evaluation media; resume and verify checksums')
    selection_options(d)
    d.add_argument('--repo-id', default=data.REPO_ID)
    d.add_argument('--revision', help='HF commit/tag; subsequent downloads keep the initially resolved commit')
    d.add_argument('--workers', type=int, default=4)
    v = sub.add_parser('validate', help='validate selected local paths, schema, and SHA-256 without API calls')
    selection_options(v)
    v.add_argument('--decode', action='store_true', help='also fully decode all videos in the local catalog (requires FFprobe)')
    v.add_argument('--ffprobe', default='ffprobe')
    i = sub.add_parser('init', help='create a model config; credentials remain in environment variables')
    i.add_argument('--api-base', required=True, help='base URL, e.g. http://localhost:8000/v1')
    i.add_argument('--model', required=True, help='provider deployment/model name, including slashes if needed')
    i.add_argument('--protocol', choices=['chat', 'responses', 'gemini'], default='chat')
    i.add_argument('--input-mode', choices=['frames', 'video'], default='frames', help='chat: JPEG frame list or native video_url')
    i.add_argument('--key-env', default='EMBER_API_KEY')
    i.add_argument('--out', type=Path, default=Path('model.local.json'))
    t = sub.add_parser('api-test', help='free local API mock; --live tests your configured service on one tiny synthetic clip')
    t.add_argument('--live', action='store_true')
    t.add_argument('--config', type=Path, default=Path('model.local.json'))
    t.add_argument('--model', default='custom', help='config model id (not deployment name)')
    t.add_argument('--out', type=Path)
    e = sub.add_parser('evaluate', help='evaluate a selected subset or all questions; rerun the same command to resume')
    selection_options(e)
    e.add_argument('--config', type=Path, default=Path('model.local.json'))
    e.add_argument('--models', nargs='+', default=['custom'], help='config ids; explicit all is supported')
    e.add_argument('--out', type=Path, default=Path('runs/custom'))
    e.add_argument('--condition', choices=['V1M0', 'V0M0', 'V1M3', 'V1M3C', 'V1M3CC', 'CoT'], default='V1M0')
    e.add_argument('--workers', type=int, default=2)
    e.add_argument('--min-interval', type=float, default=0)
    e.add_argument('--questions', type=Path)
    e.add_argument('--max-output-tokens', type=int)
    e.add_argument('--fps-ladder', nargs='+', type=int)
    e.add_argument('--summarize', action='store_true')
    args = p.parse_args(argv)
    try:
        if args.command == 'download':
            if not 1 <= args.workers <= 32:
                raise ValueError('--workers must be 1-32')
            data.download(args.data_root, args.repo_id, args.revision, args.levels, args.tasks, args.limit, args.workers)
        elif args.command == 'init':
            from evaluation.ember_eval import validate_config
            ep = dict(protocol=args.protocol, base_url=args.api_base, key_env=args.key_env)
            if args.protocol == 'chat':
                ep['input_mode'] = args.input_mode
                if args.input_mode == 'video':
                    ep['video_fps_field'] = 'part'
            if args.protocol == 'responses' or ep.get('input_mode') == 'frames':
                ep['max_images'] = 1500
            cfg = dict(defaults=dict(temperature=0, max_output_tokens=512, fps_ladder=[5, 3, 1], timeout_s=900),
                       endpoints={'custom': ep}, models={'custom': dict(name=args.model, api_model=args.model, endpoint='custom')})
            validate_config(cfg)
            # Avoid silently replacing a user's model config.
            with args.out.open('x', encoding='utf-8') as f:
                json.dump(cfg, f, indent=2)
                f.write('\n')
            print(f'Created {args.out}. Set {args.key_env} in your shell; use a dummy value for a local unauthenticated server.')
        elif args.command == 'api-test':
            out = (args.out or Path('runs') / ('api-test-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))).resolve()
            if not args.live:
                from evaluation.scripts.smoke import smoke
                smoke(out)
            else:
                from evaluation.scripts.make_synthetic_fixture import make_fixture
                if out.exists() and any(out.iterdir()):
                    raise ValueError('API test requires a new output directory')
                out.mkdir(parents=True, exist_ok=True)
                cfg = json.loads(args.config.read_text(encoding='utf-8-sig'))
                cfg['_synthetic'] = True
                cfg['defaults'].update(max_output_tokens=128, fps_ladder=[1])
                config = out / 'test_config.json'
                data.atomic_json(config, cfg)
                catalog = make_fixture(out / '_inputs')
                print('Sending one tiny synthetic video/image request to your configured API; provider charges may apply.')
                result = run_evaluator(['--catalog', catalog, '--config', config, '--models', args.model,
                                        '--out', out, '--limit', '1', '--workers', '1'])
                if result:
                    raise SystemExit(result)
                attempts = out / 'V1M0' / args.model / 'attempts.jsonl'
                if not any(json.loads(line).get('valid_answer') for line in attempts.read_text(encoding='utf-8').splitlines()):
                    raise ValueError(f'API test returned no valid answer. Inspect {attempts}')
                print('Live API test passed. This is synthetic connectivity evidence, not a benchmark score.')
        elif args.command == 'validate':
            result = run_evaluator(['--catalog', args.data_root / 'catalog.json', '--out', 'runs/validation',
                                    '--validate-catalog', *subset_flags(args)])
            if result:
                raise SystemExit(result)
            if args.decode:
                if args.levels or args.tasks or args.limit:
                    raise ValueError('--decode checks the whole local catalog; omit subset flags and download the full dataset first')
                raise SystemExit(subprocess.call([sys.executable, '-m', 'evaluation.scripts.audit_dataset',
                                                   '--root', str(args.data_root), '--out', 'runs/media-audit',
                                                   '--ffprobe', args.ffprobe]))
        else:
            flags = ['--catalog', args.data_root / 'catalog.json', '--config', args.config,
                     '--models', *args.models, '--out', args.out, '--condition', args.condition,
                     '--workers', args.workers, '--min-interval', args.min_interval, *subset_flags(args)]
            for name in ('questions', 'max_output_tokens'):
                if getattr(args, name) is not None:
                    flags += ['--' + name.replace('_', '-'), getattr(args, name)]
            if args.fps_ladder:
                flags += ['--fps-ladder', *args.fps_ladder]
            if args.summarize:
                flags += ['--summarize']
            raise SystemExit(run_evaluator(flags))
    except (ValueError, OSError) as exc:
        p.error(str(exc))


if __name__ == '__main__':
    main()
