#!/usr/bin/env python3
"""Fetch or verify the exact native dependency archives in deps.lock.json."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import stat
import tarfile
import time
import urllib.error
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "models" / "deps.lock.json"
DOWNLOAD_ATTEMPTS = 4
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 60


def safe_member_name(raw: str) -> str:
    name = raw.replace("\\", "/")
    path = PurePosixPath(name)
    if (not name or "\0" in name or name.startswith("/") or path.is_absolute()
            or ".." in path.parts or (path.parts and path.parts[0].endswith(":"))):
        raise RuntimeError(f"unsafe archive member path: {raw!r}")
    return path.as_posix().rstrip("/")


def inspect_archive(path: Path) -> None:
    seen: set[str] = set()
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                name = safe_member_name(member.filename)
                if not name or name in seen:
                    raise RuntimeError(f"empty or duplicate archive member: {member.filename!r}")
                seen.add(name)
                mode = member.external_attr >> 16
                if mode and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                    raise RuntimeError(f"unsupported archive member: {member.filename}")
        return
    try:
        with tarfile.open(path, "r:*") as archive:
            for member in archive.getmembers():
                name = safe_member_name(member.name)
                if not name or name in seen:
                    raise RuntimeError(f"empty or duplicate archive member: {member.name!r}")
                seen.add(name)
                if member.issym() or member.islnk() or member.isdev() or not (
                    member.isfile() or member.isdir()
                ):
                    raise RuntimeError(f"unsupported archive member: {member.name}")
    except tarfile.TarError as exception:
        raise RuntimeError(f"unsupported dependency archive: {path.name}") from exception


def verify(path: Path, record: dict[str, object]) -> None:
    data = path.read_bytes()
    if len(data) != int(record["bytes"]):
        raise RuntimeError(f"{path.name}: byte count mismatch")
    if hashlib.sha256(data).hexdigest() != record["sha256"]:
        raise RuntimeError(f"{path.name}: SHA-256 mismatch")
    inspect_archive(path)


def download(record: dict[str, object], destination: Path) -> None:
    expected_bytes = int(record["bytes"])
    partial = destination.with_suffix(destination.suffix + ".part")
    last_error: BaseException | None = None
    for attempt in range(DOWNLOAD_ATTEMPTS):
        offset = partial.stat().st_size if partial.exists() else 0
        if offset > expected_bytes:
            partial.unlink()
            offset = 0
        if offset == expected_bytes:
            verify(partial, record)
            os.replace(partial, destination)
            return
        headers = {"User-Agent": "light-ocr-bootstrap/1"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = urllib.request.Request(str(record["source"]), headers=headers)
        try:
            with urllib.request.urlopen(
                request, timeout=DOWNLOAD_TIMEOUT_SECONDS
            ) as response:
                status = response.getcode()
                content_range = response.headers.get("Content-Range", "")
                append = bool(
                    offset
                    and status == 206
                    and content_range.startswith(f"bytes {offset}-")
                )
                if offset and status == 206 and not append:
                    partial.unlink(missing_ok=True)
                    raise urllib.error.URLError(
                        f"invalid resume response: {content_range!r}"
                    )
                mode = "ab" if append else "wb"
                with partial.open(mode) as stream:
                    while True:
                        chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                        if not chunk:
                            break
                        stream.write(chunk)
                        if stream.tell() > expected_bytes:
                            raise RuntimeError(
                                f"{destination.name}: download exceeds locked byte count"
                            )
            if partial.stat().st_size == expected_bytes:
                verify(partial, record)
                os.replace(partial, destination)
                return
            last_error = RuntimeError(
                f"incomplete response ({partial.stat().st_size}/{expected_bytes} bytes)"
            )
        except (
            TimeoutError,
            ConnectionError,
            http.client.HTTPException,
            urllib.error.URLError,
        ) as exception:
            last_error = exception
        if attempt + 1 < DOWNLOAD_ATTEMPTS:
            time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(
        f"{destination.name}: dependency download failed after "
        f"{DOWNLOAD_ATTEMPTS} attempts: {last_error}"
    ) from last_error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, default=ROOT / ".cache" / "dependencies")
    parser.add_argument("--offline", action="store_true", help="verify only; never download")
    arguments = parser.parse_args()
    arguments.cache_dir.mkdir(parents=True, exist_ok=True)
    lock = json.loads(LOCK.read_text("utf-8"))
    for record in lock["dependencies"]:
        destination = arguments.cache_dir / record["filename"]
        if destination.exists():
            verify(destination, record)
            continue
        if arguments.offline:
            raise RuntimeError(f"offline dependency archive is missing: {destination}")
        download(record, destination)
    print(arguments.cache_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
