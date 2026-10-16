#!/usr/bin/env python3
"""Exercise real media, all three wire protocols, retry, resume and scoring offline."""
import argparse
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from scripts.export_submission import validate_run
from scripts.make_synthetic_fixture import make_fixture


class MockHandler(BaseHTTPRequestHandler):
    requests_seen = 0
    lock = threading.Lock()

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        with self.lock:
            type(self).requests_seen += 1
        text = json.dumps(body)
        # Scenario 2 is intentionally wrong. Scenario 4 needs one FPS fallback.
        answer = 'D' if 'SYNTHETIC_SCENARIO_4' in text else 'A'
        raw = 'invalid mock format' if 'SYNTHETIC_SCENARIO_4' in text and 'at 5 fps' in text else f'Final Answer: [{answer}]'
        if self.path.endswith('/chat/completions'):
            content = body['messages'][0]['content']
            if body['model'] == 'mock-chat-frames':
                assert len([part for part in content if part.get('type') == 'image_url']) >= 2
                assert not any(part.get('type') == 'video_url' for part in content)
            else:
                assert any(part.get('type') == 'video_url' for part in content)
            response = {'id': 'synthetic-chat', 'model': body['model'],
                        'choices': [{'message': {'content': raw}, 'finish_reason': 'stop'}]}
        elif self.path.endswith(':generateContent'):
            assert any(part.get('inline_data', {}).get('mime_type') == 'video/mp4' for part in body['contents'][0]['parts'])
            response = {'responseId': 'synthetic-gemini',
                        'candidates': [{'content': {'parts': [{'text': raw}]}, 'finishReason': 'STOP'}]}
        elif self.path.endswith('/responses'):
            assert len([part for part in body['input'][0]['content'] if part['type'] == 'input_image']) >= 2
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            events = [{'type': 'response.output_text.delta', 'delta': raw},
                      {'type': 'response.completed', 'response': {'id': 'synthetic-responses',
                                                                 'status': 'completed', 'model': body['model']}}]
            self.wfile.write((''.join('data: ' + json.dumps(e) + '\n\n' for e in events) + 'data: [DONE]\n\n').encode())
            return
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())


def smoke(out):
    MockHandler.requests_seen = 0
    out = Path(out).resolve()
    if out.exists() and any(out.iterdir()):
        raise ValueError('smoke needs a new or empty output directory; fixture ports change between smoke sessions')
    out.mkdir(parents=True, exist_ok=True)
    catalog = make_fixture(out / '_inputs')
    server = ThreadingHTTPServer(('127.0.0.1', 0), MockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}/v1'
    cfg = {'_synthetic': True, 'defaults': {'temperature': 0, 'max_output_tokens': 64,
                                          'fps_ladder': [5, 3, 1], 'timeout_s': 10},
           'endpoints': {}, 'models': {}}
    for protocol in ('chat', 'gemini', 'responses'):
        cfg['endpoints'][protocol] = {'protocol': protocol, 'base_url': base, 'key_env': 'EMBER_SYNTHETIC_KEY'}
        cfg['models']['mock-' + protocol] = {'name': 'Synthetic ' + protocol, 'endpoint': protocol}
    cfg['endpoints']['chat-frames'] = dict(cfg['endpoints']['chat'], input_mode='frames')
    cfg['models']['mock-chat-frames'] = {'name': 'Synthetic chat frames', 'endpoint': 'chat-frames'}
    config = out / '_inputs' / 'models.json'
    config.write_text(json.dumps(cfg, indent=2), encoding='utf-8')
    env = {**os.environ, 'EMBER_SYNTHETIC_KEY': 'synthetic-local-only'}
    command = [sys.executable, str(HERE / 'ember_eval.py'), '--catalog', str(catalog),
               '--config', str(config), '--out', str(out), '--workers', '2']
    try:
        subprocess.run(command + ['--validate-catalog'], env=env, check=True)
        subprocess.run(command, env=env, check=True)
        requests_after_run = MockHandler.requests_seen
        if requests_after_run != 20:
            raise AssertionError(f'expected 20 mock attempts, got {requests_after_run}')
        subprocess.run(command, env=env, check=True)
        subprocess.run(command + ['--summarize'], env=env, check=True)
        if MockHandler.requests_seen != requests_after_run:
            raise AssertionError('resume/summarize made unexpected requests')
        for model in cfg['models']:
            candidate = validate_run(out / 'V1M0' / model)
            if candidate['accuracy']['overall'] != 75.0 or candidate['unanswered'] != 0:
                raise AssertionError('synthetic accuracy must be 75%, with all four answers valid')
            candidate_path = out / f'{model}.candidate.json'
            candidate_path.write_text(json.dumps(candidate, indent=2) + '\n', encoding='utf-8')
        print('OFFLINE SMOKE OK: 3 protocols / 4 input adapters; 20 mock attempts; 5-to-3 fallback; resume/summarize made 0 requests; 4 validated synthetic candidates.')
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    try:
        smoke(parser.parse_args().out)
    except (ValueError, OSError, AssertionError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))
