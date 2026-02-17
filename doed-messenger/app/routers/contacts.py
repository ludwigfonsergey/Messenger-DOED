from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import List, Optional
from app.database import get_db
from app import models
from jose import JWTError, jwt
import os
from dotenv import load_dotenv

load_dotenv()

router = APIRouter(prefix="/api/contacts", tags=["contacts"])

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

@router.get("/list")
async def get_contacts(
    request: Request,
    db: Session = Depends(get_db)
):
    """Получить список контактов текущего пользователя"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    contacts = db.query(models.Contact).filter(
        models.Contact.user_id == user.id,
        models.Contact.is_deleted == False
    ).all()
    
    result = []
    for contact in contacts:
        contact_user = db.query(models.User).filter(models.User.id == contact.contact_id).first()
        if contact_user:
            # Проверяем, не забанен ли пользователь
            if contact_user.status == "заблокирован":
                result.append({
                    "id": contact.id,
                    "contact_id": contact.contact_id,
                    "name": "👻 ЗАБАНЕН",
                    "username": "banned",
                    "tag": "banned",
                    "status": "заблокирован",
                    "avatar": "👻",
                    "avatar_type": "emoji",
                    "is_favorite": contact.is_favorite,
                    "created_at": contact.created_at.isoformat() if contact.created_at else None,
                    "is_banned": True
                })
            else:
                result.append({
                    "id": contact.id,
                    "contact_id": contact.contact_id,
                    "name": contact.contact_name or contact_user.username,
                    "username": contact_user.username,
                    "tag": contact_user.tag,
                    "status": contact_user.status,
                    "avatar": contact_user.avatar,
                    "avatar_type": contact_user.avatar_type,
                    "avatar_url": contact_user.avatar_url,
                    "is_favorite": contact.is_favorite,
                    "created_at": contact.created_at.isoformat() if contact.created_at else None,
                    "is_banned": False
                })
    
    return result

@router.post("/add")
async def add_contact(
    request: Request,
    contact_id: int = Form(...),
    contact_name: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """Добавить пользователя в контакты"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if user.id == contact_id:
        raise HTTPException(status_code=400, detail="Нельзя добавить себя в контакты")
    
    contact_user = db.query(models.User).filter(models.User.id == contact_id).first()
    if not contact_user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Проверяем, не забанен ли пользователь
    if contact_user.status == "заблокирован":
        raise HTTPException(status_code=400, detail="Нельзя добавить забаненного пользователя")
    
    # Проверяем, есть ли уже контакт (включая удаленные)
    existing = db.query(models.Contact).filter(
        and_(
            models.Contact.user_id == user.id,
            models.Contact.contact_id == contact_id
        )
    ).first()
    
    if existing:
        if existing.is_deleted:
            # Восстанавливаем удаленный контакт
            existing.is_deleted = False
            existing.contact_name = contact_name or contact_user.username
            db.commit()
            return {"status": "ok", "message": "Контакт восстановлен", "id": existing.id}
        else:
            raise HTTPException(status_code=400, detail="Этот пользователь уже в ваших контактах")
    
    new_contact = models.Contact(
        user_id=user.id,
        contact_id=contact_id,
        contact_name=contact_name or contact_user.username,
        auto_added=False,
        is_deleted=False
    )
    db.add(new_contact)
    db.commit()
    db.refresh(new_contact)
    
    return {
        "status": "ok", 
        "id": new_contact.id,
        "contact": {
            "id": contact_user.id,
            "username": contact_user.username,
            "tag": contact_user.tag,
            "avatar": contact_user.avatar,
            "avatar_type": contact_user.avatar_type,
            "avatar_url": contact_user.avatar_url
        }
    }

@router.delete("/remove/{contact_id}")
async def remove_contact(
    contact_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Удалить контакт (мягкое удаление)"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    contact = db.query(models.Contact).filter(
        and_(
            models.Contact.user_id == user.id,
            models.Contact.contact_id == contact_id,
            models.Contact.is_deleted == False
        )
    ).first()
    
    if not contact:
        raise HTTPException(status_code=404, detail="Контакт не найден")
    
    # Мягкое удаление
    contact.is_deleted = True
    db.commit()
    
    return {"status": "ok", "message": "Контакт удален"}

@router.delete("/remove-chat/{contact_id}")
async def remove_chat(
    contact_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Удалить чат с пользователем (удаляет контакт и все сообщения)"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Удаляем все сообщения между пользователями
    db.query(models.Message).filter(
        or_(
            and_(models.Message.sender_id == user.id, models.Message.receiver_id == contact_id),
            and_(models.Message.sender_id == contact_id, models.Message.receiver_id == user.id)
        )
    ).delete(synchronize_session=False)
    
    # Удаляем контакт если есть
    contact = db.query(models.Contact).filter(
        and_(
            models.Contact.user_id == user.id,
            models.Contact.contact_id == contact_id
        )
    ).first()
    
    if contact:
        db.delete(contact)
    
    db.commit()
    
    return {"status": "ok", "message": "Чат удален"}

@router.get("/all-users")
async def get_all_users(
    request: Request,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Получить список всех пользователей (кроме забаненных) для добавления"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    query = db.query(models.User).filter(
        models.User.id != user.id,
        models.User.status != "заблокирован",
        models.User.is_bot == False  # Не показываем ботов в общем списке
    )
    
    if search:
        query = query.filter(
            or_(
                models.User.username.contains(search),
                models.User.tag.contains(search)
            )
        )
    
    users = query.limit(50).all()
    
    # Получаем ID пользователей, которые уже в контактах
    existing_contacts = db.query(models.Contact).filter(
        models.Contact.user_id == user.id,
        models.Contact.is_deleted == False
    ).all()
    contact_ids = [c.contact_id for c in existing_contacts]
    
    return [
        {
            "id": u.id,
            "username": u.username,
            "tag": u.tag,
            "status": u.status,
            "avatar": u.avatar,
            "avatar_type": u.avatar_type,
            "avatar_url": u.avatar_url,
            "is_contact": u.id in contact_ids
        }
        for u in users
    ]