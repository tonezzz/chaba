---
category: operations
---

# Components

### 1. Baseline Collection Script

**Location:** `scripts/collect-performance-baselines.mjs`

**Purpose:** Collects performance baselines from MCP health server historical data

**Usage:**
```bash
node scripts/collect-performance-baselines.mjs
```

**Features:**
- Connects to MCP health server via stdio transport
- Collects 7 days of health history
- Calculates statistical baselines for each service:
  - Mean, median, p95, p99 response times
  - Standard deviation
  - Min/max values
  - Healthy percentage
- Marks data quality confidence (high/medium/low)
- Saves baselines to `docs/ssot/infrastructure/performance-baselines.yml`

**Baseline Quality Levels:**
- **High confidence:** 5+ healthy checks
- **Medium confidence:** 3-4 healthy checks  
- **Low confidence:** 1-2 healthy checks

### 2. Overnight Assessment Integration

**Location:** `scripts/overnight-assessment.mjs`

**Purpose:** Integrates baseline analysis into overnight assessment reports

**Features:**
- Loads baselines from YAML file
- Compares current health data against baselines
- Detects anomalies (>50% deviation)
- Identifies performance degradation (>20% deviation)
- Identifies performance improvement (>20% improvement)
- Generates structured baseline analysis report

**Anomaly Detection Thresholds:**
- **Critical anomaly:** >100% deviation from baseline
- **Warning anomaly:** 50-100% deviation from baseline
- **Degradation:** 20-50% deviation from baseline
- **Improvement:** <-20% deviation from baseline
- **Within baseline:** -20% to +20% deviation

### 3. Baseline Data File

**Location:** `docs/ssot/infrastructure/performance-baselines.yml`

**Structure:**
```yaml
baselines:
  ServiceName:
    service_name: ServiceName
    category: api|datastore|gpu|system|web|queue
    type: http|container|systemd
    total_checks: total number of checks
    healthy_checks: number of healthy checks
    healthy_percentage: percentage
    response_time:
      mean: average response time (ms)
      median: median response time (ms)
      p95: 95th percentile (ms)
      p99: 99th percentile (ms)
      min: minimum response time (ms)
      max: maximum response time (ms)
      std_dev: standard deviation (ms)
    data_quality:
      sample_size: number of healthy checks
      confidence: high|medium|low
      date_range:
        start: ISO timestamp
        end: ISO timestamp
    established: ISO timestamp when baseline was created
```

## Current Baselines

As of 2026-08-12, baselines established for 18 services:

### API Services
- **Yomi API:** 165ms median, 100% healthy
- **Yomi Summarization:** 166ms median, 100% healthy
- **Yomi Rate Limiter:** 165ms median, 100% healthy
- **Yomi Activity Status:** 157ms median, 100% healthy
- **Playlived:** 117ms median, 100% healthy
- **MDDB API:** 158ms median, 100% healthy

### Data Services
- **Weaviate:** 200ms median, 100% healthy
- **MDDB Panel:** 114ms median, 100% healthy

### GPU Services
- **Imagen2:** 138ms median, 100% healthy
- **GPU Queue:** 117ms median, 100% healthy

### System Services
- **Yomi Update All Timer:** 22ms median, 100% healthy
- **Yomi Update Active Timer:** 19ms median, 100% healthy
- **Weaviate Index Timer:** 16ms median, 100% healthy
- **Chaba Health Monitor Timer:** 17ms median, 100% healthy

### Web Services
- **Caddy:** 141ms median, 100% healthy
- **BServer:** 163ms median, 100% healthy
- **Raceman Web:** 132ms median, 100% healthy

### Optional Services
- **Frigate NVR:** 177ms median, 100% healthy

**Note:** All current baselines have low confidence due to limited historical data (single check). Baselines will improve as more health history accumulates.

