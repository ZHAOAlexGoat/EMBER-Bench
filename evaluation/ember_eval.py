# -*- coding: utf-8 -*-
"""EMBER-Bench unified evaluator.

One prompt, one media pipeline, one answer parser and one retry ladder for every model.
Endpoints (configs/models.json) differ only in wire format (chat / gemini / responses) and auth.

Per question: try the history video at 5 Hz; if the request fails for a non-transient reason
(input too long, too many frames, refusal, invalid answer, ...) retry once at 3 Hz, then at 1 Hz.
The first valid answer is kept; selection never looks at correctness. Unanswered = wrong.

Conditions:
  V1M0      main input condition: video + current frame (unified runner, default)
  V0M0      current frame only (P items)
  V1M3      video + current frame + action log (memory context)
  V1M3C     V1M3 + accident cause annotations (ablation)
  V1M3CC    V1M3 + cause + consequence annotations (ablation)
  CoT       V1M0 + causal chain-of-thought guidance (§4.4)

Usage:
  python ember_eval.py --catalog catalog.json --models qwen3.8-flash gemini-3.8-flash --out runs/demo
  python ember_eval.py --catalog catalog.json --models all --condition V0M0 --out runs/v0
  python ember_eval.py --catalog catalog.json --out runs/demo --summarize
Keys: environment variables named by key_env in configs/models.json (e.g. DASHSCOPE_API_KEY).
This runner is not an exact reproduction of the frozen paper Table 2 settings.
"""
import argparse, ast, base64, hashlib, json, os, re, shutil, subprocess, sys, tempfile, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / 'configs' / 'models.json'
CFG = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
DEF = CFG['defaults']
LOCK, GATE = threading.Lock(), threading.Lock()
TLS = threading.local()
STATE = {'next_post': 0.0, 'cooldown': 0.0}
TRANSIENT_TRIES = 3            # network/429/5xx retries inside one fps stage (do not advance the ladder)
NA_STEM = 'What is the most likely next action to perform?'
CB_STEM = 'Which marked historical segment contains the core incident that made this next action necessary?'


# ---------------------------------------------------------------- utilities
def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def secrets():
    return [os.environ[e['key_env']] for e in CFG['endpoints'].values() if os.environ.get(e['key_env'])]


def clean(text):
    text = str(text)
    for s in secrets():
        text = text.replace(s, '[REDACTED]')
    return text


def redact_tree(value):
    if isinstance(value, str):
        return clean(value)
    if isinstance(value, list):
        return [redact_tree(v) for v in value]
    if isinstance(value, dict):
        return {k: redact_tree(v) for k, v in value.items()}
    return value


def session():
    if not hasattr(TLS, 's'):
        TLS.s = requests.Session()
    return TLS.s


def b64(path):
    return base64.b64encode(Path(path).read_bytes()).decode('ascii')


def image_mime(path):
    """Use file bytes, not a guessed JPEG label, for the decision image."""
    with Path(path).open('rb') as stream:
        header = stream.read(12)
    if header.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if header.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if header.startswith(b'RIFF') and header[8:12] == b'WEBP':
        return 'image/webp'
    if header.startswith((b'GIF87a', b'GIF89a')):
        return 'image/gif'
    raise ValueError('decision image must be JPEG, PNG, WebP, or GIF (provider support may vary)')


def options(item):
    """Read JSON arrays and legacy Python list literals without executing code."""
    o = item.get('options')
    if isinstance(o, str):
        if len(o) > 100_000:
            raise ValueError('options literal is too large')
        try:
            o = json.loads(o)
        except ValueError:
            try:
                o = ast.literal_eval(o)
            except (ValueError, SyntaxError, RecursionError) as exc:
                raise ValueError('options must be a list of four strings') from exc
    if not isinstance(o, (list, tuple)) or len(o) != 4 or not all(isinstance(v, str) and v.strip() for v in o):
        raise ValueError('options must contain exactly four nonempty strings')
    return list(o)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def validate_config(cfg):
    """Fail before transport on malformed configuration and unsafe output names."""
    for section in ('defaults', 'endpoints', 'models'):
        if not isinstance(cfg.get(section), dict) or not cfg[section]:
            raise ValueError(f'config requires a nonempty {section} object')
    defaults = cfg['defaults']
    ladder = defaults.get('fps_ladder')
    if (not isinstance(ladder, list) or not ladder or
            any(type(v) is not int or v <= 0 for v in ladder) or
            ladder != sorted(set(ladder), reverse=True)):
        raise ValueError('fps_ladder must contain distinct positive integers in descending order')
    for k in ('max_output_tokens', 'timeout_s'):
        if not isinstance(defaults.get(k), (int, float)) or defaults[k] <= 0:
            raise ValueError(f'defaults.{k} must be positive')
    if not isinstance(defaults.get('temperature'), (int, float)):
        raise ValueError('defaults.temperature must be numeric')
    for name, ep in cfg['endpoints'].items():
        if not isinstance(ep, dict) or ep.get('protocol') not in ('chat', 'gemini', 'responses'):
            raise ValueError(f'endpoint {name}: unknown protocol')
        url = urlparse(ep.get('base_url', ''))
        if not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError(f'endpoint {name}: base_url must not contain credentials/query/fragment')
        if url.scheme != 'https' and not (url.scheme == 'http' and url.hostname in ('127.0.0.1', 'localhost', '::1')):
            raise ValueError(f'endpoint {name}: use HTTPS, or loopback HTTP for local tests')
        if not re.fullmatch(r'[A-Z_][A-Z0-9_]*', ep.get('key_env', '')):
            raise ValueError(f'endpoint {name}: invalid key_env')
        for k in ('max_images', 'base64_max_bytes'):
            if k in ep and (type(ep[k]) is not int or ep[k] <= 0):
                raise ValueError(f'endpoint {name}: {k} must be a positive integer')
        if ep.get('input_mode', 'video') not in ('video', 'frames'):
            raise ValueError(f'endpoint {name}: input_mode must be video or frames')
        if ep.get('input_mode') == 'frames' and ep['protocol'] == 'gemini':
            raise ValueError(f'endpoint {name}: Gemini uses native video input')
    for model, entry in cfg['models'].items():
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', model) or model in ('.', '..'):
            raise ValueError(f'unsafe model id: {model!r}; use a simple id and optional api_model')
        if not isinstance(entry, dict) or entry.get('endpoint') not in cfg['endpoints'] or not entry.get('name'):
            raise ValueError(f'model {model}: missing name or endpoint')


