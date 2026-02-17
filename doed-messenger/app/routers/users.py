from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Optional
from app.database import get_db
from app import models
from jose import JWTError, jwt
import os
import shutil
import uuid
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

router = APIRouter(prefix="/api/users", tags=["users"])

SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this")
ALGORITHM = "HS256"

AVATAR_DIR = Path("static/avatars")
AVATAR_DIR.mkdir(parents=True, exist_ok=True)

def get_current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        token = token.replace("Bearer ", "")
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            return None
        user = db.query(models.User).filter(models.User.username == username).first()
        return user
    except JWTError:
        return None

@router.get("/list")
async def get_users_list(
    request: Request,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Получить список всех пользователей (кроме себя)"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    query = db.query(models.User).filter(
        models.User.id != user.id,
        models.User.status != "заблокирован"
    )
    
    if search:
        query = query.filter(
            or_(
                models.User.username.contains(search),
                models.User.tag.contains(search)
            )
        )
    
    users = query.limit(50).all()
    
    return [
        {
            "id": u.id,
            "username": u.username,
            "tag": u.tag,
            "status": u.status,
            "avatar": u.avatar,
            "avatar_type": u.avatar_type,
            "avatar_url": u.avatar_url
        }
        for u in users
    ]

@router.post("/avatar/upload")
async def upload_avatar(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Загрузить аватарку"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Проверяем тип файла
    allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Можно загружать только изображения (JPEG, PNG, GIF, WEBP)")
    
    # Проверяем размер (макс 5MB)
    MAX_SIZE = 5 * 1024 * 1024
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)
    
    if file_size > MAX_SIZE:
        raise HTTPException(status_code=400, detail="Файл слишком большой (макс 5MB)")
    
    # Создаем уникальное имя файла
    file_extension = Path(file.filename).suffix
    unique_filename = f"avatar_{user.id}_{uuid.uuid4()}{file_extension}"
    file_path = AVATAR_DIR / unique_filename
    
    # Удаляем старую аватарку если она была загружена
    if user.avatar_type == "image" and user.avatar_url:
        old_avatar = Path(".") / user.avatar_url.lstrip('/')
        if old_avatar.exists():
            old_avatar.unlink()
    
    # Сохраняем новую аватарку
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Обновляем пользователя
    user.avatar = "📷"
    user.avatar_type = "image"
    user.avatar_url = f"/static/avatars/{unique_filename}"
    db.commit()
    
    return {
        "status": "ok",
        "avatar": user.avatar,
        "avatar_type": user.avatar_type,
        "avatar_url": user.avatar_url
    }

@router.post("/avatar/emoji")
async def set_emoji_avatar(
    request: Request,
    emoji: str = Form(...),
    db: Session = Depends(get_db)
):
    """Установить эмодзи как аватарку"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Удаляем старую загруженную аватарку если была
    if user.avatar_type == "image" and user.avatar_url:
        old_avatar = Path(".") / user.avatar_url.lstrip('/')
        if old_avatar.exists():
            old_avatar.unlink()
    
    user.avatar = emoji
    user.avatar_type = "emoji"
    user.avatar_url = None
    db.commit()
    
    return {
        "status": "ok",
        "avatar": user.avatar,
        "avatar_type": user.avatar_type
    }

@router.get("/avatar/{user_id}")
async def get_user_avatar(
    user_id: int,
    db: Session = Depends(get_db)
):
    """Получить аватарку пользователя"""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "avatar": user.avatar,
        "avatar_type": user.avatar_type,
        "avatar_url": user.avatar_url
    }