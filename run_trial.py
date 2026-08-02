#!/usr/bin/env python3
"""Run every task in both arms and record what happened. Decides nothing.

    python3 run_trial.py --self-test            # prove every verifier can fail
    python3 run_trial.py --budget 0.50          # then actually run it
    python3 run_trial.py --tasks parse-durations --repeats 1 --budget 0.25

DESIGN NOTES THAT MATTER MORE THAN THE CODE

PAIRED, AND RANDOMIZED WITHIN THE PAIR. Each task runs in both arms, so task difficulty is
its own control and cancels. The order of the two arms is shuffled per task so that any drift
over the trial window — rate limits, model updates, a machine getting busier — cannot land
systematically on one arm. Unpaired designs on five tasks would measure the task set.

A FRESH WORKSPACE PER RUN. Every run gets its own temp directory seeded from scratch. Sharing
a workspace would let the first arm leave the answer lying around for the second, which is a
silent way to make both arms look identical.

THE VERIFIER RUNS AFTER THE AGENT IS GONE, in that same workspace, and its exit code is the
outcome. Nothing reads the diff. Nothing asks a model whether the work is good.

COLLECTION DOES NOT AGGREGATE. Every row goes to results.jsonl raw — tokens, seconds, cost,
turns, exit code, and the arm. `report.py` is the only place a rate is computed, so a rate can
always be recomputed from the rows if the analysis turns out to be wrong. The corpus already
learned this lesson: a statistic whose inputs were thrown away cannot be re-examined when the
denominator turns out to have been two different things.

WHAT IS NOT CONTROLLED, said plainly: turning the hooks off also disables coverage logging and
the safety guard, so the manipulation is the whole hook layer rather than the gate in
isolation. Recorded in the pre-registration; repeated here because this file is what someone
will read first.
"""
import argparse
import json
import os
import pathlib
import random
import shutil
import subprocess
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
RESULTS = HERE / 'results.jsonl'
ARMS = {'gate-on': HERE / 'settings.gate-on.json',
        'gate-off': HERE / 'settings.gate-off.json'}

sys.path.insert(0, str(HERE))
from tasks import TASKS, REFERENCE, by_id                            # noqa: E402


def seed_workspace(task, root):
    root.mkdir(parents=True, exist_ok=True)
    for name, body in (task.get('seed') or {}).items():
        (root / name).write_text(body)
    return root


def run_verifier(task, cwd):
    """Exit code decides. Captured, never interpreted."""
    p = subprocess.run(['bash', '-c', task['verify']], cwd=cwd,
                       capture_output=True, text=True, timeout=120)
    return p.returncode, (p.stderr or p.stdout)[-400:]


def self_test():
    """Every verifier must FAIL on an untouched seed, or the trial proves nothing.

    A verifier that already passes gives both arms a free pass and inflates whichever arm
    quit sooner. This is the cheapest possible check and the most expensive thing to get
    wrong, so it is a gate rather than a warning.
    """
    ok = True
    print('self-test — each verifier must fail before any work is done\n')
    for t in TASKS:
        with tempfile.TemporaryDirectory() as td:
            ws = seed_workspace(t, pathlib.Path(td) / 'w')
            try:
                code, tail = run_verifier(t, ws)
            except subprocess.TimeoutExpired:
                code, tail = -1, 'timeout'
            good = code != 0
            ok = ok and good
            print(f"  {'ok  ' if good else 'FAIL'}  {t['id']:<18} exit={code}"
                  + ('' if good else '   <-- passes on an untouched workspace'))
    print('\n  ' + ('PASS — every task starts red.' if ok else
                    '  FAIL — fix the verifiers above before running the trial.'))
    return 0 if ok else 1


def solve_test():
    """Every verifier must PASS on a correct solution — the other half of the gate.

    --self-test alone is not enough. A verifier that can never pass reports 0% for both arms
    and looks exactly like a finding: "the gate makes no difference." Both halves have to
    hold, because between them they prove the measurement can move in either direction.
    """
    ok = True
    print('solve-test — each verifier must pass on a correct solution\n')
    for t in TASKS:
        with tempfile.TemporaryDirectory() as td:
            ws = seed_workspace(t, pathlib.Path(td) / 'w')
            for name, body in REFERENCE[t['id']].items():
                (ws / name).write_text(body)
            try:
                code, tail = run_verifier(t, ws)
            except subprocess.TimeoutExpired:
                code, tail = -1, 'timeout'
            good = code == 0
            ok = ok and good
            print(f"  {'ok  ' if good else 'FAIL'}  {t['id']:<18} exit={code}"
                  + ('' if good else f'   {tail[:140]}'))
    print('\n  ' + ('PASS — every verifier is reachable.' if ok else
                    'FAIL — an unreachable verifier scores both arms 0% and reads as a result.'))
    return 0 if ok else 1


