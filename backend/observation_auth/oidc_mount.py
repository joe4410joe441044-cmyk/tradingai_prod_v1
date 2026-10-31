"""Mount the observation OIDC router.

The default config is empty, so the feature stays off and no JWKS client is
constructed.  Supplying a config does not read the process environment.
"""
import time

from backend.observation_auth.oidc_api import create_observation_oidc_router
from backend.observation_auth.oidc_config import ObservationOidcConfig
from backend.observation_auth.oidc_jwks import GoogleJwksClient, UrllibPinnedTransport


def mount_observation_oidc(
        app, config=None, *, exchanger=None, jwks=None, now=None,
        monotonic=None, transport=None):
    if not isinstance(config, ObservationOidcConfig):
        config = ObservationOidcConfig(config)
    if jwks is None and config.disabled_reason() is None:
        jwks = GoogleJwksClient(
            transport or UrllibPinnedTransport(),
            now or time.time,
        )
    app.include_router(create_observation_oidc_router(
        config,
        exchanger=exchanger,
        jwks=jwks,
        now=now,
        monotonic=monotonic,
    ))
    return app
