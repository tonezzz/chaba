---
title: Test PWA - iPad Progressive Web App
description: Progressive Web App demo for iPad testing with full-screen support, interactive features, and status detection capabilities.
tags: [pwa, ipad, mobile, testing, web-development, chaba-h3]
created: 2026-08-06
updated: 2026-08-06
category: implementation
related: [ssot.apps.test-pwa.yml, h3-pages.md]
search_keywords: [progressive-web-app, ipad-fullscreen, mobile-testing, pwa-manifest, standalone-mode]
---

# Test PWA - iPad Progressive Web App

**Abstract**: A Progressive Web App (PWA) demo application for testing iPad full-screen capabilities, featuring interactive elements, theme switching, local storage persistence, and comprehensive status detection for PWA installation and display modes.

## Overview

The Test PWA is a demonstration application deployed on the chaba-h3 platform that showcases Progressive Web App capabilities specifically optimized for iPad devices. It serves as both a functional testing tool and a reference implementation for building PWAs with full-screen support, interactive features, and proper iOS integration.

## Purpose

- **PWA Development Reference**: Template and best practices for building PWAs with iPad full-screen support
- **Display Mode Testing**: Compare standalone vs browser vs minimal-ui display modes on iOS
- **Installation Workflow Testing**: Test home screen installation and launch behavior
- **Feature Demonstration**: Showcase PWA capabilities like local storage and status detection
- **iOS Integration**: Demonstrate proper Apple-specific meta tags and iOS PWA patterns

## Key Files

| File | Purpose |
|------|---------|
| `chaba-h3/public/apps/test-pwa/index.html` | Main HTML structure with meta tags and app container |
| `chaba-h3/public/apps/test-pwa/manifest.json` | PWA manifest with display mode, icons, and theme configuration |
| `chaba-h3/public/apps/test-pwa/app.css` | Responsive CSS with theme variables and touch-friendly controls |
| `chaba-h3/public/apps/test-pwa/app.js` | Interactive logic for counter, themes, and status detection |
| `chaba-h3/public/apps/test-pwa/icon-192.svg` | SVG icon for home screen (192x192) |
| `chaba-h3/public/apps/test-pwa/icon-512.svg` | SVG icon for app launcher (512x512) |
| `docs/ssot/apps/ssot.apps.test-pwa.yml` | SSOT configuration and detailed feature documentation |

## Implementation/Architecture

### Manifest Configuration

The PWA uses `display: standalone` mode for native app-like experience:

```json
{
  "display": "standalone",
  "orientation": "any",
  "background_color": "#ffffff",
  "theme_color": "#2563eb",
  "scope": "/apps/test-pwa/",
  "start_url": "/apps/test-pwa/"
}
```

### Apple-Specific Integration

iOS-specific meta tags for proper iPad integration:

```html
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#2563eb">
```

### Interactive Features

- **Counter**: Tap counter with local storage persistence
- **Theme Switcher**: 5 color themes (default, dark, green, purple, orange)
- **Status Detection**: PWA installation status, display mode, online/offline status
- **Safe Area Insets**: `viewport-fit=cover` for edge-to-edge display on modern iOS devices

### State Management

Local storage persists user preferences across sessions:

```javascript
localStorage.setItem('test-pwa-state', JSON.stringify({
  count: currentCount,
  currentTheme: selectedTheme
}));
```

## Operational Procedures

### Installation on iPad

1. Open Safari on iPad and navigate to `https://chaba.h3.gizmo-thailand.com/apps/test-pwa/`
2. Tap the Share button (square with arrow)
3. Select "Add to Home Screen"
4. Tap "Add" to confirm installation
5. Launch from home screen for full-screen standalone mode

### Testing Procedures

#### Full-Screen Verification
1. Open app in Safari browser - note browser UI is visible
2. Install to home screen and launch - note browser UI is hidden
3. Compare the two experiences to confirm standalone mode

#### Theme Testing
1. Tap "Change Theme" button to cycle through all 5 themes
2. Verify visual consistency across all themes
3. Close and reopen app - theme should persist

#### Persistence Testing
1. Use counter to increment tap count
2. Close app completely
3. Reopen app - counter should show previous value
4. Test with different themes - both should persist

#### Status Detection
1. Check "PWA Installed" status when launched from browser vs home screen
2. Verify "Display Mode" shows correct mode (standalone vs browser)
3. Test "Online" status by toggling WiFi/cellular connection

### Deployment

The Test PWA is deployed on the chaba-h3 Plesk static site:

- **Location**: `chaba-h3/public/apps/test-pwa/`
- **URL**: `https://chaba.h3.gizmo-thailand.com/apps/test-pwa/`
- **Branch**: `chaba.h3` (Plesk static site)
- **Registry**: Listed in `apps.yml` with 📱 icon

## Troubleshooting

### Issue: Full-screen mode not working
- **Symptoms**: App still shows browser UI when launched from home screen
- **Causes**: Manifest not loaded, display mode not set to standalone, iOS cache
- **Solutions**: 
  - Clear Safari cache and re-install
  - Verify manifest.json is accessible and valid
  - Ensure `display: standalone` is set in manifest
  - Remove and re-add to home screen

### Issue: Theme not persisting
- **Symptoms**: Theme resets to default after closing app
- **Causes**: Local storage disabled, JavaScript error, storage quota exceeded
- **Solutions**:
  - Check browser console for JavaScript errors
  - Verify local storage is enabled in Safari settings
  - Clear local storage and test again

### Issue: Icons not displaying
- **Symptoms**: Default app icon shows instead of custom icon
- **Causes**: SVG icons not accessible, incorrect icon sizes, iOS cache
- **Solutions**:
  - Verify icon files are accessible at correct paths
  - Ensure SVG files are valid and properly sized
  - Clear iOS cache and re-install app

## Performance Metrics

- **Load Time**: < 1 second on typical WiFi connection
- **Storage**: ~50KB total (HTML + CSS + JS + icons)
- **Memory**: Minimal footprint, no background processes
- **Battery**: No significant impact (no background services)

## Related Documentation

- **SSOT Configuration**: `docs/ssot/apps/ssot.apps.test-pwa.yml` - Complete feature documentation
- **chaba.h3 Pages**: `docs/kb/h3-pages.md` - Deployment patterns and URL routing
- **Worktree Strategy**: `docs/kb/worktree-separation-strategy.md` - chaba-h3 worktree context
- **Documentation Standards**: `docs/kb/documentation-maintenance-standards.md` - KB entry guidelines

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-06 | Initial creation with full PWA implementation and documentation | tony |
