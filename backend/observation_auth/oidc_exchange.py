"""Authorization-code + PKCE token exchange for Google.

The HTTP client is injected in tests.  The default transport talks only to
the pinned discovery document and the pinned token endpoint, checks provider
metadata, and posts ``client_secret`` in the form body once.  Failures return
a reason code.  Secret values, authorization codes, and tokens are not logged.
"""
import http.client
import json
import ssl
from urllib.parse import urlsplit, urlencode

from backend.observation_auth.oidc_config import (
    AUTHORIZATION_ENDPOINT, EXPECTED_ISSUER, JWKS_URI, TOKEN_ENDPOINT)
from backend.observation_auth.oidc_jwks import DISCOVERY_URL, assert_pinned_url


TIMEOUT_SECONDS = 5.0
MAX_RESPONSE_BYTES = 65536
_VERIFIER_CHARS = frozenset(
    'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~')


class TokenExchangeError(Exception):
    def __init__(self, reason):
        self.reason = reason


class TokenExchangeResult:
    def __init__(self, id_token=None, reason=None):
        self.id_token = id_token
        self.reason = reason

    @property
    def ok(self):
        return (
            self.reason is None
            and isinstance(self.id_token, str)
            and self.id_token.count('.') == 2
        )

    def __repr__(self):
        return 'TokenExchangeResult(ok=%s, reason=%r)' % (self.ok, self.reason)


class UrllibTokenTransport:
    """One HTTPS request per call.  Redirects are not followed."""

    def __init__(self, timeout=TIMEOUT_SECONDS, max_bytes=MAX_RESPONSE_BYTES):
        self.timeout = timeout
        self.max_bytes = max_bytes
        self._ssl = ssl.create_default_context()

    def get_bytes(self, url):
        host, path = assert_pinned_url(url)
        if url != DISCOVERY_URL:
            raise TokenExchangeError('TOKEN_ENDPOINT_REJECTED')
        try:
            status, payload = self._read(
                'GET', host, path, body=None, headers={'Accept': 'application/json'})
        except TimeoutError:
            raise TokenExchangeError('PROVIDER_METADATA_UNAVAILABLE')
        except OSError:
            raise TokenExchangeError('PROVIDER_METADATA_UNAVAILABLE')
        if status != 200:
            raise TokenExchangeError('PROVIDER_METADATA_UNAVAILABLE')
        return payload

    def post_form(self, url, body, headers, timeout):
        host, path = _assert_token_endpoint(url)
        if not isinstance(body, (bytes, bytearray)) or len(body) > 8192:
            raise TokenExchangeError('TOKEN_EXCHANGE_FAILED')
        if headers:
            for name in headers:
                if name.lower() == 'authorization':
                    raise TokenExchangeError('TOKEN_EXCHANGE_FAILED')
        safe_headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        try:
            return self._read('POST', host, path, body=bytes(body), headers=safe_headers, timeout=timeout)
        except TimeoutError:
            raise TokenExchangeError('TOKEN_ENDPOINT_TIMEOUT')
        except OSError:
            raise TokenExchangeError('TOKEN_EXCHANGE_FAILED')

    def _read(self, method, host, path, body, headers, timeout=None):
        if self._ssl.verify_mode != ssl.CERT_REQUIRED or not self._ssl.check_hostname:
            raise TokenExchangeError('TOKEN_EXCHANGE_FAILED')
        connection = http.client.HTTPSConnection(
            host, timeout=self.timeout if timeout is None else timeout, context=self._ssl)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                raise TokenExchangeError('TOKEN_ENDPOINT_REJECTED')
            payload = response.read(self.max_bytes + 1)
            status = response.status
        except TokenExchangeError:
            raise
        finally:
            connection.close()
        if len(payload) > self.max_bytes:
            raise TokenExchangeError('TOKEN_EXCHANGE_FAILED')
        return status, payload


