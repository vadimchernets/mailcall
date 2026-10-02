# Changelog

## 0.1.6 — 2026-10-02

- Skills run their scripts through the step-0 launcher, on every system: the Bash tool runs
  `sh "${CLAUDE_PLUGIN_ROOT}/hooks/python.sh" mailcall say scripts/<name>.py ...`, the PowerShell tool (Windows without
  Git Bash) the same line starting with the bare path `${CLAUDE_PLUGIN_ROOT}/hooks/python.ps1`. No skill calls `python3`
  any more (on Windows it is often missing or the Microsoft Store stub). The launcher takes a Python only once `-c`
  proves 3.8+, tries `python`, `py -3`, `python3` on Windows, never starts the Store or Apple stub, and with no Python
  says one step-0 line. Scripts are passed relative to the plugin root; text piped in PowerShell reaches the script as
  UTF-8 with no BOM (Windows PowerShell 5.1 wrote one). `allowed-tools` grant both forms, quoted as the command is -
  the old unquoted `Bash(python3 ${CLAUDE_PLUGIN_ROOT}/...)` never matched the quoted commands and always prompted.
  Checked on GitHub Actions on windows-latest, macos-latest and ubuntu-latest, including a real `claude -p` that opens a
  skill and runs its command with no prompt, through Bash and through PowerShell.
- New `hooks/python.sh` and `hooks/python.ps1` (the launcher only; mailcall has no hooks).

## 0.1.5 — 2026-10-02

- README: install from Poly A1's catalogue by its raw link (`/plugin marketplace add https://raw.githubusercontent.com/vadimchernets/poly-a1-plugins/main/.claude-plugin/marketplace.json`,
  then `/plugin install mailcall@poly-a1`) - no git needed; the Poly A1 folder is the way without internet,
  and `marketplace remove` is never the way to switch.

## 0.1.4 — 2026-10-02

- Every release now carries `mailcall-0.1.4.zip` (one top folder `mailcall-0.1.4/`), built by the new
  `scripts/release-zip.sh` and attached by `.github/workflows/release.yml` on each `v*` tag. The Poly A1
  catalogue installs it as an `archive` source with its `sha256`, so installing needs no git: a
  beginner's Linux has none, and on a Mac without Apple's Command Line Tools `git` is the stub that
  opens Apple's install window.

## 0.1.3 — 2026-10-02

- Language check: `scripts/check_language.py` (run by `tests/test_check_language.py`) fails if Cyrillic
  appears outside a language place (`ru/`, `uk/` folders, `README.ru.md`, `lang/ru.json`, `lang/uk.json`),
  in file names or text. Controls plant Cyrillic in a code comment, a file name, a JSON key and Markdown.

## 0.1.2 — 2026-10-02

- Project language is English: comments, skill instructions, docs and default messages translated; skills tell Claude to reply in the person's language.
