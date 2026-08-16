"""Native Project Folder selection owned by the local backend."""

import asyncio
import sys
from typing import Protocol


class DirectoryPicker(Protocol):
    async def pick(self) -> str | None: ...


class MacOSDirectoryPicker:
    """Open the system folder picker without granting browser filesystem access."""

    async def pick(self) -> str | None:
        if sys.platform != "darwin":
            raise RuntimeError("Project Folder browsing requires macOS")
        process = await asyncio.create_subprocess_exec(
            "/usr/bin/osascript",
            "-e",
            'POSIX path of (choose folder with prompt "Choose the Project Folder")',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 1 and (
            b"User canceled" in stderr or b"(-128)" in stderr
        ):
            return None
        if process.returncode != 0:
            raise RuntimeError("Could not open the Project Folder picker")
        selected = stdout.decode("utf-8").strip()
        return selected or None
