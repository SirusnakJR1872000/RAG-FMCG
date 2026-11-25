"""Roles and permissions, defined once (PROJECT_SPEC §13.3).

The permission tests are generated from ROLE_PERMISSIONS, so the matrix in the spec, this
table and the tests cannot drift apart. Menus are hidden by role in the UI for convenience;
security is enforced only here, by the backend.
"""

PERMISSIONS = ("query:run", "history:own", "docs:read", "docs:manage", "audit:read",
               "audit:export", "users:manage", "health:details")

_VIEWER = frozenset({"query:run", "history:own", "docs:read"})

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "viewer": _VIEWER,
    "qa_user": _VIEWER | {"docs:manage"},
    # The auditor reviews the use of the system but cannot use it: no query, no feedback.
    "auditor": frozenset({"docs:read", "audit:read", "audit:export"}),
    "admin": frozenset(PERMISSIONS),
    "system": frozenset(),  # the CLI's account: it can never log in
}
LOGIN_ROLES = ("viewer", "qa_user", "auditor", "admin")


def permissions_for(role: str) -> list[str]:
    return sorted(ROLE_PERMISSIONS.get(role, frozenset()))


def has_permission(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())
