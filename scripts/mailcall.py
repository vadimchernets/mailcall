#!/usr/bin/env python3
"""Mailcall: the helper script behind /mailcall:setup, /mailcall:digest and /mailcall:watch.

Python standard library only. Nothing here sends, deletes, moves or marks a letter.

The main road needs no script at all: Claude reads the person's Gmail through the Gmail connector of
claude.ai (the person switches it on in Claude's settings and signs in with Google themselves).
This script is the spare road and the careful hands:

  where                      what the OS keeps, and the commands the PERSON types to store / forget
                             the app password (the script never sees it typed, never writes it)
  check  --user ADDR         IMAP: sign in with the stored app password, open INBOX read-only, count
  fetch  --user ADDR         IMAP: letters of the last N days as JSON on stdout (nothing on disk)
  alerts [--eml F ...]       Google Alerts letters -> news items with the REAL links, taken by code
  feed   --url URL | --file  a Google Alerts RSS/Atom feed -> the same items (no mail at all)
  unwrap                     stdin text -> every google.com/url?... link unwrapped, trackers cut
  letter [--file F ...]      the connector road: a letter exactly as the Gmail tool returned it
                             (raw RFC 822, Gmail API JSON with payload.headers / raw, or plain text)
                             -> sender checked by Authentication-Results like on IMAP; links and
                             Alerts items only from letters whose sender is confirmed; a letter
                             with no headers is "unverified" and gives no links
  words  list|add|remove     the person's "words to watch", kept in ~/.mailcall/watch.json
  config show|set            ~/.mailcall/config.json: address, server, road (connector|imap), lang

Every sentence meant for the person ("say", "note", "rule") comes from lang/<code>.json - en, es, pt,
ru, uk - with English underneath anything missing. The language is --lang, then config.json's "lang",
then MAILCALL_LANG, then the system's (LC_ALL, LC_MESSAGES, LANG). Codes ("code", "sender_auth")
never change with the language.

IMAP READ-ONLY IS ENFORCED BY THE PROTOCOL, NOT PROMISED (ported from the author's V1,
packages/mail-digest/source-imap.mjs):
  1. EXAMINE, never SELECT: the server opens the mailbox read-only and must answer [READ-ONLY];
  2. a whitelist on the wire: only CAPABILITY, LOGIN, LIST, EXAMINE, UID SEARCH, UID FETCH, NOOP,
     LOGOUT leave the computer, and a FETCH may ask only UID, FLAGS, INTERNALDATE, RFC822.SIZE and
     BODY.PEEK[...] (plain BODY[] and RFC822 would mark the letter read);
  3. \\Seen is measured: flags are read before and after; a letter that turned "read" is reported.
"""

import argparse
import base64
import ctypes
import datetime as dt
import email
import email.policy
import email.utils
import html
import imaplib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

SERVICE = "mailcall"
ALERTS_SENDER = "googlealerts-noreply@google.com"
MAX_DAYS = 7
MAX_ITEMS = 50
SNIPPET = 700
MAX_BYTES = 256 * 1024

# Known IMAP servers. App passwords: Gmail (needs 2-Step Verification), Yahoo, iCloud, Yandex, Mail.ru.
SERVERS = {
    "gmail.com": "imap.gmail.com", "googlemail.com": "imap.gmail.com",
    "yahoo.com": "imap.mail.yahoo.com", "icloud.com": "imap.mail.me.com", "me.com": "imap.mail.me.com",
    "yandex.ru": "imap.yandex.ru", "ya.ru": "imap.yandex.ru", "yandex.com": "imap.yandex.com",
    "mail.ru": "imap.mail.ru", "bk.ru": "imap.mail.ru", "inbox.ru": "imap.mail.ru", "list.ru": "imap.mail.ru",
    "outlook.com": "outlook.office365.com", "hotmail.com": "outlook.office365.com", "live.com": "outlook.office365.com",
    "gmx.com": "imap.gmx.com", "gmx.de": "imap.gmx.net", "ukr.net": "imap.ukr.net", "proton.me": "127.0.0.1",
}
APP_PASSWORD_PAGES = {
    "imap.gmail.com": "https://myaccount.google.com/apppasswords",
    "imap.mail.yahoo.com": "https://login.yahoo.com/account/security",
    "imap.mail.me.com": "https://account.apple.com (Sign-In and Security -> App-Specific Passwords)",
    "imap.yandex.ru": "https://id.yandex.ru/security/app-passwords",
    "imap.yandex.com": "https://id.yandex.com/security/app-passwords",
    "imap.mail.ru": "https://account.mail.ru/user/2-step-auth/passwords",
}


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANG_DIR = os.path.join(ROOT, "lang")


