"""Synthetic safety checks for package archive inspection."""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts.verify_package import check_paths, check_sdist, check_wheel, main

SYNTHETIC_ACCESS_KEY_MARKER = b"AK" + b"IAEXAMPLE"


def make_wheel(
    path: Path, members: dict[str, bytes] | None = None, remove: str | None = None
) -> None:
    contents = {
        "zeroagent/cli.py": b"",
        "zeroagent/textual_app.py": b"",
        "zeroagent/assets/logo.png": b"PNG",
        "zeroagent-0.12.0b1.dist-info/METADATA": b"Name: zeroagent\n",
        "zeroagent-0.12.0b1.dist-info/entry_points.txt": (
            b"zeroagent = zeroagent.cli:main\n"
        ),
    }
    if members:
        contents.update(members)
    if remove:
        del contents[remove]
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in contents.items():
            archive.writestr(name, content)


def make_sdist(path: Path, members: dict[str, bytes] | None = None) -> None:
    contents = {
        "zeroagent-0.12.0b1/pyproject.toml": b"",
        "zeroagent-0.12.0b1/README.md": b"",
        "zeroagent-0.12.0b1/LICENSE": b"",
        "zeroagent-0.12.0b1/src/zeroagent/assets/logo.png": b"PNG",
    }
    if members:
        contents.update(members)
    with tarfile.open(path, "w:gz") as archive:
        for name, content in contents.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))


def test_check_paths_rejects_unsafe_and_sensitive_names() -> None:
    for member in ("../secret", "/absolute", ".venv/x", ".git/config", "x.pyc", ".env"):
        with pytest.raises(SystemExit):
            check_paths([member], "fixture")


def test_wheel_rejects_credential_like_content(tmp_path: Path) -> None:
    wheel = tmp_path / "fixture.whl"
    make_wheel(wheel, {"safe.txt": SYNTHETIC_ACCESS_KEY_MARKER})
    with pytest.raises(SystemExit, match="credential-like"):
        check_wheel(wheel)


def test_wheel_scans_python_source_except_known_redaction_module(
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "fixture.whl"
    make_wheel(wheel, {"zeroagent/other.py": SYNTHETIC_ACCESS_KEY_MARKER})
    with pytest.raises(SystemExit, match="credential-like"):
        check_wheel(wheel)
    make_wheel(wheel, {"zeroagent/blackbox/redaction.py": SYNTHETIC_ACCESS_KEY_MARKER})
    check_wheel(wheel)


def test_sdist_scans_source_except_exact_prefixed_redaction_module(
    tmp_path: Path,
) -> None:
    sdist = tmp_path / "fixture.tar.gz"
    make_sdist(
        sdist,
        {"zeroagent-0.12.0b1/src/zeroagent/other.py": SYNTHETIC_ACCESS_KEY_MARKER},
    )
    with pytest.raises(SystemExit, match="credential-like"):
        check_sdist(sdist)


def test_sdist_rejects_unrecognized_or_multiple_archive_roots(tmp_path: Path) -> None:
    sdist = tmp_path / "fixture.tar.gz"
    make_sdist(sdist, {"other/src/zeroagent/blackbox/redaction.py": b""})
    with pytest.raises(SystemExit, match="archive root"):
        check_sdist(sdist)
    make_sdist(sdist, {"other/file.txt": b""})
    with pytest.raises(SystemExit, match="archive root"):
        check_sdist(sdist)
    make_sdist(
        sdist,
        {
            "zeroagent-0.12.0b1/src/zeroagent/blackbox/redaction.py": (
                SYNTHETIC_ACCESS_KEY_MARKER
            )
        },
    )
    check_sdist(sdist)
    make_sdist(
        sdist,
        {
            "zeroagent-0.12.0b1/src/zeroagent/blackbox/not-redaction.py": (
                SYNTHETIC_ACCESS_KEY_MARKER
            )
        },
    )
    with pytest.raises(SystemExit, match="credential-like"):
        check_sdist(sdist)


def test_sdist_rejects_oversized_member(tmp_path: Path) -> None:
    sdist = tmp_path / "fixture.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        info = tarfile.TarInfo("zeroagent-0.12.0b1/large.txt")
        info.size = 5 * 1024 * 1024 + 1
        archive.addfile(info, io.BytesIO(b"x" * info.size))
    with pytest.raises(SystemExit, match="size limit"):
        check_sdist(sdist)


def test_corrupt_archives_fail_safely(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.whl"
    corrupt.write_bytes(b"not an archive")
    with pytest.raises(zipfile.BadZipFile):
        check_wheel(corrupt)


def test_valid_synthetic_archives_pass(tmp_path: Path) -> None:
    wheel = tmp_path / "valid.whl"
    sdist = tmp_path / "valid.tar.gz"
    make_wheel(wheel)
    make_sdist(sdist)
    check_wheel(wheel)
    check_sdist(sdist)


@pytest.mark.parametrize(
    "member",
    [
        "zeroagent/.git/config",
        "zeroagent/cache.pyc",
        "../secret",
        "zeroagent/.env",
    ],
)
def test_wheel_rejects_forbidden_member(tmp_path: Path, member: str) -> None:
    wheel = tmp_path / "fixture.whl"
    make_wheel(wheel, {member: b"x"})
    with pytest.raises(SystemExit):
        check_wheel(wheel)


@pytest.mark.parametrize(
    "missing",
    [
        "zeroagent/cli.py",
        "zeroagent/assets/logo.png",
        "zeroagent-0.12.0b1.dist-info/entry_points.txt",
    ],
)
def test_wheel_rejects_missing_required_member(tmp_path: Path, missing: str) -> None:
    wheel = tmp_path / "fixture.whl"
    make_wheel(wheel, remove=missing)
    with pytest.raises(SystemExit, match="missing|required|entry point"):
        check_wheel(wheel)


def test_wheel_rejects_incorrect_distribution_version(tmp_path: Path) -> None:
    wheel = tmp_path / "fixture.whl"
    make_wheel(wheel)
    with zipfile.ZipFile(wheel) as archive:
        members = {
            name.replace("0.12.0b1", "9.9.9"): archive.read(name)
            for name in archive.namelist()
        }
    make_wheel(wheel, members)
    with pytest.raises(SystemExit, match="metadata is invalid"):
        check_wheel(wheel)


def test_script_entry_point_accepts_valid_distribution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_wheel(tmp_path / "zeroagent-0.12.0b1-py3-none-any.whl")
    make_sdist(tmp_path / "zeroagent-0.12.0b1.tar.gz")
    monkeypatch.setattr("sys.argv", ["verify_package.py", str(tmp_path)])
    main()