class GooglePkceTokenExchanger:
    """Confidential Google client with PKCE S256 and one token POST."""

    def __init__(self, *, client_id, client_secret, redirect_uri, transport, timeout=TIMEOUT_SECONDS):
        if not isinstance(client_id, str) or not client_id:
            raise ValueError('client id required')
        if not isinstance(client_secret, str) or len(client_secret) < 16:
            raise ValueError('client authentication required')
        if not isinstance(redirect_uri, str) or not redirect_uri:
            raise ValueError('redirect uri required')
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._transport = transport
        self._timeout = timeout

    def __repr__(self):
        return 'GooglePkceTokenExchanger(redacted)'

    def exchange(self, code, verifier, redirect_uri):
        try:
            return self._exchange(code, verifier, redirect_uri)
        except TokenExchangeError as exc:
            return TokenExchangeResult(reason=exc.reason)
        except TimeoutError:
            return TokenExchangeResult(reason='TOKEN_ENDPOINT_TIMEOUT')
        except OSError:
            return TokenExchangeResult(reason='TOKEN_EXCHANGE_FAILED')
        except Exception:
            return TokenExchangeResult(reason='TOKEN_EXCHANGE_FAILED')

    def _exchange(self, code, verifier, redirect_uri):
        if redirect_uri != self._redirect_uri:
            raise TokenExchangeError('REDIRECT_URI_MISMATCH')
        if not isinstance(code, str) or not code or len(code) > 512 or any(ch.isspace() for ch in code):
            raise TokenExchangeError('TOKEN_EXCHANGE_FAILED')
        if not _verifier_ok(verifier):
            raise TokenExchangeError('PKCE_VERIFIER_REJECTED')
        self._require_provider_metadata()
        form = urlencode((
            ('code', code),
            ('client_id', self._client_id),
            ('client_secret', self._client_secret),
            ('redirect_uri', self._redirect_uri),
            ('grant_type', 'authorization_code'),
            ('code_verifier', verifier),
        )).encode('ascii')
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        status, payload = self._transport.post_form(TOKEN_ENDPOINT, form, headers, self._timeout)
        if status != 200:
            raise TokenExchangeError('TOKEN_ENDPOINT_HTTP_ERROR')
        document = _json_object(payload)
        return TokenExchangeResult(id_token=_id_token(document))

    def _require_provider_metadata(self):
        assert_pinned_url(DISCOVERY_URL)
        document = _json_object(self._transport.get_bytes(DISCOVERY_URL))
        methods = document.get('token_endpoint_auth_methods_supported')
        challenges = document.get('code_challenge_methods_supported')
        algorithms = document.get('id_token_signing_alg_values_supported')
        if (
            document.get('issuer') != EXPECTED_ISSUER
            or document.get('authorization_endpoint') != AUTHORIZATION_ENDPOINT
            or document.get('token_endpoint') != TOKEN_ENDPOINT
            or document.get('jwks_uri') != JWKS_URI
            or not isinstance(methods, list)
            or 'client_secret_post' not in methods
            or not isinstance(challenges, list)
            or 'S256' not in challenges
            or not isinstance(algorithms, list)
            or 'RS256' not in algorithms
        ):
            raise TokenExchangeError('PROVIDER_METADATA_MISMATCH')


def _assert_token_endpoint(url):
    parts = urlsplit(url)
    if (
        parts.scheme != 'https'
        or parts.hostname != 'oauth2.googleapis.com'
        or parts.path != '/token'
        or parts.query
        or parts.fragment
        or parts.username
        or parts.password
        or parts.port not in (None, 443)
    ):
        raise TokenExchangeError('TOKEN_ENDPOINT_REJECTED')
    return parts.hostname, parts.path


def _verifier_ok(value):
    if not isinstance(value, str) or not 43 <= len(value) <= 128:
        return False
    return all(ch in _VERIFIER_CHARS for ch in value)


def _unique_object(pairs):
    parsed = {}
    for key, value in pairs:
        if key in parsed:
            raise ValueError('duplicate')
        parsed[key] = value
    return parsed


def _json_object(raw):
    if not isinstance(raw, (bytes, bytearray)):
        raise TokenExchangeError('MALFORMED_TOKEN_RESPONSE')
    if len(raw) > MAX_RESPONSE_BYTES:
        raise TokenExchangeError('MALFORMED_TOKEN_RESPONSE')
    try:
        parsed = json.loads(bytes(raw).decode('utf-8'), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError, ValueError):
        raise TokenExchangeError('MALFORMED_TOKEN_RESPONSE')
    if not isinstance(parsed, dict):
        raise TokenExchangeError('MALFORMED_TOKEN_RESPONSE')
    return parsed


def _id_token(document):
    token = document.get('id_token')
    if not isinstance(token, str) or token.count('.') != 2:
        raise TokenExchangeError('MALFORMED_TOKEN_RESPONSE')
    token_type = document.get('token_type')
    if token_type != 'Bearer':
        raise TokenExchangeError('MALFORMED_TOKEN_RESPONSE')
    if 'expires_in' in document and type(document.get('expires_in')) is not int:
        raise TokenExchangeError('MALFORMED_TOKEN_RESPONSE')
    if 'access_token' in document and not isinstance(document.get('access_token'), str):
        raise TokenExchangeError('MALFORMED_TOKEN_RESPONSE')
    if 'refresh_token' in document and not isinstance(document.get('refresh_token'), str):
        raise TokenExchangeError('MALFORMED_TOKEN_RESPONSE')
    return token
