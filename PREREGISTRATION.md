# Does the laserbrain gate change how agents finish work?

**Pre-registered 2026-08-01, before any trial data existed.** Written first on purpose: the
corpus already contains one statistic that got quoted without its denominator, and the cure
for that is deciding what counts as an answer while it is still possible to be surprised.

---

## The claim under test

Diego's question was whether laserbrain "saves time and tokens." That question cannot be
asked in that form, and saying why is half the design.

**Fewer tokens is trivially winnable by doing less.** An agent that gives up on step three
spends almost nothing and finishes fast. Any metric that rewards brevity rewards quitting.
So token count alone is not a measure of anything, and a trial built on it would produce a
number that flatters whichever condition failed more often.

The measurable claim is therefore not "spends less" but:

> **The gate spends tokens to buy a higher rate of finished work.**

That is a claim about a *ratio*, and it can lose. If the gate raises cost without raising
completion, the honest report is that it costs and does not deliver.

## Hypotheses, and what would refute each

| # | Hypothesis | Refuted if |
|---|---|---|
| H1 | The gate raises the pass rate | pass rate with the gate ≤ pass rate without, on ≥30 paired tasks |
| H2 | The gate costs tokens | it does not — this one is expected to hold and is the price tag, not a benefit |
| H3 | Cost per *passing* task is lower with the gate | tokens-per-pass is ≥ without the gate |

H3 is the interesting one. H1 without H3 means the gate works and is expensive. H3 without
H1 would mean it is cheap and useless. Both are reportable outcomes.

## The one threshold, fixed now

**A pass-rate difference below 10 percentage points is reported as no effect**, whatever its
p-value, because with 30 paired tasks anything smaller is inside the noise of task selection.
This number is chosen before the data exists so it cannot be moved afterward to rescue a
result.

Sample size: **≥30 tasks, each run in both conditions.** Below 30 the trial reports its
numbers and states explicitly that no conclusion is drawn — the same refusal
`sensitivity.py` makes about d-prime.

## Design

Paired, within-task. Every task runs twice — gate on, gate off — so each task is its own
control and task difficulty cancels out. Order is randomized per task so that any drift in
model behaviour over the trial window does not systematically favour one arm.

**Conditions differ in exactly one thing:** the settings file. `settings.gate-on.json`
carries the laserbrain PreToolUse/PostToolUse/UserPromptSubmit hooks; `settings.gate-off.json`
carries none. Same model, same prompt, same tools, same working copy, same budget cap.

**Success is decided by a command, not by judgement.** Each task ships a `verify.sh` that
exits 0 or non-zero. Neither the agent nor the person running the trial grades anything. A
task whose verifier cannot fail is not a task — `--self-test` runs every verifier against an
untouched workspace and refuses to proceed if any of them passes before work has been done.

**Measured per run:** wall-clock seconds, input/output/cache tokens, cost in USD, turns, and
the verifier's exit code. All raw rows are written to `results.jsonl`; nothing is aggregated
at collection time.

## What this trial cannot say

- **It is one operator's task set.** Tasks written by the same person who built the
  instrument select for the failures that instrument was designed around. This measures the
  gate on *these* tasks, not on work in general.
- **One model, one week.** No claim about other models or later versions.
- **Pass/fail is coarse.** A verifier says "the tests are green," not "the code is good." A
  condition could pass more often and produce worse work, and this design would not see it.
- **The gate is not the only difference the hooks make.** Turning the hooks off also turns
  off coverage logging and the safety guard. The trial measures the whole hook layer, and
  says so, rather than pretending to isolate the gate alone.

## Running it

```
python3 run_trial.py --self-test          # prove every verifier can fail
python3 run_trial.py --budget 0.50        # per-run USD cap
python3 report.py
```
