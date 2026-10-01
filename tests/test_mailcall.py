"""Mailcall tests: `python3 -m pytest tests` (or `python3 tests/test_mailcall.py`).

No network and no real mailbox: the letters are fake files in tests/letters, and the IMAP server is a
tiny fake one on 127.0.0.1 that records every command it receives - so the tests prove what reaches
the wire (EXAMINE, BODY.PEEK) and what never does (SELECT, STORE, plain BODY[]).
"""

import imaplib
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import mailcall as mc  # noqa: E402

LET = os.path.join(ROOT, "tests", "letters")
SCRIPT = os.path.join(ROOT, "scripts", "mailcall.py")


def raw(name):
    with open(os.path.join(LET, name), "rb") as f:
        return f.read().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


def run(*args, env=None, inp=None):
    e = dict(os.environ)
    e["MAILCALL_HOME"] = tempfile.mkdtemp()
    e.update(env or {})
    r = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, env=e, input=inp, timeout=60)
    return r.returncode, json.loads(r.stdout) if r.stdout.strip() else None


# ------------------------------------------------------------------ Google Alerts, links by code

def test_alerts_real_letter_gives_real_links():
    d = mc.describe(raw("alerts-real.eml"))
    assert d["google_alerts"] and d["alerts_auth"] == "pass"
    urls = [i["url"] for i in d["alerts_items"]]
    assert urls == ["https://citynews.example.org/bakery?id=7", "https://blog.example.net/2026/09/review"]
    assert all("google." not in u for u in urls)          # manage / unsubscribe dropped
    assert all("utm_" not in u for u in urls)             # trackers cut
    assert d["alerts_items"][0]["title"] == "Anna Petrova opens a bakery on Main Street"


def test_forged_alerts_letter_gives_nothing():
    d = mc.describe(raw("alerts-forged.eml"))
    assert d["google_alerts"] and d["alerts_auth"] == "unsigned" and d["alerts_items"] == []


def test_ordinary_letters():
    p = mc.describe(raw("from-person.eml"))
    assert p["from"] == "oleg@example.com" and not p["newsletter"] and not p["google_alerts"]
    assert "contract" in p["snippet"]
    n = mc.describe(raw("newsletter.eml"))
    assert n["newsletter"] and "color:red" not in n["snippet"] and "Big sale" in n["snippet"]


def test_feed_and_unwrap():
    with open(os.path.join(LET, "alerts-feed.xml"), encoding="utf-8") as f:
        items = mc.feed_items(f.read())
    assert [i["url"] for i in items] == ["https://citynews.example.org/bakery", "https://other.example.com/x?page=2"]
    assert items[0]["title"] == "Anna Petrova opens a bakery" and items[1]["title"] == "Second & last"
    assert mc.feed_items("<html>no</html>") is None
    assert mc.unwrap("javascript:alert(1)") is None
    assert mc.unwrap("https://user:pw@example.com/") is None
    assert mc.unwrap("https://www.google.com/url?q=https://a.example/p") == "https://a.example/p"
    code, o = run("unwrap", inp="see https://www.google.com/url?url=https://a.example/x%3Futm_medium%3Dm and https://www.google.com/alerts")
    assert code == 0 and o["links"] == ["https://a.example/x"]


def test_cli_alerts_and_feed():
    code, o = run("alerts", "--eml", *[os.path.join(LET, f) for f in sorted(os.listdir(LET)) if f.endswith(".eml")])
    assert code == 0 and o["skipped_not_alerts"] == 2
    good = [a for a in o["alerts"] if a["auth"] == "pass"]
    assert len(good) == 1 and len(good[0]["items"]) == 2
    code, o = run("feed", "--url", "https://evil.example.com/feed")
    assert code == 2 and o["code"] == "not-a-google-feed"


# ------------------------------------------------------------------ the connector road: the same check

