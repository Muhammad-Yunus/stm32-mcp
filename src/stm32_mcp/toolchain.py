"""Toolchain discovery — find CubeIDE, Programmer CLI, parse project files."""

import glob
import os
import xml.etree.ElementTree as ET
from pathlib import Path

# Cached paths (populated on first call)
_cubeide_path: str | None = None
_programmer_cli_path: str | None = None
_cubeide_searched = False
_programmer_cli_searched = False


def find_cubeide() -> str | None:
    """Find STM32CubeIDE executable. Caches result after first lookup."""
    global _cubeide_path, _cubeide_searched
    if _cubeide_searched:
        return _cubeide_path

    patterns = [
        # macOS
        "/Applications/STM32CubeIDE.app/Contents/MacOS/stm32cubeide",
        # Linux
        "/opt/st/stm32cubeide_*/stm32cubeide",
    ]
    for pattern in patterns:
        matches = glob.glob(pattern)
        if matches:
            _cubeide_path = sorted(matches)[-1]  # latest version
            break

    _cubeide_searched = True
    return _cubeide_path


def find_programmer_cli() -> str | None:
    """Find STM32_Programmer_CLI. Caches result after first lookup."""
    global _programmer_cli_path, _programmer_cli_searched
    if _programmer_cli_searched:
        return _programmer_cli_path

    patterns = [
        # Inside CubeIDE on macOS
        "/Applications/STM32CubeIDE.app/Contents/Eclipse/plugins/"
        "com.st.stm32cube.ide.mcu.externaltools.cubeprogrammer*"
        "/tools/bin/STM32_Programmer_CLI",
        # CubeCLT on macOS
        "/opt/ST/STM32CubeCLT*/STM32CubeProgrammer/bin/STM32_Programmer_CLI",
        # Linux inside CubeIDE
        "/opt/st/stm32cubeide_*/plugins/"
        "com.st.stm32cube.ide.mcu.externaltools.cubeprogrammer*"
        "/tools/bin/STM32_Programmer_CLI",
        # Linux standalone
        "/opt/ST/STM32CubeProgrammer/bin/STM32_Programmer_CLI",
    ]
    for pattern in patterns:
        matches = glob.glob(pattern)
        if matches:
            _programmer_cli_path = sorted(matches)[-1]
            break

    _programmer_cli_searched = True
    return _programmer_cli_path


def get_project_name(project_path: str) -> str:
    """Parse .project XML to extract the Eclipse project name."""
    project_file = os.path.join(project_path, ".project")
    if not os.path.isfile(project_file):
        raise FileNotFoundError(f"No .project file found at {project_path}")

    tree = ET.parse(project_file)
    name_elem = tree.find("name")
    if name_elem is None or not name_elem.text:
        raise ValueError(f"Could not find <name> element in {project_file}")
    return name_elem.text


def validate_project_path(project_path: str) -> str:
    """Check that .project and .cproject exist. Returns resolved absolute path."""
    resolved = str(Path(project_path).resolve())

    if not os.path.isdir(resolved):
        raise FileNotFoundError(f"Directory does not exist: {resolved}")

    project_file = os.path.join(resolved, ".project")
    cproject_file = os.path.join(resolved, ".cproject")

    if not os.path.isfile(project_file):
        raise FileNotFoundError(
            f"No .project found at {resolved}. Is this a CubeIDE project?"
        )
    if not os.path.isfile(cproject_file):
        raise FileNotFoundError(
            f"No .cproject found at {resolved}. Is this a CubeIDE project?"
        )

    return resolved
