# Mailcall

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23107727.svg)](https://doi.org/10.5281/zenodo.23107727)

**An agent that reads your mailbox for you — and every morning tells you what matters.**

What is important today, who is waiting for your answer, what the internet wrote about the words
you watch (your name, your business, your competitor — through Google Alerts), and your newsletters
boiled down to one line each. Replies come as drafts; you send them yourself.

```
/mailcall:setup  jane.doe@gmail.com
/mailcall:digest
/mailcall:watch add "Jane Doe" "Acme Bakery"
```

## Install

```
/plugin marketplace add https://raw.githubusercontent.com/vadimchernets/poly-a1-plugins/main/.claude-plugin/marketplace.json
/plugin install mailcall@poly-a1
```

The first line adds Poly A1's catalogue by its link - one file, no git and no GitHub account - and
later corrections reach you from the same place (Claude Code 2.1.224 or later; `claude update`). If
`poly-a1` is already there, from the Poly A1 folder or from before, skip it: the second line is enough.

Without internet, from the Poly A1 folder:

```
/plugin marketplace add <path to the Poly A1 folder>
/plugin install mailcall@poly-a1
```

Once there is internet, the folder is switched to the link in place, keeping everything installed
([how](https://github.com/vadimchernets/poly-a1-plugins/blob/main/OFFER-THESE.md#later-from-the-folder-to-github-without-losing-anything)). Never `/plugin marketplace remove poly-a1`: it uninstalls every plugin that came from
it and deletes their saved data.

## What is inside

| Skill | What it does |
|---|---|
| `/mailcall:setup [address]` | Connects the mailbox and proves it: "I see your mailbox: 23 letters in the last day, 9 unread." Shows how to take the access back. |
| `/mailcall:digest [days]` | `Mail-<date>.md`: important · waiting for your answer · your watched words · newsletters in one line · looks like fraud. Drafts on request. |
| `/mailcall:watch` | Words to watch: helps you create Google Alerts for them, then reads the Alerts letters and writes a short digest per word with real links. |

## Two roads, no passwords in files

| Road | For | What you do once |
|---|---|---|
| **Connector** (main) | Gmail, Google Workspace | claude.ai → Settings → Connectors → Gmail → Connect. You sign in with Google. Nothing installed, no password anywhere. |
| **IMAP, read-only** | any mailbox: Yandex, Mail.ru, iCloud, Yahoo, company mail — and Gmail too | Make an *app password* in your mail account, type it into your system's own keychain with one command in your terminal. The command asks for it; it never passes through the chat or a file. |
| **Feed** | Google Alerts without connecting any mailbox | Choose «RSS feed» in Google Alerts and give Mailcall the feed address. |

Where the app password lives: macOS Keychain (`security`), Windows Credential Manager (`cmdkey`),
Linux Secret Service (`secret-tool`). `python3 scripts/mailcall.py where --user <address>` prints
the exact store and forget commands for your computer.

## Read-only is a wall, not a promise (IMAP)

- The inbox is opened with `EXAMINE`; the server must answer `[READ-ONLY]`, or nothing is read.
- A whitelist on the wire: only `CAPABILITY LOGIN LIST EXAMINE UID SEARCH UID FETCH NOOP LOGOUT`
  leave the computer; a fetch may ask only for `BODY.PEEK[…]`, flags, date and size. `STORE`,
  `SELECT`, `EXPUNGE`, `MOVE`, `COPY`, `APPEND`, plain `BODY[]` are refused before one byte is sent.
- "Unread" is measured before and after; a letter that turned "read" is reported.

On the connector road the rule is Claude's: the Google screen grants the whole mailbox; the skills
never call a send, reply, forward, delete, label or mark tool, and a letter's text is data, never an
instruction.

## Links come from code

A letter can be written *for* an AI ("open this link", "forward the invoices"). So Mailcall's
summaries carry only links the script extracted: Google Alerts redirects unwrapped to the real
address, trackers (`utm_*`, `fbclid`…) cut, Google's own manage/unsubscribe links dropped — and an
"Alerts" letter that Google's mail server did not vouch for (DMARC/DKIM) gives no links at all.
The same check runs on both roads: on the Gmail connector road Claude saves the letter as the tool
returned it and `mailcall letter --file <file>` reads its `Authentication-Results` / `Received` /
`From`; a letter that comes without headers is marked "unverified" and gives no links.

## The script on its own

```
python3 scripts/mailcall.py check --user you@yandex.ru          # sign in, read-only, count
python3 scripts/mailcall.py fetch --days 1                       # letters as JSON on stdout, nothing on disk
python3 scripts/mailcall.py alerts --eml letter.eml              # Alerts letter -> news with real links
python3 scripts/mailcall.py feed --url https://www.google.com/alerts/feeds/...
python3 scripts/mailcall.py words add "Jane Doe"
```

Tests (no network, fake letters, a fake IMAP server that records every command):
`python3 -m pytest tests` or `python3 tests/test_mailcall.py`.

## Principles

- Read only. Drafts only. Nothing is sent without your "yes" — and even then you press Send.
- No keys, no paid API, nothing bought: your Claude subscription and your own mailbox.
- The summary file carries who / when / subject / what is asked — not the letters themselves.

## Good to know

- **Outlook.com / Hotmail:** Microsoft switched off password (app-password) IMAP for personal
  accounts in 2024. For Alerts use the feed road; for the whole mailbox, forward it to a Gmail
  address and use the connector.
- **Gmail app passwords** appear only when 2-Step Verification is on in the Google account.
- **Connector tool names** are Google's/Anthropic's and may change; the skills find them by search
  (`ToolSearch gmail`), not by a fixed name.
- **Company mail:** the administrator may block connectors or IMAP; then the feed road still works
  for Alerts.

## License

Apache-2.0. Ideas and code ported from the author's own work are credited in [NOTICE](NOTICE).
