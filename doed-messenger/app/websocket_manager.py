from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Cookie
from typing import Dict, List, Optional
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from .database import SessionLocal, get_db
from . import models
import json
import os
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this")
ALGORITHM = "HS256"

class ConnectionManager:
    def __init__(self):
        # Словарь: {user_id: websocket}
        self.active_connections: Dict[int, WebSocket] = {}
        # Словарь: {user_id: username}
        self.active_users: Dict[int, str] = {}
    
    async def connect(self, websocket: WebSocket, user_id: int, username: str):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        self.active_users[user_id] = username
        print(f"User {username} (ID: {user_id}) connected")
    
    def disconnect(self, user_id: int):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        if user_id in self.active_users:
            del self.active_users[user_id]
        print(f"User ID {user_id} disconnected")
    
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
    
    await manager.connect(websocket, user.id, user.username)
    
    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            
            print(f"Received message: {message_data}")  # Отладка
            
            receiver_id = message_data.get("receiver_id")
            content = message_data.get("content")
            
            if not receiver_id or not content:
                continue
            
            # Сохраняем сообщение в БД
            new_message = models.Message(
                sender_id=user.id,
                receiver_id=receiver_id,
                content=content
            )
            db.add(new_message)
            db.commit()
            db.refresh(new_message)
            
            # Получаем информацию об отправителе
            sender = user
            
            # Формируем сообщение для отправки
            message_to_send = {
                "type": "new_message",
                "id": new_message.id,
                "sender_id": sender.id,
                "sender_name": sender.username,
                "sender_tag": sender.tag,
                "content": content,
                "timestamp": new_message.timestamp.isoformat()
            }
            
            print(f"Sending to user {receiver_id}: {message_to_send}")  # Отладка
            
            # Отправляем получателю
            sent = await manager.send_personal_message(message_to_send, receiver_id)
            
            # Если получатель не в сети, сообщение сохранится в БД и будет доставлено позже
            if not sent:
                print(f"User {receiver_id} is offline, message saved to DB")
            
            # Отправляем подтверждение отправителю
            await manager.send_personal_message({
                "type": "message_sent",
                "id": new_message.id,
                "content": content,
                "receiver_id": receiver_id
            }, user.id)
            
    except WebSocketDisconnect:
        manager.disconnect(user.id)
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        db.close()