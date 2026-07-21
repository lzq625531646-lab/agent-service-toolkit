#!/usr/bin/env bash
# On-demand smoke tests for docker-backed integration paths that aren't in the
# fast unit-test suite or the default CI run: the Postgres and MongoDB
# checkpointers, the AG-UI endpoint, and LangFuse tracing. Lets a maintainer (or
# agent) verify these still work without waiting for a full CI cycle.
#
# Usage:
#   ./scripts/smoke_test.sh                 # default targets: postgres, mongo, agui
#   ./scripts/smoke_test.sh mongo           # run a single target
#   ./scripts/smoke_test.sh postgres agui   # run a subset
#   ./scripts/smoke_test.sh langfuse        # run the heavy langfuse target on its own
#   ./scripts/smoke_test.sh all             # everything, including langfuse
#
# Targets: postgres, mongo, agui, langfuse
#   langfuse is excluded from the default run: it spins up LangFuse's full
#   self-host stack (6 services, ~5GB of images) and takes noticeably longer, so
#   run it explicitly or via `all`. It also needs the cgr.dev container registry
#   reachable (for the minio image) — in a restricted-egress cloud environment,
#   add cgr.dev to the network allowlist first.
#
# Only databases run in Docker; the service itself runs on the host via uv,
# pointed at localhost. That's deliberate — building the service image requires
# reaching package registries from inside the build container, which is blocked
# in some sandboxed agent environments. Running on the host sidesteps that while
# still exercising real database containers.
#
# A green run is meant to actually mean something. Beyond the pytest/API check,
# each target independently verifies the intended dependency was really used:
# the DB targets query the container for this run's thread, and langfuse queries
# its API for the trace. This is what catches a silent fallback (e.g. to SQLite)
# that would otherwise pass the API-level test against any working checkpointer.
#
# Requires: docker, docker compose, uv, node (AG-UI client), python3, curl
set -euo pipefail
cd "$(dirname "$0")/.."

# Unique per run so the backend verification below reflects THIS run's data even
# if the database volume isn't empty. Exported so the pytest test uses the same
# thread id (see tests/smoke/test_persistence.py).
SMOKE_THREAD_ID="smoke-test-$(date +%s)-$$"
export SMOKE_THREAD_ID
SMOKE_SERVICE_PORT="${SMOKE_SERVICE_PORT:-8080}"
SMOKE_SERVICE_URL="http://localhost:${SMOKE_SERVICE_PORT}"
export SMOKE_SERVICE_URL
# Database smoke containers always use their own Compose project. This prevents
# the cleanup trap's `down -v` from ever deleting a developer's persistent data.
SMOKE_COMPOSE_PROJECT_NAME="${SMOKE_COMPOSE_PROJECT_NAME:-agent-service-toolkit-smoke-$$}"

# LangFuse's self-host compose is fetched from upstream at this pinned tag rather
# than vendored into the repo. Bump this to move to a newer LangFuse.
LANGFUSE_REF="v3.205.1"

SERVICE_PID=""
SERVICE_LOG=""
LANGFUSE_COMPOSE=""  # temp compose file, set while the langfuse target runs

compose_smoke() {
  docker compose --project-name "$SMOKE_COMPOSE_PROJECT_NAME" "$@"
}

start_service() {
  # Start the agent service on the host with the given backend env, then wait
  # until it reports healthy. Args: KEY=VALUE ... connection settings.
  if curl -sf "$SMOKE_SERVICE_URL/health" >/dev/null 2>&1; then
    echo "  ✗ refusing to start: something is already listening on :$SMOKE_SERVICE_PORT"
    return 1
  fi
  SERVICE_LOG="$(mktemp)"
  env MODE=prod USE_FAKE_MODEL=true PORT="$SMOKE_SERVICE_PORT" "$@" \
    uv run python src/run_service.py > "$SERVICE_LOG" 2>&1 &
  SERVICE_PID=$!
  for _ in $(seq 1 30); do
    if curl -sf "$SMOKE_SERVICE_URL/health" >/dev/null 2>&1; then
      return 0
    fi
    if ! kill -0 "$SERVICE_PID" 2>/dev/null; then
      echo "  ✗ service exited during startup; log:"
      cat "$SERVICE_LOG"
      return 1
    fi
    sleep 2
  done
  echo "  ✗ service did not become healthy within 60s; log:"
  cat "$SERVICE_LOG"
  return 1
}

stop_service() {
  if [[ -n "$SERVICE_PID" ]]; then
    kill "$SERVICE_PID" 2>/dev/null || true
    wait "$SERVICE_PID" 2>/dev/null || true
    SERVICE_PID=""
  fi
  if [[ -n "$SERVICE_LOG" ]]; then
    rm -f "$SERVICE_LOG"
    SERVICE_LOG=""
  fi
}

