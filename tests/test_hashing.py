"""C2 해시 — `canonical_json`과 패키지 `content_hash`.

이 규칙들은 **언어가 달라도 같은 값**이 나와야 서명이 성립한다. 그래서 표기까지 고정한다.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from chaeksas.contracts import (
    FloatInPayloadError,
    canonical_json,
    content_hash_dir,
    content_hash_from_files,
    content_hash_zip,
)
from chaeksas.contracts.hashing import sha256_hex


def test_canonical_json_sorts_keys_and_drops_spaces() -> None:
    assert canonical_json({"b": 1, "a": [1, 2]}) == b'{"a":[1,2],"b":1}'


def test_canonical_json_key_order_does_not_change_bytes() -> None:
    """같은 내용이면 어디서 만들어도 같은 바이트 — 서명이 성립하는 근거."""
    assert canonical_json({"a": 1, "b": {"c": 2, "d": 3}}) == canonical_json({"b": {"d": 3, "c": 2}, "a": 1})


def test_canonical_json_keeps_non_ascii_raw() -> None:
    """`ensure_ascii=false` — 한글이 `\\uXXXX`로 바뀌지 않는다."""
    assert canonical_json({"name": "세금계산서"}) == '{"name":"세금계산서"}'.encode()


def test_float_in_payload_is_refused() -> None:
    """`1.0`과 `1`의 표기가 언어마다 달라 서명이 깨진다 — 아예 막는다."""
    with pytest.raises(FloatInPayloadError) as e:
        canonical_json({"amount": 1.0})
    assert e.value.code == "float_in_payload"
    with pytest.raises(FloatInPayloadError, match=r"payload\.a\[1\]\.b"):
        canonical_json({"a": [0, {"b": 0.5}]})


def test_bool_is_allowed_and_not_confused_with_int() -> None:
    assert canonical_json({"ok": True, "n": 1}) == b'{"n":1,"ok":true}'


def test_unsupported_type_is_refused() -> None:
    with pytest.raises(ValueError, match="쓸 수 없는 타입"):
        canonical_json({"when": object()})


# ─────────────── content_hash ───────────────


def manifest_bytes(**over: object) -> bytes:
    data: dict[str, object] = {"schema": 1, "id": "a", "version": "1.0.0", "content_hash": "sha256:" + "00" * 32}
    return json.dumps(data | over, ensure_ascii=False).encode("utf-8")


def test_content_hash_shape() -> None:
    h = content_hash_from_files({"process/main.bpmn": b"<x/>"})
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 64


def test_content_hash_follows_the_documented_recipe() -> None:
    """경로 + NUL + sha256(내용) hex + 개선문자를 정렬 순으로 이어 붙인 뒤 전체를 해시한다."""
    files = {"b.txt": b"two", "a.txt": b"one"}
    expected = sha256_hex(
        f"a.txt\0{sha256_hex(b'one')}\n".encode() + f"b.txt\0{sha256_hex(b'two')}\n".encode()
    )
    assert content_hash_from_files(files) == f"sha256:{expected}"


def test_signature_file_is_excluded() -> None:
    """`SIGNATURE`를 넣어도 해시가 바뀌지 않는다 — Center가 내려줄 때 끼워 넣기 때문."""
    base = {"process/main.bpmn": b"<x/>"}
    assert content_hash_from_files(base) == content_hash_from_files({**base, "SIGNATURE": b'{"sig":"..."}'})


def test_manifest_content_hash_field_is_excluded() -> None:
    """`content_hash`에 결과를 적어 넣어야 하므로, 그 필드 자신은 해시 대상이 아니다."""
    a = content_hash_from_files({"manifest.json": manifest_bytes(content_hash="sha256:" + "11" * 32)})
    b = content_hash_from_files({"manifest.json": manifest_bytes(content_hash="sha256:" + "22" * 32)})
    assert a == b


def test_manifest_formatting_does_not_change_the_hash() -> None:
    """매니페스트는 canonical_json으로 바꿔 해시하니, 들여쓰기·키 순서가 달라도 같다."""
    one = json.dumps({"schema": 1, "id": "a"}, indent=4).encode("utf-8")
    two = json.dumps({"id": "a", "schema": 1}, separators=(",", ":")).encode("utf-8")
    assert content_hash_from_files({"manifest.json": one}) == content_hash_from_files({"manifest.json": two})


def test_other_files_are_hashed_byte_for_byte() -> None:
    """매니페스트가 아닌 파일은 원문 그대로 — BPMN의 공백 하나도 해시를 바꾼다."""
    assert content_hash_from_files({"p.bpmn": b"<x/>"}) != content_hash_from_files({"p.bpmn": b"<x />"})


def test_content_changes_the_hash() -> None:
    assert content_hash_from_files({"a": b"1"}) != content_hash_from_files({"a": b"2"})
    assert content_hash_from_files({"a": b"1"}) != content_hash_from_files({"b": b"1"})


def test_dir_and_zip_agree(tmp_path: Path) -> None:
    """Studio는 폴더에서, Center는 zip에서 계산한다 — 값이 같아야 한다."""
    root = tmp_path / "pkg"
    (root / "process").mkdir(parents=True)
    (root / "process" / "main.bpmn").write_bytes(b"<definitions/>")
    (root / "manifest.json").write_bytes(manifest_bytes())
    (root / "SIGNATURE").write_bytes(b"{}")

    zip_path = tmp_path / "pkg.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for p in sorted(root.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(root).as_posix())

    assert content_hash_dir(root) == content_hash_zip(zip_path)
