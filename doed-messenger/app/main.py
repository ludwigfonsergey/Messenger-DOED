from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, Base, get_db
from app import auth, websocket_manager
from app.routers import messages, contacts, files, admin, reports, users
from sqlalchemy.orm import Session
from app.models import User
from jose import JWTError, jwt
import os
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime

load_dotenv()

# Создаем папки
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

AVATAR_DIR = Path("static/avatars")
AVATAR_DIR.mkdir(parents=True, exist_ok=True)

# Создаем таблицы БД
Base.metadata.create_all(bind=engine)

# Функция для проверки и назначения админа
def ensure_admin_exists():
    """Проверяет и назначает админа для указанной почты"""
    db = next(get_db())
    try:
        admin_email = "sergeykatkov213@gmail.com"
        user = db.query(User).filter(User.email == admin_email).first()
        
        if user:
            if not user.is_admin:
                user.is_admin = True
                db.commit()
                print(f"✅ Админ права назначены для {user.username} ({user.email})")
            else:
                print(f"✅ Пользователь {user.username} уже является админом")
        else:
            print(f"❌ Пользователь с email {admin_email} не найден")
            print("   Зарегистрируйтесь с этим email чтобы стать админом")
    except Exception as e:
        print(f"❌ Ошибка при проверке админа: {e}")
    finally:
        db.close()

# Функция для создания ботов
def create_bots_if_not_exists():
    """Создает демо-ботов в базе данных"""
    db = next(get_db())
    
    bots = [
        {"username": "Чеченский чат", "tag": "chechen_bot", "email": "chechen@doed.local", "avatar": "🇷🇺"},
        {"username": "Vernam AI", "tag": "vernam_bot", "email": "vernam@doed.local", "avatar": "🤖"},
        {"username": "Сглыпа", "tag": "sglypa_bot", "email": "sglypa@doed.local", "avatar": "👺"},
        {"username": "Eiriley", "tag": "eiriley_bot", "email": "eiriley@doed.local", "avatar": "🧠"},
        {"username": "Дольфи", "tag": "dolfi_bot", "email": "dolfi@doed.local", "avatar": "🐬"},
        {"username": "Derd", "tag": "derd_bot", "email": "derd@doed.local", "avatar": "🎮"},
        {"username": "Doed", "tag": "doed_bot", "email": "doed@doed.local", "avatar": "👿"},
        {"username": "Канал В.В.Путина", "tag": "putin_bot", "email": "putin@doed.local", "avatar": "🇷🇺"},
        {"username": "ГЭМДЭ НЬЮС", "tag": "gmd_bot", "email": "gmd@doed.local", "avatar": "📰"},
        {"username": "Федя Букер", "tag": "booker_bot", "email": "booker@doed.local", "avatar": "🎤"},
    ]
    
    created_count = 0
    for bot_data in bots:
        try:
            # Проверяем, нет ли уже такого бота
            bot = db.query(User).filter(
                (User.tag == bot_data["tag"]) | (User.email == bot_data["email"])
            ).first()
            
            if not bot:
                bot = User(
                    username=bot_data["username"],
                    tag=bot_data["tag"],
                    email=bot_data["email"],
                    hashed_password="bot_password_123",
                    avatar=bot_data["avatar"],
                    avatar_type="emoji",
                    is_bot=True,
                    status="бот в сети"
                )
                db.add(bot)
                created_count += 1
                print(f"✅ Создан бот: {bot_data['username']}")
        except Exception as e:
            print(f"❌ Ошибка при создании бота {bot_data['username']}: {e}")
    
    if created_count > 0:
        try:
            db.commit()
            print(f"✅ {created_count} ботов успешно создано")
        except Exception as e:
            print(f"❌ Ошибка при сохранении ботов: {e}")
    else:
        print("✅ Все боты уже существуют")
    
    db.close()

