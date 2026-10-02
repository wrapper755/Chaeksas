"""C2. 해시 — `canonical_json`과 패키지 `content_hash`.

단일 원본: `docs/03-contracts/C2-signing-envelope.md`.

두 규칙 모두 **언어가 달라도 같은 값이 나와야** 한다. 그래서 표기가 흔들리는 것을 금지한다.

- `canonical_json`: 키 정렬, 구분자 `,`·`:`(공백 없음), UTF-8, `ensure_ascii=false`.
- 서명 대상에 **실수(float)를 쓰지 않는다.** `1.0`과 `1`의 표기가 언어마다 달라 서명이 깨진다.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

#: 패키지 해시에서 빼는 파일 (서명 자체는 해시 대상이 아니다).
SIGNATURE_NAME = "SIGNATURE"
MANIFEST_NAME = "manifest.json"


class FloatInPayloadError(ValueError):
    """서명 대상에 실수가 들어왔다. 422 `float_in_payload`."""

    code = "float_in_payload"


def _check_signable(x: Any, where: str = "payload") -> None:
    """서명 대상에 쓸 수 있는 값인지. 문자열·정수·불리언·null·배열·객체만."""
    if x is None or isinstance(x, (str, bool, int)):  # bool이 int보다 먼저여야 한다
        return
    if isinstance(x, float):
        raise FloatInPayloadError(f"{where}에 실수가 있다: {x!r} (정수나 문자열로 바꾼다)")
    if isinstance(x, Mapping):
        for k, v in x.items():
            if not isinstance(k, str):
                raise ValueError(f"{where}의 키가 문자열이 아니다: {k!r}")
            _check_signable(v, f"{where}.{k}")
        return
    if isinstance(x, (list, tuple)):
        for i, v in enumerate(x):
            _check_signable(v, f"{where}[{i}]")
        return
    raise ValueError(f"{where}에 쓸 수 없는 타입이다: {type(x).__name__}")


def canonical_json(x: Any) -> bytes:
    """서명·해시 대상의 표준 표기 (UTF-8 바이트).

    키를 정렬하고 공백을 없애므로, 같은 내용이면 어디서 만들어도 같은 바이트가 나온다.
    실수가 들어 있으면 `FloatInPayloadError`.
    """
    _check_signable(x)
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest_bytes_for_hash(raw: bytes) -> bytes:
    """`manifest.json`은 `content_hash` 필드를 뺀 뒤 `canonical_json`으로 바꿔 해시한다.

    (그 필드에 해시 결과를 적어 넣어야 하므로, 자기 자신을 해시 대상에서 빼야 한다.)
    """
    data = json.loads(raw.decode("utf-8"))
    if isinstance(data, dict):
        data.pop("content_hash", None)
    return canonical_json(data)


def content_hash_from_files(files: Mapping[str, bytes]) -> str:
    """패키지 안 파일들 → `sha256:<hex>`.

    규칙: 상대 경로(`/` 구분) 정렬 순으로, 파일마다 `경로` + `\\0` + `sha256(내용) hex` + `\\n`을
    이어 붙이고 전체를 SHA-256한다. `SIGNATURE`는 빼고, `manifest.json`은 위 규칙으로 바꿔 해시한다.
    """
    lines = []
    for path in sorted(files):
        if path == SIGNATURE_NAME:
            continue
        raw = files[path]
        if path == MANIFEST_NAME:
            raw = _manifest_bytes_for_hash(raw)
        lines.append(f"{path}\0{sha256_hex(raw)}\n".encode())
    return "sha256:" + sha256_hex(b"".join(lines))


def content_hash_dir(root: Path) -> str:
    """풀어 놓은 패키지 폴더의 `content_hash` (Studio가 빌드할 때)."""
    files = {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and not p.is_symlink()
    }
    return content_hash_from_files(files)


def content_hash_zip(zip_path: Path) -> str:
    """패키지 zip의 `content_hash` (Center가 업로드를 검사할 때)."""
    with zipfile.ZipFile(zip_path) as zf:
        files = {
            info.filename: zf.read(info)
            for info in sorted(zf.infolist(), key=lambda i: i.filename)
            if not info.is_dir()
        }
    return content_hash_from_files(files)
