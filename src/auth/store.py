import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from auth.security import create_session_token, hash_session_token, normalize_email
from core.settings import settings
from memory.postgres import get_postgres_connection_string, validate_postgres_config

logger = logging.getLogger(__name__)


class DuplicateUserError(ValueError):
    pass


class ConversationAccessError(PermissionError):
    pass


@dataclass(frozen=True)
class UserRecord:
    id: UUID
    email: str
    display_name: str
    password_hash: str
    created_at: datetime


@dataclass(frozen=True)
class ConversationRecord:
    thread_id: str
    user_id: UUID
    title: str
    agent_id: str
    model: str
    created_at: datetime
    updated_at: datetime


class UserStore:
    def __init__(self) -> None:
        self._pool: AsyncConnectionPool | None = None

    async def open(self) -> None:
        if self._pool is not None:
            return
        validate_postgres_config()
        self._pool = AsyncConnectionPool(
            get_postgres_connection_string(),
            min_size=settings.POSTGRES_MIN_CONNECTIONS_PER_POOL,
            max_size=settings.POSTGRES_MAX_CONNECTIONS_PER_POOL,
            kwargs={
                "autocommit": True,
                "row_factory": dict_row,
                "application_name": f"{settings.POSTGRES_APPLICATION_NAME}-auth",
            },
            check=AsyncConnectionPool.check_connection,
            open=False,
        )
        await self._pool.open(wait=True)
        await self._setup()

    async def close(self) -> None:
        if self._pool is None:
            return
        await self._pool.close()
        self._pool = None

    async def create_user(self, email: str, display_name: str, encoded_password: str) -> UserRecord:
        user_id = uuid4()
        try:
            async with self._connection() as conn:
                row = await (
                    await conn.execute(
                        """
                        INSERT INTO app_users (id, email, display_name, password_hash)
                        VALUES (%s, %s, %s, %s)
                        RETURNING id, email, display_name, password_hash, created_at
                        """,
                        (user_id, normalize_email(email), display_name.strip(), encoded_password),
                    )
                ).fetchone()
        except UniqueViolation as exc:
            raise DuplicateUserError("An account with this email already exists") from exc
        if row is None:
            raise RuntimeError("User insert did not return a row")
        return self._user_from_row(row)

    async def get_user_by_email(self, email: str) -> UserRecord | None:
        async with self._connection() as conn:
            row = await (
                await conn.execute(
                    """
                    SELECT id, email, display_name, password_hash, created_at
                    FROM app_users
                    WHERE email = %s AND disabled_at IS NULL
                    """,
                    (normalize_email(email),),
                )
            ).fetchone()
        return self._user_from_row(row) if row else None

    async def get_user_by_id(self, user_id: UUID) -> UserRecord | None:
        async with self._connection() as conn:
            row = await (
                await conn.execute(
                    """
                    SELECT id, email, display_name, password_hash, created_at
                    FROM app_users
                    WHERE id = %s AND disabled_at IS NULL
                    """,
                    (user_id,),
                )
            ).fetchone()
        return self._user_from_row(row) if row else None

    async def create_session(self, user_id: UUID, lifetime: timedelta) -> tuple[str, datetime]:
        raw_token = create_session_token()
        expires_at = datetime.now(UTC) + lifetime
        async with self._connection() as conn:
            await conn.execute(
                """
                INSERT INTO user_sessions (id, user_id, token_hash, expires_at)
                VALUES (%s, %s, %s, %s)
                """,
                (uuid4(), user_id, hash_session_token(raw_token), expires_at),
            )
        return raw_token, expires_at

    async def get_user_by_session_token(self, token: str) -> UserRecord | None:
        token_hash = hash_session_token(token)
        async with self._connection() as conn:
            row = await (
                await conn.execute(
                    """
                    UPDATE user_sessions AS sessions
                    SET last_used_at = now()
                    FROM app_users AS users
                    WHERE sessions.token_hash = %s
                      AND sessions.expires_at > now()
                      AND sessions.revoked_at IS NULL
                      AND users.id = sessions.user_id
                      AND users.disabled_at IS NULL
                    RETURNING users.id, users.email, users.display_name,
                              users.password_hash, users.created_at
                    """,
                    (token_hash,),
                )
            ).fetchone()
        return self._user_from_row(row) if row else None

    async def revoke_session(self, token: str) -> None:
        async with self._connection() as conn:
            await conn.execute(
                """
                UPDATE user_sessions SET revoked_at = now()
                WHERE token_hash = %s AND revoked_at IS NULL
                """,
                (hash_session_token(token),),
            )

    async def ensure_conversation(
        self,
        *,
        thread_id: str,
        user_id: UUID,
        title: str,
        agent_id: str,
        model: str,
    ) -> ConversationRecord:
        async with self._connection() as conn, conn.transaction():
            existing = await (
                await conn.execute(
                    """
                    SELECT thread_id, user_id, title, agent_id, model, created_at, updated_at
                    FROM chat_sessions WHERE thread_id = %s FOR UPDATE
                    """,
                    (thread_id,),
                )
            ).fetchone()
            if existing:
                if existing["user_id"] != user_id:
                    raise ConversationAccessError("Conversation does not belong to this user")
                row = await (
                    await conn.execute(
                        """
                        UPDATE chat_sessions
                        SET agent_id = %s, model = %s, updated_at = now()
                        WHERE thread_id = %s
                        RETURNING thread_id, user_id, title, agent_id, model,
                                  created_at, updated_at
                        """,
                        (agent_id, model, thread_id),
                    )
                ).fetchone()
            else:
                row = await (
                    await conn.execute(
                        """
                        INSERT INTO chat_sessions
                            (thread_id, user_id, title, agent_id, model)
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING thread_id, user_id, title, agent_id, model,
                                  created_at, updated_at
                        """,
                        (thread_id, user_id, title, agent_id, model),
                    )
                ).fetchone()
        if row is None:
            raise RuntimeError("Conversation upsert did not return a row")
        return self._conversation_from_row(row)

    async def get_conversation(self, user_id: UUID, thread_id: str) -> ConversationRecord | None:
        async with self._connection() as conn:
            row = await (
                await conn.execute(
                    """
                    SELECT thread_id, user_id, title, agent_id, model, created_at, updated_at
                    FROM chat_sessions
                    WHERE thread_id = %s AND user_id = %s
                    """,
                    (thread_id, user_id),
                )
            ).fetchone()
        return self._conversation_from_row(row) if row else None

    async def list_conversations(self, user_id: UUID) -> list[ConversationRecord]:
        async with self._connection() as conn:
            rows = await (
                await conn.execute(
                    """
                    SELECT thread_id, user_id, title, agent_id, model, created_at, updated_at
                    FROM chat_sessions
                    WHERE user_id = %s
                    ORDER BY updated_at DESC
                    """,
                    (user_id,),
                )
            ).fetchall()
        return [self._conversation_from_row(row) for row in rows]

    async def touch_conversation(self, user_id: UUID, thread_id: str) -> None:
        async with self._connection() as conn:
            await conn.execute(
                """
                UPDATE chat_sessions SET updated_at = now()
                WHERE thread_id = %s AND user_id = %s
                """,
                (thread_id, user_id),
            )

    async def _setup(self) -> None:
        async with self._connection() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_users (
                    id uuid PRIMARY KEY,
                    email text NOT NULL UNIQUE,
                    display_name text NOT NULL,
                    password_hash text NOT NULL,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now(),
                    disabled_at timestamptz
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_sessions (
                    id uuid PRIMARY KEY,
                    user_id uuid NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
                    token_hash char(64) NOT NULL UNIQUE,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    last_used_at timestamptz NOT NULL DEFAULT now(),
                    expires_at timestamptz NOT NULL,
                    revoked_at timestamptz
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    thread_id text PRIMARY KEY,
                    user_id uuid NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
                    title text NOT NULL,
                    agent_id text NOT NULL,
                    model text NOT NULL,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS user_sessions_user_id_idx ON user_sessions(user_id)"
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS chat_sessions_user_updated_idx
                ON chat_sessions(user_id, updated_at DESC)
                """
            )

    def _connection(self):
        if self._pool is None:
            raise RuntimeError("User store is not open")
        return self._pool.connection()

    @staticmethod
    def _user_from_row(row) -> UserRecord:
        return UserRecord(
            id=row["id"],
            email=row["email"],
            display_name=row["display_name"],
            password_hash=row["password_hash"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _conversation_from_row(row) -> ConversationRecord:
        return ConversationRecord(
            thread_id=row["thread_id"],
            user_id=row["user_id"],
            title=row["title"],
            agent_id=row["agent_id"],
            model=row["model"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


user_store = UserStore()
