"""Observation-only Google OIDC routes.

These routes are not the trading login.  A verified subject does not receive
order authority, and the approval gate stays disabled.  No network client is
included; token exchange and JWKS come from injected test doubles.
"""
import secrets
from http.cookies import SimpleCookie
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from backend.observation_auth.oidc_config import AUTHORIZATION_ENDPOINT, ObservationOidcConfig
from backend.observation_auth.oidc_exchange import TokenExchangeResult
from backend.observation_auth.oidc_tokens import (
    ObservationSessionStore, TransactionStore, allowlist_decision, pkce_pair,
    token_kid, verify_id_token)
from tools.work_aa.observation_operator_identity import OBSERVATION_PERMISSION


SESSION_COOKIE = 'tradingai_observation_session'
CSRF_COOKIE = 'tradingai_observation_csrf'
TXN_COOKIE = 'tradingai_observation_oidc_txn'
CSRF_HEADER = 'X-TradingAI-Observation-CSRF'
COOKIE_PATH = '/api/observation'


class RefusingTokenExchanger:
    def exchange(self, code, verifier, redirect_uri):
        return None


class RefusingJwks:
    def keys(self):
        return None


def create_observation_oidc_router(
        config, *, exchanger=None, jwks=None, now=None, monotonic=None):
    if not isinstance(config, ObservationOidcConfig):
        config = ObservationOidcConfig(config)
    exchanger = exchanger or RefusingTokenExchanger()
    jwks = jwks or RefusingJwks()
    wall = now
    mono = monotonic
    transactions = TransactionStore(config.transaction_ttl_seconds, monotonic=mono)
    sessions = None
    if config.disabled_reason() is None:
        sessions = ObservationSessionStore(
            config.session_secret, config.session_ttl_seconds, monotonic=mono)
    router = APIRouter(prefix='/api/observation/auth/oidc')

    def deny(reason, status_code=403):
        return JSONResponse(
            status_code=status_code,
            content={'status': 'DENIED', 'reason': reason,
                     'approval_gate': 'DISABLED', 'stage_b_execution_ready': False})

    def current_session(request):
        if sessions is None:
            return None
        raw = request.cookies.get(SESSION_COOKIE)
        session_id = sessions.unsign(raw) if raw else None
        if session_id is None:
            return None
        row = sessions.read(session_id)
        if row is None:
            return None
        row['session_id'] = session_id
        return row

    @router.get('/start')
    def start(request: Request):
        reason = config.disabled_reason()
        if reason is not None:
            return deny(reason)
        if any(name in request.query_params for name in ('next', 'redirect', 'return_to')):
            return deny('OPEN_REDIRECT_REJECTED', 400)
        verifier, challenge = pkce_pair()
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        transactions.put(state, nonce, verifier)
        query = urlencode({
            'client_id': config.client_id,
            'redirect_uri': config.redirect_uri,
            'response_type': 'code',
            'scope': 'openid',
            'state': state,
            'nonce': nonce,
            'code_challenge': challenge,
            'code_challenge_method': 'S256',
        })
        response = RedirectResponse(AUTHORIZATION_ENDPOINT + '?' + query, status_code=302)
        _set_cookie(response, TXN_COOKIE, state, config, max_age=config.transaction_ttl_seconds)
        return response

    @router.get('/callback')
    def callback(request: Request, code: str = '', state: str = '', error: str = ''):
        reason = config.disabled_reason()
        if reason is not None:
            return deny(reason)
        if error:
            transactions.consume(state)
            return deny('OAUTH_ERROR')
        if not state or request.cookies.get(TXN_COOKIE) != state:
            return deny('STATE_MISMATCH')
        consumed = transactions.consume(state)
        if isinstance(consumed, str):
            return deny(consumed)
        issued = exchanger.exchange(code, consumed['verifier'], config.redirect_uri)
        if isinstance(issued, TokenExchangeResult):
            if not issued.ok:
                return deny(issued.reason or 'TOKEN_EXCHANGE_FAILED')
            issued = issued.id_token
        elif isinstance(issued, dict):
            issued = issued.get('id_token')
        if not isinstance(issued, str) or not issued:
            return deny('TOKEN_EXCHANGE_FAILED')
        if hasattr(jwks, 'keys_for'):
            key_set = jwks.keys_for(token_kid(issued))
        else:
            key_set = jwks.keys()
        if isinstance(key_set, str):
            return deny(key_set)
        verified = verify_id_token(
            issued, keys=key_set, issuer=config.issuer, audience=config.client_id,
            nonce=consumed['nonce'], now=int(wall()) if wall else 0,
            skew=config.clock_skew_seconds)
        if isinstance(verified, str):
            return deny(verified)
        listed = allowlist_decision(config.allowlist, config.issuer, verified['subject'])
        if listed is not None:
            return deny(listed)
        session_id = sessions.create(verified['subject'], config.issuer)
        csrf = secrets.token_hex(32)
        response = JSONResponse(status_code=200, content=_public_status(
            verified['subject']))
        _set_cookie(response, SESSION_COOKIE, sessions.sign(session_id), config,
                    max_age=config.session_ttl_seconds)
        _set_cookie(response, CSRF_COOKIE, csrf, config, http_only=False,
                    max_age=config.session_ttl_seconds)
        _clear_cookie(response, TXN_COOKIE, config)
        return response

    @router.get('/status')
    def status(request: Request):
        if config.disabled_reason() is not None:
            return JSONResponse(status_code=401, content={
                'status': 'UNAUTHENTICATED', 'approval_gate': 'DISABLED',
                'stage_b_execution_ready': False})
        row = current_session(request)
        if row is None:
            return JSONResponse(status_code=401, content={
                'status': 'UNAUTHENTICATED', 'approval_gate': 'DISABLED',
                'stage_b_execution_ready': False})
        return JSONResponse(content=_public_status(row['subject']))

    @router.post('/logout')
    def logout(request: Request):
        if config.disabled_reason() is not None:
            response = JSONResponse(content={
                'status': 'UNAUTHENTICATED', 'approval_gate': 'DISABLED',
                'stage_b_execution_ready': False})
            _clear_cookie(response, SESSION_COOKIE, config)
            _clear_cookie(response, CSRF_COOKIE, config)
            return response
        if not _csrf_ok(request):
            return deny('CSRF_REJECTED')
        raw = request.cookies.get(SESSION_COOKIE)
        session_id = sessions.unsign(raw) if raw else None
        if session_id is not None:
            sessions.revoke(session_id)
        response = JSONResponse(content={
            'status': 'UNAUTHENTICATED', 'approval_gate': 'DISABLED',
            'stage_b_execution_ready': False})
        _clear_cookie(response, SESSION_COOKIE, config)
        _clear_cookie(response, CSRF_COOKIE, config)
        return response

    return router


