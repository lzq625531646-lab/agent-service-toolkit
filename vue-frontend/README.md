# Agent Service Toolkit Vue Frontend

Vue 3 + TypeScript implementation of the Streamlit chat UI.

## Run With Existing Backend

```bash
cd vue-frontend
npm install
npm run dev
```

Open:

```text
http://localhost:5173
```

The frontend calls the FastAPI backend directly:

```text
http://localhost:8080
```

## One-Click Local Run

From PyCharm or terminal, run:

```text
scripts/run_vue_local.py
```

It starts:

```text
FastAPI backend: http://localhost:8080
Vue frontend:    http://localhost:5173
```

If ports are occupied:

```bash
lsof -i :8080
lsof -i :5173
kill -9 $(lsof -ti :8080)
kill -9 $(lsof -ti :5173)
```
