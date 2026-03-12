from .input_mode_base import InputMode
from typing import Optional

class YarpInputMode(InputMode):
    """YARP port input mode"""

    def __init__(self, port_name: str = "/mcp_client/input:i"):
        self.port_name = port_name
        self.input_port = None
        self.output_port = None
        self.yarp_network = None

    async def initialize(self):
        import yarp
        yarp.Network.init()
        self.yarp_network = yarp.Network()
        if not self.yarp_network.checkNetwork():
            raise RuntimeError("YARP network not available. Please start yarpserver.")
        self.input_port = yarp.BufferedPortBottle()
        if not self.input_port.open(self.port_name):
            raise RuntimeError(f"Failed to open YARP input port: {self.port_name}")
        output_port_name = self.port_name.replace(":i", ":o")
        self.output_port = yarp.BufferedPortBottle()
        if not self.output_port.open(output_port_name):
            raise RuntimeError(f"Failed to open YARP output port: {output_port_name}")
        print(f"\033[92m✅ YARP ports opened:\033[0m")
        print(f"   Input: {self.port_name}")
        print(f"   Output: {output_port_name}")
        print(f"\033[96mWaiting for messages on {self.port_name}...\033[0m")

    async def get_input(self) -> Optional[str]:
        import yarp
        bottle = self.input_port.read(False)
        if bottle is not None and bottle.size() > 0:
            message = bottle.get(0).asString()
            print(f"\033[92m📥 Received from YARP: {message}\033[0m")
            return message
        import asyncio
        await asyncio.sleep(0.1)
        return ""

    async def send_response(self, response: str):
        import yarp
        bottle = self.output_port.prepare()
        bottle.clear()
        bottle.addString(response)
        self.output_port.write()
        print(f"\033[96m📤 Sent to YARP: {response[:100]}...\033[0m")

    async def cleanup(self):
        import yarp
        if self.input_port:
            self.input_port.close()
        if self.output_port:
            self.output_port.close()
        if self.yarp_network:
            yarp.Network.fini()
        print(f"\033[96mYARP ports closed\033[0m")
