"""Codec, schema, JSON API, HTML board, and a Ruby-shaped SQLite swap."""

import json
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fizzy import create_app
from fizzy.codec import base36_to_bytes, bytes_to_base36, uuid7_bytes
from fizzy import store
from fizzy.db import connect
from fizzy.migrate import MIGRATION_VERSIONS
from fizzy.schema import SCHEMA_VERSION

SAMPLE = "01jcqzx8h0000000000000000"


def _table(conn, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


def _columns(conn, name: str) -> set[str]:
    return {row["name"] for row in conn.execute(f'PRAGMA table_info("{name}")')}


def app_in(directory: Path):
    database = directory / "fizzy.sqlite3"
    storage = directory / "storage"
    application = create_app({
        "DATABASE": str(database),
        "STORAGE": str(storage),
        "SECRET_KEY": "test-secret",
        "TESTING": True,
    })
    return application


class CodecTests(unittest.TestCase):
    def test_sample_id_roundtrip(self):
        raw = base36_to_bytes(SAMPLE)
        self.assertEqual(len(raw), 16)
        self.assertEqual(bytes_to_base36(raw), SAMPLE)
        self.assertEqual(len(bytes_to_base36(uuid7_bytes())), 25)


class SchemaTests(unittest.TestCase):
    def test_empty_file_gets_rails_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fresh.sqlite3"
            conn = connect(path)
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='accounts'"
            ).fetchone()
            self.assertIsNotNone(row)
            versions = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}
            self.assertEqual(versions, set(MIGRATION_VERSIONS))
            self.assertEqual(MIGRATION_VERSIONS[-1], SCHEMA_VERSION)
            self.assertIn("20260828120000", versions)
            fts = conn.execute(
                "SELECT name FROM sqlite_master WHERE name='search_records_fts'"
            ).fetchone()
            self.assertIsNotNone(fts)
            conn.close()
            again = connect(path)
            count = again.execute("SELECT COUNT(*) AS n FROM schema_migrations").fetchone()
            self.assertEqual(count["n"], len(MIGRATION_VERSIONS))
            again.close()

    def test_older_ruby_file_is_migrated_on_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.sqlite3"
            account = b"\x01" * 16
            identity = b"\x02" * 16
            membership = b"\x03" * 16
            user = b"\x04" * 16
            board = b"\x05" * 16
            card = b"\x06" * 16
            comment = b"\x07" * 16
            reaction = b"\x08" * 16
            event = b"\x09" * 16
            notification = b"\x0a" * 16
            now = "2026-01-01 00:00:00.000000"
            raw = sqlite3.connect(path)
            raw.executescript(
                """
                CREATE TABLE schema_migrations (version varchar NOT NULL PRIMARY KEY);
                CREATE TABLE accounts (
                    id blob PRIMARY KEY NOT NULL,
                    created_at datetime NOT NULL,
                    name varchar NOT NULL,
                    updated_at datetime NOT NULL
                );
                CREATE TABLE identities (
                    id blob PRIMARY KEY NOT NULL,
                    created_at datetime NOT NULL,
                    email_address varchar NOT NULL,
                    updated_at datetime NOT NULL
                );
                CREATE TABLE memberships (
                    id blob PRIMARY KEY NOT NULL,
                    created_at datetime NOT NULL,
                    identity_id blob NOT NULL,
                    join_code varchar,
                    tenant varchar NOT NULL,
                    updated_at datetime NOT NULL
                );
                CREATE TABLE users (
                    id blob PRIMARY KEY NOT NULL,
                    account_id blob,
                    active boolean NOT NULL DEFAULT 1,
                    created_at datetime NOT NULL,
                    membership_id blob,
                    name varchar NOT NULL,
                    role varchar NOT NULL DEFAULT 'member',
                    updated_at datetime NOT NULL
                );
                CREATE TABLE boards (
                    id blob PRIMARY KEY NOT NULL,
                    account_id blob,
                    all_access boolean NOT NULL DEFAULT 0,
                    created_at datetime NOT NULL,
                    creator_id blob NOT NULL,
                    name varchar NOT NULL,
                    updated_at datetime NOT NULL
                );
                CREATE TABLE cards (
                    id blob PRIMARY KEY NOT NULL,
                    account_id blob,
                    board_id blob NOT NULL,
                    created_at datetime NOT NULL,
                    creator_id blob NOT NULL,
                    last_active_at datetime NOT NULL,
                    status varchar NOT NULL DEFAULT 'published',
                    title varchar,
                    updated_at datetime NOT NULL
                );
                CREATE TABLE comments (
                    id blob PRIMARY KEY NOT NULL,
                    account_id blob,
                    card_id blob NOT NULL,
                    created_at datetime NOT NULL,
                    creator_id blob NOT NULL,
                    updated_at datetime NOT NULL
                );
                CREATE TABLE reactions (
                    id blob PRIMARY KEY NOT NULL,
                    comment_id blob NOT NULL,
                    content varchar(16) NOT NULL,
                    created_at datetime NOT NULL,
                    reacter_id blob NOT NULL,
                    updated_at datetime NOT NULL
                );
                CREATE TABLE events (
                    id blob PRIMARY KEY NOT NULL,
                    account_id blob,
                    action varchar NOT NULL,
                    board_id blob NOT NULL,
                    created_at datetime NOT NULL,
                    creator_id blob NOT NULL,
                    eventable_id blob NOT NULL,
                    eventable_type varchar NOT NULL,
                    updated_at datetime NOT NULL
                );
                CREATE TABLE notifications (
                    id blob PRIMARY KEY NOT NULL,
                    account_id blob,
                    created_at datetime NOT NULL,
                    read_at datetime,
                    source_id blob NOT NULL,
                    source_type varchar NOT NULL,
                    updated_at datetime NOT NULL,
                    user_id blob NOT NULL
                );
                CREATE TABLE card_activity_spikes (
                    id blob PRIMARY KEY NOT NULL,
                    card_id blob NOT NULL,
                    created_at datetime NOT NULL,
                    updated_at datetime NOT NULL
                );
                CREATE TABLE search_results (
                    id blob PRIMARY KEY NOT NULL,
                    created_at datetime NOT NULL,
                    updated_at datetime NOT NULL
                );
                CREATE TABLE account_exports (
                    id blob PRIMARY KEY NOT NULL,
                    account_id blob NOT NULL,
                    user_id blob NOT NULL,
                    status varchar NOT NULL DEFAULT 'pending',
                    completed_at datetime,
                    created_at datetime NOT NULL,
                    updated_at datetime NOT NULL
                );
                """
            )
            raw.execute("INSERT INTO schema_migrations (version) VALUES ('20251111122540')")
            raw.execute(
                "INSERT INTO accounts (id, created_at, name, updated_at) VALUES (?, ?, 'Home', ?)",
                (account, now, now),
            )
            raw.execute(
                "INSERT INTO identities (id, created_at, email_address, updated_at) VALUES (?, ?, 'ada@example.com', ?)",
                (identity, now, now),
            )
            raw.execute(
                "INSERT INTO memberships (id, created_at, identity_id, tenant, updated_at) VALUES (?, ?, ?, 'home', ?)",
                (membership, now, identity, now),
            )
            raw.execute(
                """INSERT INTO users
                   (id, account_id, created_at, membership_id, name, role, updated_at)
                   VALUES (?, ?, ?, ?, 'Ada', 'admin', ?)""",
                (user, account, now, membership, now),
            )
            raw.execute(
                """INSERT INTO boards
                   (id, account_id, created_at, creator_id, name, updated_at)
                   VALUES (?, ?, ?, ?, 'Product', ?)""",
                (board, account, now, user, now),
            )
            raw.execute(
                """INSERT INTO cards
                   (id, account_id, board_id, created_at, creator_id, last_active_at, title, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'Ship it', ?)""",
                (card, account, board, now, user, now, now),
            )
            raw.execute(
                """INSERT INTO comments
                   (id, account_id, card_id, created_at, creator_id, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (comment, account, card, now, user, now),
            )
            raw.execute(
                """INSERT INTO reactions
                   (id, comment_id, content, created_at, reacter_id, updated_at)
                   VALUES (?, ?, 'Yes', ?, ?, ?)""",
                (reaction, comment, now, user, now),
            )
            raw.execute(
                """INSERT INTO events
                   (id, account_id, action, board_id, created_at, creator_id, eventable_id, eventable_type, updated_at)
                   VALUES (?, ?, 'card_published', ?, ?, ?, ?, 'Card', ?)""",
                (event, account, board, now, user, card, now),
            )
            raw.execute(
                """INSERT INTO notifications
                   (id, account_id, created_at, source_id, source_type, updated_at, user_id)
                   VALUES (?, ?, ?, ?, 'Event', ?, ?)""",
                (notification, account, now, event, now, user),
            )
            raw.execute(
                "INSERT INTO card_activity_spikes (id, card_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (b"\x0b" * 16, card, now, now),
            )
            raw.execute(
                "INSERT INTO card_activity_spikes (id, card_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (b"\x0c" * 16, card, "2026-01-02 00:00:00.000000", "2026-01-02 00:00:00.000000"),
            )
            raw.execute(
                """INSERT INTO account_exports
                   (id, account_id, user_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (b"\x0d" * 16, account, user, now, now),
            )
            raw.commit()
            raw.close()

            conn = connect(path)
            self.assertFalse(_table(conn, "memberships"))
            self.assertFalse(_table(conn, "search_results"))
            self.assertFalse(_table(conn, "account_exports"))
            self.assertTrue(_table(conn, "exports"))
            self.assertTrue(_table(conn, "identity_transfers"))
            self.assertTrue(_table(conn, "action_pack_passkeys"))
            self.assertIn("verified_at", _columns(conn, "users"))
            self.assertNotIn("membership_id", _columns(conn, "users"))
            self.assertIn("staff", _columns(conn, "identities"))
            self.assertIn("number", _columns(conn, "cards"))
            self.assertIn("reactable_type", _columns(conn, "reactions"))
            self.assertNotIn("comment_id", _columns(conn, "reactions"))
            self.assertIn("card_id", _columns(conn, "notifications"))
            self.assertIn("type", _columns(conn, "exports"))
            opened = conn.execute("SELECT identity_id, role FROM users").fetchone()
            self.assertEqual(opened["identity_id"], bytes_to_base36(identity))
            self.assertEqual(opened["role"], "owner")
            numbered = conn.execute("SELECT number FROM cards").fetchone()
            self.assertEqual(numbered["number"], 1)
            counted = conn.execute("SELECT cards_count FROM accounts").fetchone()
            self.assertEqual(counted["cards_count"], 1)
            reacted = conn.execute("SELECT content, reactable_type, reactable_id FROM reactions").fetchone()
            self.assertEqual(reacted["content"], "Yes")
            self.assertEqual(reacted["reactable_type"], "Comment")
            self.assertEqual(reacted["reactable_id"], bytes_to_base36(comment))
            noted = conn.execute("SELECT card_id, unread_count FROM notifications").fetchone()
            self.assertEqual(noted["card_id"], bytes_to_base36(card))
            self.assertEqual(noted["unread_count"], 1)
            spikes = conn.execute("SELECT COUNT(*) AS n FROM card_activity_spikes").fetchone()
            self.assertEqual(spikes["n"], 1)
            versions = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}
            self.assertEqual(versions, set(MIGRATION_VERSIONS))
            conn.execute("UPDATE notifications SET unread_count = 5")
            conn.commit()
            conn.close()

            again = connect(path)
            self.assertEqual(
                again.execute("SELECT unread_count FROM notifications").fetchone()["unread_count"],
                5,
            )
            self.assertEqual(
                again.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"],
                1,
            )
            self.assertEqual(
                again.execute("SELECT identity_id FROM users").fetchone()["identity_id"],
                bytes_to_base36(identity),
            )
            again.close()


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = app_in(Path(self.tmp.name))
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def request(self, method, path, token=None, **kwargs):
        headers = {"Accept": "application/json"}
        headers.update(kwargs.pop("headers", {}))
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return getattr(self.client, method)(path, headers=headers, **kwargs)

    def test_board_flow_and_swap_shape(self):
        created = self.request(
            "post",
            "/signup",
            json={"signup": {"email_address": "ada@example.com", "full_name": "Ada Lovelace", "account_name": "Home"}},
        )
        self.assertEqual(created.status_code, 201, created.get_data(as_text=True))
        body = created.get_json()
        slug = body["slug"]
        token_response = self.request(
            "post",
            "/my/access_tokens",
            json={"access_token": {"description": "script", "permission": "write"}},
        )
        self.assertEqual(token_response.status_code, 201, token_response.get_data(as_text=True))
        token = token_response.get_json()["token"]

        board = self.request(
            "post",
            f"{slug}/boards.json",
            token,
            json={"board": {"name": "Product", "all_access": True}},
        )
        self.assertEqual(board.status_code, 201, board.get_data(as_text=True))
        board_id = board.get_json()["id"]
        self.assertEqual(board.get_json()["auto_postpone_period_in_days"], 30)

        column = self.request(
            "post",
            f"{slug}/boards/{board_id}/columns.json",
            token,
            json={"column": {"name": "Doing", "color": "var(--color-card-4)"}},
        )
        self.assertEqual(column.status_code, 201, column.get_data(as_text=True))
        column_id = column.get_json()["id"]
        self.assertEqual(column.get_json()["color"], "var(--color-card-4)")

        card = self.request(
            "post",
            f"{slug}/boards/{board_id}/cards.json",
            token,
            json={"card": {"title": "Ship the port", "description": "Keep the SQLite file."}},
        )
        self.assertEqual(card.status_code, 201, card.get_data(as_text=True))
        number = card.get_json()["number"]
        self.assertEqual(card.get_json()["description"], "Keep the SQLite file.")
        self.assertIn("action-text-content", card.get_json()["description_html"])
        etag = card.headers["ETag"]
        cached = self.request("get", f"{slug}/cards/{number}.json", token, headers={"If-None-Match": etag})
        self.assertEqual(cached.status_code, 304)

        step = self.request(
            "post",
            f"{slug}/cards/{number}/steps.json",
            token,
            json={"step": {"content": "Write the codec"}},
        )
        self.assertEqual(step.status_code, 201)
        step_id = step.get_json()["id"]
        done = self.request(
            "put",
            f"{slug}/cards/{number}/steps/{step_id}.json",
            token,
            json={"step": {"completed": True}},
        )
        self.assertTrue(done.get_json()["completed"])

        comment = self.request(
            "post",
            f"{slug}/cards/{number}/comments.json",
            token,
            json={"comment": {"body": "Looking good"}},
        )
        self.assertEqual(comment.status_code, 201)
        self.assertEqual(comment.get_json()["body"]["plain_text"], "Looking good")

        users = self.request("get", f"{slug}/users.json", token)
        user_id = users.get_json()[0]["id"]
        assigned = self.request(
            "post",
            f"{slug}/cards/{number}/assignments.json",
            token,
            json={"assignee_id": user_id},
        )
        self.assertEqual(assigned.status_code, 204)
        shown = self.request("get", f"{slug}/cards/{number}.json", token).get_json()
        self.assertEqual(shown["assignees"][0]["id"], user_id)
        self.assertEqual(shown["steps"][0]["completed"], True)

        tagged = self.request(
            "post",
            f"{slug}/cards/{number}/taggings.json",
            token,
            json={"tag_title": "port"},
        )
        self.assertEqual(tagged.status_code, 204)
        tags = self.request("get", f"{slug}/tags.json", token).get_json()
        self.assertEqual(tags[0]["title"], "port")

        reaction = self.request(
            "post",
            f"{slug}/cards/{number}/reactions.json",
            token,
            json={"reaction": {"content": "Yes"}},
        )
        self.assertEqual(reaction.status_code, 201)
        self.request("post", f"{slug}/cards/{number}/goldness.json", token)
        self.request("post", f"{slug}/cards/{number}/pin.json", token)
        golden = self.request("get", f"{slug}/cards/{number}.json", token).get_json()
        self.assertTrue(golden["golden"])
        pins = self.request("get", f"{slug}/my/pins.json", token).get_json()
        self.assertEqual(pins[0]["number"], number)

        triaged = self.request(
            "post",
            f"{slug}/cards/{number}/triage.json",
            token,
            json={"column_id": column_id},
        )
        self.assertEqual(triaged.status_code, 204)
        in_column = self.request("get", f"{slug}/cards/{number}.json", token).get_json()
        self.assertEqual(in_column["column"]["id"], column_id)

        self.request("post", f"{slug}/cards/{number}/not_now.json", token)
        postponed = self.request("get", f"{slug}/cards/{number}.json", token).get_json()
        self.assertTrue(postponed["postponed"])
        self.assertNotIn("column", postponed)

        self.request("post", f"{slug}/cards/{number}/closure.json", token)
        closed = self.request("get", f"{slug}/cards/{number}.json", token).get_json()
        self.assertTrue(closed["closed"])
        self.assertFalse(closed["postponed"])
        open_list = self.request("get", f"{slug}/cards.json", token).get_json()
        self.assertEqual(open_list, [])
        done_list = self.request("get", f"{slug}/cards.json?indexed_by=closed", token).get_json()
        self.assertEqual(done_list[0]["number"], number)

        found = self.request("get", f"{slug}/search.json?q=SQLite", token).get_json()
        self.assertEqual(found["cards"][0]["number"], number)

        hook = self.request(
            "post",
            f"{slug}/boards/{board_id}/webhooks.json",
            token,
            json={"webhook": {"name": "local", "url": "http://127.0.0.1:9/hook", "subscribed_actions": ["comment_created"]}},
        )
        self.assertEqual(hook.status_code, 201, hook.get_data(as_text=True))
        hook_id = hook.get_json()["id"]
        self.assertTrue(hook.get_json()["signing_secret"])
        self.request(
            "post",
            f"{slug}/cards/{number}/comments.json",
            token,
            json={"comment": {"body": "wake the hook"}},
        )
        deliveries = self.request("get", f"{slug}/boards/{board_id}/webhooks/{hook_id}/deliveries.json", token)
        self.assertEqual(deliveries.status_code, 200, deliveries.get_data(as_text=True))
        self.assertEqual(deliveries.get_json()[0]["state"], "errored")
        stored_headers = deliveries.get_json()[0]["request"]["headers"]
        self.assertNotIn("X-Webhook-Signature", stored_headers)

        readonly = self.request(
            "post",
            "/my/access_tokens",
            json={"access_token": {"description": "eyes", "permission": "read"}},
        ).get_json()["token"]
        blocked = self.request(
            "post",
            f"{slug}/boards/{board_id}/cards.json",
            readonly,
            json={"card": {"title": "nope"}},
        )
        self.assertEqual(blocked.status_code, 403)

        exported = self.request("post", f"{slug}/account/exports.json", token)
        self.assertEqual(exported.status_code, 201, exported.get_data(as_text=True))
        self.assertEqual(exported.get_json()["status"], "completed")
        download = self.client.get(exported.get_json()["download_url"], headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(download.status_code, 200)
        self.assertIn(b"manifest.json", download.data)

    def test_html_board_and_magic_link(self):
        page = self.client.get("/signup")
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.get_data(as_text=True)).group(1)
        signed = self.client.post(
            "/signup",
            data={
                "csrf_token": token,
                "signup[full_name]": "Grace Hopper",
                "signup[email_address]": "grace@example.com",
                "signup[account_name]": "Navy",
            },
            follow_redirects=True,
        )
        self.assertIn("Name the work", signed.get_data(as_text=True))
        token = re.search(r'name="csrf_token" value="([^"]+)"', signed.get_data(as_text=True)).group(1)
        made = self.client.post(
            signed.request.path.replace("/boards/new", "/boards"),
            data={"csrf_token": token, "board[name]": "Compiler"},
            follow_redirects=False,
        )
        board_page = self.client.get(made.location)
        html = board_page.get_data(as_text=True)
        self.assertIn("Maybe?", html)
        self.assertIn("Not Now", html)
        self.assertIn("Done", html)
        self.assertIn("filter__terms", html)
        self.assertIn("Filter these cards", html)
        self.assertIn('id="maybe"', html)
        self.assertIn('data-hotkey="jump"', html)
        self.assertIn('data-hotkey="k"', html)
        self.assertIn('data-hotkey="p"', html)
        self.assertIn('data-hotkey="n"', html)
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        action = re.search(r'action="([^"]+/columns)"', html).group(1)
        self.client.post(action, data={"csrf_token": token, "column[name]": "Doing", "column[color]": "var(--color-card-5)"})
        with_column = self.client.get(made.location).get_data(as_text=True)
        self.assertIn("Doing", with_column)
        self.assertIn("Edit column", with_column)
        card_action = re.search(r'action="([^"]+/cards)"', html).group(1)
        token = re.search(r'name="csrf_token" value="([^"]+)"', self.client.get(made.location).get_data(as_text=True)).group(1)
        landed = self.client.post(
            card_action,
            data={"csrf_token": token, "card[title]": "COBOL"},
            follow_redirects=True,
        )
        landed_html = landed.get_data(as_text=True)
        self.assertIn("COBOL", landed_html)
        self.assertIn("Doing", landed_html)
        card_href = re.search(r'href="([^"]+/cards/\d+)"', landed_html).group(1)
        card_html = self.client.get(card_href).get_data(as_text=True)
        self.assertIn('data-hotkey="done"', card_html)
        self.assertIn('data-hotkey="gold"', card_html)
        self.assertIn('data-hotkey="postpone"', card_html)
        self.assertIn("after 30 quiet days", card_html)
        self.assertIn("comment__body", card_html)
        self.assertIn("header--card", card_html)
        self.assertIn("card__meta-avatars--assignees", card_html)
        token = re.search(r'name="csrf_token" value="([^"]+)"', card_html).group(1)
        moved = self.client.post(
            card_href + "/closure",
            data={"csrf_token": token},
            headers={"X-Fizzy-Fragment": "card"},
        )
        self.assertEqual(moved.status_code, 200, moved.get_data(as_text=True))
        fragment = moved.get_json()
        self.assertEqual(fragment["lane"], "closed")
        self.assertIn("COBOL", fragment["html"])
        self.assertFalse(fragment["stay"])
        paged = self.client.post(
            card_href + "/goldness",
            data={"csrf_token": token},
            headers={"X-Fizzy-Fragment": "page"},
        )
        self.assertEqual(paged.status_code, 200, paged.get_data(as_text=True))
        sheet = paged.get_json()
        self.assertIn("golden-effect", sheet["html"])
        self.assertIn("Undo", sheet["html"])
        self.assertEqual(sheet["boardName"], "Compiler")

        self.client.post("/logout", data={"csrf_token": token, "_method": "delete"})
        login = self.client.get("/login")
        token = re.search(r'name="csrf_token" value="([^"]+)"', login.get_data(as_text=True)).group(1)
        code_page = self.client.post("/login", data={"csrf_token": token, "email_address": "grace@example.com"})
        code_html = code_page.get_data(as_text=True)
        code = re.search(r"Your code is ([0-9A-Z]+)", code_html).group(1)
        token = re.search(r'name="csrf_token" value="([^"]+)"', code_html).group(1)
        home = self.client.post("/login/code", data={"csrf_token": token, "code": code}, follow_redirects=True)
        self.assertIn("Latest Activity", home.get_data(as_text=True))
        self.assertIn("Added", home.get_data(as_text=True))


