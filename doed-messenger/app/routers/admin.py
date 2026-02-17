from fastapi import APIRouter, Depends, HTTPException, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_
from typing import Optional
from app.database import get_db
from app import models
from jose import JWTError, jwt
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="templates")

SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this")
ALGORITHM = "HS256"

ADMIN_EMAIL = "sergeykatkov213@gmail.com"

def get_current_admin(request: Request, db: Session = Depends(get_db)):
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
        
        if user and user.email == ADMIN_EMAIL:
            if not user.is_admin:
                user.is_admin = True
                db.commit()
                print(f"👑 Admin rights granted to {user.username}")
            return user
        return None
    except JWTError:
        return None

@router.get("/", response_class=HTMLResponse)
async def admin_panel(
    request: Request,
    db: Session = Depends(get_db)
):
    """Главная страница админ-панели"""
    admin = get_current_admin(request, db)
    if not admin:
        return RedirectResponse(url="/")
    
    total_users = db.query(models.User).count()
    total_messages = db.query(models.Message).count()
    total_reports = db.query(models.Report).count()
    pending_reports = db.query(models.Report).filter(models.Report.status == "pending").count()
    muted_users = db.query(models.User).filter(models.User.can_only_write_bots == True).count()
    banned_users = db.query(models.User).filter(models.User.status == "заблокирован").count()
    
    recent_reports = db.query(models.Report).order_by(desc(models.Report.created_at)).limit(10).all()
    
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "admin": admin,
        "total_users": total_users,
        "total_messages": total_messages,
        "total_reports": total_reports,
        "pending_reports": pending_reports,
        "muted_users": muted_users,
        "banned_users": banned_users,
        "recent_reports": recent_reports
    })

