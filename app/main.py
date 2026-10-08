from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import secrets
import time
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import DEMO_USERNAME, DEMO_PASSWORD
from app.database import get_db, metrics_var
from app.models import Category, Comment, Ticket, User
from app.rules import VALID_STATUSES, is_sla_breached, response_minutes

app = FastAPI(title='Служба поддержки ДЗ №1', version='1.0')
auth_scheme = HTTPBasic()


def require_auth(credentials: HTTPBasicCredentials = Depends(auth_scheme)):
    valid_user = secrets.compare_digest(credentials.username.encode(), DEMO_USERNAME.encode())
    valid_password = secrets.compare_digest(credentials.password.encode(), DEMO_PASSWORD.encode())
    if not (valid_user and valid_password):
        raise HTTPException(status_code=401, detail='Неверные учётные данные',
                            headers={'WWW-Authenticate': 'Basic'})
    return credentials.username


@app.middleware('http')
async def track_requests(request, call_next):
    metrics = {'sql_ms': 0.0, 'query_count': 0}
    token = metrics_var.set(metrics)
    start = time.perf_counter()
    try:
        response = await call_next(request)
        total_ms = (time.perf_counter() - start) * 1000
        response.headers['X-Server-ms'] = f'{total_ms:.3f}'
        response.headers['X-DB-ms'] = f"{metrics['sql_ms']:.3f}"
        response.headers['X-DB-Queries'] = str(metrics['query_count'])
        return response
    finally:
        metrics_var.reset(token)


class TicketCreate(BaseModel):
    user_id: int = Field(ge=1)
    category_id: int = Field(ge=1)
    title: str = Field(min_length=3, max_length=160)
    body: str = Field(min_length=1, max_length=4000)


class StatusChange(BaseModel):
    status: Literal['new', 'in_progress', 'closed']


class CommentCreate(BaseModel):
    author_id: int = Field(ge=1)
    body: str = Field(min_length=1, max_length=4000)


def ticket_json(ticket: Ticket):
    return {'id': ticket.id, 'user_id': ticket.user_id, 'category_id': ticket.category_id,
            'title': ticket.title, 'body': ticket.body, 'status': ticket.status,
            'created_at': ticket.created_at.isoformat(),
            'first_response_at': ticket.first_response_at.isoformat() if ticket.first_response_at else None}


@app.get('/', response_class=HTMLResponse)
def home(username: str = Depends(require_auth)):
    return (Path(__file__).resolve().parent.parent / 'static' / 'index.html').read_text(encoding='utf-8')


@app.get('/api/meta')
def meta(db: Session = Depends(get_db), username: str = Depends(require_auth)):
    users = db.execute(select(User.id, User.username).order_by(User.id).limit(10)).all()
    categories = db.execute(select(Category.id, Category.name, Category.sla_minutes).order_by(Category.id)).all()
    return {'users': [{'id': x.id, 'username': x.username} for x in users],
            'categories': [{'id': x.id, 'name': x.name, 'sla_minutes': x.sla_minutes} for x in categories]}


@app.get('/api/tickets')
def get_tickets(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
                ticket_status: Literal['new', 'in_progress', 'closed'] | None = Query(None, alias='status'),
                category_id: int | None = Query(None, ge=1),
                db: Session = Depends(get_db), username: str = Depends(require_auth)):
    filters = []
    if ticket_status:
        filters.append(Ticket.status == ticket_status)
    if category_id:
        filters.append(Ticket.category_id == category_id)
    total = db.scalar(select(func.count()).select_from(Ticket).where(*filters)) or 0
    tickets = db.scalars(select(Ticket).where(*filters).order_by(Ticket.id.desc()).offset((page - 1) * size).limit(size)).all()
    return {'items': [ticket_json(t) for t in tickets], 'total': total, 'page': page, 'size': size}