def write_json(path, value):
    """Replace metadata atomically so an interrupted write cannot corrupt a run."""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, path)


# ---------------------------------------------------------------- prompt (identical for all models)
def prompt(item, cond):
    task = item.get('objective') or item.get('task_name_zh') or ''
    if item['qa_type'] == 'NA':
        opts = '\n'.join(f'{k}. {v}' for k, v in zip('ABCD', options(item)))
        if cond == 'V0M0':
            tail = ('Do not write a chain of thought, explanation, or markdown.\n'
                    'Output exactly one line and nothing else:\nFinal Answer: [A/B/C/D]')
            return (f'Task instruction: {task}\nQuestion: {NA_STEM}\n{opts}\n\n'
                    'Choose the best next action based on the task and the current image.\n' + tail)
        mem_text = item.get('m3_text') or ''
        if cond in ('V1M3C', 'V1M3CC'):
            anns = item.get('incidents') or []
            fields = 'accident cause and consequence' if cond == 'V1M3CC' else 'accident cause'
            omit = ('Anomaly stage and obligation fields are omitted.' if cond == 'V1M3CC'
                    else 'Anomaly stage, obligation, and consequence fields are omitted.')
            if anns:
                block = [{'subtask': a['subtask'], 'action': a['action'],
                          'accident_cause': a.get('accident_cause') or '(not annotated)',
                          **(({'accident_consequence': a.get('accident_consequence') or '(not annotated)'}
                             if cond == 'V1M3CC' else {}))}
                         for a in anns]
                ann_block = f'\n\nincident_annotations ({fields}):\n' + json.dumps(block, ensure_ascii=False, indent=2)
            else:
                ann_block = (f'\n\nincident_annotations ({fields}):\n[]  '
                             '(no incident was annotated in the completed subtasks)')
            mem_text = mem_text + ann_block
            omit += (f' Annotated {fields} for incidents in these completed subtasks are listed after the log.')
            log_note = (f'The action log contains only completed subtasks before the decision. '
                        f'Incident annotations ({fields}) refer only to those completed subtasks; '
                        'they do not state the next action.')
        else:
            omit = None
            log_note = ('If an action log is provided, it contains only completed subtasks before the decision and '
                        'does not include privileged anomaly fields.')
        mem = '\n\n' + mem_text if mem_text and cond in ('V1M3', 'V1M3C', 'V1M3CC') else ''
        if cond == 'CoT':
            tail = ('Before choosing, briefly state whether any observed event disrupted task execution and what '
                    'effect, if any, still matters for the current decision. Do not assume a disruption occurred '
                    'or remains unresolved. Then select the next action.\n'
                    'Output exactly two lines, without markdown:\n'
                    'Assessment: <at most two sentences and 60 words>\nFinal Answer: [A/B/C/D]')
        else:
            tail = ('Do not write a chain of thought, explanation, or markdown.\n'
                    'Output exactly one line and nothing else:\nFinal Answer: [A/B/C/D]')
        base = (f'Task instruction: {task}\nQuestion: {NA_STEM}\n{opts}\n{mem}\n\n'
                'The history video is a uniformly sampled visual prefix up to the decision moment, followed by '
                f'the current decision frame. Use both the video and the current frame.\n{log_note}\n' + tail)
        if omit:
            base = base.replace('Anomaly stage, obligation, cause, and consequence fields are omitted.', omit)
            base = base.replace('If an action log is provided, it contains only completed subtasks before the '
                                'decision and does not include privileged anomaly fields.', log_note)
        return base
    mem = ''
    if cond in ('V1M3', 'V1M3C', 'V1M3CC'):
        labels = item.get('option_labels') or {}
        lab = '\n'.join(f"Option {k}: {labels.get(k) or '(unlabeled interval)'}" for k in 'ABCD')
        mem = ('\n\nMarked option text labels (these describe the historical interval marked OPTION A–D in the '
               'video):\n' + lab + '\n\n' + (item.get('m3_text') or ''))
    ev = ''.join(f'{k}. The event shown while OPTION {k} appears in the history video.\n' for k in 'ABCD')
    tail = ('Do not write a chain of thought, explanation, or markdown.\n'
            'Output exactly one line and nothing else:\nFinal Answer: [A/B/C/D]')
    return (f"Task instruction: {task}\nThe next action is: \"{item.get('known_action') or ''}\"\n"
            f'Question: {CB_STEM}\n{ev}{mem}\n\n'
            'Each on-screen label OPTION A–D identifies one candidate historical interval.\n'
            'Select the marked segment that contains the core incident that made this next action necessary.\n'
            + tail)


def intro(item, fps, cond):
    if cond == 'V0M0':
        return 'Current frame at the decision moment.'
    if item['qa_type'] == 'NA':
        if cond == 'CoT':
            return (f'History video at {fps} fps, uniformly sampled from the start up to the decision moment; '
                    'then the current frame at the decision moment.')
        return (f'History video at {fps} fps, uniformly sampled from the start up to the decision moment; '
                'then the current frame at the decision moment.')
    return (f'History video at {fps} fps with OPTION A–D labels, ending before the known action; '
            'then the current frame at the decision moment.')


