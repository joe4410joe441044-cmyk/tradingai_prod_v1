"""Offline Google OIDC flow.  The token exchanger and JWKS are in-process."""
import base64
import hashlib
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
    CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE, TXN_COOKIE,
    create_observation_oidc_router, observation_session_authorizes_trading,
    stage_b_execution_gate)
from backend.observation_auth.oidc_config import ObservationOidcConfig
from tools.work_aa.observation_operator_identity import OBSERVATION_PERMISSION


SUBJECT = 'google-subject-1'
NOW = 1_700_000_000
REDIRECT = 'http://testserver/api/observation/auth/oidc/callback'
_PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


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
        self.seen = None

    def exchange(self, code, verifier, redirect_uri):
        self.seen = (code, verifier, redirect_uri)
        return self.token


class KeySet:
    def __init__(self, keys):
        self._keys = keys

    def keys(self):
        return self._keys


def _b64(raw):
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def _jwk(key):
    numbers = key.public_key().public_numbers()
    return {
        'kty': 'RSA',
        'alg': 'RS256',
        'kid': 'test-key',
        'n': _b64(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, 'big')),
        'e': _b64(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, 'big')),
    }


def _sign(payload, private=_PRIVATE, kid='test-key'):
    header = _b64(json.dumps({'alg': 'RS256', 'kid': kid}, separators=(',', ':')).encode())
    body = _b64(json.dumps(payload, separators=(',', ':')).encode())
    signing = (header + '.' + body).encode('ascii')
    signature = private.sign(signing, padding.PKCS1v15(), hashes.SHA256())
    return header + '.' + body + '.' + _b64(signature)


def _config(**overrides):
    raw = {
        'enabled': True,
        'issuer': 'https://accounts.google.com',
        'client_id': 'example-client.apps.googleusercontent.com',
        'redirect_uri': REDIRECT,
        'client_secret': 'c' * 32,
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


def _app(config=None, exchanger=None, jwks=None, clock=None):
    clock = clock or Clock()
    exchanger = exchanger or Exchanger()
    if jwks is None:
        from backend.observation_auth.oidc_tokens import public_key_from_jwk
        jwks = KeySet({'test-key': public_key_from_jwk(_jwk(_PRIVATE))})
    app = FastAPI()
    app.include_router(create_observation_oidc_router(
        config or _config(), exchanger=exchanger, jwks=jwks,
        now=clock.time, monotonic=clock.monotonic))

    @app.post('/api/bot/start')
    def bot_start(request: Request):
        require_operator_session(request)
        return {'status': 'STARTED'}

    return app, exchanger, clock


def _token(nonce, **overrides):
    payload = {
        'iss': 'https://accounts.google.com',
        'aud': 'example-client.apps.googleusercontent.com',
        'sub': SUBJECT,
        'nonce': nonce,
        'iat': NOW,
        'exp': NOW + 300,
        'email': 'person@example.com',
    }
    payload.update(overrides)
    return _sign(payload)


def _start(client):
    response = client.get('/api/observation/auth/oidc/start', follow_redirects=False)
    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers['location']).query)
    return response, query


def _login(client, query):
    return client.get(
        '/api/observation/auth/oidc/callback',
        params={'code': 'auth-code', 'state': query['state'][0]},
        follow_redirects=False)


def test_f11d13_01_feature_flag_off_rejects_start():
    app, _exchanger, _clock = _app(_config(enabled=False))
    response = TestClient(app).get('/api/observation/auth/oidc/start')
    assert response.status_code == 403
    assert response.json()['reason'] == 'FEATURE_DISABLED'
    assert 'location' not in response.headers


def test_f11d13_02_missing_configuration_fails_closed():
    app, _exchanger, _clock = _app(_config(client_id=''))
    response = TestClient(app).get('/api/observation/auth/oidc/start')
    assert response.status_code == 403
    assert response.json()['reason'] == 'MISSING_CONFIGURATION'


