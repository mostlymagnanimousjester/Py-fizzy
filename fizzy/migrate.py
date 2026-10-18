"""Bring a Fizzy SQLite file up to the current app schema.

Rails records one row in ``schema_migrations`` per file under ``db/migrate``.
A database this app created from scratch only had the latest version stamped,
and a file written by an older Ruby release is missing later columns. Opening
either file runs this module.

The steps are idempotent. They follow the column and index list in
``schema.py`` (the SQLite schema at ``20260828120000``) and the data moves in
the Ruby migrations: memberships folded into users, polymorphic reactions,
notification card ids, card numbers, and the dropped tables. MySQL search
shards and the SaaS migrations are not part of this schema.

SQLite will not ``ADD COLUMN`` a bare ``NOT NULL`` without a default, and it
will not change a declared type in place. Those Rails steps are applied as far
as SQLite allows (nullable add, then a backfill). Declared-type widenings and
foreign-key removal are recorded without a table rebuild; this process opens
every file with ``foreign_keys=OFF``.
"""

from __future__ import annotations

import re
import sqlite3

from .codec import dump_dt, utcnow, uuid7_bytes, uuid_bytes
from .schema import (
    SCHEMA_VERSION,
    _column_names,
    _migrate_reactions,
    _tables,
    index_specs,
    table_statements,
)

# App migrations only. saas/db/migrate is a different product schema.
MIGRATION_VERSIONS = (
    "20251111122540",
    "20251111153019",
    "20251112093037",
    "20251112184932",
    "20251113111501",
    "20251113160907",
    "20251113163145",
    "20251113190256",
    "20251114084325",
    "20251114183203",
    "20251117190817",
    "20251117192434",
    "20251117202517",
    "20251120110206",
    "20251120194700",
    "20251120203100",
    "20251121092508",
    "20251121112416",
    "20251125110629",
    "20251125130010",
    "20251127000001",
    "20251129110120",
    "20251129175717",
    "20251201100607",
    "20251201132341",
    "20251205010536",
    "20251205205826",
    "20251210054934",
    "20251219120755",
    "20251223000001",
    "20251223000002",
    "20251224092315",
    "20260121155752",
    "20260206104338",
    "20260209165805",
    "20260211122517",
    "20260212102026",
    "20260213154740",
    "20260213170100",
    "20260218120000",
    "20260709120000",
    "20260825120000",
    "20260828120000",
)

# Indexes the later migrations replace. Leaving the old unique indexes in
# place would reject rows the current schema allows (a tag title reused in
# another account, a join code reused in another account).
OBSOLETE_INDEXES = (
    "index_accesses_on_accessed_at",
    "index_account_join_codes_on_code",
    "index_board_publications_on_account_id_and_key",
    "index_cards_on_last_active_at_and_status",
    "index_events_on_action",
    "index_events_on_summary_id_and_action",
    "index_notifications_on_user_id_and_read_at_and_created_at",
    "index_push_subscriptions_on_endpoint",
    "index_push_subscriptions_on_user_agent",
    "index_push_subscriptions_on_user_id",
    "index_reactions_on_comment_id",
    "index_tags_on_title",
    "index_users_on_membership_id",
    "index_users_on_role",
    "idx_on_endpoint_p256dh_key_auth_key_7553014576",
)

# (table, foreign key, parent table that already has account_id)
_ACCOUNT_FROM_PARENT = (
    ("boards", "creator_id", "users"),
    ("cards", "board_id", "boards"),
    ("columns", "board_id", "boards"),
    ("comments", "card_id", "cards"),
    ("events", "board_id", "boards"),
    ("webhooks", "board_id", "boards"),
    ("accesses", "board_id", "boards"),
    ("assignments", "card_id", "cards"),
    ("board_publications", "board_id", "boards"),
    ("card_activity_spikes", "card_id", "cards"),
    ("card_goldnesses", "card_id", "cards"),
    ("card_not_nows", "card_id", "cards"),
    ("closures", "card_id", "cards"),
    ("pins", "card_id", "cards"),
    ("steps", "card_id", "cards"),
    ("taggings", "card_id", "cards"),
    ("watches", "card_id", "cards"),
    ("filters", "creator_id", "users"),
    ("notification_bundles", "user_id", "users"),
    ("notifications", "user_id", "users"),
    ("push_subscriptions", "user_id", "users"),
    ("search_queries", "user_id", "users"),
    ("user_settings", "user_id", "users"),
    ("webhook_delinquency_trackers", "webhook_id", "webhooks"),
    ("webhook_deliveries", "webhook_id", "webhooks"),
)


def upgrade(conn: sqlite3.Connection) -> None:
    """Apply every app migration that this file is still missing."""
    _rename_account_exports(conn)
    _normalize_stored_ids(conn)
    _fold_memberships(conn)
    for statement in table_statements():
        conn.execute(statement)
    _copy_search_shards(conn)
    _drop_obsolete_tables(conn)
    _add_missing_columns(conn)
    _backfill(conn)
    _migrate_reactions(conn)
    _backfill_notifications(conn)
    _dedupe_card_activity_spikes(conn)
    _promote_first_admin(conn)
    _drop_obsolete_indexes(conn)
    _ensure_indexes(conn)
    _stamp(conn)
    _ensure_environment(conn)
    conn.commit()


