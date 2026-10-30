"""묶은 실행 파일이 **제 확장을 다 들고 있나** — 빌드 검사 (ADR-0024).

설치 파일로 묶으면 확장이 **조용히 사라질 수 있다** — 셋 중 하나만 빠져도 증상이 다르다
(ADR-0024, 스파이크 S5):

| 빠진 것 | 증상 |
| --- | --- |
| dist-info 메타데이터 | 엔트리 포인트가 **빈 목록** — 확장이 아예 없는 것처럼 된다 |
| 데이터 파일 | `extension.json`을 읽을 수 없다 (호스트가 사유를 남기고 끈다) |
| 서브모듈 | 확장은 켜지는데 **`entry` 해석에서** 터진다 (실행 중에야 안다) |

셋 다 **실행 중에야** 드러나므로 빌드가 묶은 실행 파일을 `--selftest`로 한 번 돌려 본다.
**인스턴스를 만들지 않고 `entry`를 풀기만 한다** (`extension_api.entry.resolve`) — 그 셋을
가리는 데는 import와 속성 찾기까지면 충분하고, Qt 위젯을 만들려면 화면 없는 환경에서도
`QApplication`이 필요해 빌드 검사가 무거워진다.

**쓰는 쪽은 둘이다** (PC 실행기·Studio의 `--selftest`) — 한 자리에 두어 둘이 같은 것을 본다.
깃발을 읽는 것도 여기다(`main`) — 두 앱이 깃발을 따로 늘리면 빌드가 한쪽에만 넘긴다.

**찍힌 판도 함께 싣는다** ([ADR-0067](../../../../../docs/decisions/0067-build-stamp.md)) — 빌드가
`--expect-version`으로 넘기면 묶은 앱이 **읽은** 판이 그것과 같아야 한다. 파일이 안 들어갔거나 앱이
다른 자리를 읽으면 현장에서 `0.0.0`을 보고서야 안다.

**런타임을 정말 띄워 보는 단계는 앱이 준다** (`--start-runtimes`) — 띄우는 길은 PC 실행기의 것이라
(`core`는 PC 실행기를 모른다) `main(start_runtimes=…)`로 받는다. 그 앱이 주지 않았는데 깃발이 오면
**실패로 적는다**(빌드가 「봤다」고 믿으면 안 된다).
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from chaeksas.contracts.extension import PANEL_SURFACES
from chaeksas.core import build_info
from chaeksas.core.extensions import ExtensionHost, load_host, summarize
from chaeksas.extension_api.entry import module_root, resolve

#: 빌드 검사 깃발 — **PC 실행기·Studio가 같은 이름을 쓴다** (ADR-0024). 빌드가 이것으로 부른다.
SELFTEST_FLAG = "--selftest"


def _entries(host: ExtensionHost) -> list[tuple[str, str, str]]:
    """풀어 봐야 하는 기여들 — `(확장 id, 무엇, entry)`.

    **선언이 있는 것만** 본다 (`editor`·`executor`는 선택 칸이다). 자리를 늘리면 여기 한 줄을
    더한다 — 빌드 검사가 그 자리를 보지 않으면 그 기여는 **현장에서** 터진다.
    """
    found: list[tuple[str, str, str]] = []
    for task in host.task_types():
        if task.value.executor is not None:
            found.append((task.extension_id, f"task_types[{task.value.id}].executor", task.value.executor.entry))
        if task.value.editor is not None and task.value.editor.entry:
            found.append((task.extension_id, f"task_types[{task.value.id}].editor", task.value.editor.entry))
    for editor in host.studio_editors():
        found.append((editor.extension_id, f"studio.editors[{editor.value.task_type}]", editor.value.entry))
    for env in host.agent_environments():
        found.append((env.extension_id, f"agent_environments[{env.value.domain}]", env.value.entry))
    for tool in host.tools():
        found.append((tool.extension_id, f"tool_ui.tools[{tool.value.id}]", tool.value.entry))
    for runtime in host.local_runtimes():
        found.append((runtime.extension_id, f"bot_ui.local_runtimes[{runtime.value.id}]", runtime.value.entry))
    for one in host.preflight():
        found.append((one.extension_id, f"preflight[{one.value.id}]", one.value.entry))
    # **자리 이름을 베끼지 않는다** — 계약이 쥔 목록을 돈다 (늘면 여기도 함께 본다).
    for surface in sorted(PANEL_SURFACES):
        for panel in host.panels(surface):
            found.append((panel.extension_id, f"bot_ui.panels[{panel.value.id}]", panel.value.entry))
    return found


def check(
    *,
    want: list[str] | None = None,
    host: ExtensionHost | None = None,
    expect_version: str | None = None,
    stamp: build_info.Stamp | None = None,
    extra: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """묶은 앱에서 확장이 다 보이나. `{"all_ok": bool, "steps": {...}}`.

    `want`를 주면 **그 확장들이 켜져 있어야** 한다 — 빌드하는 쪽이 「무엇이 들어가야 하는가」를
    안다 (ADR-0018 §5 포함 목록). 주지 않으면 **하나라도 켜져 있으면** 된다: 묶인 앱에
    엔트리 포인트가 하나도 없는 것이 가장 흔한 실패다.
    """
    found = host if host is not None else load_host()
    enabled = [one.id for one in found.enabled()]
    steps: dict[str, Any] = {
        "entry_points": {
            "ok": bool(enabled) if want is None else set(want) <= set(enabled),
            "value": summarize(found),
        }
    }

    bad: list[str] = []
    for extension_id, what, entry in _entries(found):
        try:
            resolve(entry, root=module_root(extension_id))
        except Exception as e:  # noqa: BLE001 — 무엇이 터져도 빌드를 멈춰야 한다
            bad.append(f"{extension_id} {what} ({entry}): {type(e).__name__}: {e}")
    steps["entries"] = {"ok": not bad, "value": bad or f"{len(_entries(found))}개 모두 풀린다"}

    # 찍힌 판 — `expect_version`이 없으면 보이기만 한다(묶지 않은 앱에는 없다). 빌드가 넘기면
    # **`core`의 판도** 읽혀야 한다 — dist-info가 빠지면 C4 `versions.core`가 `0.0.0`이 된다.
    read = stamp if stamp is not None else build_info.stamp()
    core = build_info.package_version("chaeksas-core")
    steps["build"] = {
        "ok": expect_version is None
        or (read is not None and read.version == expect_version and core != build_info.UNKNOWN),
        "value": {"stamp": None if read is None else read.to_json(), "core": core},
    }

    steps.update(extra or {})
    return {"all_ok": all(step["ok"] for step in steps.values()), "steps": steps}


def run(
    out: Path | None = None,
    *,
    want: list[str] | None = None,
    expect_version: str | None = None,
    extra: Callable[[], dict[str, dict[str, Any]]] | None = None,
) -> int:
    """`--selftest` 본문 — 결과를 JSON으로 적고 끝 코드를 돌려준다 (0이면 다 좋다).

    **파일로 적는다** — 묶은 앱은 콘솔 없이(`--windowed`) 뜰 수 있어 표준 출력이 사라진다.
    """
    found = check(want=want, expect_version=expect_version, extra=extra() if extra is not None else None)
    text = json.dumps(found, ensure_ascii=False, indent=2)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0 if found["all_ok"] else 1


#: 런타임을 정말 띄워 보라는 깃발 — 빌드가 PC 실행기에만 넘긴다.
START_RUNTIMES_FLAG = "--start-runtimes"


def main(
    args: Sequence[str],
    *,
    prog: str,
    start_runtimes: Callable[[], dict[str, Any]] | None = None,
) -> int:
    """`<앱> --selftest [파일] [--want a,b] [--expect-version 판] [--start-runtimes]` — 두 앱이 부른다."""
    parser = argparse.ArgumentParser(prog=prog, add_help=False)
    parser.add_argument(SELFTEST_FLAG, dest="out", nargs="?", default=None)
    parser.add_argument("--want", dest="want", default=None, help="켜져 있어야 하는 확장 id (쉼표로 여럿)")
    parser.add_argument("--expect-version", dest="expect", default=None, help="찍혀 있어야 하는 판")
    parser.add_argument(START_RUNTIMES_FLAG, dest="start", action="store_true", help="로컬 런타임을 띄워 본다")
    found, _ = parser.parse_known_args(list(args))
    want = [one.strip() for one in str(found.want).split(",") if one.strip()] if found.want else None

    def runtimes() -> dict[str, dict[str, Any]]:
        if start_runtimes is None:
            return {"runtimes": {"ok": False, "value": f"{prog}는 로컬 런타임을 띄우지 않는다"}}
        return {"runtimes": start_runtimes()}

    return run(
        Path(found.out) if found.out else None,
        want=want,
        expect_version=found.expect,
        extra=runtimes if found.start else None,
    )


__all__ = ["SELFTEST_FLAG", "START_RUNTIMES_FLAG", "check", "main", "run"]
