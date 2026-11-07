"""PKCE token exchange and config injection.  No live Google connection."""
import base64
import hashlib
import http.client
import json
import os
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.auth.api import create_operator_auth_router
from backend.auth.auth_config import OperatorAuthConfig
from backend.auth.dependencies import require_operator_session
from backend.auth.operator_auth import OperatorAuthenticator, hash_operator_credential
from backend.auth.operator_session import COOKIE_NAME, OperatorSessionManager
from backend.auth.session_middleware import OperatorSessionMiddleware
from backend.observation_auth.oidc_api import (
    CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE, observation_session_authorizes_trading,
    stage_b_execution_gate)
from backend.observation_auth.oidc_config import (
    CANONICAL_REDIRECT_URI, EXPECTED_ISSUER, GOOGLE_CLIENT_TYPE,
    TOKEN_ENDPOINT, TOKEN_ENDPOINT_AUTH_METHOD, ObservationOidcConfig)
from backend.observation_auth.oidc_exchange import (
    GooglePkceTokenExchanger, TokenExchangeError, UrllibTokenTransport)
from backend.observation_auth.oidc_jwks import DISCOVERY_URL, JWKS_URL
from backend.observation_auth.oidc_mount import mount_observation_oidc
from backend.observation_auth.oidc_settings import (
    ENV_ALLOWLIST, ENV_CLIENT_ID, ENV_CLIENT_SECRET, ENV_ENABLED, ENV_REDIRECT_URI,
    ENV_SESSION_SECRET, ENV_SESSION_TTL, load_observation_oidc_settings)
from backend.observation_auth.oidc_tokens import public_key_from_jwk, verify_id_token
from tools.work_aa.observation_operator_identity import OBSERVATION_PERMISSION


SUBJECT = 'google-subject-1'
SECRET = 'c' * 32
SESSION_SECRET = 'o' * 32
CLIENT_ID = 'example-client.apps.googleusercontent.com'
NOW = 1_700_000_000
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


class JwksTransport:
    def __init__(self, key=_PRIVATE, kid='test-key'):
        self.calls = []
        self.key = key
        self.kid = kid
        self.discovery = _discovery()

    def get_bytes(self, url):
        self.calls.append(url)
        if url == DISCOVERY_URL:
            return json.dumps(self.discovery).encode('utf-8')
        if url != JWKS_URL:
            raise AssertionError(url)
        return json.dumps({'keys': [_jwk(self.key, self.kid)]}).encode('utf-8')


class TokenTransport:
    def __init__(self):
        self.gets = []
        self.posts = []
        self.discovery = _discovery()
        self.status = 200
        self.body = None
        self.get_error = None
        self.post_error = None

    def get_bytes(self, url):
        self.gets.append(url)
        if self.get_error is not None:
            raise self.get_error
        return json.dumps(self.discovery).encode('utf-8')

    def post_form(self, url, body, headers, timeout):
        self.posts.append({
            'url': url, 'body': body, 'headers': dict(headers), 'timeout': timeout})
        if self.post_error is not None:
            raise self.post_error
        payload = self.body if self.body is not None else b'{}'
        return self.status, payload


def _b64(raw):
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def _jwk(key, kid='test-key'):
    numbers = key.public_key().public_numbers()
    return {
        'kty': 'RSA', 'alg': 'RS256', 'kid': kid, 'use': 'sig',
        'n': _b64(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, 'big')),
        'e': _b64(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, 'big')),
    }


def _sign(payload, private=_PRIVATE, kid='test-key'):
    header = _b64(json.dumps({'alg': 'RS256', 'kid': kid}, separators=(',', ':')).encode())
    body = _b64(json.dumps(payload, separators=(',', ':')).encode())
    signing = (header + '.' + body).encode('ascii')
    signature = private.sign(signing, padding.PKCS1v15(), hashes.SHA256())
    return header + '.' + body + '.' + _b64(signature)


def _discovery(**overrides):
    document = {
        'issuer': EXPECTED_ISSUER,
        'authorization_endpoint': 'https://accounts.google.com/o/oauth2/v2/auth',
        'token_endpoint': TOKEN_ENDPOINT,
        'jwks_uri': JWKS_URL,
        'token_endpoint_auth_methods_supported': ['client_secret_post', 'client_secret_basic'],
        'code_challenge_methods_supported': ['plain', 'S256'],
        'id_token_signing_alg_values_supported': ['RS256'],
    }
    document.update(overrides)
    return document


