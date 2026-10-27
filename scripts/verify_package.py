"""Offline archive inventory checks for release-engineering CI."""

from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path

FORBIDDEN = (".venv/", ".git/", "__pycache__/", ".pytest_cache/", ".ruff_cache/")
SUSPICIOUS_FILENAMES = (".env", "id_rsa", "id_ed25519", ".pem", ".key", "credentials")
SECRET_MARKERS = (b"-----BEGIN PRIVATE KEY-----", b"AKIA")
MAX_MEMBER_SIZE = 5 * 1024 * 1024
KNOWN_REDACTION_SOURCE = "zeroagent/blackbox/redaction.py"


def check_paths(names: list[str], label: str) -> None:
    unsafe = [
        name for name in names if name.startswith("/") or ".." in Path(name).parts
    ]
    unwanted = [
        name
        for name in names
        if name.endswith(".pyc") or any(x in name for x in FORBIDDEN)
    ]
    suspicious = [
        name
        for name in names
        if any(marker in name.casefold() for marker in SUSPICIOUS_FILENAMES)
    ]
    if unsafe or unwanted or suspicious:
        raise SystemExit(
            f"{label} contains unsafe paths: {unsafe + unwanted + suspicious}"
        )


def check_content(name: str, content: bytes, label: str) -> None:
    # This module contains literal redaction signatures used to detect secrets.
    if name == KNOWN_REDACTION_SOURCE:
        return
    if any(marker in content for marker in SECRET_MARKERS):
        raise SystemExit(f"{label} contains credential-like content: {name}")


def check_wheel(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        check_paths(names, "wheel")
        dist_infos = {
            name.split("/", 1)[0]
            for name in names
            if name.endswith(".dist-info/METADATA")
        }
        expected_dist_info = "zeroagent-0.12.0.dev0.dist-info"
        if dist_infos != {expected_dist_info}:
            raise SystemExit(
                f"wheel distribution metadata is invalid: {sorted(dist_infos)}"
            )
        for member in archive.infolist():
            if member.file_size > MAX_MEMBER_SIZE:
                raise SystemExit(f"wheel member exceeds size limit: {member.filename}")
            if not member.is_dir():
                check_content(member.filename, archive.read(member), "wheel")
        required = {
            "zeroagent/cli.py",
            "zeroagent/textual_app.py",
            "zeroagent/assets/logo.png",
            "zeroagent-0.12.0.dev0.dist-info/METADATA",
            "zeroagent-0.12.0.dev0.dist-info/entry_points.txt",
        }
        missing = required - set(names)
        if missing:
            raise SystemExit(f"wheel missing required members: {sorted(missing)}")
        entry_points = archive.read("zeroagent-0.12.0.dev0.dist-info/entry_points.txt")
        if b"zeroagent = zeroagent.cli:main" not in entry_points:
            raise SystemExit("wheel console entry point is invalid")


def check_sdist(sdist: Path) -> None:
    with tarfile.open(sdist, "r:gz") as archive:
        names = archive.getnames()
        check_paths(names, "sdist")
        for member in archive.getmembers():
            if member.size > MAX_MEMBER_SIZE:
                raise SystemExit(f"sdist member exceeds size limit: {member.name}")
            if member.isfile():
                fileobj = archive.extractfile(member)
                if fileobj is not None:
                    check_content(member.name, fileobj.read(), "sdist")
        required = (
            "pyproject.toml",
            "README.md",
            "LICENSE",
            "src/zeroagent/assets/logo.png",
        )
        missing = [
            item for item in required if not any(name.endswith(item) for name in names)
        ]
        if missing:
            raise SystemExit(f"sdist missing required members: {missing}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_package.py DIST_DIR")
    dist = Path(sys.argv[1])
    (wheel,) = dist.glob("zeroagent-*.whl")
    (sdist,) = dist.glob("zeroagent-*.tar.gz")
    check_wheel(wheel)
    check_sdist(sdist)
    print(f"verified {wheel.name} and {sdist.name}")


if __name__ == "__main__":
    main()