wait_healthy() {
  # Wait until a container reports healthy. Args: container id.
  local cid="$1" status=""
  for _ in $(seq 1 20); do
    status="$(docker inspect -f '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo missing)"
    [[ "$status" == "healthy" ]] && return 0
    echo "  waiting for database... ($status)"
    sleep 2
  done
  echo "  ✗ database never became healthy"
  return 1
}

assert_positive_count() {
  # Args: count-string, label. Fails loudly unless count is an integer > 0.
  local n="$1" label="$2"
  if [[ "$n" =~ ^[0-9]+$ ]] && (( n > 0 )); then
    echo "  ✓ verified: $n $label"
  else
    echo "  ✗ FAIL: expected >0 $label, got '$n' — backend was NOT exercised as intended"
    return 1
  fi
}

cleanup() {
  echo "--- Tearing down ---"
  stop_service
  # down removes every service in the merged project (postgres + mongo), so this
  # one call cleans up regardless of which target was running.
  compose_smoke -f compose.yaml -f docker/compose.mongo.yaml down -v >/dev/null 2>&1 || true
  if [[ -n "$LANGFUSE_COMPOSE" && -f "$LANGFUSE_COMPOSE" ]]; then
    docker compose -f "$LANGFUSE_COMPOSE" down -v >/dev/null 2>&1 || true
    rm -f "$LANGFUSE_COMPOSE"
  fi
}
trap cleanup EXIT

smoke_postgres() {
  echo "=== PostgreSQL checkpointer and long-term Store (DATABASE_TYPE=postgres) ==="
  local postgres_host_port="${SMOKE_POSTGRES_HOST_PORT:-25433}"
  local postgres_user="${SMOKE_POSTGRES_USER:-agent_service_smoke}"
  local postgres_password="${SMOKE_POSTGRES_PASSWORD:-smoke-only-password}"
  local postgres_db="${SMOKE_POSTGRES_DB:-agent_service_toolkit_smoke}"
  POSTGRES_HOST_PORT="$postgres_host_port" POSTGRES_USER="$postgres_user" \
    POSTGRES_PASSWORD="$postgres_password" POSTGRES_DB="$postgres_db" \
    compose_smoke -f compose.yaml up -d postgres
  local cid
  cid="$(compose_smoke -f compose.yaml ps -q postgres)"
  wait_healthy "$cid"
  local -a postgres_env=(
    DATABASE_TYPE=postgres
    POSTGRES_HOST=localhost
    POSTGRES_PORT="$postgres_host_port"
    POSTGRES_USER="$postgres_user"
    POSTGRES_PASSWORD="$postgres_password"
    POSTGRES_DB="$postgres_db"
  )
  start_service "${postgres_env[@]}"
  uv run pytest tests/smoke/test_persistence.py -v --run-docker

  # Write a long-term Store record through the same production initializer used
  # by the service. A fresh process reads it after the service restart below.
  env "${postgres_env[@]}" uv run python -c "
import asyncio
import sys
sys.path.insert(0, 'src')
from memory.postgres import get_postgres_store

async def main():
    async with get_postgres_store() as store:
        await store.aput(('smoke-test', 'restart'), '$SMOKE_THREAD_ID', {'persisted': True})

asyncio.run(main())
print('  wrote long-term Store record')
"

  local n
  n="$(docker exec -e PGPASSWORD="$postgres_password" "$cid" \
    psql -U "$postgres_user" -d "$postgres_db" -tAc \
    "select count(*) from checkpoints where thread_id='$SMOKE_THREAD_ID'" 2>/dev/null | tr -d '[:space:]')" || true
  assert_positive_count "$n" "postgres checkpoint rows for this run's thread"
  n="$(docker exec -e PGPASSWORD="$postgres_password" "$cid" \
    psql -U "$postgres_user" -d "$postgres_db" -tAc \
    "select count(*) from pg_extension where extname='vector'" 2>/dev/null | tr -d '[:space:]')" || true
  assert_positive_count "$n" "pgvector extension registrations"
  n="$(docker exec -e PGPASSWORD="$postgres_password" "$cid" \
    psql -U "$postgres_user" -d "$postgres_db" -tAc \
    "select count(*) from pg_tables where schemaname='public' and tablename in ('rag_documents','rag_chunks')" 2>/dev/null | tr -d '[:space:]')" || true
  if [[ "$n" == "2" ]]; then
    echo "  ✓ verified: pgvector RAG tables initialized"
  else
    echo "  ✗ FAIL: expected both pgvector RAG tables, got '$n'"
    return 1
  fi

  # Stop the whole application process, reconnect with new pools, and prove both
  # the conversation checkpoint and Store item survived that restart.
  stop_service
  start_service "${postgres_env[@]}"
  uv run python -c "
import sys
sys.path.insert(0, 'src')
from client import AgentClient

history = AgentClient('$SMOKE_SERVICE_URL').get_history('$SMOKE_THREAD_ID')
human = [message.content for message in history.messages if message.type == 'human']
assert human == ['Tell me a joke?', 'Tell me another?'], human
print('  ✓ checkpoint history survived service restart')
"
  env "${postgres_env[@]}" uv run python -c "
import asyncio
import sys
sys.path.insert(0, 'src')
from memory.postgres import get_postgres_store

async def main():
    async with get_postgres_store() as store:
        item = await store.aget(('smoke-test', 'restart'), '$SMOKE_THREAD_ID')
        assert item is not None and item.value == {'persisted': True}, item

asyncio.run(main())
print('  ✓ long-term Store survived service restart')
"
  compose_smoke -f compose.yaml down -v
}

