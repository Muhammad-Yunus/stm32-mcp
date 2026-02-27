"""stm32-mcp server — entry point and tool registration."""

import logging

from mcp.server.fastmcp import FastMCP

from .build import stm32_build, stm32_build_and_flash
from .flash import stm32_board_info, stm32_flash
from .serial_tools import (
    serial_connect,
    serial_disconnect,
    serial_list_ports,
    serial_read,
    serial_send,
)

INSTRUCTIONS = """\
stm32-mcp: Build, flash, and communicate with STM32 hardware.

## Available Tools

- stm32_build          — Compile firmware using CubeIDE headless builder
- stm32_flash          — Flash .elf/.bin/.hex to board via ST-Link SWD
- stm32_build_and_flash — Build + flash in one step (use this most of the time)
- stm32_board_info     — Read ST-Link and MCU info (device ID, flash size, voltage)
- serial_list_ports    — List serial ports (marks ST-Link VCP ports)
- serial_connect       — Open a serial connection
- serial_send          — Send data and read response
- serial_read          — Read buffered serial data
- serial_disconnect    — Close a serial connection

## Typical Workflow

1. Edit source files (Core/Src/*.c, Core/Inc/*.h)
2. stm32_build_and_flash(project_path="/path/to/project") — build + flash
3. serial_connect(port="/dev/cu.usbmodemXXXX") — open VCP
4. serial_send(connection_id="...", data="PING") — test firmware
5. serial_disconnect(connection_id="...") — clean up

## Rules

- project_path must point to a directory containing .project and .cproject files
- Never edit files in Debug/, Release/, Drivers/, or .cproject
- New .c/.h files are automatically detected by the headless builder
- Always build before flashing
- Always verify behavior over serial after flashing
- Serial default: 115200 baud, LF line endings
"""

mcp = FastMCP("stm32-mcp", instructions=INSTRUCTIONS)

# Register all 9 tools
mcp.tool()(stm32_build)
mcp.tool()(stm32_build_and_flash)
mcp.tool()(stm32_flash)
mcp.tool()(stm32_board_info)
mcp.tool()(serial_list_ports)
mcp.tool()(serial_connect)
mcp.tool()(serial_send)
mcp.tool()(serial_read)
mcp.tool()(serial_disconnect)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    mcp.run()


if __name__ == "__main__":
    main()
