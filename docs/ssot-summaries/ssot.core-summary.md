# SSOT Core Configuration Summary

**Purpose**: Summary of core SSOT configuration files for searchability via MCP docs server.

## SSOT Index

**File**: `docs/ssot/ssot.index.yml`
**Purpose**: Master index of all SSOT files with purpose, location, and key content
**Sections**: Core/Cross-Project, System & Environment, UI & Frontend, Applications, Tooling & Knowledge, Templates
**Usage**: Single entry point for orienting to the SSOT system

## Strategic Focus Management

**File**: `docs/ssot/ssot.focus.yml`
**Purpose**: Strategic focus areas with shared vs per-branch tracking
**Features**:
- Active/pending/completed status tracking
- Dependency tracking and history
- Cross-branch focus coordination
- Strategic priority management

## System Improvements

**File**: `docs/ssot/ssot.improvements.yml`
**Purpose**: Pending system improvements with priority, effort, and impact scoring
**Features**:
- Priority and effort estimation
- Dependency tracking
- Impact scoring system
- Active items only (completed items archived)

**Archive**: `docs/ssot/ssot.improvements.archive.yml` - Completed improvements

## Validation Patterns

**File**: `docs/ssot/ssot.validation-patterns.yml`
**Purpose**: Validation rules, file-type classifications, and best practices
**Features**:
- SSOT system validation rules
- File-type classifications
- Best practices and patterns
- Error prevention guidelines

## Token Optimization

**File**: `docs/ssot/ssot.token-optimization.yml`
**Purpose**: MCP filter config, Headroom proxy, Devin usage patterns for token cost reduction
**Features**:
- MCP filtering configuration
- Headroom proxy setup
- Token usage patterns
- Cost reduction strategies
- Performance optimization

## UI & Frontend Configuration

**File**: `docs/ssot/ssot.libs.yml`
**Purpose**: Design tokens, shared components, asset paths, build workflow
**Features**:
- Design tokens and variables
- Shared component library
- Asset path management
- Build workflow configuration
- UI constraints and guidelines

**Stub**: `docs/ssot/ssot.ui.yml` - Redirects to ssot.libs.yml

## Architecture Diagrams

**File**: `docs/ssot/ssot.diagrams.yml`
**Purpose**: Architecture and connection diagrams for multi-host setups
**Features**:
- Playlive architecture diagrams
- Barrier system diagrams
- Multi-host connection diagrams
- Network topology documentation

## Tooling Configuration

**File**: `docs/ssot/ssot.devin.tools.yml`
**Purpose**: MCP server definitions and launch configuration for Devin/Windsurf
**Features**:
- MCP server configurations
- Launch parameters
- Tool definitions
- Integration settings

## Documentation Tools

**File**: `docs/ssot/ssot.docs.yml`
**Purpose**: Document processing tools, LLM infrastructure, library evaluation
**Features**:
- Document processing tools
- LLM infrastructure configuration
- Library evaluation candidates
- Documentation automation

## Testing Configuration

**File**: `docs/ssot/ssot.test.weaviate.yml`
**Purpose**: Weaviate vector database testing and optimization
**Features**:
- Embedding service setup
- Test plans and procedures
- Optimization notes
- Performance benchmarks

## System Configuration

**File**: `docs/ssot/ssot.mysystem.home.yml`
**Purpose**: Home environment configuration (workstations, network, services)
**Features**:
- Workstation configurations (tony-omen, tony-dell)
- Network configuration
- Service endpoints
- Health check URLs

**Mobile**: `docs/ssot/ssot.mysystem.mobile.yml` - Mobile/remote environment configuration

## Documentation Infrastructure

**File**: `docs/ssot/ssot.documentation-infrastructure.yml`
**Purpose**: Documentation infrastructure and disaster recovery procedures
**Features**:
- Backup scripts and schedules
- Recovery procedures
- MCP server configuration
- Disaster recovery planning

## Focus Automation

**File**: `docs/ssot/ssot.focus.yml`
**Purpose**: Strategic focus automation system for activity monitoring
**Features**:
- Advanced activity monitoring
- Dependency-driven automation
- Multi-project support
- Strategic focus management

## Templates

**File**: `docs/ssot/template.yml`
**Purpose**: Canonical template for creating new SSOT files
**Usage**: Copy and fill in for new SSOT file creation

**App Template**: `docs/ssot/apps/template.app.yml` - Standardized template for application SSOT files

## Related Documentation

- **SSOT Standards**: `docs/kb/ssot-documentation-standards.md` - SSOT maintenance procedures
- **App Standards**: `docs/kb/app-ssot-standards.md` - Application SSOT file standards
- **Documentation Standards**: `docs/kb/documentation-maintenance-standards.md` - KB entry guidelines
- **Search Methods**: `docs/kb/documentation-search.md` - Dual search methods guide

## Search Keywords

SSOT index, strategic focus, system improvements, validation patterns, token optimization, UI configuration, architecture diagrams, MCP tools, documentation infrastructure, focus automation, templates, Devin tools, Weaviate testing
