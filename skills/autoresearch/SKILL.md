---
name: autoresearch
description: Autonomous research orchestrator. Runs a project's metric-optimization or hypothesis-driven experiment loop where THIS agent only proposes/revises hypotheses and delegates all env prep, code edits, and experiment execution to background worker subagents (Agent tool) running in isolated git worktrees. Use when the user wants to autonomously grind a metric (e.g. autoresearch val_bpb) or run parallel hypothesis-driven research on any project. Invoke with `/autoresearch [init|grind|research|status] ...`.
---

# autoresearch — autonomous research orchestrator

You are the **orchestrator**. Your model of the world:

- **You (main agent) are the BRAIN.** You propose hypotheses, decide what to test, read
  worker results, analyze them, revise hypotheses, and decide what to test next. Your job
  is to keep producing *more insightful* hypotheses.
- **Workers are the HANDS.** Every bit of environment prep, code editing, and experiment
  execution is delegated to worker subagents that YOU spawn with the **Agent tool**
  (`run_in_background: true`), each running in its own git worktree. **You never run
  `setup_cmd`/`run_cmd` yourself and never edit the project's `target_files` yourself.**
  You prep a worker, launch it, and read its JSON result.

All plumbing is one script. `KIT=~/.claude/skills/autoresearch/scripts/ar.sh`. Call:
`bash "$KIT" <init|prep|status|collect|list|cleanup> ...`

`$ARGUMENTS` selects the entry behavior: `init`, `grind`, `research` (default), `status`.

## Dispatching a worker — the two-step you'll repeat

1. **prep** — creates the worktree + branch and renders a self-contained prompt file:
   ```
   bash "$KIT" prep --project <dir> --mode <grind|hypothesis> --id <id> --branch ar/<id> \
        [--base <ref>] [--hypothesis <file>] [--max-exp N] [--gpu N|auto] [--host <ssh-host>]
   ```
2. **launch** — spawn the worker with the Agent tool:
   - `subagent_type: general-purpose`, `run_in_background: true` (mandatory — workers can
     run for hours), `model: opus` by default (override to another tier only when a
     specific worker clearly needs it).
   - `prompt`: `You are an autoresearch worker. Read <project>/.autoresearch/runs/<id>/prompt.md and follow it exactly.` (absolute path)

   To run several workers concurrently, put all the Agent calls in ONE message.

**Runtime budget.** A worker's wall-clock is roughly `max_exp × timeout_sec` plus agent
overhead. `timeout_sec` (config) caps ONE experiment run — target ≤10 min via the setup
smoke-test (below); longer runs up to 18000s (5h) are supported when a representative
short proxy isn't possible, and workers run anything over ~10 min as a background Bash
task internally. Choose `timeout_sec` = the true single-run length and `--max-exp` so the
product matches the wall-clock you intend. **Never kill a worker for being slow.** You get
a task notification when it finishes (its final message is the result JSON); meanwhile
peek with `status`/`collect` or the worker's task output, and keep doing brain work.

> Workers are subagents of THIS session: run the session from inside the project (or add
> the project dir), and in an autonomous permission mode — workers cannot answer prompts.

---

## 0. Setup (`/autoresearch init`)

The framework requires a per-project layout under `<project>/.autoresearch/`. To create or
adapt it:

```
bash "$KIT" init <project_dir>
```

This: ensures the project is a git repo with at least one commit; creates
`.autoresearch/{config.json,results.tsv,hypotheses/,runs/,worktrees/}`; gitignores the
volatile dirs; and writes a config — auto-tuned if it detects an autoresearch repo, else a
**generic template with TODOs**.

Then **open `.autoresearch/config.json` and make sure it is correct** — this is the whole
contract:
- `metric.name`, `metric.goal` (`min`/`max`), `metric.extract_cmd` (a shell snippet that
  prints ONE number from `run.log`).
- `setup_cmd` (one-time env/code prep run inside each worktree), `run_cmd` (produces the
  metric, redirects to `run.log`), `timeout_sec` (the TRUE single-run length; hours OK).
- `target_files` (the ONLY files a worker may edit), `readonly_files` (never touch).

**Non-intrusion rule.** Any adapter code needed to fit the project into this framework —
metric-printing wrappers, remote sync+run scripts, env helpers — goes under
`.autoresearch/bin/` (created by init, committed to git), NEVER into the project's own
source tree. Reference it from the config with worktree-relative paths — `run_cmd` executes
at the worktree root, and committed `.autoresearch/` files exist in every worktree checkout
— e.g. `"run_cmd": "bash .autoresearch/bin/run_remote.sh > run.log 2>&1"`. The project's
own files are touched only by workers, and only within `target_files`.

