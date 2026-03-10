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

Options:
  --mode {chat,yarp,ros2}    Input mode (default: chat)
                             chat: Interactive terminal chat
                             yarp: Listen to YARP port for messages
                             ros2: Listen to ROS2 service for requests

  --model {local,remote}     LLM backend (default: remote)
                             remote: Azure OpenAI
                             local: Local Ollama instance

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

from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession

from modules.input_modes.input_mode_chat import ChatInputMode
from modules.input_modes.input_mode_yarp import YarpInputMode
from modules.input_modes.input_mode_ros2 import ROS2InputMode
from modules.llm_backends.llm_backend_azure import AzureOpenAIBackend
from modules.llm_backends.llm_backend_ollama import OllamaBackend
from modules.core.Yarp_mcpClient_GeneralCore import Yarp_mcpClient_GeneralCore

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


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="YARP MCP Swiss Army Client with multiple input modes and LLM backends",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive chat with Azure OpenAI
  python mcp_yarpSwissArmyClient.py --mode chat --model remote

  # YARP port input with local Ollama
  python mcp_yarpSwissArmyClient.py --mode yarp --model local --ollama-model llama3.2

  # ROS2 service with Azure OpenAI
  python mcp_yarpSwissArmyClient.py --mode ros2 --model remote
        """
    )

    parser.add_argument(
        "--mode",
        choices=["chat", "yarp", "ros2"],
        default="chat",
        help="Input mode: chat (interactive terminal), yarp (YARP port), or ros2 (ROS2 service)"
    )

    parser.add_argument(
        "--model",
        choices=["local", "remote"],
        default="remote",
        help="LLM backend: remote (Azure OpenAI) or local (Ollama)"
    )

    parser.add_argument(
        "--yarp-port",
        default="/mcp_client/input:i",
        help="YARP port name for yarp mode (default: /mcp_client/input:i)"
    )

    parser.add_argument(
        "--ros2-service",
        default="/mcp_client/query",
        help="ROS2 service name for ros2 mode (default: /mcp_client/query)"
    )

    parser.add_argument(
        "--ollama-url",
        default="http://localhost:11434/v1",
        help="Ollama API URL (default: http://localhost:11434/v1)"
    )

    parser.add_argument(
        "--ollama-model",
        default="llama3.2",
        help="Ollama model name (default: llama3.2)"
    )

    return parser.parse_args()


async def main():
    args = parse_arguments()

    print(f"{Colors.HEADER}Starting YARP MCP Swiss Army Client{Colors.ENDC}")
    print(f"  Mode: {args.mode}")
    print(f"  Model: {args.model}")
    print()

    try:
        if args.mode == "chat":
            input_mode = ChatInputMode()
        elif args.mode == "yarp":
            input_mode = YarpInputMode(port_name=args.yarp_port)
        elif args.mode == "ros2":
            input_mode = ROS2InputMode(service_name=args.ros2_service)
        else:
            print(f"{Colors.FAIL}Unknown mode: {args.mode}{Colors.ENDC}")
            return
    except Exception as e:
        print(f"{Colors.FAIL}❌ Failed to create input mode: {e}{Colors.ENDC}")
        import traceback
        traceback.print_exc()
        return

    try:
        if args.model == "remote":
            llm_backend = AzureOpenAIBackend()
        elif args.model == "local":
            llm_backend = OllamaBackend(
                base_url=args.ollama_url,
                model=args.ollama_model
            )
        else:
            print(f"{Colors.FAIL}Unknown model: {args.model}{Colors.ENDC}")
            return
        await llm_backend.initialize()
    except Exception as e:
        print(f"{Colors.FAIL}❌ Failed to initialize LLM backend: {e}{Colors.ENDC}")
        import traceback
        traceback.print_exc()
        return

    client = Yarp_mcpClient_GeneralCore(input_mode=input_mode, llm_backend=llm_backend)
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