def _gmail_json(name):
    """A letter the way the Gmail API / connector gives it: payload.headers + base64url parts."""
    import base64
    import email as em
    import email.policy as ep
    msg = em.message_from_bytes(raw(name), policy=ep.default)
    def part(p):
        d = {"mimeType": p.get_content_type(), "parts": [part(c) for c in p.iter_parts()] if p.is_multipart() else []}
        if not p.is_multipart():
            d["body"] = {"data": base64.urlsafe_b64encode(p.get_content().encode("utf-8")).decode().rstrip("=")}
        return d
    payload = part(msg)
    payload["headers"] = [{"name": k, "value": str(v)} for k, v in msg.items()]
    return {"id": "m1", "payload": payload}


def test_connector_letter_real_alerts_json_gives_links():
    code, o = run("letter", inp=json.dumps(_gmail_json("alerts-real.eml")))
    d = o["letters"][0]
    assert code == 0 and d["sender_auth"] == "pass" and d["alerts_auth"] == "pass"
    assert [i["url"] for i in d["alerts_items"]] == ["https://citynews.example.org/bakery?id=7",
                                                     "https://blog.example.net/2026/09/review"]
    assert all("utm_" not in u and "google." not in u for u in d["links"]) and d["links"]


def test_connector_letter_forged_alerts_dropped_on_both_roads():
    forged = _gmail_json("alerts-forged.eml")
    forged["payload"]["headers"].insert(0, {"name": "Received", "value": "from evil.example by mx.google.com"})
    code, o = run("letter", inp=json.dumps({"messages": [forged]}))
    d = o["letters"][0]
    assert d["sender_auth"] == "fail" and d["alerts_auth"] == "unsigned"
    assert d["alerts_items"] == [] and d["links"] == [] and o["looks_forged"] == 1
    assert "обман" in d["say"]
    # the raw source passed as a file: the same verdict
    f = os.path.join(tempfile.mkdtemp(), "letter.eml")
    open(f, "wb").write(b"Received: from evil.example by mx.google.com\r\n" + raw("alerts-forged.eml"))
    code, o = run("letter", "--file", f)
    assert o["letters"][0]["sender_auth"] == "fail" and o["letters"][0]["alerts_items"] == []


def test_connector_letter_without_headers_is_not_checked_and_gives_no_links():
    body = "Google Alerts\nAnna Petrova opens a bakery\n<https://www.google.com/url?url=https://citynews.example.org/bakery%3Futm_source%3Dx>"
    code, o = run("letter", inp=body)
    d = o["letters"][0]
    assert d["sender_auth"] == "unverified" and d["links"] == [] and o["not_checked"] == 1
    assert "не проверено" in d["say"]
    # JSON with only from/subject/snippet (no headers): also not checked, even "from Google Alerts"
    code, o = run("letter", inp=json.dumps({"from": "Google Alerts <googlealerts-noreply@google.com>",
                                             "subject": "Alert", "snippet": body}))
    d = o["letters"][0]
    assert d["google_alerts"] and d["sender_auth"] == "unverified" and d["alerts_auth"] == "unverified"
    assert d["alerts_items"] == [] and d["links"] == []


def test_sender_check_for_any_letter():
    import email as em
    import email.policy as ep
    ok = (b"Authentication-Results: mx.google.com; dkim=pass header.i=@shop.example.com; "
          b"dmarc=pass (p=NONE) header.from=shop.example.com\r\nFrom: Shop <news@shop.example.com>\r\n"
          b"Subject: hi\r\n\r\nsee https://shop.example.com/a?utm_source=x\r\n")
    d = mc.check_letter(ok)
    assert d["sender_auth"] == "pass" and d["links"] == ["https://shop.example.com/a"]
    spoof = ok.replace(b"From: Shop <news@shop.example.com>", b"From: Bank <help@bank.example>")
    assert mc.check_letter(spoof)["sender_auth"] == "fail" and mc.check_letter(spoof)["links"] == []
    fake_top = b"Authentication-Results: evil.example; dmarc=pass header.from=bank.example\r\nFrom: <a@bank.example>\r\n\r\nx"
    assert mc.sender_verdict(em.message_from_bytes(fake_top, policy=ep.default)) == "fail"


# ------------------------------------------------------------------ the wire whitelist