class SwapTests(unittest.TestCase):
    def test_ruby_blobs_roundtrip_through_the_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / "ruby.sqlite3"
            conn = connect(database)
            conn.close()
            identity = uuid7_bytes()
            account = uuid7_bytes()
            user = uuid7_bytes()
            board = uuid7_bytes()
            card = base36_to_bytes(SAMPLE)
            rich = uuid7_bytes()
            token_id = uuid7_bytes()
            now = "2026-02-03 04:05:06.123456"
            raw = sqlite3.connect(database)
            raw.execute(
                "INSERT INTO identities (id, created_at, email_address, staff, updated_at) VALUES (?, ?, ?, ?, ?)",
                (identity, now, "ruby@example.com", 0, now),
            )
            raw.execute(
                "INSERT INTO accounts (id, cards_count, created_at, external_account_id, name, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (account, 7, now, 880011, "Ruby", now),
            )
            raw.execute(
                """INSERT INTO users
                   (id, account_id, active, created_at, identity_id, name, role, updated_at, verified_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user, account, 1, now, identity, "Ruby Owner", "owner", now, now),
            )
            raw.execute(
                "INSERT INTO boards (id, account_id, all_access, created_at, creator_id, name, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (board, account, 1, now, user, "Imported", now),
            )
            raw.execute(
                """INSERT INTO cards
                   (id, account_id, board_id, column_id, created_at, creator_id, due_on, last_active_at, number, status, title, updated_at)
                   VALUES (?, ?, ?, NULL, ?, ?, NULL, ?, 7, 'published', ?, ?)""",
                (card, account, board, now, user, now, "From Ruby", now),
            )
            raw.execute(
                """INSERT INTO action_text_rich_texts
                   (id, account_id, body, created_at, name, record_id, record_type, updated_at)
                   VALUES (?, ?, ?, ?, 'description', ?, 'Card', ?)""",
                (rich, account, '<div class="action-text-content"><p>Kept <strong>HTML</strong></p></div>', now, card, now),
            )
            raw.execute(
                """INSERT INTO identity_access_tokens
                   (id, created_at, description, identity_id, permission, token, updated_at)
                   VALUES (?, ?, ?, ?, 'write', ?, ?)""",
                (token_id, now, "from ruby", identity, "ruby-token-plaintext", now),
            )
            raw.commit()
            raw.close()

            application = create_app({
                "DATABASE": str(database),
                "STORAGE": str(root / "storage"),
                "SECRET_KEY": "test-secret",
                "TESTING": True,
            })
            client = application.test_client()
            response = client.get(
                "/880011/cards/7.json",
                headers={"Authorization": "Bearer ruby-token-plaintext", "Accept": "application/json"},
            )
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            payload = response.get_json()
            self.assertEqual(payload["id"], SAMPLE)
            self.assertEqual(payload["title"], "From Ruby")
            self.assertEqual(payload["description"], "Kept HTML")
            self.assertIn("<strong>HTML</strong>", payload["description_html"])
            self.assertTrue(payload["created_at"].startswith("2026-02-03T04:05:06.123"))

            listed = client.get(
                "/880011/cards.json",
                headers={"Authorization": "Bearer ruby-token-plaintext"},
            )
            self.assertEqual(listed.status_code, 200, listed.get_data(as_text=True))
            self.assertEqual(json.loads(listed.get_data(as_text=True))[0]["number"], 7)

    def test_older_reactions_table_is_migrated_before_the_board_opens(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            application = app_in(root)
            client = application.test_client()
            signed = client.post(
                "/signup",
                json={"signup": {"email_address": "ada@example.com", "full_name": "Ada Lovelace", "account_name": "Home"}},
                headers={"Accept": "application/json"},
            )
            self.assertEqual(signed.status_code, 201, signed.get_data(as_text=True))
            slug = signed.get_json()["slug"]
            token = client.post(
                "/my/access_tokens",
                json={"access_token": {"description": "script", "permission": "write"}},
                headers={"Accept": "application/json"},
            ).get_json()["token"]
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            board = client.post(f"{slug}/boards.json", json={"board": {"name": "Product"}}, headers=headers)
            board_id = board.get_json()["id"]
            card = client.post(
                f"{slug}/boards/{board_id}/cards.json",
                json={"card": {"title": "Ship the port"}},
                headers=headers,
            )
            number = card.get_json()["number"]
            comment = client.post(
                f"{slug}/cards/{number}/comments.json",
                json={"comment": {"body": "Looking good"}},
                headers=headers,
            )
            comment_id = comment.get_json()["id"]
            user_id = client.get(f"{slug}/users.json", headers=headers).get_json()[0]["id"]

            raw = sqlite3.connect(root / "fizzy.sqlite3")
            raw.execute("DROP TABLE reactions")
            raw.execute(
                """
                CREATE TABLE reactions (
                    id blob PRIMARY KEY NOT NULL,
                    comment_id blob NOT NULL,
                    content varchar(16) NOT NULL,
                    created_at datetime NOT NULL,
                    reacter_id blob NOT NULL,
                    updated_at datetime NOT NULL
                )
                """
            )
            now = "2026-02-03 04:05:06.123456"
            raw.execute(
                "INSERT INTO reactions (id, comment_id, content, created_at, reacter_id, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (uuid7_bytes(), base36_to_bytes(comment_id), "Yes", now, base36_to_bytes(user_id), now),
            )
            raw.commit()
            raw.close()

            page = client.get(
                f"{slug}/boards/{board_id}",
                headers={"Authorization": f"Bearer {token}", "Accept": "text/html"},
            )
            self.assertEqual(page.status_code, 200, page.get_data(as_text=True))
            self.assertIn("Ship the port", page.get_data(as_text=True))

            conn = connect(root / "fizzy.sqlite3")
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(reactions)")}
            self.assertIn("reactable_type", columns)
            self.assertIn("reactable_id", columns)
            self.assertNotIn("comment_id", columns)
            found = store.reactions_of(conn, "Comment", comment_id)
            self.assertEqual([row["content"] for row in found], ["Yes"])
            self.assertEqual(found[0]["reactable_type"], "Comment")
            self.assertEqual(found[0]["reactable_id"], comment_id)
            self.assertEqual(store.reactions_of(conn, "Card", card.get_json()["id"]), [])
            versions = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}
            self.assertIn("20260121155752", versions)
            conn.close()


if __name__ == "__main__":
    unittest.main()
