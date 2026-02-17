from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text, BigInteger, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    tag = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    status = Column(String, default="в сети")
    avatar = Column(String, default="👤")  # Эмодзи или путь к картинке
    avatar_type = Column(String, default="emoji")  # 'emoji' или 'image'
    avatar_url = Column(String, nullable=True)  # URL если загружено изображение
    is_admin = Column(Boolean, default=False)
    is_bot = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Поля для таймера мута
    muted_until = Column(DateTime, nullable=True)
    can_only_write_bots = Column(Boolean, default=False)
    
    # Отношения
    sent_messages = relationship("Message", foreign_keys="Message.sender_id", back_populates="sender", cascade="all, delete-orphan")
    received_messages = relationship("Message", foreign_keys="Message.receiver_id", back_populates="receiver", cascade="all, delete-orphan")
    user_contacts = relationship("Contact", foreign_keys="Contact.user_id", back_populates="user", cascade="all, delete-orphan")
    contact_of = relationship("Contact", foreign_keys="Contact.contact_id", back_populates="contact", cascade="all, delete-orphan")
    sent_reports = relationship("Report", foreign_keys="Report.reporter_id", back_populates="reporter", cascade="all, delete-orphan")
    received_reports = relationship("Report", foreign_keys="Report.reported_id", back_populates="reported", cascade="all, delete-orphan")

class Message(Base):
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    receiver_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    is_read = Column(Boolean, default=False)
    
    # Поля для файлов
    is_file = Column(Boolean, default=False)
    file_name = Column(String, nullable=True)
    file_path = Column(String, nullable=True)
    file_size = Column(BigInteger, nullable=True)
    file_type = Column(String, nullable=True)
    
    # Отношения
    sender = relationship("User", foreign_keys=[sender_id], back_populates="sent_messages")
    receiver = relationship("User", foreign_keys=[receiver_id], back_populates="received_messages")
    reports = relationship("Report", back_populates="message", cascade="all, delete-orphan")

class Contact(Base):
    __tablename__ = "contacts"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    contact_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    contact_name = Column(String, nullable=True)
    is_favorite = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    auto_added = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)  # Помечен ли как удаленный
    
    user = relationship("User", foreign_keys=[user_id], back_populates="user_contacts")
    contact = relationship("User", foreign_keys=[contact_id], back_populates="contact_of")
    
    __table_args__ = (UniqueConstraint('user_id', 'contact_id', name='unique_contact'),)

class Report(Base):
    __tablename__ = "reports"
    
    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"))
    reporter_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    reported_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    reason = Column(String, nullable=False)
    status = Column(String, default="pending")
    mute_duration = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    message = relationship("Message", back_populates="reports")
    reporter = relationship("User", foreign_keys=[reporter_id], back_populates="sent_reports")
    reported = relationship("User", foreign_keys=[reported_id], back_populates="received_reports")
    reviewer = relationship("User", foreign_keys=[reviewed_by])