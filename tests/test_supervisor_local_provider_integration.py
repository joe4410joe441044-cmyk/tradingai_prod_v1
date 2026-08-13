from pydantic import BaseModel,ConfigDict
from backend.supervisor.ollama_provider import OllamaLocalProvider
from backend.supervisor.provider_configuration import SupervisorProviderConfiguration,SupervisorProviderMode
class JapaneseOutput(BaseModel):
 model_config=ConfigDict(extra="forbid"); answer:str; mode:str
def test_real_local_ollama_status_and_typed_japanese_response():
 provider=OllamaLocalProvider(SupervisorProviderConfiguration(mode=SupervisorProviderMode.OLLAMA_LOCAL)); assert provider.availability.value=="AVAILABLE"; result=provider.generate_structured_output({"instruction":"日本語で短くSHADOW状態を説明"},JapaneseOutput,180); assert result.failureCode is None; assert result.output.mode=="SHADOW"; assert result.output.answer; status=provider.status(); assert status["localhostOnly"] is True and status["operationalEffect"]=="NONE"