def lang_words(code="en"):
    """lang/<code>.json, English underneath anything missing."""
    words = {}
    for name in ("en", code):
        try:
            with open(os.path.join(LANG_DIR, "%s.json" % name), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            words.update(data)
    return words


def pick_lang(explicit=None):
    for value in (explicit, load("config.json", {}).get("lang"), os.environ.get("MAILCALL_LANG"),
                  os.environ.get("LC_ALL"), os.environ.get("LC_MESSAGES"), os.environ.get("LANG")):
        if isinstance(value, str) and len(value) >= 2:
            code = value[:2].lower()
            if os.path.exists(os.path.join(LANG_DIR, "%s.json" % code)):
                return code
    return "en"


WORDS = lang_words("en")


def t(key):
    return WORDS.get(key, key)


def home():
    h = os.environ.get("MAILCALL_HOME") or os.path.join(os.path.expanduser("~"), ".mailcall")
    os.makedirs(h, exist_ok=True)
    return h


def out(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=1) + "\n")


def load(name, default):
    try:
        with open(os.path.join(home(), name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save(name, obj):
    p = os.path.join(home(), name)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def server_for(addr, given=None):
    if given:
        return given
    dom = str(addr or "").rsplit("@", 1)[-1].lower()
    return SERVERS.get(dom, "imap." + dom if dom else "")


# ---------------------------------------------------------------- the OS credential store -------------

def target(user):
    return "%s:%s" % (SERVICE, user)


def store_commands(user):
    """The commands the person types in their own terminal. Each one asks for the password itself."""
    u = user.replace('"', "")
    return {
        "Darwin": {"store": 'security add-generic-password -U -s %s -a "%s" -w' % (SERVICE, u),
                   "forget": 'security delete-generic-password -s %s -a "%s"' % (SERVICE, u),
                   "where": "Keychain Access, item \"%s\"" % SERVICE},
        "Linux": {"store": 'secret-tool store --label="mailcall %s" service %s account "%s"' % (u, SERVICE, u),
                  "forget": 'secret-tool clear service %s account "%s"' % (SERVICE, u),
                  "where": "GNOME Keyring / KWallet (Secret Service), label \"mailcall %s\"" % u},
        "Windows": {"store": 'cmdkey /generic:%s /user:"%s" /pass' % (target(u), u),
                    "forget": "cmdkey /delete:%s" % target(u),
                    "where": "Credential Manager -> Windows Credentials, \"%s\"" % target(u)},
    }.get(platform.system(), {})


def _win_read(user):
    try:
        from ctypes import wintypes

        class CRED(ctypes.Structure):
            _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                        ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                        ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
                        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                        ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]
        adv = ctypes.WinDLL("advapi32")
        p = ctypes.POINTER(CRED)()
        if not adv.CredReadW(target(user), 1, 0, ctypes.byref(p)):
            return None
        try:
            blob = ctypes.string_at(p.contents.CredentialBlob, p.contents.CredentialBlobSize)
            return blob.decode("utf-16-le")
        finally:
            adv.CredFree(p)
    except Exception:
        return None


def read_password(user):
    """From the OS store only. No file, no environment variable, no question."""
    sysname = platform.system()
    try:
        if sysname == "Darwin":
            r = subprocess.run(["security", "find-generic-password", "-s", SERVICE, "-a", user, "-w"],
                               capture_output=True, text=True, timeout=20)
            return r.stdout.rstrip("\n") if r.returncode == 0 and r.stdout.strip() else None
        if sysname == "Linux":
            if not shutil.which("secret-tool"):
                return None
            r = subprocess.run(["secret-tool", "lookup", "service", SERVICE, "account", user],
                               capture_output=True, text=True, timeout=20)
            return r.stdout.rstrip("\n") if r.returncode == 0 and r.stdout.strip() else None
        if sysname == "Windows":
            return _win_read(user)
    except (OSError, subprocess.SubprocessError):
        return None
    return None


# ---------------------------------------------------------------- the wire whitelist -----------------

ALLOWED = ("CAPABILITY", "LOGIN", "LIST", "EXAMINE", "UID SEARCH", "UID FETCH", "NOOP", "LOGOUT")
FETCH_ATOMS = ("UID", "FLAGS", "INTERNALDATE", "RFC822.SIZE")
PEEK = re.compile(r"BODY\.PEEK\[[^\]\r\n]*\](?:<\d+(?:\.\d+)?>)?", re.I)


def check_command(name, args=()):
    """(ok, why). The same rule the guarded client applies before a byte is written."""
    name = str(name or "").upper()
    args = [a.decode() if isinstance(a, bytes) else str(a) for a in args]
    if any(re.search(r"[\r\n\0]", a) for a in args):
        return False, "shape"
    verb = name
    if name == "UID":
        verb = "UID " + (args[0].upper() if args else "")
        args = args[1:]
    if verb not in ALLOWED:
        return False, "verb %s" % verb
    if verb == "UID FETCH":
        items = (args[1] if len(args) > 1 else "").strip()
        items = items[1:-1] if items.startswith("(") and items.endswith(")") else items
        rest = PEEK.sub(" ", items)
        for tok in rest.split():
            if tok.upper() not in FETCH_ATOMS:
                return False, "fetch item %s" % tok
    if verb == "UID SEARCH":
        joined = " ".join(args).upper()
        if not re.fullmatch(r"(CHARSET UTF-8 )?(UID \d+:\* )?SINCE \d{1,2}-[A-Z]{3}-\d{4}( FROM \"[^\"]*\")?", joined):
            return False, "search shape"
    return True, verb


class Refused(Exception):
    pass


class Guard:
    """Refuses, before one byte is written, every command off the read-only list."""

    def _command(self, name, *args):
        ok, why = check_command(name, args)
        if not ok:
            raise Refused(why)
        return super()._command(name, *args)


class GuardedIMAP(Guard, imaplib.IMAP4_SSL):
    pass


def imap_since(days):
    d = dt.date.today() - dt.timedelta(days=max(1, min(MAX_DAYS, int(days))))
    return d.strftime("%d-%b-%Y")


def _flags(conn, uids):
    res = {}
    if not uids:
        return res
    typ, data = conn.uid("FETCH", ",".join(uids), "(UID FLAGS)")
    for item in data or []:
        line = item[0] if isinstance(item, tuple) else item
        if not isinstance(line, bytes):
            continue
        m = re.search(rb"UID (\d+)", line)
        f = re.search(rb"FLAGS \(([^)]*)\)", line)
        if m:
            res[m.group(1).decode()] = (f.group(1).decode() if f else "")
    return res


def open_readonly(conn, user, password, mailbox="INBOX"):
    conn.login(user, password)
    typ, _ = conn.select('"%s"' % mailbox, readonly=True)
    if typ != "OK":
        raise Refused("examine refused")
    if "READ-ONLY" not in conn.untagged_responses:
        raise Refused("server did not confirm READ-ONLY")


def fetch_letters(conn, days=1, limit=50, sender=None):
    """Letters of the last `days` days in the already-opened (EXAMINE) mailbox. Never marks anything."""
    crit = ["SINCE", imap_since(days)]
    if sender:
        crit += ["FROM", '"%s"' % sender.replace('"', "")]
    typ, data = conn.uid("SEARCH", *crit)
    uids = (data[0].split() if data and data[0] else [])
    uids = [u.decode() for u in uids][-max(1, min(200, int(limit))):]
    before = _flags(conn, uids)
    letters = []
    for uid in uids:
        typ, data = conn.uid("FETCH", uid, "(UID BODY.PEEK[]<0.%d>)" % MAX_BYTES)
        raw = b"".join(x[1] for x in (data or []) if isinstance(x, tuple) and isinstance(x[1], bytes))
        if raw:
            letters.append(describe(raw, uid, unread="\\Seen" not in before.get(uid, "")))
    after = _flags(conn, uids)
    changed = [u for u in uids if "\\Seen" not in before.get(u, "") and "\\Seen" in after.get(u, "")]
    return letters, changed


# ---------------------------------------------------------------- reading one letter ------------------

def html_to_text(s):
    s = re.sub(r"(?is)<(script|style|head)\b.*?</\1\s*>", " ", s or "")
    s = re.sub(r"(?i)<br\s*/?>|</p\s*>|</div\s*>|</tr\s*>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n", s)).strip()


