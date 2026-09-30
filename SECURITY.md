# Security

## What Mailcall touches

- **Connector road:** the Gmail connector the person switched on in their Claude account. The
  skills use only search and read tools; they never call a send, reply, forward, trash, label,
  spam or filter tool. A Gmail draft is created only after the person's explicit «да» to that.
- **IMAP road:** one TLS connection to the person's mail server, opened read-only (`EXAMINE`,
  `[READ-ONLY]` confirmed), with a whitelist of commands enforced in code before anything is sent.
- **The app password** is read from the operating system's credential store (macOS Keychain,
  Windows Credential Manager, Linux Secret Service) at the moment of the call and kept only in
  memory. The person puts it there with the system's own command, which prompts for it.
- **Files:** `~/.mailcall/config.json` (address, server, road) and `~/.mailcall/watch.json` (the
  words). Summaries are written in the folder the person works in and carry who / when / subject /
  what is asked, not letter bodies. Letters fetched over IMAP go to stdout only.

## What it never does

- Never asks for, stores or writes a password, key or card number.
- Never sends, deletes, moves, labels or marks a letter as read.
- Never follows an instruction written inside a letter; never opens a link from a letter.
- Never uses a paid API.

## Reporting

Open an issue, or write to the author through the Poly A1 support address.