# Вызываем функции создания
print("\n" + "="*60)
print(" " * 15 + "🔴 DOED MESSENGER")
print("="*60)
ensure_admin_exists()
create_bots_if_not_exists()
print("="*60)
print(" " * 18 + "ГОТОВ К РАБОТЕ")
print("="*60 + "\n")

app = FastAPI(
    title="Doed Messenger",
    description="Мессенджер с красным акцентом",
    version="2.0.0"
)

# Шаблоны и статика
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем все роутеры
app.include_router(auth.router)                       # Маршруты авторизации
app.include_router(websocket_manager.router)          # WebSocket соединения
app.include_router(messages.router, prefix="/api/messages")   # История сообщений
app.include_router(contacts.router)                   # 👈 Управление контактами (без префикса, он уже в router)
app.include_router(files.router, prefix="/api/files") # Загрузка файлов
app.include_router(admin.router)                      # Админ-панель
app.include_router(reports.router)                    # Жалобы на сообщения
app.include_router(users.router)                      # 👈 Новый роутер для пользователей

SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this")
ALGORITHM = "HS256"

def get_current_user_from_cookie(request: Request, db: Session = Depends(get_db)):
    """Получает текущего пользователя из куки"""
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        token = token.replace("Bearer ", "")
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            return None
        user = db.query(User).filter(User.username == username).first()
        return user
    except JWTError:
        return None

@app.get("/")
async def auth_page(request: Request):
    """Страница авторизации"""
    return templates.TemplateResponse("auth.html", {"request": request})

@app.get("/chat")
async def chat_page(request: Request, db: Session = Depends(get_db)):
    """Главная страница чата"""
    user = get_current_user_from_cookie(request, db)
    if not user:
        return templates.TemplateResponse("auth.html", {"request": request, "error": "not_authenticated"})
    
    # Проверяем админа при каждом входе
    if user.email == "sergeykatkov213@gmail.com" and not user.is_admin:
        user.is_admin = True
        db.commit()
        print(f"👑 Админ права назначены для {user.username} при входе")
    
    # Проверяем, не забанен ли пользователь
    if user.status == "заблокирован":
        response = templates.TemplateResponse("auth.html", {
            "request": request, 
            "error": "banned",
            "message": "❌ ВАС ЗАБАНИЛИ НАВСЕГДА! Аккаунт удалён."
        })
        response.delete_cookie("access_token", path="/")
        return response
    
    return templates.TemplateResponse("index.html", {"request": request, "user": user})

@app.get("/api/me")
async def get_me(request: Request, db: Session = Depends(get_db)):
    """Получить информацию о текущем пользователе"""
    user = get_current_user_from_cookie(request, db)
    if not user:
        return {"error": "Not authenticated"}
    
    # Проверяем, не забанен ли пользователь
    if user.status == "заблокирован":
        return {"error": "banned", "message": "❌ ВАС ЗАБАНИЛИ НАВСЕГДА!"}
    
    # Проверяем, не истек ли мут
    if user.can_only_write_bots and user.muted_until:
        if user.muted_until < datetime.utcnow():
            user.can_only_write_bots = False
            user.muted_until = None
            user.status = "в сети"
            db.commit()
            print(f"✅ Мут истек для пользователя {user.username}")
    
    print(f"👤 Данные пользователя: {user.username}, ID: {user.id}, тег: @{user.tag}, админ: {user.is_admin}")
    
    return {
        "id": user.id,
        "username": user.username,
        "tag": user.tag,
        "email": user.email,
        "status": user.status,
        "avatar": user.avatar,
        "avatar_type": user.avatar_type,
        "avatar_url": user.avatar_url,
        "is_admin": user.is_admin,
        "is_bot": user.is_bot,
        "can_only_write_bots": user.can_only_write_bots,
        "muted_until": user.muted_until.isoformat() if user.muted_until else None
    }

