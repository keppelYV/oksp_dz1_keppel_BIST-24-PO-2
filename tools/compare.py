import json
from pathlib import Path

small = json.loads(Path('results/bench_small.json').read_text(encoding='utf-8'))
work = json.loads(Path('results/bench_work.json').read_text(encoding='utf-8'))
print(f'{"Операция":<18} {"p50 малое":>12} {"p95 малое":>12} {"p50 рабочее":>14} {"p95 рабочее":>14} {"Рост p50":>11}')
for name, a in small['operations'].items():
    b = work['operations'][name]
    growth = b['p50'] / a['p50'] if a['p50'] > 0 else 0
    print(f'{name:<18} {a["p50"]:>12.2f} {a["p95"]:>12.2f} {b["p50"]:>14.2f} {b["p95"]:>14.2f} {growth:>10.2f}x')

