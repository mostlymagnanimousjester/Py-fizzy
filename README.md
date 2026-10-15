# Fizzy

A local Flask board for a [Fizzy](https://github.com/basecamp/fizzy) SQLite database. It is a personal kanban: wide columns for Maybe, the workflow you name, Not now, and Done, plus the JSON API Fizzy documents.

The app binds to `127.0.0.1`. It speaks SQLite only. Point it at a database the Ruby app already created and the same rows stay readable.

## Run

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m fizzy
```

Open http://127.0.0.1:47621 . The first visit can create an account in `instance/fizzy.sqlite3`. Sign-in codes are shown on the next page because nothing is emailed.

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

Schema is applied only when `accounts` is missing. An existing Fizzy file is opened as-is: blob UUIDs, `0`/`1` booleans, and `YYYY-MM-DD HH:MM:SS.ffffff` timestamps. Personal access tokens already in `identity_access_tokens` work as `Authorization: Bearer` values. The browser session cookie is this app's own session id, so log in again in the browser (the code appears on screen).

## API

Paths match Fizzy: `/{external_account_id}/boards.json`, `/cards/{number}.json`, and the rest of the documented resources. Send `Accept: application/json` or a `.json` suffix. Bearer tokens skip the HTML form token. `ETag` / `If-None-Match` return `304` when the body is unchanged.

## Tests

```bash
python -m unittest discover -s tests
```

Why a feature was kept or dropped is in `DECISIONS.md`.
