import json
from typing import List, Dict, Any, Optional
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession
import asyncio
import logging
import subprocess
from ..llm_backends.llm_backend_base import LLMBackend
from ..input_modes.input_mode_base import InputMode

# Try to import YARP for port discovery
try:
    import yarp
    YARP_AVAILABLE = True
except ImportError:
    YARP_AVAILABLE = False
    yarp = None

logger = logging.getLogger(__name__)

# Color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


class Yarp_mcpClient_BaseCore:
    """Base class for YARP MCP clients with common functionality for server discovery,
    tool management, and message processing. Subclasses should override template methods
    to customize behavior."""

    def __init__(self, input_mode: InputMode, llm_backend: LLMBackend, custom_prompt_file: str = None):
        self.input_mode = input_mode
        self.llm_backend = llm_backend
        self.custom_prompt_file = custom_prompt_file
        self.custom_prompt_text = None
        self.conversation_history: List[Dict[str, Any]] = []
        self.mcp_urls: Dict[str, str] = {}  # Maps server name to MCP URL
        self.tool_descriptions_cache = {}
        self.tool_to_server: Dict[str, str] = {}  # Maps tool name to server name
        self.system_prompt_addenda: Dict[str, str] = {}  # Maps server name to system prompt addendum
        self.available_tools = []
        self.system_prompt = ""  # Will be built dynamically after discovery

        # Load custom prompt from file if provided
        if self.custom_prompt_file:
            self._load_custom_prompt()

        # Tool parameter definitions (hardcoded, does not change)
        self._tool_parameters = self._define_tool_parameters()

    async def call_mcp_tool(self, tool_name: str, args: dict, server_url: str = None) -> dict:
        """Call an MCP tool and return the result

        Args:
            tool_name: Name of the tool to call
            args: Arguments for the tool
            server_url: URL of the MCP server (defaults to first available server if not specified)
        """
        if server_url is None:
            # Use first available server if not specified
            server_url = next(iter(self.mcp_urls.values())) if self.mcp_urls else None
            if not server_url:
                return {
                    "success": False,
                    "error": "No MCP servers available"
                }

        try:
            async with streamablehttp_client(server_url) as (read_stream, write_stream, get_session_id):
                async with ClientSession(read_stream, write_stream) as session:
                    # Initialize the session
                    await session.initialize()

                    # Call the tool
                    tool_result = await session.call_tool(tool_name, args)

                    # Convert the result to a dict format
                    if hasattr(tool_result, 'isError') and tool_result.isError:
                        return {
                            "success": False,
                            "error": str(tool_result.content) if hasattr(tool_result, 'content') else "Tool call failed"
                        }
                    else:
                        # Extract content from the tool result
                        content = {}
                        if hasattr(tool_result, 'content'):
                            for item in tool_result.content:
                                if hasattr(item, 'type') and item.type == "text":
                                    content["text"] = item.text
                                elif hasattr(item, 'type') and item.type == "json":
                                    if isinstance(item.json, dict):
                                        content.update(item.json)
                                    else:
                                        content["json"] = item.json

                        # Also include structured content if available
                        if hasattr(tool_result, 'structuredContent') and tool_result.structuredContent:
                            content.update(tool_result.structuredContent)

                        return {
                            "success": True,
                            **content
                        }

        except Exception as e:
            return {
                "success": False,
                "error": f"MCP connection error: {str(e)}"
            }

    async def discover_mcp_servers(self):
        """Discover available MCP servers and their tools using MCP client sessions"""
        self.tool_descriptions_cache = {}
        self.tool_to_server = {}
        self.system_prompt_addenda = {}
        self.mcp_urls = {}

        if not YARP_AVAILABLE:
            logger.warning("YARP not available for port discovery. Server discovery will fail.")
            return

        try:
            # Initialize YARP network
            if not yarp.Network.checkNetwork():
                yarp.Network.init()

            # Dynamically discover all MCP server info ports
            port_names = self._discover_mcp_ports()

            for port_name in port_names:
                try:
                    await asyncio.sleep(0.1)  # Small delay between queries
                    server_info = await self._query_server_info(port_name)
                    if server_info and "name" in server_info:
                        server_name = server_info["name"]
                        self.mcp_urls[server_name] = server_info.get("url", "")

                        # Store system prompt addendum if provided
                        if "system_prompt_addendum" in server_info:
                            self.system_prompt_addenda[server_name] = server_info["system_prompt_addendum"]
                            logger.info(f"Received system prompt addendum from '{server_name}'")
                        else:
                            logger.info(f"No system prompt addendum found for '{server_name}'")

                        descriptions = server_info.get("descriptions", {})
                        if descriptions:
                            self.tool_descriptions_cache.update(descriptions)
                            # Track which server each tool belongs to
                            for tool_name in descriptions.keys():
                                self.tool_to_server[tool_name] = server_name
                        logger.info(f"Discovered MCP server '{server_name}' at {server_info.get('url', 'unknown')} with {len(descriptions)} tools")
                except Exception as e:
                    logger.debug(f"Could not query {port_name}: {e}")

        except Exception as e:
            logger.warning(f"Error discovering MCP servers: {e}")

        # No fallback - if discovery failed, we have no servers
        if not self.mcp_urls:
            logger.warning("No MCP servers discovered. All server features will be unavailable.")

    def _discover_mcp_ports(self) -> List[str]:
        """
        Dynamically discover all YARP ports matching the pattern /mcp_server/*/info:o
        by parsing the output of 'yarp name list'

        Returns:
            List of port names matching the MCP server info port pattern
        """
        discovered_ports = []

        try:
            # Run 'yarp name list' command
            result = subprocess.run(
                ["yarp", "name", "list"],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                logger.debug(f"yarp name list failed with return code {result.returncode}")
                return discovered_ports

            # Parse the output
            # Format of each line: "registration name /port/name ip 192.168.1.41 port 10034 type tcp"
            for line in result.stdout.split('\n'):
                line = line.strip()

                # Lines with port registrations start with "registration name "
                if line.startswith("registration name "):
                    try:
                        # Extract the port name (between "registration name " and " ip")
                        after_name = line[len("registration name "):]
                        ip_index = after_name.find(" ip")
                        if ip_index != -1:
                            port_name = after_name[:ip_index]

                            # Filter for MCP server info ports
                            if port_name.startswith("/mcp_server") and port_name.endswith("/info:o"):
                                discovered_ports.append(port_name)
                                logger.debug(f"Discovered MCP server port: {port_name}")
                    except Exception as e:
                        logger.debug(f"Error parsing line: {line}, error: {e}")

        except Exception as e:
            logger.debug(f"Error discovering MCP ports: {e}")

        return discovered_ports

    async def _query_server_info(self, port_name: str) -> Dict[str, Any]:
        """Query a YARP RPC port for basic server info, then use MCP client session to get tools"""
        print(f"{Colors.OKBLUE}Querying {port_name} for server info...{Colors.ENDC}")
        try:
            # Create RPC client port to get server name and URL
            client_port = yarp.RpcClient()
            client_port_name = f"/mcp_client/discovery/{port_name.split('/')[-2]}:o"

            if not client_port.open(client_port_name):
                logger.debug(f"Failed to open client port {client_port_name}")
                return {}

            # Connect to server port
            if not yarp.Network.connect(client_port_name, port_name):
                logger.debug(f"Failed to connect to {port_name}")
                client_port.close()
                return {}

            server_info = {}

            # Query server name
            cmd = yarp.Bottle()
            reply = yarp.Bottle()
            cmd.addString("get_name")

            if client_port.write(cmd, reply):
                if reply.size() > 0:
                    server_info["name"] = reply.get(0).asString()

            # Query server MCP URL
            cmd = yarp.Bottle()
            reply = yarp.Bottle()
            cmd.addString("get_mcp_url")

            if client_port.write(cmd, reply):
                if reply.size() > 0:
                    server_info["url"] = reply.get(0).asString()

            cmd = yarp.Bottle()
            reply = yarp.Bottle()
            cmd.addString("get_system_prompt_addendum")
            if client_port.write(cmd, reply):
                if reply.size() > 0:
                    reply_str = reply.get(0).asString()
                    if reply_str and reply_str.lower() != "not_implemented":
                        server_info["system_prompt_addendum"] = reply.get(0).asString()

            client_port.close()

            # Now use MCP client session to get tool descriptions and system prompt addendum via MCP
            print(f"{Colors.OKBLUE}Querying MCP server '{server_info.get('name', 'unknown')}' for tools...{Colors.ENDC}")
            if server_info.get("url"):
                try:
                    async with streamablehttp_client(server_info["url"]) as (read_stream, write_stream, get_session_id):
                        async with ClientSession(read_stream, write_stream) as session:
                            await session.initialize()

                            # Get list of tools from the MCP server
                            tools_response = await session.list_tools()

                            # Extract descriptions from tools
                            descriptions = {}
                            for tool in tools_response.tools:
                                # Store tool info including description and schema
                                descriptions[tool.name] = {
                                    "description": tool.description,
                                    "inputSchema": tool.inputSchema.model_dump() if hasattr(tool.inputSchema, 'model_dump') else dict(tool.inputSchema)
                                }

                            server_info["descriptions"] = descriptions
                            logger.debug(f"Retrieved {len(descriptions)} tools from {server_info.get('name', 'unknown')} via MCP client session")
                            print(f"{Colors.OKGREEN}✅ Retrieved {len(descriptions)} tools from {server_info.get('name', 'unknown')} via MCP client session{Colors.ENDC}")

                except Exception as e:
                    logger.debug(f"Error querying tools via MCP client session for {server_info.get('name', 'unknown')}: {e}")

            return server_info

        except Exception as e:
            logger.debug(f"Error querying {port_name}: {e}")
            import traceback
            traceback.print_exc()
            return {}

    def _load_custom_prompt(self):
        """Load custom prompt from file"""
        try:
            with open(self.custom_prompt_file, 'r', encoding='utf-8') as f:
                self.custom_prompt_text = f.read().strip()
                logger.info(f"Loaded custom prompt from {self.custom_prompt_file} ({len(self.custom_prompt_text)} chars)")
                print(f"{Colors.OKGREEN}✅ Loaded custom prompt from {self.custom_prompt_file}{Colors.ENDC}")
        except FileNotFoundError:
            logger.error(f"Custom prompt file not found: {self.custom_prompt_file}")
            print(f"{Colors.FAIL}❌ Custom prompt file not found: {self.custom_prompt_file}{Colors.ENDC}")
            self.custom_prompt_text = None
        except Exception as e:
            logger.error(f"Error loading custom prompt file: {e}")
            print(f"{Colors.FAIL}❌ Error loading custom prompt file: {e}{Colors.ENDC}")
            self.custom_prompt_text = None

    def _define_tool_parameters(self) -> Dict[str, Dict]:
        """
        Define parameter information for known tools.

        Since tools are discovered dynamically from MCP servers, we only define
        parameters for tools where we have reliable information. For other tools,
        we let the MCP server validate the parameters.
        """
        # No hardcoded tool parameters - all tools use generic schema
        # Servers define their own parameter schemas
        return {}

    def _get_tool_parameters(self, tool_name: str) -> Dict:
        """
        Get parameters for a tool from discovered tool descriptions.

        Returns the input schema from the tool definition if available,
        otherwise returns a generic object schema that lets the MCP server validate.
        """
        # Check if we have tool info cached
        tool_info = self.tool_descriptions_cache.get(tool_name)
        if tool_info and isinstance(tool_info, dict) and "inputSchema" in tool_info:
            return tool_info["inputSchema"]

        # For tools without discovered schema, use a generic object schema
        # This allows the MCP server to handle validation
        return {
            "type": "object",
            "properties": {},
            "additionalProperties": True
        }

    def _get_base_system_prompt(self) -> str:
        """Get the base system prompt intro. Can be overridden by subclasses.

        Returns the intro text before the tools list.
        """
        # Use custom prompt if provided, otherwise use default R1 prompt
        if self.custom_prompt_text:
            return self.custom_prompt_text + "\n\nYou can help users with general questions and conversations, and you also have the ability to:\n\n"
        else:
            return """You are the robot R1 from the Italian Institute of Technology with access to YARP (Yet Another Robot Platform) capabilities through function calls.

IMPORTANT: You have access to actual function calling capabilities. When you need to use YARP tools, use the provided function calls - do NOT generate fake JSON objects or mock responses in your text. Only describe what you're doing and what the actual results were.

You can help users with general questions and conversations, and you also have the ability to:

"""

    def _get_system_prompt_additions(self) -> str:
        """Get additional text to add to the system prompt after tools list.

        Subclasses can override this to add specialized instructions.
        Default returns guidance for using YARP tools.
        """
        return """
When using YARP tools:
1. Use the appropriate tool functions with the requested parameters
2. Describe the results based on what the actual function calls returned

Be conversational and helpful. Explain what you're doing with the YARP tools, but use actual function calls rather than generating mock responses."""

    def _build_system_prompt(self) -> str:
        """Build system prompt dynamically based on discovered tools"""
        if not self.tool_descriptions_cache:
            return "You are a helpful AI assistant with access to YARP capabilities through function calls."

        # Get base prompt from subclass
        prompt = self._get_base_system_prompt()

        # Organize tools by server using the discovered tool_to_server mapping
        tools_by_server = {}
        for tool_name, tool_info in self.tool_descriptions_cache.items():
            # Get the server this tool belongs to from discovery
            server_name = self.tool_to_server.get(tool_name, "Unknown")
            # Capitalize for display
            server = f"{server_name.capitalize()} Server"

            if server not in tools_by_server:
                tools_by_server[server] = []

            # Extract description from tool info
            if isinstance(tool_info, dict):
                desc = tool_info.get("description", "")
            else:
                desc = str(tool_info)

            tools_by_server[server].append((tool_name, desc))

        # Build tool section for each server
        counter = 1
        for server_type in sorted(tools_by_server.keys()):
            prompt += f"\n**{server_type}:**\n"
            for tool_name, description in tools_by_server[server_type]:
                prompt += f"{counter}. **{tool_name}** - {description}\n"
                counter += 1

        # Add prompt additions from subclass
        prompt += self._get_system_prompt_additions()

        # Add system prompt addenda from servers
        if self.system_prompt_addenda:
            logger.info(f"Adding {len(self.system_prompt_addenda)} system prompt addenda to prompt")
            prompt += "\n\n" + "="*80 + "\n"
            prompt += "ADDITIONAL REQUIREMENTS FROM CONNECTED SERVERS:\n"
            prompt += "="*80 + "\n"
            for server_name, addendum in self.system_prompt_addenda.items():
                logger.info(f"Including addendum from server: {server_name}")
                prompt += f"\n[From {server_name.upper()} Server]:\n{addendum}\n"
        else:
            logger.info("No system prompt addenda found from servers")

        return prompt

    def get_available_tools(self) -> List[Dict[str, Any]]:
        """Build tools dynamically from discovered tool descriptions.

        Subclasses can override to add additional special tools.
        """
        tools = []

        if not self.tool_descriptions_cache:
            logger.warning("No tool descriptions in cache. Tools may not be available.")
            return tools

        for tool_name, tool_info in self.tool_descriptions_cache.items():
            # Extract description
            if isinstance(tool_info, dict):
                description = tool_info.get("description", f"Tool: {tool_name}")
            else:
                description = str(tool_info)

            # Get parameters using the fallback method
            parameters = self._get_tool_parameters(tool_name)

            tool_def = {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": description,
                    "parameters": parameters,
                },
            }

            tools.append(tool_def)

        return tools

    async def _handle_tool_call(self, tool_call: Any) -> Dict[str, Any]:
        """Handle a tool call and return the result.

        Subclasses can override to add special tool call handling (e.g., monitoring tasks).
        Default behavior: determine server and call the MCP tool.

        Args:
            tool_call: The tool call object with id, function name, and arguments

        Returns:
            Result dictionary from the tool call
        """
        fn_name = tool_call.function.name
        fn_args = json.loads(tool_call.function.arguments)

        print(f"{Colors.OKCYAN}🔧 Calling YARP tool: {fn_name}({fn_args}){Colors.ENDC}")

        # Determine which server this tool belongs to
        server_name = self.tool_to_server.get(fn_name)

        if server_name and server_name in self.mcp_urls:
            server_url = self.mcp_urls[server_name]
        else:
            # Tool not in our mapping, try first available server
            server_url = next(iter(self.mcp_urls.values())) if self.mcp_urls else "http://127.0.0.1:4000/mcp"

        # Call the MCP tool
        return await self.call_mcp_tool(fn_name, fn_args, server_url)

    async def process_user_message(self, user_input: str) -> str:
        """Process user message and get LLM response, handling tool calls"""

        # Check for special commands
        if user_input.lower().strip() in ["!system_prompt", "!prompt", "!sp"]:
            return f"Current System Prompt:\n\n{self.system_prompt}"

        if user_input.lower().strip() in ["!addenda", "!server_addenda"]:
            if self.system_prompt_addenda:
                result = "Server-provided system prompt addenda:\n\n"
                for server_name, addendum in self.system_prompt_addenda.items():
                    result += f"[{server_name.upper()}]\n{addendum}\n\n"
                return result
            else:
                return "No server-provided system prompt addenda found."

        # Add user message to conversation history
        self.conversation_history.append({"role": "user", "content": user_input})

        # Keep calling the LLM until it stops making tool calls
        max_iterations = 20  # Allow up to 20 tool call iterations for complex interactions
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            # Prepare messages for the LLM (include system prompt)
            messages = []
            messages.append({"role": "system", "content": self.system_prompt})
            messages.extend(self.conversation_history)

            try:
                # Log what we're sending to the LLM
                logger.info(f"Sending {len(messages)} messages to LLM (including system prompt: {any(m.get('role') == 'system' for m in messages)})")
                if any(m.get('role') == 'system' for m in messages):
                    sys_msg = next(m for m in messages if m.get('role') == 'system')
                    logger.debug(f"System prompt being sent ({len(sys_msg['content'])} chars)")

                # Call LLM backend
                response = await self.llm_backend.chat_completion(
                    messages=messages,
                    tools=self.get_available_tools()
                )

                message = response.choices[0].message

                # Handle tool calls if present
                if message.tool_calls:
                    # Add the assistant's message with tool calls to history
                    self.conversation_history.append({
                        "role": "assistant",
                        "content": message.content,
                        "tool_calls": [
                            {
                                "id": tool_call.id,
                                "type": "function",
                                "function": {
                                    "name": tool_call.function.name,
                                    "arguments": tool_call.function.arguments
                                }
                            }
                            for tool_call in message.tool_calls
                        ]
                    })

                    # Process each tool call
                    for tool_call in message.tool_calls:
                        # Call subclass method to handle the tool call
                        result = await self._handle_tool_call(tool_call)

                        # Add tool result to conversation
                        self.conversation_history.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.function.name,
                            "content": json.dumps(result),
                        })

                    # Continue the loop to let the LLM respond to the tool results
                    continue

                else:
                    # No tool calls, this is the final response
                    response_content = message.content
                    self.conversation_history.append({"role": "assistant", "content": response_content})
                    return response_content

            except Exception as e:
                error_msg = f"Error communicating with LLM: {str(e)}"
                print(f"{Colors.FAIL}❌ {error_msg}{Colors.ENDC}")
                return error_msg

        # If we hit max iterations, return whatever we have
        return "I've completed the available tool calls but may have reached the iteration limit."

    async def _run_loop_setup(self):
        """Setup hook for subclasses before starting the main loop.

        Override this to perform subclass-specific initialization.
        """
        pass

    async def _run_loop_cleanup(self):
        """Cleanup hook for subclasses after the main loop ends.

        Override this to perform subclass-specific cleanup.
        """
        pass

    async def run_loop(self):
        """Main run loop - works with any input mode"""
        # Initialize input mode
        await self.input_mode.initialize()

        # Discover MCP servers and their tool descriptions
        print(f"{Colors.OKBLUE}Discovering MCP servers...{Colors.ENDC}")
        await self.discover_mcp_servers()

        # Build available tools from discovered descriptions
        self.available_tools = self.get_available_tools()

        # Build system prompt dynamically from discovered tools
        self.system_prompt = self._build_system_prompt()
        logger.info(f"System prompt built. Length: {len(self.system_prompt)} chars")
        logger.info(f"System prompt addenda count: {len(self.system_prompt_addenda)}")
        logger.debug(f"System prompt: {self.system_prompt[:300]}...")

        # Print system prompt for debugging
        print(f"\n{Colors.OKBLUE}{'='*80}")
        print(f"SYSTEM PROMPT FOR THIS SESSION:")
        print(f"{'='*80}{Colors.ENDC}")
        print(self.system_prompt)
        print(f"{Colors.OKBLUE}{'='*80}{Colors.ENDC}\n")

        # Call subclass setup hook
        await self._run_loop_setup()

        while True:
            try:
                # Get input from the input mode
                user_input = await self.input_mode.get_input()

                # None means shutdown requested
                if user_input is None:
                    break

                # Empty string means no input yet (continue waiting)
                if not user_input:
                    continue

                # Process the message and get response
                response = await self.process_user_message(user_input)

                # Send response through the input mode
                await self.input_mode.send_response(response)

            except KeyboardInterrupt:
                print(f"\n\n{Colors.OKCYAN}👋 Interrupted!{Colors.ENDC}")
                break
            except Exception as e:
                print(f"\n{Colors.FAIL}❌ Unexpected error: {e}{Colors.ENDC}")
                import traceback
                traceback.print_exc()
                continue

        # Call subclass cleanup hook
        await self._run_loop_cleanup()

        # Cleanup input mode
        await self.input_mode.cleanup()
