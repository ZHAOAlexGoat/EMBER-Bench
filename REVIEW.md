# Initial release review

Reviewed on **2026-10-02** before uploading the website and evaluation package to the aligned GitHub account, **Alex0605goat**.

## Paper and leaderboard

The paper is 26 pages. Its SHA-256 is `443f0b84a1af5f5e6c3fb94046bf866ad77926a2140d82a7d750cb7bf3ee1b1b`.

An independent paper audit visually checked the rendered Table 2 and checked the transcription against the extracted table. All **17 rows × 10 scores = 170 values** match the manuscript. The human mean is a separate reference, excluded from ranking. The complete JSON, CSV, and no-JavaScript HTML fallback agree exactly.

Verified counts: 189 tasks, 699 questions, 548 P questions, 151 C questions, and 151 matched pairs. Per-level P/C counts are documented in the leaderboard guide. The stale action-log gain of 1.7pp in the previous README was corrected to the final manuscript's **1.6pp**; the additional privileged-annotation gain is **13.0pp**. The Gemini 3.1 Pro **Preview** label now matches Table 2.

The Doubao display name has been corrected to **Doubao-Seed-2.1-Pro** at the user's request in the leaderboard JSON, downloadable CSV, static HTML, and evaluation model metadata. All 170 scores, categories, and model ranks remain unchanged. The evaluation provider deployment key remains `doubao-seed-2-1-pro-260915`. The pinned table fingerprint was regenerated after verifying that only this display name changed.

The paper's anonymous review URL states that review data and code are available. Its live contents could not be verified in this review. The public repository's complete dataset release remains **pending**; the website does not provide an invented dataset download or license.

## Website validation

- Original memory-field SVG illustration, event/state/action layout, and keyboard-accessible prediction/traceback explanation.
- Real browser rendering at 1440px desktop and 390px mobile widths; no page overflow, broken images, script errors, or HTTP resource errors.
- Local resource links checked under a project subpath; GitHub links align to `Alex0605goat/EMBER-Bench`.
- Search and empty state; 7 closed-source / 9 open-source filters; all ten score columns in both sort directions; global ranks and ties with an unranked human reference.
- Downloaded CSV checked against all 170 values; no-JavaScript table checked against the same values.
- Keyboard tabs, mobile menu/Escape handling, and reduced-motion behavior exercised.
- Dependency-free `scripts/validate_site.py` checks the paper snapshot, unpublished paper exclusion, public ownership configuration, and all local HTML links. `scripts/sync_leaderboard.py` regenerates CSV and static table from reviewed JSON.

The user subsequently supplied three original figure PDFs: `benchmark_overview_film.pdf`, `benchmark_diversity.pdf`, and `section4_analysis.pdf`. The website uses full-page, 3200px-wide PNG renders with the original aspect ratios, colors, labels, and content. Each figure links to its unmodified source PDF. Byte identity against the supplied files was verified; checksums and render dimensions are recorded in `docs/assets/figures/originals.json` and checked during CI. The overview, dataset coverage, and analysis sections use these original figures. The analysis caption distinguishes diagnostic paired-subset ablations from the main 699-question leaderboard.

The supplied five-stage construction PNG now appears in Design; the original task filmstrip figure appears in Introduction. The design PNG remains byte-identical at 4287 × 2094, with its original transparency shown on a white canvas. Its SHA-256 and dimensions are recorded in the same provenance manifest and checked during CI. The construction diagram's annotation schema is illustrative, separate from the executable runner's catalog interface.

## Evaluation review

The supplied evaluation package was audited and corrected. Material changes include:

- Replace arbitrary `eval` option parsing with safe parsing and strict four-option validation.
- Validate catalog IDs, split labels, media paths/hashes, and required condition inputs before API calls.
- Require an explicit matched P subset for paired experiments; 343 deep-level P items cannot stand in for the 151 paired items.
- Keep action logs and privileged annotations out of the CoT condition.
- Reject ambiguous multi-answer/template echoes and conflicting answer markers.
- Bind resume to catalog/subset/configuration/code/prompt/condition/endpoint identity, detect altered logs, and keep the first valid answer regardless of correctness.
- Recompute scoring from predictions; preserve unanswered items in denominators and use `null` for empty splits.
- Mark incomplete/quota-interrupted runs and export candidates as review required instead of publishing them automatically.
- Use direct provider endpoints by default for Gemini/OpenAI; custom gateways require explicit configuration.

