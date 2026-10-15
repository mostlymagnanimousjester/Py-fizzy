"""Read and write the Fizzy tables. Callers own the transaction."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import timedelta
from pathlib import Path

from .codec import dump_dt, iso, magic_code, new_id, parse_dt, token, utcnow
from .constants import (
    BUNDLE_FREQUENCIES,
    COLOR_NAMES,
    COLOR_VALUES,
    DEFAULT_POSTPONE_DAYS,
    POSTPONE_DAYS,
    STALLED_DAYS,
    WEBHOOK_ACTIONS,
)
from .db import delete_where, enc, insert, q, q1, update as write_row
from .errors import FizzyError, forbidden, invalid, not_found
from .text import mention_ids_from_html, plain_text, to_html

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _id(conn, table, column, value):
    return enc(conn, table, column, value)


def _ids(conn, table, column, values):
    return [_id(conn, table, column, value) for value in values]


def require(row, message="Not found"):
    if row is None:
        raise not_found(message)
    return row


def update(conn, table, row_id, **cols):
    write_row(conn, table, row_id, **cols)
    if table == "cards" and "last_active_at" in cols:
        fresh = card_by_id(conn, row_id)
        if fresh and fresh.get("status") == "published":
            detect_activity_spike(conn, fresh)


# --- identity, session, tokens ---------------------------------------------

def identity_by_email(conn, email: str):
    return q1(conn, "SELECT * FROM identities WHERE lower(email_address) = ?", (email.strip().lower(),))


def identity_by_id(conn, identity_id: str):
    return q1(conn, "SELECT * FROM identities WHERE id = ?", (_id(conn, "identities", "id", identity_id),))


def create_magic_link(conn, identity_id: str, purpose: int = 0):
    code = magic_code()
    while q1(conn, "SELECT id FROM magic_links WHERE code = ?", (code,)):
        code = magic_code()
    link_id = insert(
        conn,
        "magic_links",
        code=code,
        expires_at=utcnow() + timedelta(minutes=15),
        identity_id=identity_id,
        purpose=purpose,
    )
    return q1(conn, "SELECT * FROM magic_links WHERE id = ?", (_id(conn, "magic_links", "id", link_id),))


def consume_magic_link(conn, link_id: str, code: str):
    link = q1(conn, "SELECT * FROM magic_links WHERE id = ?", (_id(conn, "magic_links", "id", link_id),))
    if not link:
        return None
    expires = parse_dt(link["expires_at"])
    if expires is None or expires < utcnow():
        return None
    if link["code"].upper() != code.strip().upper():
        return None
    delete_where(conn, "magic_links", id=link["id"])
    return identity_by_id(conn, link["identity_id"])


def create_session(conn, identity_id: str, ip: str | None, user_agent: str | None):
    session_id = insert(
        conn,
        "sessions",
        identity_id=identity_id,
        ip_address=(ip or "")[:255],
        user_agent=(user_agent or "")[:4096],
    )
    return session_id


def session_identity(conn, session_id: str):
    row = q1(
        conn,
        """
        SELECT identities.* FROM sessions
        JOIN identities ON identities.id = sessions.identity_id
        WHERE sessions.id = ?
        """,
        (_id(conn, "sessions", "id", session_id),),
    )
    return row


def delete_session(conn, session_id: str):
    delete_where(conn, "sessions", id=session_id)


def access_tokens(conn, identity_id: str):
    return q(
        conn,
        "SELECT * FROM identity_access_tokens WHERE identity_id = ? ORDER BY created_at DESC",
        (_id(conn, "identity_access_tokens", "identity_id", identity_id),),
    )


def create_access_token(conn, identity_id: str, description: str, permission: str):
    if permission not in {"read", "write"}:
        raise invalid({"permission": ["must be read or write"]})
    value = token(24)
    token_id = insert(
        conn,
        "identity_access_tokens",
        description=(description or "")[:2000],
        identity_id=identity_id,
        permission=permission,
        token=value,
    )
    row = q1(
        conn,
        "SELECT * FROM identity_access_tokens WHERE id = ?",
        (_id(conn, "identity_access_tokens", "id", token_id),),
    )
    return row


def delete_access_token(conn, identity_id: str, token_id: str):
    row = q1(
        conn,
        "SELECT * FROM identity_access_tokens WHERE id = ? AND identity_id = ?",
        (
            _id(conn, "identity_access_tokens", "id", token_id),
            _id(conn, "identity_access_tokens", "identity_id", identity_id),
        ),
    )
    require(row, "Token not found")
    delete_where(conn, "identity_access_tokens", id=token_id)


def identity_for_bearer(conn, raw_token: str):
    row = q1(conn, "SELECT * FROM identity_access_tokens WHERE token = ?", (raw_token,))
    if not row:
        return None
    identity = identity_by_id(conn, row["identity_id"])
    if not identity:
        return None
    return identity, row["permission"]


# --- accounts and users ----------------------------------------------------

def next_external_id(conn) -> int:
    row = q1(conn, "SELECT id, value FROM account_external_id_sequences LIMIT 1")
    if row is None:
        current = q1(conn, "SELECT MAX(external_account_id) AS value FROM accounts")
        start = int(current["value"] or 0) if current else 0
        new_value = start + 1
        insert(conn, "account_external_id_sequences", value=new_value)
        return new_value
    new_value = int(row["value"]) + 1
    update(conn, "account_external_id_sequences", row["id"], value=new_value)
    return new_value


def _join_code() -> str:
    raw = token(12)
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:12]}"


def create_account(conn, *, name: str, owner_name: str, identity_id: str):
    if not name.strip():
        raise invalid({"name": ["can't be blank"]})
    if not owner_name.strip():
        raise invalid({"full_name": ["can't be blank"]})
    external = next_external_id(conn)
    account_id = insert(conn, "accounts", cards_count=0, external_account_id=external, name=name.strip()[:255])
    insert(
        conn,
        "entropies",
        account_id=account_id,
        auto_postpone_period=DEFAULT_POSTPONE_DAYS * 86400,
        container_id=account_id,
        container_type="Account",
    )
    insert(conn, "users", account_id=account_id, active=True, identity_id=None, name="System", role="system")
    user_id = insert(
        conn,
        "users",
        account_id=account_id,
        active=True,
        identity_id=identity_id,
        name=owner_name.strip()[:255],
        role="owner",
        verified_at=utcnow(),
    )
    insert(
        conn,
        "user_settings",
        account_id=account_id,
        bundle_email_frequency=1,
        timezone_name=None,
        user_id=user_id,
    )
    insert(
        conn,
        "account_join_codes",
        account_id=account_id,
        code=_join_code(),
        usage_count=0,
        usage_limit=10,
    )
    return account_by_id(conn, account_id), user_by_id(conn, user_id)


def signup(conn, email: str, full_name: str, account_name: str):
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise invalid({"email_address": ["is not a valid email"]})
    if identity_by_email(conn, email):
        raise invalid({"email_address": ["already has an account — log in instead"]})
    identity_id = insert(conn, "identities", email_address=email, staff=False)
    account, user = create_account(conn, name=account_name or f"{full_name}'s Fizzy", owner_name=full_name, identity_id=identity_id)
    return identity_by_id(conn, identity_id), account, user


def accounts_for_identity(conn, identity_id: str):
    return q(
        conn,
        """
        SELECT accounts.*, users.id AS user_id
        FROM users
        JOIN accounts ON accounts.id = users.account_id
        WHERE users.identity_id = ? AND users.active = 1
        ORDER BY accounts.created_at
        """,
        (_id(conn, "users", "identity_id", identity_id),),
    )


def account_by_external(conn, external_id: int):
    return q1(conn, "SELECT * FROM accounts WHERE external_account_id = ?", (int(external_id),))


def account_by_id(conn, account_id: str):
    return q1(conn, "SELECT * FROM accounts WHERE id = ?", (_id(conn, "accounts", "id", account_id),))


def user_for_identity(conn, account_id: str, identity_id: str):
    return q1(
        conn,
        """
        SELECT users.*, identities.email_address
        FROM users
        LEFT JOIN identities ON identities.id = users.identity_id
        WHERE users.account_id = ? AND users.identity_id = ?
        """,
        (_id(conn, "users", "account_id", account_id), _id(conn, "users", "identity_id", identity_id)),
    )


def user_by_id(conn, user_id: str):
    return q1(
        conn,
        """
        SELECT users.*, identities.email_address
        FROM users
        LEFT JOIN identities ON identities.id = users.identity_id
        WHERE users.id = ?
        """,
        (_id(conn, "users", "id", user_id),),
    )


def users_in_account(conn, account_id: str, include_system: bool = False):
    sql = """
        SELECT users.*, identities.email_address
        FROM users
        LEFT JOIN identities ON identities.id = users.identity_id
        WHERE users.account_id = ?
    """
    if not include_system:
        sql += " AND users.role != 'system'"
    sql += " ORDER BY lower(users.name)"
    return q(conn, sql, (_id(conn, "users", "account_id", account_id),))


def system_user(conn, account_id: str):
    return q1(
        conn,
        "SELECT * FROM users WHERE account_id = ? AND role = 'system' LIMIT 1",
        (_id(conn, "users", "account_id", account_id),),
    )


def entropy_for(conn, account_id: str, container_type: str, container_id: str):
    return q1(
        conn,
        """
        SELECT * FROM entropies
        WHERE container_type = ? AND container_id = ?
        """,
        (container_type, _id(conn, "entropies", "container_id", container_id)),
    )


def postpone_days(conn, account_id: str, board_id: str | None = None) -> int:
    if board_id:
        row = entropy_for(conn, account_id, "Board", board_id)
        if row:
            days = int(row["auto_postpone_period"]) // 86400
            if days in POSTPONE_DAYS:
                return days
    row = entropy_for(conn, account_id, "Account", account_id)
    if row:
        days = int(row["auto_postpone_period"]) // 86400
        if days in POSTPONE_DAYS:
            return days
    return DEFAULT_POSTPONE_DAYS


def set_entropy(conn, account_id: str, container_type: str, container_id: str, days: int):
    if days not in POSTPONE_DAYS:
        raise invalid({"auto_postpone_period_in_days": [f"must be one of {', '.join(map(str, POSTPONE_DAYS))}"]})
    seconds = days * 86400
    row = entropy_for(conn, account_id, container_type, container_id)
    if row:
        update(conn, "entropies", row["id"], auto_postpone_period=seconds)
    else:
        insert(
            conn,
            "entropies",
            account_id=account_id,
            auto_postpone_period=seconds,
            container_id=container_id,
            container_type=container_type,
        )


def join_code_for(conn, account_id: str):
    return q1(
        conn,
        "SELECT * FROM account_join_codes WHERE account_id = ?",
        (_id(conn, "account_join_codes", "account_id", account_id),),
    )


def update_join_limit(conn, account_id: str, limit: int):
    if limit < 0 or limit > 10_000_000_000:
        raise invalid({"usage_limit": ["is out of range"]})
    row = require(join_code_for(conn, account_id), "Join code not found")
    update(conn, "account_join_codes", row["id"], usage_limit=limit)


def reset_join_code(conn, account_id: str):
    row = require(join_code_for(conn, account_id), "Join code not found")
    code = _join_code()
    while q1(conn, "SELECT id FROM account_join_codes WHERE code = ? AND id != ?", (code, _id(conn, "account_join_codes", "id", row["id"]))):
        code = _join_code()
    update(conn, "account_join_codes", row["id"], code=code, usage_count=0)


def join_account(conn, code: str, identity_id: str, name: str):
    row = q1(conn, "SELECT * FROM account_join_codes WHERE code = ?", (code.strip(),))
    require(row, "That join code is not active")
    if int(row["usage_count"]) >= int(row["usage_limit"]):
        raise invalid({"code": ["has been used up"]})
    existing = user_for_identity(conn, row["account_id"], identity_id)
    if existing:
        if not existing["active"]:
            update(conn, "users", existing["id"], active=True)
        return account_by_id(conn, row["account_id"]), user_by_id(conn, existing["id"])
    identity = identity_by_id(conn, identity_id)
    user_id = insert(
        conn,
        "users",
        account_id=row["account_id"],
        active=True,
        identity_id=identity_id,
        name=(name or identity["email_address"].split("@")[0])[:255],
        role="member",
        verified_at=utcnow(),
    )
    insert(
        conn,
        "user_settings",
        account_id=row["account_id"],
        bundle_email_frequency=1,
        user_id=user_id,
    )
    update(conn, "account_join_codes", row["id"], usage_count=int(row["usage_count"]) + 1)
    for board in q(
        conn,
        "SELECT id FROM boards WHERE account_id = ? AND all_access = 1",
        (_id(conn, "boards", "account_id", row["account_id"]),),
    ):
        _grant_access(conn, row["account_id"], board["id"], user_id, "access_only")
    return account_by_id(conn, row["account_id"]), user_by_id(conn, user_id)


def settings_row(conn, user_id: str):
    return q1(conn, "SELECT * FROM user_settings WHERE user_id = ?", (_id(conn, "user_settings", "user_id", user_id),))


def set_timezone(conn, user_id: str, name: str):
    row = settings_row(conn, user_id)
    if row:
        update(conn, "user_settings", row["id"], timezone_name=name[:255])
    else:
        user = user_by_id(conn, user_id)
        insert(conn, "user_settings", account_id=user["account_id"], bundle_email_frequency=1, timezone_name=name[:255], user_id=user_id)


def set_bundle_frequency(conn, user_id: str, frequency: str):
    if frequency not in BUNDLE_FREQUENCIES:
        raise invalid({"bundle_email_frequency": ["is not a supported frequency"]})
    row = require(settings_row(conn, user_id), "Settings not found")
    update(conn, "user_settings", row["id"], bundle_email_frequency=BUNDLE_FREQUENCIES.index(frequency))


def frequency_name(value) -> str:
    try:
        return BUNDLE_FREQUENCIES[int(value)]
    except (TypeError, ValueError, IndexError):
        return "never"


def update_user_name(conn, user_id: str, name: str):
    if not name.strip():
        raise invalid({"name": ["can't be blank"]})
    update(conn, "users", user_id, name=name.strip()[:255])


def set_role(conn, actor: dict, user_id: str, role: str):
    if role not in {"owner", "admin", "member"}:
        raise invalid({"role": ["is not a role"]})
    if actor["role"] not in {"owner", "admin"}:
        raise forbidden()
    target = require(user_by_id(conn, user_id))
    if target["role"] == "owner" and actor["id"] != target["id"]:
        raise forbidden("Only an owner can change another owner")
    if role != "owner" and target["role"] == "owner" and _owner_count(conn, target["account_id"]) <= 1:
        raise invalid({"role": ["the only owner can't be demoted"]})
    update(conn, "users", user_id, role=role)


def deactivate_user(conn, actor: dict, user_id: str):
    target = require(user_by_id(conn, user_id))
    if target["id"] == actor["id"]:
        raise invalid({"user": ["you can't deactivate yourself"]})
    if actor["role"] not in {"owner", "admin"} or (target["role"] == "owner" and actor["role"] != "owner"):
        raise forbidden()
    if target["role"] == "owner" and _owner_count(conn, target["account_id"]) <= 1:
        raise invalid({"user": ["the only owner can't be deactivated"]})
    update(conn, "users", user_id, active=False)


def _owner_count(conn, account_id: str) -> int:
    row = q1(
        conn,
        "SELECT COUNT(*) AS n FROM users WHERE account_id = ? AND role = 'owner' AND active = 1",
        (_id(conn, "users", "account_id", account_id),),
    )
    return int(row["n"])


def change_email(conn, user: dict, new_email: str):
    new_email = new_email.strip().lower()
    if not EMAIL_RE.match(new_email):
        raise invalid({"email_address": ["is not a valid email"]})
    if user.get("email_address") == new_email:
        raise invalid({"email_address": ["is already your email"]})
    other = identity_by_email(conn, new_email)
    if other:
        existing = user_for_identity(conn, user["account_id"], other["id"])
        if existing:
            raise invalid({"email_address": ["already belongs to someone in this account"]})
    return new_email


def apply_email_change(conn, user_id: str, new_email: str):
    user = require(user_by_id(conn, user_id))
    other = identity_by_email(conn, new_email)
    if other:
        update(conn, "users", user["id"], identity_id=other["id"])
        return
    identity_id = insert(conn, "identities", email_address=new_email, staff=False)
    update(conn, "users", user["id"], identity_id=identity_id)


# --- boards ----------------------------------------------------------------

def _grant_access(conn, account_id, board_id, user_id, involvement="access_only"):
    existing = q1(
        conn,
        "SELECT id FROM accesses WHERE board_id = ? AND user_id = ?",
        (_id(conn, "accesses", "board_id", board_id), _id(conn, "accesses", "user_id", user_id)),
    )
    if existing:
        return existing["id"]
    return insert(
        conn,
        "accesses",
        account_id=account_id,
        board_id=board_id,
        user_id=user_id,
        involvement=involvement,
        accessed_at=utcnow(),
    )


def can_see_board(conn, user: dict, board: dict) -> bool:
    if board["account_id"] != user["account_id"]:
        return False
    if board["all_access"] and user["active"] and user["role"] != "system":
        return True
    row = q1(
        conn,
        "SELECT id FROM accesses WHERE board_id = ? AND user_id = ?",
        (_id(conn, "accesses", "board_id", board["id"]), _id(conn, "accesses", "user_id", user["id"])),
    )
    return row is not None


def can_admin_board(user: dict, board: dict) -> bool:
    return user["role"] in {"owner", "admin"} or board["creator_id"] == user["id"]


def boards_for(conn, user: dict):
    return q(
        conn,
        """
        SELECT boards.* FROM boards
        LEFT JOIN accesses ON accesses.board_id = boards.id AND accesses.user_id = ?
        WHERE boards.account_id = ?
          AND (boards.all_access = 1 OR accesses.id IS NOT NULL)
        ORDER BY accesses.accessed_at IS NULL, accesses.accessed_at DESC, lower(boards.name)
        """,
        (_id(conn, "accesses", "user_id", user["id"]), _id(conn, "boards", "account_id", user["account_id"])),
    )


def board_by_id(conn, board_id: str):
    return q1(conn, "SELECT * FROM boards WHERE id = ?", (_id(conn, "boards", "id", board_id),))


def touch_access(conn, board_id: str, user_id: str):
    row = q1(
        conn,
        "SELECT id FROM accesses WHERE board_id = ? AND user_id = ?",
        (_id(conn, "accesses", "board_id", board_id), _id(conn, "accesses", "user_id", user_id)),
    )
    if row:
        update(conn, "accesses", row["id"], accessed_at=utcnow())


def create_board(conn, user: dict, name: str, all_access: bool = True, days: int | None = None):
    if not name.strip():
        raise invalid({"name": ["can't be blank"]})
    board_id = insert(
        conn,
        "boards",
        account_id=user["account_id"],
        all_access=all_access,
        creator_id=user["id"],
        name=name.strip()[:255],
    )
    _grant_access(conn, user["account_id"], board_id, user["id"], "watching")
    if all_access:
        for other in users_in_account(conn, user["account_id"]):
            if other["id"] != user["id"] and other["active"]:
                _grant_access(conn, user["account_id"], board_id, other["id"], "access_only")
    if days:
        set_entropy(conn, user["account_id"], "Board", board_id, int(days))
    return board_by_id(conn, board_id)


def update_board(conn, user: dict, board: dict, *, name=None, all_access=None, user_ids=None, public_description=None):
    if not can_admin_board(user, board):
        raise forbidden()
    cols = {}
    if name is not None:
        if not str(name).strip():
            raise invalid({"name": ["can't be blank"]})
        cols["name"] = str(name).strip()[:255]
    if all_access is not None:
        cols["all_access"] = bool(all_access)
    if cols:
        update(conn, "boards", board["id"], **cols)
    if all_access is True:
        for other in users_in_account(conn, board["account_id"]):
            if other["active"]:
                _grant_access(conn, board["account_id"], board["id"], other["id"], "watching" if other["id"] == board["creator_id"] else "access_only")
    if user_ids is not None:
        keep = set(user_ids) | {board["creator_id"]}
        current = q(
            conn,
            "SELECT id, user_id FROM accesses WHERE board_id = ?",
            (_id(conn, "accesses", "board_id", board["id"]),),
        )
        for access in current:
            if access["user_id"] not in keep:
                delete_where(conn, "accesses", id=access["id"])
        for user_id in keep:
            member = user_by_id(conn, user_id)
            if member and member["account_id"] == board["account_id"]:
                _grant_access(conn, board["account_id"], board["id"], user_id, "watching" if user_id == board["creator_id"] else "access_only")
    if public_description is not None:
        _write_rich(conn, board["account_id"], "Board", board["id"], "public_description", public_description)
    return board_by_id(conn, board["id"])


def delete_board(conn, user: dict, board: dict):
    if not can_admin_board(user, board):
        raise forbidden()
    cards = q(conn, "SELECT id FROM cards WHERE board_id = ?", (_id(conn, "cards", "board_id", board["id"]),))
    for card in cards:
        delete_card(conn, user, card_by_id(conn, card["id"]), force=True)
    for table, column in (
        ("columns", "board_id"),
        ("events", "board_id"),
        ("accesses", "board_id"),
        ("board_publications", "board_id"),
    ):
        conn.execute(f'DELETE FROM "{table}" WHERE "{column}" = ?', (_id(conn, table, column, board["id"]),))
    hooks = q(conn, "SELECT id FROM webhooks WHERE board_id = ?", (_id(conn, "webhooks", "board_id", board["id"]),))
    for hook in hooks:
        delete_where(conn, "webhook_deliveries", webhook_id=hook["id"])
        delete_where(conn, "webhook_delinquency_trackers", webhook_id=hook["id"])
        delete_where(conn, "webhooks", id=hook["id"])
    ent = entropy_for(conn, board["account_id"], "Board", board["id"])
    if ent:
        delete_where(conn, "entropies", id=ent["id"])
    _delete_rich(conn, "Board", board["id"], "public_description")
    delete_where(conn, "boards", id=board["id"])


def board_user_ids(conn, board_id: str) -> list[str]:
    rows = q(conn, "SELECT user_id FROM accesses WHERE board_id = ? ORDER BY created_at", (_id(conn, "accesses", "board_id", board_id),))
    return [row["user_id"] for row in rows]


def publish_board(conn, user: dict, board: dict):
    if not can_admin_board(user, board):
        raise forbidden()
    existing = publication(conn, board["id"])
    if existing:
        return existing
    key = token(16)
    while q1(conn, "SELECT id FROM board_publications WHERE key = ?", (key,)):
        key = token(16)
    insert(conn, "board_publications", account_id=board["account_id"], board_id=board["id"], key=key)
    return publication(conn, board["id"])


def unpublish_board(conn, user: dict, board: dict):
    if not can_admin_board(user, board):
        raise forbidden()
    row = publication(conn, board["id"])
    if row:
        delete_where(conn, "board_publications", id=row["id"])


def publication(conn, board_id: str):
    return q1(conn, "SELECT * FROM board_publications WHERE board_id = ?", (_id(conn, "board_publications", "board_id", board_id),))


def board_by_publication_key(conn, key: str):
    row = q1(conn, "SELECT * FROM board_publications WHERE key = ?", (key,))
    if not row:
        return None, None
    return board_by_id(conn, row["board_id"]), row


# --- columns ---------------------------------------------------------------

def columns_for(conn, board_id: str):
    return q(
        conn,
        "SELECT * FROM columns WHERE board_id = ? ORDER BY position, created_at",
        (_id(conn, "columns", "board_id", board_id),),
    )


def column_by_id(conn, column_id: str):
    return q1(conn, "SELECT * FROM columns WHERE id = ?", (_id(conn, "columns", "id", column_id),))


def normalize_color(value: str | None) -> str:
    if not value:
        return "var(--color-card-default)"
    text = str(value).strip()
    if text in COLOR_VALUES:
        return text
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and parsed.get("value") in COLOR_VALUES:
                return parsed["value"]
        except json.JSONDecodeError:
            pass
    for name, css in COLOR_NAMES.items():
        if text.lower() == name.lower():
            return css
    raise invalid({"color": ["is not a column color"]})


def create_column(conn, user: dict, board: dict, name: str, color: str | None = None):
    if not can_see_board(conn, user, board):
        raise forbidden()
    if not name.strip():
        raise invalid({"name": ["can't be blank"]})
    current = columns_for(conn, board["id"])
    position = (max((int(col["position"]) for col in current), default=-1) + 1)
    column_id = insert(
        conn,
        "columns",
        account_id=board["account_id"],
        board_id=board["id"],
        color=normalize_color(color),
        name=name.strip()[:255],
        position=position,
    )
    return column_by_id(conn, column_id)


def update_column(conn, user: dict, column: dict, *, name=None, color=None, position=None):
    board = require(board_by_id(conn, column["board_id"]))
    if not can_admin_board(user, board) and board["creator_id"] != user["id"]:
        if not can_see_board(conn, user, board):
            raise forbidden()
    cols = {}
    if name is not None:
        if not str(name).strip():
            raise invalid({"name": ["can't be blank"]})
        cols["name"] = str(name).strip()[:255]
    if color is not None:
        cols["color"] = normalize_color(color)
    if position is not None:
        cols["position"] = int(position)
    if cols:
        update(conn, "columns", column["id"], **cols)
    return column_by_id(conn, column["id"])


def delete_column(conn, user: dict, column: dict):
    board = require(board_by_id(conn, column["board_id"]))
    if not can_admin_board(user, board):
        raise forbidden()
    conn.execute(
        "UPDATE cards SET column_id = NULL, updated_at = ? WHERE column_id = ?",
        (dump_dt(utcnow()), _id(conn, "cards", "column_id", column["id"])),
    )
    delete_where(conn, "columns", id=column["id"])


def move_column(conn, user: dict, column: dict, direction: int):
    siblings = columns_for(conn, column["board_id"])
    index = next(i for i, col in enumerate(siblings) if col["id"] == column["id"])
    target = index + direction
    if target < 0 or target >= len(siblings):
        return siblings
    siblings[index], siblings[target] = siblings[target], siblings[index]
    for position, col in enumerate(siblings):
        update(conn, "columns", col["id"], position=position)
    return columns_for(conn, column["board_id"])


# --- rich text -------------------------------------------------------------

def rich_text(conn, record_type: str, record_id: str, name: str):
    return q1(
        conn,
        "SELECT * FROM action_text_rich_texts WHERE record_type = ? AND record_id = ? AND name = ?",
        (record_type, _id(conn, "action_text_rich_texts", "record_id", record_id), name),
    )


def _write_rich(conn, account_id, record_type, record_id, name, value):
    html = to_html(value)
    existing = rich_text(conn, record_type, record_id, name)
    if not html:
        if existing:
            delete_where(conn, "action_text_rich_texts", id=existing["id"])
        return
    if existing:
        update(conn, "action_text_rich_texts", existing["id"], body=html)
    else:
        insert(
            conn,
            "action_text_rich_texts",
            account_id=account_id,
            body=html,
            name=name,
            record_id=record_id,
            record_type=record_type,
        )


def _delete_rich(conn, record_type, record_id, name):
    existing = rich_text(conn, record_type, record_id, name)
    if existing:
        delete_where(conn, "action_text_rich_texts", id=existing["id"])


def rich_map(conn, record_type: str, record_ids: list[str], name: str) -> dict[str, str]:
    if not record_ids:
        return {}
    marks = ",".join("?" for _ in record_ids)
    rows = q(
        conn,
        f"""
        SELECT record_id, body FROM action_text_rich_texts
        WHERE record_type = ? AND name = ? AND record_id IN ({marks})
        """,
        [record_type, name, *_ids(conn, "action_text_rich_texts", "record_id", record_ids)],
    )
    return {row["record_id"]: row["body"] or "" for row in rows}


# --- cards -----------------------------------------------------------------

def card_by_id(conn, card_id: str):
    return q1(conn, "SELECT * FROM cards WHERE id = ?", (_id(conn, "cards", "id", card_id),))


def card_by_number(conn, account_id: str, number: int):
    return q1(
        conn,
        "SELECT * FROM cards WHERE account_id = ? AND number = ?",
        (_id(conn, "cards", "account_id", account_id), int(number)),
    )


def _next_number(conn, account_id: str) -> int:
    row = q1(conn, "SELECT cards_count FROM accounts WHERE id = ?", (_id(conn, "accounts", "id", account_id),))
    number = int(row["cards_count"]) + 1
    update(conn, "accounts", account_id, cards_count=number)
    return number


def create_card(conn, user: dict, board: dict, *, title: str | None, description: str | None = None,
                status: str = "published", column_id: str | None = None, created_at=None, last_active_at=None,
                tag_titles: list[str] | None = None):
    if not can_see_board(conn, user, board):
        raise forbidden()
    if status not in {"drafted", "published"}:
        raise invalid({"status": ["must be drafted or published"]})
    now = parse_dt(created_at) or utcnow() if created_at else utcnow()
    active_at = parse_dt(last_active_at) or now if last_active_at else now
    clean_title = (title or "").strip()
    if status == "published" and not clean_title:
        clean_title = "Untitled"
    if column_id:
        column = require(column_by_id(conn, column_id), "Column not found")
        if column["board_id"] != board["id"]:
            raise invalid({"column_id": ["is not on this board"]})
    card_id = insert(
        conn,
        "cards",
        account_id=board["account_id"],
        board_id=board["id"],
        column_id=column_id,
        creator_id=user["id"],
        due_on=None,
        last_active_at=active_at,
        number=_next_number(conn, board["account_id"]),
        status=status,
        title=clean_title[:255] or None,
        created_at=now,
    )
    if description:
        _write_rich(conn, board["account_id"], "Card", card_id, "description", description)
    _watch(conn, board["account_id"], card_id, user["id"], True)
    if status == "published":
        _event(conn, user, board, "Card", card_id, "card_published", {})
    for tag_title in tag_titles or []:
        toggle_tag(conn, user, card_by_id(conn, card_id), tag_title, force_on=True)
    update(conn, "boards", board["id"])
    return card_by_id(conn, card_id)


def update_card(conn, user: dict, card: dict, *, title=None, description=None, status=None, last_active_at=None, tag_titles=None):
    board = require(board_by_id(conn, card["board_id"]))
    if not can_see_board(conn, user, board):
        raise forbidden()
    cols = {}
    if title is not None and title != card["title"]:
        cols["title"] = (str(title).strip() or "Untitled")[:255]
    if status is not None:
        if status not in {"drafted", "published"}:
            raise invalid({"status": ["must be drafted or published"]})
        if status != card["status"]:
            cols["status"] = status
    if last_active_at is not None:
        cols["last_active_at"] = parse_dt(last_active_at) or utcnow()
    if (cols or description is not None or tag_titles is not None) and "last_active_at" not in cols:
        cols["last_active_at"] = utcnow()
    if cols:
        update(conn, "cards", card["id"], **cols)
    if title is not None and card["status"] == "published" and title != card["title"]:
        _event(conn, user, board, "Card", card["id"], "card_title_changed", {"particulars": {"old_title": card["title"] or "", "new_title": cols.get("title", "")}})
    if status == "published" and card["status"] != "published":
        _event(conn, user, board, "Card", card["id"], "card_published", {})
    if description is not None:
        _write_rich(conn, card["account_id"], "Card", card["id"], "description", description)
        _sync_mentions(conn, user, "Card", card["id"], description, card)
    if tag_titles is not None:
        current = {tag["title"] for tag in tags_for_card(conn, card["id"])}
        wanted = {title.lstrip("#").strip() for title in tag_titles if title.strip()}
        for name in wanted - current:
            toggle_tag(conn, user, card, name, force_on=True)
        for name in current - wanted:
            toggle_tag(conn, user, card, name, force_off=True)
    update(conn, "boards", board["id"])
    return card_by_id(conn, card["id"])


def delete_card(conn, user: dict, card: dict, force: bool = False):
    board = board_by_id(conn, card["board_id"])
    if not force:
        if user["role"] not in {"owner", "admin"} and card["creator_id"] != user["id"]:
            raise forbidden()
    comments = q(conn, "SELECT id FROM comments WHERE card_id = ?", (_id(conn, "comments", "card_id", card["id"]),))
    comment_ids = [row["id"] for row in comments]
    conn.execute("DELETE FROM notifications WHERE card_id = ?", (_id(conn, "notifications", "card_id", card["id"]),))
    conn.execute(
        "DELETE FROM events WHERE eventable_type = 'Card' AND eventable_id = ?",
        (_id(conn, "events", "eventable_id", card["id"]),),
    )
    if comment_ids:
        marks = ",".join("?" * len(comment_ids))
        encoded = _ids(conn, "events", "eventable_id", comment_ids)
        conn.execute(
            f"DELETE FROM events WHERE eventable_type = 'Comment' AND eventable_id IN ({marks})",
            encoded,
        )
        conn.execute(
            f"DELETE FROM reactions WHERE reactable_type = 'Comment' AND reactable_id IN ({marks})",
            _ids(conn, "reactions", "reactable_id", comment_ids),
        )
        conn.execute(
            f"DELETE FROM mentions WHERE source_type = 'Comment' AND source_id IN ({marks})",
            _ids(conn, "mentions", "source_id", comment_ids),
        )
        for comment_id in comment_ids:
            _delete_rich(conn, "Comment", comment_id, "body")
    for table in ("comments", "steps", "taggings", "assignments", "watches", "pins", "closures", "card_not_nows", "card_goldnesses", "card_activity_spikes"):
        conn.execute(f'DELETE FROM "{table}" WHERE card_id = ?', (_id(conn, table, "card_id", card["id"]),))
    conn.execute(
        "DELETE FROM reactions WHERE reactable_type = 'Card' AND reactable_id = ?",
        (_id(conn, "reactions", "reactable_id", card["id"]),),
    )
    conn.execute(
        "DELETE FROM mentions WHERE source_type = 'Card' AND source_id = ?",
        (_id(conn, "mentions", "source_id", card["id"]),),
    )
    _delete_rich(conn, "Card", card["id"], "description")
    _purge_attachments(conn, "Card", card["id"])
    delete_where(conn, "cards", id=card["id"])
    if board:
        update(conn, "boards", board["id"])


def closure_of(conn, card_id: str):
    return q1(conn, "SELECT * FROM closures WHERE card_id = ?", (_id(conn, "closures", "card_id", card_id),))


def not_now_of(conn, card_id: str):
    return q1(conn, "SELECT * FROM card_not_nows WHERE card_id = ?", (_id(conn, "card_not_nows", "card_id", card_id),))


def gold_of(conn, card_id: str):
    return q1(conn, "SELECT * FROM card_goldnesses WHERE card_id = ?", (_id(conn, "card_goldnesses", "card_id", card_id),))


def spike_of(conn, card_id: str):
    return q1(conn, "SELECT * FROM card_activity_spikes WHERE card_id = ?", (_id(conn, "card_activity_spikes", "card_id", card_id),))


def detect_activity_spike(conn, card: dict) -> bool:
    """Ruby Card::ActivitySpike::Detector. Touch the spike row when an entropic card just got busy."""
    if not card or card.get("status") != "published" or not card.get("last_active_at"):
        return False
    period_days = postpone_days(conn, card["account_id"], card["board_id"])
    recent_start = utcnow() - timedelta(seconds=period_days * 86400 * 0.33)
    comments = q(
        conn,
        "SELECT creator_id FROM comments WHERE card_id = ? AND created_at >= ?",
        (_id(conn, "comments", "card_id", card["id"]), dump_dt(recent_start)),
    )
    spiked = len(comments) >= 3 and len({row["creator_id"] for row in comments}) >= 2
    if not spiked:
        last = q1(
            conn,
            """
            SELECT action, created_at FROM events
            WHERE eventable_type = 'Card' AND eventable_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (_id(conn, "events", "eventable_id", card["id"]),),
        )
        when = parse_dt(last["created_at"]) if last else None
        if last and when and when > utcnow() - timedelta(minutes=1):
            if last["action"] == "card_assigned" and assignees_of(conn, card["id"]):
                spiked = True
            elif last["action"] == "card_reopened" and closure_of(conn, card["id"]) is None:
                spiked = True
    if not spiked:
        return False
    existing = spike_of(conn, card["id"])
    if existing:
        write_row(conn, "card_activity_spikes", existing["id"])
    else:
        insert(conn, "card_activity_spikes", account_id=card["account_id"], card_id=card["id"])
    return True


