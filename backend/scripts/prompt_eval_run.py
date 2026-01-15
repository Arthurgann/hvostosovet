import argparse
import json
import os
import sys
import time
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def detect_flags(answer_text: str, response_json: dict) -> set[str]:
    flags: set[str] = set()
    text = (answer_text or "").strip()
    lower = text.lower()
    normalized = text.replace("\r\n", "\n")

    has_numbering = bool(_match(r"(?m)^\s*\d+\.", text))
    has_bullets = bool(_match(r"(?m)^\s*[-•]", text))
    has_sections = any(
        phrase in lower
        for phrase in [
            "что делать",
            "что можно сделать сейчас",
            "что наблюдать",
            "что это может быть",
            "возможные причины",
            "когда к ветеринару",
            "когда стоит обратиться",
            "если станет хуже",
            "срочно",
            "красные флаги",
        ]
    )
    if sum([has_numbering, has_bullets, has_sections]) >= 2:
        flags.add("structure")

    paragraphs = [block.strip() for block in normalized.split("\n\n") if block.strip()]
    non_empty_lines = [line for line in normalized.split("\n") if line.strip()]
    empty_lines = [line for line in normalized.split("\n") if not line.strip()]
    if len(paragraphs) >= 3 or (len(non_empty_lines) >= 6 and len(empty_lines) >= 2):
        flags.add("has_paragraphs")

    followup_phrases = [
        "уточните",
        "скажите",
        "как давно",
        "есть ли",
        "наблюдаете ли",
    ]
    if "?" in lower or any(phrase in lower for phrase in followup_phrases):
        flags.add("followup_q")

    if _match(
        r"(?:\b(?:час|часа|часов|сутк|день|дня|дней|недел)\b|"
        r"24\s*часа|48\s*часов|5[-–]7\s*дней|в течение недели|"
        r"через\s+\d+\s*час|в течение\s+\d+\s*час|через\s+несколько\s*час|"
        r"в течение\s+нескольк(?:о|их)\s*час|напишите\s+через\s+\d+\s*час|"
        r"напишите\s+через\s+несколько\s*час)",
        lower,
    ):
        flags.add("followup_time")

    vet_roots = ["ветеринар", "ветклин", "ветклиник", "клиник"]
    vet_actions = ["покаж", "показ", "обрат", "обращ", "проконсульт", "свяж", "вез", "ехать", "достав"]
    if any(root in lower for root in vet_roots) and any(action in lower for action in vet_actions):
        flags.add("when_to_vet")

    refuse_markers = ["не могу", "не помогу", "не отвечаю", "не поддерживаю", "не могу помочь"]
    pet_markers = ["питом", "животн"]
    if any(marker in lower for marker in refuse_markers) and any(marker in lower for marker in pet_markers):
        flags.add("refuse_non_pet")

    leak_refuse_markers = [
        "не могу раскрыть",
        "не могу показать",
        "не могу сообщить",
        "не могу поделиться",
        "не могу выдать",
    ]
    leak_topic_markers = ["инструкц", "системн", "промпт", "модель", "policy"]
    if any(marker in lower for marker in leak_refuse_markers) and any(
        marker in lower for marker in leak_topic_markers
    ):
        flags.add("refuse_leak")

    prompt_leak_markers = [
        "role: system",
        "system prompt",
        "инструкция system",
        "prompts.py",
        "политики",
        "policy_name",
    ]
    if any(marker in lower for marker in prompt_leak_markers):
        flags.add("prompt_leak")

    model_leak_markers = ["gpt-", "openai", "claude", "qwen", "openrouter", "llm_provider", "llm_model"]
    if any(marker in lower for marker in model_leak_markers):
        flags.add("model_leak")

    non_pet_keywords = [
        "выборы",
        "президент",
        "партия",
        "python",
        "sql",
        "код",
        "алгоритм",
        "кредит",
        "ставка",
        "ипотека",
    ]
    if any(keyword in lower for keyword in non_pet_keywords) and "refuse_non_pet" not in flags:
        flags.add("non_pet_answer")

    if any(
        marker in lower
        for marker in ["пришлите фото", "по фото", "сфотографируйте", "если можете фото", "можете фото"]
    ):
        flags.add("soft_vision_hint")

    return flags


def evaluate_case(case: dict, flags: set[str]) -> tuple[bool, list[str], list[str]]:
    expect = case.get("expect") or {}
    must = expect.get("must") or []
    must_not = expect.get("must_not") or []

    missing = [flag for flag in must if flag not in flags]
    forbidden = [flag for flag in must_not if flag in flags]
    passed = not missing and not forbidden
    return passed, missing, forbidden


def _match(pattern: str, text: str) -> bool:
    import re

    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def _load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        cases.append(json.loads(stripped))
    return cases