@app.post('/api/tickets', status_code=201)
def create_ticket(data: TicketCreate, db: Session = Depends(get_db), username: str = Depends(require_auth)):
    if db.get(User, data.user_id) is None or db.get(Category, data.category_id) is None:
        raise HTTPException(status_code=404, detail='Пользователь или категория не найдены')
    now = datetime.now(timezone.utc)
    ticket = Ticket(user_id=data.user_id, category_id=data.category_id, title=data.title,
                    body=data.body, status='new', created_at=now, updated_at=now)
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket_json(ticket)


@app.get('/api/tickets/{ticket_id}')
def get_ticket(ticket_id: int, db: Session = Depends(get_db), username: str = Depends(require_auth)):
    item = db.execute(select(Ticket, User.username, Category.name, Category.sla_minutes)
                      .join(User, User.id == Ticket.user_id)
                      .join(Category, Category.id == Ticket.category_id)
                      .where(Ticket.id == ticket_id)).first()
    if item is None:
        raise HTTPException(status_code=404, detail='Заявка не найдена')
    ticket, owner, category, sla = item
    comments = db.execute(select(Comment, User.username)
                          .join(User, User.id == Comment.author_id)
                          .where(Comment.ticket_id == ticket_id)
                          .order_by(Comment.created_at, Comment.id)).all()
    return {**ticket_json(ticket), 'owner': owner, 'category': category,
            'sla_minutes': sla,
            'response_minutes': response_minutes(ticket.created_at, ticket.first_response_at),
            'sla_breached': is_sla_breached(ticket.created_at, ticket.first_response_at, sla),
            'comments': [{'id': c.id, 'author': author, 'body': c.body,
                          'created_at': c.created_at.isoformat()} for c, author in comments]}


@app.patch('/api/tickets/{ticket_id}/status')
def change_status(ticket_id: int, data: StatusChange, db: Session = Depends(get_db), username: str = Depends(require_auth)):
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail='Заявка не найдена')
    ticket.status = data.status
    ticket.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(ticket)
    return ticket_json(ticket)


@app.post('/api/tickets/{ticket_id}/comments', status_code=201)
def add_comment(ticket_id: int, data: CommentCreate, db: Session = Depends(get_db), username: str = Depends(require_auth)):
    ticket = db.get(Ticket, ticket_id)
    author = db.get(User, data.author_id)
    if ticket is None or author is None:
        raise HTTPException(status_code=404, detail='Заявка или автор не найдены')
    now = datetime.now(timezone.utc)
    comment = Comment(ticket_id=ticket_id, author_id=author.id, body=data.body, created_at=now)
    db.add(comment)
    if author.role == 'staff' and ticket.first_response_at is None:
        ticket.first_response_at = now
    db.commit()
    db.refresh(comment)
    return {'id': comment.id, 'ticket_id': ticket_id, 'author': author.username,
            'body': comment.body, 'created_at': comment.created_at.isoformat()}


@app.get('/api/summary')
def summary(db: Session = Depends(get_db), username: str = Depends(require_auth)):

    categories = db.scalars(select(Category).order_by(Category.id)).all()
    by_cat = {c.id: {'category_id': c.id, 'category': c.name,
                     'sla_minutes': c.sla_minutes, 'total': 0, 'open': 0,
                     'sla_violations': 0} for c in categories}
    rows = db.execute(select(Ticket.category_id, Ticket.status, Ticket.created_at, Ticket.first_response_at,
                             Category.sla_minutes).join(Category, Category.id == Ticket.category_id)).all()
    now = datetime.now(timezone.utc)
    for category_id, status_value, created_at, first_response_at, sla in rows:
        bucket = by_cat[category_id]
        bucket['total'] += 1
        if status_value != 'closed':
            bucket['open'] += 1
        if is_sla_breached(created_at, first_response_at, sla, now):
            bucket['sla_violations'] += 1
    result = []
    for row in by_cat.values():
        row['violation_share_pct'] = round(100 * row['sla_violations'] / row['total'], 2) if row['total'] else 0.0
        result.append(row)
    return {'categories': result, 'total_tickets': sum(x['total'] for x in result),
            'open_tickets': sum(x['open'] for x in result)}
