"""비밀 폴더 — OS 비밀 저장소가 없는 컨테이너에서 받은 키를 둘 자리 (ADR-0100).

**운영자가 고를 때만 쓴다** — 환경변수 `CHK_SERVER_RUNNER__SECRETS_DIR`가 있어야 켜진다. 없으면
지금처럼 OS 비밀 저장소만 보고, 그것도 없으면 등록 요청을 보내지 않는다 (C12). 몰래 평문 파일로
흘리지 않는다는 규칙(CLAUDE.md §5)은 그대로이고, 이것은 **사람이 자리를 정해 준 경우**다.

- 파일 하나(`secrets.json`)이고 폴더는 0700·파일은 0600이다. 쓸 때는 0600으로 만든 임시 파일을
  바꿔 끼운다 — 반쯤 쓴 파일이 남지 않는다.
- `keyring` 백엔드와 같은 세 함수(`get_password`·`set_password`·`delete_password`)를 가져
  `Credentials`가 그 자리에 끼운다. 부르는 쪽(등록·회전)은 달라지지 않는다.
- 하트비트 스레드와 실행 스레드가 함께 부를 수 있어 잠금 하나로 묶는다.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

ENV_SECRETS_DIR = "CHK_SERVER_RUNNER__SECRETS_DIR"
FILE_NAME = "secrets.json"


class SecretFile:
    """비밀 폴더 하나. `service`(keyring의 서비스 이름)마다 이름 공간을 나눈다."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.path = folder / FILE_NAME
        self._lock = threading.Lock()

    def _read(self) -> dict[str, dict[str, str]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        # 깨진 파일은 덮지 않는다 — 받은 키를 조용히 잃으면 다시 승인해야 한다.
        if not isinstance(raw, dict):
            raise ValueError(f"{self.path}의 모양이 다릅니다")
        return {str(k): {str(n): str(v) for n, v in dict(v).items()} for k, v in raw.items()}

    def _write(self, body: dict[str, dict[str, str]]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        if sys.platform != "win32":  # Windows의 chmod는 읽기 전용 표시만 바꾼다
            self.folder.chmod(0o700)
        temp = self.path.with_name(f".{FILE_NAME}.{os.getpid()}.tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(body, out, ensure_ascii=False, indent=2)
        temp.replace(self.path)

    def get_password(self, service: str, name: str) -> str | None:
        with self._lock:
            return self._read().get(service, {}).get(name)

    def set_password(self, service: str, name: str, value: str) -> None:
        with self._lock:
            body = self._read()
            body.setdefault(service, {})[name] = value
            self._write(body)

    def delete_password(self, service: str, name: str) -> None:
        with self._lock:
            body = self._read()
            if body.get(service, {}).pop(name, None) is None:
                return
            if not body[service]:
                del body[service]
            self._write(body)


def from_env() -> SecretFile | None:
    """환경변수가 가리키는 비밀 폴더. 없으면 `None` (켜지 않는다)."""
    folder = os.environ.get(ENV_SECRETS_DIR)
    return SecretFile(Path(folder)) if folder else None


__all__ = ["ENV_SECRETS_DIR", "FILE_NAME", "SecretFile", "from_env"]
