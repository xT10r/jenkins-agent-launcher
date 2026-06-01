#!/usr/bin/env python3
"""Запускает PyInstaller без cmd-склейки аргументов."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 5:
        print("Usage: _run_pyinstaller.py <build-vars.json> <project-dir> <build-dir> <src>")
        return 1

    vars_json = Path(sys.argv[1]).resolve()
    project_dir = Path(sys.argv[2]).resolve()
    build_dir = Path(sys.argv[3]).resolve()
    src = Path(sys.argv[4]).resolve()

    cfg = json.loads(vars_json.read_text(encoding="utf-8"))

    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--clean",
        "--name",
        cfg.get("exeName") or "jenkins-agent",
        "--distpath",
        str(project_dir),
        "--workpath",
        str(build_dir),
        "--specpath",
        str(build_dir),
        "--hidden-import=cryptography",
        "--hidden-import=PyQt5",
        f"--paths={project_dir}",
    ]

    version_script = cfg.get("versionScript") or ""
    if version_script:
        args.extend(["--version-file", version_script])

    icon = cfg.get("icon") or ""
    if icon:
        args.extend(["--icon", icon])
        args.extend(["--add-data", f"{icon};assets"])

    if cfg.get("noConsole", True):
        args.append("--windowed")

    args.append(str(src))
    return subprocess.run(args, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
