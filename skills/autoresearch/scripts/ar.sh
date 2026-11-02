#!/usr/bin/env bash
# autoresearch-kit — orchestration plumbing for autonomous research loops.
# Single entrypoint, many subcommands. The orchestrator (main agent) calls these;
# the heavy lifting (env prep, code edits, running experiments) is done by worker
# SUBAGENTS that the orchestrator launches itself (Agent tool, run_in_background)
# into isolated git worktrees prepared here.
#
#   ar.sh init      <project_dir>                       # adapt a project to the framework
#   ar.sh prep      --project D --mode M --id ID ...    # create worktree + render worker prompt
#   ar.sh status    --project D [--id ID]               # poll worker states (result.json presence)
#   ar.sh collect   --project D --id ID                 # print a worker's result JSON
#   ar.sh list      --project D                         # list all workers
#   ar.sh cleanup   --project D --id ID [--keep-branch] # remove a worker's worktree
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TPL_DIR="$(cd "$SCRIPT_DIR/../templates" && pwd)"

_die() { echo "ar.sh: $*" >&2; exit 1; }
_abs() { (cd "$1" 2>/dev/null && pwd) || _die "no such dir: $1"; }

# render <template_file> KEY VAL KEY VAL ...  -> stdout with {{KEY}} replaced (multiline-safe)
render() {
  local tpl="$1"; shift
  local content; content="$(cat "$tpl")"
  while [ "$#" -gt 0 ]; do
    local key="$1" val="$2"; shift 2
    content="${content//\{\{$key\}\}/$val}"
  done
  printf '%s' "$content"
}

# --- argument parsing helper: fills assoc-like vars from --key value pairs ---
PROJECT="" MODE="" ID="" BRANCH="" BASE="" HYP_FILE="" MAX_EXP="" KEEP_BRANCH="" GPU="" HOST=""
parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --project)   PROJECT="$2"; shift 2;;
      --mode)      MODE="$2"; shift 2;;
      --id)        ID="$2"; shift 2;;
      --branch)    BRANCH="$2"; shift 2;;
      --base)      BASE="$2"; shift 2;;
      --hypothesis) HYP_FILE="$2"; shift 2;;
      --max-exp)   MAX_EXP="$2"; shift 2;;
      --gpu)       GPU="$2"; shift 2;;
      --host)      HOST="$2"; shift 2;;
      --keep-branch) KEEP_BRANCH="1"; shift;;
      *) _die "unknown arg: $1";;
    esac
  done
}

# =====================================================================
# init: adapt an arbitrary project into the framework's file layout
# =====================================================================
cmd_init() {
  local dir="${1:-$PWD}"
  [ -d "$dir" ] || _die "not a directory: $dir"
  dir="$(_abs "$dir")"

  # 1) ensure git repo (worktrees + branches require it)
  if ! git -C "$dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "[init] '$dir' is not a git repo -> running git init"
    git -C "$dir" init -q
    git -C "$dir" add -A
    git -C "$dir" -c user.name="autoresearch" -c user.email="autoresearch@local" commit -qm "autoresearch: initial snapshot" || true
  fi

  # 2) ensure a committable base exists (worktrees need at least one commit)
  if ! git -C "$dir" rev-parse HEAD >/dev/null 2>&1; then
    git -C "$dir" add -A
    git -C "$dir" -c user.name="autoresearch" -c user.email="autoresearch@local" commit -qm "autoresearch: initial snapshot" || true
  fi

  local ar="$dir/.autoresearch"
  mkdir -p "$ar/hypotheses" "$ar/runs" "$ar/worktrees" "$ar/bin"

  # 3) gitignore the volatile parts (worktrees + run artifacts must never be committed)
  printf 'worktrees/\nruns/\n' > "$ar/.gitignore"
  if ! grep -qsE '^/?\.autoresearch/(worktrees|runs)' "$dir/.gitignore" 2>/dev/null; then
    printf '\n# autoresearch volatile dirs + per-experiment log\n.autoresearch/worktrees/\n.autoresearch/runs/\nrun.log\n' >> "$dir/.gitignore"
  fi

  # 4) results ledger
  if [ ! -f "$ar/results.tsv" ]; then
    printf 'worker_id\tcommit\tmetric\tsecondary\tstatus\tdescription\n' > "$ar/results.tsv"
  fi

  # 5) config: autodetect autoresearch repo, else write a generic template with TODOs
  if [ ! -f "$ar/config.json" ]; then
    if [ -f "$dir/train.py" ] && [ -f "$dir/prepare.py" ] && grep -qs "val_bpb" "$dir/train.py" "$dir/prepare.py" 2>/dev/null; then
      echo "[init] detected an autoresearch-style repo -> writing tuned default config"
      cp "$TPL_DIR/config.autoresearch.json" "$ar/config.json"
    else
      echo "[init] writing generic config template (EDIT .autoresearch/config.json before dispatching)"
      cp "$TPL_DIR/config.generic.json" "$ar/config.json"
    fi
  fi

  echo "[init] ready: $ar"
  echo "       config:    $ar/config.json"
  echo "       results:   $ar/results.tsv"
  echo "       hypotheses:$ar/hypotheses/"
  echo "       bin:       $ar/bin/ (adapter scripts live HERE, never in the project tree)"
}

