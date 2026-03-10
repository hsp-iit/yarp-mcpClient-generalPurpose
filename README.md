# YARP MCP General Purpose Client

A conversational AI client that **automatically discovers and uses YARP MCP servers** through natural language.

## ⚠️ Disclaimer

This codebase has been written with the contribution of generative AI. While the code has been tested, please use it carefully and review it for your specific use case before deploying in production environments.

**This repository is under active development** and may change significantly with each new commit. Breaking changes may occur without notice.

## Setup

### Option 1: Using `uv` (Recommended - Fast)
```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Run the client
uv run python Yarp_mcpClient_GeneralPurpose.py --mode chat --model remote
```

### Option 2: Using Conda
```bash
# Create conda environment from file
conda env create -f environment.yml

# Activate environment
conda activate yarp-mcp-client

# Run the client
python Yarp_mcpClient_GeneralPurpose.py --mode chat --model remote
```

## Quick Start

### 1. Chat Mode (Interactive Terminal)
```bash
# With uv
uv run python Yarp_mcpClient_GeneralPurpose.py --mode chat --model remote

# Or with conda (after: conda activate yarp-mcp-client)
python Yarp_mcpClient_GeneralPurpose.py --mode chat --model remote
```

**Environment variables for Azure OpenAI (remote mode):**
```bash
export AZURE_API_KEY="your-key"
export AZURE_API_VERSION="2024-02-15-preview"
export AZURE_ENDPOINT="https://your-resource.openai.azure.com"
export DEPLOYMENT_ID="gpt-4"
```

**Or use local Ollama (no API key needed):**
```bash
uv run python Yarp_mcpClient_GeneralPurpose.py --mode chat --model local --ollama-model llama2
# Or with conda:
python Yarp_mcpClient_GeneralPurpose.py --mode chat --model local --ollama-model llama2
```

### 2. YARP Port Mode
```bash
# Terminal 1: Start yarpserver
yarpserver

# Terminal 2: Start client
# With uv:
uv run python Yarp_mcpClient_GeneralPurpose.py --mode yarp --model local
# Or with conda:
conda activate yarp-mcp-client
python Yarp_mcpClient_GeneralPurpose.py --mode yarp --model local

# Terminal 3: Send messages
yarp write /test /mcp_client/input:i
# Type your message and press Enter
```

### 3. ROS2 Service Mode (Placeholder)
```bash
# With uv:
uv run python Yarp_mcpClient_GeneralPurpose.py --mode ros2 --model remote
# Or with conda:
python Yarp_mcpClient_GeneralPurpose.py --mode ros2 --model remote
```

## Options

| Option | Values | Default | Notes |
|--------|--------|---------|-------|
| `--mode` | chat, yarp, ros2 | chat | Input mode |
| `--model` | local, remote | remote | LLM backend |
| `--yarp-port` | port name | /mcp_client/input:i | YARP input port (yarp mode only) |
| `--ollama-url` | URL | http://localhost:11434 | Ollama API (local mode only) |
| `--ollama-model` | model name | llama2 | Ollama model (local mode only) |

## How It Works

```
User Input (chat/YARP/ROS2)
         ↓
Yarp_mcpClient_GeneralPurpose.py
         ↓
Yarp_mcpClient_GeneralCore.py (discover, manage sessions, call tools)
         ↓
YARP Network (discovers MCP servers via /mcp_server/*/info:o ports)
         ↓
MCP Servers (speech, battery, etc.) ←→ YARP Devices
```

### Key Features

✅ **Auto-discovery** - Finds all MCP servers on YARP network
✅ **Persistent sessions** - Reuses connections (efficient)
✅ **Dynamic tools** - Adapts to any MCP server (via `list_tools()`)
✅ **Multiple modes** - Terminal, YARP port, ROS2 service
✅ **Multiple backends** - Azure OpenAI or local Ollama

## Prerequisites

### YARP
```bash
yarpserver  # Start YARP name server
# (For yarp mode only; not needed for chat mode)
```

### Azure OpenAI (remote mode)
```bash
export AZURE_API_KEY="your-api-key"
export AZURE_API_VERSION="2024-02-15-preview"
export AZURE_ENDPOINT="https://your-resource.openai.azure.com"
export DEPLOYMENT_ID="gpt-4"
```

