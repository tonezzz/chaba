---
description: Test responsive design using Playlive automation + Chrome DevTools Device Mode + manual iPad verification
---
1. **Playlive Automation Phase**:
   - Create a Chrome session using `playlive_create_chrome_live` or `playlive_create_playwright_chrome`
   - Navigate to the target URL using `playlive_navigate`
   - Run automated interactions (click, fill, etc.) using Playlive tools
   - Take screenshots using `playlive_screenshot_image` for desktop baseline
   - Close session with `playlive_close_session`

2. **Chrome DevTools Device Mode Phase**:
   - Open Chrome DevTools (F12) and toggle Device Mode (Ctrl+Shift+M)
   - Select iPad preset (iPad Pro 12.9", iPad Air, or iPad Mini)
   - Navigate to the same target URL
   - Verify responsive layout, touch interactions, and viewport behavior
   - Test network throttling (3G/4G) if needed
   - Note any layout or functionality issues

3. **Manual iPad Verification Phase**:
   - Open the target URL on real iPad Chrome
   - Verify critical user flows and interactions
   - Check iOS-specific behaviors (scrolling, zoom, touch gestures)
   - Compare with desktop and DevTools results
   - Document any device-specific issues

4. **Reporting**:
   - Summarize findings from all three testing phases
   - Highlight any responsive design issues found
   - Note iOS-specific behaviors that differ from desktop
   - Provide recommendations for fixes if issues were found
