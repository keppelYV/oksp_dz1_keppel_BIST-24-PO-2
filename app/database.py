import time
from contextvars import ContextVar
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
metrics_var: ContextVar[dict | None] = ContextVar('metrics_var', default=None)


@event.listens_for(engine, 'before_cursor_execute')
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    context._started_at = time.perf_counter()


@event.listens_for(engine, 'after_cursor_execute')
def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    metrics = metrics_var.get()
    if metrics is not None:
        metrics['sql_ms'] += (time.perf_counter() - context._started_at) * 1000
        metrics['query_count'] += 1


def get_db():
    with Session(engine) as session:
        yield session
