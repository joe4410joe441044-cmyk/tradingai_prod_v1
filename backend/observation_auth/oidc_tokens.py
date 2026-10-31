"""ID token checks for the observation OIDC callback.

Verification uses a caller-supplied key set.  This module does not fetch
Google and does not accept a token as proof of an approval.
"""
import base64
import hashlib
import hmac
import json
import secrets
import threading
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers

from tools.work_aa.observation_operator_identity import OBSERVATION_PERMISSION


def pkce_pair():
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    challenge = base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')
    return verifier, challenge


def _b64url(raw):
    text = raw.decode('ascii') if isinstance(raw, bytes) else raw
    pad = '=' * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def public_key_from_jwk(jwk):
    numbers = RSAPublicNumbers(
        int.from_bytes(_b64url(jwk['e']), 'big'),
        int.from_bytes(_b64url(jwk['n']), 'big'),
    )
    return numbers.public_key()


def token_kid(token):
    """Read the unverified header kid.  This does not accept the token."""
    if not isinstance(token, str) or token.count('.') != 2:
        return None
    try:
        header = json.loads(_b64url(token.split('.', 1)[0]))
    except (ValueError, json.JSONDecodeError, TypeError):
        return None
    kid = header.get('kid') if isinstance(header, dict) else None
    return kid if isinstance(kid, str) and kid else None


def verify_id_token(token, *, keys, issuer, audience, nonce, now, skew):
    if not isinstance(token, str) or token.count('.') != 2:
        return 'INVALID_TOKEN'
    header_b, payload_b, sig_b = token.split('.')
    try:
        header = json.loads(_b64url(header_b))
    except (ValueError, json.JSONDecodeError, TypeError):
        return 'INVALID_TOKEN'
    if not isinstance(header, dict) or header.get('alg') != 'RS256':
        return 'ALGORITHM_REJECTED'
    kid = header.get('kid')
    if not isinstance(kid, str) or not kid:
        return 'MISSING_KID'
    try:
        payload = json.loads(_b64url(payload_b))
        signature = _b64url(sig_b)
    except (ValueError, json.JSONDecodeError, TypeError):
        return 'INVALID_TOKEN'
    if keys is None:
        return 'JWKS_UNAVAILABLE'
    key = keys.get(kid) if isinstance(keys, dict) else None
    if key is None:
        return 'UNKNOWN_SIGNING_KEY'
    try:
        key.verify(
            signature,
            (header_b + '.' + payload_b).encode('ascii'),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except InvalidSignature:
        return 'INVALID_SIGNATURE'
    if payload.get('iss') != issuer:
        return 'WRONG_ISSUER'
    aud = payload.get('aud')
    audiences = aud if isinstance(aud, list) else [aud]
    if audience not in audiences:
        return 'WRONG_AUDIENCE'
    exp = payload.get('exp')
    iat = payload.get('iat')
    if type(exp) is not int or type(iat) is not int or type(now) is not int:
        return 'EXPIRED'
    if iat > now + skew:
        return 'FUTURE_ISSUED'
    if exp <= now:
        return 'EXPIRED'
    if not isinstance(payload.get('nonce'), str):
        return 'MISSING_NONCE'
    got = payload['nonce']
    if len(got) != len(nonce) or not hmac.compare_digest(got, nonce):
        return 'NONCE_MISMATCH'
    subject = payload.get('sub')
    if not isinstance(subject, str) or not subject:
        return 'MISSING_SUBJECT'
    return {'subject': subject}


def allowlist_decision(allowlist, issuer, subject):
    match = None
    for entry in allowlist:
        if entry.get('issuer') == issuer and entry.get('subject') == subject:
            match = entry
            break
    if match is None:
        return 'UNAUTHORIZED_SUBJECT'
    if match.get('enabled') is not True:
        return 'DISABLED_SUBJECT'
    if match.get('permission') != OBSERVATION_PERMISSION:
        return 'MISSING_PERMISSION'
    return None


class TransactionStore:
    """One-time OIDC transactions.  The code verifier never leaves the process."""

    def __init__(self, ttl_seconds, monotonic=None):
        self._ttl = ttl_seconds
        self._mono = monotonic or time.monotonic
        self._rows = {}
        self._lock = threading.Lock()

    def put(self, state, nonce, verifier):
        now = self._mono()
        with self._lock:
            self._rows[state] = {
                'nonce': nonce,
                'verifier': verifier,
                'expires_at': now + self._ttl,
                'used': False,
            }

    def consume(self, state):
        now = self._mono()
        with self._lock:
            row = self._rows.get(state)
            if row is None:
                return 'STATE_MISMATCH'
            if row['used']:
                return 'STATE_REPLAY'
            if row['expires_at'] <= now:
                return 'EXPIRED_STATE'
            row['used'] = True
            return {'nonce': row['nonce'], 'verifier': row['verifier']}


class ObservationSessionStore:
    """Process-local observation sessions.  Not the trading operator session."""

    def __init__(self, secret, ttl_seconds, monotonic=None):
        if len(secret) < 16:
            raise ValueError('session secret required')
        self._secret = secret.encode('utf-8')
        self._ttl = ttl_seconds
        self._mono = monotonic or time.monotonic
        self._rows = {}
        self._lock = threading.Lock()

    def create(self, subject, issuer):
        session_id = secrets.token_hex(32)
        now = self._mono()
        with self._lock:
            self._rows[session_id] = {
                'subject': subject,
                'issuer': issuer,
                'expires_at': now + self._ttl,
            }
        return session_id

    def read(self, session_id):
        now = self._mono()
        with self._lock:
            row = self._rows.get(session_id)
            if row is None:
                return None
            if row['expires_at'] <= now:
                self._rows.pop(session_id, None)
                return None
            return dict(row)

    def revoke(self, session_id):
        with self._lock:
            self._rows.pop(session_id, None)

    def sign(self, session_id):
        digest = hmac.digest(self._secret, session_id.encode('ascii'), hashlib.sha256)
        return session_id + '.' + digest.hex()

    def unsign(self, value):
        if not isinstance(value, str) or '.' not in value:
            return None
        session_id, _, sig_hex = value.rpartition('.')
        expected = hmac.digest(self._secret, session_id.encode('ascii'), hashlib.sha256)
        try:
            provided = bytes.fromhex(sig_hex)
        except ValueError:
            return None
        if not hmac.compare_digest(expected, provided):
            return None
        return session_id
