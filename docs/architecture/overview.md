# System Architecture Overview

Auto-generated from SSOT configuration
Generated: 2026-08-12 20:33:16

## Components

### Web Stack
- Caddy web server
- Static file serving
- Reverse proxy for APIs

### Data Services
- PostgreSQL database
- Weaviate vector database
- Redis cache (optional)

### AI/ML Services
- Llama Router (GPU inference)
- GPU Queue management
- Image generation services

### Monitoring
- Health check system
- Performance monitoring
- Alerting system

## Service Dependencies

See [Services Overview](../services/overview.md) for detailed dependency information.

## Related Documentation

- [SSOT Index](../ssot/ssot.index.yml)
- [Infrastructure Configuration](../ssot/infrastructure/)
