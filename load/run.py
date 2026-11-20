"""Ступени k6 на отдельной базе PostgreSQL в Ubuntu/WSL."""

import argparse
import csv
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen

from dotenv import dotenv_values
import psycopg
from sqlalchemy.engine import URL


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / 'load/.env.dz2'
ENV_EXAMPLE = ROOT / 'load/.env.dz2.example'
CLOCK_TICKS = os.sysconf('SC_CLK_TCK')
SAMPLE_FIELDS = [
    'epoch_ms', 'app_cpu_pct', 'db_cpu_pct', 'app_rss_mib', 'db_mib',
    'db_connections', 'db_active',
]


def output(command, **kwargs):
    return subprocess.check_output(command, cwd=ROOT, text=True, **kwargs).strip()


def config():
    env_file = ENV_FILE if ENV_FILE.exists() else ENV_EXAMPLE
    env = os.environ | dotenv_values(env_file)
    env['DATABASE_URL'] = URL.create(
        'postgresql+psycopg',
        username=env['POSTGRES_USER'],
        password=env['POSTGRES_PASSWORD'],
        host='127.0.0.1',
        port=int(env['POSTGRES_PORT']),
        database=env['POSTGRES_DB'],
    ).render_as_string(hide_password=False)
    compose = ['docker', 'compose', '--env-file', str(env_file), '-p', env['COMPOSE_PROJECT_NAME']]
    return env, compose


def db_connect(env):
    return psycopg.connect(
        host='127.0.0.1', port=env['POSTGRES_PORT'], dbname=env['POSTGRES_DB'],
        user=env['POSTGRES_USER'], password=env['POSTGRES_PASSWORD'],
        autocommit=True, application_name='dz2_monitor', connect_timeout=5,
    )


def prepare_database(env, compose):
    subprocess.run([*compose, 'up', '-d', '--wait', 'db'], cwd=ROOT, env=env, check=True)
    container = output([*compose, 'ps', '-q', 'db'], env=env)
    port = output(['docker', 'port', container, '5432/tcp'])
    if port != '127.0.0.1:' + env['POSTGRES_PORT']:
        raise RuntimeError('Порт контейнера PostgreSQL не совпадает с портом испытания.')
    db_pid = output(['docker', 'inspect', '-f', '{{.State.Pid}}', container])
    cgroup = next(
        line.split('::', 1)[1]
        for line in Path('/proc', db_pid, 'cgroup').read_text().splitlines()
        if line.startswith('0::')
    )
    return Path('/sys/fs/cgroup') / cgroup.lstrip('/')


def cgroup_cpu(cgroup):
    first = (cgroup / 'cpu.stat').read_text().splitlines()[0].split()
    return int(first[1]) / 1_000_000


def cgroup_memory(cgroup):
    current = int((cgroup / 'memory.current').read_text())
    stats = dict(line.split() for line in (cgroup / 'memory.stat').read_text().splitlines())
    return max(0, current - int(stats['inactive_file'])) / 1024**2


def process_usage(pid):
    proc = Path('/proc', str(pid))
    try:
        stat = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
        children = (proc / 'task' / str(pid) / 'children').read_text().split()
        memory = (proc / 'status').read_text().split('VmRSS:', 1)
    except FileNotFoundError:
        return 0.0, 0.0
    cpu_seconds = (int(stat[11]) + int(stat[12])) / CLOCK_TICKS
    mib = int(memory[1].split()[0]) / 1024 if len(memory) == 2 else 0.0
    for child in children:
        child_cpu, child_mib = process_usage(int(child))
        cpu_seconds += child_cpu
        mib += child_mib
    return cpu_seconds, mib


def profiled_pid(profiler):
    children = Path('/proc', str(profiler.pid), 'task', str(profiler.pid), 'children').read_text().split()
    if len(children) != 1:
        raise RuntimeError('Не удалось определить процесс Uvicorn, запущенный py-spy.')
    return int(children[0])


def snapshot(pid, cgroup):
    app_cpu, app_mem = process_usage(pid)
    return time.monotonic(), app_cpu, cgroup_cpu(cgroup), app_mem, cgroup_memory(cgroup)


