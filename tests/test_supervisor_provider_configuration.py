import pytest
from backend.supervisor.ollama_provider import OllamaLocalProvider
from backend.supervisor.provider_configuration import SupervisorProviderConfiguration,SupervisorProviderMode,OLLAMA_LOCAL_ENDPOINT,load_supervisor_provider_configuration
def test_configuration_is_explicit_local_bounded_and_charge_free():
 c=SupervisorProviderConfiguration(mode=SupervisorProviderMode.OLLAMA_LOCAL); assert c.endpoint=="http://127.0.0.1:11434"; assert c.model=="qwen3:4b-instruct"; assert c.timeoutSeconds==180 and c.maximumOutputBytes==65536
 assert load_supervisor_provider_configuration({}).mode is SupervisorProviderMode.DISABLED
def test_arbitrary_endpoint_and_disabled_adapter_are_rejected():
 with pytest.raises(ValueError): OllamaLocalProvider(SupervisorProviderConfiguration(endpoint="http://example.com"))
 with pytest.raises(ValueError): OllamaLocalProvider(SupervisorProviderConfiguration(mode=SupervisorProviderMode.DISABLED))
def test_environment_selects_openai_mode_with_model_and_credential():
 c=load_supervisor_provider_configuration({"SUPERVISOR_PROVIDER":"OPENAI","SUPERVISOR_MODEL":"gpt-4o-mini","SUPERVISOR_CREDENTIAL_ID":"OPENAI_API_KEY"})
 assert c.mode is SupervisorProviderMode.OPENAI; assert c.model=="gpt-4o-mini"; assert c.credentialId=="OPENAI_API_KEY"; assert c.maxOutputTokens==4096
def test_unknown_environment_value_fails_closed_to_disabled():
 assert load_supervisor_provider_configuration({"SUPERVISOR_PROVIDER":"BOGUS"}).mode is SupervisorProviderMode.DISABLED
