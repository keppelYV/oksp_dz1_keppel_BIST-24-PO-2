import os
os.environ['DATABASE_URL'] = 'sqlite+pysqlite:///:memory:'
os.environ['DB_SCHEMA'] = 'test_schema'
os.environ['DEMO_USERNAME'] = 'demo'
os.environ['DEMO_PASSWORD'] = 'demo123'

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.database import get_db
from app.main import app
from app.models import Base, User, Category, Ticket


@pytest.fixture
def client():
    engine = create_engine('sqlite+pysqlite:///:memory:',
                           connect_args={'check_same_thread': False}, poolclass=StaticPool)
    engine = engine.execution_options(schema_translate_map={'test_schema': None})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        now = datetime(2026, 10, 1, 10, tzinfo=timezone.utc)
        session.add_all([
            User(id=1, username='staff', display_name='Сотрудник', role='staff'),
            User(id=2, username='client2', display_name='Клиент', role='client'),
            Category(id=1, name='Вопросы', sla_minutes=60),
            Ticket(id=1, user_id=2, category_id=1, title='Проблема входа', body='Не удаётся войти',
                   status='new', created_at=now, updated_at=now, first_response_at=None),
        ])
        session.commit()

    def override_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def auth():
    return ('demo', 'demo123')
