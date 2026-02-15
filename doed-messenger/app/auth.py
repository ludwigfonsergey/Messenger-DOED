from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from jose import JWTError, jwt
import bcrypt
from . import models
from .database import SessionLocal, get_db
from typing import Optional
import os
import re
from dotenv import load_dotenv

load_dotenv()

# Настройки JWT
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

router = APIRouter()

def verify_password(plain_password, hashed_password):
    """Проверяет соответствие пароля хешу"""
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except:
        return False

def get_password_hash(password):
    """Хеширует пароль (без ограничений по длине)"""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Создает JWT токен"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def validate_tag(tag: str):
    """Проверяет, что тег содержит только латинские буквы, цифры и нижнее подчеркивание"""
    if not tag:
        return False
    if tag.startswith('@'):
        tag = tag[1:]
    return bool(re.match('^[a-zA-Z0-9_]+$', tag))

@router.post("/register")
async def register(
    username: str = Form(...),
    tag: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    """Регистрация нового пользователя"""
    try:
        # Очищаем тег
        if tag.startswith('@'):
            tag = tag[1:]
        
        # Валидация тега
        if not validate_tag(tag):
            return RedirectResponse(url="/?error=tag_invalid", status_code=303)
        
        # Проверяем существование
        db_user = db.query(models.User).filter(
            (models.User.username == username) | 
            (models.User.email == email) |
            (models.User.tag == tag)
        ).first()
        
        if db_user:
            return RedirectResponse(url="/?error=exists", status_code=303)
        
        # Создаем пользователя
        hashed_password = get_password_hash(password)
        new_user = models.User(
            username=username,
            tag=tag,
            email=email,
            hashed_password=hashed_password
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        # Сразу логиним после регистрации
        access_token = create_access_token(data={"sub": new_user.username})
        response = RedirectResponse(url="/chat", status_code=303)
        response.set_cookie(
            key="access_token", 
            value=f"Bearer {access_token}", 
            httponly=True,
            max_age=1800,  # 30 минут
            expires=1800,
            path="/"
        )
        return response
        
    except Exception as e:
        print(f"Registration error: {e}")
        return RedirectResponse(url="/?error=invalid", status_code=303)

@router.post("/login")
async def login(
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    """Вход в систему"""
    try:
        # Очищаем входные данные
        login_input = username.strip()
        if login_input.startswith('@'):
            login_input = login_input[1:]
        
        print(f"Login attempt: {login_input}")  # Для отладки
        
        # Ищем пользователя
        user = db.query(models.User).filter(
            (models.User.username == login_input) | (models.User.tag == login_input)
        ).first()
        
        if not user:
            print(f"User not found: {login_input}")
            return RedirectResponse(url="/?error=invalid", status_code=303)
        
        # Проверяем пароль
        if not verify_password(password, user.hashed_password):
            print(f"Invalid password for user: {login_input}")
            return RedirectResponse(url="/?error=invalid", status_code=303)
        
        # Создаем токен
        access_token = create_access_token(data={"sub": user.username})
        
        response = RedirectResponse(url="/chat", status_code=303)
        response.set_cookie(
            key="access_token", 
            value=f"Bearer {access_token}", 
            httponly=True,
            max_age=1800,  # 30 минут
            expires=1800,
            path="/"
        )
        print(f"Login successful: {user.username}")
        return response
        
    except Exception as e:
        print(f"Login error: {e}")
        return RedirectResponse(url="/?error=invalid", status_code=303)

@router.get("/logout")
async def logout():
    """Выход из системы"""
    response = RedirectResponse(url="/")
    response.delete_cookie("access_token", path="/")
    return response

@router.get("/api/user/{identifier}")
async def get_user_by_identifier(
    identifier: str,
    db: Session = Depends(get_db)
):
    """Поиск пользователя по username или tag"""
    try:
        if identifier.startswith('@'):
            identifier = identifier[1:]
        
        user = db.query(models.User).filter(
            (models.User.username == identifier) | (models.User.tag == identifier)
        ).first()
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        return {
            "id": user.id,
            "username": user.username,
            "tag": user.tag,
            "status": user.status,
            "avatar": user.avatar
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/debug/users")
async def debug_users(db: Session = Depends(get_db)):
    """Для отладки - посмотреть всех пользователей"""
    users = db.query(models.User).all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "tag": u.tag,
            "email": u.email,
            "hashed_password": u.hashed_password[:20] + "..."
        }
        for u in users
    ]