def _resume(conn, card: dict):
    closure = closure_of(conn, card["id"])
    if closure:
        delete_where(conn, "closures", id=closure["id"])
    postponed = not_now_of(conn, card["id"])
    if postponed:
        delete_where(conn, "card_not_nows", id=postponed["id"])
    spike = q1(conn, "SELECT id FROM card_activity_spikes WHERE card_id = ?", (_id(conn, "card_activity_spikes", "card_id", card["id"]),))
    if spike:
        delete_where(conn, "card_activity_spikes", id=spike["id"])


def close_card(conn, user: dict, card: dict):
    board = require(board_by_id(conn, card["board_id"]))
    if closure_of(conn, card["id"]):
        return
    postponed = not_now_of(conn, card["id"])
    if postponed:
        delete_where(conn, "card_not_nows", id=postponed["id"])
    insert(conn, "closures", account_id=card["account_id"], card_id=card["id"], user_id=user["id"])
    update(conn, "cards", card["id"], last_active_at=utcnow())
    _event(conn, user, board, "Card", card["id"], "card_closed", {})


def reopen_card(conn, user: dict, card: dict):
    board = require(board_by_id(conn, card["board_id"]))
    closure = closure_of(conn, card["id"])
    if not closure:
        return
    delete_where(conn, "closures", id=closure["id"])
    update(conn, "cards", card["id"], last_active_at=utcnow())
    _event(conn, user, board, "Card", card["id"], "card_reopened", {})


