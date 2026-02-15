from fastapi import APIRouter, Depends, HTTPException, Request, Form
from sqlalchemy.orm import Session
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

@router.get("/list")
async def get_contacts(
    request: Request,
    db: Session = Depends(get_db)
):
    """Получить список контактов пользователя"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    contacts = db.query(models.Contact).filter(models.Contact.user_id == user.id).all()
    
    result = []
    for contact in contacts:
        contact_user = db.query(models.User).filter(models.User.id == contact.contact_id).first()
        if contact_user:
            result.append({
                "id": contact.id,
                "contact_id": contact.contact_id,
                "name": contact.contact_name or contact_user.username,
                "username": contact_user.username,
                "tag": contact_user.tag,
                "status": contact_user.status,
                "avatar": contact_user.avatar,
                "is_favorite": contact.is_favorite
            })
    
    return result

@router.post("/add")
async def add_contact(
    contact_id: int = Form(...),
    contact_name: Optional[str] = Form(None),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """Добавить пользователя в контакты"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Проверяем, не добавляет ли пользователь сам себя
    if user.id == contact_id:
        raise HTTPException(status_code=400, detail="Cannot add yourself")
    
    # Проверяем, существует ли пользователь
    contact_user = db.query(models.User).filter(models.User.id == contact_id).first()
    if not contact_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Проверяем, нет ли уже такого контакта
    existing = db.query(models.Contact).filter(
        models.Contact.user_id == user.id,
        models.Contact.contact_id == contact_id
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Contact already exists")
    
    # Создаем новый контакт
    new_contact = models.Contact(
        user_id=user.id,
        contact_id=contact_id,
        contact_name=contact_name or contact_user.username
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
            "tag": contact_user.tag
        }
    }