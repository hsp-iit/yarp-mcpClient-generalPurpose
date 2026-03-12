from .llm_backend_base import LLMBackend
from openai import OpenAI
from typing import List, Dict, Any

class OllamaBackend(LLMBackend):
    """Local Ollama backend"""

    def __init__(self, base_url: str = "http://localhost:11434/v1", model: str = "llama2"):
        self.base_url = base_url
        self.model = model
        self.client = None

    async def initialize(self):
        self.client = OpenAI(
            base_url=self.base_url,
            api_key="ollama"  # Ollama doesn't require a real API key
        )

    async def chat_completion(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Any:
        try:
            return self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools if tools else None,
                max_tokens=1000
            )
        except Exception:
            return self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=1000
            )

    def get_model_name(self) -> str:
        return self.model