**27 offline behavior tests passed**, including image-format MIME handling, real FFmpeg media processing, and a complete loopback smoke run through chat, Gemini, and streamed Responses transports. The smoke exercises 5→3 FPS fallback, scoring, resume, summaries, and candidate exports. It uses synthetic media and mock answers, requires no API key, and makes no paid requests.

Validation commands:

```bash
python scripts/validate_site.py
cd evaluation
python -m pytest tests -q
python scripts/smoke.py --out runs/synthetic-smoke
```

Use a fresh output directory for the smoke command. See the evaluation package's detailed review notes and catalog documentation for input boundaries.

## Light presentation and paper withdrawal

Both pages now use a spacious white presentation, graphite system sans-serif type, warm amber accents, and the continuous EMBER-Bench wordmark with a geometric flame icon. Real browser checks at 320, 390, 768, 1024, and 1440px verify that every visible button has at least a 16px label and a 44px target, with no page overflow, missing images, or script errors. Search, class filters, all score sorts, CSV export, keyboard tabs, mobile navigation, and the no-JavaScript table still pass.

The conceptual memory scene adds three signal paths, orbit layers, node activation, central echoes, and gentle pointer depth. Browser checks verify actual motion, reduced-motion reset and freeze, offscreen pause and resume, repeated back/forward-cache lifecycle, and terminal cleanup. Scientific figures and all 170 reported scores remain unchanged.

Conference submission and review-status promotion was removed from public text. At that stage, the unpublished paper PDF and its download links were removed and no replacement preprint URL was advertised. Only the three user-approved original figure PDFs are allowed in the deployed site. The validator and ignore rule prevent reintroducing a local manuscript PDF into the Pages assets.

The Overview now credits all eight authors in the order shown in the supplied OpenReview screenshot. Aoyang Cai and Boning Zhao are marked as equal contributors, Zhiwei Yu and Guocai Yao as corresponding authors, and Shaoxuan Xie is assigned to BAAI according to the user's correction. An independent visual transcription and HTML review checked the names, order, institution numbering, contribution markers, and accessible labels. The author block was inspected at 320, 390, 768, and 1440px with no clipping or page overflow.

The author block has been integrated into the opening research masthead, before the conceptual memory hero. A compact centered byline replaces the widely spaced grid. Official Tsinghua, HKU, and BAAI institution marks accompany larger affiliation names; their original files and source pages are documented. The mobile layout uses HKU's standalone shield rather than shrinking the full signature. Browser inspection at 320, 390, 768, 1024, and 1440px verifies the original author order and markers, intact images, and no horizontal overflow.

Per the user's affiliation correction, Aoyang Cai and Boning Zhao also have BAAI affiliations as interns: their superscripts are respectively `1,3,*` and `2,3,*`, with both institutions included in the accessible labels.

## Mint and ice-blue presentation refinement

An earlier refinement introduced very pale mint and ice-blue light fields with slow gradient motion and readable deep-teal text. The conceptual memory SVG used matching colors; all four original scientific figures, institution assets, and reported leaderboard scores remained unchanged. Reduced motion disables the decorative gradient motion and immediately shows full score bars.

The comparison card now shows the unweighted average of the 16 non-human models' reported Overall accuracies: `660.3 / 16 = 41.26875%`, displayed as **41.3%**. An independent calculation and visual check of the supplied table verified all 16 inputs. The average excludes the human reference, and the website validator checks both the one-decimal display and the exact bar percentage against the leaderboard JSON. Each score track stays visible while its fill expands from the left; the three fills start in sequence.

## Warm-white and champagne refinement

