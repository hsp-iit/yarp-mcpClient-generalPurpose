from typing import List, Dict, Any
from ..llm_backends.llm_backend_base import LLMBackend
from ..input_modes.input_mode_base import InputMode
from .Yarp_mcpClient_BaseCore import Yarp_mcpClient_BaseCore


class Yarp_mcpClient_GeneralCore(Yarp_mcpClient_BaseCore):
    """General purpose YARP MCP client core with support for custom prompts."""

    def __init__(self, input_mode: InputMode, llm_backend: LLMBackend, custom_prompt_file: str = None):
        """Initialize the general core client.

        Args:
            input_mode: Input mode for getting user input
            llm_backend: LLM backend for chat completion
            custom_prompt_file: Optional path to custom system prompt file
        """
        super().__init__(input_mode, llm_backend, custom_prompt_file)