def _allowlist(subject=SUBJECT, permission=OBSERVATION_PERMISSION, enabled=True):
    return [{
        'issuer': EXPECTED_ISSUER,
        'subject': subject,
        'permission': permission,
        'enabled': enabled,
    }]


def _env(**overrides):
    values = {
        ENV_ENABLED: 'true',
        ENV_CLIENT_ID: CLIENT_ID,
        ENV_CLIENT_SECRET: SECRET,
        ENV_SESSION_SECRET: SESSION_SECRET,
        ENV_REDIRECT_URI: CANONICAL_REDIRECT_URI,
        ENV_ALLOWLIST: json.dumps(_allowlist()),
    }
    values.update(overrides)
    return values


def _config_mapping(**overrides):
    raw = {
        'enabled': True,
        'issuer': EXPECTED_ISSUER,
        'client_id': CLIENT_ID,
        'client_secret': SECRET,
        'redirect_uri': 'http://testserver/api/observation/auth/oidc/callback',
        'session_secret': SESSION_SECRET,
        'secure_cookie': False,
        'insecure_redirect_allowed': True,
        'allowlist': _allowlist(),
    }
    raw.update(overrides)
    return raw


def _token(nonce, **overrides):
    payload = {
        'iss': EXPECTED_ISSUER,
        'aud': CLIENT_ID,
        'sub': SUBJECT,
        'nonce': nonce,
        'iat': NOW,
        'exp': NOW + 300,
    }
    payload.update(overrides)
    kid = payload.pop('kid', 'test-key')
    private = payload.pop('private', _PRIVATE)
    return _sign(payload, private=private, kid=kid)


def _mount(token_transport, jwks_transport=None, clock=None, **overrides):
    clock = clock or Clock()
    app = FastAPI()
    authority = {'realOrderAllowed': False, 'changed': False}
    mount_observation_oidc(
        app,
        ObservationOidcConfig(_config_mapping(**overrides)),
        transport=jwks_transport or JwksTransport(),
        token_transport=token_transport,
        now=clock.time,
        monotonic=clock.monotonic,
    )

    def _protected():
        def route(request: Request):
            require_operator_session(request)
            authority['changed'] = True
            return {'status': 'MUTATED'}
        return route

    for path in (
        '/api/bot/start',
        '/api/bot/stop',
        '/api/bot/loop/start',
        '/api/bot/manual-trade',
        '/api/bot/live-order',
        '/api/bot/paper-order',
        '/api/bot/stage-b/approve',
        '/api/bot/authority',
    ):
        app.post(path)(_protected())
    app.state.authority = authority
    return app, clock


def _start(client):
    response = client.get('/api/observation/auth/oidc/start', follow_redirects=False)
    assert response.status_code == 302, response.text
    query = parse_qs(urlparse(response.headers['location']).query)
    return response, query


def _callback(client, query, **params):
    payload = {'code': 'auth-code', 'state': query['state'][0]}
    payload.update(params)
    return client.get('/api/observation/auth/oidc/callback', params=payload, follow_redirects=False)


def _arm(transport, query, **overrides):
    nonce = overrides.pop('nonce', query['nonce'][0])
    transport.body = json.dumps({
        'access_token': 'hidden-access',
        'expires_in': 300,
        'id_token': _token(nonce, **overrides),
        'token_type': 'Bearer',
    }).encode('utf-8')


def test_f11d25_01_default_off_ignores_credentials():
    secret = 'z' * 40
    result = load_observation_oidc_settings({
        ENV_ENABLED: 'TRUE',
        ENV_CLIENT_ID: CLIENT_ID,
        ENV_CLIENT_SECRET: secret,
        ENV_SESSION_SECRET: SESSION_SECRET,
    })
    assert result.enabled_requested is False
    assert result.secret_values_retained is False
    assert result.config.client_secret == ''
    assert result.config.disabled_reason() == 'FEATURE_DISABLED'
    assert result.public_view()['effective_enabled'] is False
    assert secret not in repr(result)
    assert secret not in repr(result.config)
    empty = load_observation_oidc_settings({})
    assert empty.config.disabled_reason() == 'FEATURE_DISABLED'
    app = mount_observation_oidc(FastAPI(), empty.config, token_transport=TokenTransport())
    response = TestClient(app).get('/api/observation/auth/oidc/start', follow_redirects=False)
    assert response.status_code == 403
    assert response.json()['reason'] == 'FEATURE_DISABLED'
    assert response.json()['stage_b_execution_ready'] is False


