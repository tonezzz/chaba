# Justfile for chaba (tony-omen) orchestration

_default:
    @just --list

# Regenerate Frigate config and camera map from cameras.json
regenerate-cameras:
    python3 frigate/generate_config.py

# Copy generated camera map to the web server public directory
sync-camera-map:
    cp frigate/camera-map.html stacks/web/public/camera-map.html

# Regenerate and copy camera map in one step
rebuild-cameras: regenerate-cameras sync-camera-map

# Restart the Caddy web Docker stack
restart-web:
    docker compose -f stacks/web/docker-compose.yml restart

# Follow Caddy web container logs
web-logs:
    docker logs web -f

# Restart the Frigate NVR stack
restart-frigate:
    docker compose -f frigate/docker-compose.yml restart

# Build the legacy Reef Riders static mirror
build-reefriders:
    python3 scripts/reefriders/build.py

# Check llama-server health
llama-status:
    curl -s http://localhost:8008/health

# Show running Docker containers
docker-ps:
    docker ps --format 'table {{"{{"}}.Names{{"}}"}}\t{{"{{"}}.Status{{"}}"}}\t{{"{{"}}.Ports{{"}}"}}'
