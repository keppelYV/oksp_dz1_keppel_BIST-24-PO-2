# Сервис заявок в службу поддержки

ДЗ №1 по дисциплине «Оптимизация клиент-серверных приложений», вариант 2.

Небольшой сервис для работы с обращениями: можно создать заявку, изменить её статус, оставить комментарий и посмотреть статистику по категориям. Для каждой категории задан срок первого ответа сотрудника (SLA); в сводке видно, сколько заявок открыто и где срок нарушен.

Стек: Python, FastAPI, SQLAlchemy, PostgreSQL 16, HTML/JavaScript. База запускается через Docker Compose.

## Запуск

Понадобятся Python 3.12+ с `venv`, Docker и Docker Compose. Проект запускался в Ubuntu (WSL) с Python 3.14.4.

В корне проекта:

```bash
cp .env.example .env
nano .env
```

В `.env` нужно указать личный префикс латиницей. Для этого проекта используются следующие значения:

```dotenv
COMPOSE_PROJECT_NAME=keppel_yura
POSTGRES_DB=keppel_yura_db
POSTGRES_USER=app
POSTGRES_PASSWORD=changeme
DB_SCHEMA=keppel_yura
DATABASE_URL=postgresql+psycopg://app:changeme@localhost:5432/keppel_yura_db
DEMO_USERNAME=demo
DEMO_PASSWORD=demo123
APP_PORT=8000
```

Пароль `changeme` приведён для локального запуска. Если меняется пароль PostgreSQL, его нужно заменить и в `DATABASE_URL`.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

docker compose up -d db
docker compose ps
python -m app.seed small
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Команда наполнения сама создаёт схему и таблицы. После запуска сайт доступен по адресу http://localhost:8000. Браузер запросит логин и пароль из `.env` (в примере `demo` / `demo123`). Есть три страницы: список заявок, карточка и сводка.

Документация API: http://localhost:8000/docs.

## Проверка

Откройте второй терминал в папке проекта и активируйте окружение:

```bash
source .venv/bin/activate
pytest -q
```

Для быстрой проверки работающего API:

```bash
curl -u demo:demo123 'http://localhost:8000/api/tickets?page=1&size=3'
curl -u demo:demo123 'http://localhost:8000/api/tickets/1'
curl -u demo:demo123 'http://localhost:8000/api/summary'
```

Без авторизации API возвращает `401`, при неверных параметрах — `422`. Тесты запускаются отдельно от сервера и работают с тестовой базой SQLite в памяти.

## Наполнение базы

```bash
python -m app.seed small
python -m app.seed work
```

| Таблица | Малое | Рабочее |
| --- | ---: | ---: |
| `users` | 50 | 3 000 |
| `categories` | 5 | 10 |
| `tickets` | 300 | 75 000 |
| `comments` | 900 | 225 000 |

Генератор использует `seed=42`, поэтому повторное наполнение создаёт те же данные. **Обе команды пересоздают таблицы в схеме `DB_SCHEMA`**: изменения, сделанные через интерфейс, при этом пропадут.

## Замеры времени ответа

Сервер должен быть запущен. Сначала измеряем малый объём, потом рабочий:

```bash
python -m app.seed small
python -m tools.bench --label small

python -m app.seed work
python -m tools.bench --label work

python -m tools.compare
```

Для каждой из семи операций выполняются 5 прогревочных запросов и 30 измерений. Скрипт выводит `p50`, `p95`, максимум, серверное время, время SQL и число SQL-запросов. Результаты сохраняются в `results/bench_small.json` и `results/bench_work.json`; эта папка не включается в репозиторий.

В каждом прогоне операции записи дополнительно создают 35 заявок и 35 комментариев, включая прогрев. Поэтому перед повторным замером лучше снова выполнить `app.seed`.

Для разложения времени используются заголовки `X-Server-ms`, `X-DB-ms` и `X-DB-Queries`. Время SQL учитывает выполнение запроса, но не всю последующую обработку полученных строк.

Если меняли `DEMO_USERNAME` или `DEMO_PASSWORD`, передайте их скрипту измерений через `--user` и `--password`.

## API

Все операции требуют HTTP Basic-авторизацию.

| Метод и путь | Параметры | Результат | Ошибки |
| --- | --- | --- | --- |
| `GET /api/meta` | — | Пользователи и категории | 401 |
| `GET /api/tickets` | `page`, `size`, `status`, `category_id` | Список и общее количество | 401, 422 |
| `GET /api/tickets/{id}` | ID заявки | Заявка, комментарии, SLA | 401, 404 |
| `POST /api/tickets` | `user_id`, `category_id`, `title`, `body` | Созданная заявка (`201`) | 401, 404, 422 |
| `PATCH /api/tickets/{id}/status` | `status` | Обновлённая заявка | 401, 404, 422 |
| `POST /api/tickets/{id}/comments` | `author_id`, `body` | Новый комментарий (`201`) | 401, 404, 422 |
| `GET /api/summary` | — | Статистика по категориям | 401 |

Статусы заявок: `new`, `in_progress`, `closed`. Время первого ответа фиксируется при первом комментарии сотрудника. Открытыми считаются заявки со статусами `new` и `in_progress`.



Остановить базу можно командой `docker compose down`. Данные  останутся в Docker volume.
 Команда `docker compose down -v` удаляет и volume с базой.