smoke_mongo() {
  echo "=== MongoDB checkpointer (DATABASE_TYPE=mongo) ==="
  local files=(-f compose.yaml -f docker/compose.mongo.yaml)
  compose_smoke "${files[@]}" up -d mongo
  local cid
  cid="$(compose_smoke "${files[@]}" ps -q mongo)"
  wait_healthy "$cid"
  start_service DATABASE_TYPE=mongo MONGO_HOST=localhost MONGO_PORT=27017 MONGO_DB=agent_service
  uv run pytest tests/smoke/test_persistence.py -v --run-docker
  local n
  n="$(docker exec "$cid" mongosh agent_service --quiet --eval \
    "db.checkpoints.countDocuments({thread_id:'$SMOKE_THREAD_ID'})" 2>/dev/null | tr -d '[:space:]')" || true
  assert_positive_count "$n" "mongo checkpoint documents for this run's thread"
  stop_service
  compose_smoke "${files[@]}" down -v
}

smoke_agui() {
  echo "=== AG-UI endpoint ==="
  # AG-UI is backend-agnostic, so the default SQLite checkpointer is fine here
  # and no database container is needed.
  start_service
  local out
  out="$(cd scripts/agui-client && npm install --silent && \
    AGENT_URL="$SMOKE_SERVICE_URL" MODEL=fake \
      node client.mjs "Tell me a joke!" chatbot)" || true
  echo "$out"
  # A green exit isn't enough: confirm the stream actually completed and returned
  # the fake model's response, not an empty or partial run.
  if ! grep -q "RUN_FINISHED" <<<"$out"; then
    echo "  ✗ FAIL: AG-UI stream did not reach RUN_FINISHED"
    return 1
  fi
  if ! grep -q "This is a test response from the fake model." <<<"$out"; then
    echo "  ✗ FAIL: AG-UI did not return the expected assistant response"
    return 1
  fi
  echo "  ✓ verified: AG-UI streamed a complete run with the expected response"
  stop_service
}