def parts(msg):
    plain, rich = None, None
    for p in (msg.walk() if msg.is_multipart() else [msg]):
        ct = p.get_content_type()
        if ct not in ("text/plain", "text/html") or p.get_content_disposition() == "attachment":
            continue
        try:
            body = p.get_content()
        except Exception:
            try:
                body = (p.get_payload(decode=True) or b"").decode("utf-8", "replace")
            except Exception:
                body = ""
        if ct == "text/plain" and plain is None:
            plain = body
        if ct == "text/html" and rich is None:
            rich = body
    return plain, rich


def auth_verdict(msg):
    """The receiving Google server vouches for the sender: top Authentication-Results by mx.google.com,
    with dmarc=pass, or dkim=pass for google.com."""
    ar = msg.get_all("Authentication-Results") or []
    if not ar:
        return "unsigned"
    top = str(ar[0]).strip()
    if not top.lower().startswith("mx.google.com"):
        return "unsigned"
    low = top.lower()
    if "dmarc=pass" in low or re.search(r"dkim=pass[^;]*header\.(i=@|d=)google\.com", low):
        return "pass"
    return "unsigned"


def sender_verdict(msg):
    """Any sender, the same rule as for Alerts: the top Authentication-Results, written by Gmail's own
    mx.google.com, says dmarc=pass for the From domain, or dkim=pass for that domain.
    pass | fail (headers there, no pass: looks forged) | unverified (no headers to check)."""
    ar = msg.get_all("Authentication-Results") or []
    if not ar:
        # the full header set is there (Gmail always writes Received and its verdict) but no verdict:
        # Gmail did not vouch for this sender. Only a body or From/Subject: nothing to check.
        return "fail" if (msg.get("Received") or msg.get("Message-ID")) else "unverified"
    top = re.sub(r"\s+", " ", str(ar[0])).strip().lower()
    if not top.startswith("mx.google.com"):
        return "fail"
    dom = email.utils.parseaddr(str(msg.get("From", "")))[1].lower().rpartition("@")[2]
    if not dom:
        return "fail"
    for m in re.finditer(r"dmarc=pass[^;]*header\.from=([a-z0-9.-]+)", top):
        if m.group(1) == dom:
            return "pass"
    for m in re.finditer(r"dkim=pass[^;]*header\.(?:i=[^ ;]*@|d=)([a-z0-9.-]+)", top):
        d = m.group(1)
        if dom == d or dom.endswith("." + d):
            return "pass"
    return "fail"


