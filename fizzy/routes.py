"""HTTP routes for the board and the Fizzy JSON API."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from .codec import iso, parse_dt, utcnow
from .db import q1, update
from .constants import COLUMN_COLORS, PAGE_SIZE, POSTPONE_DAYS, WEBHOOK_ACTIONS
from .errors import FizzyError, forbidden, invalid, not_found, unauthorized
from .present import (
    Urls,
    account_json,
    board_json,
    card_json,
    card_view,
    color_label,
    column_json,
    comment_json,
    event_json,
    notification_json,
    reaction_json,
    settings_json,
    step_json,
    tag_json,
    user_json,
    webhook_json,
)
from . import store

bp = Blueprint("fizzy", __name__)


def conn():
    return g.conn


def wants_json() -> bool:
    if request.environ.get("fizzy.json"):
        return True
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return True
    accept = request.headers.get("Accept", "")
    return "application/json" in accept and "text/html" not in accept


def csrf_token() -> str:
    token = session.get("_csrf")
    if not token:
        token = hashlib.sha256(session.get("_csrf_seed", request.remote_addr or "local").encode()).hexdigest()
        # A stable secret mixed with a random session value.
        import secrets
        token = secrets.token_urlsafe(24)
        session["_csrf"] = token
    return token


def check_csrf():
    if request.headers.get("Authorization", "").lower().startswith("bearer "):
        return
    if request.is_json:
        return
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    if not sent or sent != session.get("_csrf"):
        # Issue a token first so a missing session doesn't loop forever on the login form.
        if "_csrf" not in session:
            csrf_token()
            sent = request.form.get("csrf_token")
        if not sent or sent != session.get("_csrf"):
            raise forbidden("The form expired. Reload the page and try again.")


def origin() -> str:
    return request.host_url.rstrip("/")


def urls_for(account) -> Urls:
    external = account["external_account_id"] if account else None
    return Urls(origin(), external)


def json_body(payload, status=200, location=None, extra_headers=None):
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    etag = hashlib.sha256(raw.encode()).hexdigest()[:32]
    if request.method in {"GET", "HEAD"} and request.headers.get("If-None-Match") == f'"{etag}"':
        response = make_response("", 304)
        response.headers["ETag"] = f'"{etag}"'
        return response
    response = make_response(raw, status)
    response.mimetype = "application/json"
    response.headers["ETag"] = f'"{etag}"'
    response.headers["Cache-Control"] = "max-age=0, private, must-revalidate"
    if location:
        response.headers["Location"] = location
    for key, value in (extra_headers or {}).items():
        response.headers[key] = value
    return response


def page_window():
    try:
        page = max(int(request.args.get("page", 1)), 1)
    except ValueError:
        page = 1
    return page, PAGE_SIZE, (page - 1) * PAGE_SIZE


def paginate(items):
    page, size, _offset = page_window()
    extra = len(items) > size
    rows = items[:size]
    headers = {}
    if extra:
        query = request.args.to_dict(flat=False)
        query["page"] = [str(page + 1)]
        flat = []
        for key, values in query.items():
            for value in values:
                flat.append((key, value))
        link = request.base_url + "?" + urlencode(flat)
        headers["Link"] = f'<{link}>; rel="next"'
    return rows, headers


def multi(name: str) -> list[str]:
    values = request.args.getlist(f"{name}[]") or request.args.getlist(name)
    return [value for value in values if value]


def form_body(root: str) -> dict:
    if request.is_json:
        data = request.get_json(silent=True) or {}
        nested = data.get(root)
        if isinstance(nested, dict):
            merged = dict(nested)
        else:
            merged = dict(data)
        return merged
    result: dict = {}
    prefix = f"{root}["
    for key, value in request.form.items():
        if key.startswith(prefix) and key.endswith("]"):
            inner = key[len(prefix):-1]
            if inner.endswith("[]"):
                result.setdefault(inner[:-2], [])
                result[inner[:-2]].append(value)
            else:
                result[inner] = value
        elif key == root:
            result[key] = value
    for key, storage in request.files.items():
        inner = key
        if key.startswith(prefix) and key.endswith("]"):
            inner = key[len(prefix):-1]
        if storage and storage.filename:
            result[inner] = storage
    if not result:
        result.update(request.form.to_dict())
    return result


def as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "t", "on", "yes"}


def verb() -> str:
    override = (request.form.get("_method") or request.args.get("_method") or "").upper()
    if request.method == "POST" and override in {"PUT", "PATCH", "DELETE"}:
        return override
    return request.method


def load_identity():
    g.identity = None
    g.permission = "write"
    g.user = None
    g.account = None
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        raw = header.split(" ", 1)[1].strip()
        found = store.identity_for_bearer(conn(), raw)
        if not found:
            raise unauthorized("That access token is not valid")
        g.identity, g.permission = found
        return
    session_id = request.cookies.get("session_token")
    if session_id:
        g.identity = store.session_identity(conn(), session_id)
        g.permission = "write"


def require_identity():
    load_identity()
    if not g.identity:
        if wants_json():
            raise unauthorized()
        session["next"] = request.url
        return redirect(url_for("fizzy.login"))
    return None


def enter_account(slug: int):
    bounced = require_identity()
    if bounced:
        return bounced
    account = store.account_by_external(conn(), slug)
    if not account:
        raise not_found("No account uses that address")
    user = store.user_for_identity(conn(), account["id"], g.identity["id"])
    if not user or not user["active"]:
        raise forbidden("You are not a member of this account")
    if g.permission == "read" and verb() not in {"GET", "HEAD"}:
        raise forbidden("This token is read-only")
    g.account = account
    g.user = user
    g.slug = f"/{account['external_account_id']}"
    return None


def require_board(board_id: str):
    board = store.board_by_id(conn(), board_id)
    if not board or board["account_id"] != g.account["id"] or not store.can_see_board(conn(), g.user, board):
        raise not_found("Board not found")
    return board


def require_card(number: int):
    card = store.card_by_number(conn(), g.account["id"], number)
    if not card:
        raise not_found("Card not found")
    board = store.board_by_id(conn(), card["board_id"])
    if not board or not store.can_see_board(conn(), g.user, board):
        raise not_found("Card not found")
    return card, board


@bp.before_request
def prepare():
    if request.endpoint == "static":
        return
    csrf_token()
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        check_csrf()


@bp.context_processor
def inject():
    account = getattr(g, "account", None)
    user = getattr(g, "user", None)
    unread = store.unread_count(conn(), user["id"]) if user else 0
    boards = store.boards_for(conn(), user) if user else []
    tray_pins = []
    tray_notes = []
    if user and account:
        urls = Urls(request.host_url.rstrip("/"), account["external_account_id"])
        for card in store.pins_for_user(conn(), user)[:8]:
            tray_pins.append({"number": card["number"], "title": card["title"] or "Untitled"})
        tray_notes = [notification_json(conn(), row, urls) for row in store.notifications_for(conn(), user, 8, 0)]
    return {
        "csrf_token": session.get("_csrf", ""),
        "identity": getattr(g, "identity", None),
        "current_user": user,
        "account": account,
        "slug": getattr(g, "slug", ""),
        "unread": unread,
        "nav_boards": boards,
        "tray_pins": tray_pins,
        "tray_notes": tray_notes,
        "colors": COLUMN_COLORS,
        "color_label": color_label,
        "postpone_choices": POSTPONE_DAYS,
        "webhook_actions": WEBHOOK_ACTIONS,
    }


@bp.app_template_filter("iso")
def _iso(value):
    return iso(value) or ""


def _redirect_home():
    accounts = store.accounts_for_identity(conn(), g.identity["id"])
    nxt = session.pop("next", None)
    if nxt and nxt.startswith(request.host_url):
        return redirect(nxt)
    if len(accounts) == 1:
        return redirect(f"/{accounts[0]['external_account_id']}/")
    return redirect(url_for("fizzy.accounts"))


def _start_session(identity_id: str):
    session_id = store.create_session(conn(), identity_id, request.remote_addr, request.user_agent.string)
    response_target = _redirect_home()
    # identity must be visible to _redirect_home
    return session_id, response_target


# --- signed-out -----------------------------------------------------------

@bp.route("/")
def root():
    load_identity()
    if not g.identity:
        return redirect(url_for("fizzy.login"))
    return _redirect_home()


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    load_identity()
    if request.method == "GET":
        return render_template("signup.html")
    payload = form_body("signup")
    identity, account, _user = store.signup(
        conn(),
        payload.get("email_address", ""),
        payload.get("full_name", ""),
        payload.get("account_name", ""),
    )
    session_id = store.create_session(conn(), identity["id"], request.remote_addr, request.user_agent.string)
    g.identity = identity
    if wants_json():
        response = json_body(
            {"id": identity["id"], "email_address": identity["email_address"], "slug": f"/{account['external_account_id']}"},
            201,
        )
    else:
        flash("Account created. This database now has a board waiting for work.")
        response = redirect(f"/{account['external_account_id']}/boards/new")
    response.set_cookie("session_token", session_id, httponly=True, samesite="Lax", path="/")
    return response


@bp.route("/login", methods=["GET", "POST"])
def login():
    load_identity()
    if g.identity and request.method == "GET":
        return _redirect_home()
    if request.method == "GET":
        return render_template("login.html")
    payload = form_body("session") or form_body("login")
    email = (payload.get("email_address") or request.form.get("email_address") or "").strip()
    identity = store.identity_by_email(conn(), email) if email else None
    if not identity:
        raise invalid({"email_address": ["No identity uses that email. Create an account first."]})
    link = store.create_magic_link(conn(), identity["id"], 0)
    session["pending_link"] = link["id"]
    if wants_json():
        response = json_body(
            {"pending_authentication_token": link["id"], "code": link["code"]},
            201,
        )
        response.set_cookie("pending_authentication_token", link["id"], httponly=True, samesite="Lax", path="/")
        return response
    return render_template("login_code.html", code=link["code"], email=identity["email_address"])


@bp.route("/session", methods=["POST", "DELETE"])
def session_collection():
    if verb() == "DELETE" or request.method == "DELETE":
        load_identity()
        session_id = request.cookies.get("session_token")
        if session_id:
            store.delete_session(conn(), session_id)
        response = json_body({}, 204) if wants_json() else redirect(url_for("fizzy.login"))
        response.delete_cookie("session_token", path="/")
        return response
    return login()


@bp.route("/login/code", methods=["POST"])
@bp.route("/session/magic_link", methods=["POST"])
def magic_link():
    payload = form_body("magic_link")
    code = (payload.get("code") or request.form.get("code") or "").strip()
    link_id = (
        request.cookies.get("pending_authentication_token")
        or session.get("pending_link")
        or payload.get("pending_authentication_token")
    )
    if not link_id or not code:
        raise unauthorized("The code doesn't match")
    identity = store.consume_magic_link(conn(), link_id, code)
    if not identity:
        raise unauthorized("The code doesn't match")
    session.pop("pending_link", None)
    session_id = store.create_session(conn(), identity["id"], request.remote_addr, request.user_agent.string)
    g.identity = identity
    if wants_json():
        response = json_body({"session_token": session_id})
    else:
        response = _redirect_home()
    response.set_cookie("session_token", session_id, httponly=True, samesite="Lax", path="/")
    response.delete_cookie("pending_authentication_token", path="/")
    return response


@bp.route("/logout", methods=["POST"])
def logout():
    return session_collection()


@bp.route("/accounts")
def accounts():
    bounced = require_identity()
    if bounced:
        return bounced
    rows = store.accounts_for_identity(conn(), g.identity["id"])
    if wants_json():
        return json_body({"accounts": [{"name": row["name"], "slug": f"/{row['external_account_id']}"} for row in rows]})
    return render_template("accounts.html", accounts=rows)


@bp.route("/my/identity", methods=["GET"])
def my_identity():
    bounced = require_identity()
    if bounced:
        return bounced
    rows = store.accounts_for_identity(conn(), g.identity["id"])
    accounts = []
    for row in rows:
        user = store.user_by_id(conn(), row["user_id"])
        urls = Urls(origin(), row["external_account_id"])
        accounts.append({
            "id": row["id"],
            "name": row["name"],
            "slug": f"/{row['external_account_id']}",
            "created_at": iso(row["created_at"]),
            "user": user_json(user, urls),
        })
    if wants_json():
        return json_body({"id": g.identity["id"], "accounts": accounts})
    return render_template("accounts.html", accounts=rows)


@bp.route("/my/access_tokens", methods=["GET", "POST"])
def access_tokens():
    bounced = require_identity()
    if bounced:
        return bounced
    if request.method == "POST":
        payload = form_body("access_token")
        created = store.create_access_token(
            conn(),
            g.identity["id"],
            payload.get("description") or "Personal token",
            payload.get("permission") or "read",
        )
        if wants_json():
            return json_body(
                {
                    "id": created["id"],
                    "token": created["token"],
                    "description": created["description"],
                    "permission": created["permission"],
                    "created_at": iso(created["created_at"]),
                },
                201,
                location=origin() + "/my/access_tokens/" + created["id"] + ".json",
            )
        flash("Copy this token now. It stays in the database, but this screen is the one that shows it in full.")
        return render_template("token_created.html", token=created)
    rows = store.access_tokens(conn(), g.identity["id"])
    if wants_json():
        return json_body([
            {"id": row["id"], "description": row["description"], "permission": row["permission"], "created_at": iso(row["created_at"])}
            for row in rows
        ])
    return render_template("tokens.html", tokens=rows)


@bp.route("/my/access_tokens/<token_id>", methods=["DELETE", "POST"])
def access_token_delete(token_id):
    bounced = require_identity()
    if bounced:
        return bounced
    if verb() != "DELETE" and request.method != "DELETE":
        abort(404)
    store.delete_access_token(conn(), g.identity["id"], token_id)
    if wants_json():
        return json_body({}, 204)
    flash("Token revoked.")
    return redirect(url_for("fizzy.access_tokens"))


@bp.route("/up")
def health():
    return {"ok": True, "service": "fizzy"}


# --- account home ----------------------------------------------------------

@bp.route("/<int:slug>/")
def home(slug):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    _page, size, offset = page_window()
    events = store.events_for(conn(), g.user, multi("board_ids"), multi("creator_ids"), size + 1, offset)
    rows, headers = paginate(events)
    urls = urls_for(g.account)
    if wants_json():
        return json_body([event_json(conn(), event, urls) for event in rows], extra_headers=headers)
    described = []
    for event in rows:
        payload = event_json(conn(), event, urls)
        described.append(payload)
    return render_template("activity.html", events=described)


@bp.route("/<int:slug>/activities")
def activities(slug):
    return home(slug)


@bp.route("/<int:slug>/search")
def search(slug):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    terms = (request.args.get("q") or request.args.get("terms") or " ".join(multi("terms"))).strip()
    cards = store.search_cards(conn(), g.user, terms) if terms else []
    urls = urls_for(g.account)
    if wants_json():
        return json_body({"terms": terms, "cards": [card_json(conn(), card, urls) for card in cards]})
    views = [card_view(conn(), card, g.user["id"]) for card in cards]
    return render_template("search.html", terms=terms, cards=views)


# --- boards ----------------------------------------------------------------

@bp.route("/<int:slug>/boards", methods=["GET", "POST"])
def boards(slug):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    urls = urls_for(g.account)
    if request.method == "POST":
        payload = form_body("board")
        board = store.create_board(
            conn(),
            g.user,
            payload.get("name", ""),
            as_bool(payload.get("all_access"), True),
            int(payload["auto_postpone_period_in_days"]) if payload.get("auto_postpone_period_in_days") else None,
        )
        if payload.get("public_description"):
            board = store.update_board(conn(), g.user, board, public_description=payload.get("public_description"))
        g.deliver = True
        if wants_json():
            return json_body(board_json(conn(), board, urls, detailed=True), 201, urls("boards", board["id"]) + ".json")
        return redirect(f"{g.slug}/boards/{board['id']}")
    rows = store.boards_for(conn(), g.user)
    if wants_json():
        return json_body([board_json(conn(), board, urls) for board in rows])
    return render_template("boards.html", boards=rows)


@bp.route("/<int:slug>/boards/new")
def board_new(slug):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    return render_template("board_form.html", board=None)


@bp.route("/<int:slug>/boards/<board_id>", methods=["GET", "PUT", "POST", "DELETE"])
def board_detail(slug, board_id):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    board = require_board(board_id)
    urls = urls_for(g.account)
    action = verb()
    if action == "DELETE":
        store.delete_board(conn(), g.user, board)
        if wants_json():
            return json_body({}, 204)
        flash(f"Deleted {board['name']}.")
        return redirect(f"{g.slug}/boards")
    if action in {"PUT", "PATCH"}:
        payload = form_body("board")
        user_ids = payload.get("user_ids")
        if isinstance(user_ids, str):
            user_ids = [user_ids]
        updated = store.update_board(
            conn(),
            g.user,
            board,
            name=payload.get("name"),
            all_access=as_bool(payload["all_access"]) if "all_access" in payload else None,
            user_ids=user_ids,
            public_description=payload.get("public_description"),
        )
        if wants_json():
            return json_body(board_json(conn(), updated, urls, detailed=True))
        flash("Board saved.")
        return redirect(f"{g.slug}/boards/{board_id}/edit")
    if wants_json() and request.args.get("view") != "columns":
        # JSON board show is the resource. HTML show is the kanban.
        if "application/json" in request.headers.get("Accept", "") or request.environ.get("fizzy.json"):
            return json_body(board_json(conn(), board, urls, detailed=True))
    store.touch_access(conn(), board["id"], g.user["id"])
    store.auto_postpone_board(conn(), board)
    g.deliver = True
    columns = store.columns_for(conn(), board["id"])
    lanes = {
        "maybe": [card_view(conn(), card, g.user["id"]) for card in store.lane_cards(conn(), board["id"], "maybe")],
        "not_now": [card_view(conn(), card, g.user["id"]) for card in store.lane_cards(conn(), board["id"], "not_now")],
        "closed": [card_view(conn(), card, g.user["id"]) for card in store.lane_cards(conn(), board["id"], "closed")],
    }
    column_views = []
    for column in columns:
        column_views.append({
            "column": column,
            "cards": [card_view(conn(), card, g.user["id"]) for card in store.column_cards(conn(), column["id"])],
        })
    published = store.publication(conn(), board["id"])
    filters = _card_filters()
    filters["board_ids"] = [board["id"]]
    filtering = bool(
        request.args.get("indexed_by")
        or request.args.get("q")
        or request.args.get("creation")
        or request.args.get("closure")
        or multi("assignee_ids")
        or multi("creator_ids")
        or multi("tag_ids")
    )
    filtered = [card_view(conn(), card, g.user["id"]) for card in store.query_cards(conn(), g.user, filters, 60, 0)] if filtering else []
    return render_template(
        "board.html",
        board=board,
        columns=column_views,
        lanes=lanes,
        published=published,
        days=store.postpone_days(conn(), board["account_id"], board["id"]),
        filtering=filtering,
        filtered=filtered,
        filters=filters,
    )


@bp.route("/<int:slug>/boards/<board_id>/edit")
def board_edit(slug, board_id):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    board = require_board(board_id)
    members = store.users_in_account(conn(), g.account["id"])
    granted = set(store.board_user_ids(conn(), board["id"]))
    return render_template(
        "board_form.html",
        board=board,
        members=members,
        granted=granted,
        hooks=store.webhooks_for(conn(), board["id"]),
        published=store.publication(conn(), board["id"]),
        days=store.postpone_days(conn(), board["account_id"], board["id"]),
        public_description=store.rich_text(conn(), "Board", board["id"], "public_description"),
    )


@bp.route("/<int:slug>/boards/<board_id>/columns", methods=["GET", "POST"])
def columns(slug, board_id):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    board = require_board(board_id)
    urls = urls_for(g.account)
    if request.method == "POST":
        payload = form_body("column")
        column = store.create_column(conn(), g.user, board, payload.get("name", ""), payload.get("color"))
        if wants_json():
            return json_body(column_json(column, urls), 201, urls("boards", board["id"], "columns", column["id"]) + ".json")
        return redirect(f"{g.slug}/boards/{board['id']}")
    rows = store.columns_for(conn(), board["id"])
    return json_body([column_json(column, urls) for column in rows])


@bp.route("/<int:slug>/boards/<board_id>/columns/<column_id>", methods=["GET", "PUT", "POST", "DELETE"])
def column_detail(slug, board_id, column_id):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    board = require_board(board_id)
    column = store.column_by_id(conn(), column_id)
    if not column or column["board_id"] != board["id"]:
        raise not_found("Column not found")
    urls = urls_for(g.account)
    action = verb()
    if action == "DELETE":
        store.delete_column(conn(), g.user, column)
        if wants_json():
            return json_body({}, 204)
        return redirect(f"{g.slug}/boards/{board['id']}")
    if action in {"PUT", "PATCH"}:
        payload = form_body("column")
        updated = store.update_column(
            conn(), g.user, column,
            name=payload.get("name"),
            color=payload.get("color"),
            position=payload.get("position"),
        )
        return json_body(column_json(updated, urls))
    if wants_json():
        return json_body(column_json(column, urls))
    return redirect(f"{g.slug}/boards/{board['id']}")


@bp.route("/<int:slug>/boards/<board_id>/columns/<column_id>/cards")
def column_cards(slug, board_id, column_id):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    board = require_board(board_id)
    column = store.column_by_id(conn(), column_id)
    if not column or column["board_id"] != board["id"]:
        raise not_found("Column not found")
    urls = urls_for(g.account)
    cards = store.column_cards(conn(), column["id"])
    _page, size, offset = page_window()
    window = cards[offset:offset + size + 1]
    rows, headers = paginate(window)
    return json_body([card_json(conn(), card, urls) for card in rows], extra_headers=headers)


@bp.route("/<int:slug>/columns/<column_id>/move", methods=["POST"])
def column_move(slug, column_id):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    column = store.column_by_id(conn(), column_id)
    if not column or column["account_id"] != g.account["id"]:
        raise not_found()
    direction = -1 if request.form.get("direction") == "left" else 1
    store.move_column(conn(), g.user, column, direction)
    return redirect(f"{g.slug}/boards/{column['board_id']}")


@bp.route("/<int:slug>/boards/<board_id>/publication", methods=["POST", "DELETE"])
def board_publication(slug, board_id):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    board = require_board(board_id)
    urls = urls_for(g.account)
    if verb() == "DELETE" or request.method == "DELETE":
        store.unpublish_board(conn(), g.user, board)
        if wants_json():
            return json_body({}, 204)
        flash("Board is private again.")
        return redirect(f"{g.slug}/boards/{board_id}/edit")
    store.publish_board(conn(), g.user, board)
    if wants_json():
        return json_body(board_json(conn(), store.board_by_id(conn(), board_id), urls, detailed=True), 201)
    flash("Board published. Anyone with the link can read it.")
    return redirect(f"{g.slug}/boards/{board_id}/edit")


@bp.route("/<int:slug>/boards/<board_id>/entropy", methods=["PUT", "POST"])
def board_entropy(slug, board_id):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    board = require_board(board_id)
    if not store.can_admin_board(g.user, board):
        raise forbidden()
    payload = form_body("entropy")
    store.set_entropy(conn(), g.account["id"], "Board", board["id"], int(payload.get("auto_postpone_period_in_days") or 30))
    urls = urls_for(g.account)
    if wants_json():
        return json_body(board_json(conn(), board, urls))
    flash("Auto-postpone updated.")
    return redirect(f"{g.slug}/boards/{board_id}/edit")


# --- cards -----------------------------------------------------------------

def _card_filters():
    return {
        "board_ids": multi("board_ids"),
        "tag_ids": multi("tag_ids"),
        "assignee_ids": multi("assignee_ids"),
        "creator_ids": multi("creator_ids"),
        "closer_ids": multi("closer_ids"),
        "card_ids": multi("card_ids"),
        "column_ids": multi("column_ids"),
        "indexed_by": request.args.get("indexed_by") or "all",
        "sorted_by": request.args.get("sorted_by") or "latest",
        "assignment_status": request.args.get("assignment_status"),
        "creation": request.args.get("creation"),
        "closure": request.args.get("closure"),
        "terms": multi("terms") or ([request.args.get("q")] if request.args.get("q") else []),
    }


@bp.route("/<int:slug>/cards", methods=["GET"])
def cards(slug):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    _page, size, offset = page_window()
    found = store.query_cards(conn(), g.user, _card_filters(), size + 1, offset)
    rows, headers = paginate(found)
    urls = urls_for(g.account)
    if wants_json():
        return json_body([card_json(conn(), card, urls) for card in rows], extra_headers=headers)
    return render_template(
        "cards.html",
        cards=[card_view(conn(), card, g.user["id"]) for card in rows],
        filters=_card_filters(),
        tags=store.tags_in_account(conn(), g.account["id"]),
        members=store.users_in_account(conn(), g.account["id"]),
    )


@bp.route("/<int:slug>/boards/<board_id>/cards", methods=["POST"])
def card_create(slug, board_id):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    board = require_board(board_id)
    payload = form_body("card")
    status = payload.get("status") or "published"
    tags = payload.get("tag_ids") or []
    # The documented API takes tag ids. The board composer takes a title and optional tags as text.
    tag_titles = payload.get("tag_titles") or []
    if isinstance(tag_titles, str):
        tag_titles = [part.strip() for part in tag_titles.split(",") if part.strip()]
    card = store.create_card(
        conn(),
        g.user,
        board,
        title=payload.get("title"),
        description=payload.get("description"),
        status=status,
        column_id=payload.get("column_id") or None,
        created_at=payload.get("created_at"),
        last_active_at=payload.get("last_active_at"),
        tag_titles=tag_titles,
    )
    if tags:
        known = {tag["id"]: tag["title"] for tag in store.tags_in_account(conn(), g.account["id"])}
        for tag_id in tags:
            if tag_id in known:
                store.toggle_tag(conn(), g.user, card, known[tag_id], force_on=True)
    upload = payload.get("image")
    if upload and getattr(upload, "read", None):
        data = upload.read()
        if data:
            store.save_blob(
                conn(), Path(current_app.config["STORAGE"]), g.account["id"], "Card", card["id"],
                "image", upload.filename, upload.mimetype or "application/octet-stream", data,
            )
    g.deliver = True
    urls = urls_for(g.account)
    if wants_json():
        return json_body(card_json(conn(), store.card_by_id(conn(), card["id"]), urls, detailed=True), 201, urls("cards", card["number"]) + ".json")
    return redirect(f"{g.slug}/boards/{board['id']}")


@bp.route("/<int:slug>/cards/<int:number>", methods=["GET", "PUT", "POST", "DELETE"])
def card_detail(slug, number):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    card, board = require_card(number)
    urls = urls_for(g.account)
    action = verb()
    if action == "DELETE":
        store.delete_card(conn(), g.user, card)
        if wants_json():
            return json_body({}, 204)
        flash("Card deleted.")
        return redirect(f"{g.slug}/boards/{board['id']}")
    if action in {"PUT", "PATCH"}:
        payload = form_body("card")
        description = None
        if "description" in payload:
            from .text import plain_text
            existing = store.rich_text(conn(), "Card", card["id"], "description")
            current = plain_text(existing["body"] if existing else "")
            submitted = (payload.get("description") or "").strip()
            if submitted != current:
                description = payload.get("description")
        updated = store.update_card(
            conn(), g.user, card,
            title=payload.get("title") if "title" in payload else None,
            description=description,
            status=payload.get("status"),
            last_active_at=payload.get("last_active_at"),
            tag_titles=payload.get("tag_titles") if "tag_titles" in payload else None,
        )
        upload = payload.get("image")
        if upload and getattr(upload, "read", None):
            data = upload.read()
            if data:
                store.save_blob(
                    conn(), Path(current_app.config["STORAGE"]), g.account["id"], "Card", card["id"],
                    "image", upload.filename, upload.mimetype or "application/octet-stream", data,
                )
        g.deliver = True
        if wants_json():
            return json_body(card_json(conn(), store.card_by_id(conn(), updated["id"]), urls, detailed=True))
        flash("Card saved.")
        return redirect(f"{g.slug}/cards/{number}")
    view = card_view(conn(), card, g.user["id"])
    comments = []
    for comment in store.comments_of(conn(), card["id"]):
        body = store.rich_text(conn(), "Comment", comment["id"], "body")
        comments.append({
            "comment": comment,
            "html": (body["body"] if body else "") or "",
            "author": store.user_by_id(conn(), comment["creator_id"]),
            "reactions": store.reactions_of(conn(), "Comment", comment["id"]),
        })
    if wants_json():
        return json_body(card_json(conn(), card, urls, detailed=True))
    return render_template(
        "card.html",
        board=board,
        view=view,
        comments=comments,
        reactions=store.reactions_of(conn(), "Card", card["id"]),
        members=store.users_in_account(conn(), g.account["id"]),
        columns=store.columns_for(conn(), board["id"]),
        all_tags=store.tags_in_account(conn(), g.account["id"]),
        boards=store.boards_for(conn(), g.user),
        days=store.postpone_days(conn(), g.account["id"], board["id"]),
    )


def _card_action(slug, number, work):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    card, board = require_card(number)
    result = work(card, board)
    g.deliver = True
    if wants_json():
        if result is not None and not isinstance(result, tuple):
            return result
        return json_body({}, 204)
    return redirect(request.referrer or f"{g.slug}/cards/{number}")


@bp.route("/<int:slug>/cards/<int:number>/closure", methods=["POST", "DELETE"])
def card_closure(slug, number):
    def work(card, _board):
        if verb() == "DELETE" or request.method == "DELETE":
            store.reopen_card(conn(), g.user, card)
        else:
            store.close_card(conn(), g.user, card)
    return _card_action(slug, number, work)


@bp.route("/<int:slug>/cards/<int:number>/not_now", methods=["POST"])
def card_not_now(slug, number):
    return _card_action(slug, number, lambda card, _board: store.postpone_card(conn(), g.user, card))


@bp.route("/<int:slug>/cards/<int:number>/triage", methods=["POST", "DELETE"])
def card_triage(slug, number):
    def work(card, _board):
        if verb() == "DELETE" or request.method == "DELETE":
            store.untriage_card(conn(), g.user, card)
            return None
        payload = form_body("triage")
        column_id = payload.get("column_id") or request.form.get("column_id")
        if not column_id:
            raise invalid({"column_id": ["can't be blank"]})
        store.triage_card(conn(), g.user, card, column_id)
    return _card_action(slug, number, work)


@bp.route("/<int:slug>/cards/<int:number>/board", methods=["PUT", "POST"])
def card_board(slug, number):
    def work(card, _board):
        payload = form_body("card")
        board_id = payload.get("board_id") or request.form.get("board_id")
        if not board_id:
            raise invalid({"board_id": ["can't be blank"]})
        moved = store.move_card_board(conn(), g.user, card, board_id)
        if wants_json():
            return json_body(card_json(conn(), moved, urls_for(g.account), detailed=True))
        return None
    return _card_action(slug, number, work)


@bp.route("/<int:slug>/cards/<int:number>/goldness", methods=["POST", "DELETE"])
def card_gold(slug, number):
    def work(card, _board):
        store.toggle_gold(conn(), g.user, card, not (verb() == "DELETE" or request.method == "DELETE"))
    return _card_action(slug, number, work)


@bp.route("/<int:slug>/cards/<int:number>/pin", methods=["POST", "DELETE"])
def card_pin(slug, number):
    def work(card, _board):
        store.toggle_pin(conn(), g.user, card, not (verb() == "DELETE" or request.method == "DELETE"))
    return _card_action(slug, number, work)


@bp.route("/<int:slug>/cards/<int:number>/watch", methods=["POST", "DELETE"])
def card_watch(slug, number):
    def work(card, _board):
        store.set_watch(conn(), g.user, card, not (verb() == "DELETE" or request.method == "DELETE"))
    return _card_action(slug, number, work)


@bp.route("/<int:slug>/cards/<int:number>/taggings", methods=["POST"])
def card_tag(slug, number):
    def work(card, _board):
        payload = form_body("tagging")
        title = payload.get("tag_title") or request.form.get("tag_title") or ""
        store.toggle_tag(conn(), g.user, card, title)
    return _card_action(slug, number, work)


@bp.route("/<int:slug>/cards/<int:number>/self_assignment", methods=["POST"])
def card_self_assign(slug, number):
    def work(card, _board):
        store.toggle_assignment(conn(), g.user, card, g.user["id"])
    return _card_action(slug, number, work)


@bp.route("/<int:slug>/cards/<int:number>/assignments", methods=["POST"])
def card_assign(slug, number):
    def work(card, _board):
        payload = form_body("assignment")
        assignee = payload.get("assignee_id") or request.form.get("assignee_id")
        if not assignee:
            raise invalid({"assignee_id": ["can't be blank"]})
        store.toggle_assignment(conn(), g.user, card, assignee)
    return _card_action(slug, number, work)


@bp.route("/<int:slug>/cards/<int:number>/image", methods=["DELETE", "POST"])
def card_image(slug, number):
    def work(card, _board):
        if verb() == "DELETE" or request.method == "DELETE":
            store._purge_attachments(conn(), "Card", card["id"], name="image", storage=Path(current_app.config["STORAGE"]))
    return _card_action(slug, number, work)


@bp.route("/<int:slug>/cards/<int:number>/steps", methods=["POST"])
def steps_create(slug, number):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    card, _board = require_card(number)
    payload = form_body("step")
    step = store.create_step(conn(), g.user, card, payload.get("content", ""), as_bool(payload.get("completed"), False))
    urls = urls_for(g.account)
    if wants_json():
        return json_body(step_json(step), 201, urls("cards", number, "steps", step["id"]) + ".json")
    return redirect(f"{g.slug}/cards/{number}")


@bp.route("/<int:slug>/cards/<int:number>/steps/<step_id>", methods=["GET", "PUT", "POST", "DELETE"])
def step_detail(slug, number, step_id):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    card, _board = require_card(number)
    step = store.step_by_id(conn(), step_id)
    if not step or step["card_id"] != card["id"]:
        raise not_found("Step not found")
    action = verb()
    if action == "DELETE":
        store.delete_step(conn(), step)
        if wants_json():
            return json_body({}, 204)
        return redirect(f"{g.slug}/cards/{number}")
    if action in {"PUT", "PATCH"}:
        payload = form_body("step")
        updated = store.update_step(
            conn(), g.user, step,
            content=payload.get("content") if "content" in payload else None,
            completed=as_bool(payload["completed"]) if "completed" in payload else None,
        )
        if wants_json():
            return json_body(step_json(updated))
        return redirect(f"{g.slug}/cards/{number}")
    return json_body(step_json(step))


@bp.route("/<int:slug>/cards/<int:number>/comments", methods=["GET", "POST"])
def comments(slug, number):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    card, _board = require_card(number)
    urls = urls_for(g.account)
    if request.method == "POST":
        payload = form_body("comment")
        comment = store.create_comment(conn(), g.user, card, payload.get("body", ""), payload.get("created_at"))
        g.deliver = True
        if wants_json():
            return json_body(comment_json(conn(), comment, urls, card), 201, urls("cards", number, "comments", comment["id"]) + ".json")
        return redirect(f"{g.slug}/cards/{number}#comment-{comment['id']}")
    rows = store.comments_of(conn(), card["id"])
    _page, size, offset = page_window()
    window, headers = paginate(rows[offset:offset + size + 1])
    return json_body([comment_json(conn(), comment, urls, card) for comment in window], extra_headers=headers)


@bp.route("/<int:slug>/cards/<int:number>/comments/<comment_id>", methods=["GET", "PUT", "POST", "DELETE"])
def comment_detail(slug, number, comment_id):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    card, _board = require_card(number)
    comment = store.comment_by_id(conn(), comment_id)
    if not comment or comment["card_id"] != card["id"]:
        raise not_found("Comment not found")
    urls = urls_for(g.account)
    action = verb()
    if action == "DELETE":
        store.delete_comment(conn(), g.user, comment)
        if wants_json():
            return json_body({}, 204)
        return redirect(f"{g.slug}/cards/{number}")
    if action in {"PUT", "PATCH"}:
        payload = form_body("comment")
        updated = store.update_comment(conn(), g.user, comment, payload.get("body", ""))
        if wants_json():
            return json_body(comment_json(conn(), updated, urls, card))
        return redirect(f"{g.slug}/cards/{number}#comment-{comment_id}")
    return json_body(comment_json(conn(), comment, urls, card))


@bp.route("/<int:slug>/cards/<int:number>/reactions", methods=["GET", "POST"])
def card_reactions(slug, number):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    card, _board = require_card(number)
    urls = urls_for(g.account)
    if request.method == "POST":
        payload = form_body("reaction")
        reaction = store.add_reaction(conn(), g.user, card["account_id"], "Card", card["id"], payload.get("content", ""))
        if wants_json():
            return json_body(reaction_json(conn(), reaction, urls, number), 201)
        return redirect(f"{g.slug}/cards/{number}")
    rows = store.reactions_of(conn(), "Card", card["id"])
    return json_body([reaction_json(conn(), row, urls, number) for row in rows])


@bp.route("/<int:slug>/cards/<int:number>/reactions/<reaction_id>", methods=["DELETE", "POST"])
def card_reaction_delete(slug, number, reaction_id):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    require_card(number)
    if verb() != "DELETE" and request.method != "DELETE":
        abort(404)
    store.delete_reaction(conn(), g.user, reaction_id)
    if wants_json():
        return json_body({}, 204)
    return redirect(f"{g.slug}/cards/{number}")


@bp.route("/<int:slug>/cards/<int:number>/comments/<comment_id>/reactions", methods=["GET", "POST"])
def comment_reactions(slug, number, comment_id):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    card, _board = require_card(number)
    comment = store.comment_by_id(conn(), comment_id)
    if not comment or comment["card_id"] != card["id"]:
        raise not_found()
    urls = urls_for(g.account)
    if request.method == "POST":
        payload = form_body("reaction")
        reaction = store.add_reaction(conn(), g.user, card["account_id"], "Comment", comment["id"], payload.get("content", ""))
        if wants_json():
            return json_body(reaction_json(conn(), reaction, urls, number, comment_id), 201)
        return redirect(f"{g.slug}/cards/{number}#comment-{comment_id}")
    rows = store.reactions_of(conn(), "Comment", comment["id"])
    return json_body([reaction_json(conn(), row, urls, number, comment_id) for row in rows])


@bp.route("/<int:slug>/cards/<int:number>/comments/<comment_id>/reactions/<reaction_id>", methods=["DELETE", "POST"])
def comment_reaction_delete(slug, number, comment_id, reaction_id):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    require_card(number)
    if verb() != "DELETE" and request.method != "DELETE":
        abort(404)
    store.delete_reaction(conn(), g.user, reaction_id)
    if wants_json():
        return json_body({}, 204)
    return redirect(f"{g.slug}/cards/{number}#comment-{comment_id}")


# --- people, tags, notifications, account ---------------------------------

@bp.route("/<int:slug>/tags")
def tags(slug):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    urls = urls_for(g.account)
    rows = store.tags_in_account(conn(), g.account["id"])
    if wants_json():
        return json_body([tag_json(tag, urls) for tag in rows])
    return render_template("tags.html", tags=rows)


@bp.route("/<int:slug>/users", methods=["GET"])
def users(slug):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    urls = urls_for(g.account)
    rows = [user for user in store.users_in_account(conn(), g.account["id"]) if user["active"]]
    if wants_json():
        return json_body([user_json(user, urls) for user in rows])
    code = store.join_code_for(conn(), g.account["id"])
    return render_template("users.html", users=store.users_in_account(conn(), g.account["id"]), join_code=code)


@bp.route("/<int:slug>/users/<user_id>", methods=["GET", "PUT", "POST", "DELETE"])
def user_detail(slug, user_id):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    user = store.user_by_id(conn(), user_id)
    if not user or user["account_id"] != g.account["id"] or user["role"] == "system":
        raise not_found("User not found")
    urls = urls_for(g.account)
    action = verb()
    if action == "DELETE":
        store.deactivate_user(conn(), g.user, user_id)
        if wants_json():
            return json_body({}, 204)
        flash(f"{user['name']} is deactivated.")
        return redirect(f"{g.slug}/users")
    if action in {"PUT", "PATCH"}:
        if not (g.user["role"] in {"owner", "admin"} or g.user["id"] == user["id"]):
            if g.user["id"] != user["id"]:
                raise forbidden()
        payload = form_body("user")
        if "name" in payload:
            if g.user["id"] != user["id"] and g.user["role"] not in {"owner", "admin"}:
                raise forbidden()
            store.update_user_name(conn(), user["id"], payload.get("name") or "")
        if payload.get("role"):
            store.set_role(conn(), g.user, user["id"], payload["role"])
        upload = payload.get("avatar")
        if upload and getattr(upload, "read", None):
            data = upload.read()
            if data:
                store.save_blob(
                    conn(), Path(current_app.config["STORAGE"]), g.account["id"], "User", user["id"],
                    "avatar", upload.filename, upload.mimetype or "application/octet-stream", data,
                )
        if wants_json():
            return json_body(user_json(store.user_by_id(conn(), user["id"]), urls))
        flash("Profile saved.")
        return redirect(f"{g.slug}/users")
    if wants_json():
        return json_body(user_json(user, urls))
    return render_template("user.html", person=user)


@bp.route("/<int:slug>/users/<user_id>/avatar", methods=["GET", "DELETE", "POST"])
def user_avatar(slug, user_id):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    user = store.user_by_id(conn(), user_id)
    if not user or user["account_id"] != g.account["id"]:
        raise not_found()
    if verb() == "DELETE" or request.method == "DELETE":
        store._purge_attachments(conn(), "User", user["id"], name="avatar", storage=Path(current_app.config["STORAGE"]))
        if wants_json():
            return json_body({}, 204)
        return redirect(f"{g.slug}/users/{user_id}")
    return _send_avatar(user)


def _send_avatar(user):
    blob = store.attachment_blob(conn(), "User", user["id"], "avatar")
    if blob:
        path = store.blob_path(Path(current_app.config["STORAGE"]), blob["key"])
        if path:
            return send_file(path, mimetype=blob["content_type"] or "image/png", max_age=3600)
    initial = (user["name"] or "?").strip()[:1].upper()
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='80' height='80'>"
        f"<rect width='80' height='80' rx='40' fill='#efe6d6'/>"
        f"<text x='40' y='48' text-anchor='middle' font-family='sans-serif' font-size='32' fill='#3d3428'>{initial}</text>"
        "</svg>"
    )
    response = make_response(svg)
    response.mimetype = "image/svg+xml"
    return response


@bp.route("/<int:slug>/users/<user_id>/email_addresses", methods=["POST"])
def email_change(slug, user_id):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    user = store.user_by_id(conn(), user_id)
    if not user or user["id"] != g.user["id"]:
        raise not_found("User not found")
    payload = form_body("email")
    new_email = store.change_email(conn(), user, payload.get("email_address") or request.form.get("email_address") or "")
    from itsdangerous import URLSafeTimedSerializer
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="change-email")
    token = serializer.dumps({"user_id": user["id"], "email": new_email, "old": user.get("email_address")})
    if wants_json():
        response = json_body({}, 201)
        response.headers["X-Fizzy-Confirmation-Token"] = token
        return response
    return render_template("email_token.html", token=token, email=new_email, user_id=user["id"])


@bp.route("/<int:slug>/users/<user_id>/email_addresses/<token>/confirmation", methods=["POST"])
def email_confirm(slug, user_id, token):
    from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
    account = store.account_by_external(conn(), slug)
    if not account:
        raise not_found()
    g.account = account
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="change-email")
    try:
        data = serializer.loads(token, max_age=30 * 60)
    except (BadSignature, SignatureExpired):
        raise invalid({"error": ["Token is invalid or has expired"]})
    if data.get("user_id") != user_id:
        raise invalid({"error": ["Token is invalid or has expired"]})
    store.apply_email_change(conn(), user_id, data["email"])
    if wants_json():
        return json_body({}, 204)
    flash("Email address updated. Log in with the new address next time.")
    return redirect(url_for("fizzy.login"))


@bp.route("/<int:slug>/notifications")
def notifications(slug):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    _page, size, offset = page_window()
    rows = store.notifications_for(conn(), g.user, size + 1, offset)
    window, headers = paginate(rows)
    urls = urls_for(g.account)
    if wants_json():
        return json_body([notification_json(conn(), row, urls) for row in window], extra_headers=headers)
    return render_template("notifications.html", notes=[notification_json(conn(), row, urls) for row in window])


@bp.route("/<int:slug>/notifications/<notification_id>/reading", methods=["POST", "DELETE"])
def notification_reading(slug, notification_id):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    note = store.notification_by_id(conn(), notification_id)
    if not note or note["user_id"] != g.user["id"]:
        raise not_found()
    store.mark_notification(conn(), note, read=not (verb() == "DELETE" or request.method == "DELETE"))
    if wants_json():
        return json_body({}, 204)
    return redirect(f"{g.slug}/notifications")


@bp.route("/<int:slug>/notifications/bulk_reading", methods=["POST"])
def notification_bulk(slug):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    store.mark_all_read(conn(), g.user["id"])
    if wants_json():
        return json_body({}, 204)
    return redirect(f"{g.slug}/notifications")


@bp.route("/<int:slug>/notifications/settings", methods=["GET", "PUT", "POST"])
def notification_settings(slug):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    if request.method != "GET":
        payload = form_body("user_settings")
        store.set_bundle_frequency(conn(), g.user["id"], payload.get("bundle_email_frequency") or "never")
        if wants_json():
            return json_body({}, 204)
        flash("Notification preference saved. Mail is not sent from this local app.")
        return redirect(f"{g.slug}/notifications")
    return json_body(settings_json(conn(), g.user["id"]))


@bp.route("/<int:slug>/my/timezone", methods=["PATCH", "PUT", "POST"])
def timezone(slug):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    payload = form_body("timezone")
    name = payload.get("timezone_name") or request.form.get("timezone_name")
    if not name:
        raise invalid({"timezone_name": ["can't be blank"]})
    store.set_timezone(conn(), g.user["id"], name)
    if wants_json():
        return json_body({}, 204)
    return redirect(f"{g.slug}/")


@bp.route("/<int:slug>/my/pins")
def my_pins(slug):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    cards = store.pins_for_user(conn(), g.user)
    urls = urls_for(g.account)
    if wants_json():
        return json_body([card_json(conn(), card, urls) for card in cards])
    return render_template("pins.html", cards=[card_view(conn(), card, g.user["id"]) for card in cards])


@bp.route("/<int:slug>/account/settings")
def account_settings(slug):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    if wants_json():
        return json_body(account_json(conn(), g.account))
    return render_template(
        "settings.html",
        days=store.postpone_days(conn(), g.account["id"]),
        join_code=store.join_code_for(conn(), g.account["id"]),
        settings=settings_json(conn(), g.user["id"]),
    )


@bp.route("/<int:slug>/account/join_code", methods=["GET", "PUT", "POST", "DELETE"])
def join_code(slug):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    if g.user["role"] not in {"owner", "admin"} and request.method != "GET":
        raise forbidden()
    if verb() == "DELETE" or request.method == "DELETE":
        store.reset_join_code(conn(), g.account["id"])
        if wants_json():
            return json_body({}, 204)
        flash("Join code reset.")
        return redirect(f"{g.slug}/account/settings")
    if request.method != "GET":
        payload = form_body("account_join_code")
        store.update_join_limit(conn(), g.account["id"], int(payload.get("usage_limit") or 10))
        if wants_json():
            return json_body({}, 204)
        flash("Join code updated.")
        return redirect(f"{g.slug}/account/settings")
    row = store.join_code_for(conn(), g.account["id"])
    return json_body({
        "code": row["code"],
        "usage_count": row["usage_count"],
        "usage_limit": row["usage_limit"],
        "url": origin() + g.slug + "/join/" + row["code"],
        "active": int(row["usage_count"]) < int(row["usage_limit"]),
    })


@bp.route("/<int:slug>/account/entropy", methods=["PUT", "POST"])
def account_entropy(slug):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    if g.user["role"] not in {"owner", "admin"}:
        raise forbidden()
    payload = form_body("entropy")
    store.set_entropy(conn(), g.account["id"], "Account", g.account["id"], int(payload.get("auto_postpone_period_in_days") or 30))
    if wants_json():
        return json_body(account_json(conn(), g.account))
    flash("Account auto-postpone updated.")
    return redirect(f"{g.slug}/account/settings")


@bp.route("/<int:slug>/account/rename", methods=["POST"])
def account_rename(slug):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    if g.user["role"] not in {"owner", "admin"}:
        raise forbidden()
    name = (request.form.get("name") or "").strip()
    if not name:
        raise invalid({"name": ["can't be blank"]})
    update(conn(), "accounts", g.account["id"], name=name[:255])
    flash("Account renamed.")
    return redirect(f"{g.slug}/account/settings")


@bp.route("/<int:slug>/join/<code>", methods=["GET", "POST"])
@bp.route("/join/<code>", methods=["GET", "POST"])
def join(code, slug=None):
    bounced = require_identity()
    if bounced:
        session["next"] = request.url
        return bounced
    if request.method == "GET":
        return render_template("join.html", code=code)
    account, _user = store.join_account(conn(), code, g.identity["id"], g.identity["email_address"].split("@")[0])
    flash(f"You joined {account['name']}.")
    return redirect(f"/{account['external_account_id']}/")


@bp.route("/<int:slug>/account/new", methods=["POST"])
def another_account(slug):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    name = (request.form.get("name") or "").strip() or "Another Fizzy"
    account, _user = store.create_account(conn(), name=name, owner_name=g.user["name"], identity_id=g.identity["id"])
    return redirect(f"/{account['external_account_id']}/boards/new")


# --- webhooks and exports --------------------------------------------------

@bp.route("/<int:slug>/boards/<board_id>/webhooks", methods=["GET", "POST"])
def webhooks(slug, board_id):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    board = require_board(board_id)
    urls = urls_for(g.account)
    if request.method == "POST":
        payload = form_body("webhook")
        actions = payload.get("subscribed_actions") or request.form.getlist("subscribed_actions")
        hook = store.create_webhook(conn(), g.user, board, payload.get("name", ""), payload.get("url", ""), actions)
        if wants_json():
            return json_body(webhook_json(conn(), hook, urls), 201, urls("boards", board_id, "webhooks", hook["id"]) + ".json")
        flash("Webhook created.")
        return redirect(f"{g.slug}/boards/{board_id}/edit")
    rows = store.webhooks_for(conn(), board["id"])
    _page, size, offset = page_window()
    window, headers = paginate(rows[offset:offset + size + 1])
    return json_body([webhook_json(conn(), row, urls) for row in window], extra_headers=headers)


@bp.route("/<int:slug>/boards/<board_id>/webhooks/<webhook_id>", methods=["GET", "PATCH", "PUT", "POST", "DELETE"])
def webhook_detail(slug, board_id, webhook_id):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    board = require_board(board_id)
    hook = store.webhook_by_id(conn(), webhook_id)
    if not hook or hook["board_id"] != board["id"]:
        raise not_found()
    urls = urls_for(g.account)
    action = verb()
    if action == "DELETE":
        store.delete_webhook(conn(), g.user, hook)
        if wants_json():
            return json_body({}, 204)
        flash("Webhook deleted.")
        return redirect(f"{g.slug}/boards/{board_id}/edit")
    if action in {"PUT", "PATCH"}:
        payload = form_body("webhook")
        actions = payload.get("subscribed_actions")
        if actions is None and request.form.getlist("subscribed_actions"):
            actions = request.form.getlist("subscribed_actions")
        updated = store.update_webhook(
            conn(), g.user, hook,
            name=payload.get("name") if "name" in payload else None,
            actions=actions,
            active=as_bool(payload["active"]) if "active" in payload else None,
        )
        if wants_json():
            return json_body(webhook_json(conn(), updated, urls))
        return redirect(f"{g.slug}/boards/{board_id}/edit")
    return json_body(webhook_json(conn(), hook, urls))


@bp.route("/<int:slug>/boards/<board_id>/webhooks/<webhook_id>/activation", methods=["POST"])
def webhook_activation(slug, board_id, webhook_id):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    board = require_board(board_id)
    hook = store.webhook_by_id(conn(), webhook_id)
    if not hook or hook["board_id"] != board["id"]:
        raise not_found()
    updated = store.update_webhook(conn(), g.user, hook, active=True)
    return json_body(webhook_json(conn(), updated, urls_for(g.account)), 201)


@bp.route("/<int:slug>/boards/<board_id>/webhooks/<webhook_id>/deliveries")
def webhook_deliveries(slug, board_id, webhook_id):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    board = require_board(board_id)
    hook = store.webhook_by_id(conn(), webhook_id)
    if not hook or hook["board_id"] != board["id"]:
        raise not_found()
    _page, size, offset = page_window()
    rows = store.deliveries_for(conn(), hook["id"], size + 1, offset)
    window, headers = paginate(rows)
    urls = urls_for(g.account)
    payload = []
    for delivery in window:
        event = q1(conn(), "SELECT * FROM events WHERE id = ?", (store._id(conn(), "events", "id", delivery["event_id"]),))
        request_body = delivery.get("request") or {}
        if isinstance(request_body, dict) and "headers" in request_body:
            request_body = {"headers": {k: v for k, v in request_body["headers"].items() if k != "X-Webhook-Signature"}}
        response_body = delivery.get("response") or {}
        summary = None
        if isinstance(response_body, dict) and response_body:
            summary = {key: response_body.get(key) for key in ("code", "error") if key in response_body}
        payload.append({
            "id": delivery["id"],
            "state": delivery["state"],
            "created_at": iso(delivery["created_at"]),
            "updated_at": iso(delivery["updated_at"]),
            "request": request_body or None,
            "response": summary,
            "event": {
                "id": event["id"],
                "action": event["action"],
                "created_at": iso(event["created_at"]),
                "creator": {"id": event["creator_id"], "name": (store.user_by_id(conn(), event["creator_id"]) or {}).get("name")},
                "eventable": {"type": event["eventable_type"], "id": event["eventable_id"], "url": urls("boards", board_id)},
            } if event else None,
        })
    return json_body(payload, extra_headers=headers)


@bp.route("/<int:slug>/account/exports", methods=["POST"])
@bp.route("/<int:slug>/users/<user_id>/data_exports", methods=["POST"])
def export_create(slug, user_id=None):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    kind = "User::DataExport" if user_id else "Account::Export"
    if user_id and user_id != g.user["id"]:
        raise forbidden()
    if kind == "Account::Export" and g.user["role"] not in {"owner", "admin"}:
        raise forbidden()
    created = store.finish_export(conn(), Path(current_app.config["STORAGE"]), g.user, kind)
    if wants_json():
        return json_body(_export_json(created), 201)
    return render_template("export.html", export=_export_json(created))


@bp.route("/<int:slug>/account/exports/<export_id>")
@bp.route("/<int:slug>/users/<user_id>/data_exports/<export_id>")
def export_show(slug, export_id, user_id=None):
    bounced = enter_account(slug)
    if bounced:
        return bounced
    row = store.export_by_id(conn(), export_id)
    if not row or row["user_id"] != g.user["id"] or row["account_id"] != g.account["id"]:
        raise not_found()
    return json_body(_export_json(row))


def _export_json(row):
    payload = {"id": row["id"], "status": row["status"], "created_at": iso(row["created_at"])}
    completed = parse_dt(row.get("completed_at"))
    fresh = completed and (utcnow() - completed).total_seconds() < 86400
    blob = store.attachment_blob(conn(), row["type"], row["id"], "file") if row["status"] == "completed" else None
    if fresh and blob:
        payload["download_url"] = origin() + f"/{g.account['external_account_id']}/storage/{blob['id']}"
    return payload


@bp.route("/<int:slug>/storage/<blob_id>")
def storage(slug, blob_id):
    account = store.account_by_external(conn(), slug)
    if not account:
        raise not_found()
    blob = q1(conn(), "SELECT * FROM active_storage_blobs WHERE id = ?", (store._id(conn(), "active_storage_blobs", "id", blob_id),))
    if not blob or blob["account_id"] != account["id"]:
        raise not_found()
    load_identity()
    member = store.user_for_identity(conn(), account["id"], g.identity["id"]) if g.identity else None
    if not member and not _blob_on_published_board(blob["id"]):
        bounced = enter_account(slug)
        if bounced:
            return bounced
    path = store.blob_path(Path(current_app.config["STORAGE"]), blob["key"])
    if not path:
        raise not_found("The file is not on this machine. Set FIZZY_STORAGE to the Rails storage directory.")
    return send_file(path, mimetype=blob["content_type"] or "application/octet-stream", download_name=blob["filename"], max_age=3600)


def _blob_on_published_board(blob_id: str) -> bool:
    attachment = q1(
        conn(),
        "SELECT * FROM active_storage_attachments WHERE blob_id = ?",
        (store._id(conn(), "active_storage_attachments", "blob_id", blob_id),),
    )
    if not attachment or attachment["record_type"] != "Card" or attachment["name"] != "image":
        return False
    card = store.card_by_id(conn(), attachment["record_id"])
    if not card or card["status"] != "published":
        return False
    return store.publication(conn(), card["board_id"]) is not None


@bp.route("/<int:slug>/public/boards/<key>")
@bp.route("/public/boards/<key>")
def public_board(key, slug=None):
    board, published = store.board_by_publication_key(conn(), key)
    if not board or not published:
        raise not_found("This board is not published")
    account = store.account_by_id(conn(), board["account_id"])
    load_identity()
    g.account = account
    g.slug = f"/{account['external_account_id']}"
    if g.identity:
        g.user = store.user_for_identity(conn(), account["id"], g.identity["id"])
    else:
        g.user = None
    columns = store.columns_for(conn(), board["id"])
    lanes = {
        "maybe": [card_view(conn(), card) for card in store.lane_cards(conn(), board["id"], "maybe")],
        "not_now": [card_view(conn(), card) for card in store.lane_cards(conn(), board["id"], "not_now")],
        "closed": [card_view(conn(), card) for card in store.lane_cards(conn(), board["id"], "closed")],
    }
    column_views = [{
        "column": column,
        "cards": [card_view(conn(), card) for card in store.column_cards(conn(), column["id"])],
    } for column in columns]
    description = store.rich_text(conn(), "Board", board["id"], "public_description")
    return render_template(
        "public_board.html",
        board=board,
        columns=column_views,
        lanes=lanes,
        description=(description["body"] if description else ""),
        account=account,
        public_key=key,
    )


@bp.route("/<int:slug>/public/boards/<key>/cards/<int:number>")
def public_card(slug, key, number):
    board, published = store.board_by_publication_key(conn(), key)
    if not board:
        raise not_found()
    g.account = store.account_by_id(conn(), board["account_id"])
    g.slug = f"/{g.account['external_account_id']}"
    card = store.card_by_number(conn(), board["account_id"], number)
    if not card or card["board_id"] != board["id"] or card["status"] != "published":
        raise not_found()
    view = card_view(conn(), card)
    comments = []
    for comment in store.comments_of(conn(), card["id"]):
        body = store.rich_text(conn(), "Comment", comment["id"], "body")
        comments.append({
            "comment": comment,
            "html": (body["body"] if body else "") or "",
            "author": store.user_by_id(conn(), comment["creator_id"]),
            "reactions": [],
        })
    return render_template("public_card.html", board=board, view=view, comments=comments, key=key)


@bp.after_request
def deliver_webhooks(response):
    if not g.get("deliver") or g.get("rollback"):
        return response
    try:
        urls = urls_for(g.account) if g.get("account") else None

        def build(event, hook):
            if urls is None:
                body = json.dumps({"id": event["id"], "action": event["action"]})
                return body, "application/json"
            if "hooks.slack.com" in (hook["url"] or ""):
                card = None
                if event["eventable_type"] == "Card":
                    card = store.card_by_id(conn(), event["eventable_id"])
                text = store.describe_event(conn(), event, card)
                return json.dumps({"text": text}), "application/json"
            payload = event_json(conn(), event, urls)
            return json.dumps(payload, default=str), "application/json"

        store.deliver_pending(conn(), build)
    except Exception:
        current_app.logger.exception("webhook delivery failed")
    return response
