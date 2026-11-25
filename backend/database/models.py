"""Tables of the SQLite database (PROJECT_SPEC §12), as SQLAlchemy Core definitions.

Core (not the ORM) keeps every query explicit and lets the audit writer work inside the same
transaction as the change it records. Rules enforced by the database itself:
- audit_log rows can never be updated or deleted (two triggers);
- at most one `active` version per doc_code (a partial unique index);
- ratings, roles, statuses and comment length are CHECK constraints.
"""

from sqlalchemy import (
    DDL,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    event,
    text,
)

metadata = MetaData()

ROLES = ("viewer", "qa_user", "auditor", "admin", "system")

users = Table(
    "users", metadata,
    Column("id", String, primary_key=True),
    Column("username", String, unique=True, nullable=False),  # never reused
    Column("full_name", String, nullable=False),
    Column("password_hash", String, nullable=False),  # Argon2id; '!' for the system account
    Column("role", String, nullable=False),
    Column("is_active", Integer, nullable=False, server_default="1"),
    Column("can_login", Integer, nullable=False, server_default="1"),  # 0 for the system account
    Column("failed_login_count", Integer, nullable=False, server_default="0"),
    Column("locked_until", String),
    Column("password_changed_at", String, nullable=False),
    Column("must_change_password", Integer, nullable=False, server_default="1"),
    Column("created_at", String, nullable=False),
    Column("created_by", String, ForeignKey("users.id")),
    CheckConstraint("role IN ('viewer','qa_user','auditor','admin','system')", name="users_role"),
)

password_history = Table(
    "password_history", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", String, ForeignKey("users.id"), nullable=False),
    Column("password_hash", String, nullable=False),
    Column("created_at", String, nullable=False),
    Index("idx_pwhist_user", "user_id", "created_at"),
)

documents = Table(
    "documents", metadata,
    Column("id", String, primary_key=True),
    Column("doc_code", String, nullable=False),
    Column("title", String, nullable=False),
    Column("version", String, nullable=False),
    Column("effective_date", String),
    Column("publisher", String),
    Column("file_path", String, nullable=False),
    Column("sha256", String, nullable=False),
    Column("page_count", Integer),
    Column("chunk_count", Integer, nullable=False),
    Column("status", String, nullable=False),
    Column("status_reason", String),
    Column("ingested_at", String, nullable=False),
    Column("ingested_by", String, ForeignKey("users.id"), nullable=False),
    Column("superseded_by", String, ForeignKey("documents.id")),
    UniqueConstraint("doc_code", "version"),
    CheckConstraint("status IN ('active','superseded','withdrawn')", name="documents_status"),
    Index("one_active_per_code", "doc_code", unique=True, sqlite_where=text("status = 'active'")),
)

conversations = Table(
    "conversations", metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, ForeignKey("users.id"), nullable=False),
    Column("created_at", String, nullable=False),
)

audit_log = Table(
    "audit_log", metadata,
    Column("seq", Integer, primary_key=True, autoincrement=False),  # assigned explicitly (§14.3)
    Column("event_id", String, unique=True, nullable=False),
    Column("timestamp_utc", String, nullable=False),  # ISO 8601, microseconds, 'Z'
    Column("event_type", String, nullable=False),
    Column("user_id", String, ForeignKey("users.id")),  # NULL only for unknown usernames
    Column("username", String, nullable=False),
    Column("role", String),
    Column("client_ip", String),
    Column("request_id", String),
    Column("payload_json", Text, nullable=False),
    Column("prev_hash", String, nullable=False),
    Column("row_hash", String, nullable=False),
    Index("idx_audit_time", "timestamp_utc"),
    Index("idx_audit_user", "user_id"),
    Index("idx_audit_type", "event_type"),
)

# AUD-02: no UPDATE and no DELETE, through the application or through SQL.
event.listen(audit_log, "after_create", DDL(
    "CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_log "
    "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END"))
event.listen(audit_log, "after_create", DDL(
    "CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_log "
    "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END"))

feedback = Table(
    "feedback", metadata,
    Column("id", String, primary_key=True),
    Column("query_event_id", String, ForeignKey("audit_log.event_id"), nullable=False),
    Column("user_id", String, ForeignKey("users.id"), nullable=False),
    Column("rating", Integer, nullable=False),
    Column("comment", Text),
    Column("created_at", String, nullable=False),
    UniqueConstraint("query_event_id", "user_id"),
    CheckConstraint("rating IN (-1, 1)", name="feedback_rating"),
    CheckConstraint("length(comment) <= 1000", name="feedback_comment_length"),
)

refresh_tokens = Table(
    "refresh_tokens", metadata,
    Column("jti", String, primary_key=True),  # SHA-256 of the opaque token (never the token)
    Column("user_id", String, ForeignKey("users.id"), nullable=False),
    Column("family_id", String, nullable=False),  # detects reuse of a rotated token
    Column("issued_at", String, nullable=False),
    Column("expires_at", String, nullable=False),  # absolute: 8 h from the first login
    Column("last_used_at", String, nullable=False),  # idle: 30 min
    Column("revoked", Integer, nullable=False, server_default="0"),
)
