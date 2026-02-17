from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional
from ..database import get_db
from .. import models
from jose import JWTError, jwt
import os
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this")
ALGORITHM = "HS256"

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

@router.get("/history/{contact_id}")
async def get_message_history(
    contact_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Получить историю сообщений с конкретным пользователем"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    messages = db.query(models.Message).filter(
        or_(
            (models.Message.sender_id == user.id) & (models.Message.receiver_id == contact_id),
            (models.Message.sender_id == contact_id) & (models.Message.receiver_id == user.id)
        )
    ).order_by(models.Message.timestamp).limit(100).all()
    
    # Отмечаем сообщения как прочитанные
    for msg in messages:
        if msg.receiver_id == user.id and not msg.is_read:
            msg.is_read = True
    db.commit()
    
    result = []
    for msg in messages:
        sender = db.query(models.User).filter(models.User.id == msg.sender_id).first()
        
        message_data = {
            "id": msg.id,
            "sender_id": msg.sender_id,
            "sender_name": sender.username if sender else "Unknown",
            "content": msg.content,
            "timestamp": msg.timestamp.isoformat(),
            "is_read": msg.is_read,
            "is_mine": msg.sender_id == user.id
        }
        
        # Добавляем информацию о файле если есть
        if msg.is_file:
            message_data.update({
                "is_file": True,
                "file_name": msg.file_name,
                "file_path": msg.file_path,
                "file_size": msg.file_size,
                "file_type": msg.file_type
            })
        
        result.append(message_data)
    
    return result

@router.get("/unread")
async def get_unread_messages(
    request: Request,
    db: Session = Depends(get_db)
):
    """Получить количество непрочитанных сообщений"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    unread = db.query(
        models.Message.sender_id,
        models.User.username,
        models.User.tag,
        db.func.count(models.Message.id).label('count')
    ).join(
        models.User, models.User.id == models.Message.sender_id
    ).filter(
        models.Message.receiver_id == user.id,
        models.Message.is_read == False
    ).group_by(
        models.Message.sender_id,
        models.User.username,
        models.User.tag
    ).all()
    
    return [
        {
            "sender_id": u.sender_id,
            "username": u.username,
            "tag": u.tag,
            "count": u.count
        }
        for u in unread
    ]

@router.post("/read/{message_id}")
async def mark_as_read(
    message_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Отметить сообщение как прочитанное"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    message = db.query(models.Message).filter(models.Message.id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    
    if message.receiver_id != user.id:
        raise HTTPException(status_code=403, detail="Not your message")
    
    message.is_read = True
    db.commit()
    
    return {"status": "ok"}

@router.post("/read/all/{sender_id}")
async def mark_all_as_read(
    sender_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Отметить все сообщения от конкретного отправителя как прочитанные"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    db.query(models.Message).filter(
        models.Message.sender_id == sender_id,
        models.Message.receiver_id == user.id,
        models.Message.is_read == False
    ).update({"is_read": True})
    
    db.commit()
    
    return {"status": "ok"}