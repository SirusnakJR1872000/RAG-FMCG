"""Permission matrix, password hashing and policy (PROJECT_SPEC §13.2, §13.3; SEC-03, SEC-05)."""

import pytest
from argon2 import PasswordHasher

from auth import passwords
from auth.passwords import (
    COMMON,
    REUSED,
    SAME_AS_USERNAME,
    TOO_LONG,
    TOO_SHORT,
    check_policy,
    dummy_verify,
    hash_password,
    is_common,
    needs_rehash,
    verify_password,
)
from auth.permissions import (
    LOGIN_ROLES,
    PERMISSIONS,
    ROLE_PERMISSIONS,
    has_permission,
    permissions_for,
)
from errors import ApiError, error_body, new_request_id

FAST = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)


@pytest.fixture(autouse=True)
def fast_hasher():
    passwords.configure_hasher(FAST)
    yield
    passwords.configure_hasher(PasswordHasher())


# ── the matrix of §13.3, written out independently of the code under test ────────────────

SPEC_MATRIX = {  # permission → roles that have it
    "query:run": {"viewer", "qa_user", "admin"},
    "history:own": {"viewer", "qa_user", "admin"},
    "docs:read": {"viewer", "qa_user", "auditor", "admin"},
    "docs:manage": {"qa_user", "admin"},
    "audit:read": {"auditor", "admin"},
    "audit:export": {"auditor", "admin"},
    "users:manage": {"admin"},
    "health:details": {"admin"},
}


@pytest.mark.parametrize("permission", PERMISSIONS)
@pytest.mark.parametrize("role", [*LOGIN_ROLES, "system"])
def test_SEC_02_every_role_has_exactly_the_permissions_of_the_spec_matrix(role, permission):
    assert has_permission(role, permission) == (role in SPEC_MATRIX[permission])


def test_the_matrix_covers_every_permission_and_the_auditor_cannot_query():
    assert set(SPEC_MATRIX) == set(PERMISSIONS)
    assert not has_permission("auditor", "query:run")  # using the system ≠ reviewing its use
    assert ROLE_PERMISSIONS["system"] == frozenset() and not has_permission("nobody", "docs:read")
    assert permissions_for("qa_user") == sorted(["query:run", "history:own", "docs:read",
                                                 "docs:manage"])


# ── hashing ──────────────────────────────────────────────────────────────────────────────

def test_SEC_03_passwords_are_stored_as_salted_argon2id_hashes():
    first, second = hash_password("correct horse battery"), hash_password("correct horse battery")
    assert first.startswith("$argon2id$") and first != second  # random salt per hash
    assert "correct" not in first
    assert verify_password(first, "correct horse battery")
    assert not verify_password(first, "wrong horse battery")


def test_a_placeholder_or_garbage_hash_never_verifies():
    for stored in ("!", "", "not-a-hash", "$argon2id$broken"):
        assert verify_password(stored, "!") is False


def test_old_hash_parameters_trigger_a_rehash():
    old = PasswordHasher(time_cost=1, memory_cost=512, parallelism=1).hash("some password here")
    assert needs_rehash(old) and not needs_rehash(hash_password("some password here"))


def test_the_dummy_check_runs_a_real_verification_and_returns_nothing():
    assert dummy_verify("anything") is None


# ── policy ───────────────────────────────────────────────────────────────────────────────

def policy(password, username="gpatil", recent=()):
    return check_policy(password, username=username, min_length=12, recent_hashes=list(recent))


def test_SEC_05_a_good_password_breaks_no_rule():
    assert policy("violet-lantern-orbit-42") == []


def test_SEC_05_twelve_characters_is_the_minimum():
    assert policy("a1b2c3d4e5f") == [TOO_SHORT]  # 11
    assert policy("a1b2c3d4e5f6") == []  # 12


def test_a_huge_password_is_refused():
    assert TOO_LONG in policy("x" * 129 + "!")
    assert TOO_LONG not in policy("x1" * 64)  # exactly 128


@pytest.mark.parametrize("password", ["password1234", "Password123!", "QWERTYUIOP", "welcome123",
                                      "Administrator1", "ChangeMe123!", "letmein"])
def test_common_passwords_are_refused_even_with_digits_or_symbols_added(password):
    assert is_common(password) and COMMON in policy(password)


def test_a_long_unusual_password_is_not_common():
    assert not is_common("violet-lantern-orbit-42")
    assert not is_common("pass")  # too short to match as a stem


def test_the_username_is_refused_in_any_case():
    assert SAME_AS_USERNAME in policy("GPatil-Gpatil", username="gpatil-gpatil")


def test_SEC_05_a_password_cannot_repeat_one_of_the_recent_ones():
    recent = [hash_password("old password one!"), hash_password("old password two!")]
    assert policy("old password two!", recent=recent) == [REUSED]
    assert policy("brand new password!", recent=recent) == []


def test_several_broken_rules_are_all_reported():
    assert set(policy("password", username="password")) == {TOO_SHORT, COMMON, SAME_AS_USERNAME}


# ── errors ───────────────────────────────────────────────────────────────────────────────

def test_SEC_12_the_error_body_has_a_code_a_message_and_a_request_id_only():
    rid = new_request_id()
    assert rid.startswith("req_") and len(rid) == 10
    assert error_body("LLM_TIMEOUT", "Too slow.", rid) == {
        "error": {"code": "LLM_TIMEOUT", "message": "Too slow.", "request_id": rid}}
    assert error_body("X", "y", rid, [{"field": "q"}])["error"]["details"] == [{"field": "q"}]
    err = ApiError(504, "LLM_TIMEOUT", "Too slow.", headers={"Retry-After": "5"})
    assert (err.status, err.code, str(err), err.headers) == (504, "LLM_TIMEOUT", "Too slow.",
                                                              {"Retry-After": "5"})
