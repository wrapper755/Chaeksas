"""M5 인수 시험 — 업무 예제의 M5 묶음을 **진짜 앱으로** 돌린다 (조각 14).

로드맵의 M5 기준이다: 「업무 예제 M5 묶음 통과」. M3·M4와 다른 것은 **서비스 앱이 진짜로
있다**는 것이다 — 녹음해 둔 답을 돌려주는 스텁이 아니라, `samples/mock_apps`가 127.0.0.1에
떠서 C11로 답하고 외부 앱 둘은 HTTP 어댑터로 불린다.

한 바퀴가 이렇게 돈다.

    모의 앱 16개 (진짜 소켓)
        ↑ 주소는 Center 리소스 등록(C7) · 외부 확장은 서명된 정의(C13 E6)
    Center (진짜 앱)
        ↑ Studio가 **읽기만** 한다 (`studio.services`)
    Studio 시험 실행 → 엔진 → RoutedCaller → C11 / 어댑터

거듭 보는 것 다섯.

1. **묶음 목록은 예제에서 읽는다** — `README.md`의 표를 사람이 옮겨 적으면 어긋난다.
2. **주소의 출처는 하나다** (C13) — Center 리소스 등록이다. 등록하지 않은 앱은 부를 수 없다.
3. **외부 앱은 봉투로만** 온다 — 진짜 `chk-admin` 서명을 Center에 등록하고, Studio가 받아
   `verify_external`로 **다시 검증한다**. 검증되지 않으면 부르지 않는다.
4. **키는 참조 이름으로만** 간다 (ADR-0013) — 그림에는 이름뿐이고 값은 Studio의 비밀 창고에서
   나온다. 여기서는 시험이 그 자리를 맡는다.
5. **바깥에 나가지 않는다** — 모델도 모의 앱도 127.0.0.1이다.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi.testclient import TestClient
from stub_model import StubModel

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.admin import keys as keystore  # noqa: E402
from chaeksas.center.api.signing import bootstrap_key  # noqa: E402
from chaeksas.center.app import create_app  # noqa: E402
from chaeksas.center.settings import Settings as CenterSettings  # noqa: E402
from chaeksas.center.storage import Store  # noqa: E402
from chaeksas.contracts.bpmn_ext import Case  # noqa: E402
from chaeksas.contracts.extension import definition_hash  # noqa: E402
from chaeksas.contracts.signing import sign  # noqa: E402
from chaeksas.core.app_directory import AppDirectory  # noqa: E402
from chaeksas.mock_apps import catalog  # noqa: E402
from chaeksas.mock_apps.c11 import SHARED_KEY_ENV  # noqa: E402
from chaeksas.mock_apps.c11 import build as build_mock
from chaeksas.mock_apps.external import apps as external_apps  # noqa: E402
from chaeksas.mock_apps.external import definitions as external_defs  # noqa: E402
from chaeksas.studio.receiver import Receiver  # noqa: E402
from chaeksas.studio.run_dialog import AUTONOMOUS  # noqa: E402
from chaeksas.studio.runner import NO_EXPECT, PASS, CaseRun, Outcome, Plan, read_cases  # noqa: E402
from chaeksas.studio.services import CenterReader, Services  # noqa: E402
from chaeksas.studio.settings import Settings  # noqa: E402
from chaeksas.studio.workspace import BpmProcess, Workspace  # noqa: E402

DOCS = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples"
EXAMPLES = DOCS / "bpmn"

#: 모의 앱이 받는 키 하나 (`samples/README.md`). 그림의 키 참조는 모두 이 값으로 풀린다.
DEV_KEY = "chk_svc_m5acceptancekey000000000000000000000"

ADMIN_TOKEN = "t-admin"
ADMIN = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
SIGN_PASS = "열쇠말"
SIGNED_AT = "2026-10-07T09:00:00+09:00"
#: Center를 TestClient로 부르므로 주소는 이것이다 (httpx의 규약).
CENTER_URL = "http://testserver"


def bundle() -> list[str]:
    """M5 묶음의 예제 파일 이름 — `README.md`의 「마일스톤별 인수 시험 묶음」 표에서 읽는다."""
    body = (DOCS / "README.md").read_text(encoding="utf-8")
    row = next(line for line in body.splitlines() if line.startswith("| M5 |"))
    ids = [x.strip().lower().replace("-", "") for x in row.split("|")[2].split(",")]
    found = []
    for one in ids:
        match = next((p.stem for p in sorted(EXAMPLES.glob(f"{one}_*.bpmn"))), None)
        assert match, f"묶음에 적힌 {one}에 맞는 예제 파일이 없다"
        found.append(match)
    return found


M5 = bundle()


# ─────────────────────────── 모의 앱 (진짜 소켓) ───────────────────────────


def serve(app: Any) -> tuple[str, Any, threading.Thread]:
    """ASGI 앱 하나를 127.0.0.1의 빈 포트에 띄운다."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "앱이 뜨지 않았다"
    return f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}", server, thread