def parse_answer(raw, item=None):
    raw = str(raw or '')
    markers = re.findall(r'Final\s+Answer\s*:', raw, re.I)
    hits = re.findall(r'^\s*[#*` ]*Final\s+Answer\s*:[*` ]*(?:\[\s*([ABCD])\s*\]|([ABCD]))[.*` ]*\s*$',
                      raw, re.I | re.M)
    hits = [(a or b) for a, b in hits]
    if markers:
        # An echoed [A/B/C/D] template or a multi-choice answer is invalid;
        # never take the first letter of an ambiguous response.
        if len(hits) != len(markers):
            return ''
        return hits[-1].upper() if len({h.upper() for h in hits}) == 1 else ''
    lines = [s.strip() for s in raw.strip().splitlines() if s.strip()]
    if not lines:
        return ''
    m = re.fullmatch(r'[#*`\s]*\[?([ABCD])\]?[.#*`\s]*', lines[-1], re.I)
    if m:
        return m.group(1).upper()
    m = re.fullmatch(r'([A-D])\.\s+(.+)', lines[-1])          # "B. <exact option text>"
    norm = lambda x: ' '.join(str(x).split()).casefold()
    if m and item is not None and item['qa_type'] == 'NA' and norm(m[2]) == norm(options(item)['ABCD'.index(m[1])]):
        return m[1]
    return ''


assert parse_answer('### Final Answer: D') == 'D' and parse_answer('**Final Answer:** C') == 'C'
assert parse_answer('Final Answer: [B]') == 'B' and parse_answer('A') == 'A'
assert parse_answer('Final Answer: A\nFinal Answer: B') == ''


# ---------------------------------------------------------------- media (same for all models)
FFMPEG = shutil.which('ffmpeg')
if not FFMPEG:
    try:
        import imageio_ffmpeg
        FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        FFMPEG = None


def ffmpeg(args):
    if not FFMPEG:
        raise RuntimeError('ffmpeg not found (install ffmpeg or pip install imageio-ffmpeg)')
    p = subprocess.run([FFMPEG, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', *args],
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=600)
    if p.returncode:
        raise RuntimeError('ffmpeg: ' + p.stderr.decode('utf-8', 'replace')[:400])


MEDIA_LOCKS = {}


def media_lock(path):
    with LOCK:
        return MEDIA_LOCKS.setdefault(str(path), threading.Lock())


def video_at(src, src_sha, fps, cache):
    """History video resampled to `fps` (cached). Uniform temporal sampling, audio dropped."""
    out = cache / f'{src_sha[:16]}_{fps}hz.mp4'
    with media_lock(out):
        if not out.exists():
            tmp = out.with_suffix('.tmp.mp4')
            ffmpeg(['-i', str(src), '-vf', f'fps={fps}', '-an', '-c:v', 'libx264', '-preset', 'veryfast',
                    '-crf', '23', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(tmp)])
            os.replace(tmp, out)
    return out


def frames_at(src, src_sha, fps, cache):
    """Same resampled history as JPEG frames, for endpoints without video input."""
    d = cache / f'{src_sha[:16]}_{fps}hz_frames'
    with media_lock(d):
        if not (d / 'done').exists():
            shutil.rmtree(d, ignore_errors=True)
            tmp = Path(tempfile.mkdtemp(dir=cache))
            ffmpeg(['-i', str(src), '-vf', f'fps={fps}', '-q:v', '4', str(tmp / 'f_%05d.jpg')])
            (tmp / 'done').write_text('ok')
            os.replace(tmp, d)
    files = sorted(d.glob('f_*.jpg'))
    if not files:
        raise RuntimeError('ffmpeg produced zero frames')
    return files


def duration(path):
    """Seconds, from ffmpeg's stream header (no cv2 dependency)."""
    if not FFMPEG:
        raise RuntimeError('ffmpeg not found')
    p = subprocess.run([FFMPEG, '-nostdin', '-hide_banner', '-i', str(path)],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    m = re.search(rb'Duration: (\d+):(\d+):([\d.]+)', p.stderr)
    if not m:
        raise RuntimeError('cannot read video duration')
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])


# ---------------------------------------------------------------- endpoints (wire format only)
def endpoint_url(ep):
    url = (os.environ.get(ep.get('base_url_env', '')) or ep['base_url']).rstrip('/')
    # Apply the same transport safety checks to overrides as to the registry.
    overridden = {**ep, 'base_url': url}
    validate_config({'defaults': DEF, 'endpoints': {'endpoint': overridden},
                     'models': {'check': {'name': 'check', 'endpoint': 'endpoint'}}})
    return url


def key_for(ep):
    k = os.environ.get(ep['key_env'])
    if not k:
        raise SystemExit(f"missing environment variable {ep['key_env']}")
    return k


def dashscope_upload(model, path, key):
    """Private temporary OSS upload for videos too large for base64 (DashScope only)."""
    pol = session().get('https://dashscope.aliyuncs.com/api/v1/uploads', params={'action': 'getPolicy', 'model': model},
                        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
                        timeout=(20, 60))
    pol.raise_for_status()
    d = pol.json()['data']
    obj = d['upload_dir'].rstrip('/') + '/' + Path(path).name
    form = {'OSSAccessKeyId': d['oss_access_key_id'], 'Signature': d['signature'], 'policy': d['policy'],
            'x-oss-object-acl': d.get('x_oss_object_acl', 'private'),
            'x-oss-forbid-overwrite': d.get('x_oss_forbid_overwrite', 'true'), 'key': obj,
            'success_action_status': '200'}
    with Path(path).open('rb') as f:
        up = session().post(d['upload_host'], data=form, files={'file': (Path(path).name, f, 'video/mp4')},
                            timeout=(30, 180))
    up.raise_for_status()
    return 'oss://' + obj


