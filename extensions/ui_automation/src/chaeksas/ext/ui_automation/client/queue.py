"""밀린 등록 — 서버에 닿지 못한 등록을 쌓아 두고 나중에 올린다 (BUI-06 8번).

사람이 화면 앞에서 한 일을 **네트워크 때문에 잃지 않게** 한다. 등록 담당자는 보통 현장에서
일하고, 그 자리에서 서버가 안 열리는 일이 흔하다.

지키는 것 넷.

- **4xx는 쌓지 않는다.** 한 번 거부된 것은 다시 보내도 같은 답이고, 큐를 영원히 막는다
  (C8 보고 큐와 같은 규칙).
- **삭제는 쌓지 않는다.** 되돌릴 수 없는 일을 나중에 조용히 하면 안 된다.
- **같은 화면은 한 자리만** 차지한다 — 고치고 다시 누른 것이 쌓여 옛 등록이 뒤에 올라가면
  안 된다 (나중 것이 이긴다).
- **보낸 것만 지운다.** 올리다 실패하면 그대로 남아 다음에 다시 간다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chaeksas.ext.ui_automation.contracts.registry import PageRegistration

log = logging.getLogger(__name__)

#: 큐가 사는 곳 (확장 폴더 밑, C13 `storage.dir`).
QUEUE_DIR = "pending-registrations"


def _safe(page_id: str) -> str:
    """파일 이름으로 쓸 수 있게 — 화면 하나에 파일 하나다 (같은 화면은 한 자리)."""
    return "".join(one if one.isalnum() or one in "._-" else "_" for one in page_id)[:120]


@dataclass
class Pending:
    """밀린 등록 한 벌. 파일 하나에 화면 하나."""

    folder: Path

    def path(self, page_id: str) -> Path:
        return self.folder / f"{_safe(page_id)}.json"

    def add(self, page: PageRegistration) -> Path:
        """쌓는다. **같은 화면이 이미 있으면 덮는다** — 나중 것이 사람의 뜻이다."""
        self.folder.mkdir(parents=True, exist_ok=True)
        target = self.path(page.page_id)
        staged = target.with_suffix(".json.tmp")
        staged.write_text(page.model_dump_json(indent=2), encoding="utf-8", newline="\n")
        staged.replace(target)
        return target

    def all(self) -> list[PageRegistration]:
        """쌓인 것 (화면 ID 순). 읽지 못하는 것은 **버리지 않고 지나간다**."""
        out = []
        for one in sorted(self.folder.glob("*.json")) if self.folder.is_dir() else []:
            try:
                out.append(PageRegistration.model_validate_json(one.read_text(encoding="utf-8")))
            except (OSError, ValueError) as e:  # noqa: PERF203 — 한 줄 깨져도 나머지는 올린다
                log.warning("밀린 등록을 읽지 못했다 (%s): %s", one.name, e)
        return out

    def count(self) -> int:
        return len(list(self.folder.glob("*.json"))) if self.folder.is_dir() else 0

    def drop(self, page_id: str) -> bool:
        """그 화면의 밀린 등록을 버린다 (지운 화면을 나중에 되살리지 않게 — BUI-06 10번)."""
        found = self.path(page_id)
        if not found.is_file():
            return False
        found.unlink()
        return True

    def flush(self, client: Any) -> tuple[int, list[str]]:
        """쌓인 것을 올린다 → `(올린 수, 못 올린 사유들)`.

        **4xx는 버린다** (다시 보내도 같은 답이다 — 사유를 돌려주어 화면이 말하게 한다).
        닿지 못한 것은 **그대로 남는다**.
        """
        sent = 0
        problems: list[str] = []
        for page in self.all():
            try:
                client.register(page)
            except Exception as e:  # noqa: BLE001 — 거부·닿지 못함을 가려 본다
                if getattr(e, "permanent", False):
                    self.drop(page.page_id)
                    problems.append(f"{page.page_id}: 서버가 거부해 버렸습니다 — {e}")
                    continue
                problems.append(f"{page.page_id}: {e}")
                break  # 서버가 닫혀 있다 — 나머지도 같은 답이다
            self.drop(page.page_id)
            sent += 1
        return sent, problems


def read_queue(folder: Path) -> Pending:
    return Pending(folder=folder / QUEUE_DIR)


__all__ = ["QUEUE_DIR", "Pending", "read_queue"]