@pytest.fixture(scope="session")
def mock_apps() -> Iterator[dict[str, str]]:
    """모의 앱 열여섯 개를 띄운다 — `{app_id: base_url}`.

    **TestClient로 끼우지 않는다** — Studio의 엔진이 `httpx`로 진짜 요청을 보내고, 어댑터는
    호스트를 IP로 풀어 그 IP로 접속한다 (C13 §4-3). 진짜 소켓이어야 그 길이 시험된다.

    C11 앱 열넷은 **한 포트**에 `/<app_id>`로 모은다 (주소에 경로가 붙어도 C11은 그대로
    이어 붙인다). 외부 앱 둘은 **각자 포트**다 — `AdapterCaller`는 `base_url`의 **경로를
    버리고** 호스트·포트만 쓰므로(§4-3의 DNS 고정이 origin 단위다), 경로 접두사 뒤에 둘 수
    없다. 진짜 외부 앱이 제 주소를 갖는 모양과 같다.
    """
    from fastapi import FastAPI  # noqa: PLC0415

    os.environ[SHARED_KEY_ENV] = DEV_KEY
    held = []
    root = FastAPI(title="모의 서비스 앱 (M5 인수 시험)")
    for one in catalog.C11_APPS:
        root.mount(f"/{one.app_id}", build_mock(one).app)
    shared, server, thread = serve(root)
    held.append((server, thread))

    found = {one.app_id: f"{shared}/{one.app_id}" for one in catalog.C11_APPS}
    for app_id, make in external_apps.BUILDERS.items():
        base, server, thread = serve(make())
        held.append((server, thread))
        found[app_id] = base

    yield found
    for server, thread in held:
        server.should_exit = True
        thread.join(timeout=10)


#: 케이스마다 모의 앱의 거짓 데이터를 바꿔야 하는 자리 — `(예제, 케이스)` → `(앱, 시나리오)`.
#:
#: BX-08의 두 케이스는 **입력이 둘 다 비어 있고** 케이스 설명이 「모의 서버에 95일 연체 1건
#: 추가」라고 적어 두었다. 그 「추가」를 하는 자리다 (`samples/README.md`).
CASE_SCENARIOS: dict[tuple[str, str], tuple[str, str]] = {
    ("bx08_receivable_dunning", "이관 1건"): ("erp", "이관1건"),
}


def scenario(apps: dict[str, str], app_id: str, name: str) -> None:
    """모의 앱의 거짓 데이터를 고른다 (모의만의 길 — C11에는 없다, `samples/README.md`)."""
    import httpx  # noqa: PLC0415

    answer = httpx.post(f"{apps[app_id]}/mock/v1/scenario", json={"name": name}, timeout=10)
    assert answer.status_code == 200, answer.text


# ─────────────────────────── Center (진짜 앱) ───────────────────────────


