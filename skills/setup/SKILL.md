---
name: setup
description: Connect the person's mailbox to Claude and prove it works - the Gmail connector of their Claude subscription first (no password anywhere), or, for any other mailbox or when the connector is not there, read-only IMAP with an app password the person types themselves into the system keychain (Keychain on Mac, Credential Manager on Windows, Secret Service on Linux). Ends by showing, in one line, what Claude now really sees, and how to take the access back. Use when the person says "connect my email", "read my inbox", "set up mailcall" (or the equivalent in whatever language they are using), or before the first /mailcall:digest or /mailcall:watch.
argument-hint: "[your mailbox address]"
allowed-tools: Bash(sh "${CLAUDE_PLUGIN_ROOT}/hooks/python.sh" mailcall say scripts/*) PowerShell(& "${CLAUDE_PLUGIN_ROOT}/hooks/python.ps1" mailcall say scripts/*) Bash(date*) ToolSearch Read Write
---

# Mailcall: connect the mailbox

## Running mailcall's scripts (Mac, Linux, Windows)

Every script command on this page is written for the **Bash** tool and starts with
`sh "${CLAUDE_PLUGIN_ROOT}/hooks/python.sh" mailcall say scripts/…`. If your shell tool is **PowerShell** (Windows
without Git Bash), run the same command with only its start changed: `& "${CLAUDE_PLUGIN_ROOT}/hooks/python.ps1"`
in place of `sh "${CLAUDE_PLUGIN_ROOT}/hooks/python.sh"`, everything after it unchanged, on one line; text for
standard input goes in as `@'…'@ | & "${CLAUDE_PLUGIN_ROOT}/hooks/python.ps1" …` instead of `<<'EOF'`.
Never call `python3`, `python` or `py` yourself: the launcher finds a real Python 3.8+ (`python`,
then `py -3`, then `python3`) and never starts the Microsoft Store or Apple stub. If it answers
with one line saying mailcall "is paused" because this computer has no working Python 3 yet, tell the
person that in one plain line and go on by hand — never show them a Python error and stop.

The person said: $ARGUMENTS

Answer in the person's language, as to someone who is at a computer for the first time. One action,
then wait for their answer. The person signs in and types passwords; you never ask for a password,
never see one, never write one anywhere.

The script: `sh "${CLAUDE_PLUGIN_ROOT}/hooks/python.sh" mailcall say scripts/mailcall.py` —
below it is called `mailcall`.

## 1. Which mailbox, which road

Ask for the address if it is not in the argument. Then choose the road and say it in one line:

- **Gmail (…@gmail.com or a Google Workspace address) → the connector.** Nothing to install, no
  password. Go to step 2.
- **Any other mailbox** (Yandex, Mail.ru, iCloud, Yahoo, a company mail…), or Gmail when the
  connector cannot be switched on → **IMAP, read-only.** Go to step 3.
- **The person does not want mail connected at all** but wants the Google Alerts digest → the
  **feed** road of `/mailcall:watch` (Alerts delivered as a feed, no mailbox access). Say it exists.

## 2. The connector road (Gmail)

1. Check whether the Gmail tools are already here: `ToolSearch` with the query `gmail`. Tools whose
   names start with `mcp__claude_ai_Gmail__` and can search and read (search, get thread, get
   message) mean the connector is on. If only an `authenticate` tool is there, call it and give the
   person the link it returns; they sign in with Google in their browser themselves.
2. If there are no Gmail tools at all, say where the switch really lives: **claude.ai → Settings →
   Connectors → Gmail → Connect** (the same account Claude Code is signed in with; in the Claude
   desktop app it is the same place). The person does it; then they restart this Claude Code window
   and type `/mailcall:setup` again.
3. Say before the Google screen appears what it will say: the permission is for the whole mailbox,
   not one folder. Mailcall's rule is on top of that: **read only**. Nothing is sent, deleted,
   archived, labelled or marked read by you, today or later.
4. Prove it: search the last 24 hours and say in ONE line what you now really see — "I see your
   mailbox: 23 letters in the last day, 9 unread, 2 Google Alerts letters." Nothing from the
   letters themselves in this line.
5. Save the road: `mailcall config set --user <address> --road connector`.

## 3. The IMAP road (any mailbox), read-only by the protocol

1. `mailcall config set --user <address> --road imap` — the server is guessed from the address;
   if it is a company mail, ask for the IMAP server name and add `--host <server>`.
2. `mailcall where --user <address>` — gives the page where the **app password** is made
   (`app_password_page`) and the exact command for this computer (`store`).
3. Walk the person through it, one step at a time:
   - Open the app-password page, sign in, make a password named `mailcall`. Gmail makes app
     passwords only when 2-Step Verification is on — if the page says it is not available, the
     person turns 2-Step Verification on first (same account page, "Security").
   - Open their own terminal (Mac: Terminal; Windows: PowerShell; Linux: any terminal) — **not
     this chat** — paste the `store` command, press Enter; the system itself asks for the password;
     they paste the app password there. It goes into the system keychain, not into any file, and
     nothing of it passes through this conversation.
   - If the person pasted the password into this chat by mistake: say so plainly, ask them to
     delete that app password on the same page and make a new one. Do not use the pasted one.
4. Prove it: `mailcall check --user <address>`. It signs in, opens the inbox **read-only**
   (the server must confirm it, otherwise it stops), counts the last day's letters and checks that
   not one of them turned "read". Say the result in one line, as above.
   - `no-password` → the store step did not happen; repeat it.
   - `login-refused` → the app password is wrong or IMAP is off in the mailbox settings (Yandex,
     Mail.ru: the "Mail clients" setting → allow IMAP). Make a new app password.
   - `connect-failed` → the server name is wrong; ask for it.

## 4. Close

Tell the person three things, short:

- What Claude now sees (the line from step 2.4 or 3.4).
- The rule: **I only read. Replies are drafts; you send them yourself.** Offer to write this rule
  into the folder's `CLAUDE.md`: "Mail: read-only. Drafts yes, sending only by the person."

Reply to the person in their own language even though this file is in English.
- How to take the access back, in both places:
  - connector: claude.ai → Settings → Connectors → Gmail → Disconnect, **and**
    https://myaccount.google.com/connections (remove Claude there too);
  - IMAP: delete the app password on the page where it was made, **and** run the `forget` command
    from `mailcall where`.

Next: `/mailcall:digest` for the morning summary, `/mailcall:watch` for the words to watch.
