"""확장 호스트를 묶을 때 **설치된 확장도 함께** 넣는다 (ADR-0024).

호스트 모듈(`chaeksas.core.extensions`)을 import하는 앱이면 이 훅이 걸린다. 확장은 문자열
(엔트리 포인트·`entry`)로만 닿기 때문에 PyInstaller의 정적 분석이 보지 못한다. 그래서 훅이
설치된 확장을 직접 훑어 셋을 넣는다. 셋 중 하나만 빠져도 증상이 다르다 (S5 스파이크).

| 넣는 것 | 없으면 |
| --- | --- |
| `copy_metadata` (dist-info) | `entry_points(group=…)`가 비어서 **확장을 아예 못 찾는다** |
| `collect_data_files` (`extension.json`) | 「`extension.json`을 읽을 수 없다」로 `failures`에 남는다 |
| `collect_submodules` (클라이언트 모듈) | 확장은 켜지는데 `entry` 해석에서 터진다 |

**확장 이름을 적지 않는 것이 요점이다.** 확장을 설치하면 그만큼 들어간다 (ADR-0018 — 플랫폼은
특정 확장을 모른다).
"""

from importlib.metadata import entry_points

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

GROUP = "chaeksas.extensions"

datas: list[tuple[str, str]] = []
hiddenimports: list[str] = []

found = sorted(entry_points(group=GROUP), key=lambda e: e.name)
for ep in found:
    package = ep.value  # 확장의 파이썬 패키지 (예: chaeksas.ext.ui_automation)
    hiddenimports.append(package)
    hiddenimports += collect_submodules(package)
    datas += collect_data_files(package)
    if ep.dist is not None:
        datas += copy_metadata(ep.dist.metadata["Name"])

print(
    f"[hook-chaeksas.core.extensions] 확장 {len(found)}개 "
    f"({', '.join(ep.name for ep in found) or '없음'}), "
    f"hiddenimports {len(hiddenimports)}개, datas {len(datas)}개"
)