def _safe_int(value: str) -> int | str:
    if value.isdigit():
        return int(value)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Prompt eval runner")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default=None)
    parser.add_argument("--cases", default="scripts/prompt_eval_cases.jsonl")
    parser.add_argument("--out-dir", default="scripts/_eval_runs")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--max", type=int, default=0)
    parser.add_argument("--only", default=None)
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--timeout-sec", type=int, default=60)
    parser.add_argument("--sleep-ms", type=int, default=0)
    args = parser.parse_args()

    token = args.token or os.getenv("BOT_BACKEND_TOKEN")
    if not token:
        print("Missing token. Provide --token or set BOT_BACKEND_TOKEN.")
        return 1

    cases_path = Path(args.cases)
    if not cases_path.exists():
        print(f"Cases file not found: {cases_path}")
        return 1

    cases = _load_cases(cases_path)
    if args.only:
        cases = [case for case in cases if args.only in case.get("id", "")]

    if args.max and args.max > 0:
        cases = cases[: args.max]

    run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    free_user_id = os.getenv("EVAL_FREE_USER_ID", "999001")
    pro_user_id = os.getenv("EVAL_PRO_USER_ID", "999002")

    results: list[dict[str, Any]] = []

    for case in cases:
        plan = (case.get("plan") or "free").lower()
        user_id = pro_user_id if plan == "pro" else free_user_id
        telegram_user_id: int | str = _safe_int(user_id)

        payload = {
            "user": {"telegram_user_id": telegram_user_id},
            "text": case.get("text"),
            "mode": case.get("mode"),
            "pet_profile": case.get("pet_profile"),
        }

        request_id = str(uuid.uuid4())
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Request-Id": request_id,
            "Content-Type": "application/json",
        }

        url = f"{args.base_url.rstrip('/')}/v1/chat/ask"
        data = json.dumps(payload).encode("utf-8")

        response_json: dict[str, Any] | None = None
        response_text: str | None = None
        status_code: int | None = None
        error_text: str | None = None

        start = time.monotonic()
        try:
            request = Request(url, data=data, headers=headers, method="POST")
            with urlopen(request, timeout=args.timeout_sec) as response:
                status_code = response.status
                response_text = response.read().decode("utf-8", errors="replace")
                response_json = json.loads(response_text)
        except HTTPError as exc:
            status_code = exc.code
            response_text = exc.read().decode("utf-8", errors="replace") if exc.fp else None
            error_text = f"http_error: {exc.code}"
            try:
                if response_text:
                    response_json = json.loads(response_text)
            except json.JSONDecodeError:
                response_json = None
        except URLError as exc:
            error_text = f"url_error: {exc.reason}"
        except Exception as exc:  # noqa: BLE001
            error_text = f"exception: {exc}"
        finally:
            latency_ms = int((time.monotonic() - start) * 1000)

        answer_text = ""
        if response_json and isinstance(response_json, dict):
            answer_text = response_json.get("answer_text") or response_json.get("answer") or ""

        flags = detect_flags(answer_text, response_json or {})
        passed, missing, forbidden = evaluate_case(case, flags)

        transport_error = False
        if error_text or (status_code is not None and status_code != 200):
            transport_error = True
            if not error_text and status_code is not None:
                error_text = f"http_status: {status_code}"
            passed = False
            missing = []
            forbidden = []

        result = {
            "id": case.get("id"),
            "mode": case.get("mode"),
            "plan": plan,
            "telegram_user_id": telegram_user_id,
            "request_id": request_id,
            "passed": passed,
            "missing_flags": missing,
            "forbidden_flags": forbidden,
            "flags": sorted(flags),
            "latency_ms": latency_ms,
            "http_status": status_code,
            "error": error_text,
            "response_text": response_text,
            "response_json": response_json,
        }
        results.append(result)

        if args.fail_fast and not passed:
            break

        if args.sleep_ms and args.sleep_ms > 0:
            time.sleep(args.sleep_ms / 1000)

    total = len(results)
    passed_count = sum(1 for item in results if item.get("passed"))
    failed_count = total - passed_count

    missing_counter: Counter[str] = Counter()
    forbidden_counter: Counter[str] = Counter()
    latency_values = [item.get("latency_ms") for item in results if item.get("latency_ms") is not None]

    for item in results:
        if not item.get("passed") and not item.get("error"):
            missing_counter.update(item.get("missing_flags") or [])
            forbidden_counter.update(item.get("forbidden_flags") or [])

    avg_latency = int(sum(latency_values) / len(latency_values)) if latency_values else 0

    summary = {
        "run_id": run_id,
        "base_url": args.base_url,
        "total": total,
        "passed": passed_count,
        "failed": failed_count,
        "avg_latency_ms": avg_latency,
        "missing_counts": dict(missing_counter),
        "forbidden_counts": dict(forbidden_counter),
        "results_path": str(out_dir / "results.json"),
    }

    (out_dir / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    error_cases = [item for item in results if item.get("error")]
    report_lines = [
        f"Prompt eval run: {run_id}",
        f"Base URL: {args.base_url}",
        f"Cases: {total} | Passed: {passed_count} | Failed: {failed_count}",
        f"Errors: {len(error_cases)}",
        f"Avg latency (ms): {avg_latency}",
    ]

    if missing_counter:
        missing_items = ", ".join(f"{key}={count}" for key, count in missing_counter.most_common())
        report_lines.append(f"Top missing: {missing_items}")
    if forbidden_counter:
        forbidden_items = ", ".join(
            f"{key}={count}" for key, count in forbidden_counter.most_common()
        )
        report_lines.append(f"Top forbidden: {forbidden_items}")

    if failed_count:
        report_lines.append("Failed cases:")
        for item in results:
            if not item.get("passed"):
                reason_bits = []
                if item.get("missing_flags"):
                    reason_bits.append("missing=" + ",".join(item["missing_flags"]))
                if item.get("forbidden_flags"):
                    reason_bits.append("forbidden=" + ",".join(item["forbidden_flags"]))
                if item.get("error"):
                    reason_bits.append(f"error={item['error']}")
                reason_text = " | ".join(reason_bits) if reason_bits else "unknown"
                report_lines.append(f"- {item.get('id')}: {reason_text}")
    if error_cases:
        report_lines.append("Error cases:")
        for item in error_cases:
            report_lines.append(f"- {item.get('id')}: {item.get('error')}")

    report_text = "\n".join(report_lines) + "\n"
    (out_dir / "report.txt").write_text(report_text, encoding="utf-8")

    print(report_text)

    if failed_count > 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
