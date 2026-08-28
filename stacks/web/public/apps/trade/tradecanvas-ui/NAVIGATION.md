# Navigation Menu Maintenance

## Adding New Pages

To add a new page to the navigation menu:

1. **Create your new HTML file** (e.g., `newpage.html`)
2. **Add the navigation menu** to your new page by inserting this code after the `</header>` tag:

```html
<!-- Navigation Menu -->
<nav class="nav-menu">
    <ul class="nav-list">
        <li class="nav-item"><a href="index.html" class="nav-link">Trading Dashboard</a></li>
        <li class="nav-item"><a href="compare.html" class="nav-link">Compare</a></li>
        <li class="nav-item"><a href="newpage.html" class="nav-link">New Page</a></li>
    </ul>
</nav>
```

3. **Add the nav.js script** before the closing `</body>` tag:

```html
<script src="nav.js"></script>
```

4. **Update all existing pages** (index.html, compare.html, etc.) to include your new page in their navigation menu.

## Current Pages

- `index.html` - Trading Dashboard
- `compare.html` - Compare

## How It Works

- The navigation menu uses the `nav.js` script to automatically highlight the active page
- The script checks the current URL and adds the `active` class to the corresponding navigation link
- CSS styles in `styles.css` handle the visual appearance and hover effects

## Styling

Navigation styles are defined in `styles.css` under the `.nav-menu`, `.nav-list`, `.nav-item`, and `.nav-link` classes. You can customize colors, spacing, and layout there.
