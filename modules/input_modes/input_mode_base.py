from abc import ABC, abstractmethod
from typing import Optional

class InputMode(ABC):
    """Abstract base class for input modes"""

    @abstractmethod
    async def initialize(self):
        """Initialize the input mode"""
        pass

    @abstractmethod
    async def get_input(self) -> Optional[str]:
        """Get input from the source. Returns None if input source is closed."""
        pass

    @abstractmethod
    async def send_response(self, response: str):
        """Send response back (if applicable)"""
        pass

    @abstractmethod
    async def cleanup(self):
        """Cleanup resources"""
        pass
