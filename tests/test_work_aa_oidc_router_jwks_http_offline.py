"""HTTP integration for the mounted observation OIDC router.  No live Google."""
import base64
import hashlib
import http.client
import json
from urllib.parse import parse_qs, urlparse

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.auth.api import create_operator_auth_router
from backend.auth.auth_config import OperatorAuthConfig
from backend.auth.dependencies import require_operator_session
from backend.auth.operator_auth import OperatorAuthenticator, hash_operator_credential
from backend.auth.operator_session import COOKIE_NAME, OperatorSessionManager
from backend.observation_auth.oidc_api import (
    CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE, TXN_COOKIE, stage_b_execution_gate)
from backend.observation_auth.oidc_config import ObservationOidcConfig
from backend.observation_auth.oidc_jwks import (
    DISCOVERY_URL, JWKS_URL, GoogleJwksClient)
from backend.observation_auth.oidc_mount import mount_observation_oidc
from tools.work_aa.observation_operator_identity import OBSERVATION_PERMISSION


SUBJECT = 'google-subject-1'
NOW = 1_700_000_000
REDIRECT = 'http://testserver/api/observation/auth/oidc/callback'
_PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OPERATOR_HASH = hash_operator_credential('correct-horse')


class Clock:
    def __init__(self):
        self.wall = NOW
        self.mono = 1000.0

    def time(self):
        return self.wall

    def monotonic(self):
        return self.mono


class Exchanger:
    def __init__(self):
        self.token = None
        self.as_document = False
        self.seen = None

    def exchange(self, code, verifier, redirect_uri):
        self.seen = (code, verifier, redirect_uri)
        if self.token is None:
            return None
        if self.as_document:
            return {'id_token': self.token, 'access_token': 'hidden-access-token'}
        return self.token


class Transport:
    def __init__(self):
        self.calls = []
        self.discovery = {
            'issuer': 'https://accounts.google.com',
            'jwks_uri': JWKS_URL,
        }
        self.documents = []
        self.raw = None
        self.error = None

    def get_bytes(self, url):
        self.calls.append(url)
        if self.error is not None:
            raise self.error
        if url == DISCOVERY_URL:
            return json.dumps(self.discovery).encode('utf-8')
        if url != JWKS_URL:
            raise AssertionError(url)
        if self.raw is not None:
            return self.raw
        document = self.documents.pop(0)
        return json.dumps(document).encode('utf-8')


def _b64(raw):
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def _jwk(key, kid='test-key'):
    numbers = key.public_key().public_numbers()
    return {
        'kty': 'RSA', 'alg': 'RS256', 'kid': kid, 'use': 'sig',
        'n': _b64(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, 'big')),
        'e': _b64(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, 'big')),
    }


def _sign(payload, private=_PRIVATE, kid='test-key', alg='RS256'):
    header = {'alg': alg}
    if kid is not None:
        header['kid'] = kid
    encoded_header = _b64(json.dumps(header, separators=(',', ':')).encode())
    encoded_body = _b64(json.dumps(payload, separators=(',', ':')).encode())
    if alg != 'RS256':
        return encoded_header + '.' + encoded_body + '.'
    signing = (encoded_header + '.' + encoded_body).encode('ascii')
    signature = private.sign(signing, padding.PKCS1v15(), hashes.SHA256())
    return encoded_header + '.' + encoded_body + '.' + _b64(signature)


def _config(**overrides):
    raw = {
        'enabled': True,
        'issuer': 'https://accounts.google.com',
        'client_id': 'example-client.apps.googleusercontent.com',
        'redirect_uri': REDIRECT,
        'session_secret': 'o' * 32,
        'secure_cookie': False,
        'insecure_redirect_allowed': True,
        'allowlist': [{
            'issuer': 'https://accounts.google.com',
            'subject': SUBJECT,
            'permission': OBSERVATION_PERMISSION,
            'enabled': True,
        }],
    }
    raw.update(overrides)
    return ObservationOidcConfig(raw)


def _token(nonce, **overrides):
    payload = {
        'iss': 'https://accounts.google.com',
        'aud': 'example-client.apps.googleusercontent.com',
        'sub': SUBJECT,
        'nonce': nonce,
        'iat': NOW,
        'exp': NOW + 300,
    }
    payload.update(overrides)
    return _sign(payload)


