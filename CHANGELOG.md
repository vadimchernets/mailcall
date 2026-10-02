# Changelog

## 0.1.3 — 2026-10-02

- Language check: `scripts/check_language.py` (run by `tests/test_check_language.py`) fails if Cyrillic
  appears outside a language place (`ru/`, `uk/` folders, `README.ru.md`, `lang/ru.json`, `lang/uk.json`),
  in file names or text. Controls plant Cyrillic in a code comment, a file name, a JSON key and Markdown.

## 0.1.2 — 2026-10-02

- Project language is English: comments, skill instructions, docs and default messages translated; skills tell Claude to reply in the person's language.
