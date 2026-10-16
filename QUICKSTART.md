# Run EMBER-Bench

Python 3.10+ is supported; Python 3.12 is recommended. Installation, offline tests, the local API smoke test, and an anonymous data download are checked in CI on Windows, Linux, and macOS with Python 3.12, plus Linux with Python 3.10. The CLI includes a packaged FFmpeg fallback. Start with the [OS-specific environment setup](README.md#1-install); run the commands below from the repository root.

**Data is available:** [Alexzhao0605gt/EMBER-Bench](https://huggingface.co/datasets/Alexzhao0605gt/EMBER-Bench) contains 699 checked questions (4.67 GiB) under CC BY-NC 4.0. Public downloads need no Hugging Face login. The verified snapshot with the current README is `789111aff84058db4bb1d2a2441e8fbd8ea469bc`; use `--revision 789111aff84058db4bb1d2a2441e8fbd8ea469bc` with `download` to request it. Media and annotations are unchanged from the original release.

## 1. Install

```bash
git clone https://github.com/ZHAOAlexGoat/EMBER-Bench.git
cd EMBER-Bench
python -m pip install -e .
ember-bench api-test
```

The last command starts a local mock API, checks four input adapters, and tests retries, scoring, and resume. It makes **no paid calls** and needs no dataset or API key. If your shell cannot find `ember-bench`, use `python -m ember_bench` in its place. A virtual environment is recommended.

## 2. Download the data you need

```bash
# One P question for a first run
ember-bench download --levels L1 --tasks P --limit 1
ember-bench validate --levels L1 --tasks P --limit 1

# All C questions in L2 (58 items)
ember-bench download --levels L2 --tasks C

# All scenarios and question types (699 items; about 4.7 GiB)
ember-bench download
ember-bench validate
```

The default location is `data/EMBER-Bench`. Use `--data-root /your/path` consistently to change it. Downloading a subset transfers only its videos and current images plus metadata. Subsequent commands resume and repair corrupted files, keeping the first resolved HF commit. A `download_receipt.json` records that commit; use `--revision COMMIT_OR_TAG` and a new data directory when changing releases. Public downloads require no HF login.

| Selection | Count |
|---|---:|
| `--levels L1 --tasks P` | 205 |
| `--levels L2 --tasks P` | 113 |
| `--levels L2 --tasks C` | 58 |
| `--levels L3 --tasks P` | 128 |
| `--levels L3 --tasks C` | 60 |
| `--levels L4 --tasks P` | 102 |
| `--levels L4 --tasks C` | 33 |

Combine levels (`--levels L2 L3 L4`) and types (`--tasks P C`), or omit both for all questions. L1 has P only; requesting only L1-C gives an explanatory error. `--limit N` selects the first N items **after** scenario/type filtering; it is a smoke subset, not a representative benchmark score.

## 3. Configure an API or a local model server

For an OpenAI-compatible multimodal Chat Completions service:

```bash
ember-bench init --api-base https://YOUR_PROVIDER/v1 --model YOUR_DEPLOYMENT_NAME
```

For a self-hosted compatible vision-language model:

```bash
ember-bench init --api-base http://localhost:8000/v1 --model YOUR_LOCAL_MODEL
```

Run one of these commands. It creates `model.local.json`; it will not overwrite an existing config. The config's local ID is `custom`; `api_model` is the exact deployment name sent to the API, including names containing `/`. Change that JSON to switch models, providers, output budget, frame limits, or provider-specific request fields. Use `--out other-model.json` and later `--config other-model.json` for additional models.

Chat mode defaults to a sequence of sampled JPEG frames, supported by many multimodal compatible servers. If your provider accepts native MP4 `video_url`, add `--input-mode video`. For a Responses API use `--protocol responses`; for Gemini's native `generateContent` API use `--protocol gemini` and its API base (without the final model/action path). Compatibility and input limits depend on the deployed model. The existing multi-provider registry remains available at `evaluation/configs/models.json`.

Set the key locally in the same terminal:

```bash
# Bash / zsh
export EMBER_API_KEY='YOUR_KEY'
```

```powershell
# Windows PowerShell
$env:EMBER_API_KEY = 'YOUR_KEY'
```

For an unauthenticated local server, set the value to `local`. Keys are read from the environment and not saved in model configs or run manifests. `--key-env ANOTHER_VARIABLE` chooses another name at config creation.

```bash
# One 1-second synthetic clip; at most 128 output tokens
ember-bench api-test --live
```

The live test sends one tiny synthetic example to your configured service, so its normal API charges apply. It verifies media transport and answer parsing without downloading benchmark data. This is not a model accuracy result.

## 4. Run a small test, a category, or everything

```bash
# Low-cost real-data check; reduced sampling is for smoke testing
ember-bench evaluate --levels L1 --tasks P --limit 1 --fps-ladder 1 --max-output-tokens 128 --out runs/first-test

# One complete category with the normal 5 → 3 → 1 Hz retry ladder
ember-bench evaluate --levels L2 --tasks C --out runs/l2-c

# Full 699-question evaluation
ember-bench evaluate --out runs/full
```

Use the same `--levels`/`--tasks` selection when downloading and evaluating. Rerun the identical evaluation command to resume; completed questions are not called again. Changing the model, config, subset, sampling, or condition requires a different output directory. `--workers 2` is the default; use `--workers 1 --min-interval 1` for stricter service limits. The generated config uses a 512-token output budget; select a suitable larger budget for models that need it and report the chosen budget.

Results are written under `runs/NAME/V1M0/custom/`: `summary.json` contains overall and per-level/type accuracy, `selected.jsonl` contains selected predictions, and `attempts.jsonl` plus `manifest.json` retain retry and configuration evidence. Unanswered items count as incorrect. `--summarize` rebuilds results without requests. Never compare a tiny subset or a synthetic test's accuracy with the full paper table.

For registry models:

```bash
ember-bench evaluate --config evaluation/configs/models.json --models MODEL_ID --out runs/registry-model
```

Only an explicit `--models all` runs the entire selected registry. See [advanced usage](evaluation/docs/USAGE.md) for provider settings and [protocol details](evaluation/README.md) for the distinction between this unified runner and the frozen paper results.

## Memory conditions and matched pairs

V1M0 is the main video/current-frame condition. `--condition V0M0` uses only current frames and P questions. `--condition V1M3`, `V1M3C`, `V1M3CC`, or `CoT` selects the explicitly paired 151 P questions by default; scenario/type filters further narrow that subset. The C and CC variants contain privileged annotations and are diagnostic ablations. `--questions ids.txt` accepts explicit IDs. The main prompt never receives reference answers or these privileged fields.

## Data checks and maintenance

`ember-bench validate` verifies schema, paths, and hashes before any model calls. A full decode check is available with system FFmpeg/FFprobe installed:

```bash
ember-bench validate --decode
```

This checks the full local dataset for complete decoding, silent streams, 5 Hz history, landscape dimensions, and zero display rotation. [Data preparation and limitations](docs/DATASET.md) documents the four rotated C-label layouts, brief OPTION markers, and other retained limitations. Data use is **CC BY-NC 4.0**; code is **MIT**.
