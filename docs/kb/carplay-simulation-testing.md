---
title: CarPlay Simulation Testing
description: CarPlay-style interface simulation for iPad testing with GPS tracking, route planning, and navigation simulation capabilities
tags: [carplay, ipad, testing, simulation, gps, navigation]
created: 2026-08-06
updated: 2026-08-06
category: implementation
related: [ssot.apps.test-carplay.yml, app-ssot-standards.md, h3-pages.md]
search_keywords: [carplay simulation, ipad testing, gps tracking, route planning, navigation testing, ios interface]
---

# CarPlay Simulation Testing
## What it is

title: CarPlay Simulation Testing


**Abstract**: CarPlay-style simulation interface for iPad testing that provides GPS tracking, route planning, and navigation simulation capabilities using iOS-inspired design patterns and modular architecture.
## Context/Background

Created 2026-08-07 as part of Chaba infrastructure documentation.


## Overview

Test CarPlay is a simulation interface designed for iPad testing that replicates CarPlay-style navigation and mapping functionality. It provides a controlled environment for testing GPS-based applications, route planning interfaces, and iOS-style UI patterns without requiring actual CarPlay hardware or real GPS data.

## Purpose

- **iPad Interface Testing**: Test CarPlay-style interfaces on iPad devices with iOS-inspired design
- **GPS Simulation**: Simulate GPS location tracking with predefined locations and current location detection
- **Route Planning Testing**: Test route planning interfaces with Google Maps-style input and suggestions
- **Navigation Simulation**: Simulate turn-by-turn navigation and route visualization
- **UI Pattern Validation**: Validate iOS-style UI patterns, animations, and responsive design

## Key Files

- **index.html**: Main app shell with CarPlay-style layout and map container
- **carplay.css**: iOS-inspired dark theme styling with animations and responsive design
- **gps-module.js**: GPS location data and tracking with predefined locations
- **route-input-module.js**: Route planning interface with suggestions and calculation
- **main.js**: Main app logic integrating GPS and route modules

## Implementation

### GPS Location System

**Predefined Locations:**
- Tony Omen: 13.7563, 100.5018 (Primary Workstation)
- Tony Dell: 13.7565, 100.5020 (Secondary Workstation)
- Home: 13.7560, 100.5015 (Home Location)
- Chaba H3: 13.7520, 100.5000 (Chaba H3 Location)

**Features:**
- Centralized LOCATIONS object with GPS coordinates and metadata
- Current location detection via browser geolocation API
- Location type classification (workstation, home)
- Address information for each location

### Route Planning Interface

**Input Fields:**
- Start location input with autocomplete
- Destination location input with autocomplete
- "My location" buttons for quick current location selection
- Debounced search (300ms) for performance

**Suggestions System:**
- Auto-complete location suggestions
- Separate suggestion panels for start/destination fields
- Location filtering based on input
- Visual feedback for suggestion selection

**Route Calculation:**
- Simulated route calculation between locations
- Route visualization on map (when implemented)
- Turn-by-turn direction simulation
- Progress tracking and ETA estimation

### UI Design Patterns

**CarPlay-Inspired Styling:**
- Dark theme with iOS color palette
- Rounded corners and smooth animations
- Touch-optimized controls and interactions
- Responsive design for iPad screens

**Components:**
- Route input panel with header and body sections
- Location suggestion panels (400px max height)
- Current location buttons with GPS icons
- Route calculation and navigation controls

## Testing Procedures

### GPS Testing
1. Test predefined location selection from suggestions
2. Verify current location detection with browser geolocation
3. Test location accuracy and coordinate mapping
4. Validate location type classification

### Route Planning Testing
1. Test start/destination input fields
2. Verify auto-complete suggestions functionality
3. Test debounced search performance
4. Validate route calculation logic
5. Test "My location" button functionality

### UI Testing
1. Test iOS-style animations and transitions
2. Verify responsive design on iPad screens
3. Test touch interactions and gesture support
4. Validate dark theme consistency
5. Test route suggestion panel visibility states

### Integration Testing
1. Test GPS module integration with route planning
2. Verify location database consistency
3. Test state management across modules
4. Validate map integration (when implemented)

## Known Limitations

**GPS Data:**
- Coordinates are approximate Bangkok area values
- Not connected to real GPS hardware
- Limited to predefined location database

**Route Calculation:**
- Simulated routing, not connected to real routing API
- No real-time traffic data
- Limited to predefined location network

**Map Integration:**
- Map rendering not yet implemented
- Currently UI-only simulation
- Requires Leaflet or similar map library integration

**Browser Dependencies:**
- Requires geolocation API support
- Dependent on browser permissions
- Limited to browsers with GPS API access

## Deployment

**Location:** `chaba-h3/public/apps/test-carplay/`
**URL:** `https://chaba.h3.gizmo-thailand.com/apps/test-carplay/`
**Branch:** `chaba-h3`
**Registry:** Listed in `chaba-h3/public/apps/apps.yml`

## Related Documentation

- **SSOT File**: `docs/ssot/apps/ssot.apps.test-carplay.yml` - Complete app configuration
- **App Standards**: `docs/kb/app-ssot-standards.md` - SSOT standards for applications
- **H3 Pages**: `docs/kb/h3-pages.md` - Chaba-h3 deployment procedures

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-06 | Initial CarPlay simulation testing documentation | devin |

## Tags

- **api**: api
- **rest**: rest
- **http**: http
- **web**: web
- **database**: database
- **postgres**: postgres
- **redis**: redis
- **mongodb**: mongodb
- **sql**: sql
- **deployment**: deployment
- **ci**: ci
- **cd**: cd
- **docker**: docker
- **performance**: performance
- **optimization**: optimization
- **caching**: caching
- **testing**: testing
- **e2e**: e2e
- **automation**: automation
- **documentation**: documentation
- **kb**: kb
- **knowledge-base**: knowledge-base
- **h3**: h3
- **gizmo**: gizmo
- **thailand**: thailand
- **carplay**: carplay
- **apple**: apple
- **automotive**: automotive
- **ssot**: ssot
- **configuration**: configuration
- **infrastructure**: infrastructure
- **2026**: 2026
