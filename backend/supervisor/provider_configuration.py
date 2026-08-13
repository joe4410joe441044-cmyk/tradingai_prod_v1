"""Non-secret explicit configuration for the local Supervisor provider."""
from dataclasses import dataclass
from enum import Enum

class SupervisorProviderMode(str,Enum):
    DISABLED="DISABLED"
    OLLAMA_LOCAL="OLLAMA_LOCAL"

OLLAMA_LOCAL_ENDPOINT="http://127.0.0.1:11434"
OLLAMA_LOCAL_MODEL="qwen3:4b-instruct"
OLLAMA_LOCAL_TIMEOUT_SECONDS=180.0
OLLAMA_LOCAL_MAX_OUTPUT_BYTES=65536

@dataclass(frozen=True)
class SupervisorProviderConfiguration:
    mode: SupervisorProviderMode=SupervisorProviderMode.DISABLED
    endpoint: str=OLLAMA_LOCAL_ENDPOINT
    model: str=OLLAMA_LOCAL_MODEL
    timeoutSeconds: float=OLLAMA_LOCAL_TIMEOUT_SECONDS
    maximumOutputBytes: int=OLLAMA_LOCAL_MAX_OUTPUT_BYTES

def load_supervisor_provider_configuration():
    return SupervisorProviderConfiguration()