### Ollama (local mode)
```bash
# Install: https://ollama.ai/
ollama pull llama2  # or mistral, codellama, etc.
ollama serve        # (usually auto-starts)
```

### MCP Servers
At least one MCP server must be running and discoverable on YARP. See the [yarp-mcpServers-devices](https://github.com/hsp-iit/yarp-mcpServers-devices) repository for instructions on launching available servers (ISpeechSynthesizer, IBattery, etc.).

## Examples

### Example 1: Chat with Available MCP Servers
```bash
# Terminal: Start YARP servers
# See https://github.com/hsp-iit/yarp-mcpServers-devices for launch instructions

# Start client (with uv)
uv run python Yarp_mcpClient_GeneralPurpose.py --mode chat --model remote

# Or with conda (after: conda activate yarp-mcp-client)
python Yarp_mcpClient_GeneralPurpose.py --mode chat --model remote

# Try these:
> Speak "Welcome to YARP"
> Say hello world
> What can you do?
```

### Example 2: YARP Integration
```bash
# Terminal 1: Start YARP servers
# See https://github.com/hsp-iit/yarp-mcpServers-devices for launch instructions

# Terminal 2: Client (with uv)
uv run python Yarp_mcpClient_GeneralPurpose.py --mode yarp --model local
# Or with conda:
python Yarp_mcpClient_GeneralPurpose.py --mode yarp --model local

# Terminal 3: Send messages
echo "Hello" | yarp write /test /mcp_client/input:i
```

### Example 3: Offline with Ollama
```bash
# Terminal 1: Start ollama (if not running)
ollama serve

# Terminal 2: Start client (with uv, no API key needed!)
uv run python Yarp_mcpClient_GeneralPurpose.py --mode chat --model local --ollama-model mistral
# Or with conda:
python Yarp_mcpClient_GeneralPurpose.py --mode chat --model local --ollama-model mistral

# Chat freely offline
```

## Architecture

### File Structure
- **Yarp_mcpClient_GeneralPurpose.py** - Entry point, argument parsing
- **Yarp_mcpClient_GeneralCore.py** - Core logic (server discovery, session management, tool routing)
- **input_mode_*.py** - Input modes (chat, yarp, ros2)
- **llm_backend_*.py** - LLM backends (azure, ollama)

### Discovery Process

1. **YARP Port Discovery**: Parses `yarp name list` to find `/mcp_server/*/info:o` ports
2. **RPC Queries**: Gets server name, URL, system prompt addenda via YARP RPC
3. **Session Creation**: Creates persistent MCP session to server URL
4. **Tool Discovery**: Calls `session.list_tools()` to get available tools
5. **Session Reuse**: All subsequent tool calls use the persistent session

## Troubleshooting

### "No MCP servers discovered"
```bash
# Check YARP is running
yarpserver

# Check if any servers are registered
yarp name list | grep "mcp_server.*info:o"

# To launch servers, see: https://github.com/hsp-iit/yarp-mcpServers-devices
```

### "Azure API connection failed"
```bash
# Check all env vars are set
echo $AZURE_API_KEY $AZURE_API_VERSION $AZURE_ENDPOINT $DEPLOYMENT_ID

# Verify they're correct for your Azure account
```

### "Ollama connection failed"
```bash
# Check Ollama is running
curl http://localhost:11434/api/tags

# Start it
ollama serve

# Install model
ollama pull llama2
```

### "Failed to open YARP port"
```bash
# Check port isn't in use
yarp name list | grep input:i

# Use different port
python Yarp_mcpClient_GeneralPurpose.py --mode yarp --yarp-port /my_robot/llm:i
```

## Architecture Improvements (Recent Refactoring)

- ✅ **Persistent MCP Sessions** - One session per server, reused for all tool calls
- ✅ **MCP-native Tool Discovery** - Uses `list_tools()` instead of custom RPC calls
- ✅ **Dynamic Tool Loading** - No hardcoded tool definitions; adapts to any MCP server
- ✅ **YARP RPC for Metadata** - Still uses RPC for server discovery and system prompts (by design)

This follows MCP best practices while maintaining compatibility with YARP's RPC-based server discovery.
