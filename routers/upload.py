"""
API для загрузки файлов
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pathlib import Path
import shutil
import uuid
from models import User
from deps import get_admin_user, get_current_user

router = APIRouter(tags=["upload"])

UPLOAD_DIR = Path("/home/crm-backend/uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

PDF_EXTENSIONS = {".pdf"}
MAX_PDF_SIZE = 50 * 1024 * 1024  # 50MB


@router.post("/api/upload/image")
async def upload_image(
    file: UploadFile = File(...),
    _: User = Depends(get_admin_user)
):
    """Загрузка изображения"""
    
    # Проверка расширения
    file_ext = Path(file.filename or "").suffix.lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Недопустимый формат файла. Разрешены: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    
    # Проверка размера
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Файл слишком большой. Максимальный размер: 5MB"
        )
    
    # Генерация уникального имени
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = UPLOAD_DIR / unique_filename
    
    # Сохранение файла
    try:
        with open(file_path, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения файла: {str(e)}")
    
    # Возвращаем URL
    return {
        "filename": unique_filename,
        "url": f"/uploads/{unique_filename}"
    }


@router.post("/api/upload/profile-image")
async def upload_profile_image(
    file: UploadFile = File(...),
    _: User = Depends(get_current_user),
):
    """Загрузка фото профиля (доступно авторизованным пользователям)."""
    file_ext = Path(file.filename or "").suffix.lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Недопустимый формат файла. Разрешены: {', '.join(ALLOWED_EXTENSIONS)}",
        )
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="Файл слишком большой. Максимальный размер: 5MB")
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = UPLOAD_DIR / unique_filename
    try:
        with open(file_path, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения файла: {str(e)}")
    return {"filename": unique_filename, "url": f"/uploads/{unique_filename}"}


@router.post("/api/upload/chat-image")
async def upload_chat_image(
    file: UploadFile = File(...),
    _: User = Depends(get_current_user),
):
    """Загрузка картинки чата/группы (доступно авторизованным пользователям)."""
    file_ext = Path(file.filename or "").suffix.lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Недопустимый формат файла. Разрешены: {', '.join(ALLOWED_EXTENSIONS)}",
        )
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="Файл слишком большой. Максимальный размер: 5MB")
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = UPLOAD_DIR / unique_filename
    try:
        with open(file_path, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения файла: {str(e)}")
    return {"filename": unique_filename, "url": f"/uploads/{unique_filename}"}


@router.post("/api/upload/pdf")
async def upload_pdf(
    file: UploadFile = File(...),
    _: User = Depends(get_admin_user)
):
    """Загрузка PDF (каталог производителя)"""
    file_ext = Path(file.filename or "").suffix.lower()
    if file_ext not in PDF_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Недопустимый формат. Разрешён только PDF."
        )
    content = await file.read()
    if len(content) > MAX_PDF_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Файл слишком большой. Максимальный размер: {MAX_PDF_SIZE // (1024*1024)}MB"
        )
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = UPLOAD_DIR / unique_filename
    try:
        with open(file_path, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения файла: {str(e)}")
    return {
        "filename": unique_filename,
        "url": f"/uploads/{unique_filename}"
    }


REPORT_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".heic",
    ".heif",
}
MAX_REPORT_FILE_SIZE = 100 * 1024 * 1024  # 100MB


MAX_ANY_FILE_SIZE = 100 * 1024 * 1024  # 100MB


@router.post("/api/upload/file")
async def upload_any_file(
    file: UploadFile = File(...),
    _: User = Depends(get_current_user),
):
    """Загрузка любого файла для разделов вроде «Общий диск». Доступно авторизованным пользователям."""
    orig = file.filename or "file"
    file_ext = Path(orig).suffix.lower()
    content = await file.read()
    if len(content) > MAX_ANY_FILE_SIZE:
        raise HTTPException(status_code=400, detail="Файл слишком большой. Максимум 100MB")
    # Если расширения нет — сохраняем без него
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = UPLOAD_DIR / unique_filename
    try:
        with open(file_path, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    safe_name = orig.replace('"', "").strip() or unique_filename
    if len(safe_name) > 240:
        safe_name = safe_name[:237] + "..."
    return {"filename": unique_filename, "original_filename": safe_name, "url": f"/uploads/{unique_filename}"}


SIDEBAR_VIDEO_EXTENSIONS = {".mp4", ".webm"}
MAX_SIDEBAR_VIDEO_SIZE = 80 * 1024 * 1024  # 80MB


@router.post("/api/upload/sidebar-video")
async def upload_sidebar_video(
    file: UploadFile = File(...),
    _: User = Depends(get_admin_user),
):
    """Загрузка вертикального видео для сайдбара (только администратор)."""
    file_ext = Path(file.filename or "").suffix.lower()
    if file_ext not in SIDEBAR_VIDEO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Недопустимый формат. Разрешены: .mp4, .webm",
        )
    content = await file.read()
    if len(content) > MAX_SIDEBAR_VIDEO_SIZE:
        raise HTTPException(status_code=400, detail="Файл слишком большой. Максимум 80MB")
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = UPLOAD_DIR / unique_filename
    try:
        with open(file_path, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения файла: {str(e)}")
    return {"filename": unique_filename, "url": f"/uploads/{unique_filename}"}


@router.post("/api/upload/report")
async def upload_report_file(
    file: UploadFile = File(...),
    _: User = Depends(get_current_user)
):
    """Загрузка файла для отчёта (Z-отчёт, сверка по картам). Доступно авторизованным пользователям."""
    file_ext = Path(file.filename or "").suffix.lower()
    if file_ext not in REPORT_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Недопустимый формат. Разрешены: PDF, JPG, PNG, GIF, WebP, HEIC/HEIF"
        )
    content = await file.read()
    if len(content) > MAX_REPORT_FILE_SIZE:
        raise HTTPException(status_code=400, detail="Файл слишком большой. Максимум 100MB")
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = UPLOAD_DIR / unique_filename
    try:
        with open(file_path, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"filename": unique_filename, "url": f"/uploads/{unique_filename}"}


NORMATIVE_ATTACHMENT_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".odt",
    ".ods",
    ".odp",
    ".txt",
    ".rtf",
    ".zip",
}
MAX_NORMATIVE_ATTACHMENT_SIZE = 50 * 1024 * 1024  # 50MB


@router.post("/api/upload/normative-file")
async def upload_normative_file(
    file: UploadFile = File(...),
    _: User = Depends(get_admin_user),
):
    """Файл к нормативному акту (PDF, Office, архив)."""
    orig = file.filename or "file"
    file_ext = Path(orig).suffix.lower()
    if file_ext not in NORMATIVE_ATTACHMENT_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Недопустимый формат. Разрешены: {', '.join(sorted(NORMATIVE_ATTACHMENT_EXTENSIONS))}",
        )
    content = await file.read()
    if len(content) > MAX_NORMATIVE_ATTACHMENT_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Файл слишком большой. Максимум {MAX_NORMATIVE_ATTACHMENT_SIZE // (1024 * 1024)} МБ",
        )
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = UPLOAD_DIR / unique_filename
    try:
        with open(file_path, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения: {str(e)}")
    safe_name = orig.replace('"', "").strip() or unique_filename
    if len(safe_name) > 240:
        safe_name = safe_name[:237] + "..."
    return {
        "filename": unique_filename,
        "original_filename": safe_name,
        "url": f"/uploads/{unique_filename}",
    }