def postpone_card(conn, user: dict, card: dict, action: str = "card_postponed"):
    board = require(board_by_id(conn, card["board_id"]))
    _resume(conn, card)
    update(conn, "cards", card["id"], column_id=None, last_active_at=card["last_active_at"])
    if not not_now_of(conn, card["id"]):
        insert(conn, "card_not_nows", account_id=card["account_id"], card_id=card["id"], user_id=user["id"])
    _event(conn, user, board, "Card", card["id"], action, {})


def triage_card(conn, user: dict, card: dict, column_id: str):
    board = require(board_by_id(conn, card["board_id"]))
    column = require(column_by_id(conn, column_id), "Column not found")
    if column["board_id"] != card["board_id"]:
        raise invalid({"column_id": ["is not on this card's board"]})
    was_closed = closure_of(conn, card["id"]) is not None
    _resume(conn, card)
    update(conn, "cards", card["id"], column_id=column["id"], last_active_at=utcnow())
    if was_closed:
        _event(conn, user, board, "Card", card["id"], "card_reopened", {})
    _event(conn, user, board, "Card", card["id"], "card_triaged", {"particulars": {"column": column["name"]}})


def untriage_card(conn, user: dict, card: dict):
    board = require(board_by_id(conn, card["board_id"]))
    _resume(conn, card)
    update(conn, "cards", card["id"], column_id=None, last_active_at=utcnow())
    _event(conn, user, board, "Card", card["id"], "card_sent_back_to_triage", {})


