import random
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import insert, select, text, func

from app.config import DB_SCHEMA
from app.database import engine
from app.models import Base, User, Category, Ticket, Comment


SIZES = {
    'small': (50, 5, 300, 900),
    'work': (3000, 10, 75000, 225000),
}


def insert_batches(conn, table, rows, batch=1500):
    for start in range(0, len(rows), batch):
        conn.execute(insert(table), rows[start:start + batch])


def run(mode):
    if mode not in SIZES:
        raise SystemExit('Использование: python -m app.seed small | work')

    n_users, n_categories, n_tickets, n_comments = SIZES[mode]

    rng = random.Random(42)
    base = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)

    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{DB_SCHEMA}"'))

        Base.metadata.drop_all(conn)
        Base.metadata.create_all(conn)

        users = [
            {
                'id': 1,
                'username': 'staff',
                'display_name': 'Сотрудник',
                'role': 'staff'
            }
        ]

        users += [
            {
                'id': i,
                'username': f'client{i}',
                'display_name': f'Клиент {i}',
                'role': 'client'
            }
            for i in range(2, n_users + 1)
        ]

        category_names = [
            'Авторизация',
            'Оплата',
            'Доставка',
            'Ошибка приложения',
            'Консультация',
            'Личный кабинет',
            'Уведомления',
            'Подписка',
            'Возвраты',
            'Другое'
        ]

        categories = [
            {
                'id': i,
                'name': category_names[i - 1],
                'sla_minutes': 30 * i
            }
            for i in range(1, n_categories + 1)
        ]

        insert_batches(conn, User.__table__, users)
        insert_batches(conn, Category.__table__, categories)

        tickets = []
        comments = []
        comment_id = 1

        for tid in range(1, n_tickets + 1):
            uid = rng.randrange(2, n_users + 1)
            cid = rng.randrange(1, n_categories + 1)

            created = base + timedelta(minutes=tid * 3)
            time_to_reply = (tid % 6 + 1) * 23
            replied = tid % 7 != 0

            first_reply = (
                created + timedelta(minutes=time_to_reply)
                if replied else None
            )

            t_status = ('new', 'in_progress', 'closed')[tid % 3]

            tickets.append({
                'id': tid,
                'user_id': uid,
                'category_id': cid,
                'title': f'Обращение №{tid}: проблема с сервисом',
                'body': f'Описание обращения №{tid}',
                'status': t_status,
                'created_at': created,
                'updated_at': created + timedelta(minutes=5),
                'first_response_at': first_reply
            })

            for j in range(3):
                is_first_staff = replied and j == 0
                author = 1 if is_first_staff else uid

                comment_time = (
                    first_reply
                    if is_first_staff
                    else created + timedelta(minutes=j + 1)
                )

                comments.append({
                    'id': comment_id,
                    'ticket_id': tid,
                    'author_id': author,
                    'body': f'Комментарий {j + 1} к заявке {tid}',
                    'created_at': comment_time
                })

                comment_id += 1

        assert len(comments) == n_comments

        insert_batches(conn, Ticket.__table__, tickets)
        insert_batches(conn, Comment.__table__, comments)

        for table in (
            User.__table__,
            Category.__table__,
            Ticket.__table__,
            Comment.__table__
        ):
            max_id = conn.scalar(select(func.max(table.c.id)))

            conn.execute(
                text(
                    "SELECT setval("
                    "pg_get_serial_sequence(:table_name, 'id'), "
                    ":last_id, true)"
                ),
                {
                    'table_name': f'{DB_SCHEMA}.{table.name}',
                    'last_id': max_id,
                }
            )

        actual = {
            table.name: conn.scalar(
                select(func.count()).select_from(table)
            )
            for table in (
                User.__table__,
                Category.__table__,
                Ticket.__table__,
                Comment.__table__
            )
        }

    print(
        f'Наполнение {mode}, seed=42, '
        f'схема={DB_SCHEMA}: {actual}'
    )
    print('Повторный запуск даёт те же количество и содержание строк.')


if __name__ == '__main__':
    run(sys.argv[1] if len(sys.argv) > 1 else '')
