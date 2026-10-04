"""S7 — `core`가 LLM에 어떻게 닿는가. 후보를 **스텁에 붙여** 재 본다.

재는 것 넷:

1. **도구 루프 한 바퀴** — 「도구를 불러라」 → 도구 수행 → 「최종 JSON」까지 가는가.
2. **도구 화이트리스트** — 대본에 없는 도구를 부르라고 하면 막히는가.
3. **결과 필드 검증** — C14 `results: {이름: 타입}`대로 받았는지 볼 수 있는가.
4. **재생** — 궤적을 기록해 두고 **모델 없이** 같은 결과를 낼 수 있는가 (결정 수행).

돌리기: `uv run python spikes/s7-llm/run.py`
의존성 무게는 따로 잰다 (README 참고).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from stub import PORT, Handler, serve  # noqa: E402

BASE = f"http://127.0.0.1:{PORT}"

#: 예제가 쓰는 도구 6종 중 하나. 스파이크에서는 시늉만 한다.
TOOLS = {"pdf_text_tool": lambda **kw: f"(pdf 글 — {kw.get('path')})"}

#: C14 `chk:aiTask.results` — 받아야 할 필드와 타입.
RESULTS = {"공급사": "string", "금액": "int", "항목": "list"}

TYPE_OK = {
    "string": str, "int": int, "number": (int, float), "bool": bool,
    "list": list, "dict": dict, "date": str,
}


# ─────────────── 후보 A: 직접 HTTP (httpx, OpenAI 호환) ───────────────


def run_direct(*, allowed: set[str], record: list[dict] | None = None) -> dict[str, Any]:
    """우리가 들고 있는 루프. 도구 호출을 우리가 고르고, 궤적을 우리가 적는다."""
    import httpx

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "목표대로 하고 마지막에 JSON만 낸다."},
        {"role": "user", "content": "## 할 일\n청구서에서 공급사·금액·항목을 뽑는다."},
    ]
    schema = [{"type": "function", "function": {"name": name, "parameters": {}}} for name in allowed]
    usage = {"input_tokens": 0, "output_tokens": 0, "model": ""}

    for _step in range(8):
        answer = httpx.post(
            f"{BASE}/v1/chat/completions",
            json={"model": "stub-1", "messages": messages, "tools": schema},
            timeout=10,
        ).json()
        used = answer.get("usage", {})
        usage["input_tokens"] += used.get("prompt_tokens", 0)
        usage["output_tokens"] += used.get("completion_tokens", 0)
        usage["model"] = answer.get("model", "")

        message = answer["choices"][0]["message"]
        calls = message.get("tool_calls") or []
        if not calls:
            return {"text": message.get("content") or "", "usage": usage}

        messages.append(message)
        for call in calls:
            name = call["function"]["name"]
            if name not in allowed:
                raise PermissionError(f"허용하지 않은 도구: {name}")
            arguments = json.loads(call["function"]["arguments"] or "{}")
            result = TOOLS[name](**arguments)
            if record is not None:
                record.append({"tool": name, "arguments": arguments, "result": result})
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
    raise RuntimeError("단계 한도를 넘었다")


def replay(trace: list[dict], final: str) -> dict[str, Any]:
    """재생 — **모델을 부르지 않고** 적어 둔 도구 순서를 다시 밟고 마지막 답을 쓴다."""
    for step in trace:
        again = TOOLS[step["tool"]](**step["arguments"])
        if again != step["result"]:
            raise RuntimeError(f"재생이 달라졌다: {step['tool']}")
    return {"text": final, "usage": {"input_tokens": 0, "output_tokens": 0, "model": ""}}


# ─────────────── 후보 B: 벤더 SDK (openai) ───────────────


def run_openai_sdk(*, allowed: set[str]) -> dict[str, Any]:
    from openai import OpenAI  # 설치돼 있을 때만 부른다

    client = OpenAI(api_key="stub", base_url=f"{BASE}/v1")
    messages: list[Any] = [{"role": "user", "content": "청구서에서 뽑아라"}]
    schema = [{"type": "function", "function": {"name": n, "parameters": {}}} for n in allowed]
    usage = {"input_tokens": 0, "output_tokens": 0, "model": ""}
    for _step in range(8):
        answer = client.chat.completions.create(model="stub-1", messages=messages, tools=schema)
        if answer.usage:
            usage["input_tokens"] += answer.usage.prompt_tokens
            usage["output_tokens"] += answer.usage.completion_tokens
        usage["model"] = answer.model
        message = answer.choices[0].message
        if not message.tool_calls:
            return {"text": message.content or "", "usage": usage}
        messages.append(message)
        for call in message.tool_calls:
            if call.function.name not in allowed:
                raise PermissionError(f"허용하지 않은 도구: {call.function.name}")
            result = TOOLS[call.function.name](**json.loads(call.function.arguments or "{}"))
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
    raise RuntimeError("단계 한도를 넘었다")


# ─────────────── 검사 ───────────────


def check_results(text: str) -> list[str]:
    """C14 `results`대로 왔는지. 틀린 것을 말로 돌려준다."""
    try:
        found = json.loads(text)
    except ValueError as e:
        return [f"JSON이 아니다: {e}"]
    bad = []
    for name, kind in RESULTS.items():
        if name not in found:
            bad.append(f"빠짐: {name}")
        elif not isinstance(found[name], TYPE_OK[kind]):
            bad.append(f"{name}: {kind}가 아니라 {type(found[name]).__name__}")
    return bad


def line(label: str, ok: bool, note: str = "") -> None:
    print(f"  {'O' if ok else 'X'} {label}{(' — ' + note) if note else ''}")


def main() -> int:
    server, _ = serve()
    try:
        print("후보 A — 직접 HTTP (httpx, OpenAI 호환)")
        trace: list[dict] = []
        found = run_direct(allowed=set(TOOLS), record=trace)
        line("도구 루프 한 바퀴", len(trace) == 1 and bool(found["text"]), f"도구 {len(trace)}회")
        bad = check_results(found["text"])
        line("결과 필드 검증", not bad, "틀린 것 없음" if not bad else str(bad))
        line("사용량 집계", found["usage"]["input_tokens"] > 0, str(found["usage"]))

        Handler.turn = 0
        try:
            run_direct(allowed=set())
            line("도구 화이트리스트", False, "막지 못했다")
        except PermissionError as e:
            line("도구 화이트리스트", True, str(e))

        before = len(Handler.seen)
        again = replay(trace, found["text"])
        line("재생 (모델 없이)", len(Handler.seen) == before and again["text"] == found["text"],
             "모델 호출 0회")

        print("\n후보 B — 벤더 SDK (openai)")
        try:
            Handler.turn = 0
            found_b = run_openai_sdk(allowed=set(TOOLS))
            line("도구 루프 한 바퀴", bool(found_b["text"]))
            line("결과 필드 검증", not check_results(found_b["text"]), "우리가 따로 해야 한다")
            line("재생", False, "SDK는 궤적을 주지 않는다 — 우리가 메시지를 적어 둬야 한다")
        except ImportError:
            print("  (설치 안 됨 — `uv run --with openai python spikes/s7-llm/run.py`)")
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
