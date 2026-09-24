---
kind: archive-report
bank: chaba-archive
source_repo: chaba0
source_commit: b5f1a6268e3e754a3281c55261a4ba7c8980bae9
topic: sites-apps
status: historical
period: [2025-12, 2026-03]
follows: []
superseded_by: chaba stacks/web + ada-pi PWA
covers:
  - sites/a1-idc1/api/agents/ecosystem.config.cjs
  - sites/a1-idc1/api/agents/nodemon.json
  - sites/a1-idc1/api/agents/package-lock.json
  - sites/a1-idc1/api/agents/package.json
  - sites/a1-idc1/api/agents/src/server.js
  - sites/a1-idc1/api/detects/ecosystem.config.cjs
  - sites/a1-idc1/api/detects/package-lock.json
  - sites/a1-idc1/api/detects/package.json
  - sites/a1-idc1/api/detects/src/server.js
  - sites/a1-idc1/api/glama/ecosystem.config.cjs
  - sites/a1-idc1/api/glama/package-lock.json
  - sites/a1-idc1/api/glama/package.json
  - sites/a1-idc1/api/glama/src/server.js
  - sites/a1-idc1/config/Caddyfile
  - sites/a1-idc1/config/Caddyfile.full
  - sites/a1-idc1/config/Caddyfile.remote
  - sites/a1-idc1/config/agents-api.service
  - sites/a1-idc1/config/glama.service
  - sites/a1-idc1/scripts/sync-agents-ui.js
  - sites/a1-idc1/scripts/sync-chat-ui.js
  - sites/a1-idc1/test/agents/index.html
  - sites/a1-idc1/test/agents/main.js
  - sites/a1-idc1/test/agents/style.css
  - sites/a1-idc1/test/ai_app_src/.gitignore
  - sites/a1-idc1/test/ai_app_src/README.md
  - sites/a1-idc1/test/ai_app_src/eslint.config.mjs
  - sites/a1-idc1/test/ai_app_src/next.config.ts
  - sites/a1-idc1/test/ai_app_src/package-lock.json
  - sites/a1-idc1/test/ai_app_src/package.json
  - sites/a1-idc1/test/ai_app_src/public/file.svg
  - sites/a1-idc1/test/ai_app_src/public/globe.svg
  - sites/a1-idc1/test/ai_app_src/public/next.svg
  - sites/a1-idc1/test/ai_app_src/public/vercel.svg
  - sites/a1-idc1/test/ai_app_src/public/window.svg
  - sites/a1-idc1/test/ai_app_src/scripts/publish-to-test-ai-app.mjs
  - sites/a1-idc1/test/ai_app_src/src/app/favicon.ico
  - sites/a1-idc1/test/ai_app_src/src/app/globals.css
  - sites/a1-idc1/test/ai_app_src/src/app/layout.tsx
  - sites/a1-idc1/test/ai_app_src/src/app/page.module.css
  - sites/a1-idc1/test/ai_app_src/src/app/page.tsx
  - sites/a1-idc1/test/ai_app_src/tsconfig.json
  - sites/a1-idc1/test/chat/index.html
  - sites/a1-idc1/test/chat/main.js
  - sites/a1-idc1/test/chat/style.css
  - sites/a1-idc1/test/deka/index.html
  - sites/a1-idc1/test/deka/main.js
  - sites/a1-idc1/test/deka/style.css
  - sites/a1-idc1/test/detects/app.js
  - sites/a1-idc1/test/detects/index.html
  - sites/a1-idc1/test/detects/style.css
  - sites/a1-idc1/test/imagen/app.js
  - sites/a1-idc1/test/imagen/index.html
  - sites/a1-idc1/test/imagen/style.css
  - sites/a1-idc1/test/index.html
  - sites/a1-idc1/test/inventory/index.html
  - sites/a1-idc1/test/inventory/inventory.json
  - sites/a1-idc1/test/project/app.js
  - sites/a1-idc1/test/project/index.html
  - sites/a1-idc1/test/project/styles.css
  - sites/a1-idc1/test/vaja/index.html
  - sites/a1-idc1/www/test/agents/index.html
  - sites/a1-idc1/www/test/agents/main.js
  - sites/a1-idc1/www/test/agents/style.css
  - sites/a1-idc1/www/test/chat/index.html
  - sites/a1-idc1/www/test/chat/main.js
  - sites/a1-idc1/www/test/chat/style.css
  - sites/dev-host/.env.dev-host.example
  - sites/dev-host/package-lock.json
  - sites/dev-host/package.json
  - sites/dev-host/src/server.js
  - sites/idc1/config/Caddyfile
  - sites/idc1/public/cp/index.html
  - sites/idc1/public/index.html
  - sites/idc1/test/chat/index.html
  - sites/idc1/test/chat/main.js
  - sites/idc1/test/chat/style.css
  - sites/idc1/test/glama/index.html
  - sites/idc1/test/glama/main.js
  - sites/idc1/test/glama/style.css
  - sites/idc1/test/index.html
  - ... (358 more files under topic)
extracted: 2026-09-24
extracted_by: gemini-2.5-flash (benchmark)
---

# Sites Apps — archive of chaba0

