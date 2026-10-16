---
pretty_name: EMBER-Bench
license: cc-by-nc-4.0
language:
  - en
task_categories:
  - video-text-to-text
tags:
  - egocentric-video
  - embodied-ai
  - causal-memory
  - benchmark
size_categories:
  - n<1K
configs:
  - config_name: default
    data_files:
      - split: test
        path:
          - metadata.jsonl
          - data/**/*.mp4
    drop_labels: true
---

# EMBER-Bench

**Benchmarking Cross-Event Causal Memory in Long-Horizon Embodied Tasks**

[Paper](https://arxiv.org/abs/2610.05013) · [Code and evaluation](https://github.com/ZHAOAlexGoat/EMBER-Bench) · [Homepage](https://zhaoalexgoat.github.io/EMBER-Bench/)

EMBER-Bench tests which earlier events matter for the next action in recorded egocentric household activities. This evaluation release contains **699 four-choice questions** from **189 tasks**, with silent pre-decision history videos and current decision images. It is an offline reasoning benchmark.

| Scenario | Prediction (P) | Causal traceback (C) |
|---|---:|---:|
| L1: Task Progress | 205 | 0 |
| L2: Self-induced Anomaly | 113 | 58 |
| L3: External Intervention | 128 | 60 |
| L4: Compound Long-Horizon | 102 | 33 |
| Total | 548 | 151 |

All 151 C questions are paired with a P question at the same decision point. The public `test` split includes reference answers for reproducible evaluation. There is no training split; do not train on evaluation answers and report the result as held-out performance.

## Download and evaluate

The recommended downloader fetches only the requested media, pins the HF commit, resumes interrupted downloads, and verifies SHA-256 hashes.

```bash
git clone https://github.com/ZHAOAlexGoat/EMBER-Bench.git
cd EMBER-Bench
python -m pip install -e .
ember-bench download --levels L2 --tasks C --limit 1
ember-bench validate --levels L2 --tasks C --limit 1
ember-bench api-test
```

Omit subset flags to download all 699 examples (approximately 4.7 GiB of media). See the code repository's [quick start](https://github.com/ZHAOAlexGoat/EMBER-Bench/blob/main/QUICKSTART.md) for custom API/model configuration, cheap live connectivity tests, full evaluation, and resume commands. No GPU is required for the API client; a self-hosted model has its own hardware requirements.

For dataset exploration with Hugging Face Datasets:

```python
from datasets import load_dataset, Video
dataset = load_dataset("Alexzhao0605gt/EMBER-Bench", split="test")
dataset = dataset.cast_column("video", Video(decode=False))
print(dataset[0]["question_id"], dataset[0]["video"])
```

Decoding the `video` feature requires the video dependencies supported by your Datasets version. The benchmark CLI uses FFmpeg and does not require PyTorch or TorchCodec.

## Files and schema

* `catalog.json`: the evaluator's portable JSON array, ordered by scenario and question bank.
* `annotations.jsonl`: the same rows in JSON Lines for other evaluation frameworks.
* `metadata.jsonl`: standard VideoFolder metadata (`file_name` points to the history MP4).
* `data/level*/...`: 699 history MP4s and 699 current-frame JPEGs, retaining the checked archive's relative paths.
* `release.json`: version, counts, checksums, file sizes, and source question-bank fingerprints.
* `audit.json`, `known_limitations.json`: release validation evidence and retained limitations.

Each row includes `question_id`, `level`, `task_type` (`P`/`C`), legacy-compatible `qa_type` (`NA`/`CB`), `task_id`, `objective`, `question`, `options`, `gold`, `decision_frame`, `history_video`, `current_frame`, and both media hashes. `paired_id` and `is_paired` identify the 151 matched decisions.

The normal V1M0 condition uses the objective, history, current frame, and the P options or C known next action. `gold` is used only for scoring. `m3_text` is a completed-action log for memory ablations; `incidents` contains privileged cause/consequence fields and must not be given to a main-condition model. The provided runner enforces these input boundaries.

Only events ending at or before `decision_frame` are included in the action log. Objectives and logs are derived from the canonical timeline matched to the actual source task, correcting stale task-number mappings in legacy internal catalogs. Source frame indices are retained as provenance; the distributed history is sampled at 5 Hz. P/C question IDs, reference answers, and decision frames are retained from the checked question banks; P option text is unchanged, while C choices refer to the original OPTION A-D video markers.

## Media preparation and validation

All evaluation videos are silent, stored in landscape dimensions, and have zero display-rotation metadata. Full FFmpeg decoding checks every frame against the container frame count. SHA-256 checks cover all evaluation videos and current images. Every video was also visually inspected at 10%, 50%, and 90% of its duration for upright egocentric presentation. This is sampled visual inspection, not a frame-by-frame semantic certification.

L3/L4 history videos use the face-blurring workflow from [ego-video-privacy-blur](https://github.com/qinminghui869-sys/ego-video-privacy-blur), with high-quality H.264 encoding for changed videos. Side/partial faces were outside the requested frontal-face treatment scope. The release does not claim universal anonymization.

75 sideways L1/L2 histories and their current images were rotated 90 degrees counterclockwise to restore upright ego views. Frame counts, timestamps, rate, and duration were preserved; H.264 CRF 16 was used. The four affected C videos retain their original OPTION pixels and display times, rotated with the whole image; those labels consequently appear vertically. No options were retimed or relabeled. Unmodified videos are copied byte for byte. Raw source videos and `_not_blur` backups are excluded from this public evaluation package.

## Limitations and scoring

Five C items have less than one second of gold-label exposure; some have a single 5 Hz frame. These are retained and listed in `known_limitations.json`. Sampling below 5 Hz can miss brief markers. L3/L4 duration cues remain, and not all questions have undergone a fresh human semantic recertification. Do not interpret media validation as label re-annotation.

Report overall accuracy and the seven scenario/type cells; unanswered items count as incorrect. The supplied unified runner is not an exact reproduction of every model-specific setting in the frozen paper table. Changing frame rate, model deployment, output budget, prompt condition, or media release may affect results; retain run manifests and report these settings. Synthetic API-test scores are never benchmark results.

## License and attribution

The dataset is licensed under **Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)**. Attribute EMBER-Bench and its authors, link the license, indicate changes, and comply with its noncommercial terms. See [LICENSE](LICENSE). The separately distributed evaluation software uses MIT.

Authors: Aoyang Cai, Boning Zhao, Shaoxuan Xie, Dahui Gao, Huan Yang, Zhongyuan Wang, Zhiwei Yu, and Guocai Yao.

```bibtex
@article{cai2026emberbench,
  title={EMBER-Bench: Benchmarking Cross-Event Causal Memory in Long-Horizon Embodied Tasks},
  author={Cai, Aoyang and Zhao, Boning and Xie, Shaoxuan and Gao, Dahui and Yang, Huan and Wang, Zhongyuan and Yu, Zhiwei and Yao, Guocai},
  journal={arXiv preprint arXiv:2610.05013},
  year={2026}
}
```

Contact: zhaoboning0605@gmail.com. Report reproducible data issues through the code repository's issue tracker, including the question ID and release revision.