def test_whitelist():
    ok = [("CAPABILITY", ()), ("LOGIN", ("a@b.c", '"pw"')), ("EXAMINE", ('"INBOX"',)), ("LOGOUT", ()),
          ("UID", ("SEARCH", "SINCE", "29-Sep-2026")),
          ("UID", ("SEARCH", "SINCE", "29-Sep-2026", "FROM", '"googlealerts-noreply@google.com"')),
          ("UID", ("FETCH", "1,2", "(UID FLAGS)")), ("UID", ("FETCH", "7", "(UID BODY.PEEK[]<0.262144>)"))]
    for name, args in ok:
        assert mc.check_command(name, args)[0], (name, args)
    bad = [("SELECT", ('"INBOX"',)), ("STORE", ("1", "+FLAGS", "(\\Seen)")), ("UID", ("STORE", "1", "+FLAGS", "(\\Deleted)")),
           ("UID", ("FETCH", "1", "(BODY[])")), ("UID", ("FETCH", "1", "(RFC822)")), ("UID", ("FETCH", "1", "(RFC822.TEXT)")),
           ("EXPUNGE", ()), ("APPEND", ("INBOX",)), ("UID", ("MOVE", "1", "Trash")), ("UID", ("COPY", "1", "X")),
           ("IDLE", ()), ("DELETE", ("INBOX",)), ("LOGIN", ("a", "pw\r\nA1 STORE 1 +FLAGS (\\Seen)"))]
    for name, args in bad:
        assert not mc.check_command(name, args)[0], (name, args)


# ------------------------------------------------------------------ a fake IMAP server

class FakeServer:
    def __init__(self, letters, read_only=True, marks_seen=False):
        self.letters = letters            # {uid: raw bytes}
        self.flags = {u: "" for u in letters}
        self.read_only, self.marks_seen = read_only, marks_seen
        self.seen_cmds = []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        c, _ = self.sock.accept()
        f = c.makefile("rb")
        c.sendall(b"* OK fake IMAP ready\r\n")
        while True:
            line = f.readline()
            if not line:
                break
            line = line.decode().rstrip("\r\n")
            tag, _, rest = line.partition(" ")
            self.seen_cmds.append(rest)
            up = rest.upper()
            send = c.sendall
            if up == "CAPABILITY":
                send(b"* CAPABILITY IMAP4rev1\r\n%s OK done\r\n" % tag.encode())
            elif up.startswith("LOGIN"):
                send(b"%s OK logged in\r\n" % tag.encode())
            elif up.startswith("EXAMINE") or up.startswith("SELECT"):
                code = b"[READ-ONLY]" if (up.startswith("EXAMINE") and self.read_only) else b"[READ-WRITE]"
                send(b"* %d EXISTS\r\n%s OK %s done\r\n" % (len(self.letters), tag.encode(), code))
            elif up.startswith("UID SEARCH"):
                send(b"* SEARCH %s\r\n%s OK done\r\n" % (" ".join(self.letters).encode(), tag.encode()))
            elif up.startswith("UID FETCH"):
                parts_ = rest.split(" ", 3)
                uids, items = parts_[2].split(","), parts_[3]
                for i, u in enumerate(uids, 1):
                    if "BODY.PEEK" in items.upper():
                        body = self.letters[u]
                        send(b"* %d FETCH (UID %s BODY[]<0> {%d}\r\n" % (i, u.encode(), len(body)) + body + b")\r\n")
                        if self.marks_seen:
                            self.flags[u] = "\\Seen"
                    else:
                        send(b"* %d FETCH (UID %s FLAGS (%s))\r\n" % (i, u.encode(), self.flags[u].encode()))
                send(b"%s OK done\r\n" % tag.encode())
            elif up == "LOGOUT":
                send(b"* BYE\r\n%s OK bye\r\n" % tag.encode())
                break
            else:
                send(b"%s BAD no\r\n" % tag.encode())
        c.close()


class Plain(mc.Guard, imaplib.IMAP4):
    pass


def session(server):
    conn = Plain("127.0.0.1", server.port)
    mc.open_readonly(conn, "person@example.com", "app-pass")
    return conn


