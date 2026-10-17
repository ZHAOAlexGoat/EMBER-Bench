# Runner usage

All examples run from `evaluation/`. `python ember_eval.py --help` is the authoritative argument list.

## CLI options

| Option | Default / behavior |
|---|---|
| `--catalog PATH` | Required, including when summarizing |
| `--config PATH` | `configs/models.json`; custom registry supports `api_model` overrides |
| `--models ID [ID ...]` | `all`; explicitly select one model for an initial provider run |
| `--condition NAME` | `V1M0`; also `V0M0`, `V1M3`, `V1M3C`, `V1M3CC`, `CoT` |
| `--out PATH` | Required run root |
| `--workers N` | 8, allowed 1–256; concurrent questions within a model; models run sequentially |
| `--min-interval SECONDS` | 0; minimum interval between request starts in this process |
| `--path-map [OLD=NEW ...]` | Empty; first matching media-root prefix mapping |
| `--questions PATH` | Whitespace-separated question IDs; unknown IDs fail |
| `--limit N` | No limit; positive N selects the first N after filtering |
| `--no-verify-sha` | Off; skips media SHA verification and records the change in identity |
| `--validate-catalog` | Validate catalog/schema/media and exit without requests or keys |
| `--summarize` | Rebuild selected answers/summary from existing journals without requests |

`--summarize` and `--validate-catalog` are mutually exclusive. `V0M0` filters out CB. Memory conditions and CoT require an explicit matched P subset; `--questions` or a genuine `is_paired` flag selects it. A full level L2–L4 subset is not automatically the paper's 151 matched P questions.

## Configuration and endpoints

The registry includes `defaults`, `endpoints`, and `models`. Each endpoint declares `protocol`, `base_url`, and `key_env`. Remote URLs must use HTTPS and cannot embed credentials/query parameters. Loopback HTTP is accepted for tests/local model servers. Overrides are validated using the same rules.

| Registry endpoint | Credential | Optional URL override | Default destination |
|---|---|---|---|
| `dashscope` | `DASHSCOPE_API_KEY` | `DASHSCOPE_BASE_URL` | DashScope compatible-mode service |
| `gemini` | `GEMINI_API_KEY` | `GEMINI_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta` |
| `responses` | `OPENAI_API_KEY` | `OPENAI_BASE_URL` | `https://api.openai.com/v1` |
| `ark` | `ARK_API_KEY` | `ARK_BASE_URL` | Volcengine ARK service |
| `mimo` | `MIMO_API_KEY` | `MIMO_BASE_URL` | Xiaomi MiMo service |

The original gateway destinations were removed from Gemini/OpenAI defaults. If selecting a custom gateway, you explicitly control and review its base URL. Keys and visual inputs are sent to the selected service. Large DashScope videos use its temporary private OSS upload adapter when inline limits are exceeded; other adapters fail oversized inline inputs and advance the ladder.

Example custom registry for an independently deployed chat model:

```json
{
  "defaults": {"temperature": 0, "max_output_tokens": 16384, "fps_ladder": [5, 3, 1], "timeout_s": 900},
  "endpoints": {
    "my-server": {"protocol": "chat", "base_url": "https://your-deployment.example/v1", "key_env": "MY_DEPLOYMENT_KEY"}
  },
  "models": {
    "my-model": {"name": "My deployment", "endpoint": "my-server", "api_model": "provider-deployment-id"}
  }
}
```

Use `python ember_eval.py --config custom-models.json --catalog catalog.json --models my-model --out runs/custom`. A model ID is a safe directory name; `api_model` is the string sent to the provider. For Responses, history is JPEG frames; chat/Gemini use resampled video and a separate current image. The task prompt is shared, but wire controls differ. Endpoint `extra_body` / `extra_generation_config` may override generation settings, and are included in configuration identity. Provider-specific controls and model names are not certified as continuously available.

## Retry and resume

Transient network, 429, and 5xx failures allow three attempts in a stage, with 30 × retry-number seconds of shared cooldown. Other failures advance 5→3→1 FPS. A valid answer ends the question; correctness never controls retries. Authorization/quota failures stop the model, write a partial summary, and return exit code 2. Fix the credentials and rerun the same command to resume the failed stage.

