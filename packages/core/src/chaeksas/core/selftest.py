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

**쓰는 쪽은 둘이다** (Bot UI·Studio의 `--selftest`) — 한 자리에 두어 둘이 같은 것을 본다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from chaeksas.contracts.extension import PANEL_SURFACES
from chaeksas.core.extensions import ExtensionHost, load_host, summarize
from chaeksas.extension_api.entry import module_root, resolve

#: 빌드 검사 깃발 — **Bot UI·Studio가 같은 이름을 쓴다** (ADR-0024). 빌드가 이것으로 부른다.
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
    for utility in host.utilities():
        found.append((utility.extension_id, f"bot_ui.utilities[{utility.value.id}]", utility.value.entry))
    for runtime in host.local_runtimes():
        found.append((runtime.extension_id, f"bot_ui.local_runtimes[{runtime.value.id}]", runtime.value.entry))
    for one in host.preflight():
        found.append((one.extension_id, f"preflight[{one.value.id}]", one.value.entry))
    # **자리 이름을 베끼지 않는다** — 계약이 쥔 목록을 돈다 (늘면 여기도 함께 본다).
    for surface in sorted(PANEL_SURFACES):
        for panel in host.panels(surface):
            found.append((panel.extension_id, f"bot_ui.panels[{panel.value.id}]", panel.value.entry))
    return found


def check(*, want: list[str] | None = None, host: ExtensionHost | None = None) -> dict[str, Any]:
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

    return {"all_ok": all(step["ok"] for step in steps.values()), "steps": steps}


def run(out: Path | None = None, *, want: list[str] | None = None) -> int:
    """`--selftest` 본문 — 결과를 JSON으로 적고 끝 코드를 돌려준다 (0이면 다 좋다).

    **파일로 적는다** — 묶은 앱은 콘솔 없이(`--windowed`) 뜰 수 있어 표준 출력이 사라진다.
    """
    found = check(want=want)
    text = json.dumps(found, ensure_ascii=False, indent=2)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0 if found["all_ok"] else 1


__all__ = ["SELFTEST_FLAG", "check", "run"]
