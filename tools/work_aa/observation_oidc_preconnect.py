"""Offline contract for the measured OIDC proxy path.

This module does not read Nginx, credentials, or the network.  A caller
supplies the already measured proxy facts.
"""
from backend.observation_auth.oidc_api import (
    COOKIE_PATH, CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE, _set_cookie,
    stage_b_execution_gate)
from backend.observation_auth.oidc_config import (
    AUTHORIZATION_ENDPOINT, EXPECTED_ISSUER, ObservationOidcConfig)
from backend.observation_auth.oidc_jwks import DISCOVERY_URL, JWKS_URL
from tools.work_aa.observation_operator_identity import OBSERVATION_PERMISSION


BACKEND_CALLBACK_PATH = '/api/observation/auth/oidc/callback'
BACKEND_LOGOUT_PATH = '/api/observation/auth/oidc/logout'
BACKEND_START_PATH = '/api/observation/auth/oidc/start'


def callback_url(origin):
    if not isinstance(origin, str) or not origin.startswith('https://'):
        return None
    if origin.endswith('/') or '/' in origin[len('https://'):]:
        return None
    host = origin[len('https://'):]
    if not host or ':' in host or '@' in host:
        return None
    return origin + BACKEND_CALLBACK_PATH


def proxy_method(snapshot, method, path):
    if not isinstance(snapshot, dict) or snapshot.get('path_rewrite') is not False:
        return 'REWRITE_UNVERIFIED'
    if path == BACKEND_CALLBACK_PATH and method == 'GET':
        allowed = snapshot.get('api_methods') or ()
        return 'ALLOW' if 'GET' in allowed else 'DENY'
    if path == BACKEND_LOGOUT_PATH and method == 'POST':
        if snapshot.get('logout_post_explicit') is True:
            return 'ALLOW'
        return 'DENY'
    if path == BACKEND_START_PATH and method == 'GET':
        allowed = snapshot.get('api_methods') or ()
        return 'ALLOW' if 'GET' in allowed else 'DENY'
    return 'UNSCOPED'


def evaluate_preconnect(snapshot):
    origin = None
    if (
        isinstance(snapshot, dict)
        and snapshot.get('scheme') == 'https'
        and snapshot.get('port') == 443
        and isinstance(snapshot.get('host'), str)
    ):
        origin = 'https://' + snapshot['host']
    url = callback_url(origin) if origin else None
    logout = proxy_method(snapshot, 'POST', BACKEND_LOGOUT_PATH)
    callback = proxy_method(snapshot, 'GET', BACKEND_CALLBACK_PATH)
    config = ObservationOidcConfig({})
    gate = stage_b_execution_gate()
    ready = (
        url is not None
        and callback == 'ALLOW'
        and logout == 'ALLOW'
        and snapshot.get('forwards_cookie') is True
        and snapshot.get('hides_set_cookie') is False
    )
    reason = 'READY'
    if url is None:
        reason = 'CALLBACK_URL_NOT_VERIFIED'
    elif callback != 'ALLOW':
        reason = 'CALLBACK_GET_DENIED'
    elif logout != 'ALLOW':
        reason = 'POST_LOGOUT_BLOCKED_BY_PROXY'
    elif snapshot.get('forwards_cookie') is not True or snapshot.get('hides_set_cookie') is not False:
        reason = 'COOKIE_FORWARDING_UNVERIFIED'
    return {
        'callback_url': url,
        'callback_get': callback,
        'logout_post': logout,
        'issuer': EXPECTED_ISSUER,
        'authorization_endpoint': AUTHORIZATION_ENDPOINT,
        'discovery_url': DISCOVERY_URL,
        'jwks_url': JWKS_URL,
        'feature_flag': config.disabled_reason(),
        'permission': OBSERVATION_PERMISSION,
        'session_cookie': SESSION_COOKIE,
        'csrf_cookie': CSRF_COOKIE,
        'csrf_header': CSRF_HEADER,
        'cookie_path': COOKIE_PATH,
        'cookie_samesite': 'lax',
        'stage_b_decision': gate['decision'],
        'stage_b_authorized': gate.get('stage_b_execution_ready') is True,
        'preconnect_ready': ready,
        'reason': reason,
    }


def cookie_flags(config):
    class _Bag:
        def __init__(self):
            self.headers = self

        def append(self, _name, value):
            self.value = value

    bag = _Bag()
    _set_cookie(bag, SESSION_COOKIE, 'value', config, max_age=60)
    text = bag.value
    return {
        'httponly': 'HttpOnly' in text,
        'secure': 'Secure' in text,
        'samesite': 'lax' if 'SameSite=lax' in text or 'SameSite=Lax' in text else 'other',
        'path': COOKIE_PATH if 'Path=' + COOKIE_PATH in text else '',
    }
