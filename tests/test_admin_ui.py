"""Admin UI (ADM-01·04·05, ADR-0089) — 화면 없이 누른다.

| 지키는 것 | 왜 |
| --- | --- |
| 서명은 **누를 때마다 암호를 묻는다** | 창이 암호·열린 키를 쥐지 않는다 (ADR-0089 §1) |
| 확인 줄은 **CLI와 같다** | 입구가 둘이어도 「본 것과 서명한 것」이 갈라지지 않는다 |
| Center에 닿지 못하면 「알 수 없음」 | 모르는 것을 「등록 안 됨」으로 말하지 않는다 |
| 첫 키는 **이 PC의 Center일 때만** 대신 넣는다 | 첫 키를 네트워크로 넣는 길은 없다 (C2) |
| Center가 아는 **유일한** 키는 지우지 않는다 | 지우면 Admin이 잠긴다 |
| 연결은 저장하고 **CLI도 읽는다** | 창에서 한 번 넣으면 환경변수가 필요 없다 |
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fastapi.testclient import TestClient  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from chaeksas.admin import connection  # noqa: E402
from chaeksas.admin import keys as keystore  # noqa: E402
from chaeksas.admin.cli import main as admin_main  # noqa: E402
from chaeksas.admin.client import Center  # noqa: E402
from chaeksas.admin.dialogs import ConnectionDialog, Prompter  # noqa: E402
from chaeksas.admin.window import AdminWindow  # noqa: E402
from chaeksas.center.api.signing import bootstrap_key  # noqa: E402
from chaeksas.center.app import create_app  # noqa: E402
from chaeksas.center.settings import Settings  # noqa: E402
from chaeksas.center.storage import Store  # noqa: E402

TOKEN = "t-admin"
PASS = "열쇠말"


@pytest.fixture(autouse=True)
def _admin_home(monkeypatch: Any, tmp_path: Path) -> None:
    """키·설정은 임시 폴더에. **암호 환경변수는 두지 않는다** — 창이 묻는지 본다."""
    monkeypatch.delenv(keystore.PASSPHRASE_ENV, raising=False)
    monkeypatch.delenv(connection.ENV_CENTER_URL, raising=False)
    monkeypatch.delenv(connection.ENV_ADMIN_TOKEN, raising=False)
    monkeypatch.setenv(f"{keystore.ENV_PREFIX}DATA_DIR", str(tmp_path / "admin"))
    QApplication.instance() or QApplication([])


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    made = Store(tmp_path / "center.sqlite3")
    yield made
    made.close()


@pytest.fixture
def client(tmp_path: Path, store: Store) -> Iterator[TestClient]:
    settings = Settings(db_path=tmp_path / "center.sqlite3", package_dir=tmp_path / "packages", admin_token=TOKEN)
    with TestClient(create_app(settings, store=store)) as found:
        yield found


class Scripted(Prompter):
    """짜 둔 답. 무엇을 물었는지 남긴다 — 「암호를 물었나」를 본다."""

    def __init__(self, **answers: Any) -> None:
        super().__init__(None)
        self.answers = answers
        self.asked: list[tuple[str, Any]] = []

    def _take(self, name: str, detail: Any = None) -> Any:
        self.asked.append((name, detail))
        found = self.answers.get(name)
        if isinstance(found, list):
            return found.pop(0) if found else None
        return found

    def text(self, title: str, label: str, default: str = "") -> str | None:
        found = self._take("text", label)
        return default if found is None and "text" not in self.answers else found

    def passphrase(self, key_id: str) -> str | None:
        return self._take("passphrase", key_id)  # type: ignore[no-any-return]

    def new_passphrase(self) -> str | None:
        return self._take("new_passphrase")  # type: ignore[no-any-return]

    def new_key(self) -> tuple[str, str] | None:
        """「새 키」 창 — 이름은 `text`, 암호는 `new_passphrase`로 짠다 (없으면 닫은 것)."""
        name = self._take("text", "새 키") or "a"
        secret = self._take("new_passphrase")
        return (str(name), str(secret)) if secret else None

    def confirm(self, title: str, message: str) -> bool:
        return bool(self._take("confirm", message))

    def choose(self, title: str, label: str, items: list[str]) -> str | None:
        self._take("choose", items)
        return items[-1]

    def open_file(self, title: str) -> str | None:
        return self._take("open_file")  # type: ignore[no-any-return]

    def review(self, lines: list[str], problems: list[str]) -> bool:
        self._take("review", (lines, problems))
        return not problems

    def first_key(self, key: Any, url: str, *, run: Any = None) -> connection.ServerShell | None:
        return self._take("first_key", (key.key_id, url))  # type: ignore[no-any-return]

    def connection(self, reason: str = "") -> bool:
        return bool(self._take("connection", reason))

    def fail(self, message: str) -> None:
        self._take("fail", message)

    def said(self, name: str) -> list[Any]:
        return [detail for asked, detail in self.asked if asked == name]


def window(
    client: TestClient | None,
    ask: Scripted,
    *,
    url: str = "http://center",
    run: Any = None,
    shell: connection.ServerShell | None = None,
) -> AdminWindow:
    """`shell`은 ADM-06에서 사람이 고른 서버 셸이다 (없으면 그 창을 닫은 것)."""

    def center() -> Center:
        return Center(base_url=url, token=TOKEN, client=client)

    if shell is not None:
        ask.answers.setdefault("first_key", shell)
    made = AdminWindow(center=center, prompter=ask, run=run)
    made.refresh()
    return made


def first_key(store: Store, label: str = "첫 키") -> keystore.StoredKey:
    made = keystore.create(label=label, passphrase=PASS)
    bootstrap_key(store, public_key=made.public_bytes(), label=label)
    return made


def cell(table: Any, row: int, column: int) -> str:
    found = table.item(row, column)
    assert found is not None
    return str(found.text())


def select(table: Any, key_id: str) -> None:
    for at in range(table.rowCount()):
        if table.item(at, 0).text() == key_id:
            table.selectRow(at)
            return
    raise AssertionError(f"{key_id}가 표에 없다")


def definition_file(tmp_path: Path, **over: Any) -> Path:
    body: dict[str, Any] = {
        "schema": 2,
        "id": "ext-ocr",
        "version": "1.0.0",
        "name": "외부 OCR",
        "publisher": "외부 업체",
        "tier": "external",
        "service": {
            "protocol": "http-adapter",
            "base_url": "https://ocr.example.com",
            "adapter": {
                "allowed_hosts": ["ocr.example.com"],
                "auth": {"type": "bearer"},
                "operations": [
                    {
                        "name": "read_invoice",
                        "modes": ["autonomous", "deterministic"],
                        "request": {"method": "POST", "path": "/v2/invoice", "body": {"url": "{{input.file_url}}"}},
                        "response": {"output": {"biz_no": "$.result.bizNo"}},
                    }
                ],
            },
        },
        "requires_keys": [{"purpose": "run", "extra_scopes": []}],
        "contributes": {},
    }
    body.update(over)
    target = tmp_path / "extension.json"
    target.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return target


# ─────────────────────────── 키 (ADM-01) ───────────────────────────


def test_the_table_says_what_center_knows(client: TestClient, store: Store) -> None:
    registered = first_key(store)
    loose = keystore.create(label="남은 키", passphrase=PASS)
    shown = window(client, Scripted())

    states = {cell(shown.keys_table, at, 0): cell(shown.keys_table, at, 3) for at in range(2)}
    assert states == {registered.key_id: "등록됨", loose.key_id: "등록 안 됨"}
    assert cell(shown.keys_table, 0, 0) == registered.key_id, "등록된 키가 위로 온다"
    assert "Admin 키 1개" in shown.center_line


def test_unreachable_center_is_unknown_not_unregistered() -> None:
    keystore.create(label="가", passphrase=PASS)
    shown = window(None, Scripted(), url="http://127.0.0.1:9")
    assert cell(shown.keys_table, 0, 3) == "알 수 없음"
    assert "닿지 못했습니다" in shown.center_line


class FakeShell:
    """서버 셸 흉내 — `docker ps`에는 컨테이너 하나, `bootstrap`은 **그 Center 저장소에** 넣는다."""

    def __init__(self, store: Store | None, *, containers: str = "c0ffee123456\n", ssh_code: int = 0) -> None:
        self.store = store
        self.containers = containers
        self.ssh_code = ssh_code
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(argv)
        if self.ssh_code:
            return subprocess.CompletedProcess(argv, self.ssh_code, stdout="", stderr="Permission denied (publickey).")
        line = " ".join(argv)
        if "docker ps" in line:
            return subprocess.CompletedProcess(argv, 0, stdout=self.containers, stderr="")
        if self.store is not None:
            import base64

            bootstrap_key(self.store, public_key=base64.b64decode(kw["input"].strip()), label="첫 키")
        return subprocess.CompletedProcess(argv, 0, stdout="첫 Admin 키를 넣었다\n", stderr="")


def test_a_new_key_goes_in_first_on_this_pcs_center(client: TestClient, store: Store, monkeypatch: Any) -> None:
    """서버 셸이 「이 PC」이고 compose Center가 떠 있으면 컨테이너 안에서 넣고 **API로 확인한다**."""
    monkeypatch.setattr("chaeksas.admin.ops.shutil.which", lambda _name: "/usr/bin/docker")
    run = FakeShell(store)
    ask = Scripted(text="wrapper Admin", new_passphrase=PASS, confirm=[True, True])
    local = connection.ServerShell(kind=connection.SHELL_LOCAL)
    shown = window(client, ask, url="http://localhost:8800", run=run, shell=local)
    shown.new_key()

    [made] = keystore.listing()
    assert run.calls[-1][:4] == ["docker", "exec", "-i", "c0ffee123456"]
    assert "/dev/stdin" in run.calls[-1]
    assert cell(shown.keys_table, 0, 3) == "등록됨"
    assert made.key_id in shown.status.text()


def test_the_first_key_goes_in_over_ssh(client: TestClient, store: Store) -> None:
    """다른 서버의 Center — **SSH로 그 서버 셸에 들어가** 컨테이너 안에서 넣는다. 암호는 묻지 않는다."""
    run = FakeShell(store)
    ask = Scripted(text="wrapper Admin", new_passphrase=PASS, confirm=[True, True])
    remote = connection.ServerShell(kind=connection.SHELL_SSH, ssh_target="ops@center.example", ssh_port=2222)
    shown = window(client, ask, url="https://center.example", run=run, shell=remote)
    shown.new_key()

    ssh = run.calls[-1]
    assert ssh[:7] == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-p", "2222"]
    assert ssh[7] == "ops@center.example" and ssh[8] == "--"
    assert ssh[9].startswith("docker exec -i c0ffee123456 ") and "/dev/stdin" in ssh[9]
    assert "SSH ops@center.example:2222" in shown.status.text(), "어느 셸에서 넣었는지 말한다"
    assert cell(shown.keys_table, 0, 3) == "등록됨"


def test_a_written_center_command_runs_without_docker(client: TestClient, store: Store) -> None:
    run = FakeShell(store)
    remote = connection.ServerShell(
        kind=connection.SHELL_SSH, ssh_target="ops@center.example", center_command="cd ~/Chaeksas && uv run chk-center"
    )
    shown = window(client, Scripted(text="a", new_passphrase=PASS, confirm=[True, True]), run=run, shell=remote)
    shown.new_key()

    assert not any("docker" in " ".join(one) for one in run.calls), "명령을 적었으면 컨테이너를 찾지 않는다"
    assert run.calls[-1][-1].startswith("cd ~/Chaeksas && uv run chk-center admin-keys bootstrap /dev/stdin")


def test_a_shell_that_reaches_another_center_is_caught(client: TestClient) -> None:
    """셸에서는 넣었는데 **주소의 Center가 모르면** 성공이 아니다 — 서로 다른 서버를 가리킨다."""
    run = FakeShell(None)  # 다른 Center에 넣은 셈 (이 저장소는 그대로)
    remote = connection.ServerShell(kind=connection.SHELL_SSH, ssh_target="ops@other")
    ask = Scripted(text="a", new_passphrase=PASS, confirm=[True, True])
    shown = window(client, ask, run=run, shell=remote)
    shown.new_key()

    assert any("모릅니다" in one for one in ask.said("fail"))
    assert cell(shown.keys_table, 0, 3) == "등록 안 됨"


def test_ssh_without_a_key_is_said(client: TestClient) -> None:
    run = FakeShell(None, ssh_code=255)
    remote = connection.ServerShell(kind=connection.SHELL_SSH, ssh_target="ops@center.example")
    ask = Scripted(text="a", new_passphrase=PASS, confirm=True)
    window(client, ask, run=run, shell=remote).new_key()

    assert any("SSH 키" in one for one in ask.said("fail"))


def test_this_pc_is_not_used_for_a_remote_address(client: TestClient) -> None:
    """「이 PC」인데 주소가 다른 서버면 이 PC의 Center는 그 Center가 아니다 — 넣지 않는다."""
    run = FakeShell(None)
    ask = Scripted(text="a", new_passphrase=PASS, confirm=True)
    window(client, ask, run=run, shell=connection.ServerShell(kind=connection.SHELL_LOCAL)).new_key()

    assert not run.calls
    assert any("이 PC가 아닙니다" in one for one in ask.said("fail"))


def test_closing_the_first_key_dialog_puts_nothing(client: TestClient) -> None:
    """ADM-06을 닫으면 아무것도 넣지 않는다 — 네트워크로 넣는 길은 없다."""
    ask = Scripted(text="wrapper Admin", new_passphrase=PASS, confirm=True)
    shown = window(client, ask)
    shown.new_key()

    [made] = keystore.listing()
    assert ask.said("first_key") == [(made.key_id, "http://center")]
    assert cell(shown.keys_table, 0, 3) == "등록 안 됨"


def test_an_unreachable_center_offers_the_settings() -> None:
    keystore.create(label="가", passphrase=PASS)
    ask = Scripted(confirm=False)
    shown = window(None, ask, url="http://127.0.0.1:9")
    shown.keys_table.selectRow(0)
    shown.register_key()
    assert "Center 연결(주소·관리자 토큰)" in ask.said("confirm")[0]


def test_a_second_key_is_added_with_the_first_ones_signature(client: TestClient, store: Store) -> None:
    signer = first_key(store)
    second = keystore.create(label="둘째", passphrase=PASS)
    ask = Scripted(passphrase=PASS)
    shown = window(client, ask)
    select(shown.keys_table, second.key_id)
    shown.register_key()

    assert ask.said("passphrase") == [signer.key_id], "서명할 키의 암호를 **누를 때** 묻는다"
    assert {row.key.key_id: row.state for row in shown.states.rows}[second.key_id] == "등록됨"


def test_a_wrong_passphrase_changes_nothing(client: TestClient, store: Store) -> None:
    first_key(store)
    second = keystore.create(label="둘째", passphrase=PASS)
    ask = Scripted(passphrase="틀린 암호")
    shown = window(client, ask)
    select(shown.keys_table, second.key_id)
    shown.register_key()

    assert any("암호" in one for one in ask.said("fail"))
    assert {row.key.key_id: row.state for row in shown.states.rows}[second.key_id] == "등록 안 됨"


def test_the_only_key_center_knows_is_not_deleted(client: TestClient, store: Store) -> None:
    only = first_key(store)
    ask = Scripted(confirm=True)
    shown = window(client, ask)
    select(shown.keys_table, only.key_id)
    shown.delete_key()

    assert any("잠깁니다" in one for one in ask.said("fail"))
    assert [one.key_id for one in keystore.listing()] == [only.key_id]


def test_a_leftover_key_is_deleted_after_asking(client: TestClient, store: Store) -> None:
    kept = first_key(store)
    loose = keystore.create(label="시험이 남긴 키", passphrase=PASS)
    ask = Scripted(confirm=True)
    shown = window(client, ask)
    select(shown.keys_table, loose.key_id)
    shown.delete_key()

    assert len(ask.said("confirm")) == 1
    assert [one.key_id for one in keystore.listing()] == [kept.key_id]
    assert not loose.public_path.exists()


def test_revoking_a_key_asks_and_signs(client: TestClient, store: Store) -> None:
    signer = first_key(store)
    second = keystore.create(label="둘째", passphrase=PASS)
    shown = window(client, Scripted(passphrase=PASS))
    select(shown.keys_table, second.key_id)
    shown.register_key()

    ask = Scripted(confirm=True, passphrase=PASS)
    shown.ask = ask
    select(shown.keys_table, second.key_id)
    shown.revoke_key()

    assert "무효가 됩니다" in ask.said("confirm")[0], "CLI와 같은 문구"
    assert ask.said("choose"), "등록된 키가 둘이면 서명할 키를 고르게 한다"
    states = {row.key.key_id: row.state for row in shown.states.rows}
    assert states[second.key_id] == "철회됨" or states[signer.key_id] == "철회됨"


# ─────────────────────────── 외부 확장 (ADM-04) ───────────────────────────


def test_an_extension_is_signed_and_registered_with_one_press(
    client: TestClient, store: Store, tmp_path: Path
) -> None:
    key = first_key(store)
    keystore.create(label="시험이 남긴 키", passphrase=PASS)  # 여럿이어도 Center가 아는 하나를 쓴다
    source = definition_file(tmp_path)
    ask = Scripted(open_file=str(source), passphrase=PASS)
    shown = window(client, ask)
    shown.sign_extension()

    assert ask.said("passphrase") == [key.key_id]
    assert "서명하고 등록했습니다 — ext-ocr@1.0.0" in shown.status.text()
    assert [one.id for one in shown.extensions] == ["ext-ocr"]

    shown.ask = Scripted(open_file=str(source), passphrase=PASS)
    shown.sign_extension()
    assert "이미 같은 정의로" in shown.status.text()


def test_the_review_lines_are_the_clis(client: TestClient, store: Store, tmp_path: Path, capsys: Any) -> None:
    """입구가 둘이어도 **같은 줄**을 보고 서명한다."""
    first_key(store)
    source = definition_file(tmp_path)
    ask = Scripted(open_file=str(source), passphrase=PASS)
    window(client, ask).sign_extension()
    [(lines, problems)] = ask.said("review")
    assert not problems

    os.environ[keystore.PASSPHRASE_ENV] = PASS
    try:
        center = Center(base_url="http://center", token=TOKEN, client=client)
        admin_main(["-y", "sign-extension", str(source), "--out", str(tmp_path / "e.json")], center=center)
    finally:
        del os.environ[keystore.PASSPHRASE_ENV]
    printed = capsys.readouterr().out.splitlines()
    assert all(line in printed for line in lines)


def test_a_bad_definition_is_shown_and_never_signed(client: TestClient, store: Store, tmp_path: Path) -> None:
    first_key(store)
    found = json.loads(definition_file(tmp_path).read_text(encoding="utf-8"))
    found["service"]["base_url"] = "http://ocr.example.com"
    source = tmp_path / "bad.json"
    source.write_text(json.dumps(found), encoding="utf-8")
    ask = Scripted(open_file=str(source), passphrase=PASS)
    shown = window(client, ask)
    shown.sign_extension()

    [(_, problems)] = ask.said("review")
    assert problems
    assert not ask.said("passphrase"), "문제가 있으면 암호조차 묻지 않는다"
    assert shown.extensions == []


def test_an_extension_is_revoked(client: TestClient, store: Store, tmp_path: Path) -> None:
    first_key(store)
    shown = window(client, Scripted(open_file=str(definition_file(tmp_path)), passphrase=PASS))
    shown.sign_extension()
    shown.ext_table.selectRow(0)

    ask = Scripted(text="계약 종료", confirm=True, passphrase=PASS)
    shown.ask = ask
    shown.revoke_extension()

    assert "실행 불가" in ask.said("confirm")[0], "CLI와 같은 문구"
    assert "철회했습니다 — ext-ocr@1.0.0" in shown.status.text()


# ─────────────────────────── Center 연결 (ADM-05) ───────────────────────────


def test_the_saved_connection_is_what_the_cli_reads(client: TestClient) -> None:
    dialog = ConnectionDialog(client=client)
    dialog.url.setText("http://center")
    dialog.token.setText(TOKEN)
    dialog.test()
    assert "연결됨" in dialog.result_line.text()
    dialog.save()

    assert dialog.saved
    assert TOKEN not in connection.settings_path().read_text(encoding="utf-8"), "토큰은 설정 파일에 없다"
    found = Center.from_env()
    assert (found.base_url, found.token) == ("http://center", TOKEN)


def test_environment_wins_over_the_saved_connection(monkeypatch: Any) -> None:
    connection.save(url="http://saved", token="saved-token")
    monkeypatch.setenv(connection.ENV_CENTER_URL, "http://from-env")
    now = connection.current()
    assert (now.url, now.token, now.url_from_env, now.token_from_env) == ("http://from-env", "saved-token", True, False)


def test_a_rejected_token_is_said_plainly(client: TestClient) -> None:
    dialog = ConnectionDialog(client=client)
    dialog.url.setText("http://center")
    dialog.token.setText("wrong-token")
    dialog.test()
    assert dialog.result_line.text().startswith("토큰이 거부되었습니다")


def test_a_non_ascii_token_is_refused_in_words_not_a_crash(client: TestClient) -> None:
    """HTTP 헤더는 ASCII다 — 한글이 섞인 토큰은 보내기 전에 말로 멈추고, **저장하지도 않는다**."""
    dialog = ConnectionDialog(client=client)
    dialog.url.setText("http://center")
    dialog.token.setText("토큰-abc")
    dialog.test()
    assert "ASCII" in dialog.result_line.text()
    dialog.save()
    assert not dialog.saved and connection.stored_token() is None


def test_the_first_key_dialog_probes_and_keeps_the_shell(client: TestClient, tmp_path: Path) -> None:
    from chaeksas.admin.dialogs import FirstKeyDialog

    made = keystore.create(label="wrapper Admin", passphrase=PASS)
    run = FakeShell(None)
    dialog = FirstKeyDialog(made, "https://center.example", run=run)
    assert dialog.shell_kind.currentData() == connection.SHELL_SSH, "루프백이 아니면 SSH가 기본이다"
    dialog.ssh_target.setText("ops@center.example")
    dialog.probe()
    assert "찾았습니다 — SSH ops@center.example의 컨테이너 c0ffee123456" in dialog.shell_line.text()
    dialog.put()

    assert dialog.chosen == connection.ServerShell(kind="ssh", ssh_target="ops@center.example")
    assert connection.stored_shell() == dialog.chosen, "다음에 다시 적지 않게 남긴다"


def test_the_first_key_dialog_stays_open_when_nothing_is_found(client: TestClient) -> None:
    from chaeksas.admin.dialogs import FirstKeyDialog

    made = keystore.create(label="a", passphrase=PASS)
    dialog = FirstKeyDialog(made, "https://center.example", run=FakeShell(None, ssh_code=255))
    dialog.ssh_target.setText("ops@center.example")
    dialog.put()
    assert dialog.chosen is None and "SSH 키" in dialog.shell_line.text()


def test_a_missing_token_is_said_before_calling(client: TestClient) -> None:
    from chaeksas.admin.dialogs import TOKEN_GUIDE

    dialog = ConnectionDialog(client=client)
    dialog.url.setText("http://center")
    dialog.test()
    assert dialog.result_line.text().startswith("관리자 토큰이 없습니다")
    assert "담당자" in TOKEN_GUIDE, "토큰을 누구에게 받는지 말한다 (서버 내부는 적지 않는다)"
