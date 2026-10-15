"""JSON shapes from Fizzy's jbuilder templates, plus board view models."""

from __future__ import annotations

from datetime import timedelta

from .codec import iso, parse_dt, utcnow
from .constants import COLOR_NAMES
from .store import (
    api_particulars,
    assignees_of,
    attachment_blob,
    closure_of,
    board_by_id,
    column_by_id,
    columns_for,
    comments_of,
    describe_event,
    frequency_name,
    gold_of,
    has_extra_attachments,
    not_now_of,
    spike_of,
    postpone_days,
    publication,
    reactions_of,
    rich_text,
    settings_row,
    steps_of,
    tags_for_card,
    user_by_id,
)
from .text import plain_text


def plain_text_of(row):
    return plain_text(row["body"] if row else "")


class Urls:
    def __init__(self, origin: str, external_id):
        self.origin = origin.rstrip("/")
        self.slug = f"/{external_id}" if external_id is not None else ""

    def __call__(self, *parts, query: str | None = None) -> str:
        path = self.slug + "/" + "/".join(str(part).strip("/") for part in parts if part is not None)
        url = self.origin + path
        if query:
            url += ("&" if "?" in url else "?") + query
        return url

    def abs(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return self.origin + path


def user_json(user: dict, urls: Urls) -> dict:
    return {
        "id": user["id"],
        "name": user["name"],
        "role": user["role"],
        "active": bool(user["active"]),
        "email_address": user.get("email_address"),
        "created_at": iso(user["created_at"]),
        "url": urls("users", user["id"]),
        "avatar_url": urls("users", user["id"], "avatar"),
    }


def board_json(conn, board: dict, urls: Urls, *, detailed: bool = False) -> dict:
    creator = user_by_id(conn, board["creator_id"])
    payload = {
        "id": board["id"],
        "name": board["name"],
        "all_access": bool(board["all_access"]),
        "created_at": iso(board["created_at"]),
        "auto_postpone_period_in_days": postpone_days(conn, board["account_id"], board["id"]),
        "url": urls("boards", board["id"]),
        "creator": user_json(creator, urls) if creator else None,
    }
    published = publication(conn, board["id"])
    if published:
        body = rich_text(conn, "Board", board["id"], "public_description")
        payload["public_description"] = plain_text(body["body"] if body else "")
        payload["public_description_html"] = body["body"] if body else ""
        payload["public_url"] = urls("public", "boards", published["key"])
    if detailed and not board["all_access"]:
        from .store import board_user_ids
        payload["user_ids"] = board_user_ids(conn, board["id"])
    return payload


def column_json(column: dict, urls: Urls) -> dict:
    return {
        "id": column["id"],
        "name": column["name"],
        "color": column["color"],
        "created_at": iso(column["created_at"]),
        "cards_url": urls("boards", column["board_id"], "columns", column["id"], "cards"),
    }


def step_json(step: dict) -> dict:
    return {"id": step["id"], "content": step["content"], "completed": bool(step["completed"])}


def card_json(conn, card: dict, urls: Urls, *, detailed: bool = False) -> dict:
    from .store import board_by_id

    board = board_by_id(conn, card["board_id"])
    creator = user_by_id(conn, card["creator_id"])
    description = rich_text(conn, "Card", card["id"], "description")
    image = attachment_blob(conn, "Card", card["id"], "image")
    tags = [tag["title"] for tag in tags_for_card(conn, card["id"])]
    assignees = assignees_of(conn, card["id"])
    payload = {
        "id": card["id"],
        "number": card["number"],
        "title": card["title"],
        "status": card["status"],
        "description": plain_text(description["body"] if description else ""),
        "description_html": (description["body"] if description else "") or "",
        "image_url": urls("storage", image["id"]) if image else None,
        "has_attachments": has_extra_attachments(conn, card["id"]),
        "tags": tags,
        "closed": closure_of(conn, card["id"]) is not None,
        "postponed": not_now_of(conn, card["id"]) is not None,
        "golden": gold_of(conn, card["id"]) is not None,
        "last_active_at": iso(card["last_active_at"]),
        "created_at": iso(card["created_at"]),
        "url": urls("cards", card["number"]),
        "board": board_json(conn, board, urls) if board else None,
        "creator": user_json(creator, urls) if creator else None,
        "assignees": [user_json(person, urls) for person in assignees[:5]],
        "has_more_assignees": len(assignees) > 5,
        "comments_url": urls("cards", card["number"], "comments"),
        "reactions_url": urls("cards", card["number"], "reactions"),
    }
    if card.get("column_id"):
        column = column_by_id(conn, card["column_id"])
        if column:
            payload["column"] = column_json(column, urls)
    if detailed:
        payload["steps"] = [step_json(step) for step in steps_of(conn, card["id"])]
    return payload


def comment_json(conn, comment: dict, urls: Urls, card: dict | None = None) -> dict:
    from .store import card_by_id

    card = card or card_by_id(conn, comment["card_id"])
    creator = user_by_id(conn, comment["creator_id"])
    body = rich_text(conn, "Comment", comment["id"], "body")
    return {
        "id": comment["id"],
        "created_at": iso(comment["created_at"]),
        "updated_at": iso(comment["updated_at"]),
        "body": {
            "plain_text": plain_text(body["body"] if body else ""),
            "html": (body["body"] if body else "") or "",
        },
        "creator": user_json(creator, urls) if creator else None,
        "card": {"id": card["id"], "url": urls("cards", card["number"])} if card else None,
        "reactions_url": urls("cards", card["number"], "comments", comment["id"], "reactions") if card else None,
        "url": urls("cards", card["number"], "comments", comment["id"]) if card else None,
    }


def reaction_json(conn, reaction: dict, urls: Urls, card_number, comment_id=None) -> dict:
    reacter = user_by_id(conn, reaction["reacter_id"])
    if comment_id:
        url = urls("cards", card_number, "comments", comment_id, "reactions", reaction["id"])
    else:
        url = urls("cards", card_number, "reactions", reaction["id"])
    return {
        "id": reaction["id"],
        "content": reaction["content"],
        "reacter": user_json(reacter, urls) if reacter else None,
        "url": url,
    }


def event_json(conn, event: dict, urls: Urls) -> dict:
    from .store import board_by_id, card_by_id, comment_by_id

    creator = user_by_id(conn, event["creator_id"])
    board = board_by_id(conn, event["board_id"])
    card = None
    eventable = None
    if event["eventable_type"] == "Card":
        card = card_by_id(conn, event["eventable_id"])
        eventable = card_json(conn, card, urls) if card else None
        url = urls("cards", card["number"]) if card else None
    elif event["eventable_type"] == "Comment":
        comment = comment_by_id(conn, event["eventable_id"])
        if comment:
            card = card_by_id(conn, comment["card_id"])
            eventable = comment_json(conn, comment, urls, card)
            url = urls("cards", card["number"]) + f"#comment-{comment['id']}" if card else None
        else:
            url = None
    else:
        url = None
    return {
        "id": event["id"],
        "action": event["action"],
        "created_at": iso(event["created_at"]),
        "description": describe_event(conn, event, card),
        "particulars": api_particulars(event["action"], event.get("particulars")),
        "url": url,
        "eventable_type": event["eventable_type"],
        "eventable": eventable,
        "board": board_json(conn, board, urls) if board else None,
        "creator": user_json(creator, urls) if creator else None,
    }


def notification_json(conn, notification: dict, urls: Urls) -> dict:
    from .store import card_by_id

    from .store import board_by_id

    card = card_by_id(conn, notification["card_id"])
    creator = user_by_id(conn, notification["creator_id"]) if notification.get("creator_id") else None
    column = column_by_id(conn, card["column_id"]) if card and card.get("column_id") else None
    board = board_by_id(conn, card["board_id"]) if card else None
    body = "New activity"
    if card and creator:
        body = f"{creator['name']} updated “{card['title']}”"
    return {
        "id": notification["id"],
        "unread_count": notification["unread_count"],
        "read": notification["read_at"] is not None,
        "read_at": iso(notification["read_at"]) if notification["read_at"] else None,
        "created_at": iso(notification["created_at"]),
        "source_type": (notification["source_type"] or "").replace("::", "/").lower(),
        "title": card["title"] if card else None,
        "body": body,
        "creator": user_json(creator, urls) if creator else None,
        "card": {
            "id": card["id"],
            "number": card["number"],
            "title": card["title"],
            "status": card["status"],
            "board_name": board["name"] if board else None,
            "closed": closure_of(conn, card["id"]) is not None,
            "postponed": not_now_of(conn, card["id"]) is not None,
            "url": urls("cards", card["number"]),
            "column": column_json(column, urls) if column else None,
        } if card else None,
        "url": urls("notifications", notification["id"]),
    }


def account_json(conn, account: dict) -> dict:
    return {
        "id": account["id"],
        "name": account["name"],
        "cards_count": account["cards_count"],
        "created_at": iso(account["created_at"]),
        "auto_postpone_period_in_days": postpone_days(conn, account["id"]),
    }


def tag_json(tag: dict, urls: Urls) -> dict:
    return {
        "id": tag["id"],
        "title": tag["title"],
        "created_at": iso(tag["created_at"]),
        "url": urls("cards", query=f"tag_ids[]={tag['id']}"),
    }


def webhook_json(conn, hook: dict, urls: Urls) -> dict:
    from .store import board_by_id

    board = board_by_id(conn, hook["board_id"])
    actions = hook["subscribed_actions"] or []
    if isinstance(actions, str):
        import json
        try:
            actions = json.loads(actions)
        except json.JSONDecodeError:
            actions = []
    return {
        "id": hook["id"],
        "name": hook["name"],
        "payload_url": hook["url"],
        "active": bool(hook["active"]),
        "signing_secret": hook["signing_secret"],
        "subscribed_actions": actions,
        "created_at": iso(hook["created_at"]),
        "url": urls("boards", hook["board_id"], "webhooks", hook["id"]),
        "board": board_json(conn, board, urls) if board else None,
    }


def color_label(value: str) -> str:
    return COLOR_NAMES.get(value, value)


def _ago(value) -> str:
    parsed = parse_dt(value)
    if parsed is None:
        return ""
    days = (utcnow().date() - parsed.date()).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days}d ago"


