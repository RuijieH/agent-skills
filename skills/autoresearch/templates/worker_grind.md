# TASK: GRIND (closed-loop metric optimization)

You are worker `{{WORKER_ID}}` on branch `{{BRANCH}}`.
Your worktree: `{{WORKTREE}}` — run EVERY command from there (your shell does not start there).
Execution env: AR_GPU=`{{GPU}}`, AR_HOST=`{{HOST}}` (empty host = local run).

Config: `{{CONFIG}}`
Results ledger (append rows here): `{{RESULTS}}`
Write your final JSON result to: `{{RESULT_JSON}}`

GOAL: drive the metric as far as possible (per metric.goal) using the experiment loop,
exactly like the classic autoresearch loop. This is pure point-grinding — you are NOT
testing a single hypothesis, you are greedily improving the metric.

STEPS:
1. Read `{{CONFIG}}`. Note metric, goal, run_cmd, target_files, readonly_files, timeout.
2. Prepare the environment if needed: run `setup_cmd` once.
3. BASELINE: run the unmodified code through the experiment primitive once. Record it as
   keep (this is your starting best). Append to results.tsv.
4. LOOP up to {{MAX_EXP}} experiments: each iteration, pick ONE concrete improvement
   (architecture / hyperparameter / optimizer / batch / etc. — whatever the project's
   target_files allow), apply it, run the experiment primitive, keep-or-discard, log.
   Favor simple changes with clear rationale. After a few near-misses, try combining the
   ones that helped, or a more radical change.
5. Stop after {{MAX_EXP}} experiments (or sooner if clearly out of good ideas).

When done, Write `{{RESULT_JSON}}` — and reply with that same JSON as your final
message — with this schema:
{
  "worker_id": "{{WORKER_ID}}",
  "mode": "grind",
  "branch": "{{BRANCH}}",
  "metric_name": "<from config>",
  "goal": "<min|max>",
  "baseline_metric": <number>,
  "best_metric": <number>,
  "best_commit": "<short sha of best>",
  "improved": <true|false>,
  "num_experiments": <int>,
  "kept_count": <int>,
  "insight": "<2-4 sentences: what moved the metric, what didn't, why>",
  "followups": ["<promising next idea>", "..."],
  "experiments": [
    {"commit": "<sha or ''>", "metric": <number>, "status": "keep|discard|crash", "desc": "<short>"}
  ]
}
