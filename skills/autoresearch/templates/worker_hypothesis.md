# TASK: TEST ONE HYPOTHESIS

You are worker `{{WORKER_ID}}` on branch `{{BRANCH}}`.
Your worktree: `{{WORKTREE}}` — run EVERY command from there (your shell does not start there).
Execution env: AR_GPU=`{{GPU}}`, AR_HOST=`{{HOST}}` (empty host = local run).

Config: `{{CONFIG}}`
Results ledger (append rows here): `{{RESULTS}}`
Write your final JSON result to: `{{RESULT_JSON}}`

THE HYPOTHESIS TO TEST:
-----------------------------------------------------------------------
{{HYPOTHESIS}}
-----------------------------------------------------------------------

Your job is NOT to greedily grind the metric. It is to run a clean, fair test of THIS
hypothesis and report a verdict with insight the orchestrator can learn from. Be a
skeptical scientist: try to give the hypothesis its best fair shot, but report honestly
whether it actually holds.

STEPS:
1. Read `{{CONFIG}}`. Prepare the environment if needed (`setup_cmd`).
2. BASELINE: run the unmodified code once via the experiment primitive. This is the
   control. Append to results.tsv (status=keep).
3. IMPLEMENT the hypothesis as a focused change to target_files. If the hypothesis has a
   natural knob (a size, a rate, an on/off), test up to {{MAX_EXP}} variants to find
   where it helps most / confirm the trend — but keep every run a fair comparison against
   the same baseline. Log each via the experiment primitive (keep best, append rows).
4. JUDGE: did the metric move in the predicted direction, beyond noise? Decide a verdict:
   - "confirmed"     — clearly helped, reproducibly.
   - "refuted"       — clearly did not help (or hurt).
   - "partial"       — helped only under some setting / with a caveat.
   - "inconclusive"  — within noise / couldn't separate signal.
   - "crash"         — couldn't get a fair test to run.

When done, Write `{{RESULT_JSON}}` — and reply with that same JSON as your final
message — with this schema:
{
  "worker_id": "{{WORKER_ID}}",
  "mode": "hypothesis",
  "branch": "{{BRANCH}}",
  "hypothesis": "<one-line restatement of what you tested>",
  "metric_name": "<from config>",
  "goal": "<min|max>",
  "baseline_metric": <number>,
  "best_metric": <number>,
  "best_commit": "<short sha of best, or '' if nothing kept>",
  "improved": <true|false>,
  "delta": <best_metric - baseline_metric, signed>,
  "num_experiments": <int>,
  "verdict": "confirmed|refuted|partial|inconclusive|crash",
  "insight": "<3-5 sentences: WHAT you learned and WHY — the mechanism, not just the number. This is the payload the orchestrator reasons over.>",
  "followups": ["<a sharper follow-up hypothesis this result suggests>", "..."],
  "experiments": [
    {"commit": "<sha or ''>", "metric": <number>, "status": "keep|discard|crash", "desc": "<short, includes the knob value tested>"}
  ]
}
