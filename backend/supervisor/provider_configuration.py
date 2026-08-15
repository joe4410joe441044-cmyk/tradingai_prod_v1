"""Non-secret explicit configuration for the Supervisor provider.

The Supervisor keeps a provider-neutral interface. This module only resolves the
explicit, non-secret configuration that selects a provider mode. Secrets are
resolved elsewhere (e.g. the AI Advisor credential loader) and never appear here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Mapping


class SupervisorProviderMode(str, Enum):
    DISABLED = "DISABLED"
    OLLAMA_LOCAL = "OLLAMA_LOCAL"
    OPENAI = "OPENAI"


OLLAMA_LOCAL_ENDPOINT = "http://127.0.0.1:11434"
OLLAMA_LOCAL_MODEL = "qwen3:4b-instruct"
OLLAMA_LOCAL_TIMEOUT_SECONDS = 180.0
OLLAMA_LOCAL_MAX_OUTPUT_BYTES = 65536

OPENAI_SUPERVISOR_MODEL = "gpt-4o-mini"
OPENAI_SUPERVISOR_CREDENTIAL_ID = "OPENAI_API_KEY"
OPENAI_SUPERVISOR_TIMEOUT_SECONDS = 45.0
OPENAI_SUPERVISOR_MAX_OUTPUT_TOKENS = 4096

SUPERVISOR_PROVIDER_ENV = "SUPERVISOR_PROVIDER"
SUPERVISOR_MODEL_ENV = "SUPERVISOR_MODEL"
SUPERVISOR_CREDENTIAL_ID_ENV = "SUPERVISOR_CREDENTIAL_ID"


@dataclass(frozen=True)
class SupervisorProviderConfiguration:
    mode: SupervisorProviderMode = SupervisorProviderMode.DISABLED
    endpoint: str = OLLAMA_LOCAL_ENDPOINT
    model: str = OLLAMA_LOCAL_MODEL
    timeoutSeconds: float = OLLAMA_LOCAL_TIMEOUT_SECONDS
    maximumOutputBytes: int = OLLAMA_LOCAL_MAX_OUTPUT_BYTES
    credentialId: str = OPENAI_SUPERVISOR_CREDENTIAL_ID
    maxOutputTokens: int = OPENAI_SUPERVISOR_MAX_OUTPUT_TOKENS


def _mode_from_environment(
    environment: Mapping[str, str],
) -> SupervisorProviderMode:
    raw = environment.get(SUPERVISOR_PROVIDER_ENV)
    if raw is None:
        return SupervisorProviderMode.DISABLED
    try:
        return SupervisorProviderMode(raw.strip())
    except ValueError:
        return SupervisorProviderMode.DISABLED


def load_supervisor_provider_configuration(
    environment: Mapping[str, str] | None = None,
) -> SupervisorProviderConfiguration:
    """Resolve a fail-closed configuration, defaulting to DISABLED.

    The default DISABLED mode keeps the Supervisor Core available while the LLM
    interpretation layer is explicitly off. Only an explicit SUPERVISOR_PROVIDER
    value selects a live provider.
    """
    env = environment if environment is not None else os.environ
    mode = _mode_from_environment(env)
    if mode is SupervisorProviderMode.DISABLED:
        return SupervisorProviderConfiguration()
    if mode is SupervisorProviderMode.OLLAMA_LOCAL:
        return SupervisorProviderConfiguration(mode=mode)
    if mode is SupervisorProviderMode.OPENAI:
        model = (env.get(SUPERVISOR_MODEL_ENV) or OPENAI_SUPERVISOR_MODEL).strip()
        credential_id = (
            env.get(SUPERVISOR_CREDENTIAL_ID_ENV) or OPENAI_SUPERVISOR_CREDENTIAL_ID
        ).strip()
        if not model or not credential_id:
            return SupervisorProviderConfiguration()
        return SupervisorProviderConfiguration(
            mode=mode,
            endpoint="",
            model=model,
            timeoutSeconds=OPENAI_SUPERVISOR_TIMEOUT_SECONDS,
            maximumOutputBytes=OLLAMA_LOCAL_MAX_OUTPUT_BYTES,
            credentialId=credential_id,
            maxOutputTokens=OPENAI_SUPERVISOR_MAX_OUTPUT_TOKENS,
        )
    return SupervisorProviderConfiguration()
