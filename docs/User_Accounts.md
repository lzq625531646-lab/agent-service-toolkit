# User accounts and resumable chat history

The Vue application requires users to register or sign in before accessing agents. Account,
login-session, and conversation metadata are stored in the project's dedicated PostgreSQL database.
Passwords are hashed with Argon2 through `pwdlib`; plaintext passwords and raw login tokens are never
stored. Login tokens expire after `USER_SESSION_DAYS` and are revoked on logout.

## API

Public endpoints:

```text
POST /auth/register
POST /auth/login
```

Authenticated endpoints use `Authorization: Bearer <access_token>`:

```text
GET  /auth/me
POST /auth/logout
GET  /conversations
GET  /conversations/{thread_id}/messages
```

Agent invocation and streaming endpoints also require the bearer token. For an authenticated user,
the backend ignores any request-body `user_id` and uses the account UUID. It creates a conversation
record on the first message and verifies ownership before reusing a `thread_id`.

`AUTH_SECRET`, when configured, remains available for trusted service-to-service callers. A service
secret does not grant access to user conversation-list or history endpoints because those operations
require an actual user identity.

## Persistence model

- `app_users`: normalized email, display name, Argon2 password hash.
- `user_sessions`: SHA-256 hash of each random session token, expiry and revocation timestamps.
- `chat_sessions`: thread ownership, title, selected agent/model, and activity timestamps.
- LangGraph checkpoint tables: the actual messages and graph state for each `thread_id`.

The history API resolves the conversation's saved agent before reading its checkpoint. It supports
both StateGraph agents and Functional API agents, whose accumulated state is stored in the
`__previous__` checkpoint channel.

## Vue workflow

Start the service and Vue frontend, then open `http://localhost:5173`:

```sh
uv run python src/main.py

cd vue-frontend
npm run dev
```

After login, the sidebar lists only the current user's conversations. Selecting one restores its
agent, model, `thread_id`, complete message history, and allows the user to continue the same
LangGraph checkpoint.
