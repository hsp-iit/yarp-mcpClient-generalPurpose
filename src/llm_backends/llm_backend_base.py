from abc import ABC, abstractmethod
from typing import List, Dict, Any

class LLMBackend(ABC):
    """Abstract base class for LLM backends"""

    @abstractmethod
    async def initialize(self):
        """Initialize the LLM backend"""
        pass

    @abstractmethod
    async def chat_completion(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Any:
        """Get chat completion from LLM"""
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """Get the model name/identifier"""
        pass
