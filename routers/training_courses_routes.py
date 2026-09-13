"""Маршруты курсов (конструктор, прохождение, тесты, сертификат)."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from deps import get_admin_user, get_current_user
from models import TrainingCourse, TrainingUserCourseProgress, User
from training_course_logic import (
    can_access_block,
    default_payload,
    ensure_progress_shape,
    grade_quiz,
    issue_certificate_code,
    quiz_passed,
    sorted_blocks,
    strip_course_payload_for_learner,
)


def register_training_course_routes(router: APIRouter) -> None:
    @router.get("/courses/list")
    def list_courses_published(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
        rows = (
            db.query(TrainingCourse)
            .filter(TrainingCourse.is_published == True)
            .order_by(TrainingCourse.updated_at.desc())
            .all()
        )
        return [
            {
                "id": r.id,
                "title": r.title,
                "description": r.description or "",
                "preview_image_url": r.preview_image_url,
                "is_published": r.is_published,
                "updated_at": r.updated_at,
            }
            for r in rows
        ]

    @router.get("/courses/admin/all")
    def list_courses_admin(db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
        rows = db.query(TrainingCourse).order_by(TrainingCourse.updated_at.desc()).all()
        return [
            {
                "id": r.id,
                "title": r.title,
                "description": r.description or "",
                "preview_image_url": r.preview_image_url,
                "is_published": r.is_published,
                "updated_at": r.updated_at,
            }
            for r in rows
        ]

    @router.get("/courses/{course_id}/admin")
    def get_course_admin(course_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
        r = db.query(TrainingCourse).filter(TrainingCourse.id == course_id).first()
        if not r:
            raise HTTPException(status_code=404, detail="Курс не найден")
        return _course_to_dict(r)

    class CourseCreateBody(BaseModel):
        title: str | None = None
        description: str | None = ""
        preview_image_url: str | None = None
        is_published: bool = False
        payload: Any = None

    @router.post("/courses", status_code=201)
    def create_course(data: CourseCreateBody, db: Session = Depends(get_db), current_user: User = Depends(get_admin_user)):
        pl = data.payload if isinstance(data.payload, dict) else default_payload()
        normalized_title = (data.title or "").strip()[:256] or "Новый курс"
        obj = TrainingCourse(
            title=normalized_title,
            description=(data.description or "").strip(),
            preview_image_url=(data.preview_image_url or "").strip() or None,
            is_published=bool(data.is_published),
            payload=pl,
            created_by_user_id=current_user.id,
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return _course_to_dict(obj)

    class CoursePatchBody(BaseModel):
        title: str | None = None
        description: str | None = None
        preview_image_url: str | None = None
        is_published: bool | None = None
        payload: dict[str, Any] | None = None

    @router.patch("/courses/{course_id}")
    def patch_course(
        course_id: int,
        data: CoursePatchBody,
        db: Session = Depends(get_db),
        _: User = Depends(get_admin_user),
    ):
        r = db.query(TrainingCourse).filter(TrainingCourse.id == course_id).first()
        if not r:
            raise HTTPException(status_code=404, detail="Курс не найден")
        if data.title is not None:
            t = data.title.strip()
            if not t:
                raise HTTPException(status_code=400, detail="Заголовок не может быть пустым")
            r.title = t
        if data.description is not None:
            r.description = data.description.strip()
        if data.preview_image_url is not None:
            r.preview_image_url = (data.preview_image_url or "").strip() or None
        if data.is_published is not None:
            r.is_published = bool(data.is_published)
        if data.payload is not None:
            r.payload = data.payload
        r.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(r)
        return _course_to_dict(r)

    @router.delete("/courses/{course_id}", status_code=204)
    def delete_course(course_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
        r = db.query(TrainingCourse).filter(TrainingCourse.id == course_id).first()
        if not r:
            raise HTTPException(status_code=404, detail="Курс не найден")
        db.query(TrainingUserCourseProgress).filter(TrainingUserCourseProgress.course_id == course_id).delete()
        db.delete(r)
        db.commit()
        return None

    @router.get("/courses/{course_id}/learn")
    def get_course_learn(course_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
        r = db.query(TrainingCourse).filter(TrainingCourse.id == course_id).first()
        if not r or not r.is_published:
            raise HTTPException(status_code=404, detail="Курс не найден")
        payload = r.payload if isinstance(r.payload, dict) else {}
        safe = strip_course_payload_for_learner(payload)
        prog_row = (
            db.query(TrainingUserCourseProgress)
            .filter(
                TrainingUserCourseProgress.user_id == current_user.id,
                TrainingUserCourseProgress.course_id == course_id,
            )
            .first()
        )
        prog = ensure_progress_shape(prog_row.progress if prog_row else {})
        avail = []
        for b in sorted_blocks(payload):
            bid = str(b.get("id") or "")
            if not bid:
                continue
            ok, _ = can_access_block(payload, bid, prog)
            if ok:
                avail.append(bid)
        cert = None
        if prog.get("certificate_code"):
            cert = {
                "code": prog.get("certificate_code"),
                "issued_at": prog.get("certificate_issued_at"),
                "title": (payload.get("certificate") or {}).get("title") or "Сертификат",
            }
        return {
            "id": r.id,
            "title": r.title,
            "description": r.description or "",
            "preview_image_url": r.preview_image_url,
            "payload": safe,
            "progress": prog,
            "available_block_ids": avail,
        }

    class SubmitQuizBody(BaseModel):
        block_id: str | None = None
        is_exam: bool = False
        answers: dict[str, Any] = Field(default_factory=dict)

    @router.post("/courses/{course_id}/submit-quiz")
    def submit_quiz(
        course_id: int,
        body: SubmitQuizBody,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        r = db.query(TrainingCourse).filter(TrainingCourse.id == course_id).first()
        if not r or not r.is_published:
            raise HTTPException(status_code=404, detail="Курс не найден")
        payload = r.payload if isinstance(r.payload, dict) else {}
        prog_row = (
            db.query(TrainingUserCourseProgress)
            .filter(
                TrainingUserCourseProgress.user_id == current_user.id,
                TrainingUserCourseProgress.course_id == course_id,
            )
            .first()
        )
        prog = ensure_progress_shape(prog_row.progress if prog_row else {})

        if body.is_exam:
            exam = payload.get("final_exam") or {}
            questions = [q for q in (exam.get("questions") or []) if isinstance(q, dict)]
            if not questions:
                raise HTTPException(status_code=400, detail="Экзамен не настроен")
            blocks = sorted_blocks(payload)
            completed = prog.get("blocks_completed") or {}
            for b in blocks:
                bid = str(b.get("id") or "")
                if not bid:
                    continue
                if not completed.get(bid):
                    raise HTTPException(status_code=400, detail="Завершите все блоки курса перед экзаменом")
            wrong, total, wrong_ids = grade_quiz(questions, body.answers)
            passed = quiz_passed(wrong, total, exam)
            if passed:
                prog["exam_passed"] = True
                if not prog.get("certificate_code"):
                    prog["certificate_code"] = issue_certificate_code(course_id, current_user.id)
                    prog["certificate_issued_at"] = datetime.now(timezone.utc).isoformat()
            _save_progress(db, current_user.id, course_id, prog)
            return {"passed": passed, "wrong_count": wrong, "total": total, "wrong_question_ids": wrong_ids, "progress": prog}

        bid = (body.block_id or "").strip()
        if not bid:
            raise HTTPException(status_code=400, detail="Укажите block_id")
        ok, msg = can_access_block(payload, bid, prog)
        if not ok:
            raise HTTPException(status_code=403, detail=msg)
        block = next((b for b in sorted_blocks(payload) if str(b.get("id")) == bid), None)
        if not block:
            raise HTTPException(status_code=404, detail="Блок не найден")
        quiz = block.get("quiz") or {}
        questions = [q for q in (quiz.get("questions") or []) if isinstance(q, dict)]
        if not questions:
            raise HTTPException(status_code=400, detail="У блока нет теста")
        wrong, total, wrong_ids = grade_quiz(questions, body.answers)
        passed = quiz_passed(wrong, total, quiz)
        if passed:
            pq = prog.get("blocks_quiz_passed") or {}
            pq[bid] = True
            prog["blocks_quiz_passed"] = pq
        _save_progress(db, current_user.id, course_id, prog)
        return {"passed": passed, "wrong_count": wrong, "total": total, "wrong_question_ids": wrong_ids, "progress": prog}

    class CompleteBlockBody(BaseModel):
        block_id: str

    @router.post("/courses/{course_id}/complete-block")
    def complete_block(
        course_id: int,
        body: CompleteBlockBody,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        r = db.query(TrainingCourse).filter(TrainingCourse.id == course_id).first()
        if not r or not r.is_published:
            raise HTTPException(status_code=404, detail="Курс не найден")
        payload = r.payload if isinstance(r.payload, dict) else {}
        bid = (body.block_id or "").strip()
        prog_row = (
            db.query(TrainingUserCourseProgress)
            .filter(
                TrainingUserCourseProgress.user_id == current_user.id,
                TrainingUserCourseProgress.course_id == course_id,
            )
            .first()
        )
        prog = ensure_progress_shape(prog_row.progress if prog_row else {})
        ok, msg = can_access_block(payload, bid, prog)
        if not ok:
            raise HTTPException(status_code=403, detail=msg)
        block = next((b for b in sorted_blocks(payload) if str(b.get("id")) == bid), None)
        if not block:
            raise HTTPException(status_code=404, detail="Блок не найден")
        quiz = block.get("quiz") or {}
        has_q = bool(quiz.get("questions"))
        if has_q:
            pq = prog.get("blocks_quiz_passed") or {}
            if not pq.get(bid):
                raise HTTPException(status_code=400, detail="Сначала пройдите тест блока")
        comp = prog.get("blocks_completed") or {}
        comp[bid] = True
        prog["blocks_completed"] = comp
        _save_progress(db, current_user.id, course_id, prog)
        return {"ok": True, "progress": prog}


def _save_progress(db: Session, user_id: int, course_id: int, prog: dict[str, Any]):
    row = (
        db.query(TrainingUserCourseProgress)
        .filter(
            TrainingUserCourseProgress.user_id == user_id,
            TrainingUserCourseProgress.course_id == course_id,
        )
        .first()
    )
    now = datetime.now(timezone.utc)
    if not row:
        row = TrainingUserCourseProgress(user_id=user_id, course_id=course_id, progress=prog)
        db.add(row)
    else:
        row.progress = prog
        row.updated_at = now
    db.commit()


def _course_to_dict(r: TrainingCourse) -> dict[str, Any]:
    return {
        "id": r.id,
        "title": r.title,
        "description": r.description or "",
        "preview_image_url": r.preview_image_url,
        "is_published": bool(r.is_published),
        "payload": copy.deepcopy(r.payload) if isinstance(r.payload, dict) else {},
        "created_by_user_id": r.created_by_user_id,
        "created_at": r.created_at,
        "updated_at": r.updated_at,
    }