def test_f11d25_02_valid_configuration_is_accepted_and_redacted():
    result = load_observation_oidc_settings(_env())
    assert result.public_view()['effective_enabled'] is True
    assert result.public_view()['google_client_type'] == GOOGLE_CLIENT_TYPE
    assert result.public_view()['token_endpoint_auth_method'] == TOKEN_ENDPOINT_AUTH_METHOD
    assert result.config.disabled_reason() is None
    assert SECRET not in repr(result)
    assert SESSION_SECRET not in repr(result.public_view())
    blob = json.dumps(result.public_view())
    assert SECRET not in blob
    assert SESSION_SECRET not in blob


def test_f11d25_03_missing_and_invalid_configuration_fail_closed():
    missing = load_observation_oidc_settings(_env(**{ENV_CLIENT_ID: ''}))
    assert missing.config.disabled_reason() == 'MISSING_CONFIGURATION'
    absent_secret = load_observation_oidc_settings(_env())
    removed = dict(_env())
    removed.pop(ENV_CLIENT_SECRET)
    assert load_observation_oidc_settings(removed).config.disabled_reason() == 'MISSING_CLIENT_SECRET'
    assert ObservationOidcConfig(_config_mapping(client_secret='short')).disabled_reason() == 'INVALID_CLIENT_SECRET'
    malformed = load_observation_oidc_settings(_env(**{ENV_ALLOWLIST: '{'}))
    assert malformed.config.disabled_reason() == 'MALFORMED_ALLOWLIST'
    assert malformed.secret_values_retained is False
    assert malformed.config.client_secret == ''
    bad_ttl = load_observation_oidc_settings(_env(**{ENV_SESSION_TTL: 'forever'}))
    assert bad_ttl.config.disabled_reason() == 'INVALID_CONFIGURATION'
    wrong_redirect = load_observation_oidc_settings(_env(**{
        ENV_REDIRECT_URI: 'https://evil.example/api/observation/auth/oidc/callback'}))
    assert wrong_redirect.config.disabled_reason() == 'INVALID_REDIRECT_URI'
    slash = load_observation_oidc_settings(_env(**{ENV_REDIRECT_URI: CANONICAL_REDIRECT_URI + '/'}))
    assert slash.config.disabled_reason() == 'INVALID_REDIRECT_URI'
    forbidden = ObservationOidcConfig(_config_mapping(allowlist=_allowlist(permission='BOT_START')))
    assert forbidden.disabled_reason() == 'UNAUTHORIZED_PERMISSION'
    live = ObservationOidcConfig(_config_mapping(allowlist=_allowlist(permission='LIVE_ARM')))
    assert live.disabled_reason() == 'UNAUTHORIZED_PERMISSION'
    operator = ObservationOidcConfig(_config_mapping(allowlist=_allowlist(subject='operator')))
    assert operator.disabled_reason() == 'MISSING_ALLOWLIST'
    assert SECRET not in json.dumps(wrong_redirect.public_view())


def test_f11d25_04_client_authentication_is_form_post_with_pkce_verifier():
    transport = TokenTransport()
    app, _clock = _mount(transport)
    client = TestClient(app)
    _response, query = _start(client)
    verifier_challenge = query['code_challenge'][0]
    assert query['code_challenge_method'] == ['S256']
    _arm(transport, query)
    response = _callback(client, query)
    assert response.status_code == 200, response.text
    assert len(transport.posts) == 1
    posted = transport.posts[0]
    assert posted['url'] == TOKEN_ENDPOINT
    assert posted['timeout'] == 5.0
    assert 'authorization' not in {name.lower() for name in posted['headers']}
    form = parse_qs(posted['body'].decode('ascii'))
    assert form['grant_type'] == ['authorization_code']
    assert form['client_id'] == [CLIENT_ID]
    assert form['client_secret'] == [SECRET]
    assert form['redirect_uri'] == ['http://testserver/api/observation/auth/oidc/callback']
    assert form['code'] == ['auth-code']
    verifier = form['code_verifier'][0]
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    assert _b64(digest) == verifier_challenge
    assert SECRET not in response.text
    assert 'hidden-access' not in response.text
    assert response.json()['trading_authority'] is False
    assert response.json()['permission'] == OBSERVATION_PERMISSION