def request_chat(model, ep, key, parts_in):
    parts, headers = [], {'Authorization': f'Bearer {key}'}
    for kind, val, fps in parts_in:
        if kind == 'text':
            parts.append({'type': 'text', 'text': val})
        elif kind == 'image':
            parts.append({'type': 'image_url', 'image_url': {'url': 'data:' + image_mime(val) + ';base64,' + b64(val)}})
        elif kind == 'frames':
            for frame in val:
                parts.append({'type': 'image_url', 'image_url': {
                    'url': 'data:' + image_mime(frame) + ';base64,' + b64(frame)}})
        else:
            if Path(val).stat().st_size <= ep.get('base64_max_bytes', 1 << 62):
                url = 'data:video/mp4;base64,' + b64(val)
            elif ep.get('upload') == 'dashscope_oss':
                url = dashscope_upload(model, val, key)
                headers['X-DashScope-OssResourceResolve'] = 'enable'
            else:
                raise RuntimeError('video exceeds base64_max_bytes')
            p = {'type': 'video_url', 'video_url': {'url': url}}
            if ep.get('video_fps_field') == 'part':
                p['fps'] = fps
            elif ep.get('video_fps_field') == 'video_url':
                p['video_url']['fps'] = fps
            parts.append(p)
    body = {'model': model, 'messages': [{'role': 'user', 'content': parts}], 'temperature': DEF['temperature'],
            ep.get('token_field', 'max_tokens'): DEF['max_output_tokens'], **ep.get('extra_body', {})}
    r = session().post(endpoint_url(ep) + '/chat/completions', json=body, headers=headers,
                       timeout=(30, DEF['timeout_s']))
    if r.status_code != 200:
        error = dict(http_status=r.status_code, api_error=f'HTTP {r.status_code}: {clean(r.text[:800])}')
        r.close()
        return error
    d = r.json()
    ch = (d.get('choices') or [{}])[0]
    raw = (ch.get('message') or {}).get('content') or ''
    if isinstance(raw, list):
        raw = ''.join(x.get('text', '') for x in raw if isinstance(x, dict))
    return dict(http_status=200, raw_text=raw, finish_reason=ch.get('finish_reason'),
                response_model=d.get('model'), usage=d.get('usage') or {}, request_id=d.get('id'),
                api_error='' if d.get('choices') else 'no_choices')


def request_gemini(model, ep, key, parts_in):
    parts = []
    for kind, val, fps in parts_in:
        if kind == 'text':
            parts.append({'text': val})
        else:
            if Path(val).stat().st_size > ep.get('base64_max_bytes', 1 << 62):
                raise RuntimeError('media exceeds base64_max_bytes')
            mime = image_mime(val) if kind == 'image' else 'video/mp4'
            parts.append({'inline_data': {'mime_type': mime, 'data': b64(val)}})
            if kind == 'video':
                parts[-1]['videoMetadata'] = {'fps': fps}
    body = {'contents': [{'role': 'user', 'parts': parts}],
            'generationConfig': {'temperature': DEF['temperature'], 'maxOutputTokens': DEF['max_output_tokens'],
                                 **ep.get('extra_generation_config', {})}}
    r = session().post(f'{endpoint_url(ep)}/models/{quote(model, safe="")}:generateContent', json=body,
                       headers={'x-goog-api-key': key}, timeout=(30, DEF['timeout_s']))
    if r.status_code != 200:
        return dict(http_status=r.status_code, api_error=f'HTTP {r.status_code}: {clean(r.text[:800])}')
    d = r.json()
    c = (d.get('candidates') or [{}])[0]
    raw = ''.join(p.get('text', '') for p in (c.get('content') or {}).get('parts', []) if not p.get('thought'))
    err = '' if d.get('candidates') else 'no_candidates: ' + clean(json.dumps(d.get('promptFeedback') or {}))
    return dict(http_status=200, raw_text=raw, finish_reason=c.get('finishReason'),
                response_model=d.get('modelVersion'), usage=d.get('usageMetadata') or {},
                request_id=d.get('responseId'), api_error=err)


def request_responses(model, ep, key, parts_in):
    content = []
    for kind, val, fps in parts_in:
        if kind == 'text':
            content.append({'type': 'input_text', 'text': val})
        else:                                   # 'image' or a list of history frames
            for f in (val if isinstance(val, list) else [val]):
                content.append({'type': 'input_image', 'image_url': 'data:' + image_mime(f) + ';base64,' + b64(f)})
    body = {'model': model, 'input': [{'role': 'user', 'content': content}],
            'max_output_tokens': DEF['max_output_tokens'], 'stream': True, 'store': False, **ep.get('extra_body', {})}
    r = session().post(endpoint_url(ep) + '/responses', json=body, headers={'Authorization': f'Bearer {key}'},
                       stream=True, timeout=(30, DEF['timeout_s']))
    if r.status_code != 200:
        error = dict(http_status=r.status_code, api_error=f'HTTP {r.status_code}: {clean(r.text[:800])}')
        r.close()
        return error
    text, done, fail = [], {}, ''
    try:
        for line in r.iter_lines():
            line = line.decode('utf-8', 'replace').strip()
            if not line.startswith('data: ') or line[6:] == '[DONE]':
                continue
            try:
                ev = json.loads(line[6:])
            except ValueError:
                continue
            if ev.get('type') == 'response.output_text.delta':
                text.append(ev.get('delta') or '')
            elif ev.get('type') == 'response.completed':
                done = ev.get('response') or {}
            elif ev.get('type') in ('response.failed', 'error', 'response.incomplete'):
                fail = clean(str(ev.get('message') or ev)[:500])
    finally:
        r.close()
    raw = ''.join(text) or ''.join(p.get('text', '') for o in done.get('output') or []
                                   for p in o.get('content') or [] if p.get('type') == 'output_text')
    return dict(http_status=200, raw_text=raw, finish_reason=done.get('status'), response_model=done.get('model'),
                usage=done.get('usage') or {}, request_id=done.get('id'), api_error=fail)


PROTOCOLS = {'chat': request_chat, 'gemini': request_gemini, 'responses': request_responses}
OK_FINISH = {'stop', 'end_turn', 'completed'}


