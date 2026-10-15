# Decision log

This is a personal localhost tool. The bar for each feature was: does a Fizzy SQLite file need it, and does the board or the documented JSON API break without it? Rails, Solid Queue, Solid Cable, Solid Cache, billing, passkeys, outbound email, the PWA, and push notifications are out.

## Kept

- **SQLite only.** `FIZZY_DATABASE` is one file. MySQL and the 16 `search_records_*` shards are not opened. New files get the tables from `db/schema_sqlite.rb` (version `20260828120000`), including `search_records` with an integer primary key and an FTS5 table so the file shape is familiar. DDL runs only when `accounts` is missing.
- **Rails values.** Ids are 16-byte blobs in the file and 25-character base36 strings in JSON and URLs. Booleans are `0`/`1`. Timestamps are UTC `YYYY-MM-DD HH:MM:SS.ffffff`. JSON columns stay text. Foreign keys stay off.
- **Account slug.** `/{external_account_id}/...` matches Fizzy. Card URLs use the card number.
- **Magic-link login, without mail.** The 6-character code is returned in the HTML page and in the JSON body. Signup creates the identity, account, owner, and system user, then logs in. There is no password and no passkey table usage.
- **Bearer tokens.** `identity_access_tokens.token` is the plaintext Fizzy already stores. `read` tokens cannot write. Cookie sessions are a raw session-row id, not a Rails signed id. A browser logged into Ruby will not be logged in here.
- **Boards, columns, cards.** Maybe (published, open, not postponed, no column), workflow columns, Not now (`card_not_nows`, column cleared), Done (`closures`, column kept). Golden cards sort first. Triage resumes a card, then sets the column. Allowed postpone periods are 3, 7, 11, 30, 90, and 365 days. Auto-postpone runs when the HTML board is opened, as the system user, and does not refresh `last_active_at`.
- **Steps, comments, reactions, tags, assignments, watches, pins.** Comments and descriptions are Action Text rows (`div.action-text-content`). HTML is sanitized. `@Name` mentions and `data-user-id` mentions notify and watch.
- **In-app notifications.** One row per user and card; a new event clears `read_at` and bumps `unread_count`. Push tables exist for a swapped file and are never written.
- **Webhooks.** HMAC-SHA256 hex in `X-Webhook-Signature`, plus timestamp and `fizzy/1.0.0 Webhook`. Delivery happens before the response returns. Slack URLs get `{text}`. Other URLs get the activity JSON. Link-local addresses and `169.254.169.254` are refused. Localhost and private LAN are allowed, because this process never leaves the machine. A failed post is stored as `errored` and is not retried.
- **Search.** `LIKE` on title, description, and card number. `search_queries` rows are recorded. The FTS table is not queried.
- **Exports.** A zip of `cards/N.json` plus `manifest.json`, marked completed in the same request. It is a readable archive, not Fizzy’s data-transfer package. Account export is limited to owners and admins.
- **REST API.** Documented resources: identity, tokens, account, boards, columns, cards, steps, comments, reactions, tags, users, activity, notifications, pins, webhooks, deliveries, exports. Pagination is 30 rows and a `Link: rel=next` header. ETags are a hash of the JSON body.
- **Published boards.** A key in `board_publications` serves a read-only column view. Card images on a published board can be fetched without a session. Avatars without a file return an initials SVG.

## Dropped

- **Push notifications.** `push_subscriptions` is unused. No web-push, VAPID, or service worker.
- **Email delivery and digests.** `bundle_email_frequency` is stored so a Ruby file keeps its setting. Nothing is sent. `notification_bundles` are not built.
- **Passkeys, identity transfer, QR login, PWA, native shell.**
- **SaaS, billing, account cancellation jobs, imports from other products.**
- **Background jobs.** Auto-postpone, webhook delivery, and exports run in the request that needs them.
- **Activity-spike detection.** The stalled filter reads `card_activity_spikes` if Ruby already wrote them. This app does not create spikes.
- **Saved filters.** Query-string filters are implemented. The `filters` tables are not written.
- **MySQL, multi-db, replicas.**
- **Rails session signing, rate limits, and Surfguard’s public-only webhook policy.** CSRF still covers HTML forms. JSON with a bearer token or `Content-Type: application/json` does not send a form token. There is no CORS.
- **Campfire and Basecamp webhook formatting.** Slack text and the activity JSON are enough.
- **Account rename as an API endpoint.** It is a settings form only.

## UX

The board is a horizontal row of ~450px columns with tinted card bubbles. Column color is the CSS variable Fizzy stores (`var(--color-card-default)` through `var(--color-card-8)`). Dragging a card posts the same triage, not-now, close, or send-back actions the buttons use. The card page edits the title and description, steps, comments, tags, assignees, gold, pin, watch, and column.

A description is left untouched when the textarea still matches the current plain text, so opening a Ruby card and saving the title does not flatten Action Text HTML.
