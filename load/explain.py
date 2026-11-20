"""Планы SQL для проверки гипотез о карточке и списке."""

import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys

from load.run import ROOT, config, db_connect, prepare_database


def explain(db, sql, parameters=()):
    return db.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + sql, parameters).fetchone()[0][0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    env, compose = config()
    prepare_database(env, compose)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.with_suffix('.seed.log').open('w', encoding='utf-8') as log:
        subprocess.run([sys.executable, '-m', 'app.seed', 'work'], cwd=ROOT, env=env, stdout=log, check=True)
    schema = env['DB_SCHEMA']
    comments = f'"{schema}".comments'
    tickets = f'"{schema}".tickets'
    users = f'"{schema}".users'
    plans = {}
    with db_connect(env) as db:
        db.execute('ANALYZE')
        tests = {
            'detail_comments': (
                f'SELECT c.*, u.username FROM {comments} AS c JOIN {users} AS u '
                'ON u.id = c.author_id WHERE c.ticket_id = %s ORDER BY c.created_at, c.id',
                (45001,),
            ),
            'list_count': (f'SELECT count(*) FROM {tickets} WHERE status = %s', ('new',)),
            'list_page': (
                f'SELECT * FROM {tickets} WHERE status = %s ORDER BY id DESC LIMIT 20 OFFSET 0',
                ('new',),
            ),
            'list_category_count': (
                f'SELECT count(*) FROM {tickets} WHERE status = %s AND category_id = %s',
                ('new', 1),
            ),
            'list_category_page': (
                f'SELECT * FROM {tickets} WHERE status = %s AND category_id = %s ORDER BY id DESC LIMIT 20 OFFSET 0',
                ('new', 1),
            ),
        }
        for name, (sql, params) in tests.items():
            explain(db, sql, params)
            runs = [explain(db, sql, params) for _ in range(5)]
            plans[name] = {'sql': sql, 'parameters': params, 'plans': runs}
            median_ms = statistics.median(plan['Execution Time'] for plan in runs)
            print(f'{name:24s} median={median_ms:8.3f} ms (5 записей плана)')
    args.out.write_text(json.dumps(plans, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