def test_f11d25_05_redirect_state_nonce_expiry_and_replay_fail_before_retry():
    mismatch = GooglePkceTokenExchanger(
        client_id=CLIENT_ID, client_secret=SECRET, redirect_uri=CANONICAL_REDIRECT_URI,
        transport=TokenTransport())
    rejected = mismatch.exchange('auth-code', 'a' * 43, 'https://evil.example/callback')
    assert rejected.reason == 'REDIRECT_URI_MISMATCH'
    assert mismatch._transport.posts == []
    bad_verifier = mismatch.exchange('auth-code', 'short', CANONICAL_REDIRECT_URI)
    assert bad_verifier.reason == 'PKCE_VERIFIER_REJECTED'
    assert mismatch._transport.posts == []

    transport = TokenTransport()
    app, clock = _mount(transport)
    client = TestClient(app)
    _response, query = _start(client)
    wrong_state = client.get('/api/observation/auth/oidc/callback', params={
        'code': 'auth-code', 'state': 'other-state'})
    assert wrong_state.json()['reason'] == 'STATE_MISMATCH'
    assert transport.posts == []
    _arm(transport, query, nonce='n' * len(query['nonce'][0]))
    nonce = _callback(client, query)
    assert nonce.json()['reason'] == 'NONCE_MISMATCH'
    assert len(transport.posts) == 1

    transport = TokenTransport()
    app, clock = _mount(transport)
    client = TestClient(app)
    _response, query = _start(client)
    clock.mono += 301
    _arm(transport, query)
    expired = _callback(client, query)
    assert expired.json()['reason'] == 'EXPIRED_STATE'
    assert transport.posts == []

    transport = TokenTransport()
    app, _clock = _mount(transport)
    client = TestClient(app)
    _response, query = _start(client)
    transport.status = 400
    transport.body = b'{"error":"invalid_grant"}'
    first = _callback(client, query)
    assert first.json()['reason'] == 'TOKEN_ENDPOINT_HTTP_ERROR'
    assert 'invalid_grant' not in first.text
    second = _callback(client, query)
    assert second.json()['reason'] == 'STATE_REPLAY'
    assert len(transport.posts) == 1


def test_f11d25_06_token_endpoint_failures_are_safe():
    transport = TokenTransport()
    transport.post_error = TimeoutError('slow')
    app, _clock = _mount(transport)
    client = TestClient(app)
    _response, query = _start(client)
    timed = _callback(client, query)
    assert timed.json()['reason'] == 'TOKEN_ENDPOINT_TIMEOUT'
    assert 'slow' not in timed.text
    assert len(transport.posts) == 1

    transport = TokenTransport()
    transport.post_error = RuntimeError('leaked-' + SECRET)
    app, _clock = _mount(transport)
    client = TestClient(app)
    _response, query = _start(client)
    leaked = _callback(client, query)
    assert leaked.json()['reason'] == 'TOKEN_EXCHANGE_FAILED'
    assert SECRET not in leaked.text
    assert 'leaked-' not in leaked.text

    transport = TokenTransport()
    transport.body = b'[]'
    app, _clock = _mount(transport)
    client = TestClient(app)
    _response, query = _start(client)
    malformed = _callback(client, query)
    assert malformed.json()['reason'] == 'MALFORMED_TOKEN_RESPONSE'
    transport = TokenTransport()
    transport.discovery = _discovery(token_endpoint_auth_methods_supported=['none'])
    app, _clock = _mount(transport)
    client = TestClient(app)
    _response, query = _start(client)
    _arm(transport, query)
    metadata = _callback(client, query)
    assert metadata.json()['reason'] == 'PROVIDER_METADATA_MISMATCH'
    assert transport.posts == []


