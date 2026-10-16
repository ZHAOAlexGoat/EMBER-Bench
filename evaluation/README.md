# EMBER-Bench evaluation

For the simplest clone → download → API test → evaluation workflow, use the repository's [public CLI quick start](../QUICKSTART.md). It supports L1–L4 and P/C subsets, custom deployments, and local compatible model servers.

This package provides an audited **unified evaluation runner** for next-action prediction (`NA`, paper **P**) and causal traceback (`CB`, paper **C**). It preserves the supplied implementation's prompts, media adapters, and first-valid-answer scoring, with corrections for unsafe catalog parsing, annotation leakage into CoT, ambiguous answers, subset selection, resume, and reporting.

**The runner is not an exact reproduction of the frozen results in paper Table 2.** The website's paper leaderboard and new unified-runner candidates are separate. No paid provider evaluation or reproduction of the 16 paper model scores was performed during this release review. The checked-in model registry is a configuration snapshot; API access, model names, and availability require verification with the selected provider.

## Install and verify without a dataset or API keys

Use Python 3.10+; the release was tested with Python 3.12. The packaged FFmpeg binary from `imageio-ffmpeg` is used if `ffmpeg` is absent from `PATH`.

```bash
cd evaluation
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/smoke.py --out runs/synthetic-smoke
```

The smoke command requires a fresh output directory. It creates a four-question artificial catalog and media, starts a loopback-only HTTP server, and runs the real evaluator through chat, Gemini, and streamed Responses adapters. It checks a 5→3 FPS fallback, answer selection, scoring, resume, summaries, and candidate export. Its arbitrary 75% mock accuracy is **not a benchmark result**. It needs no API key and contacts no remote service.

For development, `python -m pip install -r requirements-dev.txt` also installs pytest; `python -m pytest tests -q` runs the same tests.

## Evaluate prepared benchmark inputs

Benchmark media and the aligned portable catalog are distributed separately through Hugging Face (upload currently awaiting account verification). The public catalog carries explicit pairing metadata; historical provider logs are not included. Use `ember-bench download` after publication, then supply `data/EMBER-Bench/catalog.json` to the lower-level runner below. See [catalog format and preprocessing responsibilities](docs/CATALOG.md); the tiny [synthetic fixture](fixtures/synthetic/README.md) is only an executable schema example.

```bash
# Validate the selected catalog and media hashes without requests or API keys.
python ember_eval.py --catalog /path/to/catalog.json --out runs/preflight --validate-catalog

# Bash: set only the credentials needed by your selected model.
export DASHSCOPE_API_KEY="your-key"
python ember_eval.py --catalog /path/to/catalog.json --models qwen3.8-flash --out runs/main

# Summaries live under OUT/CONDITION/MODEL, not directly under OUT.
python scripts/analyze_results.py runs/main/V1M0
python scripts/export_submission.py --run-dir runs/main/V1M0/qwen3.8-flash --output runs/candidate.json
```

In PowerShell, use `$env:DASHSCOPE_API_KEY = "your-key"`. See [QUICKSTART.md](QUICKSTART.md) for both shells and [all CLI options](docs/USAGE.md).

## Conditions and scoring

| CLI condition | Inputs | Selection |
|---|---|---|
| `V1M0` | Prepared history video + current frame | All selected P and C questions |
| `V0M0` | Current frame only | P questions only |
| `V1M3` | Video + current frame + completed action log | Explicit matched P subset |
| `V1M3C` | `V1M3` + incident causes | Cause-only extension, not a paper Table 2 condition |
| `V1M3CC` | `V1M3` + incident causes and consequences | Explicit matched P subset; paper V+L+E input intent |
| `CoT` | `V1M0` + causal assessment instruction | Explicit matched P subset; no action log or extra annotations |

For paired ablations/CoT, supply `--questions paired_prediction_ids.txt` or explicit `is_paired: true` on the appropriate P items. The paper has **151 matched pairs**, while all L2–L4 P questions total **343**; level alone cannot identify the paired subset. A custom or limited run must report its actual selected count.

The default video ladder is 5→3→1 FPS over the entire supplied prefix. Non-transient failures advance the ladder; network/429/5xx failures allow up to three attempts within a stage. Authentication/quota errors halt the model and return a nonzero CLI status. After credentials are corrected, the same command resumes that stage. The first valid answer is retained even if wrong. Unanswered questions count as incorrect; empty splits report `null`.

Each model directory contains `manifest.json`, `attempts.jsonl`, `selected.jsonl`, and `summary.json`. Runs record source catalog, selected catalog, code, configuration, prompt, and media hashes. Resume refuses a changed catalog/subset/configuration/code/condition/endpoint/media-verification setting. Use a fresh output directory when any of those change.

## Paper protocol and compatibility limits

The paper describes a 5 Hz full-prefix visual sequence followed by the decision frame, uniform downsampling to fit interface constraints, no audio, per-question requests, and failed answers scored incorrect. This runner uses a fixed 5→3→1 ladder and shared output limit. The frozen table contains **699 questions per model (548 P / 151 C)**, not the synthetic fixture or an arbitrary subset.

The supplied legacy package notes also described model-specific token limits, prompt/fps handling, and reasoning settings in the historical experiments. Those notes are not enough to reconstruct the original provider runs, and are not asserted as additional verified claims about the paper. Current endpoint-specific thinking parameters are visible in `configs/models.json`; wire formats and provider controls differ even when the task prompt is shared.

The released parser accepts a single `Final Answer: [A]` letter, with harmless Markdown decoration, plus compatibility fallbacks for a naked final-line letter or `B. <exact option text>`. It rejects conflicting final answers and echoed/multiple-choice templates. These parser corrections and compatibility fallbacks are disclosed implementation behavior, not proof of identity to the frozen parser.

Provider defaults use direct service endpoints, including official Gemini and OpenAI URLs. The supplied package used third-party Gemini/GPT gateways; this release no longer sends credentials to those gateways by default. To use your own deployment or gateway, explicitly edit a custom registry with `--config` or set the documented base URL environment variable, and review the destination. `api_model` can map a safe local model ID to a provider deployment name.

## Candidate review

The exporter checks artifact hashes and recomputes counts/accuracies from selected predictions. It emits `review_status: "review-required"`, `protocol: "unified-runner"`, and explicit synthetic/completion flags. An interrupted run is marked `incomplete`, with `incomplete_questions` and `never_attempted`; finishing resume is required before submitting a complete benchmark entry. Export never changes the website or paper leaderboard.

Hashes establish internal consistency, not dataset authenticity, leakage-free preprocessing, or independent verification that a provider ran a model. Maintainers must review dataset identity, preprocessing, actual deployment, full retry completion, and artifacts before publishing a result. See the repository's [leaderboard process](../docs/LEADERBOARD.md).

## Documentation and license

- [Quick start](QUICKSTART.md)
- [CLI, outputs, endpoints, and troubleshooting](docs/USAGE.md)
- [Catalog schema and input boundaries](docs/CATALOG.md)
- [Development and contributions](CONTRIBUTING.md)
- [Release review notes](docs/REVIEW.md)
- [MIT license](LICENSE)

Report reproducible issues through [the repository](https://github.com/ZHAOAlexGoat/EMBER-Bench/issues).
