"""Gmail (IMAP/SMTP with an app password — no OAuth dance) and Slack (bot
token) tools. Reading is free; sending is approval-gated like any other
outward action. Configure in Settings → Integrations.
"""
import asyncio
import email as email_lib
import email.header
import imaplib
import json
import smtplib
import urllib.request
from email.mime.text import MIMEText

from ..config import load_config


def _gmail_cfg():
    g = (load_config().get("integrations") or {}).get("gmail") or {}
    if not g.get("email") or not g.get("app_password"):
        return None
    return g


def _slack_cfg():
    s = (load_config().get("integrations") or {}).get("slack") or {}
    if not s.get("bot_token"):
        return None
    return s


def _decode(h):
    try:
        return str(email.header.make_header(email.header.decode_header(h or "")))
    except Exception:
        return h or ""


def _list_emails_sync(limit, unread_only):
    g = _gmail_cfg()
    if not g:
        return {"error": "Gmail not configured — add your address + app password in Settings → Integrations"}
    with imaplib.IMAP4_SSL("imap.gmail.com") as im:
        im.login(g["email"], g["app_password"])
        im.select("INBOX")
        _, data = im.search(None, "UNSEEN" if unread_only else "ALL")
        ids = data[0].split()[-limit:][::-1]
        out = []
        for mid in ids:
            _, msg_data = im.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            msg = email_lib.message_from_bytes(msg_data[0][1])
            out.append({"id": mid.decode(), "from": _decode(msg["From"])[:80],
                        "subject": _decode(msg["Subject"])[:120], "date": msg["Date"]})
        return {"emails": out, "unread_only": unread_only}


def _read_email_sync(mid):
    g = _gmail_cfg()
    if not g:
        return {"error": "Gmail not configured — add your address + app password in Settings → Integrations"}
    with imaplib.IMAP4_SSL("imap.gmail.com") as im:
        im.login(g["email"], g["app_password"])
        im.select("INBOX")
        _, msg_data = im.fetch(mid.encode(), "(BODY.PEEK[])")
        msg = email_lib.message_from_bytes(msg_data[0][1])
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode(errors="replace")
                    break
        else:
            body = msg.get_payload(decode=True).decode(errors="replace")
        return {"from": _decode(msg["From"]), "subject": _decode(msg["Subject"]),
                "date": msg["Date"], "body": body[:8000]}


def _send_email_sync(to, subject, body):
    g = _gmail_cfg()
    if not g:
        return {"error": "Gmail not configured — add your address + app password in Settings → Integrations"}
    msg = MIMEText(body)
    msg["Subject"], msg["From"], msg["To"] = subject, g["email"], to
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as sm:
        sm.login(g["email"], g["app_password"])
        sm.send_message(msg)
    return {"ok": True, "sent_to": to}


def _slack_post_sync(channel, text):
    s = _slack_cfg()
    if not s:
        return {"error": "Slack not configured — add a bot token in Settings → Integrations"}
    channel = channel or s.get("default_channel")
    if not channel:
        return {"error": "no channel given and no default_channel configured"}
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=json.dumps({"channel": channel, "text": text}).encode(),
        headers={"Authorization": f"Bearer {s['bot_token']}",
                 "Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=20) as r:
        resp = json.loads(r.read())
    if not resp.get("ok"):
        return {"error": f"slack: {resp.get('error', 'unknown')}"}
    return {"ok": True, "channel": channel}


async def list_emails(args, ctx):
    return await asyncio.to_thread(_list_emails_sync, int(args.get("limit", 5)), bool(args.get("unread_only", True)))


async def read_email(args, ctx):
    return await asyncio.to_thread(_read_email_sync, args["id"])


async def send_email(args, ctx):
    return await asyncio.to_thread(_send_email_sync, args["to"], args["subject"], args["body"])


async def slack_post(args, ctx):
    return await asyncio.to_thread(_slack_post_sync, args.get("channel"), args["text"])