def percentages(previous, current):
    dt = current[0] - previous[0]
    return tuple(max(0, (current[i] - previous[i]) * 100 / dt) for i in (1, 2))


def wait_idle(pid, cgroup):
    previous = snapshot(pid, cgroup)
    quiet = 0
    for _ in range(45):
        time.sleep(1)
        current = snapshot(pid, cgroup)
        quiet = quiet + 1 if max(percentages(previous, current)) < 5 else 0
        if quiet == 2:
            return
        previous = current
    raise RuntimeError('CPU сервиса и БД не вернулся к простою за 45 секунд.')


def collect(pid, cgroup, env, path, stop):
    with db_connect(env) as db, path.open('w', encoding='utf-8', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(SAMPLE_FIELDS)
        previous = snapshot(pid, cgroup)
        while not stop.wait(1):
            current = snapshot(pid, cgroup)
            app_cpu, db_cpu = percentages(previous, current)
            connections, active = db.execute("""
                SELECT count(*), count(*) FILTER (WHERE state = 'active')
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND backend_type = 'client backend' AND pid <> pg_backend_pid()
            """).fetchone()
            writer.writerow([
                time.time_ns() // 1_000_000, round(app_cpu, 2), round(db_cpu, 2),
                round(current[3], 2), round(current[4], 2), connections, active,
            ])
            file.flush()
            previous = current


@contextmanager
def collector(pid, cgroup, env, path):
    stop = threading.Event()
    failures = []

    def run():
        try:
            collect(pid, cgroup, env, path, stop)
        except Exception as exc:
            failures.append(exc)

    sampler = threading.Thread(target=run, name='resource-sampler')
    sampler.start()
    try:
        yield
    finally:
        stop.set()
        sampler.join()
    if failures:
        raise RuntimeError('Сбор ресурсов завершился ошибкой') from failures[0]


@contextmanager
def serve(env, args, directory):
    port = int(env['APP_PORT'])
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('127.0.0.1', port))
    command = [
        sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1',
        '--port', str(port), '--workers', str(args.workers),
    ]
    if args.profile:
        command = [
            args.py_spy, 'record', '--format', 'raw', '--rate', '31',
            '--duration', str(args.seconds + 20), '--output', str(directory / 'profile.txt'),
            '--', *command,
        ]
    with (directory / 'server.log').open('w', encoding='utf-8') as log:
        proc = subprocess.Popen(
            command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        )
        try:
            for _ in range(120):
                if proc.poll() is not None:
                    break
                try:
                    with urlopen(f'http://127.0.0.1:{port}/openapi.json', timeout=0.25) as resp:
                        if resp.status == 200:
                            break
                except (URLError, TimeoutError):
                    time.sleep(0.1)
            else:
                raise RuntimeError(f'Uvicorn недоступен. См. {directory / "server.log"}')
            if proc.poll() is not None:
                raise RuntimeError(f'Uvicorn завершился. См. {directory / "server.log"}')
            yield proc
        finally:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=15)
            except ProcessLookupError:
                proc.wait()
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()


def fields(summary, mode, seconds):
    metrics = summary['metrics']
    times = metrics[f'http_req_duration{{scenario:{mode}}}']['values']
    return {
        'p50_ms': times['med'],
        'p95_ms': times['p(95)'],
        'max_ms': times['max'],
        'error_pct': 100 * metrics[f'http_req_failed{{scenario:{mode}}}']['values']['rate'],
        'dropped': metrics.get('dropped_iterations', {}).get('values', {}).get('count', 0),
        'actual_rps': metrics['completed_in_window']['values']['count'] / seconds,
        'success_rps': metrics['successful_in_window']['values']['count'] / seconds,
        'started_ms': metrics['stage_start_epoch_ms']['values']['value'],
    }


