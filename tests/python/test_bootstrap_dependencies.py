from __future__ import annotations

import hashlib
import io
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock
import zipfile

from tools import bootstrap_dependencies


class FakeResponse:
    def __init__(
        self,
        chunks: list[bytes | BaseException],
        status: int,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.chunks = iter(chunks)
        self.status = status
        self.headers = headers or {}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_arguments: object) -> None:
        return None

    def getcode(self) -> int:
        return self.status

    def read(self, _size: int) -> bytes:
        try:
            value = next(self.chunks)
        except StopIteration:
            return b""
        if isinstance(value, BaseException):
            raise value
        return value


def archive_bytes() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        member = zipfile.ZipInfo("include/value.txt")
        member.create_system = 3
        member.external_attr = (stat.S_IFREG | 0o644) << 16
        archive.writestr(member, "locked dependency")
    return output.getvalue()


def locked(data: bytes) -> dict[str, object]:
    return {
        "filename": "dependency.zip",
        "source": "https://dependencies.invalid/dependency.zip",
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


class BootstrapDependenciesTest(unittest.TestCase):
    def test_download_resumes_after_a_read_timeout(self) -> None:
        data = archive_bytes()
        split = len(data) // 2
        responses = [
            FakeResponse([data[:split], TimeoutError("stalled")], 200),
            FakeResponse(
                [data[split:]],
                206,
                {"Content-Range": f"bytes {split}-{len(data) - 1}/{len(data)}"},
            ),
        ]
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            bootstrap_dependencies.urllib.request,
            "urlopen",
            side_effect=responses,
        ) as urlopen, mock.patch.object(bootstrap_dependencies.time, "sleep"):
            destination = Path(directory) / "dependency.zip"
            bootstrap_dependencies.download(locked(data), destination)
            self.assertEqual(destination.read_bytes(), data)
            resumed_request = urlopen.call_args_list[1].args[0]
            self.assertEqual(resumed_request.get_header("Range"), f"bytes={split}-")

    def test_download_restarts_when_server_ignores_range(self) -> None:
        data = archive_bytes()
        split = len(data) // 2
        responses = [
            FakeResponse([data[:split], TimeoutError("stalled")], 200),
            FakeResponse([data], 200),
        ]
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            bootstrap_dependencies.urllib.request,
            "urlopen",
            side_effect=responses,
        ), mock.patch.object(bootstrap_dependencies.time, "sleep"):
            destination = Path(directory) / "dependency.zip"
            bootstrap_dependencies.download(locked(data), destination)
            self.assertEqual(destination.read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