def test_f11d13_03_start_redirects_only_to_the_google_authorization_endpoint():
    app, _exchanger, _clock = _app()
    response, query = _start(TestClient(app))
    location = urlparse(response.headers['location'])
    assert location.scheme == 'https'
    assert location.netloc == 'accounts.google.com'
    assert location.path == '/o/oauth2/v2/auth'
    assert query['response_type'] == ['code']
    assert query['scope'] == ['openid']


def test_f11d13_04_start_uses_pkce_s256():
    app, exchanger, _clock = _app()
    client = TestClient(app)
    _response, query = _start(client)
    assert query['code_challenge_method'] == ['S256']
    _login(client, query)
    verifier = exchanger.seen[1]
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    challenge = base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')
    assert query['code_challenge'] == [challenge]


def test_f11d13_05_state_mismatch_is_denied():
    app, _exchanger, _clock = _app()
    client = TestClient(app)
    _response, query = _start(client)
    response = client.get('/api/observation/auth/oidc/callback', params={
        'code': 'auth-code', 'state': 'other-state'})
    assert response.status_code == 403
    assert response.json()['reason'] == 'STATE_MISMATCH'
    assert query['state'][0] != 'other-state'


def test_f11d13_06_state_replay_is_denied():
    app, exchanger, _clock = _app()
    client = TestClient(app)
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0])
    first = _login(client, query)
    client.cookies.set(TXN_COOKIE, query['state'][0], path='/api/observation')
    second = _login(client, query)
    assert first.status_code == 200
    assert second.status_code == 403
    assert second.json()['reason'] == 'STATE_REPLAY'


def test_f11d13_07_expired_state_is_denied():
    app, exchanger, clock = _app()
    client = TestClient(app)
    _response, query = _start(client)
    clock.mono += 301
    exchanger.token = _token(query['nonce'][0])
    response = _login(client, query)
    assert response.status_code == 403
    assert response.json()['reason'] == 'EXPIRED_STATE'


def test_f11d13_08_missing_nonce_is_denied():
    app, exchanger, _clock = _app()
    client = TestClient(app)
    _response, query = _start(client)
    payload = json.loads(base64.urlsafe_b64decode(_token(query['nonce'][0]).split('.')[1] + '=='))
    del payload['nonce']
    exchanger.token = _sign(payload)
    response = _login(client, query)
    assert response.status_code == 403
    assert response.json()['reason'] == 'MISSING_NONCE'


def test_f11d13_09_nonce_mismatch_is_denied():
    app, exchanger, _clock = _app()
    client = TestClient(app)
    _response, query = _start(client)
    exchanger.token = _token('x' * len(query['nonce'][0]))
    response = _login(client, query)
    assert response.status_code == 403
    assert response.json()['reason'] == 'NONCE_MISMATCH'


def test_f11d13_10_invalid_signature_is_denied():
    app, exchanger, _clock = _app()
    client = TestClient(app)
    _response, query = _start(client)
    body = json.loads(base64.urlsafe_b64decode(_token(query['nonce'][0]).split('.')[1] + '=='))
    exchanger.token = _sign(body, private=_OTHER)
    response = _login(client, query)
    assert response.status_code == 403
    assert response.json()['reason'] == 'INVALID_SIGNATURE'


def test_f11d13_11_wrong_issuer_is_denied():
    app, exchanger, _clock = _app()
    client = TestClient(app)
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0], iss='https://evil.example')
    response = _login(client, query)
    assert response.json()['reason'] == 'WRONG_ISSUER'


def test_f11d13_12_wrong_audience_is_denied():
    app, exchanger, _clock = _app()
    client = TestClient(app)
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0], aud='other-client')
    response = _login(client, query)
    assert response.json()['reason'] == 'WRONG_AUDIENCE'


def test_f11d13_13_expired_token_is_denied():
    app, exchanger, _clock = _app()
    client = TestClient(app)
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0], exp=NOW - 1)
    response = _login(client, query)
    assert response.json()['reason'] == 'EXPIRED'


def test_f11d13_14_future_issued_token_is_denied():
    app, exchanger, _clock = _app()
    client = TestClient(app)
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0], iat=NOW + 120)
    response = _login(client, query)
    assert response.json()['reason'] == 'FUTURE_ISSUED'