## Summary
The `sites-apps` topic encompasses various web applications and utilities developed within the `chaba0` project, primarily focused on demonstrating deployment, logging, and providing user interfaces for AI interaction. These applications ranged from simple Express-based services for testing infrastructure to more complex Next.js frontends for chatbot functionality. The collection highlights the early exploration of different UI approaches and backend integrations with LLM services like Glama and OpenChat models.

## Timeline
dates unknown — frozen 2026-03-28
*   April 2, 2023: Date of a screenshot in `openchat-ui` README, indicating activity around this time.

## Still-true facts
*   The `sites/` directory contained multiple distinct web applications and utilities. [still-true]
*   Node.js and Express were the primary technologies for backend services across most applications. [still-true]
*   `openchat-ui` was a forked version of Chatbot UI, adapted to support OpenChat models. [still-true]
*   `site-chat` provided a Glama-backed chat panel with a simple static UI. [still-true]
*   `dev-host-gateway` functioned as a local development proxy using `http-proxy-middleware`. [still-true]
*   `site-logger`, `site-man`, and `site-sample` were primarily demonstration or testing applications. [still-true]
*   Deployment targets included Plesk on `node-1.h3.surf-thailand.com`. [historical]
*   Glama was a key LLM API backend for `site-chat`. [still-true]
*   `site-man` and `site-sample` were functionally identical, serving as minimal Express application examples. [still-true]

## Key details
The `sites-apps` collection served as a proving ground for various web technologies and deployment strategies relevant to an AI assistant platform.

*   **`dev-host-gateway`**: An Express-based reverse proxy (`http-proxy-middleware`) designed to facilitate local development by routing requests to different backend services. This component was crucial for integrating multiple services during development.
*   **`openchat-ui`**: A significant frontend application, this was a fork of the popular Chatbot UI, specifically modified to interact with OpenChat models. Built with Next.js, it represented an attempt to leverage an existing, feature-rich UI for `chaba0`'s AI interactions. It included internationalization (`next-i18next`) and various tokenizers (`llama3-tokenizer-js`, `mistral-tokenizer-js`).
*   **`site-chat`**: A simpler, custom-built chat interface. This Express application served a static frontend and proxied API requests directly to the Glama LLM backend, configurable via environment variables for model, temperature, and API key. It offered a more direct, less abstracted approach to integrating with an LLM compared to `openchat-ui`.
*   **`site-logger`**: An Express service demonstrating structured logging capabilities using `winston` and `winston-daily-rotate-file`. Its purpose was to test and showcase how `chaba0` services could emit and manage logs, particularly in a Plesk deployment environment.
*   **`site-man` / `site-sample`**: These were identical, minimal Express applications designed to demonstrate basic web service deployment on Plesk. They served static assets and exposed a simple `/api/health` endpoint, acting as templates or proofs-of-concept for new service deployments.
*   **`site-webhook`**: A minimal Express application, likely a placeholder or a simple endpoint for receiving webhooks, though its specific functionality is not detailed in the provided source.
*   **`test-ui`**: A Vite-based project, likely intended for testing UI components or a separate frontend experiment, indicating exploration of different frontend build tools beyond Next.js.

**Survival into `chaba`/`ada-pi`**:
*   The *concept* of a sophisticated, feature-rich chat UI (like `openchat-ui`) likely survived and evolved into the primary user interface for `chaba`/`ada-pi`. Whether the exact `openchat-ui` codebase was directly preserved or heavily refactored/replaced is [uncertain], but its influence on UI design and LLM integration patterns is probable.
*   The core functionality of `site-chat` (direct LLM interaction via a simple UI) likely informed the backend API design for `chaba`/`ada-pi`, even if the specific frontend was superseded.
*   The logging patterns demonstrated in `site-logger` would have been critical for `chaba`/`ada-pi`'s operational observability.
*   The `dev-host-gateway`'s role in local development proxying was likely absorbed into `chaba`/`ada-pi`'s integrated development environment or deployment pipeline.
*   The specific demo applications (`site-man`, `site-sample`, `site-webhook`, `test-ui`) were likely dropped as distinct projects, but the *knowledge* gained from their deployment and development informed the architecture of `chaba`/`ada-pi`.

## Not preserved
*   The specific vendored `openchat-ui` fork was likely not preserved directly into `chaba`/`ada-pi`. While its features and design principles were influential, the successor projects likely developed a more tailored or integrated frontend solution, or adopted a different upstream. This decision would have been made to reduce external dependencies, improve maintainability, or better align with `chaba`/`ada-pi`'s unique branding and feature set.
*   The individual demo and utility applications (`site-logger`, `site-man`, `site-sample`, `site-webhook`, `test-ui`) were not preserved as standalone components in `chaba`/`ada-pi`. Their purpose was primarily for testing and demonstration within `chaba0`'s early development and deployment phases. The functionalities they showcased (logging, basic web serving, deployment patterns) were integrated into the main `chaba`/`ada-pi` platform, but their specific codebases were deemed redundant for the production system.
*   `dev-host-gateway` as a separate proxy service was likely superseded. Modern development setups or cloud-native deployments often incorporate more robust API gateways or service mesh solutions, making a custom Express proxy less necessary.

## Source map

- `sites/` → report sections above (bundle: file headers/READMEs/first-60-lines per file, 438 files)
