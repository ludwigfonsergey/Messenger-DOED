from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from jose import JWTError, jwt
import bcrypt
from app import models
from app.database import get_db
from typing import Optional
import os
import re
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

def verify_password(plain_password, hashed_password):
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except:
        return False

def get_password_hash(password):
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def validate_tag(tag: str):
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
        # Очищаем тег от @ если пользователь ввел
        if tag.startswith('@'):
            tag = tag[1:]
        
        print(f"📝 Register attempt: username={username}, tag={tag}, email={email}")
        
        # Валидация тега
        if not validate_tag(tag):
            print(f"❌ Invalid tag: {tag}")
            return RedirectResponse(url="/?error=tag_invalid", status_code=303)
        
        # Проверяем существование
        db_user = db.query(models.User).filter(
            (models.User.username == username) | 
            (models.User.email == email) |
            (models.User.tag == tag)
        ).first()
        
        if db_user:
            print(f"❌ User exists: {db_user.username}")
            return RedirectResponse(url="/?error=exists", status_code=303)
        
        # Создаем пользователя
        hashed_password = get_password_hash(password)
        new_user = models.User(
            username=username,
            tag=tag,
            email=email,
            hashed_password=hashed_password,
            status="в сети",
            avatar="👤"
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        print(f"✅ User created: ID={new_user.id}, username={new_user.username}, tag={new_user.tag}")
        
        # Сразу логиним после регистрации
        access_token = create_access_token(data={"sub": new_user.username})
        response = RedirectResponse(url="/chat", status_code=303)
        response.set_cookie(
            key="access_token", 
            value=f"Bearer {access_token}", 
            httponly=True,
            max_age=1800,
            expires=1800,
            path="/"
        )
        
        # Проверяем, не админ ли это
        if email == "sergeykatkov213@gmail.com":
            new_user.is_admin = True
            db.commit()
            print(f"👑 Admin rights granted to {username}")
        
        return response
        
    except Exception as e:
        print(f"❌ Registration error: {e}")
        return RedirectResponse(url="/?error=invalid", status_code=303)

@router.post("/login")
async def login(
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    """Вход в систему"""
    try:
        login_input = username.strip()
        if login_input.startswith('@'):
            login_input = login_input[1:]
        
        print(f"🔑 Login attempt: {login_input}")
        
        # Ищем пользователя по username или tag
        user = db.query(models.User).filter(
            (models.User.username == login_input) | (models.User.tag == login_input)
        ).first()
        
        if not user:
            print(f"❌ User not found: {login_input}")
            return RedirectResponse(url="/?error=invalid", status_code=303)
        
        # Проверяем, не забанен ли пользователь
        if user.status == "заблокирован":
            print(f"❌ User is banned: {login_input}")
            return RedirectResponse(url="/?error=banned", status_code=303)
        
        if not verify_password(password, user.hashed_password):
            print(f"❌ Invalid password for: {login_input}")
            return RedirectResponse(url="/?error=invalid", status_code=303)
        
        # Проверяем админа при каждом входе
        if user.email == "sergeykatkov213@gmail.com" and not user.is_admin:
            user.is_admin = True
            db.commit()
            print(f"👑 Admin rights granted to {user.username} on login")
        
        access_token = create_access_token(data={"sub": user.username})
        
        response = RedirectResponse(url="/chat", status_code=303)
        response.set_cookie(
            key="access_token", 
            value=f"Bearer {access_token}", 
            httponly=True,
            max_age=1800,
            expires=1800,
            path="/"
        )
        print(f"✅ Login successful: {user.username} (ID: {user.id}, tag: @{user.tag})")
        return response
        
    except Exception as e:
        print(f"❌ Login error: {e}")
        return RedirectResponse(url="/?error=invalid", status_code=303)

@router.get("/logout")
async def logout():
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

@router.get("/api/users/search")
async def search_users(
    q: str,
    db: Session = Depends(get_db)
):
    """Поиск пользователей по части имени или тега"""
    try:
        users = db.query(models.User).filter(
            (models.User.username.contains(q)) | (models.User.tag.contains(q))
        ).limit(10).all()
        
        return [
            {
                "id": u.id,
                "username": u.username,
                "tag": u.tag,
                "status": u.status,
                "avatar": u.avatar
            }
            for u in users
        ]
    except Exception as e:
        print(f"Search error: {e}")
        return []

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
            "is_admin": u.is_admin,
            "is_bot": u.is_bot,
            "status": u.status,
            "hashed_password": u.hashed_password[:20] + "..."
        }
        for u in users
    ]