def _has_table(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _rename_account_exports(conn) -> None:
    if not _has_table(conn, "account_exports"):
        return
    if not _has_table(conn, "exports"):
        conn.execute("ALTER TABLE account_exports RENAME TO exports")
        return
    shared = [
        column
        for column in (
            "id",
            "account_id",
            "completed_at",
            "created_at",
            "status",
            "updated_at",
            "user_id",
        )
        if column in _column_names(conn, "exports") and column in _column_names(conn, "account_exports")
    ]
    if shared and "id" in shared:
        quoted = ", ".join(f'"{column}"' for column in shared)
        conn.execute(
            f"INSERT OR IGNORE INTO exports ({quoted}) SELECT {quoted} FROM account_exports"
        )
    conn.execute("DROP TABLE account_exports")


def _fold_memberships(conn) -> None:
    """Port of drop_memberships: users.identity_id replaces membership_id.

    Ruby's migration adds ``identity_id`` and then drops ``memberships`` without
    copying the foreign key. This step copies it first. The copy used to require
    the two id columns to be the same SQLite value, so a blob membership and a
    hex membership id matched nothing and the link was deleted. Login then found
    the email and landed on an empty account list.
    """
    if not _has_table(conn, "users"):
        return
    if "identity_id" not in _column_names(conn, "users"):
        conn.execute('ALTER TABLE users ADD COLUMN "identity_id" blob')
    _link_users_by_email(conn)
    if _has_table(conn, "memberships"):
        _copy_membership_identities(conn)
    # A membership row that still has not been copied is the only record of who
    # owns the account. Keep it until a human user actually received an identity.
    if _has_table(conn, "memberships") and _membership_rows(conn) and _humans_missing_identity(conn):
        return
    if "membership_id" in _column_names(conn, "users"):
        _drop_indexes_using(conn, "users", "membership_id")
        try:
            conn.execute('ALTER TABLE users DROP COLUMN "membership_id"')
        except sqlite3.OperationalError:
            # A view or an index SQLite will not drop must not block the rest of
            # the migration. The extra column is nullable and unread by this app.
            pass
    if _has_table(conn, "memberships"):
        conn.execute("DROP TABLE memberships")
    _link_lone_identity(conn)


def _normalize_stored_ids(conn) -> None:
    """Rewrite hex, dashed, and base36 ids to 16-byte blobs.

    Session lookup joins ``identities.id = sessions.identity_id``. A new
    session stored as a blob cannot see an identity still stored as text, so
    the next request would not find that session.
    """
    tables = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    for table in tables:
        name = table["name"]
        sql = table["sql"] or ""
        if "fts" in name or "VIRTUAL" in sql.upper():
            continue
        try:
            info = conn.execute(f'PRAGMA table_info("{name}")').fetchall()
        except sqlite3.OperationalError:
            continue
        for column in info:
            col_name = column["name"]
            if col_name != "id" and not col_name.endswith("_id"):
                continue
            declared = (column["type"] or "").lower()
            if "int" in declared:
                continue
            if not (
                "blob" in declared
                or "binary" in declared
                or "uuid" in declared
                or "char" in declared
                or declared in {"", "text", "string"}
            ):
                continue
            try:
                rows = conn.execute(
                    f'SELECT rowid AS rid, "{col_name}" AS stored FROM "{name}"'
                ).fetchall()
            except sqlite3.OperationalError:
                break
            for row in rows:
                converted = uuid_bytes(row["stored"])
                if converted is None or _same_id(row["stored"], converted):
                    continue
                try:
                    conn.execute("SAVEPOINT fizzy_id_norm")
                    conn.execute(
                        f'UPDATE "{name}" SET "{col_name}" = ? WHERE rowid = ?',
                        (converted, row["rid"]),
                    )
                    conn.execute("RELEASE fizzy_id_norm")
                except sqlite3.IntegrityError:
                    conn.execute("ROLLBACK TO fizzy_id_norm")
                    conn.execute("RELEASE fizzy_id_norm")


def _same_id(raw, converted: bytes) -> bool:
    if isinstance(raw, memoryview):
        raw = raw.tobytes()
    return raw == converted


def _human_sql(columns: set[str]) -> str:
    if "role" not in columns:
        return ""
    return "AND (role IS NULL OR lower(CAST(role AS TEXT)) != 'system')"


def _humans_missing_identity(conn) -> int:
    columns = _column_names(conn, "users")
    if "identity_id" not in columns:
        return 0
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS n FROM users
        WHERE identity_id IS NULL
        {_human_sql(columns)}
        """
    ).fetchone()
    return int(row["n"] or 0)


def _membership_rows(conn) -> int:
    if not _has_table(conn, "memberships"):
        return 0
    row = conn.execute("SELECT COUNT(*) AS n FROM memberships").fetchone()
    return int(row["n"] or 0)


def _copy_membership_identities(conn) -> None:
    user_columns = _column_names(conn, "users")
    member_columns = _column_names(conn, "memberships")
    if "identity_id" not in user_columns or "identity_id" not in member_columns:
        return
    if "membership_id" in user_columns:
        conn.execute(
            """
            UPDATE users SET identity_id = (
                SELECT identity_id FROM memberships WHERE memberships.id = users.membership_id
            )
            WHERE identity_id IS NULL AND membership_id IS NOT NULL
              AND EXISTS (
                SELECT 1 FROM memberships
                WHERE memberships.id = users.membership_id AND memberships.identity_id IS NOT NULL
              )
            """
        )
    if "user_id" in member_columns:
        conn.execute(
            """
            UPDATE users SET identity_id = (
                SELECT identity_id FROM memberships WHERE memberships.user_id = users.id
            )
            WHERE identity_id IS NULL
              AND EXISTS (
                SELECT 1 FROM memberships
                WHERE memberships.user_id = users.id AND memberships.identity_id IS NOT NULL
              )
            """
        )
    if "email_address" in member_columns and "email_address" in user_columns:
        conn.execute(
            """
            UPDATE users SET identity_id = (
                SELECT identity_id FROM memberships
                WHERE lower(trim(memberships.email_address)) = lower(trim(users.email_address))
                  AND memberships.identity_id IS NOT NULL
                LIMIT 1
            )
            WHERE identity_id IS NULL
              AND email_address IS NOT NULL
              AND trim(email_address) != ''
            """
        )
    if "membership_id" not in user_columns:
        return
    members = {}
    for row in conn.execute("SELECT id AS stored, identity_id AS identity FROM memberships"):
        key = uuid_bytes(row["stored"])
        identity = uuid_bytes(row["identity"])
        if key is not None and identity is not None:
            members[key] = identity
    pending = conn.execute(
        """
        SELECT rowid AS rid, membership_id AS stored FROM users
        WHERE identity_id IS NULL AND membership_id IS NOT NULL
        """
    ).fetchall()
    for user in pending:
        identity = members.get(uuid_bytes(user["stored"]))
        if identity is not None:
            conn.execute(
                "UPDATE users SET identity_id = ? WHERE rowid = ?",
                (identity, user["rid"]),
            )


def _link_users_by_email(conn) -> None:
    """Older files kept the address on users and the identity on a separate row."""
    if not _has_table(conn, "users") or not _has_table(conn, "identities"):
        return
    columns = _column_names(conn, "users")
    if "email_address" not in columns or "identity_id" not in columns:
        return
    rows = conn.execute(
        f"""
        SELECT rowid AS rid, email_address AS email
        FROM users
        WHERE identity_id IS NULL
          AND email_address IS NOT NULL
          AND trim(email_address) != ''
          {_human_sql(columns)}
        """
    ).fetchall()
    identity_columns = _column_names(conn, "identities")
    now = dump_dt(utcnow())
    for row in rows:
        email = str(row["email"]).strip().lower()
        if "@" not in email:
            continue
        identity = _identity_bytes_for_email(conn, email, identity_columns, now)
        if identity is None:
            continue
        conn.execute("UPDATE users SET identity_id = ? WHERE rowid = ?", (identity, row["rid"]))


def _identity_bytes_for_email(conn, email: str, columns: set[str], now: str):
    found = conn.execute(
        "SELECT id AS stored FROM identities WHERE lower(trim(email_address)) = ?",
        (email,),
    ).fetchone()
    if found:
        return uuid_bytes(found["stored"]) or found["stored"]
    identity = uuid7_bytes()
    fields = ["id", "email_address", "created_at", "updated_at"]
    values: list = [identity, email, now, now]
    if "staff" in columns:
        fields.append("staff")
        values.append(0)
    quoted = ", ".join(f'"{field}"' for field in fields)
    placeholders = ", ".join("?" for _ in fields)
    try:
        conn.execute("SAVEPOINT fizzy_identity")
        conn.execute(
            f"INSERT INTO identities ({quoted}) VALUES ({placeholders})",
            values,
        )
        conn.execute("RELEASE fizzy_identity")
    except sqlite3.IntegrityError:
        conn.execute("ROLLBACK TO fizzy_identity")
        conn.execute("RELEASE fizzy_identity")
        found = conn.execute(
            "SELECT id AS stored FROM identities WHERE lower(trim(email_address)) = ?",
            (email,),
        ).fetchone()
        if not found:
            return None
        return uuid_bytes(found["stored"]) or found["stored"]
    return identity


def _link_lone_identity(conn) -> None:
    """Repair one account whose membership row is already gone.

    Linking is only safe when that account is the only one with a single
    unlinked person and the file has a single unused identity. Several
    accounts with several identities are left alone.
    """
    if not _has_table(conn, "users") or not _has_table(conn, "identities"):
        return
    if _has_table(conn, "memberships") or "membership_id" in _column_names(conn, "users"):
        return
    columns = _column_names(conn, "users")
    if "identity_id" not in columns or "account_id" not in columns:
        return
    people = conn.execute(
        f"""
        SELECT rowid AS rid, account_id AS account
        FROM users
        WHERE identity_id IS NULL
        {_human_sql(columns)}
        """
    ).fetchall()
    groups: dict = {}
    for person in people:
        groups.setdefault(person["account"], []).append(person["rid"])
    singles = {account: rids[0] for account, rids in groups.items() if len(rids) == 1}
    if len(singles) != 1:
        return
    used = set()
    for row in conn.execute("SELECT identity_id AS stored FROM users WHERE identity_id IS NOT NULL"):
        key = uuid_bytes(row["stored"])
        if key is not None:
            used.add(key)
    free = []
    for row in conn.execute("SELECT id AS stored FROM identities"):
        key = uuid_bytes(row["stored"])
        if key is not None and key not in used:
            free.append(key)
    if len(free) != 1:
        return
    rid = next(iter(singles.values()))
    conn.execute("UPDATE users SET identity_id = ? WHERE rowid = ?", (free[0], rid))


def _drop_indexes_using(conn, table: str, column: str) -> None:
    if not _has_table(conn, table):
        return
    for row in conn.execute(f'PRAGMA index_list("{table}")'):
        name = row["name"]
        if not name or name.startswith("sqlite_"):
            continue
        used = {info["name"] for info in conn.execute(f'PRAGMA index_info("{name}")')}
        if column in used:
            conn.execute(f'DROP INDEX IF EXISTS "{name}"')


def _copy_search_shards(conn) -> None:
    """Keep MySQL shard rows that were loaded into this SQLite file.

    ``search_records_0`` .. ``search_records_15`` are not the SQLite schema, but
    dropping them threw away the only copy of that search text. Copy the rows
    into the single ``search_records`` table first.
    """
    if not _has_table(conn, "search_records"):
        return
    dest = _column_names(conn, "search_records")
    wanted = (
        "account_id",
        "board_id",
        "card_id",
        "content",
        "created_at",
        "searchable_id",
        "searchable_type",
        "title",
    )
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    for row in rows:
        name = row["name"]
        if not re.fullmatch(r"search_records_\d+", name):
            continue
        present = _column_names(conn, name)
        cols = [column for column in wanted if column in dest and column in present]
        if "searchable_id" not in cols or "searchable_type" not in cols:
            continue
        quoted = ", ".join(f'"{column}"' for column in cols)
        required = [
            column
            for column in ("account_id", "board_id", "card_id", "created_at", "searchable_id", "searchable_type")
            if column in cols
        ]
        guard = " AND ".join(f'src."{column}" IS NOT NULL' for column in required)
        conn.execute(
            f'''
            INSERT INTO search_records ({quoted})
            SELECT {quoted} FROM "{name}" AS src
            WHERE {guard}
              AND NOT EXISTS (
                SELECT 1 FROM search_records AS existing
                WHERE existing.searchable_type = src.searchable_type
                  AND existing.searchable_id = src.searchable_id
              )
            '''
        )


def _drop_obsolete_tables(conn) -> None:
    for name in ("search_results", "card_engagements"):
        if _has_table(conn, name):
            conn.execute(f'DROP TABLE "{name}"')
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    for row in rows:
        name = row["name"]
        if re.fullmatch(r"search_index_\d+", name) or re.fullmatch(r"search_records_\d+", name):
            conn.execute(f'DROP TABLE "{name}"')


def _strip_expression_default(suffix: str) -> str:
    match = re.search(r"DEFAULT\s*\(", suffix)
    if not match:
        return suffix
    start = match.end() - 1
    depth = 0
    end = len(suffix)
    for index, char in enumerate(suffix[start:], start):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    return (suffix[: match.start()] + suffix[end:]).strip()


def _add_clause(declared: str, suffix: str | None) -> str:
    if not suffix:
        return declared
    if re.search(r"DEFAULT\s*\(", suffix):
        remainder = re.sub(r"\bNOT NULL\b", "", _strip_expression_default(suffix)).strip()
        return f"{declared} {remainder}".strip() if remainder else declared
    if re.search(r"\bNOT NULL\b", suffix) and "DEFAULT" not in suffix:
        return declared
    return f"{declared} {suffix}"


def _add_missing_columns(conn) -> None:
    for name, cols, _indexes, _ident in _tables():
        if not _has_table(conn, name):
            continue
        present = _column_names(conn, name)
        for col_name, declared, suffix in cols:
            if col_name == "id" or col_name in present:
                continue
            clause = _add_clause(declared, suffix)
            conn.execute(f'ALTER TABLE "{name}" ADD COLUMN "{col_name}" {clause}')


def _copy_account_id(conn, table: str, fk: str, parent: str) -> None:
    if not _has_table(conn, table) or not _has_table(conn, parent):
        return
    columns = _column_names(conn, table)
    parent_columns = _column_names(conn, parent)
    if "account_id" not in columns or fk not in columns or "account_id" not in parent_columns:
        return
    conn.execute(
        f'''
        UPDATE "{table}" SET account_id = (
            SELECT account_id FROM "{parent}" WHERE "{parent}".id = "{table}"."{fk}"
        )
        WHERE account_id IS NULL
          AND EXISTS (
            SELECT 1 FROM "{parent}"
            WHERE "{parent}".id = "{table}"."{fk}" AND "{parent}".account_id IS NOT NULL
          )
        '''
    )


def _backfill_account_ids(conn) -> None:
    for table, fk, parent in _ACCOUNT_FROM_PARENT:
        _copy_account_id(conn, table, fk, parent)
    if _has_table(conn, "entropies") and "account_id" in _column_names(conn, "entropies"):
        for container, parent in (("Board", "boards"), ("Card", "cards"), ("Column", "columns")):
            if _has_table(conn, parent):
                conn.execute(
                    f'''
                    UPDATE entropies SET account_id = (
                        SELECT account_id FROM "{parent}" WHERE "{parent}".id = entropies.container_id
                    )
                    WHERE account_id IS NULL AND container_type = ?
                      AND EXISTS (
                        SELECT 1 FROM "{parent}"
                        WHERE "{parent}".id = entropies.container_id
                          AND "{parent}".account_id IS NOT NULL
                      )
                    ''',
                    (container,),
                )
        conn.execute(
            """
            UPDATE entropies SET account_id = container_id
            WHERE account_id IS NULL AND container_type = 'Account'
            """
        )
    if _has_table(conn, "mentions") and "account_id" in _column_names(conn, "mentions"):
        if _has_table(conn, "cards"):
            conn.execute(
                """
                UPDATE mentions SET account_id = (
                    SELECT account_id FROM cards WHERE cards.id = mentions.source_id
                )
                WHERE account_id IS NULL AND source_type = 'Card'
                """
            )
        if _has_table(conn, "comments"):
            conn.execute(
                """
                UPDATE mentions SET account_id = (
                    SELECT account_id FROM comments WHERE comments.id = mentions.source_id
                )
                WHERE account_id IS NULL AND source_type = 'Comment'
                """
            )
    _copy_record_account(conn, "action_text_rich_texts", "record_type", "record_id")
    _copy_record_account(conn, "active_storage_attachments", "record_type", "record_id")
    if (
        _has_table(conn, "active_storage_blobs")
        and _has_table(conn, "active_storage_attachments")
        and "account_id" in _column_names(conn, "active_storage_blobs")
    ):
        conn.execute(
            """
            UPDATE active_storage_blobs SET account_id = (
                SELECT account_id FROM active_storage_attachments
                WHERE active_storage_attachments.blob_id = active_storage_blobs.id
                  AND active_storage_attachments.account_id IS NOT NULL
                LIMIT 1
            )
            WHERE account_id IS NULL
            """
        )
    if (
        _has_table(conn, "active_storage_variant_records")
        and _has_table(conn, "active_storage_blobs")
        and "account_id" in _column_names(conn, "active_storage_variant_records")
    ):
        conn.execute(
            """
            UPDATE active_storage_variant_records SET account_id = (
                SELECT account_id FROM active_storage_blobs
                WHERE active_storage_blobs.id = active_storage_variant_records.blob_id
            )
            WHERE account_id IS NULL
            """
        )
    if _has_table(conn, "tags") and "account_id" in _column_names(conn, "tags") and _has_table(conn, "taggings"):
        conn.execute(
            """
            UPDATE tags SET account_id = (
                SELECT cards.account_id FROM taggings
                JOIN cards ON cards.id = taggings.card_id
                WHERE taggings.tag_id = tags.id AND cards.account_id IS NOT NULL
                LIMIT 1
            )
            WHERE account_id IS NULL
            """
        )
    if _has_table(conn, "reactions") and "account_id" in _column_names(conn, "reactions"):
        columns = _column_names(conn, "reactions")
        if "comment_id" in columns and _has_table(conn, "comments"):
            conn.execute(
                """
                UPDATE reactions SET account_id = (
                    SELECT account_id FROM comments WHERE comments.id = reactions.comment_id
                )
                WHERE account_id IS NULL
                """
            )
        if "reactable_id" in columns and _has_table(conn, "comments"):
            conn.execute(
                """
                UPDATE reactions SET account_id = (
                    SELECT account_id FROM comments WHERE comments.id = reactions.reactable_id
                )
                WHERE account_id IS NULL AND reactable_type = 'Comment'
                """
            )
        if "reactable_id" in columns and _has_table(conn, "cards"):
            conn.execute(
                """
                UPDATE reactions SET account_id = (
                    SELECT account_id FROM cards WHERE cards.id = reactions.reactable_id
                )
                WHERE account_id IS NULL AND reactable_type = 'Card'
                """
            )


def _copy_record_account(conn, table: str, type_column: str, id_column: str) -> None:
    if not _has_table(conn, table) or "account_id" not in _column_names(conn, table):
        return
    for record_type, parent in (
        ("Card", "cards"),
        ("Comment", "comments"),
        ("Board", "boards"),
        ("User", "users"),
    ):
        if not _has_table(conn, parent):
            continue
        conn.execute(
            f'''
            UPDATE "{table}" SET account_id = (
                SELECT account_id FROM "{parent}" WHERE "{parent}".id = "{table}"."{id_column}"
            )
            WHERE account_id IS NULL AND "{type_column}" = ?
            ''',
            (record_type,),
        )


def _backfill_external_account_ids(conn) -> None:
    """Give every account an integer slug.

    A file from before external ids existed has no integer slug, so ``/None/``
    is not an account. Numbers already present stay where they are.
    """
    if not _has_table(conn, "accounts") or "external_account_id" not in _column_names(conn, "accounts"):
        return
    columns = _column_names(conn, "accounts")
    order = "created_at, id" if "created_at" in columns else "id"
    conn.execute("DROP TABLE IF EXISTS fizzy_external_ids")
    conn.execute(
        f"""
        CREATE TEMP TABLE fizzy_external_ids AS
        SELECT id,
               COALESCE((SELECT MAX(external_account_id) FROM accounts), 0)
               + ROW_NUMBER() OVER (ORDER BY {order}) AS external_account_id
        FROM accounts
        WHERE external_account_id IS NULL
        """
    )
    conn.execute(
        """
        UPDATE accounts SET external_account_id = (
            SELECT external_account_id FROM fizzy_external_ids
            WHERE fizzy_external_ids.id = accounts.id
        )
        WHERE id IN (SELECT id FROM fizzy_external_ids)
        """
    )
    conn.execute("DROP TABLE fizzy_external_ids")
    if not _has_table(conn, "account_external_id_sequences"):
        return
    if "value" not in _column_names(conn, "account_external_id_sequences"):
        return
    maximum = int(
        conn.execute("SELECT COALESCE(MAX(external_account_id), 0) AS value FROM accounts").fetchone()["value"]
        or 0
    )
    existing = conn.execute("SELECT value AS current FROM account_external_id_sequences").fetchall()
    if not existing:
        count = int(conn.execute("SELECT COUNT(*) AS n FROM accounts").fetchone()["n"] or 0)
        if not count:
            return
        sequence_columns = _column_names(conn, "account_external_id_sequences")
        fields = ["value"]
        params: list = [maximum]
        if "id" in sequence_columns:
            fields.insert(0, "id")
            params.insert(0, uuid7_bytes())
        now = dump_dt(utcnow())
        if "created_at" in sequence_columns:
            fields.extend(["created_at", "updated_at"])
            params.extend([now, now])
        quoted = ", ".join(f'"{field}"' for field in fields)
        placeholders = ", ".join("?" for _ in fields)
        conn.execute(
            f"INSERT INTO account_external_id_sequences ({quoted}) VALUES ({placeholders})",
            params,
        )
        return
    current = max(int(row["current"] or 0) for row in existing)
    if current < maximum:
        conn.execute(
            "UPDATE account_external_id_sequences SET value = ? WHERE value = ?",
            (maximum, current),
        )


def _normalize_active_flags(conn) -> None:
    """Store membership as 1 or 0 so later ``active = 1`` queries match.

    NULL means the column was added without a value. Ruby's default is active.
    """
    if not _has_table(conn, "users") or "active" not in _column_names(conn, "users"):
        return
    conn.execute(
        """
        UPDATE users SET active = CASE
            WHEN active IS NULL THEN 1
            WHEN lower(CAST(active AS TEXT)) IN ('1', 't', 'true', 'yes') THEN 1
            WHEN lower(CAST(active AS TEXT)) IN ('0', 'f', 'false', 'no') THEN 0
            ELSE active
        END
        WHERE active IS NULL
           OR typeof(active) != 'integer'
           OR active NOT IN (0, 1)
        """
    )


def _backfill_card_numbers(conn) -> None:
    """Give every card a positive number that is unique inside its account.

    A populated file can already have ``number`` filled with 0. SQLite's
    ``ADD COLUMN ... NOT NULL`` without a default stores 0, and the unique
    index on ``(account_id, number)`` then raises. That exception aborted
    ``connect()``, so a database that already had cards would not open.
    Numbers that are already positive and unique are left alone.
    """
    if not _has_table(conn, "cards") or "number" not in _column_names(conn, "cards"):
        return
    conn.execute("DROP TABLE IF EXISTS fizzy_card_number_backfill")
    conn.execute(
        """
        CREATE TEMP TABLE fizzy_card_number_backfill AS
        WITH ranked AS (
            SELECT id, account_id, created_at,
                   CASE WHEN number IS NOT NULL AND number > 0 THEN number END AS positive,
                   ROW_NUMBER() OVER (
                       PARTITION BY account_id,
                                    CASE WHEN number IS NOT NULL AND number > 0 THEN number END
                       ORDER BY created_at, id
                   ) AS dup_rn
            FROM cards
        ),
        keepers AS (
            SELECT id, account_id, positive AS number
            FROM ranked
            WHERE positive IS NOT NULL AND dup_rn = 1
        ),
        base AS (
            SELECT account_id, COALESCE(MAX(number), 0) AS base_n
            FROM keepers
            GROUP BY account_id
        ),
        needs AS (
            SELECT ranked.id, ranked.account_id, ranked.created_at
            FROM ranked
            WHERE ranked.id NOT IN (SELECT id FROM keepers)
        )
        SELECT needs.id AS id,
               COALESCE(base.base_n, 0) + ROW_NUMBER() OVER (
                   PARTITION BY needs.account_id
                   ORDER BY needs.created_at, needs.id
               ) AS number
        FROM needs
        LEFT JOIN base
          ON base.account_id = needs.account_id
          OR (base.account_id IS NULL AND needs.account_id IS NULL)
        """
    )
    conn.execute(
        """
        UPDATE cards SET number = (
            SELECT number FROM fizzy_card_number_backfill
            WHERE fizzy_card_number_backfill.id = cards.id
        )
        WHERE id IN (SELECT id FROM fizzy_card_number_backfill)
        """
    )
    conn.execute("DROP TABLE fizzy_card_number_backfill")
    if not _has_table(conn, "accounts") or "cards_count" not in _column_names(conn, "accounts"):
        return
    conn.execute(
        """
        UPDATE accounts SET cards_count = (
            SELECT MAX(number) FROM cards WHERE cards.account_id = accounts.id
        )
        WHERE EXISTS (
            SELECT 1 FROM cards
            WHERE cards.account_id = accounts.id
              AND cards.number > COALESCE(accounts.cards_count, 0)
        )
        """
    )


def _backfill(conn) -> None:
    _backfill_account_ids(conn)
    _backfill_external_account_ids(conn)
    _normalize_active_flags(conn)
    _backfill_card_numbers(conn)
    if _has_table(conn, "identities") and "staff" in _column_names(conn, "identities"):
        conn.execute("UPDATE identities SET staff = 0 WHERE staff IS NULL")
    if _has_table(conn, "magic_links") and "purpose" in _column_names(conn, "magic_links"):
        conn.execute("UPDATE magic_links SET purpose = 0 WHERE purpose IS NULL")
    if _has_table(conn, "events") and "particulars" in _column_names(conn, "events"):
        conn.execute("UPDATE events SET particulars = json_object() WHERE particulars IS NULL")
    if _has_table(conn, "filters") and "fields" in _column_names(conn, "filters"):
        conn.execute("UPDATE filters SET fields = json_object() WHERE fields IS NULL")
    if _has_table(conn, "notifications") and "unread_count" in _column_names(conn, "notifications"):
        conn.execute("UPDATE notifications SET unread_count = 0 WHERE unread_count IS NULL")


def _backfill_notifications(conn) -> None:
    """Port of 20260209165805: one notification row per user and card."""
    if not _has_table(conn, "notifications"):
        return
    columns = _column_names(conn, "notifications")
    if "card_id" not in columns:
        return
    event_columns = _column_names(conn, "events") if _has_table(conn, "events") else set()
    if {"id", "eventable_type", "eventable_id"} <= event_columns and "source_type" in columns:
        comment_card = (
            "(SELECT comments.card_id FROM comments WHERE comments.id = events.eventable_id)"
            if _has_table(conn, "comments")
            else "NULL"
        )
        conn.execute(
            f"""
            UPDATE notifications
            SET card_id = (
                SELECT CASE events.eventable_type
                    WHEN 'Card' THEN events.eventable_id
                    WHEN 'Comment' THEN {comment_card}
                END
                FROM events
                WHERE events.id = notifications.source_id
            )
            WHERE notifications.card_id IS NULL
              AND notifications.source_type = 'Event'
            """
        )
    mention_columns = _column_names(conn, "mentions") if _has_table(conn, "mentions") else set()
    if {"id", "source_type", "source_id"} <= mention_columns and "source_type" in columns:
        comment_card = (
            "(SELECT comments.card_id FROM comments WHERE comments.id = mentions.source_id)"
            if _has_table(conn, "comments")
            else "NULL"
        )
        conn.execute(
            f"""
            UPDATE notifications
            SET card_id = (
                SELECT CASE mentions.source_type
                    WHEN 'Card' THEN mentions.source_id
                    WHEN 'Comment' THEN {comment_card}
                END
                FROM mentions
                WHERE mentions.id = notifications.source_id
            )
            WHERE notifications.card_id IS NULL
              AND notifications.source_type = 'Mention'
            """
        )
    if "unread_count" in columns and "read_at" in columns:
        conn.execute(
            """
            UPDATE notifications SET unread_count = (
                SELECT SUM(CASE WHEN peers.read_at IS NULL THEN 1 ELSE 0 END)
                FROM notifications AS peers
                WHERE peers.user_id = notifications.user_id
                  AND peers.card_id = notifications.card_id
            )
            WHERE card_id IS NOT NULL
              AND id = (
                SELECT MAX(keepers.id) FROM notifications AS keepers
                WHERE keepers.user_id = notifications.user_id
                  AND keepers.card_id = notifications.card_id
              )
              AND (
                SELECT COUNT(*) FROM notifications AS peers
                WHERE peers.user_id = notifications.user_id
                  AND peers.card_id = notifications.card_id
              ) > 1
            """
        )
    conn.execute(
        """
        DELETE FROM notifications
        WHERE card_id IS NOT NULL
          AND id NOT IN (
            SELECT keep_id FROM (
                SELECT MAX(id) AS keep_id
                FROM notifications
                WHERE card_id IS NOT NULL
                GROUP BY user_id, card_id
            )
          )
        """
    )
    if "unread_count" in _column_names(conn, "notifications"):
        conn.execute(
            """
            UPDATE notifications
            SET unread_count = CASE WHEN read_at IS NULL THEN 1 ELSE 0 END
            WHERE card_id IS NOT NULL AND unread_count = 0 AND read_at IS NULL
            """
        )
    # Rows whose card cannot be resolved stay. Deleting them on every open
    # removed inbox history from a file that already had notifications.


def _dedupe_card_activity_spikes(conn) -> None:
    if not _has_table(conn, "card_activity_spikes"):
        return
    columns = _column_names(conn, "card_activity_spikes")
    if "card_id" not in columns or "id" not in columns:
        return
    order = "updated_at DESC, id DESC" if "updated_at" in columns else "id DESC"
    conn.execute(
        f"""
        DELETE FROM card_activity_spikes
        WHERE id NOT IN (
            SELECT keep_id FROM (
                SELECT id AS keep_id
                FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY card_id
                               ORDER BY {order}
                           ) AS rn
                    FROM card_activity_spikes
                )
                WHERE rn = 1
            )
        )
        """
    )


def _promote_first_admin(conn) -> None:
    if not _has_table(conn, "users"):
        return
    columns = _column_names(conn, "users")
    if "role" not in columns or "account_id" not in columns or "created_at" not in columns:
        return
    conn.execute(
        """
        UPDATE users SET role = 'owner'
        WHERE role = 'admin'
          AND NOT EXISTS (
            SELECT 1 FROM users AS owners
            WHERE owners.account_id = users.account_id AND owners.role = 'owner'
          )
          AND id = (
            SELECT admins.id FROM users AS admins
            WHERE admins.account_id = users.account_id AND admins.role = 'admin'
            ORDER BY admins.created_at, admins.id
            LIMIT 1
          )
        """
    )


def _drop_obsolete_indexes(conn) -> None:
    for name in OBSOLETE_INDEXES:
        conn.execute(f'DROP INDEX IF EXISTS "{name}"')


def _index_unique(conn, table: str, name: str):
    if not _has_table(conn, table):
        return None
    for row in conn.execute(f'PRAGMA index_list("{table}")'):
        if row["name"] == name:
            return bool(row["unique"])
    return None


def _ensure_indexes(conn) -> None:
    for table, name, columns, unique in index_specs():
        if not _has_table(conn, table):
            continue
        existing = _index_unique(conn, table, name)
        if existing is not None and existing != unique:
            conn.execute(f'DROP INDEX IF EXISTS "{name}"')
            existing = None
        if existing is not None:
            continue
        kind = "UNIQUE INDEX" if unique else "INDEX"
        try:
            conn.execute(f'CREATE {kind} IF NOT EXISTS "{name}" ON "{table}" ({columns})')
        except (sqlite3.OperationalError, sqlite3.IntegrityError):
            # A duplicate row must not stop the file from opening. Card numbers
            # are repaired before this step; anything still conflicting keeps
            # its rows and skips only this index.
            continue


def _stamp(conn) -> None:
    if not _has_table(conn, "schema_migrations"):
        return
    conn.executemany(
        "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
        [(version,) for version in MIGRATION_VERSIONS],
    )
    if SCHEMA_VERSION not in MIGRATION_VERSIONS:
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
            (SCHEMA_VERSION,),
        )


def _ensure_environment(conn) -> None:
    if not _has_table(conn, "ar_internal_metadata"):
        return
    row = conn.execute(
        "SELECT 1 FROM ar_internal_metadata WHERE key = 'environment'"
    ).fetchone()
    if row:
        return
    now = "1970-01-01 00:00:00.000000"
    conn.execute(
        "INSERT INTO ar_internal_metadata (key, value, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("environment", "development", now, now),
    )
