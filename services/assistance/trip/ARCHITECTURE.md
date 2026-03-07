# TRIP Service (Architecture)

## What it is
TRIP application container/service (itskovacs/TRIP).

## Container image
- `ghcr.io/itskovacs/trip:1`

## Runtime expectations
- Listens on port `8000` inside the container.

## Persistence
- TRIP persistent storage must be mounted to `/app/storage`.

## Networking
- Default: internal-only service access from Jarvis backend (no public ingress unless explicitly required).
- In the `idc1-assistance` stack, TRIP is reachable from other containers at `http://trip:8000`.
- For initial testing, TRIP may be exposed on localhost only (e.g. `127.0.0.1:18081 -> 8000`).

## Auth
- Prefer TRIP API token auth (`X-Api-Token`) for Jarvis-to-TRIP calls.
