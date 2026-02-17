from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Cookie
from typing import Dict
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.database import SessionLocal, get_db
from app import models
import json
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

router = APIRouter()
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this")
ALGORITHM = "HS256"

# Список ID ботов (заполнится при запуске)
BOT_IDS = []

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, WebSocket] = {}
        self.active_users: Dict[int, str] = {}
    
    async def connect(self, websocket: WebSocket, user_id: int, username: str):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        self.active_users[user_id] = username
        print(f"✅ User {username} (ID: {user_id}) connected")
    
    def disconnect(self, user_id: int):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        if user_id in self.active_users:
            del self.active_users[user_id]
        print(f"❌ User ID {user_id} disconnected")
    
    async def send_personal_message(self, message: dict, user_id: int):
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_json(message)
                return True
            except:
                return False
        return False
    
    async def broadcast(self, message: dict, exclude_user: int = None):
        for user_id, connection in self.active_connections.items():
            if user_id != exclude_user:
                try:
                    await connection.send_json(message)
                except:
                    pass

manager = ConnectionManager()

def get_user_from_token(token: str, db: Session):
    try:
        token = token.replace("Bearer ", "")
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
        user = db.query(models.User).filter(models.User.username == username).first()
        return user
    except JWTError:
        return None

def check_user_restrictions(user: models.User, db: Session) -> tuple[bool, str]:
    """
    Проверяет ограничения пользователя
    Возвращает (разрешено, сообщение_об_ошибке)
    """
    # Проверка бана
    if user.status == "заблокирован":
        return False, "❌ ВАС ЗАБАНИЛИ НАВСЕГДА!\nАккаунт будет удалён."
    
    # Проверка мута
    if user.can_only_write_bots:
        # Проверяем, не истек ли мут
        if user.muted_until and user.muted_until < datetime.utcnow():
            # Мут истек
            user.can_only_write_bots = False
            user.muted_until = None
            user.status = "в сети"
            db.commit()
            print(f"✅ Mute expired for user {user.username}")
            return True, ""
        else:
            # Мут еще действует
            minutes_left = int((user.muted_until - datetime.utcnow()).total_seconds() / 60) if user.muted_until else 0
            return False, f"🔇 Вы в муте. Осталось {minutes_left} мин. Можно писать только ботам."
    
    return True, ""

def add_to_contacts_if_needed(db: Session, user_id: int, contact_id: int):
    """Автоматически добавляет в контакты, если ещё не добавлен"""
    if user_id == contact_id:  # Не добавляем себя
        return
    
    existing = db.query(models.Contact).filter(
        and_(
            models.Contact.user_id == user_id,
            models.Contact.contact_id == contact_id
        )
    ).first()
    
    if not existing:
        new_contact = models.Contact(
            user_id=user_id,
            contact_id=contact_id,
            contact_name=None,
            auto_added=True
        )
        db.add(new_contact)
        print(f"✅ Auto-added contact: User {user_id} -> {contact_id}")

