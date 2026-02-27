"""Build tools — CubeIDE headless build, ELF discovery, output filtering."""

import asyncio
import glob
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

from .toolchain import find_cubeide, get_project_name, validate_project_path

_executor = ThreadPoolExecutor(max_workers=2)

# Track which projects have been imported to skip -import on subsequent builds
_imported_projects: dict[str, bool] = {}

WORKSPACE_PATH = "/tmp/stm32-mcp-workspace"
WORKSPACE_LOCK = os.path.join(WORKSPACE_PATH, ".metadata", ".lock")

BUILD_TIMEOUT = 180  # seconds


def _check_and_clear_workspace_lock() -> str | None:
    """Check workspace lock. Clear if stale. Returns error message or None.

    Our temp workspace (/tmp/stm32-mcp-workspace) is never used by CubeIDE GUI,
    so we only need to check if another MCP headless build is using it — not
    whether CubeIDE is running in general (it uses its own workspace).
    """
    if not os.path.isfile(WORKSPACE_LOCK):
        return None

    # Check if another headless build is using OUR temp workspace specifically
    try:
        result = subprocess.run(
            ["pgrep", "-f", f"stm32-mcp-workspace"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return (
                "Another MCP headless build is already running. "
                "Wait for it to finish."
            )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # No process using our workspace — stale lock, remove it
    try:
        os.remove(WORKSPACE_LOCK)
    except OSError:
        pass
    return None


# Build output filter patterns
_KEEP_PATTERNS = [
    re.compile(r"arm-none-eabi"),
    re.compile(r":\d+:\d+:\s*(error|warning|note):"),
    re.compile(r"^make\["),
    re.compile(r"\.elf\b"),
    re.compile(r"^\s*(text|data|bss)\s"),
    re.compile(r"^\s*\d+\s+\d+\s+\d+"),  # size table data rows
    re.compile(r"Build Finished", re.IGNORECASE),
    re.compile(r"Build Failed", re.IGNORECASE),
    re.compile(r"undefined reference"),
    re.compile(r"ld returned"),
    re.compile(r"multiple definition"),
    re.compile(r"cannot find -l"),
    re.compile(r"recipe for target .* failed"),
]


def _filter_build_output(raw: str) -> str:
    """Strip JVM/Eclipse noise from build output. Keep compiler lines."""
    lines = raw.splitlines()

    # Find the first line that looks like actual build output
    start_idx = 0
    for i, line in enumerate(lines):
        if "arm-none-eabi" in line or re.search(r":\d+:\d+:\s*(error|warning):", line):
            start_idx = i
            break

    # Filter from that point
    kept = []
    for line in lines[start_idx:]:
        for pattern in _KEEP_PATTERNS:
            if pattern.search(line):
                kept.append(line)
                break

    if kept:
        return "\n".join(kept)

    # Fallback: last 30 lines if nothing passed filter
    return "\n".join(lines[-30:]) if lines else raw


def _find_elf(project_path: str, config: str, build_output: str) -> str | None:
    """Find the .elf file — glob by mtime, fallback to parsing build output."""
    # Glob for .elf files in the build config directory
    elf_pattern = os.path.join(project_path, config, "*.elf")
    elfs = glob.glob(elf_pattern)
    if elfs:
        # Pick newest by mtime
        return max(elfs, key=os.path.getmtime)

    # Fallback: scan build output for .elf references
    matches = re.findall(r'[\w./-]+\.elf\b', build_output)
    for match in matches:
        # Try as absolute path
        if os.path.isfile(match):
            return match
        # Try relative to project
        candidate = os.path.join(project_path, match)
        if os.path.isfile(candidate):
            return candidate

    return None


def _do_build(
    project_path: str,
    configuration: str = "Debug",
    clean: bool = False,
    _retry: bool = False,
) -> dict:
    """Synchronous build — runs in executor thread."""
    # Find CubeIDE
    cubeide = find_cubeide()
    if not cubeide:
        return {"success": False, "output": "STM32CubeIDE not found. Install it or check the path."}

    # Validate project
    try:
        project_path = validate_project_path(project_path)
        project_name = get_project_name(project_path)
    except (FileNotFoundError, ValueError) as e:
        return {"success": False, "output": str(e)}

    # Check workspace lock
    lock_err = _check_and_clear_workspace_lock()
    if lock_err:
        return {"success": False, "output": lock_err}

    # Build the command
    build_target = f"{project_name}/{configuration}"
    build_flag = "-cleanBuild" if clean else "-build"

    cmd = [
        cubeide,
        "--launcher.suppressErrors",
        "-nosplash",
        "-application", "org.eclipse.cdt.managedbuilder.core.headlessbuild",
        "-data", WORKSPACE_PATH,
    ]

    # Import only if not previously imported (or on retry)
    cache_key = project_path
    if cache_key not in _imported_projects or _retry:
        cmd.extend(["-import", project_path])

    cmd.extend([build_flag, build_target])

    # Run build
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=BUILD_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "output": f"Build timed out after {BUILD_TIMEOUT}s."}

    raw_output = result.stdout + "\n" + result.stderr
    filtered = _filter_build_output(raw_output)

    # Detect success
    has_build_finished = bool(re.search(r"Build Finished", raw_output, re.IGNORECASE))
    has_errors = bool(re.search(r":\d+:\d+:\s*error:", raw_output))
    has_build_failed = bool(re.search(r"Build Failed", raw_output, re.IGNORECASE))
    success = has_build_finished and not has_errors and not has_build_failed

    # If build failed because project not found, retry with -import
    if not success and not _retry:
        not_found = (
            "not found in workspace" in raw_output.lower()
            or "could not find" in raw_output.lower()
        )
        if not_found:
            _imported_projects.pop(cache_key, None)
            return _do_build(project_path, configuration, clean, _retry=True)

    # Mark as imported on success
    if success:
        _imported_projects[cache_key] = True

    # Find ELF
    elf_path = None
    if success:
        elf_path = _find_elf(project_path, configuration, raw_output)

    return {
        "success": success,
        "output": filtered,
        "elf_path": elf_path,
        "project_path": project_path,
        "configuration": configuration,
    }


async def stm32_build(
    project_path: str,
    configuration: str = "Debug",
    clean: bool = False,
) -> str:
    """Build STM32 firmware using CubeIDE headless builder.

    Compiles the project at project_path using the specified build configuration.
    CubeIDE headless mode automatically detects new/deleted source files — no
    Makefile maintenance needed.

    Args:
        project_path: Absolute path to the CubeIDE project root (must contain .project and .cproject).
        configuration: Build configuration — "Debug" or "Release".
        clean: If true, clean before building (slower but ensures full rebuild).

    Returns:
        Build result with filtered compiler output, errors/warnings, ELF size,
        and the path to the built .elf file on success.
    """
    loop = asyncio.get_event_loop()
    result = await asyncio.wait_for(
        loop.run_in_executor(
            _executor,
            lambda: _do_build(project_path, configuration, clean),
        ),
        timeout=BUILD_TIMEOUT + 10,
    )

    # Format output
    parts = []
    if result["success"]:
        parts.append("BUILD SUCCESSFUL")
        if result.get("elf_path"):
            parts.append(f"ELF: {result['elf_path']}")
    else:
        parts.append("BUILD FAILED")

    parts.append("")
    parts.append(result["output"])

    return "\n".join(parts)


async def stm32_build_and_flash(
    project_path: str,
    configuration: str = "Debug",
    clean: bool = False,
    reset: bool = True,
    verify: bool = True,
) -> str:
    """Build firmware and flash it to the board in one step.

    Compiles the project, then flashes the resulting .elf to the connected
    STM32 via ST-Link. This is the most common workflow — use this instead
    of calling stm32_build and stm32_flash separately.

    Args:
        project_path: Absolute path to the CubeIDE project root.
        configuration: Build configuration — "Debug" or "Release".
        clean: If true, clean before building.
        reset: If true, reset the board after flashing.
        verify: If true, verify flash contents after writing.

    Returns:
        Combined build and flash results.
    """
    # Import here to avoid circular import
    from .flash import stm32_flash

    # Build first
    loop = asyncio.get_event_loop()
    build_result = await asyncio.wait_for(
        loop.run_in_executor(
            _executor,
            lambda: _do_build(project_path, configuration, clean),
        ),
        timeout=BUILD_TIMEOUT + 10,
    )

    parts = []
    if not build_result["success"]:
        parts.append("BUILD FAILED — skipping flash.")
        parts.append("")
        parts.append(build_result["output"])
        return "\n".join(parts)

    parts.append("BUILD SUCCESSFUL")
    if build_result.get("elf_path"):
        parts.append(f"ELF: {build_result['elf_path']}")
    parts.append("")
    parts.append(build_result["output"])

    # Flash
    elf_path = build_result.get("elf_path")
    if not elf_path:
        parts.append("")
        parts.append("ERROR: Build succeeded but no .elf file found. Cannot flash.")
        return "\n".join(parts)

    parts.append("")
    parts.append("--- FLASHING ---")
    flash_output = await stm32_flash(elf_path, reset=reset, verify=verify)
    parts.append(flash_output)

    return "\n".join(parts)
