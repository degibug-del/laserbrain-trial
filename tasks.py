#!/usr/bin/env python3
"""The task set. Each task is a prompt, a workspace seed, and a verifier that decides.

WHY THE VERIFIER IS THE WHOLE DESIGN

Nothing here grades the agent's work by reading it. Every task ends in a shell command that
exits 0 or does not, because the moment a person decides what counts as finished, the trial
is measuring that person. The verifier runs in a fresh copy of the workspace after the agent
stops, and its exit code is the only outcome recorded.

Two rules each task obeys, both enforced by run_trial.py --self-test:

  IT MUST FAIL FIRST   Run the verifier on the untouched seed and it has to be non-zero. A
                       verifier that passes before any work happened measures nothing, and
                       would hand both arms a free pass — inflating the pass rate of whichever
                       arm quit earlier. This is the single most likely way for the whole
                       trial to be quietly worthless.
  IT MUST NOT BE THE PROMPT
                       The prompt says what to build; the verifier says what "built" means.
                       If the prompt quoted the assertions, the agent would satisfy the test
                       rather than the task, and both arms would pass at ceiling.

The tasks lean toward multi-step work with a natural wrong turn in it, because that is the
regime the gate claims to help with. That is a stated bias, not a hidden one — see
PREREGISTRATION.md, "What this trial cannot say."
"""

TASKS = [
    dict(
        id='parse-durations',
        prompt=(
            "In durations.py, implement parse_duration(s) -> int returning seconds. "
            "It accepts strings like '90s', '5m', '2h', '1h30m', '2d'. Whitespace is allowed "
            "anywhere. An empty or unparseable string must raise ValueError. Bare integers "
            "are seconds. Do not add dependencies."
        ),
        seed={'durations.py': 'def parse_duration(s):\n    raise NotImplementedError\n'},
        verify='''python3 - <<'EOF'
import durations as d
assert d.parse_duration('90s') == 90
assert d.parse_duration('5m') == 300
assert d.parse_duration('2h') == 7200
assert d.parse_duration('1h30m') == 5400
assert d.parse_duration('2d') == 172800
assert d.parse_duration(' 1h 30m ') == 5400
assert d.parse_duration('45') == 45
for bad in ('', 'abc', '5x', None):
    try:
        d.parse_duration(bad); raise SystemExit('accepted bad input: %r' % (bad,))
    except (ValueError, TypeError): pass
EOF''',
    ),
    dict(
        id='fix-off-by-one',
        prompt=(
            "chunk.py has a bug: chunk(seq, n) is supposed to split seq into consecutive "
            "lists of length n, with a shorter final chunk if it does not divide evenly. "
            "Find the bug and fix it. Keep the signature."
        ),
        seed={'chunk.py': (
            'def chunk(seq, n):\n'
            '    out = []\n'
            '    for i in range(0, len(seq) - n, n):\n'   # drops the tail
            '        out.append(list(seq[i:i + n]))\n'
            '    return out\n'
        )},
        verify='''python3 - <<'EOF'
from chunk import chunk
assert chunk([1,2,3,4,5,6], 2) == [[1,2],[3,4],[5,6]]
assert chunk([1,2,3,4,5], 2) == [[1,2],[3,4],[5]]
assert chunk([1,2,3], 5) == [[1,2,3]]
assert chunk([], 3) == []
assert chunk([1,2,3,4], 4) == [[1,2,3,4]]
EOF''',
    ),
    dict(
        id='csv-median',
        prompt=(
            "Write stats.py exposing column_median(path, column) -> float. It reads a CSV "
            "with a header row and returns the median of the named column. Rows where the "
            "value is missing or non-numeric are skipped. If no numeric values remain, raise "
            "ValueError. Use only the standard library."
        ),
        seed={'data.csv': 'name,score\na,10\nb,\nc,30\nd,oops\ne,20\n'},
        verify='''python3 - <<'EOF'
import stats
assert stats.column_median('data.csv', 'score') == 20
open('one.csv','w').write('name,score\\na,7\\n')
assert stats.column_median('one.csv', 'score') == 7
open('two.csv','w').write('name,score\\na,1\\nb,3\\n')
assert stats.column_median('two.csv', 'score') == 2
open('none.csv','w').write('name,score\\na,x\\n')
try:
    stats.column_median('none.csv', 'score'); raise SystemExit('no ValueError')
except ValueError: pass
EOF''',
    ),
    dict(
        id='retry-backoff',
        prompt=(
            "In retry.py implement retry(fn, attempts=3, base=0.01). Call fn(); if it raises, "
            "sleep base * 2**(attempt-1) and try again, up to `attempts` total calls. Return "
            "fn's value on success. If every attempt raises, re-raise the LAST exception. "
            "Do not sleep after the final failure."
        ),
        seed={'retry.py': 'def retry(fn, attempts=3, base=0.01):\n    raise NotImplementedError\n'},
        verify='''python3 - <<'EOF'
import time, retry as R
calls = {'n': 0}
def flaky():
    calls['n'] += 1
    if calls['n'] < 3: raise RuntimeError('boom')
    return 'ok'
assert R.retry(flaky) == 'ok' and calls['n'] == 3
class Last(Exception): pass
def always():
    raise Last('final')
t0 = time.time()
try:
    R.retry(always, attempts=3, base=0.01); raise SystemExit('should have raised')
except Last: pass
# two sleeps only (0.01 + 0.02); a sleep after the last failure would push past 0.05
assert time.time() - t0 < 0.5, 'slept after the final attempt'
assert R.retry(lambda: 42) == 42
EOF''',
    ),
    dict(
        id='merge-configs',
        prompt=(
            "Write merge.py with deep_merge(a, b) -> dict. It returns a new dict; b wins on "
            "conflicts; nested dicts merge recursively rather than being replaced; neither "
            "input is mutated. Lists are replaced, not concatenated."
        ),
        seed={'merge.py': 'def deep_merge(a, b):\n    raise NotImplementedError\n'},
        verify='''python3 - <<'EOF'
from merge import deep_merge
a = {'x': 1, 'n': {'p': 1, 'q': 2}, 'l': [1,2]}
b = {'y': 2, 'n': {'q': 9, 'r': 3}, 'l': [3]}
out = deep_merge(a, b)
assert out == {'x':1,'y':2,'n':{'p':1,'q':9,'r':3},'l':[3]}, out
assert a == {'x': 1, 'n': {'p': 1, 'q': 2}, 'l': [1,2]}, 'mutated a'
assert b == {'y': 2, 'n': {'q': 9, 'r': 3}, 'l': [3]}, 'mutated b'
out['n']['p'] = 99
assert a['n']['p'] == 1, 'shared nested reference'
EOF''',
    ),
]


