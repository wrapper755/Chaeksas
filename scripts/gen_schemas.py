"""계약 모델 → JSON Schema 생성 (`docs/03-contracts/README.md` 원칙 5).

실행: `uv run python scripts/gen_schemas.py`
`--check`: 파일을 쓰지 않고 검사만 하며, 생성물이 모델과 다르면 1로 끝난다 (CI용).

다른 언어 도구(웹 화면의 `api-types` 등)가 같은 명세를 쓰도록 내보낸다.
브라우저 쪽 타입은 이 스키마에서 생성한다 (ADR-0017).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from chaeksas.contracts import (
    EventBatchResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    Manifest,
    RegisterRequest,
    RegisterResponse,
    RunEvent,
)

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "packages" / "contracts" / "schemas"

# (파일 이름, 모델) — 이름 앞에 계약 번호를 붙여 문서에서 찾기 쉽게 한다.
MODELS: list[tuple[str, Any]] = [
    ("c1-manifest", Manifest),
    ("c3-run-event", RunEvent),
    ("c3-event-batch-response", EventBatchResponse),
    ("c4-register-request", RegisterRequest),
    ("c4-register-response", RegisterResponse),
    ("c4-heartbeat-request", HeartbeatRequest),
    ("c4-heartbeat-response", HeartbeatResponse),
]


def outputs() -> dict[Path, str]:
    out: dict[Path, str] = {}
    for name, model in MODELS:
        schema = model.model_json_schema(by_alias=True)
        schema["$id"] = f"urn:chaeksas:contracts:{name}"
        text = json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True)
        out[OUT_DIR / f"{name}.json"] = text + "\n"
    return out


def main() -> int:
    check = "--check" in sys.argv
    out = outputs()
    existing = {p for p in OUT_DIR.glob("*.json")} if OUT_DIR.exists() else set()
    orphans = sorted(existing - set(out))

    if check:
        stale = [p for p, t in out.items() if not p.exists() or p.read_text(encoding="utf-8") != t]
        for p in [*stale, *orphans]:
            print("다름:", p.relative_to(ROOT))
        return 1 if (stale or orphans) else 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for p in orphans:
        p.unlink()
        print("지움:", p.relative_to(ROOT))
    for p, text in out.items():
        p.write_text(text, encoding="utf-8", newline="\n")
    print(f"스키마 {len(out)}개 → {OUT_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