def _mount(transport=None, exchanger=None, clock=None, **overrides):
    clock = clock or Clock()
    app = FastAPI()
    mount_observation_oidc(
        app, _config(**overrides), exchanger=exchanger or Exchanger(),
        transport=transport, now=clock.time, monotonic=clock.monotonic)
    return app, clock


def _start(client):
    response = client.get('/api/observation/auth/oidc/start', follow_redirects=False)
    assert response.status_code == 302, response.text
    query = parse_qs(urlparse(response.headers['location']).query)
    return response, query


def _callback(client, query, state=None):
    return client.get(
        '/api/observation/auth/oidc/callback',
        params={'code': 'auth-code', 'state': query['state'][0] if state is None else state},
        follow_redirects=False)


def _ready(documents):
    transport = Transport()
    transport.documents = documents
    exchanger = Exchanger()
    app, clock = _mount(transport, exchanger)
    return TestClient(app), transport, exchanger, clock


def _paths(routes):
    found = set()
    for route in routes:
        path = getattr(route, 'path', None)
        if path:
            found.add(path)
        nested = getattr(route, 'routes', None)
        if nested:
            found.update(_paths(nested))
        original = getattr(route, 'original_router', None)
        if original is not None:
            found.update(_paths(original.routes))
    return found


def test_f11d14_01_router_is_mounted_on_the_application():
    app = FastAPI()
    mount_observation_oidc(app)
    paths = _paths(app.routes)
    assert '/api/observation/auth/oidc/start' in paths
    assert '/api/observation/auth/oidc/callback' in paths
    assert '/api/observation/auth/oidc/status' in paths
    assert '/api/observation/auth/oidc/logout' in paths
    source = open('backend/main.py', encoding='utf-8').read()
    assert 'mount_observation_oidc(app)' in source


def test_f11d14_02_feature_flag_off_rejects_the_flow_without_secrets():
    client = TestClient(mount_observation_oidc(FastAPI()))
    start = client.get('/api/observation/auth/oidc/start', follow_redirects=False)
    callback = client.get('/api/observation/auth/oidc/callback')
    status = client.get('/api/observation/auth/oidc/status')
    logout = client.post('/api/observation/auth/oidc/logout')
    assert start.status_code == 403
    assert start.json()['reason'] == 'FEATURE_DISABLED'
    assert callback.status_code == 403
    assert status.status_code == 401
    assert status.json()['status'] == 'UNAUTHENTICATED'
    assert logout.status_code == 200
    assert logout.json()['status'] == 'UNAUTHENTICATED'
    joined = start.text + status.text + logout.text
    assert 'client_id' not in joined
    assert 'session_secret' not in joined
    assert 'location' not in start.headers


def test_f11d14_03_missing_configuration_fails_closed():
    app, _clock = _mount(Transport(), Exchanger(), client_id='')
    response = TestClient(app).get('/api/observation/auth/oidc/start', follow_redirects=False)
    assert response.status_code == 403
    assert response.json()['reason'] == 'MISSING_CONFIGURATION'


def test_f11d14_04_existing_login_route_remains_available():
    app = mount_observation_oidc(FastAPI())
    app.include_router(create_operator_auth_router(
        OperatorAuthenticator(_OPERATOR_HASH),
        OperatorSessionManager('s' * 32, session_ttl_seconds=300),
        OperatorAuthConfig(secure_cookie=False)))
    response = TestClient(app).post('/api/auth/login', content=b'not-json')
    assert response.status_code == 415
    assert '/api/observation/auth/oidc/start' in _paths(app.routes)
    assert '/api/auth/login' in _paths(app.routes)


def test_f11d14_05_valid_jwks_verifies_through_the_existing_verifier():
    client, _transport, exchanger, _clock = _ready([{'keys': [_jwk(_PRIVATE)]}])
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0])
    response = _callback(client, query)
    assert response.status_code == 200
    assert response.json()['subject'] == SUBJECT