# =====================================================================
# prep: create a worktree on a fresh branch and render the worker prompt.
# It does NOT launch anything — the ORCHESTRATOR launches the worker itself
# via the Agent tool (run_in_background: true) pointed at prompt.md.
# =====================================================================
cmd_prep() {
  parse_args "$@"
  [ -n "$PROJECT" ] || _die "prep needs --project"
  [ -n "$ID" ] || _die "prep needs --id"
  PROJECT="$(_abs "$PROJECT")"
  MODE="${MODE:-grind}"
  BRANCH="${BRANCH:-ar/$ID}"
  BASE="${BASE:-HEAD}"
  MAX_EXP="${MAX_EXP:-6}"
  local ar="$PROJECT/.autoresearch"
  [ -f "$ar/config.json" ] || _die "no config at $ar/config.json — run 'ar.sh init' first"

  local rundir="$ar/runs/$ID"
  mkdir -p "$rundir"
  local wt="$ar/worktrees/$ID"
  local result_json="$rundir/result.json"

  # fresh worktree on a new branch
  if git -C "$PROJECT" worktree list --porcelain | grep -q "worktree $wt$"; then
    _die "worktree already exists for id=$ID at $wt (cleanup first)"
  fi
  git -C "$PROJECT" worktree add -q -b "$BRANCH" "$wt" "$BASE" \
    || _die "git worktree add failed (branch $BRANCH may already exist)"

  # render the worker task prompt
  local tpl
  case "$MODE" in
    grind)      tpl="$TPL_DIR/worker_grind.md";;
    hypothesis) tpl="$TPL_DIR/worker_hypothesis.md";;
    *) _die "unknown mode: $MODE (grind|hypothesis)";;
  esac
  local hyp_text=""
  if [ -n "$HYP_FILE" ]; then
    [ -f "$HYP_FILE" ] || _die "hypothesis file not found: $HYP_FILE"
    hyp_text="$(cat "$HYP_FILE")"
  fi
  local task
  task="$(render "$tpl" \
    CONFIG "$ar/config.json" \
    RESULTS "$ar/results.tsv" \
    RESULT_JSON "$result_json" \
    WORKTREE "$wt" \
    BRANCH "$BRANCH" \
    WORKER_ID "$ID" \
    MAX_EXP "$MAX_EXP" \
    GPU "${GPU:-auto}" \
    HOST "$HOST" \
    HYPOTHESIS "$hyp_text")"

  # one self-contained prompt file: shared worker rules + the mode-specific task
  { cat "$TPL_DIR/worker_system.md"; printf '\n---\n\n'; printf '%s\n' "$task"; } \
    > "$rundir/prompt.md"

  # persist meta for status/collect
  cat > "$rundir/meta.json" <<EOF
{"worker_id":"$ID","mode":"$MODE","branch":"$BRANCH","base":"$BASE","worktree":"$wt","project":"$PROJECT","max_exp":$MAX_EXP,"gpu":"${GPU:-auto}","host":"$HOST"}
EOF

  echo "[prep] worker '$ID' ready (mode=$MODE branch=$BRANCH)"
  echo "       worktree: $wt"
  echo "       prompt:   $rundir/prompt.md"
  echo "       result:   $result_json (written by the worker on completion)"
  local tsec; tsec="$(sed -n 's/.*"timeout_sec"[^0-9]*\([0-9][0-9]*\).*/\1/p' "$ar/config.json" | head -1)"
  if [ -n "$tsec" ]; then
    local wc_h; wc_h="$(awk -v t="$tsec" -v n="$MAX_EXP" 'BEGIN{printf "%.1f", t*n/3600}')"
    echo "       runtime:  timeout_sec=${tsec}s per experiment × max_exp=$MAX_EXP ≈ ${wc_h}h worst-case for this worker"
    [ "$tsec" -gt 600 ] && echo "                 ^ over the 10-min-per-experiment target — shrink to a REPRESENTATIVE <=10min proxy (data subset / fewer steps), or confirm the long runtime with the user."
  fi
  echo "       now launch it yourself: Agent tool, run_in_background=true, prompt:"
  echo "         \"You are an autoresearch worker. Read $rundir/prompt.md and follow it exactly.\""
}

