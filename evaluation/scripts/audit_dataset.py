"""Read-only audit of every evaluation video: hashes, streams and full decoding.

Optional contact sheets cover three temporal positions in every video. They are
for human inspection; landscape metadata alone cannot establish an ego viewpoint.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from fractions import Fraction
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import time


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 << 20), b''):
            h.update(block)
    return h.hexdigest()


def local_path(root, relative):
    p = PurePosixPath(relative)
    if p.is_absolute() or '..' in p.parts or '\\' in relative or ':' in relative:
        raise ValueError(f'Unsafe relative media path: {relative}')
    result = root.joinpath(*p.parts).resolve()
    if not result.is_relative_to(root):
        raise ValueError('Media path escapes the dataset')
    return result


def audit(row, index, args):
    path = local_path(args.root, row['history_video'])
    image = local_path(args.root, row['current_frame'])
    stat = path.stat()
    if sha(path) != row['history_sha256'] or sha(image) != row['current_sha256']:
        raise ValueError('History or current-frame SHA256 mismatch')
    probe = subprocess.run([args.ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                           capture_output=True, text=True, encoding='utf-8', timeout=60, check=True)
    metadata = json.loads(probe.stdout)
    video = [s for s in metadata['streams'] if s['codec_type'] == 'video']
    audio = [s for s in metadata['streams'] if s['codec_type'] == 'audio']
    if len(video) != 1 or audio:
        raise ValueError(f'Expected 1 video stream and no audio: {len(video)} video, {len(audio)} audio')
    v = video[0]
    rotations = [float(s.get('rotation', 0)) for s in v.get('side_data_list', [])]
    rotations.append(float(v.get('tags', {}).get('rotate', 0)))
    if any(abs(r % 360) > 0.001 for r in rotations) or v['width'] <= v['height']:
        raise ValueError('Portrait dimensions or nonzero display rotation')
    rate = Fraction(v['avg_frame_rate'])
    if rate != 5:
        raise ValueError(f'Prepared history must be 5 Hz, got {rate}')
    decoded = subprocess.run([args.ffmpeg, '-nostdin', '-hide_banner', '-v', 'error', '-xerror',
                              '-err_detect', 'explode', '-threads', '1', '-i', str(path), '-map', '0:v:0',
                              '-an', '-fps_mode', 'passthrough', '-progress', 'pipe:1', '-f', 'null', '-'],
                             capture_output=True, text=True, encoding='utf-8', timeout=900)
    if decoded.returncode or decoded.stderr.strip():
        raise ValueError('Full decode failed: ' + decoded.stderr[-1500:])
    progress = dict(line.split('=', 1) for line in decoded.stdout.splitlines() if '=' in line)
    n = int(progress.get('frame', 0))
    if progress.get('progress') != 'end' or n <= 0:
        raise ValueError('Decode did not reach the end')
    if v.get('nb_frames') not in (None, 'N/A') and n != int(v['nb_frames']):
        raise ValueError(f'Frame count differs from container: {n} vs {v["nb_frames"]}')
    duration = float(v.get('duration') or metadata['format']['duration'])
    if abs(n / float(rate) - duration) > 0.21:
        raise ValueError('Decoded frame duration differs from container')
    preview = None
    if args.contact_sheets:
        import cv2
        from PIL import Image, ImageDraw
        cap = cv2.VideoCapture(str(path))
        canvas = Image.new('RGB', (576, 136), 'white')
        draw = ImageDraw.Draw(canvas)
        draw.text((3, 3), f'{index:03d}  {row["question_id"]}', fill='black')
        positions = [min(n - 1, int(n * t)) for t in (0.1, 0.5, 0.9)]
        for j, frame in enumerate(positions):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
            ok, pixels = cap.read()
            if not ok:
                raise ValueError(f'Cannot read review frame {frame}')
            thumb = Image.fromarray(cv2.cvtColor(pixels, cv2.COLOR_BGR2RGB))
            thumb.thumbnail((190, 108))
            canvas.paste(thumb, (j * 192 + (192 - thumb.width) // 2, 25 + (108 - thumb.height) // 2))
        cap.release()
        preview = args.out / 'strips' / f'{index:03d}.jpg'
        preview.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(preview, quality=90)
    after = path.stat()
    if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('Video changed during read-only audit')
    return dict(index=index, question_id=row['question_id'], level=row['level'], qa_type=row['qa_type'],
                history_video=row['history_video'], history_sha256=row['history_sha256'],
                current_frame=row['current_frame'], current_sha256=row['current_sha256'],
                bytes=after.st_size, width=v['width'], height=v['height'], fps=str(rate),
                sample_aspect_ratio=v.get('sample_aspect_ratio'), rotations=rotations,
                audio_streams=0, decoded_frames=n, duration_seconds=duration, full_decode='PASS',
                codec=v['codec_name'], review_strip=str(preview) if preview else None)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--ffprobe', default=shutil.which('ffprobe'))
    p.add_argument('--ffmpeg', default=shutil.which('ffmpeg'))
    p.add_argument('--workers', type=int, default=4)
    p.add_argument('--contact-sheets', action='store_true')
    args = p.parse_args()
    args.root = args.root.resolve()
    args.out = args.out.resolve()
    if not args.ffmpeg:
        import imageio_ffmpeg
        args.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    if not args.ffprobe:
        p.error('Install FFmpeg/ffprobe or supply --ffprobe /path/to/ffprobe')
    if not 1 <= args.workers <= 16:
        p.error('--workers must be 1–16')
    index_path = args.root / 'catalog.json'
    if not index_path.exists():
        index_path = args.root / 'evaluation/media_index.json'
    rows = json.loads(index_path.read_text(encoding='utf-8'))
    if len({r['question_id'] for r in rows}) != len(rows):
        p.error('Duplicate question IDs')
    args.out.mkdir(parents=True, exist_ok=True)
    started = time.time()
    records, failures = [], []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(audit, r, i, args): r for i, r in enumerate(rows)}
        for f in as_completed(futures):
            try:
                records.append(f.result())
            except Exception as exc:
                failures.append(dict(question_id=futures[f]['question_id'], error=str(exc)))
                print(json.dumps(failures[-1]), flush=True)
            done = len(records) + len(failures)
            if done % 25 == 0:
                print(f'AUDIT {done}/{len(rows)} errors={len(failures)}', flush=True)
    records.sort(key=lambda r:r['index'])
    pages = []
    if args.contact_sheets:
        from PIL import Image
        for start in range(0, len(records), 21):
            canvas = Image.new('RGB', (1728, 952), '#e5e5e5')
            group = records[start:start+21]
            for n, r in enumerate(group):
                with Image.open(r['review_strip']) as strip:
                    canvas.paste(strip, ((n % 3)*576, (n // 3)*136))
            page = args.out / f'contact_{start//21:02d}.jpg'
            canvas.save(page, quality=93)
            pages.append(dict(path=str(page), questions=[r['question_id'] for r in group]))
    summary = dict(status='PASS' if not failures else 'FAIL', videos=len(records), expected=len(rows),
                   total_decoded_frames=sum(r['decoded_frames'] for r in records),
                   audio_streams=sum(r['audio_streams'] for r in records),
                   geometry=dict(Counter(f'{r["width"]}x{r["height"]}' for r in records)),
                   failures=len(failures), elapsed_seconds=round(time.time()-started, 2))
    report = dict(schema='ember-video-audit-v1', root=str(args.root), index_sha256=sha(index_path),
                  summary=summary, files=records, failures=failures, contact_pages=pages,
                  visual_review='pending; contact sheets do not automatically establish ego viewpoint')
    (args.out/'video_audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(summary), flush=True)
    raise SystemExit(bool(failures))


if __name__ == '__main__':
    main()