def move_card_board(conn, user: dict, card: dict, new_board_id: str):
    new_board = require(board_by_id(conn, new_board_id), "Board not found")
    if not can_see_board(conn, user, new_board):
        raise forbidden()
    old_board = require(board_by_id(conn, card["board_id"]))
    if new_board["id"] == old_board["id"]:
        return card
    update(conn, "cards", card["id"], board_id=new_board["id"], column_id=None, last_active_at=utcnow())
    conn.execute(
        "UPDATE events SET board_id = ? WHERE eventable_type = 'Card' AND eventable_id = ?",
        (_id(conn, "events", "board_id", new_board["id"]), _id(conn, "events", "eventable_id", card["id"])),
    )
    _event(
        conn,
        user,
        new_board,
        "Card",
        card["id"],
        "card_board_changed",
        {"particulars": {"old_board": old_board["name"], "new_board": new_board["name"]}},
    )
    return card_by_id(conn, card["id"])


def toggle_gold(conn, user: dict, card: dict, on: bool):
    if not can_see_board(conn, user, require(board_by_id(conn, card["board_id"]))):
        raise forbidden()
    existing = gold_of(conn, card["id"])
    if on and not existing:
        insert(conn, "card_goldnesses", account_id=card["account_id"], card_id=card["id"])
    if not on and existing:
        delete_where(conn, "card_goldnesses", id=existing["id"])
    update(conn, "cards", card["id"], last_active_at=utcnow())


def _watch(conn, account_id, card_id, user_id, watching: bool):
    row = q1(
        conn,
        "SELECT * FROM watches WHERE card_id = ? AND user_id = ?",
        (_id(conn, "watches", "card_id", card_id), _id(conn, "watches", "user_id", user_id)),
    )
    if row:
        update(conn, "watches", row["id"], watching=watching)
        return
    insert(conn, "watches", account_id=account_id, card_id=card_id, user_id=user_id, watching=watching)


def set_watch(conn, user: dict, card: dict, watching: bool):
    _watch(conn, card["account_id"], card["id"], user["id"], watching)


def is_watching(conn, card_id: str, user_id: str) -> bool:
    row = q1(
        conn,
        "SELECT watching FROM watches WHERE card_id = ? AND user_id = ?",
        (_id(conn, "watches", "card_id", card_id), _id(conn, "watches", "user_id", user_id)),
    )
    return bool(row and row["watching"])


def watchers(conn, card_id: str):
    return q(
        conn,
        """
        SELECT users.* FROM watches
        JOIN users ON users.id = watches.user_id
        WHERE watches.card_id = ? AND watches.watching = 1 AND users.active = 1
        """,
        (_id(conn, "watches", "card_id", card_id),),
    )


def board_watchers(conn, board_id: str):
    return q(
        conn,
        """
        SELECT users.* FROM accesses
        JOIN users ON users.id = accesses.user_id
        WHERE accesses.board_id = ? AND accesses.involvement = 'watching' AND users.active = 1
        """,
        (_id(conn, "accesses", "board_id", board_id),),
    )


def toggle_pin(conn, user: dict, card: dict, on: bool):
    row = q1(
        conn,
        "SELECT * FROM pins WHERE card_id = ? AND user_id = ?",
        (_id(conn, "pins", "card_id", card["id"]), _id(conn, "pins", "user_id", user["id"])),
    )
    if on and not row:
        insert(conn, "pins", account_id=card["account_id"], card_id=card["id"], user_id=user["id"])
    if not on and row:
        delete_where(conn, "pins", id=row["id"])


