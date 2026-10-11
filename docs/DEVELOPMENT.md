# Website development and GitHub Pages

The website is plain HTML, CSS, JavaScript, SVG, and JSON. It requires no build step, account, or API key. Both pages work under a GitHub Pages project path.

## Preview locally

From the repository root:

```bash
python -m http.server 8000 --directory docs
```

Open `http://localhost:8000/` for the homepage and `http://localhost:8000/leaderboard.html` for the leaderboard. Serve the files over HTTP so the browser can load local JSON.

## Edit content

- `docs/index.html`: benchmark narrative and figures.
- `docs/leaderboard.html`: leaderboard layout and table fallback.
- `docs/assets/`: styles, interaction scripts, and original illustrations.
- `docs/data/site.json`: repository ownership, repository links, and the public arXiv paper URL.
- `docs/data/leaderboard.json`: paper results. Check the file's provenance metadata and score field names before editing.

After a reviewed data edit, run `python scripts/sync_leaderboard.py` to regenerate the CSV and static HTML fallback from the JSON. `validate_site.py` pins the verified paper-table fingerprint, checks the public arXiv URL in site metadata, both pages, and the README, and excludes the local manuscript PDF from deployment. An intentional score correction or new manuscript revision also requires an evidence-backed fingerprint update. New protocols belong in a separately labeled results section.

The Table 2 paper snapshot is a separate protocol from new unified-runner evaluations. Do not replace paper numbers with a rerun or a synthetic test output. See [leaderboard review](LEADERBOARD.md).

## Original scientific figures

The homepage displays the four supplied source figures from `docs/assets/figures/`:

| Source file | Homepage placement | Display PNG dimensions |
| --- | --- | --- |
| `benchmark_overview_film.pdf` | Introduction and task filmstrips | 3200 × 1688 |
| `benchmark_design.png` | Design: five-stage construction pipeline | 4287 × 2094 |
| `section4_analysis.pdf` | Experimental and diagnostic analyses | 3200 × 1738 |
| `benchmark_diversity.pdf` | Dataset coverage and distributions | 3200 × 1557 |

Each source PDF is preserved byte for byte. Its same-name PNG is a full-page rendering at 3200 pixels wide, with the original aspect ratio, colors, and white canvas. Figures link directly to their original PDFs; `originals.json` records their SHA-256 checksums. Do not crop, redraw, recolor, or restyle the contents of these research figures to match the website theme.

The original design PNG is also preserved byte for byte, including its transparent background. It is displayed on the website's white figure canvas and links directly to the original-resolution image. Its checksum and natural dimensions are verified during CI. The illustrated annotation schema describes the construction process; it is not the evaluation runner's catalog interface. Causal annotations provide privileged diagnostic information; the main video-history evaluation follows its documented visual-input protocol.

The research masthead opens the homepage with the full title, a compact author byline, contribution markers, and official institution marks. Institution names use 22px desktop and 18px mobile text. Original institution assets and their official source URLs are documented in [institution mark sources](assets/institutions/SOURCES.md); the mobile layout uses HKU's standalone shield for clarity.

The analysis figure includes history-length and event-distance breakdowns, information ablations, and paired prediction–traceback outcomes. The annotation ablation uses 151 paired prediction questions with privileged causal information. This diagnostic subset is distinct from the 699-question main leaderboard.

## Publish with GitHub Pages

1. Push the reviewed repository to `ZHAOAlexGoat/EMBER-Bench`.
2. In **Settings > Pages > Build and deployment**, select **GitHub Actions**.
3. Run the **Publish benchmark website** workflow, or push a change under `docs/` to `main`.
4. Check the deployment job and open its reported URL. The expected project URL is `https://zhaoalexgoat.github.io/EMBER-Bench/`.

Only `docs/` is uploaded as the Pages artifact. Evaluation source is accessible through repository links. The workflow validates local links and paper data before publishing.

## Move to another owner

Edit the `owner` and `repository` values in `docs/data/site.json`, update repository and Pages links in the root README, and update the remote with `git remote set-url origin https://github.com/OWNER/EMBER-Bench.git`. Relative page and asset URLs do not need changing. Repository transfer or account renaming is a separate GitHub account operation.

## Validation

```bash
python scripts/validate_site.py
cd evaluation
python -m pytest tests -q
```

Before release, inspect both pages at desktop and mobile widths. Exercise search, source filtering, score sorting, CSV export, keyboard focus, and reduced motion. Confirm the human reference is excluded from model rank and missing data never displays as zero.

## Visual design and motion

The site uses a warm-white base with very pale champagne and ivory light fields, large system sans-serif type, and readable charcoal text. Amber accents connect the interface and conceptual memory scene to the ember/flame identity. Two decorative gradient layers drift slowly behind the content without animated filters. Buttons use at least 16px labels and 44px interaction targets. Both pages share the same continuous EMBER-Bench wordmark and a geometric ember/flame icon with circuit accents.

The navigation labels the design section as **Design**. `common.js` highlights it while the section is being read and returns to Overview outside that section, including native anchor navigation and browser history. The existing `#benchmark` anchor remains compatible with older links.

The Overview's `#authors` block preserves the author order from the supplied OpenReview author list. Aoyang Cai and Boning Zhao share the `*` equal-contribution marker; Zhiwei Yu and Guocai Yao share the `†` corresponding-author marker. Affiliation 1 is Tsinghua University, 2 is The University of Hong Kong, and 3 is Beijing Academy of Artificial Intelligence (BAAI). Shaoxuan Xie's affiliation follows the author-provided correction to BAAI. Keep visible superscripts, their accessible labels, and the affiliation legend synchronized when updating this block.

`docs/assets/js/memory-scene.js` animates the conceptual SVG with layered orbits, three causal signal paths, node activation, and gentle pointer depth. It pauses outside the viewport and while the page is hidden. Reduced motion displays the original static composition. `home.js` progressively reveals content and score bars; the text, figures, and actual score values remain available without JavaScript. Research figure contents must remain unmodified.

The comparison card's third row is the unweighted mean of the 16 non-human models' reported Overall accuracies: `660.3 / 16 = 41.26875%`, displayed as `41.3%`. The validator checks the displayed mean, exact bar percentage, and model count against the leaderboard JSON. Score tracks stay visible; only the fills expand from their left edge. Each fill takes 0.55 seconds, with starts staggered by 0.18 seconds (0, 0.18, and 0.36 seconds), so the three fills finish in approximately 0.91 seconds after the first starts. Reduced motion shows all fills immediately and freezes the decorative gradients.

Design references: [Apple](https://www.apple.com/iphone/) informed the spacious light presentation and restrained motion. [SWE-bench](https://www.swebench.com/), [MMMU](https://mmmu-benchmark.github.io/), and [LongVideoBench](https://longvideobench.github.io/) informed resource navigation, benchmark explanation, and results structure. Styling and memory illustrations are original to this site.
