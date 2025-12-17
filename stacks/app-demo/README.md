# app-demo stack

This folder contains configuration for the `app-demo` stack.

## Setup

1. Copy `.env.example` to `.env`.
2. Fill in `APPHOST_TOKEN` (leave it empty if you do not need authentication).

## Variables

- `APP_DEMO_HTTP_PORT`: Host port the app-demo stack should expose.
- `APPHOST_TOKEN`: Optional token for the app host (do not commit).
- `APPHOST_REPO_URL`: Git repo URL to build/deploy from.
- `APPHOST_REF`: Git ref (branch/tag) to build from.
- `APPHOST_INSTALL_COMMAND`: Install command (e.g. `npm ci`).
- `APPHOST_BUILD_COMMAND`: Build command (e.g. `npm run build`).
- `APPHOST_OUTPUT_DIR`: Build output directory (e.g. `dist`).
- `APPHOST_RELEASES_TO_KEEP`: How many releases to keep.