# ---------------------------------------------------------------- one attempt
def attempt(model, item, cond, fps, stage, tries, cache, args):
    ep = CFG['endpoints'][CFG['models'][model]['endpoint']]
    text = prompt(item, cond)
    row = dict(model=model, question_id=item['question_id'], level=item['level'], qa_type=item['qa_type'],
               condition=cond, gold=item['gold'], stage=stage, fps=fps if cond != 'V0M0' else None, tries=tries,
               prompt_sha256=hashlib.sha256(text.encode()).hexdigest(), started_at=time.time())
    t0 = time.monotonic()
    try:
        frame = Path(item['current_frame'])
        if args.verify_sha and sha(frame) != item['current_sha256']:
            raise RuntimeError('frozen media SHA-256 mismatch (current frame)')
        if cond == 'V0M0':
            parts = [('text', intro(item, None, cond), None), ('image', frame, None), ('text', text, None)]
        else:
            src = Path(item['history_video'])
            if args.verify_sha and sha(src) != item['history_sha256']:
                raise RuntimeError('frozen media SHA-256 mismatch (history video)')
            n = int(duration(src) * fps) + 2                           # history frames + current frame
            row['n_frames'] = n
            if n > ep.get('max_images', 1 << 62):
                raise RuntimeError(f'too_many_frames: {n} > {ep["max_images"]}')
            if ep['protocol'] == 'responses' or ep.get('input_mode') == 'frames':
                source_sha = item['history_sha256'] if args.verify_sha else sha(src)
                hist = frames_at(src, source_sha, fps, cache)
                row['n_frames'] = len(hist) + 1
                if len(hist) + 1 > ep.get('max_images', 1 << 62):
                    raise RuntimeError(f'too_many_frames: {len(hist) + 1} > {ep["max_images"]}')
                media = ('frames', hist, fps)
            else:
                source_sha = item['history_sha256'] if args.verify_sha else sha(src)
                media = ('video', video_at(src, source_sha, fps, cache), fps)
                row['media_sha256'] = sha(media[1])
            parts = [('text', intro(item, fps, cond), None), media, ('text', 'Current frame at the decision moment:', None),
                     ('image', frame, None), ('text', text, None)]
        with GATE:                                                    # optional pacing + 429 cooldown
            wait = max(STATE['next_post'], STATE['cooldown']) - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            STATE['next_post'] = time.monotonic() + args.min_interval
        api_model = CFG['models'][model].get('api_model') or model
        row.update(PROTOCOLS[ep['protocol']](api_model, ep, key_for(ep), parts))
    except requests.RequestException as e:
        row['api_error'] = 'network: ' + type(e).__name__ + ': ' + clean(str(e))[:500]
    except Exception as e:                                        # oversize media, bad JSON, ffmpeg, ...
        row['api_error'] = type(e).__name__ + ': ' + clean(str(e))[:800]
    raw, err = row.get('raw_text', ''), row.get('api_error', '')
    if not err and str(row.get('finish_reason')).lower() not in OK_FINISH:
        err = f"finish_reason={row.get('finish_reason')}"
    if not err and not str(raw).strip():
        err = 'empty_response'
    pred = parse_answer(raw, item) if not err else ''
    if not err and not pred:
        err = 'invalid_answer_format'
    row.update(api_error=err, prediction=pred, valid_answer=bool(pred and not err),
               is_correct=bool(pred and not err and pred == item['gold']),
               latency_sec=round(time.monotonic() - t0, 2), finished_at=time.time())
    return redact_tree(row)


def kind(row):
    e, h = row.get('api_error', '').lower(), row.get('http_status')
    if h in (401, 402, 403) or 'freetieronly' in e:
        return 'fatal'
    if e.startswith('network:') or h == 429 or (h or 0) >= 500 or 'throttl' in e or 'ratelimit' in e:
        return 'transient'
    return 'ok' if row.get('valid_answer') else 'next_fps'


def item_complete(rows, ladder):
    """A valid answer or exhausted nonfatal retries completes a question."""
    if any(row.get('valid_answer') for row in rows):
        return True
    for stage, _ in enumerate(ladder, 1):
        done = [row for row in rows if row['stage'] == stage and kind(row) != 'fatal']
        if not any(kind(row) == 'next_fps' for row in done) and len(done) < TRANSIENT_TRIES:
            return False
    return True


# ---------------------------------------------------------------- run one model with resume
def load(path):
    if not path.exists():
        return []
    rows = []
    for line_no, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if line.strip():
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise ValueError(f'{path}:{line_no}: malformed journal; preserve a backup before repairing a partial line') from exc
            if not isinstance(row, dict):
                raise ValueError(f'{path}:{line_no}: journal row must be an object')
            rows.append(row)
    return rows


def run_identity(model, catalog, args):
    return dict(protocol='unified-runner', model=model, condition=args.condition,
                catalog_sha256=sha(args.catalog), selected_catalog_sha256=digest(catalog),
                code_sha256=sha(__file__), config_sha256=sha(CONFIG_PATH),
                effective_config_sha256=digest(CFG),
                endpoint_url=endpoint_url(CFG['endpoints'][CFG['models'][model]['endpoint']]),
                verify_sha=args.verify_sha, synthetic=bool(CFG.get('_synthetic', False)))


def ensure_manifest(model, catalog, out, args):
    identity = run_identity(model, catalog, args)
    path = out / 'manifest.json'
    if path.exists():
        manifest = json.loads(path.read_text(encoding='utf-8'))
        if manifest.get('identity') != identity:
            raise ValueError('run identity changed; use a new --out directory (catalog/subset/config/code/condition/media verification must match)')
        return manifest
    if (out / 'attempts.jsonl').exists():
        raise ValueError('attempt journal has no manifest; use a new --out directory rather than mixing unverified legacy logs')
    manifest = dict(identity=identity, n_items=len(catalog), defaults=DEF,
                    transient_tries=TRANSIENT_TRIES, workers=args.workers, started_at=time.time(),
                    question_ids=[it['question_id'] for it in catalog])
    write_json(path, manifest)
    return manifest


