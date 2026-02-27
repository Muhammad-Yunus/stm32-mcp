# stm32-mcp

MCP server that lets Claude Code build, flash, and communicate with STM32 hardware — closing the edit-compile-flash-test loop without leaving the terminal.

## Prerequisites

- **STM32CubeIDE** installed at `/Applications/STM32CubeIDE.app` (macOS) or `/opt/st/stm32cubeide_*` (Linux)
- **Python 3.10+**
- **ST-Link** connected via USB (for flash/board info)
- **Serial port** available (ST-Link VCP or USB-UART adapter)

## Installation

```bash
cd ~/Desktop/shieldy/MCP/stm32-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Register with Claude Code

### Option A: CLI

```bash
claude mcp add stm32 -- /path/to/stm32-mcp/.venv/bin/python -m stm32_mcp.server
```

### Option B: Project config

Add to your project's `.claude/settings.json` or `.claude.json`:

```json
{
  "mcpServers": {
    "stm32": {
      "command": "/Users/chrismcdowell/Desktop/shieldy/MCP/stm32-mcp/.venv/bin/python",
      "args": ["-m", "stm32_mcp.server"]
    }
  }
}
```

## Available Tools

| Tool | Description |
|------|-------------|
| `stm32_build` | Compile firmware using CubeIDE headless builder |
| `stm32_flash` | Flash .elf/.bin/.hex to board via ST-Link SWD |
| `stm32_build_and_flash` | Build + flash in one step (the 90% case) |
| `stm32_board_info` | Read ST-Link/MCU info (device ID, flash size, voltage) |
| `serial_list_ports` | List serial ports (marks ST-Link VCP ports) |
| `serial_connect` | Open a serial connection |
| `serial_send` | Send data and read response |
| `serial_read` | Read buffered serial data |
| `serial_disconnect` | Close a serial connection |

## Serial Defaults

- **Baud rate:** 115200
- **Line ending:** LF (`\n`)
- **Read polling:** 50ms inter-byte sleep, 200ms silence break
- **Buffer limits:** 4096 bytes max read

## Development

### MCP Inspector

```bash
source .venv/bin/activate
mcp dev src/stm32_mcp/server.py
```

### Loopback Testing

Serial tools can be tested without hardware using pyserial's loopback:

```python
import serial
ser = serial.serial_for_url("loop://", baudrate=115200, timeout=0.1)
ser.write(b"PING\n")
print(ser.read(100))  # b'PING\n'
```
