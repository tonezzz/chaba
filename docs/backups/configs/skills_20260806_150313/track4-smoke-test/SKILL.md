---
description: Run Track4 smoke tests using the test suite
---

# Track4 Smoke Test

Runs automated smoke tests for Track4 visualization modules and effects.

## Usage

Run this skill to verify Track4 functionality after making changes.

## What It Tests

- Module loading (RacerIconRenderer, SimulationEngine, UIController, MapLayerManager, StateManager)
- CSS file loading (base.css, components.css, layout.css, racer-icons.css)
- Course module availability
- RacerIconRenderer methods
- SimulationEngine methods
- MapLayerManager methods
- CSS classes for leader focus, ribbon caps, sections, racer interaction
- UI control structure

## How It Works

1. Opens the Track4 test page at `http://192.168.1.48:8081/apps/track4/test.html`
2. Clicks "Run All Tests" button
3. Waits for tests to complete
4. Reports results (total/passed/failed)
5. Displays test log output

## Requirements

- Track4 test page must be accessible at `http://192.168.1.48:8081/apps/track4/test.html`
- Chrome on tony-dell must be accessible via playlive MCP server
