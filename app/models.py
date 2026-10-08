from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from app.config import DB_SCHEMA


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    __table_args__ = {'schema': DB_SCHEMA}
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80))
    display_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20))


class Category(Base):
    __tablename__ = 'categories'
    __table_args__ = {'schema': DB_SCHEMA}
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    sla_minutes: Mapped[int] = mapped_column(Integer)


class Ticket(Base):
    __tablename__ = 'tickets'
    __table_args__ = {'schema': DB_SCHEMA}
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey(f'{DB_SCHEMA}.users.id'))
    category_id: Mapped[int] = mapped_column(ForeignKey(f'{DB_SCHEMA}.categories.id'))
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Comment(Base):
    __tablename__ = 'comments'
    __table_args__ = {'schema': DB_SCHEMA}
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey(f'{DB_SCHEMA}.tickets.id'))
    author_id: Mapped[int] = mapped_column(ForeignKey(f'{DB_SCHEMA}.users.id'))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
