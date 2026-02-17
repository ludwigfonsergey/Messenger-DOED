from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app import models
from jose import JWTError, jwt
import os
import shutil
import uuid
from pathlib import Path
from datetime import datetime

router = APIRouter()
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this")
ALGORITHM = "HS256"

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

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

@router.post("/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Загрузить файл и отправить его получателю"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Получаем receiver_id из query параметров
    receiver_id = request.query_params.get("receiver_id")
    if not receiver_id:
        raise HTTPException(status_code=400, detail="receiver_id is required")
    
    try:
        receiver_id = int(receiver_id)
    except:
        raise HTTPException(status_code=400, detail="receiver_id must be integer")
    
    # Проверяем размер файла (макс 50MB)
    MAX_SIZE = 50 * 1024 * 1024  # 50MB
    
    # Создаем уникальное имя файла
    file_extension = Path(file.filename).suffix
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    file_path = UPLOAD_DIR / unique_filename
    
    # Сохраняем файл
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Получаем размер файла
        file_size = file_path.stat().st_size
        
        if file_size > MAX_SIZE:
            file_path.unlink()  # Удаляем файл
            raise HTTPException(status_code=400, detail="File too large (max 50MB)")
        
        # Сохраняем информацию о файле в БД
        file_message = models.Message(
            sender_id=user.id,
            receiver_id=receiver_id,
            content=f"[Файл] {file.filename}",
            is_file=True,
            file_name=file.filename,
            file_path=f"/uploads/{unique_filename}",
            file_size=file_size,
            file_type=file.content_type
        )
        db.add(file_message)
        db.commit()
        db.refresh(file_message)
        
        return {
            "status": "ok",
            "message_id": file_message.id,
            "file_name": file.filename,
            "file_path": f"/uploads/{unique_filename}",
            "file_size": file_size
        }
        
    except Exception as e:
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/download/{file_id}")
async def download_file(
    file_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Скачать файл"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    message = db.query(models.Message).filter(models.Message.id == file_id).first()
    if not message or not message.is_file:
        raise HTTPException(status_code=404, detail="File not found")
    
    # Проверяем, имеет ли пользователь доступ к файлу
    if message.sender_id != user.id and message.receiver_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    file_path = Path(".") / message.file_path.lstrip('/')
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on server")
    
    return FileResponse(
        path=file_path,
        filename=message.file_name,
        media_type='application/octet-stream'
    )