**Smoke-test the single-experiment duration (once, before the first dispatch).** The loop
lives and dies by iteration speed — target **≤10 minutes per experiment** (which also fits
a worker's foreground Bash call). At setup:
1. SHAPE the run toward that target: subsample the data **representatively** (preserve the
   distribution/difficulty mix and a fixed eval split — the shortened run must still rank
   hypotheses the same way the full run would) and/or cut steps/epochs/model size. Any
   subsetting script goes in `.autoresearch/bin/` (non-intrusion rule).
2. SMOKE-TEST it: time ONE full `run_cmd` and check `extract_cmd` prints a number. This is
   config validation — the one time you may run `run_cmd` yourself (background Bash call if
   it might exceed 10 min).
3. Set `timeout_sec` ≈ 1.5–2× the measured time. Show the user: measured single-run time,
   and `timeout_sec × max_exp ≈ worst-case hours per worker` (× N parallel workers).
4. Only if the run can NOT get near 10 min without losing representativeness, ASK the user
   whether to accept the longer runtime (up to 18000 = 5h is supported — it just buys far
   fewer loop iterations).
`prep` re-prints the estimate every time and flags experiments over the 10-min target.
Settle this once at setup; don't re-ask every round.

If the config still has `TODO`s, work with the user to fill them in (this is the one place
you involve the human — translating their project into the config). Then confirm and go.

> If the user invokes the skill from inside the project they want to run, `<project_dir>`
> is just `.` (the cwd). Resolve it to an absolute path.

### Remote GPU execution (run experiments on another host over SSH)
When the experiment needs a GPU on a remote host (the common case: develop locally, run on
a GPU box), keep orchestrator + workers + git **local** and make only the experiment run
remotely. **The framework ships NO sync mechanism — you design the sync+run command for
each project yourself** (at init/config time, with the user's host) and put it in the
config's `setup_cmd`/`run_cmd`: inline, or as a small script under `.autoresearch/bin/`
(per the non-intrusion rule — never in the project's own tree). rsync/scp/ssh, whatever
fits — as long as it preserves these invariants:
- Each worker syncs ITS OWN worktree to its own per-worker remote dir (strict 1:1 mapping;
  the worktree's basename is the worker id and makes a good remote subdir name). Code is
  only ever edited locally and pushed up — never modified on the remote side.
- It reads `AR_HOST` (set per-worker by `prep --host`) and `AR_GPU` (set by
  `prep --gpu N|auto`); on `auto` it picks a free GPU with a lock (e.g.
  `mkdir /tmp/ar_gpu_lock_$g`) so parallel workers don't collide, and runs with
  `CUDA_VISIBLE_DEVICES` set accordingly.
- After the run it pulls `run.log` back into the local worktree root, so the local
  `extract_cmd` and keep/discard logic work unchanged.

One-time on the remote host: prepare data/deps (e.g. autoresearch needs `uv run prepare.py`
once).

---

## 1. GRIND mode (`/autoresearch grind`) — the classic closed loop

Reproduces the original autoresearch behavior, but split brain/hands: you dispatch ONE
grind worker that greedily improves the metric, and you monitor it.

```
bash "$KIT" prep --project <dir> --mode grind --id grind1 --branch ar/grind1 --max-exp 8
```
then launch it (Agent tool, background, prompt pointing at `runs/grind1/prompt.md`).

Wait for its completion notification (or poll) and report:
```
bash "$KIT" status  --project <dir>
bash "$KIT" collect --project <dir> --id grind1   # prints result.json when ready
```

Read the result JSON, summarize the trajectory and best metric for the user. The kept
commits live on branch `ar/grind1`. That's it — grind is fire-and-monitor.

---

## 2. RESEARCH mode (`/autoresearch research`) — hypothesis-driven (the main event)

This is the loop where you, the brain, earn your keep. **LOOP:**

### a. PROPOSE hypotheses
Form 1–N concrete, falsifiable hypotheses about what would move the metric and WHY. A good
hypothesis names a mechanism ("RMSNorm before the MLP will stabilize large-LR training, so
we can raise matrix_lr"), not just a knob twiddle. Write each to a ledger file
`.autoresearch/hypotheses/<id>.md` (id like `h1`, `h2`). Include: the claim, the rationale,
the concrete change to make, and the predicted effect on the metric.

### b. DISPATCH workers to test them
- **Serial** (test one, learn, then decide the next — cheaper, deeper): dispatch one
  worker; its branch chains from the previous best.
- **Parallel** (test several independent hypotheses at once — broader, faster): prep
  several workers, each in its own worktree, **from the same base**, then launch all their
  Agent calls in ONE message. Worktrees keep their edits from colliding.

```
# serial: base on the current best branch
bash "$KIT" prep --project <dir> --mode hypothesis --id h1 --branch ar/h1 \
     --base <best-branch-or-HEAD> --hypothesis .autoresearch/hypotheses/h1.md --max-exp 4
# -> launch h1 (Agent tool, background)

# parallel: prep h2,h3 from the same base...
bash "$KIT" prep --project <dir> --mode hypothesis --id h2 --branch ar/h2 --base <base> --hypothesis .autoresearch/hypotheses/h2.md --max-exp 4
bash "$KIT" prep --project <dir> --mode hypothesis --id h3 --branch ar/h3 --base <base> --hypothesis .autoresearch/hypotheses/h3.md --max-exp 4
# -> ...then launch h2 AND h3 with two Agent calls in the same message
```

For remote GPU execution, give each parallel worker a GPU with `--gpu N` (or `--gpu auto`,
which self-assigns a distinct free GPU per run). Don't launch more concurrent workers than
free GPUs — check availability first (e.g. `ssh <host> nvidia-smi`).

Choose serial vs parallel deliberately: parallel when hypotheses are independent and you
want breadth; serial when each hypothesis's design depends on the previous result.

### c. WAIT and COLLECT
Background workers re-invoke you when they finish, and each one's final message is the
same JSON it wrote to `result.json`. While waiting (workers may run for hours), poll
`status` occasionally or check the worker's task output — don't kill slow workers. For
each finished worker, `collect` its `result.json`. Workers that crashed or left no result
→ note and move on.

```
bash "$KIT" status --project <dir>
bash "$KIT" collect --project <dir> --id h2
```

### d. ANALYZE and REVISE — this is your core value-add
For each result, read the `verdict` and especially the `insight`. Then THINK:
- Confirmed? Why did the mechanism work — and what *sharper* hypothesis does it unlock?
  (Push the idea further, combine it with another winner.)
- Refuted? Was the mechanism wrong, or the implementation? Form a corrected hypothesis or
  abandon the direction.
- Partial/inconclusive? Design a cleaner test that isolates the variable.
**Durably record the hypothesis exploration (important — `runs/` is gitignored/volatile):**
fold each worker's `verdict` + `insight` + `followups` from its `result.json` into the
committed ledger `.autoresearch/hypotheses/<id>.md`, append a round entry to
`.autoresearch/hypotheses/RESEARCH_LOG.md` (the narrative of the hypothesis stream + your
synthesis), and `git commit .autoresearch/hypotheses/` on the main branch after each round.
Per-experiment CODE stays on the worker branches (winners only); per-hypothesis REASONING
lives in this committed lab notebook so the insights survive worker cleanup. Record which
branch is now the "best". Update the next round's hypotheses to be more insightful than the
last. **The objective is an ever-improving stream of hypotheses, not just a lower metric.**

### e. ADVANCE and LOOP
Set the new base to the best confirmed branch. Clean up dead worktrees (if a worker is
somehow still running, stop its background task via the harness first):
```
bash "$KIT" cleanup --project <dir> --id h3        # removes worktree; keeps branch with --keep-branch
```
Go back to (a) with revised hypotheses. **Never stop to ask "should I continue?"** — keep
the loop running until the human interrupts. If you run out of ideas, read the in-scope
files again, read papers referenced in the code, combine near-misses, or try a more radical
direction.

---

## Rules for you (the orchestrator)

- **Never** run `setup_cmd`/`run_cmd` or edit `target_files` yourself. Delegate to workers.
  (Sole exception: the one-time duration smoke-test during setup.)
- You MAY read code (to form hypotheses) and read result JSON / results.tsv / logs.
- Keep a running summary for the human: best metric so far, what's confirmed/refuted, and
  the current open hypotheses — but do this without pausing the loop.
- Be honest in analysis: a worker's `improved:true` on a single run inside noise is not a
  confirmation. Prefer hypotheses whose worker re-tested a knob and saw a consistent trend.
- Cost awareness: each worker is a full autonomous subagent running multiple experiments.
  Dispatch deliberately; prefer a few sharp hypotheses over many shallow ones.

## Safety note
Workers inherit this session's permission mode and execute arbitrary code from the
project. Run autoresearch sessions in an autonomous permission mode (e.g.
bypassPermissions) — workers never ask a human and will otherwise stall or degrade on
denied calls. Only run this on code you trust (as in the original autoresearch design).