def test_f11d14_06_invalid_jwks_is_rejected():
    client, _transport, exchanger, _clock = _ready([{'keys': []}])
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0])
    response = _callback(client, query)
    assert response.status_code == 403
    assert response.json()['reason'] == 'INVALID_JWKS'
    assert SESSION_COOKIE not in response.text


def test_f11d14_07_missing_kid_is_rejected():
    client, _transport, exchanger, _clock = _ready([{'keys': [_jwk(_PRIVATE)]}])
    _response, query = _start(client)
    body = json.loads(base64.urlsafe_b64decode(_token(query['nonce'][0]).split('.')[1] + '=='))
    exchanger.token = _sign(body, kid=None)
    response = _callback(client, query)
    assert response.json()['reason'] == 'MISSING_KID'


def test_f11d14_08_unknown_kid_is_rejected_after_one_refresh():
    other = {'keys': [_jwk(_OTHER, kid='other-key')]}
    client, transport, exchanger, _clock = _ready([other, other])
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0])
    response = _callback(client, query)
    assert response.json()['reason'] == 'UNKNOWN_SIGNING_KEY'
    assert transport.calls.count(JWKS_URL) == 2
    assert client.get('/api/observation/auth/oidc/status').status_code == 401


def test_f11d14_09_jwks_refresh_accepts_a_rotated_key():
    first = {'keys': [_jwk(_OTHER, kid='old-key')]}
    second = {'keys': [_jwk(_PRIVATE, kid='test-key')]}
    client, transport, exchanger, _clock = _ready([first, second])
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0])
    response = _callback(client, query)
    assert response.status_code == 200
    assert transport.calls.count(JWKS_URL) == 2


def test_f11d14_10_jwks_timeout_fails_closed():
    transport = Transport()
    transport.error = TimeoutError('timed out')
    client, _transport, exchanger, _clock = _ready([])
    # replace the prepared transport's error by rebuilding
    app, _clock = _mount(transport, exchanger := Exchanger())
    http = TestClient(app)
    _response, query = _start(http)
    exchanger.token = _token(query['nonce'][0])
    response = _callback(http, query)
    assert response.json()['reason'] == 'JWKS_TIMEOUT'
    assert response.status_code == 403


def test_f11d14_11_malformed_jwks_json_is_rejected():
    transport = Transport()
    transport.raw = b'{'
    app, _clock = _mount(transport, exchanger := Exchanger())
    http = TestClient(app)
    _response, query = _start(http)
    exchanger.token = _token(query['nonce'][0])
    assert _callback(http, query).json()['reason'] == 'MALFORMED_JWKS'


def test_f11d14_12_oversized_jwks_response_is_rejected():
    transport = Transport()
    transport.raw = b'{' + b' ' * 70000
    app, _clock = _mount(transport, exchanger := Exchanger())
    http = TestClient(app)
    _response, query = _start(http)
    exchanger.token = _token(query['nonce'][0])
    assert _callback(http, query).json()['reason'] == 'OVERSIZED_JWKS'


def test_f11d14_13_invalid_discovery_issuer_is_rejected():
    transport = Transport()
    transport.discovery = {'issuer': 'https://evil.example', 'jwks_uri': JWKS_URL}
    app, _clock = _mount(transport, exchanger := Exchanger())
    http = TestClient(app)
    _response, query = _start(http)
    exchanger.token = _token(query['nonce'][0])
    response = _callback(http, query)
    assert response.json()['reason'] == 'INVALID_ISSUER'
    assert JWKS_URL not in transport.calls


def test_f11d14_14_discovery_cannot_select_an_unpinned_jwks_url():
    transport = Transport()
    transport.discovery = {
        'issuer': 'https://accounts.google.com',
        'jwks_uri': 'http://127.0.0.1/latest/meta-data',
    }
    app, _clock = _mount(transport, exchanger := Exchanger())
    http = TestClient(app)
    _response, query = _start(http)
    exchanger.token = _token(query['nonce'][0])
    response = _callback(http, query)
    assert response.json()['reason'] == 'SSRF_REJECTED'
    assert transport.calls == [DISCOVERY_URL]


