"""Mount the observation OIDC router.

A config whose ``disabled_reason()`` is not None stays off.  No JWKS client
and no token exchanger are constructed in that state.  This module does not
read the process environment; the caller passes an already loaded config.
"""
import time

from backend.observation_auth.oidc_api import create_observation_oidc_router
from backend.observation_auth.oidc_config import ObservationOidcConfig
from backend.observation_auth.oidc_exchange import GooglePkceTokenExchanger, UrllibTokenTransport
from backend.observation_auth.oidc_jwks import GoogleJwksClient, UrllibPinnedTransport


def mount_observation_oidc(
        app, config=None, *, exchanger=None, jwks=None, now=None,
        monotonic=None, transport=None, token_transport=None):
    if not isinstance(config, ObservationOidcConfig):
        config = ObservationOidcConfig(config)
    if config.disabled_reason() is None:
        if jwks is None:
            jwks = GoogleJwksClient(
                transport or UrllibPinnedTransport(),
                now or time.time,
            )
        if exchanger is None:
            exchanger = GooglePkceTokenExchanger(
                client_id=config.client_id,
                client_secret=config.client_secret,
                redirect_uri=config.redirect_uri,
                transport=token_transport or UrllibTokenTransport(),
            )
    app.include_router(create_observation_oidc_router(
        config,
        exchanger=exchanger,
        jwks=jwks,
        now=now,
        monotonic=monotonic,
    ))
    return app
