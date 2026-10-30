"""STU-04 「재생 명세」 — 열린 정의의 AI 태스크 명세를 읽고 잊는다 (C14 §재생, ADR-0028).

명세는 패키지 안 `memory/specs.json`이고 **Studio가 쓰는 파일**이다 — 그림이 아니라서 캔버스를
거치지 않는다(ADR-0022는 BPMN XML의 일이다). 열쇠는 **(정의의 process id, 노드 id)**다.

메인 창이 정의를 고를 때마다 `specs_of()`로 하나 지어 속성 패널에 건다 — 들고 있지 않고 묻는
때마다 파일을 읽는다(시험 실행이 배운 뒤에도 맞게).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from chaeksas.contracts.replay import ReplayMemory, ReplaySpec
from chaeksas.core.replay import read_memory, write_memory


class SpecsUnreadable(Exception):
    """`memory/specs.json`을 읽지 못했다 — 화면은 까닭을 말하고 「명세 잊기」를 끈다."""


@dataclass(frozen=True)
class ReplaySpecs:
    """작업 폴더 하나 + 정의 하나의 재생 명세."""

    folder: Path
    process_id: str

    def _memory(self) -> ReplayMemory:
        try:
            return read_memory(self.folder)
        except (OSError, ValueError, ValidationError) as e:
            raise SpecsUnreadable(f"memory/specs.json을 읽지 못했습니다: {e}") from e

    def find(self, node_id: str) -> ReplaySpec | None:
        """그 노드의 명세. 없으면 `None`, 파일이 깨졌으면 `SpecsUnreadable`."""
        return self._memory().find(self.process_id, node_id)

    def forget(self, node_id: str) -> bool:
        """그 노드의 명세 **하나만** 지우고 곧바로 쓴다. 지운 것이 있었나."""
        memory = self._memory()
        if memory.find(self.process_id, node_id) is None:
            return False
        write_memory(self.folder, memory.without(self.process_id, node_id))
        return True


def specs_of(folder: Path | None, process_id: str | None) -> ReplaySpecs | None:
    """열린 작업 폴더와 정의 → `ReplaySpecs`. 둘 중 하나라도 없으면 `None`(모른다)."""
    if folder is None or not process_id:
        return None
    return ReplaySpecs(folder=Path(folder), process_id=process_id)


__all__ = ["ReplaySpecs", "SpecsUnreadable", "specs_of"]