def test_f11d13_15_unknown_signing_key_is_denied():
    app, exchanger, _clock = _app()
    client = TestClient(app)
    _response, query = _start(client)
    body = json.loads(base64.urlsafe_b64decode(_token(query['nonce'][0]).split('.')[1] + '=='))
    exchanger.token = _sign(body, kid='missing-key')
    response = _login(client, query)
    assert response.json()['reason'] == 'UNKNOWN_SIGNING_KEY'


def test_f11d13_16_jwks_unavailable_is_denied():
    app, exchanger, _clock = _app(jwks=KeySet(None))
    client = TestClient(app)
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0])
    response = _login(client, query)
    assert response.json()['reason'] == 'JWKS_UNAVAILABLE'


def test_f11d13_17_unknown_subject_is_denied():
    app, exchanger, _clock = _app()
    client = TestClient(app)
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0], sub='someone-else')
    response = _login(client, query)
    assert response.json()['reason'] == 'UNAUTHORIZED_SUBJECT'


def test_f11d13_18_disabled_subject_is_denied():
    entry = {
        'issuer': 'https://accounts.google.com', 'subject': SUBJECT,
        'permission': OBSERVATION_PERMISSION, 'enabled': False}
    app, exchanger, _clock = _app(_config(allowlist=[entry]))
    client = TestClient(app)
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0])
    response = _login(client, query)
    assert response.json()['reason'] == 'DISABLED_SUBJECT'


def test_f11d13_19_missing_observation_permission_fails_closed():
    entry = {
        'issuer': 'https://accounts.google.com', 'subject': SUBJECT,
        'permission': 'LIVE_ARM', 'enabled': True}
    app, _exchanger, _clock = _app(_config(allowlist=[entry]))
    response = TestClient(app).get('/api/observation/auth/oidc/start')
    assert response.status_code == 403
    assert response.json()['reason'] == 'UNAUTHORIZED_PERMISSION'


def test_f11d13_20_valid_subject_receives_an_observation_session():
    app, exchanger, _clock = _app()
    client = TestClient(app)
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0])
    response = _login(client, query)
    body = response.json()
    assert response.status_code == 200
    assert body['subject'] == SUBJECT
    assert body['permission'] == OBSERVATION_PERMISSION
    assert body['observation_authority'] is False
    assert 'id_token' not in body
    assert 'email' not in body
    status = client.get('/api/observation/auth/oidc/status')
    assert status.json()['subject'] == SUBJECT


def test_f11d13_21_expired_session_is_rejected():
    app, exchanger, clock = _app(_config(session_ttl_seconds=30))
    client = TestClient(app)
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0])
    assert _login(client, query).status_code == 200
    clock.mono += 31
    status = client.get('/api/observation/auth/oidc/status')
    assert status.status_code == 401


def test_f11d13_22_logout_invalidates_the_session():
    app, exchanger, _clock = _app()
    client = TestClient(app)
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0])
    logged = _login(client, query)
    csrf = client.cookies.get(CSRF_COOKIE)
    assert logged.status_code == 200
    denied = client.post('/api/observation/auth/oidc/logout')
    assert denied.status_code == 403
    assert denied.json()['reason'] == 'CSRF_REJECTED'
    logged_out = client.post(
        '/api/observation/auth/oidc/logout', headers={CSRF_HEADER: csrf})
    assert logged_out.json()['status'] == 'UNAUTHENTICATED'
    assert client.get('/api/observation/auth/oidc/status').status_code == 401


def test_f11d13_23_callback_replaces_a_pre_set_session_cookie():
    app, exchanger, _clock = _app()
    client = TestClient(app)
    _response, query = _start(client)
    client.cookies.set(SESSION_COOKIE, 'attacker.deadbeef', path='/api/observation')
    exchanger.token = _token(query['nonce'][0])
    response = _login(client, query)
    issued = [
        item for item in response.headers.get_list('set-cookie')
        if item.startswith(SESSION_COOKIE + '=')]
    assert issued
    assert 'attacker.deadbeef' not in issued[0]
    client.cookies.clear()
    client.cookies.set(
        SESSION_COOKIE, issued[0].split(';', 1)[0].split('=', 1)[1],
        path='/api/observation')
    assert client.get('/api/observation/auth/oidc/status').status_code == 200


