from .llm_backend_base import LLMBackend
from openai import AzureOpenAI
import os
from typing import List, Dict, Any

class AzureOpenAIBackend(LLMBackend):
    """Azure OpenAI backend"""

    def __init__(self):
        self.client = None
        self.deployment_name = None

    async def initialize(self):
        required_vars = ["AZURE_API_KEY", "AZURE_API_VERSION", "AZURE_ENDPOINT", "DEPLOYMENT_ID"]
        if not all(env_var in os.environ for env_var in required_vars):
            raise ValueError(
                "Missing Azure OpenAI environment variables. Required: " +
                ", ".join(required_vars)
            )
        self.client = AzureOpenAI(
            api_key=os.environ["AZURE_API_KEY"],
            api_version=os.environ["AZURE_API_VERSION"],
            azure_endpoint=os.environ["AZURE_ENDPOINT"]
        )
        self.deployment_name = os.environ["DEPLOYMENT_ID"]

    async def chat_completion(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Any:
        return self.client.chat.completions.create(
            model=self.deployment_name,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            max_completion_tokens=1000
        )

    def get_model_name(self) -> str:
        return self.deployment_name
