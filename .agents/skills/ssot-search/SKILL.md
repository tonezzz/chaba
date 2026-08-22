---
name: ssot-search
description: Search across all SSOT YAML files for keywords
allowed-tools:
  - grep
  - read
triggers:
  - user
  - model
---

Search across all SSOT YAML files in docs/ssot/ and trade SSOT in config/ssot/:

1. Accept search term as argument or prompt for it
2. Search across all SSOT files matching patterns:
   - docs/ssot/**/*.yml (central SSOT)
   - config/ssot/**/*.yml (trade SSOT)
3. Exclude template files: template.yml, template.app.yml
4. Use grep to find matches with context (2 lines before and after)
5. Group results by SSOT file
6. For each matching file:
   - Show file name
   - Show matching lines with context
   - Count total matches in that file
7. Provide summary:
   - Total files searched
   - Files with matches
   - Total matches across all files
8. If no matches found, suggest:
   - Try different search terms
   - Check spelling
   - Use broader terms
