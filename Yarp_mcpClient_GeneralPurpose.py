#!/usr/bin/env python3
"""
YARP MCP Swiss Army Client

This client provides a conversational interface with LLMs (Azure OpenAI or local Ollama)
and automatically discovers available MCP servers on the YARP network.

Discovered MCP servers can provide various capabilities such as:
- Speech synthesis and audio control
- Battery monitoring and status
- Vision processing and telemetry
- Motion control and sensor data
- System monitoring and diagnostics
- Any custom MCP tools exposed via MCP servers

Natural language examples:
- "Use the available tools to help me"
- "What capabilities do you have?"
- "Show me what you can do"

Usage:
  python mcp_yarpSwissArmyClient.py --mode chat --model remote
  python mcp_yarpSwissArmyClient.py --mode yarp --model local
  python mcp_yarpSwissArmyClient.py --mode ros2 --model remote
  python mcp_yarpSwissArmyClient.py --mode chat --model remote --core checker

Options:
  --mode {chat,yarp,ros2}    Input mode (default: chat)
                             chat: Interactive terminal chat
                             yarp: Listen to YARP port for messages
                             ros2: Listen to ROS2 service for requests

  --model {local,remote}     LLM backend (default: remote)
                             remote: Azure OpenAI
                             local: Local Ollama instance

  --core {standard,checker}  Client core type (default: checker)
                             standard: Basic MCP client without operation tracking
                             checker: MCP operation-resource tracking and completion updates

  --yarp-port PORT          YARP port name for yarp mode (default: /mcp_client/input:i)
  --ollama-url URL          Ollama API URL (default: http://localhost:11434)
  --ollama-model MODEL      Ollama model name (default: llama3.2)

Requirements:
- At least one MCP server running and exposing /mcp_server/<name>/info:o port
- YARP network initialized
- For remote mode: Azure OpenAI credentials in environment variables
- For local mode: Ollama running with a model installed
- For yarp mode: YARP network running
- For ros2 mode: ROS2 environment configured
"""

import os
import json
import asyncio
import sys
import argparse
from typing import List, Dict, Any, Optional


from src.input_modes.input_mode_chat import ChatInputMode
from src.input_modes.input_mode_yarp import YarpInputMode
from src.input_modes.input_mode_ros2 import ROS2InputMode
from src.llm_backends.llm_backend_azure import AzureOpenAIBackend
from src.llm_backends.llm_backend_ollama import OllamaBackend
from src.core.Yarp_mcpClient_GeneralCore import Yarp_mcpClient_GeneralCore
from src.core.Yarp_mcpClient_GeneralCheckerCore import Yarp_mcpClient_GeneralCheckerCore

# Try to import YARP
try:
    import yarp
except ImportError:
    print("ERROR: YARP Python bindings not found. Please install YARP with Python support.")
    sys.exit(1)

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


async def main():
    config = yarp.ResourceFinder()
    config.setDefault("mode", "chat")
    config.setDefault("model", "remote")
    config.setDefault("core", "checker")
    config.configure(sys.argv)

    if config.check("help"):
        print("Usage: python mcp_yarpSwissArmyClient.py [options]")
        print("Options:")
        print("  --mode {chat,yarp,ros2}          Input mode (default: chat)")
        print("  --model {local,remote}           LLM backend (default: remote)")
        print("  --core {standard,checker}        Client core type (default: checker)")
        print("  --yarp-port PORT                 YARP port name for yarp mode (default: /mcp_client/input:i)")
        print("  --ollama-url URL                 Ollama API URL (default: http://localhost:11434)")
        print("  --ollama-model MODEL             Ollama model name (default: llama3.2)")
        print("  --custom-prompt-from FILE        Name of a custom prompt file (optional)")
        print("  --custom-prompt-context CONTEXT  Context for the custom prompt (optional)")
        print("  --ros2-service SERVICE_NAME      ROS2 service name for ros2 mode (default: /mcp_client/request)")
        print("  --help                           Show this help message")
        return

    print(f"{Colors.HEADER}Starting YARP MCP Swiss Army Client{Colors.ENDC}")
    print(f"  {config.toString_c()}")
    print()

    params = {}

    try:
        if config.check("mode"):
            mode = config.find("mode").asString()
            if mode == "chat":
                input_mode = ChatInputMode()
            elif mode == "yarp":
                if not config.check("yarp-port"):
                    print(f"{Colors.FAIL}❌ YARP port name is required for yarp mode. Use --yarp-port option.{Colors.ENDC}")
                    return
                input_mode = YarpInputMode(port_name=config.find("yarp-port").asString())
            elif mode == "ros2":
                if not config.check("ros2-service"):
                    print(f"{Colors.FAIL}❌ ROS2 service name is required for ros2 mode. Use --ros2-service option.{Colors.ENDC}")
                    return
                input_mode = ROS2InputMode(service_name=config.find("ros2-service").asString())
        else:
            print(f"{Colors.FAIL}No input mode specified. Use --mode option.{Colors.ENDC}")
            return
    except Exception as e:
        print(f"{Colors.FAIL}❌ Failed to create input mode: {e}{Colors.ENDC}")
        import traceback
        traceback.print_exc()
        return
    params["input_mode"] = input_mode

    try:
        if config.check("model"):
            model = config.find("model").asString()
            if model == "remote":
                llm_backend = AzureOpenAIBackend()
            elif model == "local":
                if not config.check("ollama-url") or not config.check("ollama-model"):
                    print(f"{Colors.FAIL}❌ Ollama URL and model are required for local mode. Use --ollama-url and --ollama-model options.{Colors.ENDC}")
                    return
                llm_backend = OllamaBackend(
                    base_url=config.find("ollama-url").asString(),
                    model=config.find("ollama-model").asString()
                )
            else:
                print(f"{Colors.FAIL}Unknown model: {model}{Colors.ENDC}")
                return
            await llm_backend.initialize()
    except Exception as e:
        print(f"{Colors.FAIL}❌ Failed to initialize LLM backend: {e}{Colors.ENDC}")
        import traceback
        traceback.print_exc()
        return

    params["llm_backend"] = llm_backend

    if config.check("custom-prompt-from"):
        findPrompt = yarp.ResourceFinder()
        if config.check("custom-prompt-context"):
            findPrompt.setDefaultContext(config.find("custom-prompt-context").asString())
        custom_prompt_file = findPrompt.findFileByName(config.find("custom-prompt-from").asString())
        if not os.path.isfile(custom_prompt_file):
            print(f"{Colors.FAIL}❌ Custom prompt file not found: {custom_prompt_file}{Colors.ENDC}")
            return
        params["custom_prompt_file"] = custom_prompt_file
        print(f"{Colors.OKGREEN}Using custom prompt from file: {custom_prompt_file}{Colors.ENDC}")


    # Select the appropriate client core based on user choice
    if config.check("core"):
        core = config.find("core").asString()
        if core == "checker":
            client = Yarp_mcpClient_GeneralCheckerCore(**params)
            print(f"{Colors.OKBLUE}Using CheckerCore with operation tracking{Colors.ENDC}\n")
        elif core == "standard":
            client = Yarp_mcpClient_GeneralCore(**params)
            print(f"{Colors.OKBLUE}Using Standard Core{Colors.ENDC}\n")
        else:
            print(f"{Colors.FAIL}Unknown core type: {core}{Colors.ENDC}")
            return

    await client.run_loop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{Colors.OKCYAN}Goodbye!{Colors.ENDC}")
    except Exception as e:
        print(f"{Colors.FAIL}Fatal error: {e}{Colors.ENDC}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
