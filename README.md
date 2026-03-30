# stm32-mcp

MCP server that lets Claude Code build, flash, and communicate with STM32 hardware.

[MCP (Model Context Protocol)](https://modelcontextprotocol.io) is an open standard that lets AI assistants like Claude use external tools. This server gives Claude the ability to compile your firmware, flash it to a board, talk to it over serial, and read memory via SWD — all from a single conversation.

> [!WARNING]
> This server gives an AI direct access to your compiler, debug probe, and serial ports. It can flash firmware, overwrite memory, and send arbitrary data to your hardware. This is powerful and useful, but it is not a sandbox. Know what's connected before you let it rip.

## Prerequisites

- **STM32CubeIDE** installed at `/Applications/STM32CubeIDE.app` (macOS) or `/opt/st/stm32cubeide_*` (Linux)
- **Python 3.10+**
- **OpenOCD** (`brew install open-ocd`) — for flash, memory read/write, and live monitoring
- **open-source stlink tools** (`brew install stlink`) — for probe enumeration
- **ST-Link** connected via USB (for flash/board info)
- **Serial port** available (ST-Link VCP or USB-UART adapter)

## Installation

```bash
git clone https://github.com/shieldyguy/stm32-mcp.git
cd stm32-mcp
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
      "command": "/path/to/stm32-mcp/.venv/bin/python",
      "args": ["-m", "stm32_mcp.server"]
    }
  }
}
```

## Available Tools

### Build & Flash

| Tool                    | Description                                            |
| ----------------------- | ------------------------------------------------------ |
| `stm32_build`           | Compile firmware using CubeIDE headless builder        |
| `stm32_flash`           | Flash .elf/.bin/.hex to board via ST-Link SWD          |
| `stm32_build_and_flash` | Build + flash in one step (the 90% case)               |
| `stm32_board_info`      | Read ST-Link/MCU info (device ID, flash size, voltage) |

### Multi-Board Management

| Tool                 | Description                                          |
| -------------------- | ---------------------------------------------------- |
| `stm32_list_probes`  | Show all connected boards with nicknames and MCU IDs |
| `stm32_set_nickname` | Name a board (by MCU UID) or probe (by ST-Link SN)   |

Board nicknames follow the physical MCU (persist across probe swaps). Probe nicknames follow the ST-Link hardware. Use nicknames in any `probe` parameter across all tools.

### Serial Communication

| Tool                | Description                                                |
| ------------------- | ---------------------------------------------------------- |
| `serial_list_ports` | List serial ports (marks ST-Link VCP ports with nicknames) |
| `serial_connect`    | Open a serial connection                                   |
| `serial_send`       | Send data and read response                                |
| `serial_read`       | Read buffered serial data                                  |
| `serial_disconnect` | Close a serial connection                                  |
| `serial_sequence`   | Run multi-step send/delay sequences in one call            |

### Debug & Monitoring

| Tool                 | Description                                                |
| -------------------- | ---------------------------------------------------------- |
| `stm32_read_memory`  | Read memory by address or variable name (from ELF symbols) |
| `stm32_write_memory` | Write memory by address or variable name                   |
| `live_memory_start`  | Start continuous background memory monitoring via SWD      |
| `live_memory_read`   | Read recent entries from a live memory session             |
| `live_memory_stop`   | Stop a live memory session                                 |

## Serial Sequences

`serial_sequence` runs multiple send and delay steps in a single tool call with real timing between steps — no tool-call overhead. This is critical for timing-sensitive hardware test sequences.

### Step types

```json
[
  { "send": "SIM_LEFT", "to": "/dev/cu.usbmodem11202" },
  { "delay_ms": 500 },
  {
    "send": "GET_BLINK_STATE",
    "to": "/dev/cu.usbmodem11402",
    "expect": "BLINK"
  },
  {
    "send": "SET_BRAKE_ON",
    "to": "/dev/cu.usbmodem11402",
    "read_timeout": 1.0,
    "line_ending": "lf"
  }
]
```

- **Send step:** `{send, to, expect?, read_timeout?, line_ending?}` — `to` is the port path from `serial_connect`
- **Delay step:** `{delay_ms}` — real `time.sleep()`, not tool-call round-trips

### Parameters

- **`on_failure`:** `"continue"` (default) runs all steps regardless. `"stop"` aborts on first failed assertion.
- **`filter_responses`:** When `true`, `expect` patterns match only `>`-prefixed VCP response lines (ignores debug noise).

### Output

```
Step 1 [/dev/cu.usbmodem11202] SEND: SIM_LEFT
  Response: >OK:SIM_LEFT

Step 2 DELAY: 500ms

Step 3 [/dev/cu.usbmodem11402] SEND: GET_BLINK_STATE
  Response: >BLINK_STATE:BLINK
  Expect "BLINK": PASS

Summary: 2/2 sends OK, 1/1 assertions PASS
```

## Live Memory Monitoring

Monitor firmware variables in real time via SWD, without modifying firmware or using serial. OpenOCD runs as a persistent subprocess and polls variables over its built-in TCL socket.

### Start a session

```
live_memory_start(
    variables='["blink", "ts"]',       # symbol names from ELF
    elf_path="/path/to/firmware.elf",
    probe="taillight",                  # board/probe nickname
    interval_ms=500                     # min 250ms
)
```

Variables can be:

- **Symbol names** (strings): `"blink"` — resolved from the ELF via `arm-none-eabi-nm`
- **Dicts with symbol + type**: `{"symbol": "temperature", "type": "float"}` — interprets 32-bit value as IEEE 754
- **Dicts with raw address**: `{"address": "0x20000304", "name": "x", "width": 32}`

### Read recent values

```
live_memory_read(session_id="abc123", last_n=10)
```

Returns recent entries from an in-memory ring buffer (max 100 entries). Full history is written to the JSONL output file.

### JSONL output format

```json
{ "t": 1709830123.456, "elapsed_s": 1.002, "values": { "blink": 65539 } }
```

### Stop a session

```
live_memory_stop(session_id="abc123")
```

Returns stats: duration, read count, error count, output file path.

### Constraints

- **One session per probe** — this is a hardware constraint (single SWD connection)
- **Stop before flashing** — `live_memory` holds the SWD connection; `stm32_flash` and `stm32_read/write_memory` will fail if a session is active
- **TCL port 6666** — OpenOCD's default. Stop other OpenOCD instances first if there's a conflict

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
