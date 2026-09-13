"""
Логика курсов: оценка ответов, скрытие правильных вариантов для ученика.
"""
from __future__ import annotations

import copy
import re
import uuid
from datetime import datetime, timezone
from typing import Any


def _norm_text(s: str) -> str:
    t = " ".join((s or "").lower().replace("ё", "е").split())
    return t.strip()


def strip_question_for_learner(q: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(q)
    out.pop("correct_option_ids", None)
    out.pop("correct_text", None)
    out.pop("correct_texts", None)
    return out


def strip_quiz_for_learner(quiz: dict[str, Any] | None) -> dict[str, Any] | None:
    if not quiz:
        return None
    out = copy.deepcopy(quiz)
    for qq in out.get("questions") or []:
        if isinstance(qq, dict):
            strip_question_for_learner(qq)
    return out


def strip_course_payload_for_learner(payload: dict[str, Any]) -> dict[str, Any]:
    p = copy.deepcopy(payload)
    for b in p.get("blocks") or []:
        if isinstance(b, dict) and b.get("quiz"):
            b["quiz"] = strip_quiz_for_learner(b["quiz"])
    if p.get("final_exam"):
        p["final_exam"] = strip_quiz_for_learner(p["final_exam"])
    return p


def grade_question(q: dict[str, Any], answer: Any) -> bool:
    qtype = (q.get("type") or "single").strip()
    if qtype in ("single", "image_single", "select"):
        correct = q.get("correct_option_ids") or []
        if not correct:
            return False
        a = str(answer) if answer is not None else ""
        return a in [str(x) for x in correct]

    if qtype in ("multi", "image_multi"):
        correct = set(str(x) for x in (q.get("correct_option_ids") or []))
        if not correct:
            return False
        if not isinstance(answer, list):
            return False
        chosen = set(str(x) for x in answer)
        return chosen == correct

    if qtype in ("text", "short_text"):
        ct = q.get("correct_text")
        if ct is None:
            return False
        user = _norm_text(str(answer or ""))
        exp = _norm_text(str(ct))
        if q.get("case_insensitive", True):
            ok = user == exp
        else:
            ok = str(answer or "").strip() == str(ct).strip()
        if ok:
            return True
        # допускаем несколько правильных строк
        alts = q.get("correct_texts")
        if isinstance(alts, list):
            for a in alts:
                if _norm_text(str(a)) == user:
                    return True
        return False

    return False


def grade_quiz(questions: list[dict[str, Any]], answers: dict[str, Any]) -> tuple[int, int, list[str]]:
    """Возвращает (wrong_count, total, question_ids_wrong)."""
    wrong: list[str] = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        qid = str(q.get("id") or "")
        if not qid:
            continue
        ok = grade_question(q, answers.get(qid))
        if not ok:
            wrong.append(qid)
    return len(wrong), len(questions), wrong


def quiz_passed(
    wrong_count: int,
    total: int,
    quiz: dict[str, Any],
) -> bool:
    if total == 0:
        return True
    mode = (quiz.get("pass_mode") or "errors").strip()
    if mode == "percent":
        min_p = float(quiz.get("min_percent") or 0)
        pct = ((total - wrong_count) / total) * 100.0
        return pct + 1e-9 >= min_p
    max_wrong = quiz.get("max_wrong")
    if max_wrong is None:
        max_wrong = 0
    return wrong_count <= int(max_wrong)


def default_payload() -> dict[str, Any]:
    bid = f"blk-{uuid.uuid4().hex[:12]}"
    return {
        "version": 1,
        "blocks": [
            {
                "id": bid,
                "title": "Блок 1",
                "order": 0,
                "content_html": "<p>Текст материала</p>",
                "materials": [],
                "opens_at": None,
                "require_previous": True,
                "quiz": None,
            }
        ],
        "final_exam": None,
        "certificate": {"title": "Сертификат", "subtitle": "об окончании курса"},
    }


def ensure_progress_shape(p: dict[str, Any] | None) -> dict[str, Any]:
    if not p or not isinstance(p, dict):
        p = {}
    return {
        "blocks_quiz_passed": dict(p.get("blocks_quiz_passed") or {}),
        "blocks_completed": dict(p.get("blocks_completed") or {}),
        "exam_passed": bool(p.get("exam_passed")),
        "certificate_code": p.get("certificate_code"),
        "certificate_issued_at": p.get("certificate_issued_at"),
    }


def sorted_blocks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = [b for b in (payload.get("blocks") or []) if isinstance(b, dict)]
    blocks.sort(key=lambda x: (int(x.get("order") or 0), str(x.get("id") or "")))
    return blocks


def opens_ok(opens_at: str | None) -> bool:
    if not opens_at:
        return True
    try:
        raw = opens_at.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= dt.astimezone(timezone.utc)
    except Exception:
        return True


def can_access_block(
    payload: dict[str, Any],
    block_id: str,
    prog: dict[str, Any],
) -> tuple[bool, str]:
    blocks = sorted_blocks(payload)
    ids = [str(b.get("id")) for b in blocks if b.get("id")]
    if block_id not in ids:
        return False, "Блок не найден"
    idx = ids.index(block_id)
    b = blocks[idx]
    if not opens_ok(b.get("opens_at")):
        return False, "Блок ещё не открыт по расписанию"
    req_prev = bool(b.get("require_previous", True))
    if idx == 0 or not req_prev:
        return True, ""
    prev_id = ids[idx - 1]
    completed = prog.get("blocks_completed") or {}
    passed_quiz = prog.get("blocks_quiz_passed") or {}
    prev_b = blocks[idx - 1]
    prev_has_quiz = bool(prev_b.get("quiz") and (prev_b.get("quiz") or {}).get("questions"))
    if prev_has_quiz and not passed_quiz.get(prev_id):
        return False, "Сначала пройдите тест предыдущего блока"
    if not completed.get(prev_id):
        return False, "Сначала завершите предыдущий блок"
    return True, ""


def issue_certificate_code(course_id: int, user_id: int) -> str:
    return f"CRS-{course_id}-{user_id}-{uuid.uuid4().hex[:8].upper()}"
