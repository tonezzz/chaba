# Health Check API Endpoints

Auto-generated from SSOT health configuration
Generated: 2026-08-12 20:33:14

## Overview

This document describes all health check endpoints configured in the SSOT health configuration.

## Endpoints

### Caddy

- **ID**: caddy
- **Type**: http
- **URL**: `{profile}/apps/`
- **Expected Status**: 200
- **Timeout**: 5s
- **Category**: web
- **Profiles**: ['home', 'mobile']

### BServer

- **ID**: bserver
- **Type**: http
- **URL**: `{profile}/`
- **Expected Status**: 200
- **Timeout**: 5s
- **Category**: web
- **Profiles**: ['home', 'mobile']

### Raceman Web

- **ID**: raceman-web
- **Type**: http
- **URL**: `http://tony-omen.local:8083/apps/raceman/`
- **Expected Status**: 200
- **Timeout**: 5s
- **Category**: web
- **Profiles**: ['home']

### Raceman PHP

- **ID**: raceman-php
- **Type**: container
- **Container**: raceman-php
- **Expected State**: running
- **Category**: web
- **Profiles**: ['home']

### Yomi API

- **ID**: yomi-api
- **Type**: http
- **URL**: `{profile}/api/yomi/health`
- **Expected Status**: 200
- **Timeout**: 5s
- **Category**: api
- **Profiles**: ['home', 'mobile']

### Yomi Summarization

- **ID**: yomi-summarization
- **Type**: http
- **URL**: `{profile}/api/yomi/summarization-status`
- **Expected Status**: 200
- **Timeout**: 5s
- **Category**: api
- **Profiles**: ['home', 'mobile']

### Yomi Rate Limiter

- **ID**: yomi-rate-limiter
- **Type**: http
- **URL**: `{profile}/api/yomi/rate-limiter-status`
- **Expected Status**: 200
- **Timeout**: 5s
- **Category**: api
- **Profiles**: ['home', 'mobile']

### Yomi Activity Status

- **ID**: yomi-activity-status
- **Type**: http
- **URL**: `{profile}/api/yomi/activity-status`
- **Expected Status**: 200
- **Timeout**: 5s
- **Category**: api
- **Profiles**: ['home', 'mobile']

### Playlived

- **ID**: playlived
- **Type**: http
- **URL**: `http://tony-omen.local:9230/sessions`
- **Expected Status**: 200
- **Timeout**: 5s
- **Category**: api
- **Profiles**: ['home']

### Trade API

- **ID**: trade-api
- **Type**: http
- **URL**: `http://localhost:9000/api/health`
- **Expected Status**: 200
- **Timeout**: 5s
- **Category**: api
- **Profiles**: ['home', 'mobile']

### Remote Execution MCP (Tony Dell)

- **ID**: remote-exec-tony-dell
- **Type**: mcp
- **Category**: api
- **Profiles**: ['home']

### Postgres

- **ID**: postgres
- **Type**: container
- **Container**: postgres
- **Expected State**: running
- **Category**: datastore
- **Profiles**: ['home', 'mobile']

### Weaviate

- **ID**: weaviate
- **Type**: http
- **URL**: `{profile}/api/weaviate/v1/nodes`
- **Expected Status**: 200
- **Timeout**: 5s
- **Category**: datastore
- **Profiles**: ['home', 'mobile']

### MDDB API

- **ID**: mddb-api
- **Type**: http
- **URL**: `http://tony-omen.local:11023/health`
- **Expected Status**: 200
- **Timeout**: 5s
- **Category**: datastore
- **Profiles**: ['home', 'mobile']

### MDDB MCP Server

- **ID**: mddb-mcp
- **Type**: http
- **URL**: `http://tony-omen.local:9001/mcp`
- **Expected Status**: 200
- **Timeout**: 5s
- **Category**: datastore
- **Profiles**: ['home', 'mobile']

### MDDB Panel

- **ID**: mddb-panel
- **Type**: http
- **URL**: `{profile}/apps/mddb/`
- **Expected Status**: 200
- **Timeout**: 5s
- **Category**: web
- **Profiles**: ['home', 'mobile']

