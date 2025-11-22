# app/services/llm_provider.py
from abc import ABC, abstractmethod
from openai import AsyncOpenAI

# Local imports
from app.core.settings import settings

class LLMProvider(ABC):
    @abstractmethod
    async def get_embedding(self, text: str) -> list[float]:
        pass

    @abstractmethod
    async def chat(self, messages: list, model=None, tools=None, tool_choice=None) -> str:
        """Returns the content string or handles tool calls internally if needed"""
        pass

# OpenAI Provider class. Used when OpenAI is the provider
class OpenAIProvider(LLMProvider):
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.embed_model = settings.EMBEDDING_MODEL
        self.chat_model = settings.CHAT_MODEL

    async def get_embedding(self, text: str) -> list[float]:
        res = await self.client.embeddings.create(model=self.embed_model, input=text)
        return res.data[0].embedding
    
    async def chat(self, messages: list, model=None, tools=None, tool_choice=None):
        return await self.client.chat.completions.create(
            model=model or self.chat_model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice
        )

# Ollama Provider Class. Used when a local LLM is the provider
class OllamaProvider(LLMProvider):
    def __init__(self):
        # Ollama is API-compatible with OpenAI. This points to localhost
        self.client = AsyncOpenAI(
            base_url=settings.OLLAMA_BASE_URL,
            api_key="ollama" # API key string required, but not used
        )
        self.embed_model = "nomic-embed-text"   # Example
        self.chat_model = "llama3"              # Example

    async def get_embedding(self, text: str) -> list[float]:
        res = await self.client.embeddings.create(model=self.embed_model, input=text)
        return res.data[0].embedding
    
    async def chat(self, messages: list, model=None, tools=None, tool_choice=None):
        # WARNING: local models can struggle with tools
        return await self.client.chat.completions.create(
            model=model or self.chat_model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice
        )