@pytest.fixture(scope="session")
def admin_home(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """`chk-admin`의 개인키가 사는 곳 — 시험이 쓰는 임시 폴더다 (개발 PC를 건드리지 않는다)."""
    home = tmp_path_factory.mktemp("admin")
    before = {name: os.environ.get(name) for name in (keystore.PASSPHRASE_ENV, f"{keystore.ENV_PREFIX}DATA_DIR")}
    os.environ[keystore.PASSPHRASE_ENV] = SIGN_PASS
    os.environ[f"{keystore.ENV_PREFIX}DATA_DIR"] = str(home)
    yield home
    for name, value in before.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


@pytest.fixture(scope="session")
def center(
    tmp_path_factory: pytest.TempPathFactory, mock_apps: dict[str, str], admin_home: Path
) -> Iterator[tuple[TestClient, str]]:
    """진짜 Center + 등록된 모의 앱들. `(client, studio 키)`를 준다.

    여기서 운영자가 하는 일을 시험이 그대로 한다 — **주소를 넣고**(C7), 외부 확장 정의에
    **서명해 등록한다**(C13 E6). 둘 다 하지 않으면 Studio가 그 앱을 부를 수 없다.
    """
    root = tmp_path_factory.mktemp("center")
    store = Store(root / "center.sqlite3")
    settings = CenterSettings(
        db_path=root / "center.sqlite3", package_dir=root / "packages", admin_token=ADMIN_TOKEN
    )
    with TestClient(create_app(settings, store=store)) as client:
        signing_key = keystore.create(label="M5 인수 시험")
        bootstrap_key(store, public_key=signing_key.public_bytes(), label="M5 인수 시험")

        for one in catalog.C11_APPS:
            answer = client.post(
                "/api/v1/resources/service-apps",
                json={"base_url": mock_apps[one.app_id]},
                headers=ADMIN,
            )
            assert answer.status_code < 400, f"{one.app_id}: {answer.text}"

        for app_id, make in external_defs.BUILDERS.items():
            found = make(mock_apps[app_id])
            envelope = sign(
                {
                    "kind": "extension",
                    "id": found["id"],
                    "version": found["version"],
                    "definition_hash": definition_hash(found),
                },
                keystore.load(signing_key, passphrase=SIGN_PASS),
                signed_at=SIGNED_AT,
            )
            answer = client.post(
                "/api/v1/resources/extensions",
                json={"definition": found, "envelope": envelope.to_json_dict()},
                headers=ADMIN,
            )
            assert answer.status_code < 400, f"{app_id}: {answer.text}"

        studio_key = client.post(
            "/api/v1/center-keys", json={"name": "Studio", "type": "studio"}, headers=ADMIN
        ).json()["key"]
        yield client, studio_key
    store.close()


@pytest.fixture(scope="session")
def directory(center: tuple[TestClient, str]) -> AppDirectory:
    """Studio가 받아 든 바깥 앱 한 벌 — **봉투를 다시 검증한 것**만 들어 있다."""
    client, studio_key = center
    found = Services(
        reader=CenterReader(base_url=CENTER_URL, api_key=studio_key, client=client),
        # 그림의 키 참조는 모두 모의 앱의 개발 키로 풀린다 (ADR-0013 — 값은 그림에 없다).
        secrets=lambda ref: DEV_KEY,
    )
    made = found.directory()
    assert not found.problems, found.problems
    return made


def test_center_knows_every_mock_app(directory: AppDirectory) -> None:
    """등록이 안 된 앱은 부를 수 없다 — 열넷 모두 주소가 있어야 한다 (C7)."""
    assert set(directory.addresses) == {one.app_id for one in catalog.C11_APPS}


def test_both_external_definitions_survive_re_verification(directory: AppDirectory) -> None:
    """Studio가 **다시 검증한다** (C13 「전송」, E6) — 떨어진 것은 `problems`에 남는다."""
    assert set(directory.externals) == set(external_defs.BUILDERS)
    assert not directory.problems



# ─────────────────────────── 스텁 모델 ───────────────────────────


def canned(wanted: dict[str, str], given: dict[str, Any]) -> dict[str, Any] | None:
    """예제가 **그 값이어야 뜻이 통하는** 자리의 답. 열쇠는 `results`의 이름들이다.

    모델이 똑똑한지는 여기서 시험하지 않는다. 시험하는 것은 **엔진·케이스·기대값이 한 줄로
    맞물리는가**다 — 그래서 답은 모델이 아니라 시험이 정한다. `given`은 C14 §「AI 태스크가
    보는 값」대로 모델에게 간 값이라, 건마다 다른 답(반복)도 여기서 만들 수 있다.
    """
    key = tuple(sorted(wanted))

    if key == ("메일",):
        # BX-08과 BX-23이 **같은 모양**을 돌려준다 — `대상`의 칸으로 가른다.
        대상 = given.get("대상") or {}
        if "교육명" in 대상:  # BX-23 교육 독려
            단계 = str(대상.get("단계", ""))
            참조 = [대상.get("팀장메일")] if 단계 in ("팀장참조", "인사팀보고") else []
            if 단계 == "인사팀보고":
                참조 = [*참조, given.get("인사팀메일")]
            return {
                "메일": {
                    "받는사람": 대상.get("메일"),
                    "참조": [one for one in 참조 if one],
                    "제목": f"[{단계}] {대상.get('교육명')} 이수 안내",
                    "본문": f"{대상.get('이름')}님, {대상.get('마감일')}까지 {대상.get('링크')}에서 이수해 주세요.",
                }
            }
        # BX-08 연체 독촉
        return {
            "메일": {
                "받는사람": f"{대상.get('거래처명')} 담당자",
                "제목": f"[{대상.get('단계')}] 미결제 안내",
                "본문": f"{대상.get('거래처명')} 귀중, {대상.get('금액')}원이 {대상.get('연체일수')}일 지났습니다.",
            }
        }

    if key == ("서류결과",):  # BX-10 서류 확인
        서류 = [str(one) for one in (given.get("서류") or [])]
        통장 = any("bank" in one for one in 서류)
        사업자 = any("biz" in one for one in 서류)
        빠진 = [name for name, 있다 in (("사업자등록증", 사업자), ("통장 사본", 통장)) if not 있다]
        return {"서류결과": {"충족": not 빠진, "빠진서류": 빠진, "불일치": []}}

    if key == ("근거", "분류"):  # BX-13 반품 사유 분류
        사유 = str(given.get("사유", ""))
        if "안 켜" in 사유 or "고장" in 사유 or "불량" in 사유:
            return {"분류": "불량", "근거": "제품이 동작하지 않는다고 적혀 있다"}
        if "다른" in 사유 or "오배송" in 사유:
            return {"분류": "오배송", "근거": "주문과 다른 물건이 왔다고 적혀 있다"}
        return {"분류": "단순변심", "근거": "제품 하자를 말하지 않는다"}

    if key == ("문단",):  # BX-15 견적서 문단
        고객 = given.get("고객") or {}
        return {"문단": f"{고객.get('이름', '고객')}님께 아래와 같이 견적을 보내 드립니다."}

    if key == ("환영본문",):  # BX-20 환영 메일
        return {
            "환영본문": (
                f"{given.get('이름')}님, {given.get('부서')} 합류를 환영합니다. "
                f"{given.get('입사일')} 첫 출근이며 회사 메일은 {given.get('회사메일')}입니다. "
                f"{given.get('첫날안내')}"
            )
        }

    if key == ("긴급도", "요약", "종류", "확신도"):  # BX-31 요청 분류
        본문 = str(given.get("본문", ""))
        if "노트북" in 본문 or "화면" in 본문:
            # 확신도 0.8 이상이면 사람 확인을 건너뛴다 (「노트북 고장」 케이스).
            return {"종류": "장비", "긴급도": "높음", "요약": "노트북 화면 불량", "확신도": 0.92}
        # 애매한 요청 — 확신도가 낮아 사람에게 간다.
        return {"종류": "기타", "긴급도": "보통", "요약": "내용이 불분명한 요청", "확신도": 0.21}

    if key == ("근거부족", "초안"):  # BX-32 답변 초안
        근거 = given.get("근거") or []
        if not 근거:
            return {"초안": "", "근거부족": True}
        첫 = 근거[0] if isinstance(근거[0], dict) else {}
        return {
            "초안": f"안녕하세요 고객님. {첫.get('본문', '')}",
            "근거부족": False,
        }

    if key == ("분석",):  # BX-35 묶음 하나 분석 (반복)
        한묶음 = given.get("한묶음") or []
        found = []
        for one in 한묶음:
            제목 = str(one.get("subject", "")) if isinstance(one, dict) else ""
            주제 = 제목[제목.find("[") + 1 : 제목.find("]")] if "[" in 제목 and "]" in 제목 else ""
            주제 = 주제 or "기타"
            감성 = "부정" if 주제 in ("배송", "환불", "품질") else "긍정"
            found.append({"주제": 주제, "감성": 감성})
        return {"분석": found}

    if key == ("요약",):  # BX-35 한 장 요약
        주제별 = given.get("주제별") or {}
        return {"요약": f"주제 {len(주제별)}가지를 보았고 부정 비율은 {given.get('부정비율')}입니다."}

    if key == ("요약", "원인후보"):  # BX-34 장애 요약
        로그 = given.get("로그") or []
        return {
            "요약": f"{given.get('서비스')}에서 오류가 늘고 있습니다. 로그 {len(로그)}줄을 확인했습니다.",
            "원인후보": ["상위 결제 게이트웨이 지연 (추정)", "회로 차단기 반개방 (추정)"],
        }

    if key == ("intent",):  # FX-10 라우팅
        요청 = str(given.get("요청", ""))
        if "환율" in 요청 or "달러" in 요청:
            return {"intent": "exchange_rate"}
        if 요청.startswith("http"):
            return {"intent": "web_summary"}
        return {"intent": "answer"}

    if key == ("답",):
        # 환율 태스크는 `주소`를 받는다 (`domain: api`). 스텁은 도구를 부르지 않는다.
        if "주소" in given:
            return {"답": "오늘 USD/KRW는 1,387.5원입니다."}
        return {"답": f"「{given.get('요청')}」은 사내 안내 페이지를 확인해 주세요."}

    return None


@pytest.fixture(scope="session")
def model() -> Iterator[StubModel]:
    with StubModel(canned) as made:
        yield made


@pytest.fixture(scope="session")
def app() -> Any:
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    try:
        return QApplication.instance() or QApplication([])
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Qt를 띄울 수 없다: {type(e).__name__}: {e}")


# ─────────────────────────── 돌리기 ───────────────────────────


def studio(tmp_path: Path, example: str, model: StubModel) -> tuple[BpmProcess, Settings]:
    data = tmp_path / "studio"
    settings = replace(
        Settings(),
        data_dir=data,
        center_url=CENTER_URL,
        llm_base_url=model.base_url,
        llm_model="stub",
        readable_dirs=(),
    )
    made = Workspace(settings.workspace_dir).ensure().import_example(EXAMPLES, example)
    # 상대 경로의 기준은 **출력 폴더**다 (ADR-0026).
    outputs = settings.outputs_dir / made.id
    outputs.mkdir(parents=True, exist_ok=True)
    return made, settings


def drive(run: CaseRun, *, timeout_ms: int = 60_000) -> Outcome:
    from PySide6.QtCore import QEventLoop, QTimer  # noqa: PLC0415

    loop = QEventLoop()
    box: list[Outcome] = []

    def done(outcome: Outcome) -> None:
        box.append(outcome)
        loop.quit()

    run.ended.connect(done)
    QTimer.singleShot(timeout_ms, loop.quit)
    run.start()
    loop.exec()
    if not box:
        pytest.fail(f"시험 실행이 {timeout_ms}ms 안에 끝나지 않았다")
    return box[0]


def run_all(
    tmp_path: Path,
    example: str,
    directory: AppDirectory,
    model: StubModel,
    apps: dict[str, str],
    *,
    mode: str = AUTONOMOUS,
) -> list[tuple[Case, Outcome]]:
    made, settings = studio(tmp_path, example, model)
    definition = made.entry_definition
    assert definition is not None
    receiver = Receiver(port=0).start()
    out = []
    try:
        for case in read_cases(made, definition):
            if case.manual:
                continue
            app_id, name = CASE_SCENARIOS.get((example, case.name), ("erp", "기본"))
            scenario(apps, app_id, name)
            plan = Plan(
                process=made,
                definition=definition,
                case=case,
                mode=mode,
                settings=replace(settings),
                apps=directory,
            )
            out.append((case, drive(CaseRun(plan, receiver))))
    finally:
        receiver.stop()
    return out


#: 아직 초록이 아닌 예제와 **그 이유**. 비어 있으면 묶음이 다 돈다는 뜻이다.
#:
#: 하나라도 새로 막히면 여기에 **이유를 적고** 넣는다. 조용히 빼면 묶음이 거짓말을 한다.
REMAINING: dict[str, str] = {
    "bx16_reorder_proposal": (
        "`center-jobs`가 **진짜 Center**의 `/jobs`를 부른다 (예제의 설계다) — 이 시험의 Center는 "
        "TestClient라 소켓이 없고, 작업을 만들려면 배포된 BX-17과 등록된 Bot UI도 있어야 한다. "
        "PC 예제 재통과(Center 배포 → Bot UI) 쪽에서 같이 다룬다"
    ),
    "bx33_access_request": (
        "`Task_Schedule`이 `기간`을 쓰는데 그 칸은 **보안팀 결재에만** 있다 (위험 「높음」 갈래). "
        "「위키 읽기」(낮음)에서는 그 결재를 지나지 않아 이름이 비고 expr_error다. 예제·계약 쪽 "
        "공백이다 — 비틀지 않고 적어 둔다 (CLAUDE.md §3-6)"
    ),
    "bx36_legacy_migration": "`desktop` AI 태스크 — Windows 몫이다 (M4 인수 시험과 같은 자리)",
}

#: 케이스가 모두 통과하는 예제. 줄어들면 회귀다.
GREEN = [one for one in M5 if one not in REMAINING]


def test_the_bundle_is_read_from_the_examples() -> None:
    """묶음 목록을 사람이 옮겨 적지 않는다 — 어긋나는 순간 시험이 거짓말을 한다."""
    assert len(M5) == 20
    assert set(REMAINING) <= set(M5), f"남은 목록에 묶음 밖 예제가 있다: {set(REMAINING) - set(M5)}"
    assert len(GREEN) == 17, f"초록이 {len(GREEN)}개다 — 막힌 것이 있으면 REMAINING에 이유를 적는다"


def test_the_model_is_really_asked(
    app: Any, tmp_path: Path, directory: AppDirectory, mock_apps: dict[str, str], model: StubModel
) -> None:
    """정해 둔 답이 **정말 모델을 거쳐** 오는가 — 스텁이 안 불리면 시험이 거짓말을 한다."""
    before = model.asked
    results = run_all(tmp_path, "bx13_return_processing", directory, model, mock_apps)
    assert results
    assert model.asked > before, "AI 태스크가 모델을 부르지 않았다"


@pytest.mark.parametrize("example", GREEN)
def test_an_m5_example_passes_all_its_cases(
    app: Any,
    tmp_path: Path,
    directory: AppDirectory,
    mock_apps: dict[str, str],
    model: StubModel,
    example: str,
) -> None:
    """케이스가 **모두 통과**한다 — 서비스 앱은 진짜로 불린다."""
    results = run_all(tmp_path, example, directory, model, mock_apps)
    assert results, f"{example}: 돌릴 케이스가 없다"
    bad = [(c.name, o.verdict, o.detail) for c, o in results if o.verdict not in (PASS, NO_EXPECT)]
    assert not bad, f"{example}: {bad}"


@pytest.mark.parametrize("example", sorted(REMAINING))
def test_a_remaining_example_still_fails_for_the_written_reason(
    app: Any,
    tmp_path: Path,
    directory: AppDirectory,
    model: StubModel,
    mock_apps: dict[str, str],
    example: str,
) -> None:
    """아직 안 되는 것은 **안 된다고 적어 둔다** — 조용히 초록이 되면 목록이 썩는다."""
    if example == "bx36_legacy_migration":
        pytest.skip("데스크톱 예제 — Windows 몫이다")
    results = run_all(tmp_path, example, directory, model, mock_apps)
    bad = [(c.name, o.verdict) for c, o in results if o.verdict not in (PASS, NO_EXPECT)]
    assert bad, f"{example}: 이제 통과한다 — REMAINING에서 지운다 ({REMAINING[example]})"
