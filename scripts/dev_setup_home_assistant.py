"""Install local Home Assistant dev integrations for HARO."""

from __future__ import annotations

import argparse
import shutil
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_COMPONENTS = ROOT / "config" / "custom_components"
HARO_SOURCE = ROOT / "custom_components" / "haro"
HAEO_SOURCE = ROOT.parent / "haeo" / "custom_components" / "haeo"
HACS_ZIP_URL = "https://github.com/hacs/integration/releases/latest/download/hacs.zip"


def replace_path(path: Path) -> None:
    """Remove an existing file, symlink, or directory."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def install_haro() -> None:
    """Symlink HARO so local code changes are reflected in Home Assistant."""
    target = CONFIG_COMPONENTS / "haro"
    replace_path(target)
    target.symlink_to(HARO_SOURCE, target_is_directory=True)


def install_haeo() -> None:
    """Copy HAEO from the sibling checkout."""
    if not HAEO_SOURCE.is_dir():
        msg = f"HAEO checkout not found at {HAEO_SOURCE}"
        raise SystemExit(msg)
    target = CONFIG_COMPONENTS / "haeo"
    replace_path(target)
    shutil.copytree(
        HAEO_SOURCE,
        target,
        ignore=shutil.ignore_patterns("__pycache__", "tests"),
    )


def install_hacs() -> None:
    """Download and extract HACS into the local Home Assistant config."""
    target = CONFIG_COMPONENTS / "hacs"
    replace_path(target)
    target.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(HACS_ZIP_URL, timeout=30) as response, zipfile.ZipFile(response) as archive:
        archive.extractall(target)


def main() -> None:
    """Install local dev integrations."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-hacs", action="store_true", help="Skip downloading HACS")
    args = parser.parse_args()

    CONFIG_COMPONENTS.mkdir(parents=True, exist_ok=True)
    install_haro()
    install_haeo()
    if not args.skip_hacs:
        install_hacs()

    print(f"Installed HARO and HAEO into {CONFIG_COMPONENTS}")
    if args.skip_hacs:
        print("Skipped HACS install")
    else:
        print("Installed HACS")


if __name__ == "__main__":
    main()
