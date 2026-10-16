# EMBER-Bench

Benchmarking Cross-Event Causal Memory in Long-Horizon Embodied Tasks

[Paper](https://arxiv.org/abs/2610.05013) · [Dataset](https://huggingface.co/datasets/Alexzhao0605gt/EMBER-Bench) · [Homepage](https://zhaoalexgoat.github.io/EMBER-Bench/) · [Leaderboard](https://zhaoalexgoat.github.io/EMBER-Bench/leaderboard.html)

EMBER-Bench evaluates cross-event causal memory in egocentric household videos: **699 four-choice questions from 189 tasks**. P asks for the next action; C asks which earlier event explains it.

| Scenario | P | C |
|---|---:|---:|
| L1 Task Progress | 205 | 0 |
| L2 Self-induced Anomaly | 113 | 58 |
| L3 External Intervention | 128 | 60 |
| L4 Compound Long-Horizon | 102 | 33 |

## 1 Install

Use **Python 3.12** (3.10+ supported) and Git. The API client runs on **Windows, Linux, and macOS** and needs no GPU. FFmpeg is included through a Python dependency.

[CI](https://github.com/ZHAOAlexGoat/EMBER-Bench/actions/workflows/ci.yml) checks installation, local API tests, and public data downloads on all three systems.

```bash
git clone https://github.com/ZHAOAlexGoat/EMBER-Bench.git
cd EMBER-Bench
```

Create and activate a virtual environment:

| Terminal | Create | Activate |
|---|---|---|
| Windows Command Prompt | `py -3.12 -m venv .venv` | `.venv\Scripts\activate.bat` |
| Linux or macOS Bash/Zsh | `python3 -m venv .venv` | `source .venv/bin/activate` |

PowerShell: activate with `.\.venv\Scripts\Activate.ps1`. If script execution is blocked, use Command Prompt above, or replace `python` below with `.\.venv\Scripts\python.exe` without activation. Linux may require its `python3-venv` package.

Run the remaining commands from the repository root:

```bash
python -m pip install -e .
python -m ember_bench api-test
```

`api-test` uses a local mock API: no key, data download, or paid calls.

## 2 Set your model and API

For a multimodal OpenAI-compatible Chat Completions endpoint:

```bash
python -m ember_bench init --api-base https://YOUR_PROVIDER/v1 --model YOUR_MODEL
```

Set your key in the same terminal:

| Terminal | Command |
|---|---|
| Windows PowerShell | `$env:EMBER_API_KEY = "YOUR_KEY"` |
| Windows Command Prompt | `set "EMBER_API_KEY=YOUR_KEY"` |
| Linux or macOS Bash/Zsh | `export EMBER_API_KEY="YOUR_KEY"` |

`model.local.json` stores the API URL and exact model name; edit it to switch providers or models. Keys stay in environment variables. For a local model server, use `http://localhost:8000/v1`; set the key to `local` if authentication is disabled. The server must support image input.

Chat mode sends sampled JPEG frames by default. Native MP4, Responses, and Gemini adapters are also available; see [API options](QUICKSTART.md#3-configure-an-api-or-a-local-model-server).

## 3 Run one question

```bash
python -m ember_bench download --limit 1
python -m ember_bench validate --limit 1
python -m ember_bench evaluate --limit 1 --fps-ladder 1 --max-output-tokens 128 --out runs/first-test
```

Downloads are public and require no Hugging Face login. This reduced-sampling run checks connectivity at low cost; your API provider's charges apply. It is not a full benchmark score. `python -m ember_bench api-test --live` optionally tests your API with one tiny synthetic question.

## 4 Run a category or the full benchmark

```bash
# L2 causal traceback only
python -m ember_bench download --levels L2 --tasks C
python -m ember_bench evaluate --levels L2 --tasks C --out runs/l2-c

# All 699 questions, about 4.67 GiB of media
python -m ember_bench download
python -m ember_bench validate
python -m ember_bench evaluate --out runs/full
```

Combine selections, for example `--levels L2 L3 --tasks P C`. L1 has P only. Use the same selection for download and evaluation. `--data-root PATH` changes the data location; quote paths containing spaces.

Results are in `runs/NAME/V1M0/custom/summary.json`, with predictions in `selected.jsonl`. Rerun the same command to resume completed questions without repeat API calls. Use a new `--out` directory after changing model, configuration, subset, or code. The default evaluation uses a 5 → 3 → 1 Hz retry ladder and a 512-token output budget; report any changes.

## Code and details

`ember_bench/` provides the CLI; `evaluation/` contains inference, scoring, and model adapters; `docs/` contains the website. Evaluation media and annotations live on Hugging Face. Downloads pin a revision and verify file hashes.

[Full guide](QUICKSTART.md) · [Data format and known limitations](docs/DATASET.md) · [Evaluation protocol](evaluation/README.md) · [Release checks](docs/RELEASE_20261017.md)

The unified runner does not exactly reproduce every model-specific setting in the paper. Keep run manifests when reporting scores. Code: [MIT](evaluation/LICENSE). Data: [CC BY-NC 4.0](dataset_card/LICENSE), with attribution and noncommercial use. Cite the [EMBER-Bench paper](https://arxiv.org/abs/2610.05013). Contact: zhaoboning0605@gmail.com.