Rerun with the same catalog, condition, subset, model registry, code, media-verification setting, and endpoint URL. Completed valid questions are skipped. Exhausted unsuccessful stages stay exhausted. A changed input identity fails with instructions to use a new output directory. Worker count and pacing may change without affecting identity. Do not run two processes against the same model output directory; journal locking is within one process only.

An interrupted partial JSONL line causes a diagnostic identifying the file and line. Preserve the complete journal and a backup before removing a demonstrably truncated final line; do not silently discard valid attempts. Old journals without a matching manifest are intentionally refused.

## Outputs

```text
OUT/
  manifest_V1M0.json                 # latest invocation metadata
  _media_cache/                      # derived video / JPEG sequences
  V1M0/
    MODEL/
      manifest.json                 # stable per-model run identity and selected question IDs
      attempts.jsonl                # every attempt: raw output, errors, prompt hash, stage, FPS
      selected.jsonl                # one row per selected question; first valid prediction
      summary.json                  # accuracy, split counts, completion, artifact hashes
```

`summary.json` retains `P`/`C` names for compatibility; `selected.jsonl` uses `NA`/`CB`. `overall` is pooled question accuracy, not the average of P and C percentages. Empty splits are `null`; unanswered questions remain in denominators and score zero. `run_status` is `complete` only when every selected question has a valid answer or all configured nonfatal retry stages are exhausted. `incomplete_questions` and `never_attempted` distinguish an interrupted run from ordinary answered/failed items.

The terminal prints the same metrics as a readable table, including question counts, valid/unanswered/pending counts, status, and absolute result paths. Empty splits display `N/A`; JSON retains `null`. Mock runs are labeled `MOCK TEST`. Interrupted runs display `INCOMPLETE RUN` and must be resumed before reporting a final score. Retry-exhausted questions are counted as done on resume and remain incorrect; they are not requested again. `--summarize` returns an error if a requested model has no attempt journal at the specified output path.

```bash
python scripts/analyze_results.py runs/main/V1M0
python scripts/export_submission.py --run-dir runs/main/V1M0/my-model --output runs/my-model.candidate.json
```

Export validates hashes of manifest, attempts, and selected rows; recomputes pooled and split scores; and checks completion metadata. The candidate contains `model`, `condition`, `protocol`, `catalog_sha256`, `counts`, `accuracy`, `run_manifest`, `review_status`, `synthetic`, and `run_status`. Accuracy keys are `overall`, `NA_all`, `CB_all`, `NA_L1`–`NA_L4`, and `CB_L2`–`CB_L4`. Partial/synthetic candidates remain explicitly marked and must not be posted as complete research results. No score is uploaded automatically.

## Troubleshooting

- **Missing credential**: set the registry's `key_env` using Bash `export NAME="..."` or PowerShell `$env:NAME = "..."`. OpenAI uses `OPENAI_API_KEY`, not the old `GPT_API_KEY`.
- **Unknown or unavailable model**: verify your provider deployment and use a custom `api_model`; registry presence alone does not prove availability.
- **Media missing/hash mismatch**: check relative paths and root mapping, then obtain the authoritative file rather than bypassing verification for an official run.
- **No paired subset**: use the matched P ID list or genuine `is_paired` fields. L2–L4 alone contains more P items than the paired sample.
- **Too many frames/oversize**: the runner uniformly downsamples the whole prefix through its ladder; if the last stage fails, the unanswered item scores incorrect.
- **Changed identity**: use a new output directory. Summarizing requires the same code/configuration/catalog/subset as the original run.
- **FFmpeg unavailable**: install `requirements.txt`, which includes `imageio-ffmpeg`, or supply FFmpeg on `PATH`.

The runner cannot establish whether upstream histories, labels, annotations, or pairing obey the paper's data boundaries. See [CATALOG.md](CATALOG.md) and [the protocol disclosure](../README.md#paper-protocol-and-compatibility-limits).
