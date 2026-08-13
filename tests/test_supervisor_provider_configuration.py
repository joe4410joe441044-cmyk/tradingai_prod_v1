import pytest
from backend.supervisor.ollama_provider import OllamaLocalProvider
from backend.supervisor.provider_configuration import SupervisorProviderConfiguration,SupervisorProviderMode,OLLAMA_LOCAL_ENDPOINT,load_supervisor_provider_configuration
def test_configuration_is_explicit_local_bounded_and_charge_free():
 c=SupervisorProviderConfiguration(mode=SupervisorProviderMode.OLLAMA_LOCAL); assert c.endpoint=="http://127.0.0.1:11434"; assert c.model=="qwen3:4b-instruct"; assert c.timeoutSeconds==180 and c.maximumOutputBytes==65536
 assert load_supervisor_provider_configuration().mode is SupervisorProviderMode.DISABLED
def test_arbitrary_endpoint_and_disabled_adapter_are_rejected():
 with pytest.raises(ValueError): OllamaLocalProvider(SupervisorProviderConfiguration(endpoint="http://example.com"))
 with pytest.raises(ValueError): OllamaLocalProvider(SupervisorProviderConfiguration(mode=SupervisorProviderMode.DISABLED))
