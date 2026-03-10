from .input_mode_base import InputMode
from typing import Optional

class ChatInputMode(InputMode):
    """Interactive terminal chat input mode"""

    async def initialize(self):
        print("\033[95m\033[1m")
        print("🤖 YARP MCP Interactive Chat Client")
        print("=" * 50)
        print("\033[0m")
        print("\033[94mWelcome! I'm your AI assistant with access to YARP capabilities.\033[0m")
        print("\033[94mAvailable tools are discovered dynamically from MCP servers.\033[0m")
        print()
        print("\033[96mWhat you can do:\033[0m")
        print("  • Have natural conversations with the AI")
        print("  • Ask the AI to use available MCP tools")
        print("  • Get help with any discovered server capabilities")
        print()
        print("\033[93mType 'quit', 'exit', or 'bye' to end the conversation.\033[0m")
        print("-" * 50)

    async def get_input(self) -> Optional[str]:
        try:
            user_input = input(f"\n\033[92mYou: \033[0m").strip()
            if user_input.lower() in ['quit', 'exit', 'bye', 'q']:
                return None
            return user_input if user_input else ""
        except EOFError:
            return None

    async def send_response(self, response: str):
        print(f"\033[94m🤖 Assistant: \033[0m{response}")

    async def cleanup(self):
        print(f"\n\033[96m👋 Goodbye!\033[0m")
