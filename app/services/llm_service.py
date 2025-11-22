# app/services/llm_service.py
from app.core.settings import settings
from app.services.llm_provider import OpenAIProvider, OllamaProvider

class LLMService:
    def __init__(self):
        if settings.LLM_PROVIDER == "ollama":
            self.provider = OllamaProvider()
        else:
            self.provider = OpenAIProvider()

    async def get_embedding(self, text: str):
        return await self.provider.get_embedding(text)
    
    async def chat(self, messages, model=None, tools=None, tool_choice=None):
        return await self.provider.chat(messages, model=model, tools=tools, tool_choice=tool_choice)
    
# Instance to import elsewhere
llm_client = LLMService()
