# Agent Service Toolkit Vue AG-UI Frontend

Vue 3 + TypeScript implementation of the existing chat UI, using the standard
AG-UI protocol for agent runs. Authentication, conversations, history, RAG,
feedback, layout, and styling remain aligned with `vue-frontend`.

## Run With Existing Backend

```bash
cd vue-frontend-agui
npm install
npm run dev
```

Open:

```text
http://localhost:5173
```

The frontend calls the FastAPI backend directly. Agent runs use:

```text
POST http://localhost:8080/agui/{agent_id}/run
```

The remaining APIs, including authentication, conversation history, RAG, and
feedback, continue to use their existing endpoints.

## Start the backend

In another terminal, start the existing FastAPI service:

```bash
uv run python src/run_service.py
```

If ports are occupied:

```bash
lsof -i :8080
lsof -i :5173
kill -9 $(lsof -ti :8080)
kill -9 $(lsof -ti :5173)
```
