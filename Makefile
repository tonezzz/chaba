.RECIPEPREFIX = >

.PHONY: ai-up ai-down ai-build ai-3dgs nvr-up nvr-down nvr-regenerate nvr-restart web-up web-down sync status llama-up llama-down llama-logs llama-status

ai-up:
> docker compose -f stacks/ai/docker-compose.yml up -d

ai-down:
> docker compose -f stacks/ai/docker-compose.yml down

ai-build:
> docker compose -f stacks/ai/docker-compose.yml build

ai-3dgs:
> docker compose -f stacks/ai/docker-compose.yml run --rm 3dgs bash

nvr-up:
> docker compose -f stacks/nvr/docker-compose.yml up -d

nvr-down:
> docker compose -f stacks/nvr/docker-compose.yml down

nvr-regenerate:
> python3 stacks/nvr/generate_config.py

nvr-restart:
> docker compose -f stacks/nvr/docker-compose.yml restart

web-up:
> docker compose -f stacks/web/docker-compose.yml up -d

web-down:
> docker compose -f stacks/web/docker-compose.yml down

sync:
> cp stacks/nvr/generated/camera-map.html stacks/web/public/camera-map.html

status:
> docker compose -f stacks/ai/docker-compose.yml ps
> docker compose -f stacks/nvr/docker-compose.yml ps
> docker compose -f stacks/web/docker-compose.yml ps

llama-up:
> @mkdir -p data/models
> docker compose -f stacks/ai/docker-compose.yml up -d llama-server

llama-down:
> docker compose -f stacks/ai/docker-compose.yml stop llama-server

llama-logs:
> docker compose -f stacks/ai/docker-compose.yml logs -f llama-server

llama-status:
> @curl -fsS http://localhost:8008/health || true