smoke_langfuse() {
  echo "=== LangFuse tracing (self-hosted) ==="
  local pk="${LANGFUSE_REUSE_PUBLIC_KEY:-pk-lf-smoke-public}"
  local sk="${LANGFUSE_REUSE_SECRET_KEY:-sk-lf-smoke-secret}"
  local host="${LANGFUSE_REUSE_HOST:-http://localhost:3000}"
  local score_name="smoke-feedback-$SMOKE_THREAD_ID"

  if [[ -n "${LANGFUSE_REUSE_HOST:-}" ]]; then
    if [[ -z "${LANGFUSE_REUSE_PUBLIC_KEY:-}" || -z "${LANGFUSE_REUSE_SECRET_KEY:-}" ]]; then
      echo "  ✗ FAIL: reuse mode requires LANGFUSE_REUSE_PUBLIC_KEY and LANGFUSE_REUSE_SECRET_KEY"
      return 1
    fi
    echo "  reusing LangFuse at $host"
  else
    # Fetch LangFuse's official self-host compose (pinned) rather than vendoring it.
    # Bare mktemp (no --suffix) for macOS/BSD portability; `docker compose -f`
    # doesn't care about the file extension.
    LANGFUSE_COMPOSE="$(mktemp)"
    echo "  fetching LangFuse compose @ $LANGFUSE_REF"
    if ! curl -sSL "https://raw.githubusercontent.com/langfuse/langfuse/$LANGFUSE_REF/docker-compose.yml" \
      -o "$LANGFUSE_COMPOSE"; then
      echo "  ✗ FAIL: could not fetch LangFuse compose"
      return 1
    fi

    # LANGFUSE_INIT_* seeds an org/project/user and known API keys on first boot, so
    # no manual signup is needed and the keys below are deterministic.
    echo "  starting LangFuse stack (this pulls ~5GB the first time)..."
    LANGFUSE_INIT_ORG_ID=smoke-org LANGFUSE_INIT_ORG_NAME=smoke \
    LANGFUSE_INIT_PROJECT_ID=smoke-project LANGFUSE_INIT_PROJECT_NAME=smoke \
    LANGFUSE_INIT_PROJECT_PUBLIC_KEY="$pk" LANGFUSE_INIT_PROJECT_SECRET_KEY="$sk" \
    LANGFUSE_INIT_USER_EMAIL=smoke@example.com LANGFUSE_INIT_USER_NAME=smoke \
    LANGFUSE_INIT_USER_PASSWORD=smokepassword123 \
      docker compose -f "$LANGFUSE_COMPOSE" up -d
  fi

  echo "  waiting for langfuse-web..."
  for _ in $(seq 1 40); do
    curl -sf "$host/api/public/health" >/dev/null 2>&1 && break
    sleep 3
  done
  if ! curl -sf "$host/api/public/health" >/dev/null 2>&1; then
    echo "  ✗ FAIL: langfuse-web did not become ready"
    return 1
  fi

  start_service LANGFUSE_TRACING=true LANGFUSE_HOST="$host" LANGFUSE_BASE_URL="$host" \
    LANGFUSE_PUBLIC_KEY="$pk" LANGFUSE_SECRET_KEY="$sk"

  # (1) service-level: /health runs langfuse.auth_check() against the instance.
  if curl -s "$SMOKE_SERVICE_URL/health" | grep -q '"langfuse":"connected"'; then
    echo "  ✓ /health reports langfuse connected"
  else
    echo "  ✗ FAIL: /health did not report langfuse connected"
    return 1
  fi

  # (2) decisive: an invoke and its feedback must produce a trace and score in LangFuse.
  uv run python -c "
import sys; sys.path.insert(0, 'src')
import asyncio
from client import AgentClient
c = AgentClient('$SMOKE_SERVICE_URL')
r = c.invoke(
    'Trace me please',
    thread_id='$SMOKE_THREAD_ID',
    user_id='smoke-test-user',
    model='fake',
)
assert r.type == 'ai', r
assert r.run_id, r
asyncio.run(c.acreate_feedback(r.run_id, '$score_name', 1.0, {'comment': 'smoke test'}))
print('  traced invoke and feedback requests ok')
"
  echo "  waiting for the trace and score to land in LangFuse (ingestion is async)..."
  local n=0
  local trace_id=""
  for _ in $(seq 1 20); do
    trace_id="$(curl -s -u "$pk:$sk" \
      "$host/api/public/traces?limit=5&sessionId=$SMOKE_THREAD_ID" \
      | python3 -c 'import sys, json; data=json.load(sys.stdin).get("data", []); print(data[0]["id"] if data else "")' 2>/dev/null || true)"
    [[ -n "$trace_id" ]] && break
    sleep 3
  done
  [[ -n "$trace_id" ]] && n=1
  assert_positive_count "$n" "LangFuse traces recorded for this run"

  n=0
  for _ in $(seq 1 20); do
    n="$(curl -s -u "$pk:$sk" \
      "$host/api/public/scores?limit=20&traceId=$trace_id" \
      | SCORE_NAME="$score_name" python3 -c 'import os, sys, json; scores=json.load(sys.stdin).get("data", []); print(sum(s.get("name") == os.environ["SCORE_NAME"] for s in scores))' 2>/dev/null || echo 0)"
    [[ "$n" =~ ^[0-9]+$ ]] && (( n > 0 )) && break
    sleep 3
  done
  assert_positive_count "$n" "LangFuse feedback scores recorded for this trace"

  stop_service
  if [[ -n "$LANGFUSE_COMPOSE" ]]; then
    docker compose -f "$LANGFUSE_COMPOSE" down -v
    rm -f "$LANGFUSE_COMPOSE"
    LANGFUSE_COMPOSE=""
  fi
}

targets=("$@")
[[ ${#targets[@]} -eq 0 ]] && targets=(postgres mongo agui)

# Expand "all" to every target, including the heavy langfuse one.
expanded=()
for t in "${targets[@]}"; do
  if [[ "$t" == "all" ]]; then
    expanded+=(postgres mongo agui langfuse)
  else
    expanded+=("$t")
  fi
done
targets=("${expanded[@]}")

for t in "${targets[@]}"; do
  case "$t" in
    postgres) smoke_postgres ;;
    mongo)    smoke_mongo ;;
    agui)     smoke_agui ;;
    langfuse) smoke_langfuse ;;
    *) echo "unknown target: $t (valid: postgres, mongo, agui, langfuse, all)"; exit 2 ;;
  esac
done

echo "--- All smoke tests passed ---"