def test_fake_imap_reads_and_touches_nothing():
    srv = FakeServer({"1": raw("from-person.eml"), "2": raw("alerts-real.eml")})
    conn = session(srv)
    letters, changed = mc.fetch_letters(conn, days=1)
    conn.logout()
    assert changed == [] and len(letters) == 2 and all(x["unread"] for x in letters)
    assert letters[1]["google_alerts"] and len(letters[1]["alerts_items"]) == 2
    cmds = " | ".join(srv.seen_cmds).upper()
    assert "EXAMINE" in cmds and "SELECT" not in cmds and "STORE" not in cmds
    assert "BODY.PEEK[]" in cmds and "BODY[]" not in cmds.replace("BODY.PEEK[]", "")


def test_fake_imap_server_that_marks_seen_is_reported():
    srv = FakeServer({"5": raw("newsletter.eml")}, marks_seen=True)
    conn = session(srv)
    _, changed = mc.fetch_letters(conn, days=1)
    conn.logout()
    assert changed == ["5"]


def test_fake_imap_without_read_only_stops_before_letters():
    srv = FakeServer({"1": raw("from-person.eml")}, read_only=False)
    conn = Plain("127.0.0.1", srv.port)
    try:
        mc.open_readonly(conn, "person@example.com", "app-pass")
        assert False, "must refuse"
    except mc.Refused:
        pass
    conn.logout()
    assert not any("FETCH" in c.upper() for c in srv.seen_cmds)


def test_guard_refuses_before_writing():
    srv = FakeServer({"1": raw("from-person.eml")})
    conn = session(srv)
    for bad in (lambda: conn.store("1", "+FLAGS", "(\\Seen)"), lambda: conn.uid("STORE", "1", "+FLAGS", "(\\Deleted)"),
                lambda: conn.uid("FETCH", "1", "(BODY[])"), lambda: conn.expunge(), lambda: conn.select("INBOX")):
        try:
            bad()
            assert False, "must refuse"
        except mc.Refused:
            pass
    conn.logout()
    assert not any(w in " ".join(srv.seen_cmds).upper() for w in ("STORE", "SELECT", "EXPUNGE"))


# ------------------------------------------------------------------ no password anywhere

def test_no_password_no_socket_and_store_commands():
    code, o = run("check", "--user", "nobody-mailcall-test@example.com")
    assert code == 1 and o["code"] == "no-password" and o.get("store")
    for sysname in ("Darwin", "Linux", "Windows"):
        mc.platform.system = lambda s=sysname: s
        c = mc.store_commands("a@b.c")
        assert "a@b.c" in c["store"] and c["forget"]
        assert "pw" not in c["store"].split("a@b.c")[-1]   # the system asks; nothing typed after the address
    mc.platform.system = __import__("platform").system


def test_words_and_config():
    h = tempfile.mkdtemp()
    env = {"MAILCALL_HOME": h}
    e = dict(os.environ, **env)
    def r(*a):
        p = subprocess.run([sys.executable, SCRIPT, *a], capture_output=True, text=True, env=e)
        return json.loads(p.stdout)
    assert r("words", "add", "Анна Петрова", "пекарня Колос")["words"][0]["alerts_phrase"] == '"Анна Петрова"'
    assert len(r("words", "remove", "пекарня Колос")["words"]) == 1
    assert r("config", "set", "--user", "me@gmail.com")["config"]["host"] == "imap.gmail.com"
    for name in os.listdir(h):
        assert "pass" not in open(os.path.join(h, name), encoding="utf-8").read().lower()


def test_plugin_files():
    for p in (".claude-plugin/plugin.json", ".claude-plugin/marketplace.json"):
        json.load(open(os.path.join(ROOT, p), encoding="utf-8"))
    for s in ("setup", "digest", "watch"):
        t = open(os.path.join(ROOT, "skills", s, "SKILL.md"), encoding="utf-8").read()
        assert t.startswith("---\nname: %s\n" % s)
        assert "send" in t.lower()   # every skill carries the "never send" rule


if __name__ == "__main__":
    fails = 0
    for k, v in sorted(globals().items()):
        if k.startswith("test_") and callable(v):
            try:
                v()
                print("ok  ", k)
            except Exception as ex:  # noqa: BLE001
                fails += 1
                print("FAIL", k, repr(ex))
    sys.exit(1 if fails else 0)