def one_run(task, arm, budget, model, timeout):
    """One agent, one task, one arm. Returns a row; never raises on agent failure."""
    started = time.time()
    with tempfile.TemporaryDirectory() as td:
        ws = seed_workspace(task, pathlib.Path(td) / 'w')
        cmd = [
            'claude', '-p', task['prompt'],
            '--output-format', 'json',
            '--settings', str(ARMS[arm]),
            '--permission-mode', 'bypassPermissions',
            '--no-session-persistence',
            '--max-budget-usd', str(budget),
        ]
        if model:
            cmd += ['--model', model]
        # ISOLATE THE CORPUS. The gate-on arm runs the real hooks, which append to
        # ~/.config/laserbrain/drift-log.jsonl and ~/.claude/laserbrain/. Left alone, every
        # trial run would inject synthetic rows into the evidence base that corpus-map.py
        # summarises and paper-frozen-ground renders its figures from — measuring the
        # instrument would silently corrupt the thing being measured. Each run gets its own
        # log and state dir inside the temp workspace, thrown away with it.
        iso = pathlib.Path(td) / 'lb'
        (iso / 'state').mkdir(parents=True, exist_ok=True)
        env = dict(
            os.environ,
            LASERBRAIN_AGENT='trial',
            LASERBRAIN_DRIFT_LOG=str(iso / 'drift-log.jsonl'),
            LASERBRAIN_OUTCOMES_LOG=str(iso / 'verdict-outcomes.jsonl'),
            LASERBRAIN_LINK_LOG=str(iso / 'link.jsonl'),
            LASERBRAIN_STATE_DIR=str(iso / 'state'),
        )
        # A run that dies is DATA, not an error: an arm that crashes or overruns its budget
        # more often is telling us something, and swallowing that would bias the pass rate.
        try:
            p = subprocess.run(cmd, cwd=ws, capture_output=True, text=True,
                               timeout=timeout, env=env)
            raw, err, rc = p.stdout, p.stderr[-300:], p.returncode
        except subprocess.TimeoutExpired:
            raw, err, rc = '', 'agent timeout', -9

        usage, cost, turns, api_err, result_text = {}, None, None, None, ''
        try:
            body = json.loads(raw)
            usage = body.get('usage') or {}
            cost = body.get('total_cost_usd')
            turns = body.get('num_turns')
            api_err = bool(body.get('is_error'))
            result_text = str(body.get('result') or '')[:200]
        except Exception:
            pass

        # VOID: the run never reached the model, so its verifier result means nothing.
        #
        # Found by running: the first smoke test returned 10 clean "fail" rows in 0.9s each
        # with zero tokens and $0.000 — the CLI had exited with "Not logged in" and never
        # called anything. Every one was recorded as a failed task. With 5 tasks the report
        # correctly refused to conclude, but at 30 it would have printed NO EFFECT from
        # runs that did not happen, and the number would have looked perfectly ordinary.
        #
        # A failure has to be the agent trying and not succeeding. Anything else is absence
        # of data, and absence of data must never be counted as evidence of no effect.
        void = bool(api_err) or (usage.get('output_tokens') or 0) == 0

        try:
            vcode, vtail = run_verifier(task, ws)
        except subprocess.TimeoutExpired:
            vcode, vtail = -1, 'verifier timeout'

    return {
        'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'task': task['id'], 'arm': arm,
        'void': void, 'api_error': api_err, 'result_text': result_text,
        'passed': (vcode == 0) and not void, 'verify_exit': vcode, 'verify_tail': vtail,
        'seconds': round(time.time() - started, 1),
        'agent_exit': rc, 'agent_err': err,
        'in_tok': usage.get('input_tokens'), 'out_tok': usage.get('output_tokens'),
        'cache_read': usage.get('cache_read_input_tokens'),
        'cache_create': usage.get('cache_creation_input_tokens'),
        'cost_usd': cost, 'turns': turns, 'model': model or 'default',
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--self-test', action='store_true')
    ap.add_argument('--solve-test', action='store_true')
    ap.add_argument('--budget', type=float, default=0.50, help='USD cap per run')
    ap.add_argument('--repeats', type=int, default=1, help='pairs per task')
    ap.add_argument('--tasks', nargs='*', help='task ids; default all')
    ap.add_argument('--model', default=None)
    ap.add_argument('--timeout', type=int, default=900)
    ap.add_argument('--seed', type=int, default=None, help='fix the arm-order shuffle')
    a = ap.parse_args()

    if a.self_test:
        return self_test()
    if a.solve_test:
        return solve_test()

    if not shutil.which('claude'):
        print('  claude CLI not on PATH — nothing to run.')
        return 1

    chosen = [by_id(t) for t in a.tasks] if a.tasks else TASKS
    rng = random.Random(a.seed)
    plan = []
    for _ in range(a.repeats):
        for t in chosen:
            arms = list(ARMS)
            rng.shuffle(arms)               # randomize WITHIN the pair, not across tasks
            plan += [(t, arm) for arm in arms]

    total = len(plan)
    print(f'  {len(chosen)} task(s) x {a.repeats} repeat(s) x 2 arms = {total} runs')
    print(f'  budget cap ${a.budget:.2f}/run — worst case ${a.budget * total:.2f}\n')

    with RESULTS.open('a') as fh:
        for i, (task, arm) in enumerate(plan, 1):
            print(f'  [{i}/{total}] {task["id"]:<18} {arm:<9} ', end='', flush=True)
            row = one_run(task, arm, a.budget, a.model, a.timeout)
            fh.write(json.dumps(row) + '\n')
            fh.flush()                      # survive a ^C with the rows already on disk
            print(f'{"VOID" if row["void"] else ("PASS" if row["passed"] else "fail")}  '
                  f'{row["seconds"]:>6.1f}s  {row["out_tok"] or 0:>7,} out  '
                  f'${row["cost_usd"] or 0:.3f}')

    print(f'\n  wrote {total} row(s) -> {RESULTS}\n  now run: python3 report.py')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