The shared theme now uses warm white, extremely pale champagne and ivory light fields, charcoal text, and restrained amber accents. The conceptual memory SVG follows the same palette; its geometry, signals, and motion are unchanged. The two background layers retain their 32- and 39-second motion, and the score fills retain their staggered left-to-right expansion. Scientific figure and institution files, author markers, all reported scores, and the 41.3% model average are unchanged.

Desktop and mobile browser checks at 320, 390, 768, 1024, and 1440px verified both pages without horizontal overflow, missing images, undersized controls, or script errors. Visual inspection covered the research masthead, conceptual hero, comparison card, and leaderboard. Checks also passed for sequential fills with fixed tracks, reduced motion, and no-JavaScript fallback. Calculated contrast is at least 5.21:1 for primary button text and 4.76:1 for secondary small text on the reviewed interface surfaces.

## Transparent institution mark and compact score motion

The Tsinghua affiliation now displays the complete university emblem from the official Visual Identity site's transparent PNG as a native CSS alpha mask in Tsinghua purple. The original source bytes are preserved and documented in `docs/assets/institutions/SOURCES.md`; no emblem is generated or redrawn. Desktop and mobile inspection confirms the former JPEG's white rectangle is gone. Checks at 320, 390, 768, 1024, and 1440px verify readable affiliation names, unchanged author markers, intact research figures, and no overflow.

The three score fills now take 0.55 seconds each and start 0.18 seconds apart, finishing in approximately 0.91 seconds after the first begins. Browser sampling verifies ordered, monotonic left-to-right growth, fixed tracks and left edges, and the exact final 98.3%, 61.2%, and 41.26875% fill proportions. Reduced motion and the no-JavaScript fallback show complete fills immediately. The 170 reported scores and 41.3% displayed model average are unchanged. CSS and homepage script cache versions are updated.

## Practical limits

The complete real dataset/media, frozen paired-ID lists, and historical provider artifacts are not included. This review verifies an executable **unified runner**, not an exact reproduction or independent validation of the paper's 16-model scores. Live provider availability and deployment IDs were not tested. Media-prefix boundaries, option overlays, face blurring, and annotation leakage require review of the actual released inputs; hashes alone cannot establish those properties.

The code, website, documentation, and candidate-review process are ready for release with these boundaries stated. GitHub Actions performs the same website and offline test checks; Pages publishes only the `docs/` directory.

## GitHub account username alignment

On 2026-10-03, the owner account was renamed from `Alex0605goat` to `ZHAOAlexGoat`. The independent public `EMBER-Bench` repository keeps its identity and history. Current repository links, Pages URLs, site configuration, and owner-validation assertions use the new name. The October 2 review above preserves the username used at that time.

## Public arXiv paper — 2026-10-11

The user supplied the public preprint at [arXiv:2610.05013](https://arxiv.org/abs/2610.05013). The official abstract page was checked: the full title and eight-author order match the website, and v1 was submitted on 2026-10-04. Both navigation menus and footers now link to the paper. The homepage has a “Read the paper” hero button and a paper resource card; the leaderboard links its Table 2 provenance to arXiv. The repository README includes a prominent paper link and publication details.

The paper URL is recorded in both site and leaderboard metadata and checked during CI. The score fingerprint, all 170 scores, the 16-model average, original figures, author markers, and pending dataset status remain unchanged. No local manuscript PDF or conference promotion is introduced.

The public arXiv v1 PDF's Table 2 (page 8) was independently checked against the leaderboard JSON: all 17 row labels and all 170 accuracy values match exactly. The public PDF SHA-256 is `b52f90fe87da96e84fec82f93ce79259d2507b827fe9b4578b589206d1ab979f`. The public PDF's first-page affiliations and contribution markers also match the website.

Independent source and diff review passed, as did static site validation and whitespace checks. Browser verification passed all 28 combinations of both pages, widths of 320, 390, 768, 851, 900, 1024, and 1440px, and JavaScript enabled or disabled. Paper and existing navigation links work, including the desktop/mobile breakpoint; no page overflow, missing images, script errors, or failed site resources were found.