def stage(env, cgroup, args, rate):
    directory = args.out / f'{args.mode}-{rate:03d}'
    directory.mkdir(parents=True, exist_ok=False)
    with (directory / 'seed.log').open('w', encoding='utf-8') as log:
        subprocess.run([sys.executable, '-m', 'app.seed', 'work'], env=env, cwd=ROOT, stdout=log, check=True)
    with db_connect(env) as db:
        db.execute('ANALYZE')
    print(f'{args.mode}: {rate} запрос/с, {args.seconds} с, workers={args.workers}', flush=True)
    k6_env = env | {
        'MODE': args.mode, 'RATE': str(rate), 'SECONDS_PER_STEP': str(args.seconds),
        'SUMMARY_PATH': str(directory / 'summary.json'),
    }
    with serve(env, args, directory) as proc:
        app_pid = profiled_pid(proc) if args.profile else proc.pid
        wait_idle(app_pid, cgroup)
        with collector(app_pid, cgroup, env, directory / 'resources.csv'):
            with (directory / 'k6.log').open('w', encoding='utf-8') as log:
                run = subprocess.run([
                    args.k6, 'run', '--quiet', '--no-usage-report', '--out',
                    f'json={directory / "points.jsonl"}', str(ROOT / 'load/k6.js'),
                ], cwd=ROOT, env=k6_env, stdout=log, stderr=subprocess.STDOUT)
            if run.returncode not in (0, 99):
                raise RuntimeError(f'k6 завершился с кодом {run.returncode}. См. {directory / "k6.log"}')
            if args.profile:
                if proc.wait(timeout=20) != 0:
                    raise RuntimeError(f'py-spy завершился с ошибкой. См. {directory / "server.log"}')
            summary = json.loads((directory / 'summary.json').read_text(encoding='utf-8'))
            row = {'mode': args.mode, 'rate': rate, 'seconds': args.seconds, 'workers': args.workers}
            row.update(fields(summary, args.mode, args.seconds))
            row['passed'] = row['p95_ms'] < 500 and row['error_pct'] < 1
            if not args.profile:
                try:
                    wait_idle(app_pid, cgroup)
                except RuntimeError:
                    row['cooldown_status'] = 'cpu_not_idle_after_45s'

    (directory / 'stage.json').write_text(json.dumps(row, indent=2), encoding='utf-8')
    print(f'  p95={row["p95_ms"]:.1f} ms, ошибок={row["error_pct"]:.2f}%, '
          f'пропущено={row["dropped"]}, факт={row["actual_rps"]:.2f} запрос/с, '
          f'успешно={row["success_rps"]:.2f} запрос/с. '
          + ('Порог выполнен.' if row['passed'] else 'Порог нарушен.'), flush=True)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['mixed', 'heavy'])
    parser.add_argument('--rates', type=int, nargs='+', required=True)
    parser.add_argument('--seconds', type=int, default=30)
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--profile', action='store_true')
    args = parser.parse_args()
    if args.seconds < 1 or args.workers < 1 or min(args.rates) < 1:
        parser.error('Частота, длительность и число процессов должны быть положительными.')
    if args.profile and (args.mode != 'heavy' or len(args.rates) != 1 or args.workers != 1):
        parser.error('Профиль снимается на одной ступени heavy с одним рабочим процессом.')
    args.out = args.out.resolve()
    args.k6 = os.environ.get('K6_BIN', shutil.which('k6'))
    args.py_spy = os.environ.get('PY_SPY_BIN', shutil.which('py-spy'))
    if not args.k6 or (args.profile and not args.py_spy):
        parser.error('Укажите установленный k6 и, для --profile, py-spy.')

    env, compose = config()
    cgroup = prepare_database(env, compose)
    previous = None
    for rate in args.rates:
        row = stage(env, cgroup, args, rate)
        if row.get('cooldown_status'):
            print('Серия завершена: процессор оставался занят через 45 секунд после прогона.')
            break
        if args.mode == 'mixed' and not row['passed']:
            break
        if args.mode == 'heavy' and previous and not row['passed']:
            prev_rps = previous['success_rps']
            if prev_rps > 0 and row['success_rps'] <= 1.1 * prev_rps:
                print('Полезная частота не выросла более чем на 10% на следующей ступени.')
                break
        previous = row


if __name__ == '__main__':
    main()