def body_links(plain, rich):
    found = []
    for href in re.findall(r"""(?i)\bhref\s*=\s*(?:"([^"]*)"|'([^']*)')""", rich or ""):
        found += unwrap_text(href[0] or href[1])
    found += unwrap_text(html.unescape(plain or "")) + unwrap_text(html.unescape(html_to_text(rich or "")))
    out_ = []
    for u in found:
        if u not in out_:
            out_.append(u)
    return out_[:MAX_ITEMS]


SAY = {"pass": "say_sender_pass", "fail": "say_sender_fail", "unverified": "say_sender_unverified"}


def check_letter(raw, uid=None):
    """The connector road, the same hands as IMAP: who really sent it, and links only from code."""
    msg = email.message_from_bytes(raw if isinstance(raw, bytes) else raw.encode("utf-8"), policy=email.policy.default)
    d = describe(raw, uid=uid)
    verdict = sender_verdict(msg)
    if d["google_alerts"] and verdict != "unverified":
        verdict = "pass" if auth_verdict(msg) == "pass" else "fail"
    if d["google_alerts"]:
        d["alerts_auth"] = {"pass": "pass", "fail": "unsigned", "unverified": "unverified"}[verdict]
        if verdict != "pass":
            d["alerts_items"] = []
    plain, rich = parts(msg)
    rec = [str(r) for r in (msg.get_all("Received") or [])]
    d.update({"sender_auth": verdict, "say": t(SAY[verdict]),
              "received_by_google": bool(rec) and "google.com" in re.sub(r"\s+", " ", rec[0]).lower(),
              "links": body_links(plain, rich) if verdict == "pass" else []})
    return d


