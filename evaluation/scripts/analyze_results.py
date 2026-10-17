#!/usr/bin/env python3
"""Print per-model metrics from an OUT/CONDITION directory."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results_dir', type=Path)
    args = parser.parse_args()
    paths = sorted(args.results_dir.glob('*/summary.json'))
    if not paths:
        parser.error('no model summary.json files found; pass OUT/CONDITION')
    keys = ('overall', 'P', 'C', 'P_L1', 'P_L2', 'P_L3', 'P_L4', 'C_L2', 'C_L3', 'C_L4')
    print(f'{"Model":<28}{"Status":>12}{"N":>7}{"No answer":>11}{"Pending":>9}' + ''.join(f'{key:>8}' for key in keys))
    for path in paths:
        summary = json.loads(path.read_text(encoding='utf-8'))
        print(f'{summary["model"]:<28}{summary.get("run_status", "unknown"):>12}{summary["n"]:>7}'
              f'{summary["unanswered"]:>11}{str(summary.get("incomplete_questions", "?")):>9}' +
              ''.join(f'{summary[key]:8.1f}' if summary[key] is not None else f'{"N/A":>8}' for key in keys))
        manifest = path.with_name('manifest.json')
        if manifest.exists() and json.loads(manifest.read_text(encoding='utf-8'))['identity'].get('synthetic'):
            print('  MOCK TEST - not a benchmark score')
        if summary.get('run_status') != 'complete':
            print('  INCOMPLETE RUN - resume before reporting a final score.')


if __name__ == '__main__':
    main()