def pins_for_user(conn, user: dict):
    return q(
        conn,
        """
        SELECT cards.* FROM pins
        JOIN cards ON cards.id = pins.card_id
        WHERE pins.user_id = ?
        ORDER BY pins.created_at DESC
        """,
        (_id(conn, "pins", "user_id", user["id"]),),
    )


def is_pinned(conn, card_id: str, user_id: str) -> bool:
    return q1(
        conn,
        "SELECT id FROM pins WHERE card_id = ? AND user_id = ?",
        (_id(conn, "pins", "card_id", card_id), _id(conn, "pins", "user_id", user_id)),
    ) is not None


def tags_for_card(conn, card_id: str):
    return q(
        conn,
        """
        SELECT tags.* FROM taggings
        JOIN tags ON tags.id = taggings.tag_id
        WHERE taggings.card_id = ?
        ORDER BY lower(tags.title)
        """,
        (_id(conn, "taggings", "card_id", card_id),),
    )


def tags_in_account(conn, account_id: str):
    return q(
        conn,
        "SELECT * FROM tags WHERE account_id = ? ORDER BY lower(title)",
        (_id(conn, "tags", "account_id", account_id),),
    )


def toggle_tag(conn, user: dict, card: dict, title: str, force_on: bool = False, force_off: bool = False):
    title = title.lstrip("#").strip()
    if not title:
        raise invalid({"tag_title": ["can't be blank"]})
    tag = q1(
        conn,
        "SELECT * FROM tags WHERE account_id = ? AND title = ?",
        (_id(conn, "tags", "account_id", card["account_id"]), title[:255]),
    )
    if tag is None:
        if force_off:
            return
        tag_id = insert(conn, "tags", account_id=card["account_id"], title=title[:255])
        tag = q1(conn, "SELECT * FROM tags WHERE id = ?", (_id(conn, "tags", "id", tag_id),))
    tagging = q1(
        conn,
        "SELECT * FROM taggings WHERE card_id = ? AND tag_id = ?",
        (_id(conn, "taggings", "card_id", card["id"]), _id(conn, "taggings", "tag_id", tag["id"])),
    )
    if tagging and not force_on:
        delete_where(conn, "taggings", id=tagging["id"])
    elif not tagging and not force_off:
        insert(conn, "taggings", account_id=card["account_id"], card_id=card["id"], tag_id=tag["id"])
    update(conn, "cards", card["id"], last_active_at=utcnow())


def assignees_of(conn, card_id: str):
    return q(
        conn,
        """
        SELECT users.*, identities.email_address FROM assignments
        JOIN users ON users.id = assignments.assignee_id
        LEFT JOIN identities ON identities.id = users.identity_id
        WHERE assignments.card_id = ?
        ORDER BY assignments.created_at
        """,
        (_id(conn, "assignments", "card_id", card_id),),
    )


def toggle_assignment(conn, user: dict, card: dict, assignee_id: str):
    board = require(board_by_id(conn, card["board_id"]))
    assignee = require(user_by_id(conn, assignee_id), "User not found")
    if assignee["account_id"] != card["account_id"] or assignee["role"] == "system":
        raise invalid({"assignee_id": ["is not a member of this account"]})
    existing = q1(
        conn,
        "SELECT * FROM assignments WHERE card_id = ? AND assignee_id = ?",
        (_id(conn, "assignments", "card_id", card["id"]), _id(conn, "assignments", "assignee_id", assignee_id)),
    )
    if existing:
        delete_where(conn, "assignments", id=existing["id"])
        _event(conn, user, board, "Card", card["id"], "card_unassigned", {"assignee_ids": [assignee_id]})
    else:
        insert(
            conn,
            "assignments",
            account_id=card["account_id"],
            assignee_id=assignee_id,
            assigner_id=user["id"],
            card_id=card["id"],
        )
        _watch(conn, card["account_id"], card["id"], assignee_id, True)
        if not board["all_access"]:
            _grant_access(conn, card["account_id"], board["id"], assignee_id, "access_only")
        _event(conn, user, board, "Card", card["id"], "card_assigned", {"assignee_ids": [assignee_id]})
        _notify_users(conn, card, user, [assignee_id], "Event", _last_event_id(conn, card["id"]))
    update(conn, "cards", card["id"], last_active_at=utcnow())


def steps_of(conn, card_id: str):
    return q(
        conn,
        "SELECT * FROM steps WHERE card_id = ? ORDER BY created_at, id",
        (_id(conn, "steps", "card_id", card_id),),
    )


def step_by_id(conn, step_id: str):
    return q1(conn, "SELECT * FROM steps WHERE id = ?", (_id(conn, "steps", "id", step_id),))


def create_step(conn, user: dict, card: dict, content: str, completed: bool = False):
    if not content.strip():
        raise invalid({"content": ["can't be blank"]})
    step_id = insert(
        conn,
        "steps",
        account_id=card["account_id"],
        card_id=card["id"],
        completed=completed,
        content=content.strip(),
    )
    update(conn, "cards", card["id"], last_active_at=utcnow())
    return step_by_id(conn, step_id)


def update_step(conn, user: dict, step: dict, *, content=None, completed=None):
    cols = {}
    if content is not None:
        if not str(content).strip():
            raise invalid({"content": ["can't be blank"]})
        cols["content"] = str(content).strip()
    if completed is not None:
        cols["completed"] = bool(completed)
    if cols:
        update(conn, "steps", step["id"], **cols)
    update(conn, "cards", step["card_id"], last_active_at=utcnow())
    return step_by_id(conn, step["id"])


def delete_step(conn, step: dict):
    delete_where(conn, "steps", id=step["id"])


def comments_of(conn, card_id: str):
    return q(
        conn,
        "SELECT * FROM comments WHERE card_id = ? ORDER BY created_at, id",
        (_id(conn, "comments", "card_id", card_id),),
    )


def comment_by_id(conn, comment_id: str):
    return q1(conn, "SELECT * FROM comments WHERE id = ?", (_id(conn, "comments", "id", comment_id),))


def create_comment(conn, user: dict, card: dict, body: str, created_at=None):
    if not str(body or "").strip():
        raise invalid({"body": ["can't be blank"]})
    when = parse_dt(created_at) or utcnow() if created_at else utcnow()
    comment_id = insert(
        conn,
        "comments",
        account_id=card["account_id"],
        card_id=card["id"],
        creator_id=user["id"],
        created_at=when,
    )
    _write_rich(conn, card["account_id"], "Comment", comment_id, "body", body)
    _watch(conn, card["account_id"], card["id"], user["id"], True)
    board = require(board_by_id(conn, card["board_id"]))
    event_id = _event(conn, user, board, "Comment", comment_id, "comment_created", {})
    update(conn, "cards", card["id"], last_active_at=utcnow())
    mentioned = _sync_mentions(conn, user, "Comment", comment_id, body, card)
    recipients = {row["id"] for row in watchers(conn, card["id"])}
    recipients -= {user["id"]}
    recipients |= set(mentioned)
    recipients.discard(user["id"])
    _notify_users(conn, card, user, recipients, "Event", event_id)
    return comment_by_id(conn, comment_id)


def update_comment(conn, user: dict, comment: dict, body: str):
    if comment["creator_id"] != user["id"] and user["role"] not in {"owner", "admin"}:
        raise forbidden()
    if not str(body or "").strip():
        raise invalid({"body": ["can't be blank"]})
    _write_rich(conn, comment["account_id"], "Comment", comment["id"], "body", body)
    card = require(card_by_id(conn, comment["card_id"]))
    _sync_mentions(conn, user, "Comment", comment["id"], body, card)
    return comment_by_id(conn, comment["id"])


def delete_comment(conn, user: dict, comment: dict):
    if comment["creator_id"] != user["id"] and user["role"] not in {"owner", "admin"}:
        raise forbidden()
    conn.execute(
        "DELETE FROM events WHERE eventable_type = 'Comment' AND eventable_id = ?",
        (_id(conn, "events", "eventable_id", comment["id"]),),
    )
    conn.execute(
        "DELETE FROM reactions WHERE reactable_type = 'Comment' AND reactable_id = ?",
        (_id(conn, "reactions", "reactable_id", comment["id"]),),
    )
    conn.execute(
        "DELETE FROM mentions WHERE source_type = 'Comment' AND source_id = ?",
        (_id(conn, "mentions", "source_id", comment["id"]),),
    )
    _delete_rich(conn, "Comment", comment["id"], "body")
    delete_where(conn, "comments", id=comment["id"])


def reactions_of(conn, reactable_type: str, reactable_id: str):
    return q(
        conn,
        """
        SELECT reactions.* FROM reactions
        WHERE reactable_type = ? AND reactable_id = ?
        ORDER BY created_at
        """,
        (reactable_type, _id(conn, "reactions", "reactable_id", reactable_id)),
    )


def add_reaction(conn, user: dict, account_id: str, reactable_type: str, reactable_id: str, content: str):
    content = content.strip()
    if not content or len(content) > 16:
        raise invalid({"content": ["must be 1 to 16 characters"]})
    existing = q1(
        conn,
        """
        SELECT * FROM reactions
        WHERE reactable_type = ? AND reactable_id = ? AND reacter_id = ? AND content = ?
        """,
        (
            reactable_type,
            _id(conn, "reactions", "reactable_id", reactable_id),
            _id(conn, "reactions", "reacter_id", user["id"]),
            content,
        ),
    )
    if existing:
        return existing
    reaction_id = insert(
        conn,
        "reactions",
        account_id=account_id,
        content=content,
        reactable_id=reactable_id,
        reactable_type=reactable_type,
        reacter_id=user["id"],
    )
    return q1(conn, "SELECT * FROM reactions WHERE id = ?", (_id(conn, "reactions", "id", reaction_id),))


def delete_reaction(conn, user: dict, reaction_id: str):
    row = require(q1(conn, "SELECT * FROM reactions WHERE id = ?", (_id(conn, "reactions", "id", reaction_id),)))
    if row["reacter_id"] != user["id"] and user["role"] not in {"owner", "admin"}:
        raise forbidden()
    delete_where(conn, "reactions", id=reaction_id)


# --- events and notifications ----------------------------------------------

def _event(conn, user: dict, board: dict, eventable_type: str, eventable_id: str, action: str, particulars: dict) -> str:
    event_id = insert(
        conn,
        "events",
        account_id=board["account_id"],
        action=action,
        board_id=board["id"],
        creator_id=user["id"],
        eventable_id=eventable_id,
        eventable_type=eventable_type,
        particulars=particulars or {},
    )
    if action != "card_assigned":
        card_id = eventable_id if eventable_type == "Card" else None
        if eventable_type == "Comment":
            comment = comment_by_id(conn, eventable_id)
            card_id = comment["card_id"] if comment else None
        if card_id and action != "comment_created":
            card = card_by_id(conn, card_id)
            recipients = {row["id"] for row in watchers(conn, card_id)}
            if action == "card_published":
                recipients |= {row["id"] for row in board_watchers(conn, board["id"])}
            recipients.discard(user["id"])
            _notify_users(conn, card, user, recipients, "Event", event_id)
    _dispatch_webhooks(conn, board, event_id, action)
    return event_id