def _b64url(data):
    data = re.sub(r"\s+", "", data or "")
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _gmail_json_to_raw(obj):
    """A message object as a Gmail tool may give it -> RFC 822 bytes. None if it is not a message."""
    if not isinstance(obj, dict):
        return None
    for k in ("raw", "rawMessage", "raw_message"):
        if isinstance(obj.get(k), str) and obj[k].strip():
            v = obj[k]
            try:
                b = _b64url(v)
                if re.match(rb"^[\x21-\x39\x3b-\x7e]+:", b):
                    return b
            except Exception:
                pass
            return v.encode("utf-8")
    payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else obj
    hdrs = payload.get("headers") or obj.get("headers") or []
    if isinstance(hdrs, dict):
        hdrs = [{"name": k, "value": v} for k, vals in hdrs.items() for v in (vals if isinstance(vals, list) else [vals])]
    pairs = [(h.get("name"), h.get("value")) for h in hdrs if isinstance(h, dict) and h.get("name")]
    names = {n.lower() for n, _ in pairs}
    for k in ("from", "to", "subject", "date"):
        if k not in names and isinstance(obj.get(k), str):
            pairs.append((k.capitalize(), obj[k]))
    texts = {"text/html": [], "text/plain": []}

    def walk(p):
        if not isinstance(p, dict):
            return
        mt = (p.get("mimeType") or p.get("mime_type") or "").lower()
        data = (p.get("body") or {}).get("data") if isinstance(p.get("body"), dict) else None
        if data and mt in texts:
            try:
                texts[mt].append(_b64url(data).decode("utf-8", "replace"))
            except Exception:
                pass
        for c in p.get("parts") or []:
            walk(c)
    walk(payload)
    for k, mt in (("html", "text/html"), ("htmlBody", "text/html"), ("body_html", "text/html"),
                  ("body", "text/plain"), ("text", "text/plain"), ("plaintext", "text/plain"),
                  ("content", "text/plain"), ("snippet", "text/plain")):
        if isinstance(obj.get(k), str) and not texts[mt]:
            texts[mt].append(obj[k])
    if not pairs and not texts["text/html"] and not texts["text/plain"]:
        return None
    rich, plain = "\n".join(texts["text/html"]), "\n".join(texts["text/plain"])
    if not texts["text/html"] and re.search(r"(?i)<(html|a|table|div|p)\b", plain):
        rich, plain = plain, ""
    keep = [(n, v) for n, v in pairs if n.lower() not in ("content-type", "content-transfer-encoding", "mime-version")]
    head = "".join("%s: %s\r\n" % (n, re.sub(r"[\r\n]+", " ", str(v))) for n, v in keep)
    if rich and plain:
        b = "mailcallpart"
        body = (f"MIME-Version: 1.0\r\nContent-Type: multipart/alternative; boundary=\"{b}\"\r\n\r\n"
                f"--{b}\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{plain}\r\n"
                f"--{b}\r\nContent-Type: text/html; charset=utf-8\r\n\r\n{rich}\r\n--{b}--\r\n")
    else:
        ct = "text/html" if rich else "text/plain"
        body = f"MIME-Version: 1.0\r\nContent-Type: {ct}; charset=utf-8\r\n\r\n{rich or plain}"
    return (head + body).encode("utf-8")


def letters_from_text(text):
    """What the connector tool returned -> a list of RFC 822 letters (bytes)."""
    t = (text or "").lstrip("\ufeff")
    try:
        obj = json.loads(t)
    except ValueError:
        obj = None
    if obj is not None:
        found = []

        def walk(o):
            r = _gmail_json_to_raw(o) if isinstance(o, dict) and (
                "payload" in o or "raw" in o or "headers" in o or "from" in o or "rawMessage" in o) else None
            if r:
                found.append(r)
                return
            for v in (o.values() if isinstance(o, dict) else o if isinstance(o, list) else []):
                walk(v)
        walk(obj)
        return found
    if re.match(r"^[\x21-\x39\x3b-\x7e]+:", t):
        return [t.encode("utf-8")]          # raw RFC 822 source
    # only the body text: no headers to check; the letter is "unverified"
    return [("Content-Type: text/plain; charset=utf-8\r\n\r\n" + t).encode("utf-8")] if t.strip() else []


