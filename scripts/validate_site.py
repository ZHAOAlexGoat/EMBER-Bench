"""Dependency-free static link, table, ownership, and paper provenance checks."""
from __future__ import annotations

import hashlib
import csv
from decimal import Decimal
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import struct
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'docs'
COLUMNS = ['overall', 'p_all', 'p_l1', 'p_l2', 'p_l3', 'p_l4', 'c_all', 'c_l2', 'c_l3', 'c_l4']
TABLE_SHA = 'f5097449b88c73f2ca1e5f0daaf3b8e700efc83980eb015e0c5f288d88bd2c31'
PAPER_URL = 'https://arxiv.org/abs/2610.05013'


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.ids, self.links, self.rows = set(), [], []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'):
            if attrs['id'] in self.ids:
                raise ValueError(f"Duplicate HTML id: {attrs['id']}")
            self.ids.add(attrs['id'])
        for key in ('href', 'src'):
            if attrs.get(key):
                self.links.append(attrs[key])
        if attrs.get('srcset'):
            self.links.extend(candidate.strip().split()[0] for candidate in attrs['srcset'].split(',') if candidate.strip())


def main():
    for name in ['index.html', 'leaderboard.html', '.nojekyll', 'data/site.json', 'data/leaderboard.json']:
        assert (SITE / name).is_file(), f'Missing website file: {name}'
    pages = {p.resolve(): Page(p.read_text(encoding='utf-8')) for p in SITE.rglob('*.html')}
    checked = 0
    for path, page in pages.items():
        for value in page.links:
            url = urlsplit(value)
            if url.scheme or url.netloc or value == '#':
                continue
            assert not url.path.startswith('/'), f'Project-path incompatible link in {path.name}: {value}'
            target = (path.parent / unquote(url.path)).resolve() if url.path else path
            assert target.is_relative_to(SITE), f'Link escapes the deployed docs directory: {value}'
            if target.is_dir():
                target = target / 'index.html'
            assert target.is_file(), f'Broken local link in {path.name}: {value}'
            if url.fragment and target in pages:
                assert unquote(url.fragment) in pages[target].ids, f'Broken fragment in {path.name}: {value}'
            checked += 1
    for path in SITE.rglob('*.css'):
        for value in re.findall(r'url\([\"\']?([^\)\"\']+)', path.read_text(encoding='utf-8')):
            if urlsplit(value).scheme or value.startswith('#'):
                continue
            assert (path.parent / unquote(value)).is_file(), f'Broken CSS asset: {value}'

    config = json.loads((SITE / 'data/site.json').read_text(encoding='utf-8'))
    assert config['owner'] == 'ZHAOAlexGoat'
    assert config['repository'] == 'https://github.com/ZHAOAlexGoat/EMBER-Bench'
    data = json.loads((SITE / 'data/leaderboard.json').read_text(encoding='utf-8'))
    rows = data['rows']
    assert len(rows) == 17 and len({r['name'] for r in rows}) == 17
    assert sum(r['category'] == 'human' for r in rows) == 1
    assert sum(r['category'] == 'closed' for r in rows) == 7
    assert sum(r['category'] == 'open' for r in rows) == 9
    for row in rows:
        for key in COLUMNS:
            assert isinstance(row[key], (int, float)) and not isinstance(row[key], bool) and 0 <= row[key] <= 100
    canonical = [{k: row[k] for k in ['name', 'category', *COLUMNS]} for row in sorted(rows, key=lambda r: r['name'])]
    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    assert digest == TABLE_SHA, 'Paper Table 2 differs from the verified 170-value transcription.'
    model_rows = [row for row in rows if row['category'] != 'human']
    model_mean = sum(Decimal(str(row['overall'])) for row in model_rows) / len(model_rows)
    home = (SITE / 'index.html').read_text(encoding='utf-8')
    displayed_mean = re.search(r'<strong id="model-average">([\d.]+)<span>', home)
    average_bar = re.search(r'class="score-row average".*?--value:([\d.]+)%', home, re.S)
    assert displayed_mean and Decimal(displayed_mean.group(1)) == model_mean.quantize(Decimal('0.1')), 'Homepage model average differs from the model-only Overall mean.'
    assert average_bar and Decimal(average_bar.group(1)) == model_mean, 'Homepage average bar differs from the model-only Overall mean.'
    assert f'{len(model_rows)}-model average' in home, 'Homepage average model count is stale.'
    expected = {r['name']: r for r in rows}
    with (SITE / 'data/leaderboard.csv').open(encoding='utf-8', newline='') as stream:
        csv_rows = list(csv.DictReader(stream))
    assert len(csv_rows) == 17 and len({r['model'] for r in csv_rows}) == 17
    for row in csv_rows:
        source = expected[row['model']]
        assert row['category'] == source['category']
        assert all(float(row[key]) == source[key] for key in COLUMNS), 'CSV differs from paper JSON.'
    board = (SITE / 'leaderboard.html').read_text(encoding='utf-8')
    fallback = re.findall(r'<tr\b[^>]*data-name="([^"]+)"[^>]*>(.*?)</tr>', board, re.S)
    assert len(fallback) == 17 and len({name for name, _ in fallback}) == 17
    for name, markup in fallback:
        cells = {key: float(value) for key, value in re.findall(r'<td\b[^>]*data-key="([^"]+)"[^>]*>([\d.]+)</td>', markup)}
        assert cells == {key: expected[html.unescape(name)][key] for key in COLUMNS}, 'Static HTML table differs from paper JSON.'
    assert config.get('paper') == data.get('paper') == PAPER_URL, 'Public paper metadata must point to the approved arXiv preprint.'
    for name in ('index.html', 'leaderboard.html'):
        assert PAPER_URL in pages[(SITE / name).resolve()].links, f'Missing public paper link in {name}.'
    assert f']({PAPER_URL})' in (ROOT / 'README.md').read_text(encoding='utf-8'), 'Missing public paper link in the repository README.'
    assert not (SITE / 'assets/EMBER-Bench.pdf').exists(), 'The local manuscript PDF must not be deployed; use the public arXiv link.'
    provenance = json.loads((SITE / 'assets/figures/originals.json').read_text(encoding='utf-8'))
    originals = provenance['figures']
    expected_figures = {'benchmark_overview_film.pdf', 'benchmark_diversity.pdf', 'section4_analysis.pdf'}
    assert {f['source'] for f in originals} == expected_figures and len(originals) == 3
    published_pdfs = {p.relative_to(SITE).as_posix() for p in SITE.rglob('*.pdf')}
    assert published_pdfs == {'assets/figures/' + name for name in expected_figures}, 'Only approved original figure PDFs may be published.'
    for figure in originals:
        pdf = SITE / 'assets/figures' / figure['source']
        assert hashlib.sha256(pdf.read_bytes()).hexdigest() == figure['pdf_sha256'], f'Original figure PDF changed: {pdf.name}'
        png = (SITE / 'assets/figures' / figure['render']).read_bytes()
        assert png[:8] == b'\x89PNG\r\n\x1a\n'
        assert struct.unpack('>II', png[16:24]) == (figure['width'], figure['height']), 'Figure render dimensions changed.'
    images = provenance['images']
    assert len(images) == 1 and images[0]['source'] == 'benchmark_design.png'
    for figure in images:
        png = (SITE / 'assets/figures' / figure['source']).read_bytes()
        assert hashlib.sha256(png).hexdigest() == figure['sha256'], 'Original design image changed.'
        assert png[:8] == b'\x89PNG\r\n\x1a\n'
        assert struct.unpack('>II', png[16:24]) == (figure['width'], figure['height']), 'Original design image dimensions changed.'
    print(f'PASS: {len(pages)} HTML pages, {checked} local links, owner alignment, 17 rows / 170 paper scores in JSON, CSV and static HTML, model-only Overall mean, public arXiv links and local manuscript exclusion, 3 original figure PDFs/renders, and the original design PNG.')


if __name__ == '__main__':
    main()