def test_f11d25_07_id_token_rejections_and_unknown_subject():
    cases = (
        ({'private': _OTHER}, 'INVALID_SIGNATURE'),
        ({'iss': 'https://evil.example'}, 'WRONG_ISSUER'),
        ({'aud': 'other-client'}, 'WRONG_AUDIENCE'),
        ({'aud': [CLIENT_ID, 'other-client']}, 'WRONG_AUDIENCE'),
        ({'exp': NOW - 1}, 'EXPIRED'),
        ({'sub': 'someone-else'}, 'UNAUTHORIZED_SUBJECT'),
        ({'kid': 'missing-key'}, 'UNKNOWN_SIGNING_KEY'),
    )
    for overrides, reason in cases:
        transport = TokenTransport()
        app, _clock = _mount(transport)
        client = TestClient(app)
        _response, query = _start(client)
        payload_overrides = dict(overrides)
        if 'sub' in payload_overrides and reason == 'UNAUTHORIZED_SUBJECT':
            _arm(transport, query, **payload_overrides)
        else:
            _arm(transport, query, **payload_overrides)
        response = _callback(client, query)
        assert response.json()['reason'] == reason
        assert SECRET not in response.text

    transport = TokenTransport()
    app, _clock = _mount(transport)
    client = TestClient(app)
    _response, query = _start(client)
    body = json.loads(base64.urlsafe_b64decode(_token(query['nonce'][0]).split('.')[1] + '=='))
    del body['sub']
    transport.body = json.dumps({
        'id_token': _sign(body),
        'token_type': 'Bearer',
        'expires_in': 60,
    }).encode('utf-8')
    missing = _callback(client, query)
    assert missing.json()['reason'] == 'MISSING_SUBJECT'
    checked = verify_id_token(
        _sign(body), keys={'test-key': public_key_from_jwk(_jwk(_PRIVATE))},
        issuer=EXPECTED_ISSUER, audience=CLIENT_ID,
        nonce=query['nonce'][0], now=NOW, skew=60)
    assert checked == 'MISSING_SUBJECT'


def test_f11d25_08_observation_session_cannot_change_trading_authority():
    transport = TokenTransport()
    app, _clock = _mount(transport)
    manager = OperatorSessionManager('s' * 32, session_ttl_seconds=300)
    auth_config = OperatorAuthConfig(secure_cookie=False)
    app.add_middleware(OperatorSessionMiddleware, session_manager=manager, config=auth_config)
    app.include_router(create_operator_auth_router(
        OperatorAuthenticator(hash_operator_credential('correct-horse')),
        manager, auth_config))
    client = TestClient(app)
    _response, query = _start(client)
    _arm(transport, query)
    logged = _callback(client, query)
    assert logged.status_code == 200
    assert observation_session_authorizes_trading(client.cookies.get(SESSION_COOKIE)) is False
    assert client.get('/api/auth/status').json()['status'] == 'UNAUTHENTICATED'
    for path in (
        '/api/bot/start',
        '/api/bot/stop',
        '/api/bot/loop/start',
        '/api/bot/manual-trade',
        '/api/bot/live-order',
        '/api/bot/paper-order',
        '/api/bot/stage-b/approve',
        '/api/bot/authority',
    ):
        response = client.post(path)
        assert response.status_code == 401
    assert app.state.authority == {'realOrderAllowed': False, 'changed': False}
    gate = stage_b_execution_gate('LIVE', approve=True)
    assert gate['decision'] == 'DENY'
    assert gate['stage_b_execution_ready'] is False
    assert gate['exchange_calls'] == 0
    operator = client.post('/api/auth/login', json={'credential': 'correct-horse'})
    assert operator.status_code == 200
    assert COOKIE_NAME in ' '.join(operator.headers.get_list('set-cookie'))
    csrf = client.cookies.get(CSRF_COOKIE)
    observation_logout = client.post(
        '/api/observation/auth/oidc/logout', headers={CSRF_HEADER: csrf})
    assert observation_logout.json()['status'] == 'UNAUTHENTICATED'
    joined = ' '.join(observation_logout.headers.get_list('set-cookie'))
    assert SESSION_COOKIE in joined
    assert COOKIE_NAME + '=' not in joined
    assert client.get('/api/auth/status').json()['status'] == 'AUTHENTICATED'
    assert client.get('/api/observation/auth/oidc/status').status_code == 401
    assert client.post('/api/bot/start').status_code == 200
    assert app.state.authority['changed'] is True


