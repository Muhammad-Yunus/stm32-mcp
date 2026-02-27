"""Flash tools — STM32_Programmer_CLI wrapper."""

import asyncio
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

from .toolchain import find_programmer_cli

_executor = ThreadPoolExecutor(max_workers=2)

FLASH_TIMEOUT = 30  # seconds
INFO_TIMEOUT = 10   # seconds


def _do_flash(elf_path: str, reset: bool = True, verify: bool = True) -> str:
    """Synchronous flash — runs in executor thread."""
    cli = find_programmer_cli()
    if not cli:
        return "ERROR: STM32_Programmer_CLI not found. Install CubeIDE or CubeCLT."

    if not os.path.isfile(elf_path):
        return f"ERROR: File not found: {elf_path}"

    cmd = [cli, "-c", "port=SWD", "-w", elf_path]
    if verify:
        cmd.append("-v")
    if reset:
        cmd.append("-hardRst")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=FLASH_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        return f"ERROR: Flash timed out after {FLASH_TIMEOUT}s."

    output = result.stdout + "\n" + result.stderr

    # Parse for common errors
    if "No STM32 target found" in output or "No ST-LINK detected" in output:
        return "ERROR: No ST-Link detected. Check USB connection and board power."

    if "read out protection" in output.lower() or "RDP level" in output:
        return (
            "ERROR: Chip is read-protected. To mass erase and unlock:\n"
            f"  {cli} -c port=SWD -ob RDP=0xAA\n"
            "WARNING: This erases all flash contents."
        )

    # Extract key info
    parts = []

    # ST-LINK info
    stlink_match = re.search(r"ST-LINK\s+(SN|serial)\s*:\s*(\S+)", output, re.IGNORECASE)
    if stlink_match:
        parts.append(f"ST-LINK: {stlink_match.group(2)}")

    # Download result
    if "File download complete" in output or "download verified successfully" in output.lower():
        parts.append("Flash: OK")
    elif result.returncode != 0:
        parts.append("Flash: FAILED")

    # Verify result
    if verify:
        if "verified successfully" in output.lower():
            parts.append("Verify: OK")
        elif "verification failed" in output.lower():
            parts.append("Verify: FAILED")

    if reset and "MCU Reset" in output:
        parts.append("Reset: OK")

    # If we couldn't parse anything useful, return raw output
    if not parts:
        return output.strip()

    # Add any error lines from output
    for line in output.splitlines():
        if "error" in line.lower() and "error:" not in "\n".join(parts).lower():
            parts.append(f"  {line.strip()}")

    return "\n".join(parts)


def _do_board_info() -> str:
    """Synchronous board info — runs in executor thread."""
    cli = find_programmer_cli()
    if not cli:
        return "ERROR: STM32_Programmer_CLI not found. Install CubeIDE or CubeCLT."

    cmd = [cli, "-c", "port=SWD", "mode=NORMAL", "-rdu"]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=INFO_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        return f"ERROR: Board info timed out after {INFO_TIMEOUT}s."

    output = result.stdout + "\n" + result.stderr

    if "No STM32 target found" in output or "No ST-LINK detected" in output:
        return "ERROR: No ST-Link detected. Check USB connection and board power."

    # Extract useful fields
    info = []

    patterns = [
        (r"ST-LINK\s+SN\s*:\s*(\S+)", "ST-LINK SN"),
        (r"ST-LINK\s+FW\s*:\s*(.+)", "ST-LINK FW"),
        (r"Voltage\s*:\s*(.+)", "Voltage"),
        (r"Device\s+ID\s*:\s*(0x\S+)", "Device ID"),
        (r"Device\s+name\s*:\s*(.+)", "Device name"),
        (r"Flash\s+size\s*:\s*(.+)", "Flash size"),
        (r"Read Out Protection\s*:\s*(.+)", "RDP"),
    ]

    for pattern, label in patterns:
        match = re.search(pattern, output, re.IGNORECASE)
        if match:
            info.append(f"{label}: {match.group(1).strip()}")

    if info:
        return "\n".join(info)

    # Fallback: return trimmed output
    return output.strip()


async def stm32_flash(elf_path: str, reset: bool = True, verify: bool = True) -> str:
    """Flash firmware to STM32 board via ST-Link.

    Writes the specified .elf (or .bin/.hex) file to the connected STM32's
    flash memory using STM32_Programmer_CLI over SWD.

    Args:
        elf_path: Absolute path to the firmware file (.elf, .bin, or .hex).
        reset: If true, hard-reset the board after flashing.
        verify: If true, verify flash contents match the file.

    Returns:
        Flash result — ST-LINK info, download status, verify result.
    """
    loop = asyncio.get_event_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(_executor, lambda: _do_flash(elf_path, reset, verify)),
        timeout=FLASH_TIMEOUT + 10,
    )


async def stm32_board_info() -> str:
    """Read board information via ST-Link.

    Connects to the STM32 via SWD and reads device info: ST-LINK version,
    device ID/name, flash size, voltage, and read-out protection level.
    Useful for verifying the ST-Link connection before building/flashing.

    Returns:
        Board info — ST-LINK serial, firmware version, device ID, flash size, voltage, RDP level.
    """
    loop = asyncio.get_event_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(_executor, _do_board_info),
        timeout=INFO_TIMEOUT + 10,
    )