def test_f11d14_15_algorithm_none_is_rejected():
    client, _transport, exchanger, _clock = _ready([{'keys': [_jwk(_PRIVATE)]}])
    _response, query = _start(client)
    body = json.loads(base64.urlsafe_b64decode(_token(query['nonce'][0]).split('.')[1] + '=='))
    exchanger.token = _sign(body, alg='none')
    assert _callback(client, query).json()['reason'] == 'ALGORITHM_REJECTED'


def test_f11d14_16_start_redirects_to_the_fixed_authorization_endpoint():
    client, _transport, _exchanger, _clock = _ready([{'keys': [_jwk(_PRIVATE)]}])
    response, query = _start(client)
    location = urlparse(response.headers['location'])
    assert (location.scheme, location.netloc, location.path) == (
        'https', 'accounts.google.com', '/o/oauth2/v2/auth')
    assert query['response_type'] == ['code']


def test_f11d14_17_start_uses_pkce_s256():
    client, _transport, exchanger, _clock = _ready([{'keys': [_jwk(_PRIVATE)]}])
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0])
    _callback(client, query)
    verifier = exchanger.seen[1]
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    challenge = base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')
    assert query['code_challenge_method'] == ['S256']
    assert query['code_challenge'] == [challenge]


def test_f11d14_18_valid_callback_issues_an_observation_session():
    client, _transport, exchanger, _clock = _ready([{'keys': [_jwk(_PRIVATE)]}])
    _response, query = _start(client)
    failed = _callback(client, query)
    assert failed.json()['reason'] == 'TOKEN_EXCHANGE_FAILED'
    assert client.get('/api/observation/auth/oidc/status').status_code == 401
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0])
    exchanger.as_document = True
    response = _callback(client, query)
    assert response.status_code == 200
    assert 'hidden-access-token' not in response.text
    assert 'id_token' not in response.json()


def test_f11d14_19_invalid_state_is_rejected():
    client, _transport, exchanger, _clock = _ready([{'keys': [_jwk(_PRIVATE)]}])
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0])
    response = _callback(client, query, state='other-state')
    assert response.json()['reason'] == 'STATE_MISMATCH'


def test_f11d14_20_state_replay_is_rejected():
    client, _transport, exchanger, _clock = _ready([{'keys': [_jwk(_PRIVATE)]}])
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0])
    assert _callback(client, query).status_code == 200
    client.cookies.set(TXN_COOKIE, query['state'][0], path='/api/observation')
    assert _callback(client, query).json()['reason'] == 'STATE_REPLAY'


def test_f11d14_21_expired_state_is_rejected():
    transport = Transport()
    transport.documents = [{'keys': [_jwk(_PRIVATE)]}]
    clock = Clock()
    app, clock = _mount(transport, exchanger := Exchanger(), clock)
    client = TestClient(app)
    _response, query = _start(client)
    clock.mono += 301
    exchanger.token = _token(query['nonce'][0])
    assert _callback(client, query).json()['reason'] == 'EXPIRED_STATE'


def test_f11d14_22_nonce_mismatch_is_rejected():
    client, _transport, exchanger, _clock = _ready([{'keys': [_jwk(_PRIVATE)]}])
    _response, query = _start(client)
    exchanger.token = _token('x' * len(query['nonce'][0]))
    assert _callback(client, query).json()['reason'] == 'NONCE_MISMATCH'


def test_f11d14_23_invalid_signature_is_rejected():
    client, _transport, exchanger, _clock = _ready([{'keys': [_jwk(_PRIVATE)]}])
    _response, query = _start(client)
    body = json.loads(base64.urlsafe_b64decode(_token(query['nonce'][0]).split('.')[1] + '=='))
    exchanger.token = _sign(body, private=_OTHER)
    assert _callback(client, query).json()['reason'] == 'INVALID_SIGNATURE'


def test_f11d14_24_wrong_audience_is_rejected():
    client, _transport, exchanger, _clock = _ready([{'keys': [_jwk(_PRIVATE)]}])
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0], aud='other-client')
    assert _callback(client, query).json()['reason'] == 'WRONG_AUDIENCE'


def test_f11d14_25_wrong_token_issuer_is_rejected():
    client, _transport, exchanger, _clock = _ready([{'keys': [_jwk(_PRIVATE)]}])
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0], iss='https://evil.example')
    assert _callback(client, query).json()['reason'] == 'WRONG_ISSUER'


