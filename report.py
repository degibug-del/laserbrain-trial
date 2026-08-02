#!/usr/bin/env python3
"""Read results.jsonl and report what it supports — including nothing, when that is the answer.

    python3 report.py
    python3 report.py --results other.jsonl

This file holds the thresholds from PREREGISTRATION.md as constants, so the decision rule
cannot be adjusted after seeing the numbers without the diff showing it. That is the entire
reason they are here rather than in someone's head.
"""
import argparse
import collections
import json
import math
import pathlib
import statistics

# ── the pre-registered rule, fixed 2026-08-01 before any data existed ──────────
MIN_TASKS = 30        # below this, no conclusion is drawn — only description
MIN_EFFECT_PP = 10.0  # a pass-rate gap under this is reported as no effect

HERE = pathlib.Path(__file__).resolve().parent


def load(p):
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return statistics.mean(xs) if xs else None


def fmt(v, spec='{:,.0f}'):
    return spec.format(v) if isinstance(v, (int, float)) else 'n/a'


def mcnemar(b, c):
    """Exact-ish two-sided p for paired binary data. b and c are the discordant counts.

    Only the pairs that DISAGREE carry information about a difference — a task both arms
    passed, or both failed, says nothing about which arm is better. Reporting n as the task
    count while the test runs on b+c is a standard way to look better powered than you are,
    so both numbers print.
    """
    n = b + c
    if n == 0:
        return None
    # two-sided exact binomial against p=0.5
    tail = sum(math.comb(n, k) for k in range(0, min(b, c) + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--results', default=str(HERE / 'results.jsonl'))
    a = ap.parse_args()
    all_rows = load(pathlib.Path(a.results))
    # A void run never reached the model. Counting it as a failure would let an outage,
    # an expired login or a rate limit masquerade as "the gate made no difference".
    rows = [r for r in all_rows if not r.get('void')]
    voided = len(all_rows) - len(rows)

    bar = '=' * 70
    print(f'\n{bar}\n  LASERBRAIN GATE TRIAL\n{bar}')
    if voided:
        print(f'  EXCLUDED {voided} void run(s) — never reached the model '
              f'(api error or zero output tokens). They are absence of data, not failures.')
    if not rows:
        print('  no usable results. Run:')
        print('    python3 run_trial.py --self-test')
        print('    python3 run_trial.py --solve-test')
        print('    python3 run_trial.py --budget 0.50\n')
        return 0

    arms = sorted({r['arm'] for r in rows})
    print(f'  rows {len(rows)}   arms: {", ".join(arms)}')

    # ── per-arm description. Descriptive only; no claim yet. ──────────────────
    print(f'\n{bar}\n  PER ARM\n{bar}')
    print(f'  {"arm":<10}{"runs":>6}{"passed":>8}{"pass%":>8}{"out_tok":>10}'
          f'{"secs":>8}{"$/run":>9}')
    per = {}
    for arm in arms:
        g = [r for r in rows if r['arm'] == arm]
        p = sum(1 for r in g if r['passed'])
        per[arm] = dict(n=len(g), passed=p,
                        out=mean([r.get('out_tok') for r in g]),
                        sec=mean([r.get('seconds') for r in g]),
                        usd=mean([r.get('cost_usd') for r in g]))
        print(f'  {arm:<10}{len(g):>6}{p:>8}{p / len(g) * 100:>7.0f}%'
              f'{fmt(per[arm]["out"]):>10}{fmt(per[arm]["sec"], "{:,.0f}"):>8}'
              f'{fmt(per[arm]["usd"], "${:.3f}"):>9}')

    # ── the paired comparison, which is the actual design ────────────────────
    if set(arms) != {'gate-on', 'gate-off'}:
        print('\n  arms are not the expected pair; stopping before any comparison.\n')
        return 0

    by_task = collections.defaultdict(dict)
    for r in rows:
        by_task[r['task']].setdefault(r['arm'], []).append(r)
    paired = {t: v for t, v in by_task.items() if len(v) == 2}

    on_only = off_only = both = neither = 0
    for t, v in paired.items():
        on = any(x['passed'] for x in v['gate-on'])
        off = any(x['passed'] for x in v['gate-off'])
        both += on and off
        neither += (not on) and (not off)
        on_only += on and not off
        off_only += off and not on

    print(f'\n{bar}\n  PAIRED — each task is its own control\n{bar}')
    print(f'  tasks run in both arms   {len(paired)}')
    print(f'    both passed            {both}')
    print(f'    both failed            {neither}')
    print(f'    only WITH the gate     {on_only}   <- evidence for the gate')
    print(f'    only WITHOUT it        {off_only}   <- evidence against')
    disc = on_only + off_only
    p = mcnemar(on_only, off_only)
    print(f'  discordant pairs         {disc}'
          + (f'   McNemar p = {p:.3f}' if p is not None else '   (no disagreement to test)'))

    gap = ((per['gate-on']['passed'] / per['gate-on']['n'])
           - (per['gate-off']['passed'] / per['gate-off']['n'])) * 100

    # ── H3: the ratio that matters, cost per task that actually finished ─────
    print(f'\n{bar}\n  COST PER PASSING TASK  (H3)\n{bar}')
    for arm in arms:
        g = [r for r in rows if r['arm'] == arm]
        passes = sum(1 for r in g if r['passed'])
        tok = sum(r.get('out_tok') or 0 for r in g)
        usd = sum(r.get('cost_usd') or 0 for r in g)
        if passes:
            print(f'  {arm:<10}{tok / passes:>12,.0f} out_tok/pass   ${usd / passes:.3f}/pass')
        else:
            print(f'  {arm:<10}  no passes — a per-pass cost would divide by zero, so none is shown')

    # ── the verdict, against the rule written before the data ────────────────
    print(f'\n{bar}\n  VERDICT\n{bar}')
    print(f'  pass-rate gap (on − off): {gap:+.1f} percentage points')
    if len(paired) < MIN_TASKS:
        print(f'  NO CONCLUSION DRAWN. {len(paired)} paired task(s); the pre-registration')
        print(f'  fixed {MIN_TASKS} as the floor. The numbers above are description, not')
        print('  evidence, and must not be quoted as a result.')
    elif abs(gap) < MIN_EFFECT_PP:
        print(f'  NO EFFECT. The gap is inside the {MIN_EFFECT_PP:.0f}-point band that was called')
        print('  noise in advance. This holds whatever the p-value says.')
    else:
        who = 'WITH the gate' if gap > 0 else 'WITHOUT the gate'
        print(f'  Completion is higher {who}, by more than the pre-registered')
        print(f'  {MIN_EFFECT_PP:.0f}-point threshold' + (f' (McNemar p = {p:.3f}).' if p else '.'))
        print('  Report it beside the cost: the gate is a trade, not a free win.')
    print()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
