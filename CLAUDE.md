# Apex Siri Shortcuts

Siri Shortcuts that control a Neptune Apex aquarium controller by replaying its local
dashboard's HTTP requests. `tools/build_shortcuts.py` generates and signs them. This is
a public repo, shared with reef hobbyists.

## The live tank

A real Apex runs a live tank: any request other than a GET switches equipment that
keeps animals alive.

- Prove changes on `tools/mock_apex.py` first, then ask the user before anything writes
  to a real Apex. That includes `shortcuts run` on any shortcut other than "Apex Mock Test".
- Apex passwords stay with the user: they type them into their own terminal (`getpass`)
  or Shortcuts' import questions. Scripts that log in report redacted shapes (types,
  lengths), never values.

## Where things are

- Changing what a shortcut does (a new or changed command, the plist format, the mock):
  follow [docs/developing.md](docs/developing.md).
- What the Apex accepts and returns, verified or untested:
  [docs/apex-local-api.md](docs/apex-local-api.md). Record new findings there.

## Conventions

- Standard library only.
- Everything committed is public. Personal details (addresses, usernames, the tested
  tank's equipment) go in `CLAUDE.local.md`, which is gitignored.