def test_f11d14_26_expired_id_token_is_rejected():
    client, _transport, exchanger, _clock = _ready([{'keys': [_jwk(_PRIVATE)]}])
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0], exp=NOW - 1)
    assert _callback(client, query).json()['reason'] == 'EXPIRED'


def test_f11d14_27_unauthorized_subject_is_rejected():
    client, _transport, exchanger, _clock = _ready([{'keys': [_jwk(_PRIVATE)]}])
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0], sub='someone-else')
    assert _callback(client, query).json()['reason'] == 'UNAUTHORIZED_SUBJECT'


def test_f11d14_28_session_is_observation_only():
    client, _transport, exchanger, _clock = _ready([{'keys': [_jwk(_PRIVATE)]}])
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0])
    body = _callback(client, query).json()
    assert body['permission'] == OBSERVATION_PERMISSION
    assert body['observation_authority'] is False
    assert body['trading_authority'] is False
    assert client.get('/api/observation/auth/oidc/status').json()['subject'] == SUBJECT


def test_f11d14_29_observation_cookie_is_separate_from_the_trading_cookie():
    client, _transport, exchanger, _clock = _ready([{'keys': [_jwk(_PRIVATE)]}])
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0])
    joined = ' '.join(_callback(client, query).headers.get_list('set-cookie'))
    assert SESSION_COOKIE in joined
    assert CSRF_COOKIE in joined
    assert 'HttpOnly' in joined
    assert 'SameSite=lax' in joined or 'SameSite=Lax' in joined
    assert COOKIE_NAME not in joined


def test_f11d14_30_logout_invalidates_the_session():
    client, _transport, exchanger, _clock = _ready([{'keys': [_jwk(_PRIVATE)]}])
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0])
    _callback(client, query)
    csrf = client.cookies.get(CSRF_COOKIE)
    logged_out = client.post(
        '/api/observation/auth/oidc/logout', headers={CSRF_HEADER: csrf})
    assert logged_out.json()['status'] == 'UNAUTHENTICATED'
    assert client.get('/api/observation/auth/oidc/status').status_code == 401


def test_f11d14_31_logout_without_csrf_is_rejected():
    client, _transport, exchanger, _clock = _ready([{'keys': [_jwk(_PRIVATE)]}])
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0])
    _callback(client, query)
    response = client.post(
        '/api/observation/auth/oidc/logout', headers={CSRF_HEADER: 'wrong-csrf-value'})
    assert response.status_code == 403
    assert response.json()['reason'] == 'CSRF_REJECTED'
    assert client.get('/api/observation/auth/oidc/status').status_code == 200


def test_f11d14_32_expired_session_is_rejected():
    transport = Transport()
    transport.documents = [{'keys': [_jwk(_PRIVATE)]}]
    clock = Clock()
    app, clock = _mount(transport, exchanger := Exchanger(), clock, session_ttl_seconds=30)
    client = TestClient(app)
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0])
    assert _callback(client, query).status_code == 200
    clock.mono += 31
    assert client.get('/api/observation/auth/oidc/status').status_code == 401


def test_f11d14_33_login_does_not_grant_an_approval():
    client, _transport, exchanger, _clock = _ready([{'keys': [_jwk(_PRIVATE)]}])
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0])
    body = _callback(client, query).json()
    gate = stage_b_execution_gate()
    assert body['approval_gate'] == 'DISABLED'
    assert body['stage_b_execution_ready'] is False
    assert 'approval_id' not in body
    assert gate['decision'] == 'DENY'
    assert gate['exchange_calls'] == 0


def test_f11d14_34_observation_session_cannot_escalate_trading_control():
    client, _transport, exchanger, _clock = _ready([{'keys': [_jwk(_PRIVATE)]}])
    app = client.app

    @app.post('/api/bot/start')
    def bot_start(request: Request):
        require_operator_session(request)
        return {'status': 'STARTED'}

    @app.post('/api/bot/manual-trade')
    def manual_trade(request: Request):
        require_operator_session(request)
        return {'status': 'SENT'}

    @app.post('/api/bot/live-order-entry/arm')
    def arm(request: Request):
        require_operator_session(request)
        return {'status': 'ARMED'}

    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0])
    _callback(client, query)
    cookie = client.cookies.get(SESSION_COOKIE)
    for path in ('/api/bot/start', '/api/bot/manual-trade', '/api/bot/live-order-entry/arm'):
        response = TestClient(app, raise_server_exceptions=False).post(
            path, headers={'cookie': SESSION_COOKIE + '=' + cookie})
        assert response.status_code == 401