@router.get("/users", response_class=HTMLResponse)
async def admin_users(
    request: Request,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Список всех пользователей"""
    admin = get_current_admin(request, db)
    if not admin:
        return RedirectResponse(url="/")
    
    query = db.query(models.User)
    if search:
        query = query.filter(
            or_(
                models.User.username.contains(search),
                models.User.tag.contains(search),
                models.User.email.contains(search)
            )
        )
    
    users = query.order_by(models.User.id).all()
    
    return templates.TemplateResponse("admin_users.html", {
        "request": request,
        "admin": admin,
        "users": users,
        "search": search
    })

@router.get("/messages", response_class=HTMLResponse)
async def admin_messages(
    request: Request,
    user_id: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    """Просмотр всех сообщений"""
    admin = get_current_admin(request, db)
    if not admin:
        return RedirectResponse(url="/")
    
    query = db.query(models.Message).order_by(desc(models.Message.timestamp))
    
    if user_id:
        query = query.filter(
            or_(
                models.Message.sender_id == user_id,
                models.Message.receiver_id == user_id
            )
        )
    
    messages = query.limit(200).all()
    
    users = db.query(models.User).all()
    user_dict = {user.id: user for user in users}
    
    return templates.TemplateResponse("admin_messages.html", {
        "request": request,
        "admin": admin,
        "messages": messages,
        "users": users,
        "user_dict": user_dict,
        "selected_user": user_id
    })

@router.get("/reports", response_class=HTMLResponse)
async def admin_reports(
    request: Request,
    status: Optional[str] = "pending",
    db: Session = Depends(get_db)
):
    """Список жалоб с контекстом"""
    admin = get_current_admin(request, db)
    if not admin:
        return RedirectResponse(url="/")
    
    query = db.query(models.Report).order_by(desc(models.Report.created_at))
    
    if status and status != "all":
        query = query.filter(models.Report.status == status)
    
    reports = query.all()
    
    # Для каждой жалобы получаем контекст (сообщения до и после)
    for report in reports:
        # Получаем 5 сообщений до и после
        context_messages = db.query(models.Message).filter(
            models.Message.sender_id.in_([report.reporter_id, report.reported_id]),
            models.Message.timestamp.between(
                report.message.timestamp - timedelta(minutes=30),
                report.message.timestamp + timedelta(minutes=30)
            )
        ).order_by(models.Message.timestamp).limit(20).all()
        
        report.context = context_messages
    
    return templates.TemplateResponse("admin_reports.html", {
        "request": request,
        "admin": admin,
        "reports": reports,
        "current_status": status
    })

@router.post("/reports/{report_id}/review")
async def review_report(
    report_id: int,
    request: Request,
    action: str = Form(...),
    mute_minutes: Optional[int] = Form(10),
    db: Session = Depends(get_db)
):
    """Рассмотреть жалобу"""
    admin = get_current_admin(request, db)
    if not admin:
        raise HTTPException(status_code=401, detail="Not authorized")
    
    report = db.query(models.Report).filter(models.Report.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    print(f"📋 Processing report {report_id} with action: {action}")
    
    if action == "approve":
        report.status = "reviewed"
        print(f"✅ Report {report_id} approved")
        
    elif action == "reject":
        report.status = "rejected"
        print(f"❌ Report {report_id} rejected")
        
    elif action == "mute":
        report.status = "muted"
        report.mute_duration = mute_minutes
        
        # Мут пользователя - может писать только ботам
        user = db.query(models.User).filter(models.User.id == report.reported_id).first()
        if user:
            user.can_only_write_bots = True
            user.muted_until = datetime.utcnow() + timedelta(minutes=mute_minutes)
            user.status = f"мут {mute_minutes} мин"
            db.commit()
            print(f"🔇 User {user.username} (ID: {user.id}) muted for {mute_minutes} minutes until {user.muted_until}")
            
            # Проверяем, что изменения применились
            db.refresh(user)
            print(f"   Status: {user.status}, can_only_write_bots: {user.can_only_write_bots}, muted_until: {user.muted_until}")
        else:
            print(f"❌ User not found for ID: {report.reported_id}")
            
    elif action == "ban":
        report.status = "banned"
        user = db.query(models.User).filter(models.User.id == report.reported_id).first()
        if user:
            # Сохраняем инфо для лога
            username = user.username
            user_id = user.id
            
            # 👻 Обновляем контакты у всех пользователей, у которых был этот человек
            contacts = db.query(models.Contact).filter(
                (models.Contact.user_id == user_id) | (models.Contact.contact_id == user_id)
            ).all()
            
            for contact in contacts:
                if contact.user_id == user_id:
                    # Это контакт, где забаненный пользователь владелец
                    db.delete(contact)
                else:
                    # Это контакт у других пользователей - переименовываем
                    contact.contact_name = "👻 ЗАБАНЕН"
            
            # Меняем статус пользователя на заблокированный (не удаляем пока)
            user.status = "заблокирован"
            user.avatar = "👻"
            user.username = "Забанен"
            user.tag = "banned"
            db.commit()
            
            print(f"🔨🔨🔨 ПОЛЬЗОВАТЕЛЬ {username} (ID: {user_id}) ЗАБАНЕН!")
            print(f"👻 Все контакты обновлены")
    
    report.reviewed_at = datetime.utcnow()
    report.reviewed_by = admin.id
    db.commit()
    
    return RedirectResponse(url="/admin/reports", status_code=303)

@router.post("/users/{user_id}/ban")
async def ban_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Забанить пользователя"""
    admin = get_current_admin(request, db)
    if not admin:
        raise HTTPException(status_code=401, detail="Not authorized")
    
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if user.email == ADMIN_EMAIL:
        raise HTTPException(status_code=400, detail="Cannot ban main admin")
    
    # Сохраняем инфо для лога
    username = user.username
    
    # 👻 Обновляем контакты у всех пользователей, у которых был этот человек
    contacts = db.query(models.Contact).filter(
        (models.Contact.user_id == user_id) | (models.Contact.contact_id == user_id)
    ).all()
    
    for contact in contacts:
        if contact.user_id == user_id:
            # Это контакт, где забаненный пользователь владелец
            db.delete(contact)
        else:
            # Это контакт у других пользователей - переименовываем
            contact.contact_name = "👻 ЗАБАНЕН"
    
    # Меняем статус пользователя на заблокированный
    user.status = "заблокирован"
    user.avatar = "👻"
    user.username = "Забанен"
    user.tag = "banned"
    db.commit()
    
    print(f"🔨🔨🔨 ПОЛЬЗОВАТЕЛЬ {username} (ID: {user_id}) ЗАБАНЕН!")
    print(f"👻 Все контакты обновлены")
    
    return RedirectResponse(url="/admin/users", status_code=303)

@router.post("/users/{user_id}/mute")
async def mute_user(
    user_id: int,
    request: Request,
    minutes: int = Form(10),
    db: Session = Depends(get_db)
):
    """Замутить пользователя (может писать только ботам)"""
    admin = get_current_admin(request, db)
    if not admin:
        raise HTTPException(status_code=401, detail="Not authorized")
    
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if user.email == ADMIN_EMAIL:
        raise HTTPException(status_code=400, detail="Cannot mute main admin")
    
    user.can_only_write_bots = True
    user.muted_until = datetime.utcnow() + timedelta(minutes=minutes)
    user.status = f"мут {minutes} мин"
    db.commit()
    
    print(f"🔇 User {user.username} manually muted for {minutes} minutes")
    
    return RedirectResponse(url="/admin/users", status_code=303)

@router.post("/users/{user_id}/unmute")
async def unmute_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Снять мут с пользователя"""
    admin = get_current_admin(request, db)
    if not admin:
        raise HTTPException(status_code=401, detail="Not authorized")
    
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.can_only_write_bots = False
    user.muted_until = None
    user.status = "в сети"
    db.commit()
    
    print(f"🔊 User {user.username} unmuted")
    
    return RedirectResponse(url="/admin/users", status_code=303)

@router.post("/users/{user_id}/unban")
async def unban_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Разбанить пользователя"""
    admin = get_current_admin(request, db)
    if not admin:
        raise HTTPException(status_code=401, detail="Not authorized")
    
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.status = "в сети"
    db.commit()
    
    print(f"🔓 User {user.username} unbanned")
    
    return RedirectResponse(url="/admin/users", status_code=303)

@router.post("/users/{user_id}/make-admin")
async def make_admin(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Сделать пользователя администратором"""
    admin = get_current_admin(request, db)
    if not admin:
        raise HTTPException(status_code=401, detail="Not authorized")
    
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if user.email == ADMIN_EMAIL:
        raise HTTPException(status_code=400, detail="User is already main admin")
    
    user.is_admin = True
    db.commit()
    
    print(f"👑 User {user.username} made admin")
    
    return RedirectResponse(url="/admin/users", status_code=303)

@router.post("/users/{user_id}/remove-admin")
async def remove_admin(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Забрать права администратора"""
    admin = get_current_admin(request, db)
    if not admin:
        raise HTTPException(status_code=401, detail="Not authorized")
    
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if user.email == ADMIN_EMAIL:
        raise HTTPException(status_code=400, detail="Cannot remove main admin")
    
    user.is_admin = False
    db.commit()
    
    print(f"⬇️ User {user.username} removed from admin")
    
    return RedirectResponse(url="/admin/users", status_code=303)

@router.get("/stats")
async def admin_stats(
    request: Request,
    db: Session = Depends(get_db)
):
    """Статистика для админа"""
    admin = get_current_admin(request, db)
    if not admin:
        raise HTTPException(status_code=401, detail="Not authorized")
    
    total_users = db.query(models.User).count()
    total_messages = db.query(models.Message).count()
    total_reports = db.query(models.Report).count()
    muted_users = db.query(models.User).filter(models.User.can_only_write_bots == True).count()
    banned_users = db.query(models.User).filter(models.User.status == "заблокирован").count()
    
    return {
        "total_users": total_users,
        "total_messages": total_messages,
        "total_reports": total_reports,
        "muted_users": muted_users,
        "banned_users": banned_users,
        "pending_reports": db.query(models.Report).filter(models.Report.status == "pending").count()
    }

@router.get("/debug/check-user/{user_id}")
async def debug_check_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Проверить статус пользователя (для отладки)"""
    admin = get_current_admin(request, db)
    if not admin:
        raise HTTPException(status_code=401, detail="Not authorized")
    
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "id": user.id,
        "username": user.username,
        "status": user.status,
        "can_only_write_bots": user.can_only_write_bots,
        "muted_until": user.muted_until.isoformat() if user.muted_until else None,
        "is_bot": user.is_bot,
        "is_admin": user.is_admin
    }