@app.get("/api/bots")
async def get_bots(db: Session = Depends(get_db)):
    """Получить список всех ботов"""
    bots = db.query(User).filter(User.is_bot == True).all()
    return [
        {
            "id": bot.id,
            "username": bot.username,
            "tag": bot.tag,
            "avatar": bot.avatar,
            "avatar_type": bot.avatar_type,
            "avatar_url": bot.avatar_url,
            "status": bot.status
        }
        for bot in bots
    ]

@app.get("/debug/check-cookie")
async def check_cookie(request: Request):
    """Проверить наличие куки"""
    token = request.cookies.get("access_token")
    return {
        "has_cookie": token is not None,
        "cookie_value": token[:20] + "..." if token and len(token) > 20 else token
    }

@app.get("/debug/users")
async def debug_users(db: Session = Depends(get_db)):
    """Для отладки - посмотреть всех пользователей"""
    users = db.query(User).all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "tag": u.tag,
            "email": u.email,
            "is_admin": u.is_admin,
            "is_bot": u.is_bot,
            "status": u.status,
            "avatar": u.avatar,
            "avatar_type": u.avatar_type,
            "avatar_url": u.avatar_url,
            "can_only_write_bots": u.can_only_write_bots,
            "muted_until": u.muted_until.isoformat() if u.muted_until else None
        }
        for u in users
    ]

@app.get("/debug/clear-cookie")
async def clear_cookie():
    """Очистить куку авторизации (для отладки)"""
    response = RedirectResponse(url="/")
    response.delete_cookie("access_token", path="/")
    return response

@app.get("/debug/reset-mutes")
async def reset_all_mutes(request: Request, db: Session = Depends(get_db)):
    """Сбросить все муты (для админов)"""
    user = get_current_user_from_cookie(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    muted_users = db.query(User).filter(User.can_only_write_bots == True).all()
    for muted_user in muted_users:
        muted_user.can_only_write_bots = False
        muted_user.muted_until = None
        muted_user.status = "в сети"
    
    db.commit()
    return {"status": "ok", "reset_count": len(muted_users)}

@app.get("/debug/make-me-admin")
async def make_me_admin(request: Request, db: Session = Depends(get_db)):
    """Сделать текущего пользователя админом (для отладки)"""
    user = get_current_user_from_cookie(request, db)
    if not user:
        return {"error": "Not authenticated"}
    
    user.is_admin = True
    db.commit()
    return {"status": "ok", "message": f"Пользователь {user.username} теперь админ"}

@app.on_event("startup")
async def startup_event():
    """Действия при запуске сервера"""
    print("\n" + "🔥"*60)
    print("🔥" + " "*58 + "🔥")
    print("🔥" + " "*18 + "🔴 DOED MESSENGER" + " "*19 + "🔥")
    print("🔥" + " "*58 + "🔥")
    print("🔥"*60)
    print("🔥" + " "*58 + "🔥")
    print("🔥" + " "*5 + "🚀 Версия: 2.0.0" + " "*37 + "🔥")
    print("🔥" + " "*5 + f"📍 Адрес: http://localhost:8000" + " "*27 + "🔥")
    print("🔥" + " "*5 + f"👑 Админ: sergeykatkov213@gmail.com" + " "*18 + "🔥")
    print("🔥" + " "*5 + "📁 Загрузки: /uploads" + " "*33 + "🔥")
    print("🔥" + " "*5 + "🖼️ Аватарки: /static/avatars" + " "*28 + "🔥")
    print("🔥" + " "*58 + "🔥")
    print("🔥"*60 + "\n")

@app.on_event("shutdown")
async def shutdown_event():
    """Действия при остановке сервера"""
    print("\n" + "💀"*60)
    print("💀" + " "*58 + "💀")
    print("💀" + " "*15 + "🔴 DOED MESSENGER STOPPED" + " "*14 + "💀")
    print("💀" + " "*58 + "💀")
    print("💀"*60 + "\n")