def describe(raw, uid=None, unread=None):
    msg = email.message_from_bytes(raw if isinstance(raw, bytes) else raw.encode("utf-8"), policy=email.policy.default)
    frm = email.utils.parseaddr(str(msg.get("From", "")))
    plain, rich = parts(msg)
    text = (plain or html_to_text(rich or "")).strip()
    text = re.sub(r"\s+", " ", text)[:SNIPPET]
    try:
        when = email.utils.parsedate_to_datetime(str(msg.get("Date"))).isoformat()
    except Exception:
        when = None
    is_alert = frm[1].lower() == ALERTS_SENDER
    d = {"id": uid, "from_name": frm[0], "from": frm[1].lower(), "subject": str(msg.get("Subject", "")),
         "date": when, "unread": unread, "newsletter": bool(msg.get("List-Unsubscribe") or msg.get("List-Id")),
         "reply_to_me": bool(msg.get("In-Reply-To")), "snippet": text, "google_alerts": is_alert}
    if is_alert:
        verdict = auth_verdict(msg)
        d["alerts_auth"] = verdict
        d["alerts_items"] = alert_items(rich or plain or "") if verdict == "pass" else []
    return d


# ---------------------------------------------------------------- links: taken by code ----------------

TRACKING = re.compile(r"^(utm_.*|fbclid|gclid|dclid|mc_cid|mc_eid|yclid|_hsenc|_hsmi)$", re.I)


def is_google(host):
    return bool(re.search(r"(^|\.)google\.[a-z.]{2,6}$", host or "", re.I))


def unwrap(href):
    """The real address behind a Google redirect; http/https only; tracking parameters cut. Or None."""
    try:
        u = urllib.parse.urlsplit(html.unescape(str(href).strip()))
        for _ in range(2):
            if is_google(u.hostname) and u.path == "/url":
                q = urllib.parse.parse_qs(u.query)
                inner = (q.get("url") or q.get("q") or [None])[0]
                if not inner:
                    return None
                u = urllib.parse.urlsplit(inner)
        if u.scheme not in ("http", "https") or u.username or u.password or not u.hostname:
            return None
        q = [(k, v) for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True) if not TRACKING.match(k)]
        url = urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, urllib.parse.urlencode(q), ""))
        return url if len(url) <= 2048 else None
    except Exception:
        return None


def clean_title(s):
    s = html.unescape(re.sub(r"<[^>]*>", " ", str(s or "")))
    s = re.sub(r"<[^>]*>", " ", s)
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", s)).strip()[:300]


def collect(pairs):
    items, seen = [], {}
    for href, title in pairs:
        url = unwrap(href)
        if not url:
            continue
        host = urllib.parse.urlsplit(url).hostname.lower()
        if is_google(host):
            continue
        t = clean_title(title)
        if url in seen:
            if t and not seen[url]["title"]:
                seen[url]["title"] = t
            continue
        if len(items) >= MAX_ITEMS:
            break
        it = {"title": t, "site": host[4:] if host.startswith("www.") else host, "url": url}
        seen[url] = it
        items.append(it)
    return [i for i in items if i["title"]]


def alert_items(html_body):
    s = re.sub(r"(?is)<(script|style|head)\b.*?</\1\s*>", "", html_body or "")
    pairs = []
    for m in re.finditer(r"(?is)<a\b([^>]*)>(.*?)</a\s*>", s):
        h = re.search(r"""(?i)\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", m.group(1))
        if h:
            pairs.append((h.group(1) or h.group(2) or h.group(3) or "", m.group(2)))
    if not pairs:  # a plain-text Alerts letter: "Title\n<https://www.google.com/url?...>"
        for m in re.finditer(r"(?m)^(.+?)\s*\n\s*<?(https?://\S+?)>?\s*$", html_body or ""):
            pairs.append((m.group(2), m.group(1)))
    return collect(pairs)


def feed_items(xml):
    if not re.search(r"<(feed|rss)\b", xml or "", re.I):
        return None
    pairs = []
    for b in re.findall(r"(?is)<(?:entry|item)\b.*?</(?:entry|item)\s*>", xml)[:MAX_ITEMS * 4]:
        t = re.search(r"(?is)<title\b[^>]*>(.*?)</title\s*>", b)
        title = re.sub(r"(?s)^\s*<!\[CDATA\[(.*?)\]\]>\s*$", r"\1", t.group(1)) if t else ""
        a = re.search(r"""(?i)<link\b[^>]*\bhref\s*=\s*(?:"([^"]*)"|'([^']*)')""", b)
        href = (a.group(1) or a.group(2)) if a else None
        if not href:
            r = re.search(r"(?is)<link\b[^>]*>(.*?)</link\s*>", b)
            href = re.sub(r"(?s)^\s*<!\[CDATA\[(.*?)\]\]>\s*$", r"\1", r.group(1)).strip() if r else None
        if href:
            pairs.append((href, html.unescape(title)))
    return collect(pairs)


