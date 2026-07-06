# Contributing to Cairn

Thanks for helping keep fleets honest. Cairn is free and open source under the
**AGPL-3.0-or-later** license, and contributions are welcome — bug reports, new
source/sink/notifier connectors, docs, and tests.

## Ground rules

- Be respectful. This project follows the [Code of Conduct](CODE_OF_CONDUCT.md).
- By contributing, you agree your work is licensed under **AGPL-3.0-or-later**,
  the same license as the project.
- Keep changes surgical and focused. One logical change per pull request.

## Development setup

```bash
git clone https://github.com/jsdosanj/cairn.git
cd cairn
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                       # the suite is fast and fully offline
```

Provider tests mock the upstream APIs with `responses`, so you never need live
credentials to run them.

## Making a change

1. Branch from `main`.
2. Make the change. Match the existing style (type hints, small modules,
   `logging` over `print`).
3. Add or update tests — every source/sink/notifier has a test module under
   [`tests/`](tests/). New connectors must ship with one.
4. Run `pytest` and make sure everything passes.
5. Update the relevant page under [`docs/`](docs/) and `CHANGELOG.md`.
6. Open a pull request describing the change and how you verified it.

## Adding a source connector

Cairn is built so a new MDM/EDR is one file:

1. Add `src/cairn/sources/<name>.py` implementing
   `DeviceSource.fetch_all()` (and, optionally, a server-side
   `find_by_serial`).
2. Register it with one line in `src/cairn/registry.py`.
3. Add `tests/test_<name>.py` mocking the upstream API.
4. Document it in [`docs/sources.md`](docs/sources.md).

The core never changes. See [`docs/sources.md`](docs/sources.md) and an existing
connector (e.g. `jamf.py`) for the shape.

## Security

Never commit real credentials, config files, or `state.json`. The
`.gitignore` already excludes `config.yaml` / `settings.conf`. To report a
vulnerability, see [SECURITY.md](SECURITY.md) — please do **not** open a public
issue for security problems.
