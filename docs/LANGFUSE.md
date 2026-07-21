# Langfuse observability

The service supports self-hosted Langfuse for end-to-end LangGraph observability.
Each `/invoke`, `/stream`, and `/agui` request creates one root `agent` trace. The
Langfuse LangChain callback records the nested graph, node, model, and tool
observations below that root.

## Configuration

Configure the service in `.env`:

```dotenv
LANGFUSE_TRACING=true
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=http://localhost:3000
LANGFUSE_BASE_URL=http://localhost:3000
LANGFUSE_ENVIRONMENT=development
LANGFUSE_RELEASE=agent-service-toolkit
LANGFUSE_DEBUG=false
```

`LANGFUSE_BASE_URL` is retained for SDK/tool compatibility. Application code uses
`LANGFUSE_HOST` explicitly, so host-based runs load credentials reliably even when
dotenv values have not been exported into the shell environment.

When the agent service itself runs in Docker, `compose.yaml` overrides the URL with
`http://host.docker.internal:3000`. Set `LANGFUSE_DOCKER_URL` if the Langfuse API is
available at a different container-reachable URL.

## Captured data

- request input and final output or terminal stream status;
- agent id, protocol, public run id, selected model, environment, and release;
- `thread_id` as the Langfuse session id and `user_id` as the Langfuse user id;
- tags for service, agent, and transport;
- LangGraph graph and node spans;
- model generations, prompts, responses, token usage, and latency exposed by the provider;
- tool calls, tool arguments, results, duration, and errors;
- safeguard model calls;
- AG-UI event counts and stream event/token metrics;
- `/feedback` scores linked to the deterministic trace id derived from `run_id`.

This is intentionally high-detail tracing. A self-hosted deployment still contains
user prompts, model responses, tool arguments/results, and potentially personal data.
Restrict access to Langfuse and configure masking or sampling before using it with
sensitive production traffic.

## Verification

The smoke test can start an isolated Langfuse stack:

```sh
./scripts/smoke_test.sh langfuse
```

It can also reuse a running instance without deleting its containers or volumes:

```sh
SMOKE_SERVICE_PORT=18080 \
LANGFUSE_REUSE_HOST=http://localhost:3000 \
LANGFUSE_REUSE_PUBLIC_KEY=pk-lf-... \
LANGFUSE_REUSE_SECRET_KEY=sk-lf-... \
./scripts/smoke_test.sh langfuse
```

The test sends a uniquely identified request plus feedback, then queries Langfuse
directly for both the trace and its score. Successful service HTTP responses alone
are not considered sufficient.

Useful health checks:

```sh
curl http://localhost:3000/api/public/health
curl http://localhost:8080/health
```

The service health response contains `"langfuse":"connected"` when authentication
against the configured Langfuse instance succeeds.
