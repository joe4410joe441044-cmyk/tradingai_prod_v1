"""Isolated Nginx proof for the logout POST candidate.  Not production."""
import http.server
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / 'tests/fixtures/work_aa_oidc_nginx_logout_candidate.conf'
LAB = ROOT / 'tmp/f11d16_nginx_lab'
LISTEN = ('127.0.0.1', 18081)
MOCK = ('127.0.0.1', 18082)
REMOTE = '203.0.113.10'
EXISTING_POST = (
    'location ~ ^/api/(auth/(login|logout)|bot/(start|stop|saved-mode|control|'
    'manual-trade|loop/start|loop/stop|live-order-entry/(arm|disarm)|'
    'live-auto/(approve|start|stop)|paper-account/capital)|governance/(mode|'
    'execution|risk-profile|emergency-stop|emergency-orchestrate|emergency/unlock|'
    'emergency/retry)|runtime/(stopped-paper-safety/refresh|paper-auto/(start|'
    'cycle|stop|observe|reselect)))$ {\n'
    '    limit_except GET HEAD OPTIONS POST { deny all; }\n'
    '    proxy_pass http://127.0.0.1:18082;\n'
    '    proxy_set_header Host $host;\n'
    '    proxy_set_header X-Forwarded-Proto $scheme;\n'
    '}\n'
)


class _Handler(http.server.BaseHTTPRequestHandler):
    seen = []

    def _take(self):
        length = int(self.headers.get('Content-Length') or 0)
        if length:
            self.rfile.read(length)
        self.seen.append({
            'method': self.command,
            'path': self.path,
            'cookie': self.headers.get('Cookie'),
            'host': self.headers.get('Host'),
            'proto': self.headers.get('X-Forwarded-Proto'),
        })
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        self._take()

    def do_POST(self):
        self._take()

    def do_OPTIONS(self):
        self._take()

    def do_PUT(self):
        self._take()

    def log_message(self, _fmt, *_args):
        return


def _candidate_location():
    text = CANDIDATE.read_text(encoding='utf-8')
    assert 'location /api/ {' not in text
    assert 'ssl_certificate' not in text
    assert 'listen 80' not in text
    assert 'location = /api/observation/auth/oidc/logout' in text
    assert 'limit_except GET HEAD OPTIONS POST { deny all; }' in text
    assert 'proxy_pass http://127.0.0.1:8001;' in text
    lab = text.replace('http://127.0.0.1:8001', 'http://127.0.0.1:18082')
    assert ':8001' not in lab
    start = lab.index('location = /api/observation/auth/oidc/logout')
    return lab[start:]


def _request(method, path, remote, cookie=None):
    headers = {'X-Test-Remote': remote}
    if cookie:
        headers['Cookie'] = cookie
    request = urllib.request.Request(
        'http://127.0.0.1:18081' + path, data=b'{}' if method == 'POST' else None,
        headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_f11d16_isolated_nginx_allows_only_logout_post_among_new_routes():
    assert shutil.which('nginx')
    if LAB.exists():
        shutil.rmtree(LAB)
    (LAB / 'logs').mkdir(parents=True)
    location = _candidate_location()
    config = (
        'worker_processes 1;\n'
        'error_log logs/error.log;\n'
        'pid logs/nginx.pid;\n'
        'events { worker_connections 32; }\n'
        'http {\n'
        '  access_log logs/access.log;\n'
        '  server {\n'
        '    listen 127.0.0.1:18081;\n'
        '    set_real_ip_from 127.0.0.1;\n'
        '    real_ip_header X-Test-Remote;\n'
        '    location /api/ {\n'
        '      limit_except GET HEAD OPTIONS {\n'
        '        allow 127.0.0.1;\n'
        '        allow ::1;\n'
        '        deny all;\n'
        '      }\n'
        '      proxy_pass http://127.0.0.1:18082;\n'
        '      proxy_set_header Host $host;\n'
        '      proxy_set_header X-Forwarded-Proto $scheme;\n'
        '    }\n'
        + EXISTING_POST +
        location + '\n'
        '  }\n'
        '}\n'
    )
    (LAB / 'nginx.conf').write_text(config, encoding='utf-8')
    syntax = subprocess.run(
        ['nginx', '-p', str(LAB) + '/', '-c', 'nginx.conf', '-t'],
        capture_output=True, text=True, check=False)
    assert syntax.returncode == 0, syntax.stderr
    _Handler.seen = []
    server = http.server.ThreadingHTTPServer(MOCK, _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    master = subprocess.Popen(
        ['nginx', '-p', str(LAB) + '/', '-c', 'nginx.conf', '-g', 'daemon off;'])
    try:
        assert _request('GET', '/api/observation/auth/oidc/start', REMOTE) == 204
        assert _request('GET', '/api/observation/auth/oidc/callback', REMOTE) == 204
        assert _request('GET', '/api/observation/auth/oidc/status', REMOTE) == 204
        assert _request(
            'POST', '/api/observation/auth/oidc/logout', REMOTE,
            cookie='tradingai_observation_session=session-value') == 204
        assert _request('OPTIONS', '/api/observation/auth/oidc/logout', REMOTE) == 204
        assert _request('PUT', '/api/observation/auth/oidc/logout', REMOTE) == 403
        assert _request('POST', '/api/observation/auth/oidc/start', REMOTE) == 403
        assert _request('POST', '/api/bot/stop', REMOTE) == 204
        assert _request('POST', '/api/money-management/configuration', REMOTE) == 403
        logout = [
            item for item in _Handler.seen
            if item['path'] == '/api/observation/auth/oidc/logout'
            and item['method'] == 'POST']
        assert logout
        assert logout[0]['cookie'] == 'tradingai_observation_session=session-value'
        assert logout[0]['host'].startswith('127.0.0.1')
        assert logout[0]['proto'] == 'http'
        denied = [item for item in _Handler.seen if item['path'] == '/api/bot/stop']
        assert any(item['method'] == 'POST' for item in denied)
    finally:
        subprocess.run(
            ['nginx', '-p', str(LAB) + '/', '-c', 'nginx.conf', '-s', 'stop'],
            check=False)
        master.wait(timeout=5)
        server.shutdown()