def test_f11d13_24_logout_without_csrf_is_rejected():
    app, exchanger, _clock = _app()
    client = TestClient(app)
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0])
    _login(client, query)
    response = client.post(
        '/api/observation/auth/oidc/logout', headers={CSRF_HEADER: 'wrong-csrf-value'})
    assert response.status_code == 403
    assert response.json()['reason'] == 'CSRF_REJECTED'
    assert client.get('/api/observation/auth/oidc/status').status_code == 200


def test_f11d13_25_open_redirect_parameters_are_rejected():
    app, _exchanger, _clock = _app()
    response = TestClient(app).get(
        '/api/observation/auth/oidc/start', params={'next': 'https://evil.example'})
    assert response.status_code == 400
    assert response.json()['reason'] == 'OPEN_REDIRECT_REJECTED'


def test_f11d13_26_observation_cookie_is_not_the_trading_session_cookie():
    app, exchanger, _clock = _app()
    client = TestClient(app)
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0])
    response = _login(client, query)
    joined = ' '.join(response.headers.get_list('set-cookie'))
    assert SESSION_COOKIE in joined
    assert COOKIE_NAME not in joined
    assert 'tradingai_csrf=' not in joined


def test_f11d13_27_existing_login_still_returns_the_literal_operator():
    app, _exchanger, _clock = _app()
    stored = hash_operator_credential('correct-horse')
    app.include_router(create_operator_auth_router(
        OperatorAuthenticator(stored),
        OperatorSessionManager('s' * 32, session_ttl_seconds=300),
        OperatorAuthConfig(secure_cookie=False)))
    client = TestClient(app)
    response = client.post('/api/auth/login', json={'credential': 'correct-horse'})
    assert response.status_code == 200
    assert response.json()['identity'] == 'operator'
    assert client.get('/api/observation/auth/oidc/status').status_code == 401


def test_f11d13_28_observation_session_cannot_start_the_bot():
    app, exchanger, _clock = _app()
    client = TestClient(app, raise_server_exceptions=False)
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0])
    _login(client, query)
    response = client.post('/api/bot/start')
    assert response.status_code == 401
    assert observation_session_authorizes_trading(
        client.cookies.get(SESSION_COOKIE)) is False


def test_f11d13_29_approval_gate_stays_disabled_after_login():
    app, exchanger, _clock = _app()
    client = TestClient(app)
    _response, query = _start(client)
    exchanger.token = _token(query['nonce'][0])
    body = _login(client, query).json()
    gate = stage_b_execution_gate()
    assert body['approval_gate'] == 'DISABLED'
    assert body['stage_b_execution_ready'] is False
    assert gate['decision'] == 'DENY'
    assert gate['stage_b_execution_ready'] is False


def test_f11d13_30_oidc_modules_do_not_call_the_exchange_or_google():
    names = (
        'backend/observation_auth/oidc_api.py',
        'backend/observation_auth/oidc_tokens.py',
        'backend/observation_auth/oidc_config.py',
    )
    for name in names:
        source = open(name, encoding='utf-8').read()
        assert 'import requests' not in source
        assert 'import httpx' not in source
        assert 'kucoin_trade' not in source
        assert 'kucoin_position_stage_b_adapter' not in source
        assert 'observation_approval_authority' not in source
        assert 'socket.' not in source
        assert 'os.environ' not in source
        assert '/etc/tradingai' not in source


def test_f11d13_31_secret_configuration_is_not_disclosed():
    secret = 'c' * 32
    app, _exchanger, _clock = _app(_config(client_secret=secret))
    response = TestClient(app).get(
        '/api/observation/auth/oidc/start', follow_redirects=False)
    assert response.status_code == 302
    assert secret not in response.headers['location']
    assert secret not in response.text
    denied_app, _exchanger, _clock = _app(_config(password='not-stored-value!!'))
    denied = TestClient(denied_app).get('/api/observation/auth/oidc/start')
    assert denied.status_code == 403
    assert denied.json()['reason'] == 'SECRET_CONFIG_REJECTED'
    assert 'not-stored' not in denied.text
