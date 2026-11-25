"""The hash chain of the audit trail (PROJECT_SPEC §14.3, §14.4).

Every row stores prev_hash (the previous row's hash) and row_hash = SHA-256(prev_hash ‖
canonical(entry)). Edit or remove any row and every hash after it stops matching, which
verify() reports with the first broken `seq`.

What this does NOT stop (§14.5): someone who rewrites the whole chain consistently. External
anchors (the latest row_hash in backups, Tier 2) make that detectable.
"""

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import Connection, select

from database.models import audit_log

GENESIS_HASH = "0" * 64
HASHED_FIELDS = ("seq", "event_id", "timestamp_utc", "event_type", "user_id", "username",
                 "role", "client_ip", "request_id")


def dump_json(value: object) -> str:
    """One JSON form for storing the payload and for hashing it: the same bytes both times."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical(entry: dict) -> bytes:
    """UTF-8 bytes of the entry as defined in §14.3 (payload as a parsed object)."""
    body = {field: entry[field] for field in HASHED_FIELDS}
    body["payload"] = entry["payload"]
    return dump_json(body).encode("utf-8")


def row_hash(prev_hash: str, entry: dict) -> str:
    return hashlib.sha256(prev_hash.encode("ascii") + canonical(entry)).hexdigest()


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    checked: int  # rows examined
    first_bad_seq: int | None = None
    reason: str | None = None

    def as_dict(self) -> dict:
        return {"ok": self.ok, "checked": self.checked, "first_bad_seq": self.first_bad_seq,
                "reason": self.reason}


def verify(conn: Connection, from_seq: int = 1) -> VerifyResult:
    """Recompute every hash from `from_seq` on; check seq continuity and the prev_hash links."""
    expected_prev = GENESIS_HASH
    if from_seq > 1:
        before = conn.execute(select(audit_log.c.row_hash).where(
            audit_log.c.seq == from_seq - 1)).scalar()
        if before is None:
            return VerifyResult(False, 0, from_seq, "the row before the checked range is missing")
        expected_prev = before
    expected_seq, checked = from_seq, 0
    rows = conn.execute(select(audit_log).where(audit_log.c.seq >= from_seq)
                        .order_by(audit_log.c.seq)).mappings()
    for row in rows:
        if row["seq"] != expected_seq:
            return VerifyResult(False, checked, expected_seq, "sequence gap: a row is missing")
        if row["prev_hash"] != expected_prev:
            return VerifyResult(False, checked, row["seq"], "prev_hash does not match the "
                                "previous row")
        try:
            payload = json.loads(row["payload_json"])
        except ValueError:
            return VerifyResult(False, checked, row["seq"], "payload is not valid JSON")
        entry = {field: row[field] for field in HASHED_FIELDS} | {"payload": payload}
        if row_hash(row["prev_hash"], entry) != row["row_hash"]:
            return VerifyResult(False, checked, row["seq"], "row content does not match its hash")
        expected_prev, expected_seq, checked = row["row_hash"], expected_seq + 1, checked + 1
    return VerifyResult(True, checked)
