
import argparse
import json
from pathlib import Path
import statistics
import time
import requests


def percentile(items, p):
    a = sorted(items)
    k = (len(a) - 1) * p / 100
    low = int(k)
    high = min(low + 1, len(a) - 1)
    return a[low] + (a[high] - a[low]) * (k - low)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--url', default='http://localhost:8000')
    p.add_argument('--user', default='demo')
    p.add_argument('--password', default='demo123')
    p.add_argument('--label', choices=['small', 'work'], required=True)
    p.add_argument('--repeats', type=int, default=30)
    p.add_argument('--warmup', type=int, default=5)
    a = p.parse_args()
    if a.repeats < 20 or a.warmup < 1:
        raise SystemExit('Требуется >=20 повторов и обязательный прогрев.')
    s = requests.Session()
    s.auth = (a.user, a.password)
    base = a.url.rstrip('/')
    operations = [
        ('GET meta', 'GET', '/api/meta', {}),
        ('GET list', 'GET', '/api/tickets', {'params': {'page': 1, 'size': 20, 'status': 'new'}}),
        ('GET detail', 'GET', '/api/tickets/1', {}),
        ('GET summary', 'GET', '/api/summary', {}),
        ('POST ticket', 'POST', '/api/tickets', {'json': {'user_id': 2, 'category_id': 1,
            'title': 'Заявка для измерений', 'body': 'Контрольные измерения ДЗ1'}}),
        ('PATCH status', 'PATCH', '/api/tickets/1/status', {}),
        ('POST comment', 'POST', '/api/tickets/1/comments', {'json': {'author_id': 1,
            'body': 'Ответ сотрудника во время замеров'}}),
    ]
    output = {'label': a.label, 'warmup': a.warmup, 'repeats': a.repeats,
              'added_tickets': a.warmup + a.repeats,
              'added_comments': a.warmup + a.repeats,
              'operations': {}}
    for name, method, path, kwargs in operations:
        samples = []
        for i in range(a.warmup + a.repeats):
            opts = dict(kwargs)
            if name == 'PATCH status':
                opts['json'] = {'status': 'new' if i % 2 == 0 else 'in_progress'}
            t0 = time.perf_counter_ns()
            resp = s.request(method, base + path, timeout=60, **opts)
            elapsed_ms = (time.perf_counter_ns() - t0) / 1_000_000
            resp.raise_for_status()
            if i >= a.warmup:
                server = float(resp.headers['X-Server-ms'])
                db = float(resp.headers['X-DB-ms'])
                samples.append({'client_ms': elapsed_ms, 'server_ms': server, 'db_ms': db,
                                'code_ms': max(0, server - db),
                                'queries': int(resp.headers['X-DB-Queries'])})
        m = lambda field: [x[field] for x in samples]
        output['operations'][name] = {'p50': round(percentile(m('client_ms'), 50), 2),
                                      'p95': round(percentile(m('client_ms'), 95), 2),
                                      'max': round(max(m('client_ms')), 2),
                                      'server_ms': round(statistics.median(m('server_ms')), 2),
                                      'db_ms': round(statistics.median(m('db_ms')), 2),
                                      'code_ms': round(statistics.median(m('code_ms')), 2),
                                      'queries': round(statistics.median(m('queries')), 1),
                                      'raw_samples': samples}
    result_path = Path('results') / f'bench_{a.label}.json'
    result_path.parent.mkdir(exist_ok=True)
    result_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'Объём: {a.label}. Прогрев: {a.warmup}; повторов: {a.repeats}. Единицы: мс.')
    print(f'{"Операция":<17} {"p50":>8} {"p95":>8} {"max":>8} {"сервер":>8} {"БД":>8} {"код":>8} {"SQL":>5}')
    for name, r in output['operations'].items():
        print(f'{name:<17} {r["p50"]:>8.2f} {r["p95"]:>8.2f} {r["max"]:>8.2f} '
              f'{r["server_ms"]:>8.2f} {r["db_ms"]:>8.2f} {r["code_ms"]:>8.2f} {r["queries"]:>5.0f}')
    print(f'Результаты сохранены: {result_path}; операция POST добавила {a.warmup+a.repeats} заявок и столько же комментариев.')


if __name__ == '__main__':
    main()
