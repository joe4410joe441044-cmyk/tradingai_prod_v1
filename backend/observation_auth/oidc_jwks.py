"""Pinned Google JWKS retrieval.

The client fetches only two fixed HTTPS URLs.  A discovery document cannot
select another host.  Tests supply a transport; nothing here is called unless
a caller asks for keys.  TLS verification stays at the platform default.
"""
import http.client
import json
import ssl
from urllib.parse import urlsplit

from backend.observation_auth.oidc_config import EXPECTED_ISSUER
from backend.observation_auth.oidc_tokens import public_key_from_jwk


DISCOVERY_URL = 'https://accounts.google.com/.well-known/openid-configuration'
JWKS_URL = 'https://www.googleapis.com/oauth2/v3/certs'
CACHE_TTL_SECONDS = 300
TIMEOUT_SECONDS = 5.0
MAX_RESPONSE_BYTES = 65536
_PRIVATE_MEMBERS = ('d', 'p', 'q', 'dp', 'dq', 'qi', 'oth', 'k')
_PINNED = {
    DISCOVERY_URL: ('accounts.google.com', '/.well-known/openid-configuration'),
    JWKS_URL: ('www.googleapis.com', '/oauth2/v3/certs'),
}


class JwksRetrievalError(Exception):
    def __init__(self, reason):
        self.reason = reason


def assert_pinned_url(url):
    expected = _PINNED.get(url)
    if expected is None:
        raise JwksRetrievalError('SSRF_REJECTED')
    parts = urlsplit(url)
    host, path = expected
    if (
        parts.scheme != 'https'
        or parts.hostname != host
        or parts.path != path
        or parts.query
        or parts.fragment
        or parts.username
        or parts.password
        or parts.port not in (None, 443)
    ):
        raise JwksRetrievalError('SSRF_REJECTED')
    return host, path


class UrllibPinnedTransport:
    """HTTPS GET for the two pinned URLs.  Redirects are not followed."""

    def __init__(self, timeout=TIMEOUT_SECONDS, max_bytes=MAX_RESPONSE_BYTES):
        self.timeout = timeout
        self.max_bytes = max_bytes
        self._ssl = ssl.create_default_context()

    def get_bytes(self, url):
        host, path = assert_pinned_url(url)
        if self._ssl.verify_mode != ssl.CERT_REQUIRED or not self._ssl.check_hostname:
            raise JwksRetrievalError('JWKS_UNAVAILABLE')
        connection = http.client.HTTPSConnection(
            host, timeout=self.timeout, context=self._ssl)
        try:
            connection.request('GET', path, headers={'Accept': 'application/json'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                raise JwksRetrievalError('SSRF_REJECTED')
            if response.status != 200:
                raise JwksRetrievalError('JWKS_UNAVAILABLE')
            body = response.read(self.max_bytes + 1)
        except JwksRetrievalError:
            raise
        except TimeoutError:
            raise JwksRetrievalError('JWKS_TIMEOUT')
        except OSError:
            raise JwksRetrievalError('JWKS_UNAVAILABLE')
        finally:
            connection.close()
        if len(body) > self.max_bytes:
            raise JwksRetrievalError('OVERSIZED_JWKS')
        return body


def public_keys_from_jwks(document):
    if not isinstance(document, dict) or not isinstance(document.get('keys'), list):
        raise JwksRetrievalError('INVALID_JWKS')
    if not document['keys']:
        raise JwksRetrievalError('INVALID_JWKS')
    keys = {}
    for jwk in document['keys']:
        if not isinstance(jwk, dict):
            raise JwksRetrievalError('INVALID_JWKS')
        if any(name in jwk for name in _PRIVATE_MEMBERS):
            raise JwksRetrievalError('INVALID_JWKS')
        algorithm = jwk.get('alg', 'RS256')
        if algorithm != 'RS256':
            raise JwksRetrievalError('ALGORITHM_REJECTED')
        if jwk.get('kty') != 'RSA' or 'n' not in jwk or 'e' not in jwk:
            raise JwksRetrievalError('INVALID_JWKS')
        kid = jwk.get('kid')
        if not isinstance(kid, str) or not kid:
            raise JwksRetrievalError('MISSING_KID')
        try:
            keys[kid] = public_key_from_jwk(jwk)
        except (ValueError, TypeError, KeyError):
            raise JwksRetrievalError('INVALID_JWKS')
    return keys


class GoogleJwksClient:
    """Cache of RS256 public keys.  Failures return a reason and are not cached."""

    def __init__(self, transport, now, ttl_seconds=CACHE_TTL_SECONDS):
        self._transport = transport
        self._now = now
        self._ttl = ttl_seconds
        self._keys = None
        self._fetched_at = None

    def keys(self):
        return self._load(force=False)

    def keys_for(self, kid):
        loaded = self._load(force=False)
        if not isinstance(loaded, dict):
            return loaded
        if isinstance(kid, str) and kid and kid not in loaded:
            loaded = self._load(force=True)
        return loaded

    def _load(self, force):
        now = int(self._now())
        if (
            not force
            and isinstance(self._keys, dict)
            and self._fetched_at is not None
            and now < self._fetched_at + self._ttl
        ):
            return self._keys
        try:
            keys = self._retrieve()
        except JwksRetrievalError as exc:
            return exc.reason
        except TimeoutError:
            return 'JWKS_TIMEOUT'
        except OSError:
            return 'JWKS_UNAVAILABLE'
        self._keys = keys
        self._fetched_at = now
        return keys

    def _retrieve(self):
        assert_pinned_url(DISCOVERY_URL)
        discovery = _json_object(self._transport.get_bytes(DISCOVERY_URL))
        if discovery.get('issuer') != EXPECTED_ISSUER:
            raise JwksRetrievalError('INVALID_ISSUER')
        jwks_uri = discovery.get('jwks_uri')
        if jwks_uri != JWKS_URL:
            raise JwksRetrievalError('SSRF_REJECTED')
        assert_pinned_url(jwks_uri)
        return public_keys_from_jwks(_json_object(self._transport.get_bytes(jwks_uri)))


def _json_object(raw):
    if not isinstance(raw, (bytes, bytearray)):
        raise JwksRetrievalError('MALFORMED_JWKS')
    if len(raw) > MAX_RESPONSE_BYTES:
        raise JwksRetrievalError('OVERSIZED_JWKS')
    try:
        parsed = json.loads(raw.decode('utf-8'))
    except (UnicodeError, json.JSONDecodeError):
        raise JwksRetrievalError('MALFORMED_JWKS')
    if not isinstance(parsed, dict):
        raise JwksRetrievalError('MALFORMED_JWKS')
    return parsed
