# Fizzy

A local Flask board for a [Fizzy](https://github.com/basecamp/fizzy) SQLite database. Maybe stays in the center, Not Now and Done sit on collapsed rails, and the JSON API Fizzy documents is included. `J` opens the menu, `K` searches in the bottom bar, and `[` `]` move a card to Not Now or Done without reloading the board.

The app binds to `127.0.0.1`. It speaks SQLite only. Point it at a database the Ruby app already created and the same rows stay readable.

## Run

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m fizzy
```

Open http://127.0.0.1:47621 . The first visit can create an account in `instance/fizzy.sqlite3`. Sign-in codes are shown on the next page because nothing is emailed.

On a board, `C` adds a card, `J` opens the jump menu, `K` search, `P` pins, and `N` the inbox. Arrows move between columns and cards, Enter opens a card, `[` sends it to Not Now, `]` marks it Done, and `M` assigns it to you. On a card, `D` completes it, `E` edits the title, `T` tags, `A` assigns, Shift+`G` toggles gold, and Esc or Left goes back. Shortcuts stay quiet while you are typing.

| Variable | Default | Purpose |
| --- | --- | --- |
| `FIZZY_DATABASE` | `instance/fizzy.sqlite3` | SQLite file |
| `FIZZY_STORAGE` | `instance/storage` | Active Storage files (`key[:2]/key[2:4]/key`, with a flat fallback) |
| `FIZZY_SECRET` | `instance/secret_key` | Cookie and email-confirmation signing |
| `FIZZY_HOST` | `127.0.0.1` | Bind address |
| `FIZZY_PORT` | `47621` | Bind port |

## Swap in a Ruby database

Stop the Ruby process so the file is not locked, then:

```bash
FIZZY_DATABASE=/path/to/storage/development.sqlite3 \
FIZZY_STORAGE=/path/to/storage \
python -m fizzy
```

Opening the file runs the Fizzy app migrations through `20260828120000` and records them in `schema_migrations`. A database from an older Ruby release gains the current columns and tables in place, including polymorphic reactions, card numbers, and `identity_transfers`. A file this app already created is left intact and the historical versions are stamped. SaaS tables and the MySQL search shards are not created. Blob UUIDs, `0`/`1` booleans, and `YYYY-MM-DD HH:MM:SS.ffffff` timestamps stay as they are. Personal access tokens already in `identity_access_tokens` work as `Authorization: Bearer` values. The browser session cookie is this app's own session id, so log in again in the browser (the code appears on screen).

## API

Paths match Fizzy: `/{external_account_id}/boards.json`, `/cards/{number}.json`, and the rest of the documented resources. Send `Accept: application/json` or a `.json` suffix. Bearer tokens skip the HTML form token. `ETag` / `If-None-Match` return `304` when the body is unchanged.

## Tests

```bash
python -m unittest discover -s tests
```

Why a feature was kept or dropped is in `DECISIONS.md`.