def validate_attempts(rows, model, catalog, cond):
    """Reject stale/mixed logs and recompute validity rather than trusting a flag."""
    items = {it['question_id']: it for it in catalog}
    ladder = [None] if cond == 'V0M0' else DEF['fps_ladder']
    for row in rows:
        item = items.get(row.get('question_id'))
        if item is None:
            raise ValueError('journal contains questions outside the selected catalog')
        for k, expected in (('model', model), ('condition', cond), ('gold', item['gold']),
                            ('level', item['level']), ('qa_type', item['qa_type'])):
            if row.get(k) != expected:
                raise ValueError(f'journal mismatch for {item["question_id"]}: {k}')
        stage, tries = row.get('stage'), row.get('tries')
        if type(stage) is not int or not 1 <= stage <= len(ladder) or type(tries) is not int or not 1 <= tries <= TRANSIENT_TRIES:
            raise ValueError('journal stage/tries outside the configured retry ladder')
        if row.get('fps') != ladder[stage - 1] or row.get('prompt_sha256') != hashlib.sha256(prompt(item, cond).encode()).hexdigest():
            raise ValueError('journal fps or prompt hash mismatch')
        prediction = parse_answer(row.get('raw_text', ''), item)
        valid = bool(not row.get('api_error') and row.get('http_status') == 200 and prediction and
                     str(row.get('finish_reason')).lower() in OK_FINISH)
        if bool(row.get('valid_answer')) != valid or row.get('prediction', '') != (prediction if valid else ''):
            raise ValueError('journal prediction/validity is inconsistent with its raw response')
    return rows