### MDDB Stats Endpoint

- **ID**: mddb-stats
- **Type**: http
- **URL**: `http://tony-omen.local:11023/v1/stats`
- **Expected Status**: 200
- **Timeout**: 5s
- **Category**: datastore
- **Profiles**: ['home', 'mobile']

### MDDB Vector Stats Endpoint

- **ID**: mddb-vector-stats
- **Type**: http
- **URL**: `http://tony-omen.local:11023/v1/vector-stats`
- **Expected Status**: 200
- **Timeout**: 5s
- **Category**: datastore
- **Profiles**: ['home', 'mobile']

### MDDB Metrics Endpoint

- **ID**: mddb-metrics
- **Type**: http
- **URL**: `http://tony-omen.local:11023/metrics`
- **Expected Status**: 200
- **Timeout**: 5s
- **Category**: datastore
- **Profiles**: ['home', 'mobile']

### MDDB Container

- **ID**: mddb-container
- **Type**: container
- **Container**: mddb
- **Expected State**: running
- **Category**: datastore
- **Profiles**: ['home', 'mobile']

### Llama Router (Phi-3 only)

- **ID**: thai-legal
- **Type**: http
- **URL**: `http://tony-omen.local:8001/health`
- **Expected Status**: 200
- **Timeout**: 10s
- **Category**: gpu
- **Profiles**: ['home']

### Llama Server (MCP)

- **ID**: llama-server
- **Type**: http
- **URL**: `http://tony-omen.local:8008/health`
- **Expected Status**: 200
- **Timeout**: 10s
- **Category**: gpu
- **Profiles**: ['home']

### Imagen2

- **ID**: imagen2
- **Type**: http
- **URL**: `http://tony-omen.local:8000/health`
- **Expected Status**: 200
- **Timeout**: 10s
- **Category**: gpu
- **Profiles**: ['home']

### Txt2Vid

- **ID**: txt2vid
- **Type**: http
- **URL**: `http://tony-omen.local:8002/health`
- **Expected Status**: 200
- **Timeout**: 10s
- **Category**: gpu
- **Profiles**: ['home']

### GPU Queue

- **ID**: gpu-queue
- **Type**: http
- **URL**: `http://tony-omen.local:3001/health`
- **Expected Status**: 200
- **Timeout**: 5s
- **Category**: queue
- **Profiles**: ['home']

### Activepieces

- **ID**: activepieces
- **Type**: container
- **Container**: activepieces
- **Expected State**: running
- **Category**: optional
- **Profiles**: ['home', 'mobile']

### Frigate NVR

- **ID**: frigate
- **Type**: http
- **URL**: `{profile}/frigate/api/version`
- **Expected Status**: 200
- **Timeout**: 10s
- **Category**: optional
- **Profiles**: ['home', 'mobile']

### Camera Control

- **ID**: camera-control
- **Type**: http
- **URL**: `http://tony-omen.local:8090/`
- **Expected Status**: 200
- **Timeout**: 5s
- **Category**: optional
- **Profiles**: ['home']

### Yomi Update All Timer

- **ID**: yomi-update-all-timer
- **Type**: systemd
- **Service**: yomi-update-all.timer
- **Expected State**: active
- **Category**: system
- **Profiles**: ['home', 'mobile']

### Yomi Update Active Timer

- **ID**: yomi-update-active-timer
- **Type**: systemd
- **Service**: yomi-update-active.timer
- **Expected State**: active
- **Category**: system
- **Profiles**: ['home', 'mobile']

### Weaviate Index Timer

- **ID**: weaviate-index-timer
- **Type**: systemd
- **Service**: weaviate-index.timer
- **Expected State**: active
- **Category**: system
- **Profiles**: ['home', 'mobile']

### Chaba Health Monitor Timer

- **ID**: chaba-health-monitor-timer
- **Type**: systemd
- **Service**: chaba-health-monitor.timer
- **Expected State**: active
- **Category**: system
- **Profiles**: ['home', 'mobile']

## Testing



## Related Documentation

- [SSOT Health Configuration](../ssot/infrastructure/ssot.health.yml)
- [Health Check Dashboard](/apps/health-check/)