def test_f11d14_35_existing_login_still_returns_the_literal_operator():
    app, _clock = _mount(Transport(), Exchanger())
    app.include_router(create_operator_auth_router(
        OperatorAuthenticator(_OPERATOR_HASH),
        OperatorSessionManager('s' * 32, session_ttl_seconds=300),
        OperatorAuthConfig(secure_cookie=False)))
    client = TestClient(app)
    response = client.post('/api/auth/login', json={'credential': 'correct-horse'})
    assert response.status_code == 200
    assert response.json()['identity'] == 'operator'
    assert COOKIE_NAME in ' '.join(response.headers.get_list('set-cookie'))
    assert client.get('/api/observation/auth/oidc/status').status_code == 401


def test_f11d14_36_bot_status_route_does_not_consult_the_observation_session():
    source = open('backend/api/bot_api.py', encoding='utf-8').read()
    assert '@router.get("/status"' in source
    assert 'tradingai_observation_session' not in source
    client, _transport, exchanger, _clock = _ready([{'keys': [_jwk(_PRIVATE)]}])

    @client.app.get('/api/bot/status')
    def bot_status():
        return {'status': 'UNCHANGED_BY_OBSERVATION'}

    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0])
    _callback(client, query)
    cookie = client.cookies.get(SESSION_COOKIE)
    response = client.get(
        '/api/bot/status', headers={'cookie': SESSION_COOKIE + '=' + cookie})
    assert response.json() == {'status': 'UNCHANGED_BY_OBSERVATION'}


def test_f11d14_37_default_mount_stays_off_and_does_not_fetch_jwks():
    calls = []

    class Recording:
        def get_bytes(self, url):
            calls.append(url)
            raise AssertionError(url)

    app = FastAPI()
    mount_observation_oidc(app, transport=Recording())
    client = TestClient(app)
    assert client.get('/api/observation/auth/oidc/start', follow_redirects=False).status_code == 403
    assert client.get('/api/observation/auth/oidc/status').status_code == 401
    assert calls == []


def test_f11d14_38_tests_do_not_open_a_google_connection(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError('network')

    monkeypatch.setattr(http.client.HTTPSConnection, 'request', blocked)
    client, transport, exchanger, _clock = _ready([{'keys': [_jwk(_PRIVATE)]}])
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0])
    assert _callback(client, query).status_code == 200
    assert set(transport.calls) <= {DISCOVERY_URL, JWKS_URL}
    mocked = Transport()
    mocked.documents = [{'keys': [_jwk(_PRIVATE)]}]
    loaded = GoogleJwksClient(mocked, Clock().time).keys()
    assert isinstance(loaded, dict) and 'test-key' in loaded


def test_f11d14_39_no_authenticated_exchange_call():
    source = open('backend/observation_auth/oidc_jwks.py', encoding='utf-8').read()
    assert 'kucoin_trade' not in source
    assert 'api-futures.kucoin.com' not in source
    gate = stage_b_execution_gate()
    assert gate['exchange_calls'] == 0
    assert gate['stage_b_execution_ready'] is False


def test_f11d14_40_no_production_configuration_is_written():
    for name in (
        'backend/observation_auth/oidc_jwks.py',
        'backend/observation_auth/oidc_mount.py',
        'backend/observation_auth/oidc_api.py',
    ):
        source = open(name, encoding='utf-8').read()
        assert 'os.environ' not in source
        assert '/etc/tradingai' not in source
        assert 'kucoin_position_stage_b_adapter' not in source
        assert 'observation_approval_authority' not in source
    sample = json.load(open(
        'backend/observation_auth/observation_oidc.sample.json', encoding='utf-8'))
    assert sample['enabled'] is False
    assert 'client_secret' not in sample
