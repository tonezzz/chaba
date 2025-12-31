# PC1 DEKA Stack

Dedicated stack for DEKA Thai Supreme Court document scraping and processing.

## Services

- **mcp-deka** - Thai Supreme Court document discovery and extraction
  - Port: 8270
  - Base URL: http://deka.supremecourt.or.th/
  - Features: Document search, link extraction, content hydration

## Usage

```bash
# Start DEKA stack
docker-compose --file docker-compose.yml up -d

# Check health
curl http://localhost:8270/health

# Test basic search
curl -X POST http://localhost:8270/invoke \
  -H "Content-Type: application/json" \
  -d '{"tool":"discover_basic_year","arguments":{"startYear":2565,"endYear":2567}}'
```

## Cross-Host Access

The DEKA service is designed to be accessible from other hosts:

### From pc2-worker or other hosts
```json
// 1mcp.json configuration
{
  "mcpServers": {
    "pc1-mcp-deka": {
      "transport": "streamableHttp",
      "url": "http://pc1.vpn:8270/mcp",
      "tags": ["pc1", "deka", "thai", "legal", "remote"],
      "enabled": true
    }
  }
}
```

### Environment Setup
```bash
# Copy environment file
cp .env.example .env

# Adjust configuration as needed
# DEKA_BASE_URL=http://deka.supremecourt.or.th/
# DEKA_TIMEOUT_MS=45000
# DEKA_MAX_PAGES=200
```

## Network

- **Network**: `pc1-deka-net` (172.21.0.0/16)
- **VPN Access**: Available via `pc1.vpn:8270`
- **Data Storage**: Persistent volume `mcp-deka-data`

## Features

### Document Discovery
- **Basic Year Search**: Search documents by year range
- **Keyword Search**: Optional keyword filtering
- **Multi-page Support**: Configurable max pages per search
- **Link Extraction**: Automatic document link discovery

### Content Processing
- **HTML Hydration**: Fetch and parse document content
- **Short-view Modal**: Best-effort modal content extraction
- **Character Limits**: Configurable max characters per document
- **Data Storage**: SQLite database for document metadata

### MCP Tools
- `discover_basic_year` - Search by year range (+keyword)
- `extract_links` - Extract links from HTML content
- `hydrate_doc` - Fetch and parse specific document
- `parse_search_html` - Parse search results
- `run_search_flow` - Execute Playwright search flow
- `status` - Get database and run statistics

## Requirements

- Docker with standard networking
- Internet access to deka.supremecourt.or.th
- Sufficient storage for document database

## Data Persistence

- **Database**: SQLite in `/data` volume
- **Document IDs**: Stored in database with pagination info
- **Run History**: Tracks search flows and parsing results