def unwrap_text(text):
    found = []
    for m in re.finditer(r"https?://[^\s<>\"')\]]+", text or ""):
        u = unwrap(m.group(0))
        if u and not is_google(urllib.parse.urlsplit(u).hostname) and u not in found:
            found.append(u)
    return found


# ---------------------------------------------------------------- commands ----------------------------

def cmd_where(a):
    user = a.user or load("config.json", {}).get("user")
    if not user:
        out({"ok": False, "code": "no-user", "say": t("say_no_user")})
        return 2
    host = server_for(user, a.host)
    c = store_commands(user)
    out({"ok": True, "system": platform.system(), "user": user, "server": host, "store": c.get("store"),
         "forget": c.get("forget"), "where": c.get("where"), "app_password_page": APP_PASSWORD_PAGES.get(host),
         "stored": read_password(user) is not None,
         "note": t("note_store")})
    return 0


def connect(a):
    cfg = load("config.json", {})
    user = a.user or cfg.get("user")
    host = server_for(user, a.host or cfg.get("host"))
    if not user:
        return None, {"ok": False, "code": "no-user"}
    pw = read_password(user)
    if not pw:
        c = store_commands(user)
        return None, {"ok": False, "code": "no-password", "store": c.get("store"),
                      "app_password_page": APP_PASSWORD_PAGES.get(host)}
    try:
        conn = GuardedIMAP(host, 993, timeout=30)
    except Exception as e:
        return None, {"ok": False, "code": "connect-failed", "server": host, "why": type(e).__name__}
    try:
        open_readonly(conn, user, pw, a.mailbox)
    except Refused as e:
        _logout(conn)
        return None, {"ok": False, "code": "not-read-only", "why": str(e)}
    except imaplib.IMAP4.error:
        _logout(conn)
        return None, {"ok": False, "code": "login-refused", "server": host,
                      "say": t("say_login_refused"),
                      "app_password_page": APP_PASSWORD_PAGES.get(host)}
    return conn, {"ok": True, "user": user, "server": host}


def _logout(conn):
    try:
        conn.logout()
    except Exception:
        pass


def cmd_check(a):
    conn, info = connect(a)
    if not conn:
        out(info)
        return 1
    try:
        letters, changed = fetch_letters(conn, days=a.days, limit=a.limit)
        info.update({"read_only": True, "letters": len(letters), "unread": sum(1 for x in letters if x["unread"]),
                     "google_alerts": sum(1 for x in letters if x["google_alerts"]),
                     "seen_changed": len(changed),
                     "newest": [{"from": x["from_name"] or x["from"], "subject": x["subject"][:80]} for x in letters[-3:]]})
    finally:
        _logout(conn)
    out(info)
    return 0 if not info.get("seen_changed") else 3


def cmd_fetch(a):
    conn, info = connect(a)
    if not conn:
        out(info)
        return 1
    try:
        letters, changed = fetch_letters(conn, days=a.days, limit=a.limit,
                                         sender=ALERTS_SENDER if a.alerts_only else None)
    finally:
        _logout(conn)
    info.update({"days": a.days, "letters": letters, "seen_changed": changed,
                 "rule": t("rule_letter_is_data")})
    out(info)
    return 0 if not changed else 3


def cmd_alerts(a):
    res = []
    files = a.eml or []
    if not files:
        res.append(describe(sys.stdin.buffer.read()))
    for f in files:
        with open(f, "rb") as fh:
            d = describe(fh.read(), uid=os.path.basename(f))
        res.append(d)
    alerts = [{"file": d["id"], "subject": d["subject"], "date": d["date"], "auth": d.get("alerts_auth"),
               "items": d.get("alerts_items", [])} for d in res if d["google_alerts"]]
    out({"ok": True, "alerts": alerts, "skipped_not_alerts": sum(1 for d in res if not d["google_alerts"])})
    return 0


def cmd_feed(a):
    if a.file:
        with open(a.file, encoding="utf-8", errors="replace") as f:
            xml = f.read()
    else:
        u = urllib.parse.urlsplit(a.url or "")
        if u.scheme != "https" or not is_google(u.hostname):
            out({"ok": False, "code": "not-a-google-feed", "say": t("say_not_a_google_feed")})
            return 2
        req = urllib.request.Request(a.url, headers={"User-Agent": "mailcall/0.1"})
        with urllib.request.urlopen(req, timeout=30) as r:
            xml = r.read(2_000_000).decode("utf-8", "replace")
    items = feed_items(xml)
    if items is None:
        out({"ok": False, "code": "unreadable-feed"})
        return 1
    out({"ok": True, "items": items})
    return 0