@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    access_token: str = Cookie(None)
):
    if not access_token:
        await websocket.close(code=1008)
        return
    
    db = next(get_db())
    user = get_user_from_token(access_token, db)
    
    if not user:
        await websocket.close(code=1008)
        db.close()
        return
    
    # Загружаем ID ботов при подключении
    global BOT_IDS
    if not BOT_IDS:
        bots = db.query(models.User).filter(models.User.is_bot == True).all()
        BOT_IDS = [bot.id for bot in bots]
        print(f"🤖 Bot IDs loaded: {BOT_IDS}")
    
    await manager.connect(websocket, user.id, user.username)
    
    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            
            print(f"📨 Received message from {user.username}: {message_data}")
            
            receiver_id = message_data.get("receiver_id")
            content = message_data.get("content")
            
            if not receiver_id or not content:
                continue
            
            # 🔴 ПРОВЕРКА НА БАН - если забанен, закрываем соединение
            if user.status == "заблокирован":
                await manager.send_personal_message({
                    "type": "banned",
                    "message": "❌ ВАС ЗАБАНИЛИ НАВСЕГДА!",
                    "sound": "anvil"  # 👈 Звук наковальни
                }, user.id)
                await websocket.close()
                manager.disconnect(user.id)
                db.close()
                return
            
            # ПРОВЕРКА ОГРАНИЧЕНИЙ ПОЛЬЗОВАТЕЛЯ
            allowed, error_message = check_user_restrictions(user, db)
            if not allowed:
                await manager.send_personal_message({
                    "type": "error",
                    "message": error_message
                }, user.id)
                continue
            
            # Получаем информацию о получателе
            receiver = db.query(models.User).filter(models.User.id == receiver_id).first()
            
            if not receiver:
                await manager.send_personal_message({
                    "type": "error",
                    "message": "❌ Получатель не найден"
                }, user.id)
                continue
            
            # Проверяем, не забанен ли получатель
            if receiver.status == "заблокирован":
                await manager.send_personal_message({
                    "type": "error",
                    "message": "❌ Этот пользователь заблокирован"
                }, user.id)
                continue
            
            # ПРОВЕРКА ДЛЯ ЗАМУЧЕННЫХ ПОЛЬЗОВАТЕЛЕЙ - МОГУТ ПИСАТЬ ТОЛЬКО БОТАМ
            if user.can_only_write_bots and receiver_id not in BOT_IDS:
                minutes_left = int((user.muted_until - datetime.utcnow()).total_seconds() / 60) if user.muted_until else 0
                await manager.send_personal_message({
                    "type": "error",
                    "message": f"🔇 Вы в муте. Можете писать только ботам. Осталось: {minutes_left} мин."
                }, user.id)
                continue
            
            # АВТОМАТИЧЕСКИ ДОБАВЛЯЕМ В КОНТАКТЫ (только для реальных пользователей)
            if receiver_id not in BOT_IDS:
                add_to_contacts_if_needed(db, user.id, receiver_id)
                add_to_contacts_if_needed(db, receiver_id, user.id)
            
            # Сохраняем сообщение в БД
            new_message = models.Message(
                sender_id=user.id,
                receiver_id=receiver_id,
                content=content
            )
            db.add(new_message)
            db.commit()
            db.refresh(new_message)
            
            # Формируем сообщение для отправки
            message_to_send = {
                "type": "new_message",
                "id": new_message.id,
                "sender_id": user.id,
                "sender_name": user.username,
                "sender_tag": user.tag,
                "content": content,
                "timestamp": new_message.timestamp.isoformat()
            }
            
            print(f"📤 Sending to user {receiver_id}: {message_to_send}")
            
            # Отправляем получателю
            sent = await manager.send_personal_message(message_to_send, receiver_id)
            
            if not sent:
                print(f"⚠️ User {receiver_id} is offline, message saved to DB")
            
            # Отправляем подтверждение отправителю
            await manager.send_personal_message({
                "type": "message_sent",
                "id": new_message.id,
                "content": content,
                "receiver_id": receiver_id,
                "receiver_name": receiver.username if receiver else "Unknown"
            }, user.id)
            
    except WebSocketDisconnect:
        manager.disconnect(user.id)
        print(f"👋 User {user.username} disconnected")
    except Exception as e:
        print(f"❌ WebSocket error: {e}")
    finally:
        db.close()

@router.get("/api/bots")
async def get_bots(db: Session = Depends(get_db)):
    """Получить список всех ботов"""
    bots = db.query(models.User).filter(models.User.is_bot == True).all()
    return [
        {
            "id": bot.id,
            "username": bot.username,
            "tag": bot.tag,
            "avatar": bot.avatar
        }
        for bot in bots
    ]

@router.post("/api/bots/reload")
async def reload_bots(db: Session = Depends(get_db)):
    """Перезагрузить список ботов"""
    global BOT_IDS
    bots = db.query(models.User).filter(models.User.is_bot == True).all()
    BOT_IDS = [bot.id for bot in bots]
    return {"status": "ok", "bots": BOT_IDS}

@router.get("/api/active-users")
async def get_active_users():
    """Получить список активных пользователей"""
    return {
        "count": len(manager.active_connections),
        "users": [
            {"id": uid, "username": name} 
            for uid, name in manager.active_users.items()
        ]
    }