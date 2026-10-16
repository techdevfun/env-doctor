# Contributing

Small, focused PRs are welcome.

1. Fork, create a branch, make your change.
2. Add or update a test in `tests/` when you change audit logic.
3. Run `python -m pytest -q` — it must pass.
4. Keep the tool dependency-free (stdlib only). No new dependencies without discussion.

Please do not commit real secrets in tests or examples. Use obvious fake values.