def observation_session_authorizes_trading(_cookie=None, **_ignored):
    """An observation session is never a trading operator session."""
    return False


def stage_b_execution_gate(*_args, **_ignored):
    """Stage B stays closed inside the OIDC release.

    This does not import the KuCoin Stage B adapter and it does not open an
    exchange connection. Arguments are ignored so a caller cannot enable it.
    """
    return {
        'decision': 'DENY',
        'reason': 'STAGE_B_NOT_PART_OF_OIDC_RELEASE',
        'stage_b_execution_ready': False,
        'exchange_calls': 0,
    }


def _public_status(subject):
    gate = stage_b_execution_gate()
    return {
        'status': 'AUTHENTICATED',
        'subject': subject,
        'permission': OBSERVATION_PERMISSION,
        'observation_authority': False,
        'approval_gate': 'DISABLED',
        'stage_b_execution_ready': gate['stage_b_execution_ready'],
        'trading_authority': False,
    }


def _csrf_ok(request):
    header = request.headers.get(CSRF_HEADER)
    cookie = request.cookies.get(CSRF_COOKIE)
    if not header or not cookie or len(header) != len(cookie):
        return False
    return secrets.compare_digest(header, cookie)


def _set_cookie(response, name, value, config, max_age, http_only=True):
    cookie = SimpleCookie()
    cookie[name] = value
    cookie[name]['httponly'] = http_only
    cookie[name]['path'] = COOKIE_PATH
    cookie[name]['samesite'] = 'lax'
    cookie[name]['max-age'] = str(max_age)
    if config.secure_cookie:
        cookie[name]['secure'] = True
    response.headers.append('set-cookie', cookie[name].OutputString())


def _clear_cookie(response, name, config):
    cookie = SimpleCookie()
    cookie[name] = ''
    cookie[name]['path'] = COOKIE_PATH
    cookie[name]['max-age'] = '0'
    if config.secure_cookie:
        cookie[name]['secure'] = True
    response.headers.append('set-cookie', cookie[name].OutputString())
