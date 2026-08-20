---
category: operations
---

# Implementation/Architecture

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