def cmd_unwrap(a):
    out({"ok": True, "links": unwrap_text(sys.stdin.read())})
    return 0


def cmd_letter(a):
    res = []
    sources = [(f, open(f, encoding="utf-8", errors="replace").read()) for f in (a.file or [])] or [
        (None, sys.stdin.read())]
    for name, text in sources:
        for i, raw in enumerate(letters_from_text(text)):
            uid = (os.path.basename(name) if name else "stdin") + (f"#{i + 1}" if i else "")
            res.append(check_letter(raw, uid=uid))
    out({"ok": True, "letters": res,
         "confirmed": sum(1 for d in res if d["sender_auth"] == "pass"),
         "looks_forged": sum(1 for d in res if d["sender_auth"] == "fail"),
         "not_checked": sum(1 for d in res if d["sender_auth"] == "unverified")})
    return 0


def cmd_words(a):
    w = load("watch.json", {"words": []})
    words = w.get("words", [])
    if a.action == "add":
        for x in a.word:
            x = x.strip()
            if x and x not in [y["word"] for y in words]:
                words.append({"word": x, "alerts_phrase": '"%s"' % x.strip('"'), "added": dt.date.today().isoformat()})
    elif a.action == "remove":
        words = [y for y in words if y["word"] not in a.word]
    if a.action != "list":
        save("watch.json", {"words": words})
    out({"ok": True, "words": words, "file": os.path.join(home(), "watch.json"),
         "google_alerts": "https://www.google.com/alerts"})
    return 0


def cmd_config(a):
    cfg = load("config.json", {})
    if a.action == "set":
        for k in ("user", "host", "road", "lang"):
            v = getattr(a, k)
            if v:
                cfg[k] = v
        if cfg.get("user") and not cfg.get("host"):
            cfg["host"] = server_for(cfg["user"])
        save("config.json", cfg)
    out({"ok": True, "config": cfg, "file": os.path.join(home(), "config.json")})
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="mailcall")
    sub = p.add_subparsers(dest="cmd", required=True)

    def imap_args(s):
        s.add_argument("--user")
        s.add_argument("--host")
        s.add_argument("--mailbox", default="INBOX")
        s.add_argument("--days", type=int, default=1)
        s.add_argument("--limit", type=int, default=50)

    s = sub.add_parser("where"); s.add_argument("--user"); s.add_argument("--host"); s.set_defaults(f=cmd_where)
    s = sub.add_parser("check"); imap_args(s); s.set_defaults(f=cmd_check)
    s = sub.add_parser("fetch"); imap_args(s); s.add_argument("--alerts-only", action="store_true"); s.set_defaults(f=cmd_fetch)
    s = sub.add_parser("alerts"); s.add_argument("--eml", nargs="*"); s.set_defaults(f=cmd_alerts)
    s = sub.add_parser("feed"); s.add_argument("--url"); s.add_argument("--file"); s.set_defaults(f=cmd_feed)
    s = sub.add_parser("unwrap"); s.set_defaults(f=cmd_unwrap)
    s = sub.add_parser("letter"); s.add_argument("--file", nargs="*"); s.set_defaults(f=cmd_letter)
    s = sub.add_parser("words"); s.add_argument("action", choices=["list", "add", "remove"])
    s.add_argument("word", nargs="*"); s.set_defaults(f=cmd_words)
    s = sub.add_parser("config"); s.add_argument("action", choices=["show", "set"])
    s.add_argument("--user"); s.add_argument("--host"); s.add_argument("--road", choices=["connector", "imap", "feed"])
    s.set_defaults(f=cmd_config)
    for name, s in sub.choices.items():
        if name == "config":
            s.add_argument("--lang", choices=["en", "es", "pt", "ru", "uk"],
                           help="with set: the language mailcall speaks to the person from now on")
        else:
            s.add_argument("--lang", help="en, es, pt, ru or uk (default: config, then the system's)")
    a = p.parse_args(argv)
    global WORDS
    WORDS = lang_words(pick_lang(a.lang))
    try:
        return a.f(a)
    except Refused as e:
        out({"ok": False, "code": "command-refused", "why": str(e)})
        return 4


if __name__ == "__main__":
    sys.exit(main())
