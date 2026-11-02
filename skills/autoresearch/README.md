# autoresearch-kit

A globally-available Claude Code skill that turns the [autoresearch](https://github.com/karpathy/autoresearch)
idea into a **general autonomous-research orchestrator** usable in *any* project.

**Mental model — split brain / hands:**
- The **main agent (you) is the brain**: proposes hypotheses, reads results, analyzes,
  revises hypotheses, decides what to test next.
- **Workers are the hands**: each is a background worker **subagent** (Agent tool,
  `run_in_background: true`) running in its own **git worktree**, doing env prep + code
  edits + running experiments (single runs may take hours), then reporting a structured
  JSON result. The main agent never runs experiments or edits target files itself.

**Two modes:**
- `grind` — the classic closed loop: one worker greedily drives a metric (e.g. autoresearch
  `val_bpb`) down via keep/discard experiments.
- `research` — hypothesis-driven: serial hypotheses chain via **git branches**; independent
  hypotheses run in **parallel worktrees**. The brain analyzes verdicts+insights and
  iterates toward sharper hypotheses.

## Use it

In any project: `/autoresearch init`  → fill in `.autoresearch/config.json` → then
`/autoresearch grind` or `/autoresearch research`. The skill (`SKILL.md`) drives the
orchestration; you just talk to it.

## Files
```
SKILL.md                     orchestrator protocol (loaded on /autoresearch)
scripts/ar.sh                all plumbing: init | prep | status | collect | list | cleanup
templates/config.*.json      per-project config (autoresearch default / generic)
templates/worker_system.md   shared worker rules (prepended into each runs/<id>/prompt.md)
templates/worker_grind.md    grind-mode task prompt
templates/worker_hypothesis.md  hypothesis-mode task prompt
```

## Per-project layout (created by `ar.sh init`)
```
<project>/.autoresearch/
  config.json     metric/goal/extract, run_cmd, setup_cmd, target_files, timeout
  bin/            adapter scripts (metric wrappers, remote sync+run) — committed;
                  ALL framework glue lives here, never in the project's own tree
  results.tsv     append-only experiment ledger
  hypotheses/     hypothesis ledger (brain writes <id>.md here)
  runs/<id>/      per-worker: prompt.md, meta.json, result.json         (gitignored)
  worktrees/<id>/ per-worker isolated git worktree                      (gitignored)
```

## Notes
- `ar.sh prep` only prepares (worktree + prompt.md); the orchestrator launches each worker
  itself via the Agent tool with `run_in_background: true`. Workers inherit the session's
  permission mode and execute arbitrary project code — run in an autonomous permission
  mode, and only on trusted repos (as in the original autoresearch design).
- Long experiments are supported: `timeout_sec` caps one run (hours are fine, e.g.
  18000 = 5h); workers run anything over ~10 min as a background Bash task.
- Status: **phase 1** (core serial loop + parallel-capable plumbing) is built and verified
  end-to-end with a mock worker. Real workers need a project whose `run_cmd` actually runs
  (e.g. autoresearch needs an NVIDIA GPU).