def _stamp(conn, row, title: str):
    if not row:
        return None
    who = user_by_id(conn, row.get("user_id")) if row.get("user_id") else None
    when = parse_dt(row.get("created_at"))
    return {
        "title": title,
        "date": when.strftime("%b %d, %Y") if when else "",
        "by": who["name"] if who else "",
    }


def card_view(conn, card: dict, user_id: str | None = None) -> dict:
    from .store import is_pinned, is_watching

    description = rich_text(conn, "Card", card["id"], "description")
    steps = steps_of(conn, card["id"])
    done = sum(1 for step in steps if step["completed"])
    image = attachment_blob(conn, "Card", card["id"], "image")
    column = column_by_id(conn, card["column_id"]) if card.get("column_id") else None
    board = board_by_id(conn, card["board_id"])
    closure = closure_of(conn, card["id"])
    postponed = not_now_of(conn, card["id"])
    period_days = postpone_days(conn, card["account_id"], card["board_id"])
    last_active = parse_dt(card.get("last_active_at"))
    closes_at = last_active + timedelta(days=period_days) if last_active else None
    spike = spike_of(conn, card["id"])
    stalled_at = ""
    if spike and not closure and not postponed:
        spiked = parse_dt(spike.get("updated_at"))
        updated = parse_dt(card.get("updated_at"))
        if spiked and updated and (utcnow() - spiked).days >= 14 and (utcnow() - updated).days >= 14:
            stalled_at = iso(spiked) or ""
    stages = [
        {"id": item["id"], "name": item["name"], "color": item["color"], "current": item["id"] == card.get("column_id")}
        for item in columns_for(conn, card["board_id"])
    ]
    return {
        "card": card,
        "board_name": board["name"] if board else "",
        "description_html": (description["body"] if description else "") or "",
        "description_text": plain_text(description["body"] if description else ""),
        "tags": tags_for_card(conn, card["id"]),
        "assignees": assignees_of(conn, card["id"]),
        "steps": steps,
        "step_done": done,
        "step_total": len(steps),
        "comment_count": len(comments_of(conn, card["id"])),
        "reaction_count": len(reactions_of(conn, "Card", card["id"])),
        "golden": gold_of(conn, card["id"]) is not None,
        "closed": closure is not None,
        "postponed": postponed is not None,
        "stamp": _stamp(conn, closure, "Done") or _stamp(conn, postponed, "Not Now"),
        "image": image,
        "column": column,
        "stages": stages,
        "color": (column["color"] if column else "var(--color-card-2)"),
        "pinned": is_pinned(conn, card["id"], user_id) if user_id else False,
        "watching": is_watching(conn, card["id"], user_id) if user_id else False,
        "creator": user_by_id(conn, card["creator_id"]),
        "added_ago": _ago(card.get("created_at")),
        "active_ago": _ago(card.get("last_active_at")),
        "closes_at": iso(closes_at) if closes_at else "",
        "reminder_days": max(round(period_days * 0.25), 1),
        "stalled_at": stalled_at,
    }


def settings_json(conn, user_id: str) -> dict:
    row = settings_row(conn, user_id)
    return {"bundle_email_frequency": frequency_name(row["bundle_email_frequency"]) if row else "never"}
