"""Observation OIDC settings.

The flow is disabled unless a caller supplies a complete config object.
This module does not read the process environment or a production file.
A Google Web application client is confidential: token exchange uses
``client_secret_post`` together with PKCE S256.  The client secret is kept
on the config object and is never copied into a public view.
"""
from tools.work_aa.observation_operator_identity import (
    BOT_START_PERMISSION, LITERAL_SUBJECT, LIVE_ARM_PERMISSION, OBSERVATION_PERMISSION)


EXPECTED_ISSUER = 'https://accounts.google.com'
AUTHORIZATION_ENDPOINT = 'https://accounts.google.com/o/oauth2/v2/auth'
JWKS_URI = 'https://www.googleapis.com/oauth2/v3/certs'
TOKEN_ENDPOINT = 'https://oauth2.googleapis.com/token'
CANONICAL_REDIRECT_URI = 'https://tradingai-joe.mooo.com/api/observation/auth/oidc/callback'
TEST_REDIRECT_URI = 'http://testserver/api/observation/auth/oidc/callback'
GOOGLE_CLIENT_TYPE = 'WEB_APPLICATION_CONFIDENTIAL_PKCE'
TOKEN_ENDPOINT_AUTH_METHOD = 'client_secret_post'
CLOCK_SKEW_SECONDS = 60
MIN_CLIENT_SECRET_LENGTH = 16
MAX_SECRET_LENGTH = 256
MAX_SUBJECT_LENGTH = 255
SECRET_FIELDS = (
    'private_key', 'id_token', 'access_key', 'passphrase',
    'seed', 'password', 'credential',
)
_ALLOWLIST_KEYS = frozenset(('issuer', 'subject', 'permission', 'enabled'))


def _ascii_token(value, maximum):
    return (
        isinstance(value, str)
        and 1 <= len(value) <= maximum
        and value.strip() == value
        and all(32 < ord(ch) < 127 for ch in value)
    )


def client_secret_status(value):
    """Return a denial reason, or None when the secret is usable."""
    if not isinstance(value, str) or value == '':
        return 'MISSING_CLIENT_SECRET'
    if (
        len(value) < MIN_CLIENT_SECRET_LENGTH
        or len(value) > MAX_SECRET_LENGTH
        or value.strip() != value
        or any(ord(ch) < 33 or ord(ch) > 126 for ch in value)
    ):
        return 'INVALID_CLIENT_SECRET'
    return None


class ObservationOidcConfig:
    def __init__(self, mapping=None, *, load_error=None):
        raw = dict(mapping or {})
        self._load_error = load_error
        self._secret = any(name in raw for name in SECRET_FIELDS)
        self.enabled = raw.get('enabled') is True
        self.issuer = raw.get('issuer') or ''
        self.client_id = raw.get('client_id') if isinstance(raw.get('client_id'), str) else ''
        supplied = raw.get('client_secret')
        self.client_secret = supplied if isinstance(supplied, str) else ''
        self.redirect_uri = raw.get('redirect_uri') if isinstance(raw.get('redirect_uri'), str) else ''
        self.session_secret = raw.get('session_secret') if isinstance(raw.get('session_secret'), str) else ''
        self.allowlist = tuple(raw.get('allowlist') or ())
        self.secure_cookie = raw.get('secure_cookie') is not False
        self.insecure_redirect_allowed = raw.get('insecure_redirect_allowed') is True
        self.clock_skew_seconds = CLOCK_SKEW_SECONDS
        self.transaction_ttl_seconds = 300
        ttl = raw.get('session_ttl_seconds', 600)
        if ttl in (None, ''):
            ttl = 600
        if isinstance(ttl, str) and ttl.isdigit():
            ttl = int(ttl)
        if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl < 30 or ttl > 86400:
            self._load_error = self._load_error or 'INVALID_CONFIGURATION'
            ttl = 600
        self.session_ttl_seconds = ttl

    def disabled_reason(self):
        if self._load_error:
            return self._load_error
        if self._secret:
            return 'SECRET_CONFIG_REJECTED'
        if not self.enabled:
            return 'FEATURE_DISABLED'
        if self.issuer != EXPECTED_ISSUER:
            return 'INVALID_ISSUER'
        if not self.client_id or self.client_id.strip() != self.client_id:
            return 'MISSING_CONFIGURATION'
        secret_reason = client_secret_status(self.client_secret)
        if secret_reason is not None:
            return secret_reason
        if self.insecure_redirect_allowed:
            if self.redirect_uri != TEST_REDIRECT_URI:
                return 'INVALID_REDIRECT_URI'
        elif self.redirect_uri != CANONICAL_REDIRECT_URI:
            return 'INVALID_REDIRECT_URI'
        if len(self.session_secret) < 16:
            return 'MISSING_SESSION_SECRET'
        if (
            len(self.session_secret) > MAX_SECRET_LENGTH
            or self.session_secret.strip() != self.session_secret
            or any(ord(ch) < 33 or ord(ch) > 126 for ch in self.session_secret)
        ):
            return 'INVALID_SESSION_SECRET'
        if not self.allowlist:
            return 'MISSING_ALLOWLIST'
        for entry in self.allowlist:
            if not isinstance(entry, dict):
                return 'MISSING_ALLOWLIST'
            if set(entry) != _ALLOWLIST_KEYS:
                return 'MALFORMED_ALLOWLIST'
            if any(name in entry for name in SECRET_FIELDS) or 'client_secret' in entry:
                return 'SECRET_CONFIG_REJECTED'
            if entry.get('issuer') != EXPECTED_ISSUER:
                return 'INVALID_ISSUER'
            subject = entry.get('subject')
            if not _ascii_token(subject, MAX_SUBJECT_LENGTH) or subject == LITERAL_SUBJECT:
                return 'MISSING_ALLOWLIST'
            if entry.get('permission') in (LIVE_ARM_PERMISSION, BOT_START_PERMISSION):
                return 'UNAUTHORIZED_PERMISSION'
            if entry.get('permission') != OBSERVATION_PERMISSION:
                return 'MISSING_PERMISSION'
        return None

    def public_view(self):
        """Configured-versus-effective state with no credential values."""
        reason = self.disabled_reason()
        return {
            'google_client_type': GOOGLE_CLIENT_TYPE,
            'token_endpoint_auth_method': TOKEN_ENDPOINT_AUTH_METHOD,
            'enabled_requested': self.enabled,
            'effective_enabled': reason is None,
            'disabled_reason': reason,
            'issuer': EXPECTED_ISSUER if self.issuer == EXPECTED_ISSUER else '',
            'client_id_present': bool(self.client_id),
            'client_secret_present': bool(self.client_secret),
            'session_secret_present': bool(self.session_secret),
            'redirect_uri_exact': self.redirect_uri in (CANONICAL_REDIRECT_URI, TEST_REDIRECT_URI),
        }

    def __repr__(self):
        view = self.public_view()
        return 'ObservationOidcConfig(' + repr(view) + ')'