def run_model(model, catalog, args):
    out = Path(args.out) / args.condition / model
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(args.out) / '_media_cache'
    cache.mkdir(parents=True, exist_ok=True)
    log = out / 'attempts.jsonl'
    ensure_manifest(model, catalog, out, args)
    ladder = [None] if args.condition == 'V0M0' else DEF['fps_ladder']
    hist = {}
    for r in validate_attempts(load(log), model, catalog, args.condition):
        hist.setdefault(r['question_id'], []).append(r)
    halt = threading.Event()

    def job(item):
        rows = hist.get(item['question_id'], [])
        if any(r['valid_answer'] for r in rows):
            return
        for stage, fps in enumerate(ladder, 1):
            # Authorization/quota failures do not consume the stage retry budget:
            # fixing credentials and rerunning must actually resume this item.
            done = [r for r in rows if r['stage'] == stage and kind(r) != 'fatal']
            if any(kind(r) == 'next_fps' for r in done) or len(done) >= TRANSIENT_TRIES:
                continue                                           # this fps is already used up
            r = None
            for t in range(len(done) + 1, TRANSIENT_TRIES + 1):
                if halt.is_set():
                    return
                r = attempt(model, item, args.condition, fps, stage, t, cache, args)
                with LOCK:
                    with log.open('a', encoding='utf-8') as f:
                        f.write(json.dumps(r, ensure_ascii=False) + '\n')
                        f.flush()
                        os.fsync(f.fileno())
                k = kind(r)
                if k == 'fatal':
                    halt.set()
                    return
                if k == 'ok':
                    return
                if k == 'next_fps':
                    break
                with GATE:
                    STATE['cooldown'] = max(STATE['cooldown'], time.monotonic() + 30 * t)
            print(f'  {model} {item["question_id"]} stage {stage} failed: {r["api_error"][:120]}', flush=True)

    todo = [it for it in catalog if not any(r['valid_answer'] for r in hist.get(it['question_id'], []))]
    print(f'{model}: {len(catalog) - len(todo)} done, {len(todo)} to run', flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i, f in enumerate(as_completed([pool.submit(job, it) for it in todo]), 1):
            f.result()
            if i % 25 == 0:
                print(f'  {model} {i}/{len(todo)}', flush=True)
    if halt.is_set():
        print(f'{model}: halted on authorization/quota error; rerun to resume', flush=True)
    summarize_model(model, catalog, out, args.condition)
    return not halt.is_set()


# ---------------------------------------------------------------- selection and scoring
def summarize_model(model, catalog, out, cond):
    rows = validate_attempts(load(out / 'attempts.jsonl'), model, catalog, cond)
    sel = []
    for it in catalog:
        rs = sorted((r for r in rows if r['question_id'] == it['question_id']), key=lambda r: (r['stage'], r['tries']))
        v = next((r for r in rs if r['valid_answer']), None)      # first valid answer, never by correctness
        sel.append(dict(question_id=it['question_id'], level=it['level'], qa_type=it['qa_type'], gold=it['gold'],
                        prediction=v['prediction'] if v else '', valid=bool(v), fps=v['fps'] if v else None,
                        stage=v['stage'] if v else None, correct=int(bool(v and v['prediction'] == it['gold']))))
    tmp = out / 'selected.jsonl.tmp'
    tmp.write_text(''.join(json.dumps(s, ensure_ascii=False) + '\n' for s in sel), encoding='utf-8')
    os.replace(tmp, out / 'selected.jsonl')
    acc = lambda ss: round(100 * sum(s['correct'] for s in ss) / len(ss), 1) if ss else None
    P = [s for s in sel if s['qa_type'] == 'NA']
    C = [s for s in sel if s['qa_type'] == 'CB']
    fpsd = {}
    for s in sel:
        if s['valid']:
            fpsd[str(s['fps'])] = fpsd.get(str(s['fps']), 0) + 1
    summ = dict(model=model, name=CFG['models'][model]['name'], condition=cond, n=len(sel), overall=acc(sel),
                P=acc(P), C=acc(C), **{f'P_{l}': acc([s for s in P if s['level'] == l]) for l in ('L1', 'L2', 'L3', 'L4')},
                **{f'C_{l}': acc([s for s in C if s['level'] == l]) for l in ('L2', 'L3', 'L4')},
                unanswered=sum(not s['valid'] for s in sel), answered_by_fps=fpsd)
    summ['counts'] = {'total': len(sel), 'NA': len(P), 'CB': len(C),
                      **{f'NA_{l}': sum(s['level'] == l for s in P) for l in ('L1', 'L2', 'L3', 'L4')},
                      **{f'CB_{l}': sum(s['level'] == l for s in C) for l in ('L2', 'L3', 'L4')}}
    summ['protocol'] = 'unified-runner'
    grouped = {item['question_id']: [r for r in rows if r['question_id'] == item['question_id']] for item in catalog}
    summ['never_attempted'] = sum(not values for values in grouped.values())
    summ['incomplete_questions'] = sum(not item_complete(values, [None] if cond == 'V0M0' else DEF['fps_ladder'])
                                       for values in grouped.values())
    summ['run_status'] = 'incomplete' if summ['incomplete_questions'] else 'complete'
    summ['manifest_sha256'] = sha(out / 'manifest.json')
    summ['selected_sha256'] = sha(out / 'selected.jsonl')
    summ['attempts_sha256'] = sha(out / 'attempts.jsonl') if (out / 'attempts.jsonl').exists() else None
    write_json(out / 'summary.json', summ)
    print(json.dumps(summ, ensure_ascii=False), flush=True)
    return summ


def load_catalog(args):
    catalog_path = Path(args.catalog).resolve()
    cat = json.loads(catalog_path.read_text(encoding='utf-8-sig'))
    if not isinstance(cat, list) or not cat or not all(isinstance(it, dict) for it in cat):
        raise ValueError('catalog must be a nonempty JSON array of question objects')
    mappings = []
    for value in args.path_map:
        if '=' not in value or not value.split('=', 1)[0]:
            raise ValueError('--path-map expects nonempty OLD_PREFIX=NEW_PREFIX')
        mappings.append(value.split('=', 1))
    ids = set()
    for it in cat:
        qid = it.get('question_id')
        if not isinstance(qid, str) or not qid.strip() or qid in ids:
            raise ValueError(f'missing or duplicate question_id: {qid!r}')
        ids.add(qid)
        if it.get('qa_type') not in ('NA', 'CB') or it.get('level') not in ('L1', 'L2', 'L3', 'L4'):
            raise ValueError(f'{qid}: expected qa_type NA/CB and level L1-L4')
        if it['qa_type'] == 'CB' and it['level'] == 'L1':
            raise ValueError(f'{qid}: causal traceback has no L1 split')
        if it.get('gold') not in ('A', 'B', 'C', 'D'):
            raise ValueError(f'{qid}: gold must be A, B, C, or D')
        if it['qa_type'] == 'NA':
            it['options'] = options(it)
        elif not isinstance(it.get('known_action'), str) or not it['known_action'].strip():
            raise ValueError(f'{qid}: CB requires known_action')
        if not isinstance(it.get('objective') or it.get('task_name_zh'), str):
            raise ValueError(f'{qid}: requires objective or task_name_zh')
        for key in ('objective', 'task_name_zh', 'm3_text'):
            if it.get(key) is not None and not isinstance(it[key], str):
                raise ValueError(f'{qid}: {key} must be a string')
        if it.get('incidents') is not None:
            if not isinstance(it['incidents'], list) or any(not isinstance(a, dict) or
                    not isinstance(a.get('action'), str) or type(a.get('subtask')) not in (str, int)
                    for a in it['incidents']):
                raise ValueError(f'{qid}: incidents require string action and string/integer subtask')
        if it.get('option_labels') is not None and (not isinstance(it['option_labels'], dict) or
                any(k not in ('A', 'B', 'C', 'D') or not isinstance(v, str) for k, v in it['option_labels'].items())):
            raise ValueError(f'{qid}: option_labels must map A-D to strings')
    if args.condition == 'V0M0':
        cat = [it for it in cat if it['qa_type'] == 'NA']          # C needs the marked history
    keep = None
    if args.questions:
        keep = set(Path(args.questions).read_text(encoding='utf-8-sig').split())
        unknown = keep - ids
        if unknown:
            raise ValueError(f'question list contains unknown ids: {sorted(unknown)}')
    if args.condition in ('V1M3', 'V1M3C', 'V1M3CC', 'CoT'):
        if keep is not None:
            cat = [it for it in cat if it['question_id'] in keep and it['qa_type'] == 'NA']
        else:
            cat = [it for it in cat if it['qa_type'] == 'NA' and it.get('is_paired') is True]
            if not cat:
                raise ValueError('paired ablations require --questions with matched NA ids or explicit is_paired=true; L2-L4 alone are not the paired subset')
    elif keep is not None:
        cat = [it for it in cat if it['question_id'] in keep]
    if getattr(args, 'levels', None):
        cat = [it for it in cat if it['level'] in args.levels]
    if getattr(args, 'tasks', None):
        wanted = {'NA' if task == 'P' else 'CB' for task in args.tasks}
        cat = [it for it in cat if it['qa_type'] in wanted]
    cat = cat[:args.limit] if args.limit else cat
    if not cat:
        raise ValueError('no questions remain after condition/subset filtering')
    if args.condition in ('V1M3', 'V1M3C', 'V1M3CC'):
        if any(not isinstance(it.get('m3_text'), str) or not it['m3_text'].strip() for it in cat):
            raise ValueError('memory conditions require nonempty m3_text for every selected question')
        if args.condition in ('V1M3C', 'V1M3CC') and any('incidents' not in it for it in cat):
            raise ValueError('annotation conditions require incidents (an explicit empty list is allowed)')
    for it in cat:
        keys = ('current_frame',) if args.condition == 'V0M0' else ('history_video', 'current_frame')
        for k in keys:
            value = it.get(k)
            if not isinstance(value, str) or not value.strip() or '\x00' in value:
                raise ValueError(f'{it["question_id"]}: requires local {k} path')
            for old, new in mappings:
                if value == old or value.startswith(old.rstrip('/\\') + '/') or value.startswith(old.rstrip('/\\') + '\\'):
                    value = new.rstrip('/\\') + value[len(old.rstrip('/\\')):]
                    break
            path = Path(value)
            if not path.is_absolute():
                path = catalog_path.parent / path
            it[k] = str(path.resolve())
            hash_key = 'current_sha256' if k == 'current_frame' else 'history_sha256'
            if args.verify_sha and not re.fullmatch('[a-fA-F0-9]{64}', it.get(hash_key, '')):
                raise ValueError(f'{it["question_id"]}: requires {hash_key} with 64 hex digits')
            if it.get(hash_key):
                it[hash_key] = it[hash_key].lower()
            if not args.summarize:
                if not path.is_file():
                    raise ValueError(f'{it["question_id"]}: media file missing: {path}')
                if k == 'current_frame':
                    image_mime(path)
                if args.verify_sha and sha(path) != it[hash_key]:
                    raise ValueError(f'{it["question_id"]}: media SHA-256 mismatch: {k}')
    return cat


def main():
    global CFG, DEF, CONFIG_PATH
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--catalog', help='catalog.json (699 items)')
    ap.add_argument('--config', default=str(CONFIG_PATH), help='model/endpoint registry JSON')
    ap.add_argument('--models', nargs='+', default=['all'], help='model ids from configs/models.json, or "all"')
    ap.add_argument('--condition', default='V1M0', choices=['V1M0', 'V1M3', 'V1M3C', 'V1M3CC', 'V0M0', 'CoT'],
                    help='V1M0 video (main); V1M3 video+log; V1M3C/V1M3CC ablation with cause annotations; '
                         'V0M0 current frame only (P items); CoT causal chain-of-thought guidance')
    ap.add_argument('--out', required=True)
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--min-interval', type=float, default=0.0, help='min seconds between request starts')
    ap.add_argument('--path-map', nargs='*', default=[], help='OLD_PREFIX=NEW_PREFIX for media paths')
    ap.add_argument('--questions', help='file with question_ids to run (whitespace separated)')
    ap.add_argument('--limit', type=int, help='first N items only (smoke test)')
    ap.add_argument('--levels', nargs='+', choices=['L1', 'L2', 'L3', 'L4'], help='scenario subset; default all')
    ap.add_argument('--tasks', nargs='+', choices=['P', 'C'], help='P prediction / C traceback; default both')
    ap.add_argument('--max-output-tokens', type=int, help='override output budget (recorded in run identity)')
    ap.add_argument('--fps-ladder', type=int, nargs='+', help='override sampling rates, e.g. 1 for a cheap smoke run')
    ap.add_argument('--no-verify-sha', dest='verify_sha', action='store_false')
    ap.add_argument('--summarize', action='store_true', help='only rebuild selected.jsonl / summary.json')
    ap.add_argument('--validate-catalog', action='store_true', help='validate selected catalog/media then exit without requests or API keys')
    args = ap.parse_args()
    try:
        if args.workers < 1 or args.workers > 256 or args.min_interval < 0 or (args.limit is not None and args.limit <= 0):
            raise ValueError('--workers must be 1-256, --min-interval nonnegative, and --limit positive')
        if args.summarize and args.validate_catalog:
            raise ValueError('--summarize and --validate-catalog are mutually exclusive')
        CONFIG_PATH = Path(args.config).resolve()
        CFG = json.loads(CONFIG_PATH.read_text(encoding='utf-8-sig'))
        if args.max_output_tokens is not None:
            CFG['defaults']['max_output_tokens'] = args.max_output_tokens
        if args.fps_ladder is not None:
            CFG['defaults']['fps_ladder'] = args.fps_ladder
        validate_config(CFG)
        DEF = CFG['defaults']
    except (ValueError, OSError) as exc:
        ap.error(str(exc))
    models = list(CFG['models']) if args.models == ['all'] else args.models
    unknown = [m for m in models if m not in CFG['models']]
    if unknown:
        raise SystemExit(f'unknown model id(s): {unknown}')
    if len(models) != len(set(models)):
        raise SystemExit('duplicate model ids are not allowed')
    if not args.catalog:
        ap.error('--catalog is required (including for --summarize)')
    try:
        cat = load_catalog(args)
    except (ValueError, OSError) as exc:
        ap.error(str(exc))
    if args.validate_catalog:
        print(json.dumps({'valid': True, 'condition': args.condition, 'n_items': len(cat),
                          'selected_catalog_sha256': digest(cat)}, indent=2))
        return
    if args.summarize:
        base = Path(args.out) / args.condition
        for m in models:
            if (base / m / 'attempts.jsonl').exists():
                ensure_manifest(m, cat, base / m, args)
                summarize_model(m, cat, base / m, args.condition)
        return
    if not FFMPEG and args.condition != 'V0M0':
        raise SystemExit('ffmpeg not found (install ffmpeg or pip install imageio-ffmpeg)')
    for m in models:
        key_for(CFG['endpoints'][CFG['models'][m]['endpoint']])      # fail early, never print the key
    Path(args.out).mkdir(parents=True, exist_ok=True)
    write_json(Path(args.out) / f'manifest_{args.condition}.json', dict(
        condition=args.condition, models=models, n_items=len(cat), catalog_sha256=sha(args.catalog),
        code_sha256=sha(__file__), config_sha256=sha(CONFIG_PATH), defaults=DEF,
        transient_tries=TRANSIENT_TRIES, workers=args.workers, started_at=time.time()))
    for m in models:
        if not run_model(m, cat, args):
            raise SystemExit(2)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as exc:
        raise SystemExit(clean(str(exc)))
