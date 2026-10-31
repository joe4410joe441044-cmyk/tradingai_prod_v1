"""Server-side observation identity boundary.

The existing login assigns the literal subject ``operator`` and keeps sessions
in process memory.  That session is not an observation approval.  This module
does not read environment credentials and does not grant the observation
permission to ``operator``.
"""
import hashlib
import hmac
import secrets


OBSERVATION_PERMISSION = 'WORK_AA_READONLY_POSITION_OBSERVATION_APPROVER'
LIVE_ARM_PERMISSION = 'LIVE_ARM'
BOT_START_PERMISSION = 'BOT_START'
LITERAL_SUBJECT = 'operator'


class ObservationIdentityAuthority:
    """In-memory sessions for offline tests.  Not a production identity store."""

    def __init__(self, session_secret):
        if type(session_secret) is not bytes or len(session_secret) < 16:
            raise ValueError('session_secret')
        self._secret = session_secret
        self._secrets = {}
        self._grants = {}
        self._sessions = {}

    def register_subject(self, subject, identity_secret):
        if subject == LITERAL_SUBJECT:
            return 'LITERAL_OPERATOR_DENIED'
        if type(subject) is not str or not subject or type(identity_secret) is not bytes:
            return 'INVALID_IDENTITY'
        if len(identity_secret) < 16:
            return 'INVALID_IDENTITY'
        self._secrets[subject] = identity_secret
        self._grants.setdefault(subject, set())
        return None

    def grant(self, subject, permission, **rejected):
        if rejected:
            return 'CLIENT_FLAG_REJECTED'
        if subject == LITERAL_SUBJECT:
            return 'LITERAL_OPERATOR_DENIED'
        if subject not in self._secrets:
            return 'UNKNOWN_SUBJECT'
        if type(permission) is not str or not permission:
            return 'MISSING_PERMISSION'
        self._grants[subject].add(permission)
        return None

    def downgrade(self, subject, permission):
        self._grants.get(subject, set()).discard(permission)

    def permissions(self, subject):
        return frozenset(self._grants.get(subject, ()))

    def identity_secret(self, subject):
        return self._secrets.get(subject)

    def open_session(self, subject, now, *, ttl_seconds=60):
        if subject == LITERAL_SUBJECT:
            return None, 'LITERAL_OPERATOR_DENIED'
        if subject not in self._secrets:
            return None, 'UNKNOWN_SUBJECT'
        if type(now) is not int or type(ttl_seconds) is not int or ttl_seconds < 1:
            return None, 'EXPIRED_SESSION'
        session_id = secrets.token_hex(16)
        self._sessions[session_id] = {
            'subject': subject,
            'expires_at': now + ttl_seconds,
            'revoked': False,
        }
        return self._sign(session_id), None

    def validate(self, token, now):
        if token is None or token == '':
            return None, 'MISSING_SESSION'
        session_id = self._open_token(token)
        if session_id is None:
            return None, 'FORGED_SESSION'
        record = self._sessions.get(session_id)
        if record is None:
            return None, 'FORGED_SESSION'
        if record['revoked'] is True:
            return None, 'REVOKED_SESSION'
        if type(now) is not int or now >= record['expires_at']:
            return None, 'EXPIRED_SESSION'
        return {
            'session_id': session_id,
            'subject': record['subject'],
            'permissions': self.permissions(record['subject']),
        }, None

    def revoke(self, token, now):
        session_id = self._open_token(token) if type(token) is str else None
        record = None if session_id is None else self._sessions.get(session_id)
        if record is None:
            return 'FORGED_SESSION'
        record['revoked'] = True
        if type(now) is not int:
            return 'REVOKED_SESSION'
        return None

    def _sign(self, session_id):
        digest = hmac.digest(self._secret, session_id.encode('ascii'), hashlib.sha256)
        return session_id + '.' + digest.hex()

    def _open_token(self, token):
        if type(token) is not str or token.count('.') != 1:
            return None
        session_id, signature = token.split('.', 1)
        if not session_id or not signature:
            return None
        expected = hmac.digest(
            self._secret, session_id.encode('ascii'), hashlib.sha256)
        try:
            provided = bytes.fromhex(signature)
        except ValueError:
            return None
        if len(provided) != len(expected) or not hmac.compare_digest(expected, provided):
            return None
        return session_id


def production_identity_status():
    """Existing login is not a unique observation identity."""
    return {
        'decision': 'DENY',
        'reason': 'IDENTITY_NOT_ATTRIBUTABLE',
        'subject': None,
        'observation_permission': False,
        'session_survives_restart': False,
        'literal_operator_is_proof': False,
    }