# ── reference solutions ───────────────────────────────────────────────────────
# Used only by `run_trial.py --solve-test`, which proves each verifier is REACHABLE. A
# verifier that can never pass is as fatal as one that always does: it would report 0% for
# both arms and look like a finding. The agent never sees this file — it works in a temp
# workspace seeded only from `seed` — so keeping the answers here costs nothing.
REFERENCE = {
    'parse-durations': {'durations.py': """import re
_U = {'s':1,'m':60,'h':3600,'d':86400}
def parse_duration(s):
    if not isinstance(s, str): raise TypeError('need str')
    t = re.sub(r'\\s+','',s)
    if not t: raise ValueError('empty')
    if t.isdigit(): return int(t)
    parts = re.findall(r'(\\d+)([smhd])', t)
    if not parts or ''.join(a+b for a,b in parts) != t: raise ValueError(s)
    return sum(int(n)*_U[u] for n,u in parts)
"""},
    'fix-off-by-one': {'chunk.py': """def chunk(seq, n):
    return [list(seq[i:i+n]) for i in range(0, len(seq), n)]
"""},
    'csv-median': {'stats.py': """import csv, statistics
def column_median(path, column):
    vals=[]
    with open(path, newline='') as f:
        for row in csv.DictReader(f):
            try: vals.append(float(row[column]))
            except (TypeError, ValueError): pass
    if not vals: raise ValueError('no numeric values')
    return statistics.median(vals)
"""},
    'retry-backoff': {'retry.py': """import time
def retry(fn, attempts=3, base=0.01):
    for i in range(1, attempts+1):
        try: return fn()
        except Exception:
            if i == attempts: raise
            time.sleep(base * 2**(i-1))
"""},
    'merge-configs': {'merge.py': """import copy
def deep_merge(a, b):
    out = copy.deepcopy(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out
"""},
}


def by_id(tid):
    for t in TASKS:
        if t['id'] == tid:
            return t
    raise KeyError(tid)
