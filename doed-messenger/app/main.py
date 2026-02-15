from fastapi import FastAPI, Request, Depends
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from .database import engine, Base, get_db
from . import auth, websocket_manager
from .routers import messages, contacts
from sqlalchemy.orm import Session
from .models import User
from jose import JWTError, jwt
import os
from dotenv import load_dotenv

load_dotenv()

# Создаем таблицы БД
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Doed Messenger")

# Шаблоны и статика
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем роутеры
app.include_router(auth.router)
app.include_router(websocket_manager.router)
app.include_router(messages.router, prefix="/api/messages")
app.include_router(contacts.router, prefix="/api/contacts")

# Функция для получения текущего пользователя по токену
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this")
ALGORITHM = "HS256"

def get_current_user_from_cookie(request: Request, db: Session = Depends(get_db)):
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

# Страница авторизации
@app.get("/")
async def auth_page(request: Request):
    return templates.TemplateResponse("auth.html", {"request": request})

# Главная страница чата
@app.get("/chat")
async def chat_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request, db)
    if not user:
        return templates.TemplateResponse("auth.html", {"request": request, "error": "not_authenticated"})
    return templates.TemplateResponse("index.html", {"request": request, "user": user})

# API для данных пользователя
@app.get("/api/me")
async def get_me(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request, db)
    if not user:
        return {"error": "Not authenticated"}
    return {
        "id": user.id,
        "username": user.username,
        "tag": user.tag,
        "email": user.email,
        "status": user.status,
        "avatar": user.avatar
    }

# Для отладки - очистка куки
@app.get("/debug/clear-cookie")
async def clear_cookie():
    response = RedirectResponse(url="/")
    response.delete_cookie("access_token", path="/")
    return response