# Public CLI

New users should start with the [repository quick start](../QUICKSTART.md), which covers data download, scenario/type selection, and custom/local API setup. The commands below describe the lower-level runner.

# Quick start

Run these commands from the repository's `evaluation/` directory with Python 3.10+.

## No credentials or benchmark assets required

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/smoke.py --out runs/synthetic-smoke
```

Choose a new output directory for every separate smoke session. The server and keys are artificial and local. Results are not eligible as benchmark scores.

## Prepared benchmark catalog

Obtain the real prepared catalog and its media independently; these assets are not in this package. Relative media paths resolve against the catalog's directory. Verify the input before incurring provider charges:

```bash
python ember_eval.py --catalog /data/ember/catalog.json --models qwen3.8-flash --out runs/preflight --validate-catalog
```

On Bash:

```bash
export DASHSCOPE_API_KEY="your-key"
python ember_eval.py --catalog /data/ember/catalog.json --models qwen3.8-flash --out runs/main
```

On PowerShell:

```powershell
$env:DASHSCOPE_API_KEY = "your-key"
python ember_eval.py --catalog "D:\EMBER-Data\catalog.json" --models qwen3.8-flash --out runs/main
```

The other credential variables are `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ARK_API_KEY`, and `MIMO_API_KEY`. Set only those needed. The supplied registry's model IDs may need deployment-specific changes; use `--config custom-models.json` and its optional `api_model` field.

## Resume, inspect, and export

```bash
# Resume exactly the same run; completed valid answers are skipped.
python ember_eval.py --catalog /data/ember/catalog.json --models qwen3.8-flash --out runs/main

# Rebuild statistics without provider calls.
python ember_eval.py --catalog /data/ember/catalog.json --models qwen3.8-flash --out runs/main --summarize

python scripts/analyze_results.py runs/main/V1M0
python scripts/export_submission.py --run-dir runs/main/V1M0/qwen3.8-flash --output runs/qwen.candidate.json
```

The result directory is `runs/main/V1M0/qwen3.8-flash/`. Check `summary.json` for `run_status: "complete"`. Candidate export validates consistency and requests human review; it never publishes scores.

## Other inputs

```bash
# Current frame only; automatically selects P questions.
python ember_eval.py --catalog /data/ember/catalog.json --models qwen3.8-flash --condition V0M0 --out runs/current-frame

# Matched P subset; do not substitute all L2-L4 P items.
python ember_eval.py --catalog /data/ember/catalog.json --models qwen3.8-flash --condition CoT --questions paired_prediction_ids.txt --out runs/cot

# Map a legacy media-root prefix. Quotes protect spaces on both shells.
python ember_eval.py --catalog /data/ember/catalog.json --models qwen3.8-flash --path-map "/server/EMBER=D:/EMBER-Data" --out runs/mapped
```

See [usage](docs/USAGE.md), [catalog boundaries](docs/CATALOG.md), and [paper compatibility limits](README.md#paper-protocol-and-compatibility-limits) before interpreting scores.