def test_f11d25_09_exchange_transport_rejects_unpinned_urls_without_connecting(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError('network')

    monkeypatch.setattr(http.client.HTTPSConnection, '__init__', blocked)
    transport = UrllibTokenTransport()
    with pytest.raises(TokenExchangeError) as caught:
        transport.post_form('http://oauth2.googleapis.com/token', b'code=1', {}, 1.0)
    assert caught.value.reason == 'TOKEN_ENDPOINT_REJECTED'
    with pytest.raises(TokenExchangeError) as caught:
        transport.post_form('https://evil.example/token', b'code=1', {}, 1.0)
    assert caught.value.reason == 'TOKEN_ENDPOINT_REJECTED'


def test_f11d25_10_loader_and_exchange_do_not_read_production_files_or_log_secrets():
    copied = dict(os.environ)
    for name in (
        ENV_ENABLED, ENV_CLIENT_ID, ENV_CLIENT_SECRET, ENV_SESSION_SECRET,
        ENV_REDIRECT_URI, ENV_ALLOWLIST, ENV_SESSION_TTL,
    ):
        copied.pop(name, None)
    isolated = load_observation_oidc_settings(copied)
    assert isolated.config.disabled_reason() == 'FEATURE_DISABLED'
    assert os.environ.get(ENV_CLIENT_SECRET) == copied.get(ENV_CLIENT_SECRET)
    names = (
        'backend/observation_auth/oidc_settings.py',
        'backend/observation_auth/oidc_exchange.py',
        'backend/observation_auth/oidc_config.py',
        'backend/main.py',
    )
    for name in names:
        source = open(name, encoding='utf-8').read()
        assert 'print(' not in source
        assert 'logging.' not in source
        assert '/etc/tradingai' not in source
        assert SECRET not in source
        assert 'kucoin_trade' not in source
    sample = json.load(open(
        'backend/observation_auth/observation_oidc.sample.json', encoding='utf-8'))
    assert sample['enabled'] is False
    assert 'client_secret' not in sample
    main = open('backend/main.py', encoding='utf-8').read()
    assert 'mount_observation_oidc(app, load_observation_oidc_settings().config)' in main


def test_f11d26_01_review_rejects_extra_audience_weak_secrets_and_duplicate_keys():
    spaces = ObservationOidcConfig(_config_mapping(session_secret=' ' * 16))
    assert spaces.disabled_reason() == 'INVALID_SESSION_SECRET'
    long_secret = ObservationOidcConfig(_config_mapping(client_secret='c' * 257))
    assert long_secret.disabled_reason() == 'INVALID_CLIENT_SECRET'
    wide = ObservationOidcConfig(_config_mapping(
        allowlist=_allowlist(subject='x' * 256)))
    assert wide.disabled_reason() == 'MISSING_ALLOWLIST'
    duplicated = (
        '[{"issuer":"https://accounts.google.com","subject":"one",'
        '"subject":"two","permission":"WORK_AA_READONLY_POSITION_OBSERVATION_APPROVER",'
        '"enabled":true}]'
    )
    parsed = load_observation_oidc_settings(_env(**{ENV_ALLOWLIST: duplicated}))
    assert parsed.config.disabled_reason() == 'MALFORMED_ALLOWLIST'
    assert parsed.secret_values_retained is False
    header = _b64(json.dumps(
        {'alg': 'RS256', 'kid': 'test-key', 'crit': ['bork']},
        separators=(',', ':')).encode())
    body = _b64(json.dumps({'sub': SUBJECT}, separators=(',', ':')).encode())
    crit = verify_id_token(
        header + '.' + body + '.aa', keys={'test-key': public_key_from_jwk(_jwk(_PRIVATE))},
        issuer=EXPECTED_ISSUER, audience=CLIENT_ID, nonce='n', now=NOW, skew=60)
    assert crit == 'ALGORITHM_REJECTED'

    class _BadKey:
        def verify(self, *_args, **_kwargs):
            raise RuntimeError('secret-material')

    signed = _token('n' * 8)
    failed = verify_id_token(
        signed, keys={'test-key': _BadKey()}, issuer=EXPECTED_ISSUER,
        audience=CLIENT_ID, nonce='n' * 8, now=NOW, skew=60)
    assert failed == 'INVALID_SIGNATURE'
    transport = TokenTransport()
    transport.body = (
        b'{"id_token":"a.b.c","id_token":"d.e.f","token_type":"Bearer"}'
    )
    app, _clock = _mount(transport)
    client = TestClient(app)
    _response, query = _start(client)
    response = _callback(client, query)
    assert response.json()['reason'] == 'MALFORMED_TOKEN_RESPONSE'
    assert 'd.e.f' not in response.text
