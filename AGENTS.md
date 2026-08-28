# Chaba Session Modes

At the start of every session, determine the active operational mode using this precedence:

1. `DEVIN_MODE` environment variable.
2. `~/.config/devin/config.json` → `mode.current`.
3. `.devin/config.local.json` → `mode.current`.
4. `.devin/config.json` → `mode.current`.
5. Default to `normal`.

Then follow the behavior for that mode in `docs/ssot/infrastructure/ssot.devin-modes.yml`.

Valid modes: `normal`, `plan`, `build`, `review`.
