from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models
from jose import JWTError, jwt
import os
from dotenv import load_dotenv

load_dotenv()

router = APIRouter(prefix="/api/messages", tags=["reports"])

SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this")
ALGORITHM = "HS256"

@router.post("/report")
async def report_message(
    request: Request,
    report_data: dict,
    db: Session = Depends(get_db)
):
    """Пожаловаться на сообщение"""
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        token = token.replace("Bearer ", "")
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        user = db.query(models.User).filter(models.User.username == username).first()
        
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        
        message_id = report_data.get("message_id")
        reason = report_data.get("reason")
        
        if not message_id or not reason:
            raise HTTPException(status_code=400, detail="Missing data")
        
        message = db.query(models.Message).filter(models.Message.id == message_id).first()
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
        
        # Проверяем, не жаловался ли уже этот пользователь
        existing = db.query(models.Report).filter(
            models.Report.message_id == message_id,
            models.Report.reporter_id == user.id
        ).first()
        
        if existing:
            raise HTTPException(status_code=400, detail="You already reported this message")
        
        new_report = models.Report(
            message_id=message_id,
            reporter_id=user.id,
            reported_id=message.sender_id,
            reason=reason,
            status="pending"
        )
        db.add(new_report)
        db.commit()
        
        return {"status": "ok", "message": "Report sent"}
        
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as e:
        print(f"Report error: {e}")
        raise HTTPException(status_code=500, detail=str(e))