def _last_event_id(conn, card_id: str):
    row = q1(
        conn,
        """
        SELECT id FROM events
        WHERE eventable_type = 'Card' AND eventable_id = ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (_id(conn, "events", "eventable_id", card_id),),
    )
    return row["id"] if row else None


def _notify_users(conn, card: dict, actor: dict, user_ids, source_type: str, source_id: str | None):
    if not source_id:
        return
    for user_id in user_ids:
        if not user_id or user_id == actor["id"]:
            continue
        existing = q1(
            conn,
            "SELECT * FROM notifications WHERE user_id = ? AND card_id = ?",
            (_id(conn, "notifications", "user_id", user_id), _id(conn, "notifications", "card_id", card["id"])),
        )
        if existing:
            update(
                conn,
                "notifications",
                existing["id"],
                creator_id=actor["id"],
                read_at=None,
                source_id=source_id,
                source_type=source_type,
                unread_count=int(existing["unread_count"] or 0) + 1,
            )
        else:
            insert(
                conn,
                "notifications",
                account_id=card["account_id"],
                card_id=card["id"],
                creator_id=actor["id"],
                read_at=None,
                source_id=source_id,
                source_type=source_type,
                unread_count=1,
                user_id=user_id,
            )


def _sync_mentions(conn, user: dict, source_type: str, source_id: str, raw: str, card: dict) -> list[str]:
    html = to_html(raw)
    ids = set(mention_ids_from_html(html))
    plain = plain_text(html)
    members = users_in_account(conn, card["account_id"])
    names = sorted(((member["name"], member["id"]) for member in members if member["active"]), key=lambda item: len(item[0]), reverse=True)
    lowered = plain.lower()
    for name, member_id in names:
        if name and f"@{name.lower()}" in lowered:
            ids.add(member_id)
    conn.execute(
        "DELETE FROM mentions WHERE source_type = ? AND source_id = ?",
        (source_type, _id(conn, "mentions", "source_id", source_id)),
    )
    kept = []
    for member_id in ids:
        if member_id == user["id"]:
            continue
        member = user_by_id(conn, member_id)
        if not member or member["account_id"] != card["account_id"]:
            continue
        insert(
            conn,
            "mentions",
            account_id=card["account_id"],
            mentionee_id=member_id,
            mentioner_id=user["id"],
            source_id=source_id,
            source_type=source_type,
        )
        _watch(conn, card["account_id"], card["id"], member_id, True)
        kept.append(member_id)
    return kept


def notifications_for(conn, user: dict, limit: int, offset: int):
    return q(
        conn,
        """
        SELECT * FROM notifications
        WHERE user_id = ?
        ORDER BY (read_at IS NULL) DESC, updated_at DESC
        LIMIT ? OFFSET ?
        """,
        (_id(conn, "notifications", "user_id", user["id"]), limit, offset),
    )


def notification_by_id(conn, notification_id: str):
    return q1(conn, "SELECT * FROM notifications WHERE id = ?", (_id(conn, "notifications", "id", notification_id),))


def unread_count(conn, user_id: str) -> int:
    row = q1(
        conn,
        "SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND read_at IS NULL",
        (_id(conn, "notifications", "user_id", user_id),),
    )
    return int(row["n"])


def mark_notification(conn, notification: dict, read: bool):
    if read:
        update(conn, "notifications", notification["id"], read_at=utcnow(), unread_count=0)
    else:
        update(conn, "notifications", notification["id"], read_at=None, unread_count=1)


def mark_all_read(conn, user_id: str):
    conn.execute(
        "UPDATE notifications SET read_at = ?, unread_count = 0, updated_at = ? WHERE user_id = ? AND read_at IS NULL",
        (dump_dt(utcnow()), dump_dt(utcnow()), _id(conn, "notifications", "user_id", user_id)),
    )


def events_for(conn, user: dict, board_ids: list[str] | None, creator_ids: list[str] | None, limit: int, offset: int):
    visible = boards_for(conn, user)
    allowed = {board["id"] for board in visible}
    if board_ids:
        allowed &= set(board_ids)
    if not allowed:
        return []
    marks = ",".join("?" * len(allowed))
    params = [_id(conn, "events", "account_id", user["account_id"]), *_ids(conn, "events", "board_id", list(allowed))]
    sql = f"""
        SELECT * FROM events
        WHERE account_id = ? AND board_id IN ({marks})
    """
    if creator_ids:
        creator_marks = ",".join("?" * len(creator_ids))
        sql += f" AND creator_id IN ({creator_marks})"
        params.extend(_ids(conn, "events", "creator_id", creator_ids))
    sql += " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return q(conn, sql, params)


def api_particulars(action: str, stored) -> dict:
    stored = stored or {}
    if isinstance(stored, str):
        try:
            stored = json.loads(stored)
        except json.JSONDecodeError:
            stored = {}
    nested = stored.get("particulars") if isinstance(stored, dict) else {}
    nested = nested or {}
    if action in {"card_assigned", "card_unassigned"}:
        return {"assignee_ids": list(stored.get("assignee_ids") or [])}
    if action == "card_board_changed":
        return {"old_board": str(nested.get("old_board") or ""), "new_board": str(nested.get("new_board") or "")}
    if action == "card_title_changed":
        return {"old_title": str(nested.get("old_title") or ""), "new_title": str(nested.get("new_title") or "")}
    if action == "card_triaged":
        return {"column": str(nested.get("column") or "")}
    return {}


def describe_event(conn, event: dict, card: dict | None) -> str:
    actor = user_by_id(conn, event["creator_id"])
    name = actor["name"] if actor else "Someone"
    title = (card or {}).get("title") or "a card"
    particulars = api_particulars(event["action"], event.get("particulars"))
    action = event["action"]
    if action == "card_published":
        return f"{name} published “{title}”"
    if action == "card_triaged":
        return f"{name} moved “{title}” to {particulars.get('column') or 'a column'}"
    if action == "card_sent_back_to_triage":
        return f"{name} sent “{title}” back to Maybe"
    if action == "card_closed":
        return f"{name} closed “{title}”"
    if action == "card_reopened":
        return f"{name} reopened “{title}”"
    if action == "card_postponed":
        return f"{name} moved “{title}” to Not now"
    if action == "card_auto_postponed":
        return f"“{title}” was postponed after sitting still"
    if action == "card_assigned":
        return f"{name} assigned “{title}”"
    if action == "card_unassigned":
        return f"{name} unassigned “{title}”"
    if action == "card_board_changed":
        return f"{name} moved “{title}” to {particulars.get('new_board') or 'another board'}"
    if action == "card_title_changed":
        return f"{name} renamed a card to “{particulars.get('new_title') or title}”"
    if action == "comment_created":
        return f"{name} commented on “{title}”"
    return f"{name} updated “{title}”"


# --- search and card queries -----------------------------------------------

def search_cards(conn, user: dict, terms: str, limit: int = 50):
    needles = [part for part in re.split(r"\s+", terms.strip()) if part]
    if not needles:
        return []
    visible = [board["id"] for board in boards_for(conn, user)]
    if not visible:
        return []
    marks = ",".join("?" * len(visible))
    clauses = []
    params = [_id(conn, "cards", "account_id", user["account_id"]), *_ids(conn, "cards", "board_id", visible)]
    for needle in needles:
        like = f"%{needle}%"
        clauses.append("(cards.title LIKE ? OR action_text_rich_texts.body LIKE ? OR CAST(cards.number AS TEXT) = ?)")
        params.extend([like, like, needle.lstrip("#")])
    sql = f"""
        SELECT cards.* FROM cards
        LEFT JOIN action_text_rich_texts
          ON action_text_rich_texts.record_type = 'Card'
         AND action_text_rich_texts.name = 'description'
         AND action_text_rich_texts.record_id = cards.id
        WHERE cards.account_id = ?
          AND cards.board_id IN ({marks})
          AND cards.status = 'published'
          AND {" AND ".join(clauses)}
        ORDER BY cards.last_active_at DESC
        LIMIT ?
    """
    params.append(limit)
    try:
        insert(
            conn,
            "search_queries",
            account_id=user["account_id"],
            terms=terms[:2000],
            user_id=user["id"],
        )
    except sqlite3.IntegrityError:
        pass
    return q(conn, sql, params)


def query_cards(conn, user: dict, params: dict, limit: int, offset: int):
    visible = {board["id"] for board in boards_for(conn, user)}
    board_ids = params.get("board_ids") or []
    if board_ids:
        visible &= set(board_ids)
    if not visible:
        return []
    indexed = params.get("indexed_by") or "all"
    where = ["cards.account_id = ?", f"cards.board_id IN ({','.join('?' * len(visible))})"]
    sql_params = [_id(conn, "cards", "account_id", user["account_id"]), *_ids(conn, "cards", "board_id", list(visible))]
    joins = []
    if indexed == "draft":
        where.append("cards.status = 'drafted'")
        where.append("cards.creator_id = ?")
        sql_params.append(_id(conn, "cards", "creator_id", user["id"]))
    else:
        where.append("cards.status = 'published'")
    include_closed = indexed == "closed" or bool(params.get("closure")) or bool(params.get("closer_ids")) or bool(params.get("card_ids"))
    include_not_now = indexed == "not_now" or bool(params.get("card_ids"))
    if not include_closed:
        joins.append("LEFT JOIN closures ON closures.card_id = cards.id")
        where.append("closures.id IS NULL")
    if not include_not_now:
        joins.append("LEFT JOIN card_not_nows ON card_not_nows.card_id = cards.id")
        where.append("card_not_nows.id IS NULL")
    if indexed == "closed":
        if "LEFT JOIN closures" not in " ".join(joins):
            joins.append("JOIN closures ON closures.card_id = cards.id")
        else:
            where = [item for item in where if item != "closures.id IS NULL"]
            joins = [item.replace("LEFT JOIN closures", "JOIN closures") for item in joins]
    if indexed == "not_now":
        joins.append("JOIN card_not_nows AS postponed ON postponed.card_id = cards.id")
    if indexed == "maybe":
        where.append("cards.column_id IS NULL")
    if indexed == "golden":
        joins.append("JOIN card_goldnesses ON card_goldnesses.card_id = cards.id")
    if indexed == "stalled":
        cutoff = dump_dt(utcnow() - timedelta(days=STALLED_DAYS))
        joins.append("JOIN card_activity_spikes ON card_activity_spikes.card_id = cards.id")
        where.append("card_activity_spikes.updated_at <= ?")
        where.append("cards.updated_at <= ?")
        sql_params.extend([cutoff, cutoff])
    if indexed == "postponing_soon":
        where.append("cards.last_active_at <= ?")
        sql_params.append(dump_dt(utcnow() - timedelta(days=DEFAULT_POSTPONE_DAYS * 3 // 4)))
    if params.get("column_ids"):
        where.append(f"cards.column_id IN ({','.join('?' * len(params['column_ids']))})")
        sql_params.extend(_ids(conn, "cards", "column_id", params["column_ids"]))
    if params.get("card_ids"):
        where.append(f"cards.id IN ({','.join('?' * len(params['card_ids']))})")
        sql_params.extend(_ids(conn, "cards", "id", params["card_ids"]))
    if params.get("creator_ids"):
        where.append(f"cards.creator_id IN ({','.join('?' * len(params['creator_ids']))})")
        sql_params.extend(_ids(conn, "cards", "creator_id", params["creator_ids"]))
    if params.get("assignee_ids"):
        joins.append("JOIN assignments ON assignments.card_id = cards.id")
        where.append(f"assignments.assignee_id IN ({','.join('?' * len(params['assignee_ids']))})")
        sql_params.extend(_ids(conn, "assignments", "assignee_id", params["assignee_ids"]))
    if params.get("assignment_status") == "unassigned":
        joins.append("LEFT JOIN assignments AS any_assignment ON any_assignment.card_id = cards.id")
        where.append("any_assignment.id IS NULL")
    if params.get("tag_ids"):
        joins.append("JOIN taggings ON taggings.card_id = cards.id")
        where.append(f"taggings.tag_id IN ({','.join('?' * len(params['tag_ids']))})")
        sql_params.extend(_ids(conn, "taggings", "tag_id", params["tag_ids"]))
    if params.get("closer_ids"):
        if not any("closures" in item for item in joins):
            joins.append("JOIN closures ON closures.card_id = cards.id")
        where.append(f"closures.user_id IN ({','.join('?' * len(params['closer_ids']))})")
        sql_params.extend(_ids(conn, "closures", "user_id", params["closer_ids"]))
    window = _time_window(params.get("creation"))
    if window:
        where.append("cards.created_at >= ? AND cards.created_at < ?")
        sql_params.extend(window)
    closed_window = _time_window(params.get("closure"))
    if closed_window:
        if not any("closures" in item for item in joins):
            joins.append("JOIN closures ON closures.card_id = cards.id")
        where.append("closures.created_at >= ? AND closures.created_at < ?")
        sql_params.extend(closed_window)
    for term in params.get("terms") or []:
        if not term:
            continue
        joins.append(
            "LEFT JOIN action_text_rich_texts AS search_body ON search_body.record_type = 'Card' "
            "AND search_body.name = 'description' AND search_body.record_id = cards.id"
        )
        where.append("(cards.title LIKE ? OR search_body.body LIKE ?)")
        like = f"%{term}%"
        sql_params.extend([like, like])
    sort = params.get("sorted_by") or "latest"
    if sort == "newest":
        order = "cards.created_at DESC, cards.id DESC"
    elif sort == "oldest":
        order = "cards.created_at ASC, cards.id ASC"
    else:
        order = "cards.last_active_at DESC, cards.id DESC"
    sql = f"""
        SELECT DISTINCT cards.* FROM cards
        {' '.join(joins)}
        WHERE {' AND '.join(where)}
        ORDER BY {order}
        LIMIT ? OFFSET ?
    """
    sql_params.extend([limit, offset])
    return q(conn, sql, sql_params)


def _time_window(name: str | None):
    if not name:
        return None
    now = utcnow()
    start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if name == "today":
        start, end = start_today, start_today + timedelta(days=1)
    elif name == "yesterday":
        start, end = start_today - timedelta(days=1), start_today
    elif name == "thisweek":
        start, end = start_today - timedelta(days=start_today.weekday()), start_today + timedelta(days=1)
    elif name == "lastweek":
        this = start_today - timedelta(days=start_today.weekday())
        start, end = this - timedelta(days=7), this
    elif name == "thismonth":
        start, end = start_today.replace(day=1), start_today + timedelta(days=1)
    elif name == "lastmonth":
        first = start_today.replace(day=1)
        previous = (first - timedelta(days=1)).replace(day=1)
        start, end = previous, first
    elif name == "thisyear":
        start, end = start_today.replace(month=1, day=1), start_today + timedelta(days=1)
    elif name == "lastyear":
        this = start_today.replace(month=1, day=1)
        start, end = this.replace(year=this.year - 1), this
    else:
        return None
    return dump_dt(start), dump_dt(end)


def auto_postpone_board(conn, board: dict):
    days = postpone_days(conn, board["account_id"], board["id"])
    cutoff = dump_dt(utcnow() - timedelta(days=days))
    system = system_user(conn, board["account_id"])
    if not system:
        return 0
    rows = q(
        conn,
        """
        SELECT cards.* FROM cards
        LEFT JOIN closures ON closures.card_id = cards.id
        LEFT JOIN card_not_nows ON card_not_nows.card_id = cards.id
        WHERE cards.board_id = ?
          AND cards.status = 'published'
          AND closures.id IS NULL
          AND card_not_nows.id IS NULL
          AND cards.last_active_at <= ?
        """,
        (_id(conn, "cards", "board_id", board["id"]), cutoff),
    )
    for card in rows:
        postpone_card(conn, system, card, "card_auto_postponed")
    return len(rows)


def column_cards(conn, column_id: str):
    return q(
        conn,
        """
        SELECT cards.* FROM cards
        LEFT JOIN closures ON closures.card_id = cards.id
        LEFT JOIN card_not_nows ON card_not_nows.card_id = cards.id
        LEFT JOIN card_goldnesses ON card_goldnesses.card_id = cards.id
        WHERE cards.column_id = ?
          AND cards.status = 'published'
          AND closures.id IS NULL
          AND card_not_nows.id IS NULL
        ORDER BY (card_goldnesses.id IS NULL), cards.last_active_at DESC
        """,
        (_id(conn, "cards", "column_id", column_id),),
    )


def lane_cards(conn, board_id: str, lane: str):
    board_param = _id(conn, "cards", "board_id", board_id)
    if lane == "maybe":
        return q(
            conn,
            """
            SELECT cards.* FROM cards
            LEFT JOIN closures ON closures.card_id = cards.id
            LEFT JOIN card_not_nows ON card_not_nows.card_id = cards.id
            LEFT JOIN card_goldnesses ON card_goldnesses.card_id = cards.id
            WHERE cards.board_id = ? AND cards.status = 'published'
              AND cards.column_id IS NULL AND closures.id IS NULL AND card_not_nows.id IS NULL
            ORDER BY (card_goldnesses.id IS NULL), cards.last_active_at DESC
            """,
            (board_param,),
        )
    if lane == "not_now":
        return q(
            conn,
            """
            SELECT cards.* FROM cards
            JOIN card_not_nows ON card_not_nows.card_id = cards.id
            LEFT JOIN closures ON closures.card_id = cards.id
            WHERE cards.board_id = ? AND cards.status = 'published' AND closures.id IS NULL
            ORDER BY card_not_nows.created_at DESC
            """,
            (board_param,),
        )
    if lane == "closed":
        return q(
            conn,
            """
            SELECT cards.* FROM cards
            JOIN closures ON closures.card_id = cards.id
            WHERE cards.board_id = ?
            ORDER BY closures.created_at DESC
            """,
            (board_param,),
        )
    return []


# --- files -----------------------------------------------------------------

def save_blob(conn, storage: Path, account_id: str, record_type: str, record_id: str, name: str, filename: str, content_type: str, data: bytes):
    if len(data) > 10 * 1024 * 1024:
        raise invalid({name: ["must be smaller than 10MB"]})
    if content_type not in {"image/jpeg", "image/png", "image/gif", "image/webp"}:
        raise invalid({name: ["must be a JPEG, PNG, GIF, or WebP image"]})
    _purge_attachments(conn, record_type, record_id, name=name, storage=storage)
    key = token(28)
    digest = hashlib.md5(data).digest()
    import base64
    checksum = base64.b64encode(digest).decode()
    blob_id = insert(
        conn,
        "active_storage_blobs",
        account_id=account_id,
        byte_size=len(data),
        checksum=checksum,
        content_type=content_type,
        filename=filename[:255] or "upload",
        key=key,
        metadata="{}",
        service_name="local",
    )
    insert(
        conn,
        "active_storage_attachments",
        account_id=account_id,
        blob_id=blob_id,
        name=name,
        record_id=record_id,
        record_type=record_type,
    )
    folder = storage / key[:2] / key[2:4]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / key).write_bytes(data)
    return blob_id


def attachment_blob(conn, record_type: str, record_id: str, name: str):
    return q1(
        conn,
        """
        SELECT active_storage_blobs.* FROM active_storage_attachments
        JOIN active_storage_blobs ON active_storage_blobs.id = active_storage_attachments.blob_id
        WHERE record_type = ? AND record_id = ? AND name = ?
        """,
        (record_type, _id(conn, "active_storage_attachments", "record_id", record_id), name),
    )


def blob_path(storage: Path, key: str) -> Path | None:
    nested = storage / key[:2] / key[2:4] / key
    flat = storage / key
    if nested.is_file():
        return nested
    if flat.is_file():
        return flat
    return None


def _purge_attachments(conn, record_type: str, record_id: str, name: str | None = None, storage: Path | None = None):
    sql = "SELECT * FROM active_storage_attachments WHERE record_type = ? AND record_id = ?"
    params = [record_type, _id(conn, "active_storage_attachments", "record_id", record_id)]
    if name:
        sql += " AND name = ?"
        params.append(name)
    rows = q(conn, sql, params)
    for row in rows:
        delete_where(conn, "active_storage_attachments", id=row["id"])
        still = q1(
            conn,
            "SELECT id FROM active_storage_attachments WHERE blob_id = ?",
            (_id(conn, "active_storage_attachments", "blob_id", row["blob_id"]),),
        )
        if still:
            continue
        blob = q1(conn, "SELECT * FROM active_storage_blobs WHERE id = ?", (_id(conn, "active_storage_blobs", "id", row["blob_id"]),))
        delete_where(conn, "active_storage_blobs", id=row["blob_id"])
        if blob and storage:
            path = blob_path(storage, blob["key"])
            if path and path.is_file():
                path.unlink()


def has_extra_attachments(conn, card_id: str) -> bool:
    row = q1(
        conn,
        """
        SELECT id FROM active_storage_attachments
        WHERE record_type = 'Card' AND record_id = ? AND name != 'image'
        LIMIT 1
        """,
        (_id(conn, "active_storage_attachments", "record_id", card_id),),
    )
    if row:
        return True
    rich = rich_text(conn, "Card", card_id, "description")
    if not rich:
        return False
    embed = q1(
        conn,
        "SELECT id FROM active_storage_attachments WHERE record_type = 'ActionText::RichText' AND record_id = ? LIMIT 1",
        (_id(conn, "active_storage_attachments", "record_id", rich["id"]),),
    )
    return embed is not None


# --- webhooks --------------------------------------------------------------

def webhooks_for(conn, board_id: str):
    return q(
        conn,
        "SELECT * FROM webhooks WHERE board_id = ? ORDER BY lower(name), created_at DESC",
        (_id(conn, "webhooks", "board_id", board_id),),
    )


def webhook_by_id(conn, webhook_id: str):
    return q1(conn, "SELECT * FROM webhooks WHERE id = ?", (_id(conn, "webhooks", "id", webhook_id),))


def _normalize_actions(actions) -> list[str]:
    if actions is None:
        return list(WEBHOOK_ACTIONS)
    if isinstance(actions, str):
        actions = [part.strip() for part in actions.split(",") if part.strip()]
    chosen = []
    for action in actions:
        if action in WEBHOOK_ACTIONS and action not in chosen:
            chosen.append(action)
    if not chosen:
        raise invalid({"subscribed_actions": ["choose at least one event"]})
    return chosen


def create_webhook(conn, user: dict, board: dict, name: str, url: str, actions):
    if not can_admin_board(user, board):
        raise forbidden()
    if not name.strip():
        raise invalid({"name": ["can't be blank"]})
    if not url.startswith(("http://", "https://")):
        raise invalid({"url": ["must be an http or https URL"]})
    webhook_id = insert(
        conn,
        "webhooks",
        account_id=board["account_id"],
        active=True,
        board_id=board["id"],
        name=name.strip()[:255],
        signing_secret=token(24),
        subscribed_actions=_normalize_actions(actions),
        url=url.strip(),
    )
    insert(
        conn,
        "webhook_delinquency_trackers",
        account_id=board["account_id"],
        consecutive_failures_count=0,
        webhook_id=webhook_id,
    )
    return webhook_by_id(conn, webhook_id)


def update_webhook(conn, user: dict, webhook: dict, *, name=None, actions=None, active=None):
    board = require(board_by_id(conn, webhook["board_id"]))
    if not can_admin_board(user, board):
        raise forbidden()
    cols = {}
    if name is not None:
        if not str(name).strip():
            raise invalid({"name": ["can't be blank"]})
        cols["name"] = str(name).strip()[:255]
    if actions is not None:
        cols["subscribed_actions"] = _normalize_actions(actions)
    if active is not None:
        cols["active"] = bool(active)
    if cols:
        update(conn, "webhooks", webhook["id"], **cols)
    return webhook_by_id(conn, webhook["id"])


def delete_webhook(conn, user: dict, webhook: dict):
    board = require(board_by_id(conn, webhook["board_id"]))
    if not can_admin_board(user, board):
        raise forbidden()
    delete_where(conn, "webhook_deliveries", webhook_id=webhook["id"])
    delete_where(conn, "webhook_delinquency_trackers", webhook_id=webhook["id"])
    delete_where(conn, "webhooks", id=webhook["id"])


def deliveries_for(conn, webhook_id: str, limit: int, offset: int):
    return q(
        conn,
        "SELECT * FROM webhook_deliveries WHERE webhook_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (_id(conn, "webhook_deliveries", "webhook_id", webhook_id), limit, offset),
    )


def _dispatch_webhooks(conn, board: dict, event_id: str, action: str):
    hooks = webhooks_for(conn, board["id"])
    for hook in hooks:
        if not hook["active"]:
            continue
        actions = hook["subscribed_actions"] or []
        if isinstance(actions, str):
            try:
                actions = json.loads(actions)
            except json.JSONDecodeError:
                actions = []
        if action not in actions:
            continue
        insert(
            conn,
            "webhook_deliveries",
            account_id=board["account_id"],
            event_id=event_id,
            request=None,
            response=None,
            state="pending",
            webhook_id=hook["id"],
        )


def deliver_pending(conn, build_payload):
    """Best-effort delivery. build_payload(event) -> (body, content_type)."""
    pending = q(conn, "SELECT * FROM webhook_deliveries WHERE state = 'pending' ORDER BY created_at LIMIT 20")
    for delivery in pending:
        hook = webhook_by_id(conn, delivery["webhook_id"])
        event = q1(conn, "SELECT * FROM events WHERE id = ?", (_id(conn, "events", "id", delivery["event_id"]),))
        if not hook or not event:
            update(conn, "webhook_deliveries", delivery["id"], state="errored", response={"error": "missing"})
            continue
        try:
            body, content_type = build_payload(event, hook)
            result = _post_webhook(hook["url"], hook["signing_secret"], body, content_type, event)
        except Exception as exc:  # noqa: BLE001 - record and continue
            result = {"error": exc.__class__.__name__}
        state = "errored" if result.get("error") else "completed"
        update(
            conn,
            "webhook_deliveries",
            delivery["id"],
            state=state,
            request={"headers": result.pop("headers", {})},
            response=result,
        )


def _post_webhook(url: str, secret: str, body: str, content_type: str, event: dict) -> dict:
    import hmac
    import ipaddress
    import socket
    import urllib.error
    import urllib.request
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return {"error": "private_uri", "headers": {}}
    host = parsed.hostname
    blocked = {"169.254.169.254", "metadata.google.internal"}
    if host in blocked:
        return {"error": "private_uri", "headers": {}}
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror:
        return {"error": "dns_lookup_failed", "headers": {}}
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_link_local or ip.is_multicast or ip.is_reserved or str(ip) == "169.254.169.254":
            return {"error": "private_uri", "headers": {}}
    signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    created = iso(event["created_at"]) or ""
    headers = {
        "User-Agent": "fizzy/1.0.0 Webhook",
        "Content-Type": content_type,
        "X-Webhook-Signature": signature,
        "X-Webhook-Timestamp": created,
    }
    request = urllib.request.Request(url, data=body.encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            response.read(1024)
            return {"code": response.status, "headers": {key: value for key, value in headers.items() if key != "X-Webhook-Signature"}}
    except urllib.error.HTTPError as exc:
        return {"code": exc.code, "headers": headers}
    except Exception as exc:  # noqa: BLE001
        error = "connection_timeout" if "timed out" in str(exc).lower() else "destination_unreachable"
        return {"error": error, "headers": {key: value for key, value in headers.items() if key != "X-Webhook-Signature"}}


# --- exports ---------------------------------------------------------------

def create_export(conn, storage: Path, user: dict, kind: str):
    if kind == "Account::Export" and user["role"] not in {"owner", "admin"}:
        raise forbidden()
    export_id = insert(
        conn,
        "exports",
        account_id=user["account_id"],
        status="processing",
        type=kind,
        user_id=user["id"],
    )
    archive = _build_export_zip(conn, user, kind, export_id)
    filename = f"fizzy-{'account' if 'Account' in kind else 'user'}-export.zip"
    save_blob(conn, storage, user["account_id"], kind, export_id, "file", filename, "application/zip", archive)
    # save_blob rejects non-images. Write the zip without that check.
    return export_id


def _store_zip(conn, storage: Path, account_id: str, record_type: str, record_id: str, filename: str, data: bytes):
    import base64

    key = token(28)
    blob_id = insert(
        conn,
        "active_storage_blobs",
        account_id=account_id,
        byte_size=len(data),
        checksum=base64.b64encode(hashlib.md5(data).digest()).decode(),
        content_type="application/zip",
        filename=filename,
        key=key,
        metadata="{}",
        service_name="local",
    )
    insert(
        conn,
        "active_storage_attachments",
        account_id=account_id,
        blob_id=blob_id,
        name="file",
        record_id=record_id,
        record_type=record_type,
    )
    folder = storage / key[:2] / key[2:4]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / key).write_bytes(data)
    return blob_id


def _build_export_zip(conn, user: dict, kind: str, export_id: str) -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    cards = q(
        conn,
        "SELECT * FROM cards WHERE account_id = ? ORDER BY number",
        (_id(conn, "cards", "account_id", user["account_id"]),),
    )
    if kind == "User::DataExport":
        visible = {board["id"] for board in boards_for(conn, user)}
        mine = set()
        for card in cards:
            if card["board_id"] not in visible:
                continue
            if card["creator_id"] == user["id"]:
                mine.add(card["id"])
                continue
            assigned = q1(
                conn,
                "SELECT id FROM assignments WHERE card_id = ? AND assignee_id = ?",
                (_id(conn, "assignments", "card_id", card["id"]), _id(conn, "assignments", "assignee_id", user["id"])),
            )
            if assigned:
                mine.add(card["id"])
        cards = [card for card in cards if card["id"] in mine]
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        summary = []
        for card in cards:
            body = rich_text(conn, "Card", card["id"], "description")
            comments = []
            for comment in comments_of(conn, card["id"]):
                comment_body = rich_text(conn, "Comment", comment["id"], "body")
                author = user_by_id(conn, comment["creator_id"])
                comments.append({
                    "id": comment["id"],
                    "author": author["name"] if author else None,
                    "created_at": iso(comment["created_at"]),
                    "body": plain_text(comment_body["body"] if comment_body else ""),
                })
            payload = {
                "number": card["number"],
                "title": card["title"],
                "status": card["status"],
                "created_at": iso(card["created_at"]),
                "description": plain_text(body["body"] if body else ""),
                "tags": [tag["title"] for tag in tags_for_card(conn, card["id"])],
                "steps": [{"content": step["content"], "completed": step["completed"]} for step in steps_of(conn, card["id"])],
                "comments": comments,
            }
            archive.writestr(f"cards/{card['number']}.json", json.dumps(payload, indent=2))
            summary.append({"number": card["number"], "title": card["title"]})
        archive.writestr("manifest.json", json.dumps({"cards": summary, "exported_at": iso(utcnow())}, indent=2))
    return buffer.getvalue()


def finish_export(conn, storage: Path, user: dict, kind: str):
    export_id = insert(
        conn,
        "exports",
        account_id=user["account_id"],
        completed_at=None,
        status="processing",
        type=kind,
        user_id=user["id"],
    )
    data = _build_export_zip(conn, user, kind, export_id)
    filename = "fizzy-account-export.zip" if kind == "Account::Export" else "fizzy-user-data-export.zip"
    _store_zip(conn, storage, user["account_id"], kind, export_id, filename, data)
    update(conn, "exports", export_id, status="completed", completed_at=utcnow())
    return q1(conn, "SELECT * FROM exports WHERE id = ?", (_id(conn, "exports", "id", export_id),))


def export_by_id(conn, export_id: str):
    return q1(conn, "SELECT * FROM exports WHERE id = ?", (_id(conn, "exports", "id", export_id),))