# =====================================================================
# status / list
# =====================================================================
_worker_state() {  # echoes: done|pending. Workers are background subagents — the
  local rundir="$1" #  harness tracks liveness; here result.json is the only ground truth.
  if [ -f "$rundir/result.json" ]; then echo "done"; else echo "pending"; fi
}

cmd_status() {
  parse_args "$@"
  [ -n "$PROJECT" ] || _die "status needs --project"
  PROJECT="$(_abs "$PROJECT")"
  local runs="$PROJECT/.autoresearch/runs"
  [ -d "$runs" ] || { echo "(no workers yet)"; return; }
  printf '%-16s %-12s %-10s %s\n' "WORKER" "MODE" "STATE" "RESULT"
  for d in "$runs"/*/; do
    [ -d "$d" ] || continue
    local id; id="$(basename "$d")"
    [ -n "$ID" ] && [ "$ID" != "$id" ] && continue
    local mode="?"; [ -f "$d/meta.json" ] && mode="$(sed -n 's/.*"mode":"\([^"]*\)".*/\1/p' "$d/meta.json")"
    local state; state="$(_worker_state "$d")"
    local res="-"; [ -f "${d}result.json" ] && res="${d}result.json"
    printf '%-16s %-12s %-10s %s\n' "$id" "$mode" "$state" "$res"
  done
}

cmd_list() { cmd_status "$@"; }

# =====================================================================
# collect: print a worker's structured result (or log tail if absent)
# =====================================================================
cmd_collect() {
  parse_args "$@"
  [ -n "$PROJECT" ] || _die "collect needs --project"
  [ -n "$ID" ] || _die "collect needs --id"
  PROJECT="$(_abs "$PROJECT")"
  local rundir="$PROJECT/.autoresearch/runs/$ID"
  [ -d "$rundir" ] || _die "no such worker: $ID"
  if [ -f "$rundir/result.json" ]; then
    cat "$rundir/result.json"
  else
    echo "{\"worker_id\":\"$ID\",\"state\":\"pending\",\"note\":\"no result.json yet — check the worker subagent's task output; run.log tail (if any) below\"}"
    echo "----- run.log (tail) -----" >&2
    tail -n 40 "$PROJECT/.autoresearch/worktrees/$ID/run.log" 2>/dev/null >&2 || true
  fi
}

# =====================================================================
# cleanup: remove a worker's worktree (branch deleted unless --keep-branch).
# If the worker subagent is still running, the orchestrator must stop it
# via the harness first — there is no local pid to kill.
# =====================================================================
cmd_cleanup() {
  parse_args "$@"
  [ -n "$PROJECT" ] || _die "cleanup needs --project"
  [ -n "$ID" ] || _die "cleanup needs --id"
  PROJECT="$(_abs "$PROJECT")"
  local ar="$PROJECT/.autoresearch"
  local rundir="$ar/runs/$ID"
  local wt="$ar/worktrees/$ID"
  if [ -d "$wt" ]; then
    git -C "$PROJECT" worktree remove --force "$wt" 2>/dev/null \
      || { rm -rf "$wt"; git -C "$PROJECT" worktree prune; }
  fi
  if [ -z "$KEEP_BRANCH" ]; then
    local branch="ar/$ID"; [ -f "$rundir/meta.json" ] && branch="$(sed -n 's/.*"branch":"\([^"]*\)".*/\1/p' "$rundir/meta.json")"
    git -C "$PROJECT" branch -D "$branch" 2>/dev/null || true
  fi
  echo "[cleanup] removed worktree for '$ID'"
}

# =====================================================================
main() {
  local sub="${1:-}"; shift || true
  case "$sub" in
    init)    cmd_init "$@";;
    prep)    cmd_prep "$@";;
    status)  cmd_status "$@";;
    list)    cmd_list "$@";;
    collect) cmd_collect "$@";;
    cleanup) cmd_cleanup "$@";;
    ""|-h|--help|help)
      sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//';;
    *) _die "unknown subcommand: $sub (init|prep|status|collect|list|cleanup)";;
  esac
}
main "$@"
