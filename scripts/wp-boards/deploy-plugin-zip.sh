#!/usr/bin/env bash
# Deploy a chaba-boards plugin zip to boards.surf-thailand.com via the
# documented wp-admin upload flow (update.php?action=upload-plugin +
# overwrite link). Runs on a host that holds
# ~/.config/secrets/boards-surf-thailand-com-wp-admin-credential
# (format: "<user>,<password>") — currently tony-omen.
#
# Usage: deploy-plugin-zip.sh /path/to/chaba-boards-X.Y.Z.zip
set -euo pipefail

ZIP="${1:?usage: $0 /path/to/plugin.zip}"
SITE="https://boards.surf-thailand.com/wp"
CRED_FILE="$HOME/.config/secrets/boards-surf-thailand-com-wp-admin-credential"
CJ="$(mktemp)"; trap 'rm -f "$CJ" /tmp/_pi.html /tmp/_up.html /tmp/_ov.html' EXIT

IFS=',' read -r WPUSER WPPASS < "$CRED_FILE" || true
[ -n "${WPUSER:-}" ] && [ -n "${WPPASS:-}" ] || { echo "FAIL: cred file parse"; exit 1; }

echo "== 1. wp-login"
curl -sS -c "$CJ" -b "wordpress_test_cookie=WP+Cookie+check" \
  --data-urlencode "log=$WPUSER" \
  --data-urlencode "pwd=$WPPASS" \
  --data-urlencode "wp-submit=Log In" \
  --data-urlencode "redirect_to=$SITE/wp-admin/" \
  --data-urlencode "testcookie=1" \
  "$SITE/wp-login.php" -o /dev/null
grep -q "wordpress_logged_in" "$CJ" || { echo "FAIL: no logged_in cookie"; exit 1; }

echo "== 2. upload nonce"
curl -sS -b "$CJ" -c "$CJ" "$SITE/wp-admin/plugin-install.php?tab=upload" -o /tmp/_pi.html
NONCE=$(grep -o 'name="_wpnonce" value="[^"]*"' /tmp/_pi.html | head -1 | sed 's/.*value="//;s/"//')
[ -n "$NONCE" ] || { echo "FAIL: no _wpnonce on plugin-install page"; exit 1; }

echo "== 3. upload zip"
curl -sS -b "$CJ" -c "$CJ" \
  -F "_wpnonce=$NONCE" \
  -F "_wp_http_referer=/wp/wp-admin/plugin-install.php?tab=upload" \
  -F "pluginzip=@$ZIP;type=application/zip" \
  -F "install-plugin-submit=Install Now" \
  "$SITE/wp-admin/update.php?action=upload-plugin" -o /tmp/_up.html

if grep -q "Plugin installed successfully\|Plugin updated successfully" /tmp/_up.html; then
  echo "OK: installed (no overwrite needed)"; exit 0
fi

echo "== 4. overwrite confirm"
# WP shows a compare table + "Replace current with uploaded" link/button.
OVURL=$(grep -o 'href="[^"]*overwrite[^"]*"' /tmp/_up.html | head -1 | sed 's/href="//;s/"$//;s/&amp;/\&/g')
if [ -z "$OVURL" ]; then
  # newer WP: a form posting back to update.php
  OVURL=$(grep -o 'action="[^"]*"' /tmp/_up.html | grep -i "update.php" | head -1 | sed 's/action="//;s/"$//;s/&amp;/\&/g')
fi
case "$OVURL" in
  http*) : ;;
  /*)    OVURL="https://boards.surf-thailand.com$OVURL" ;;
  *)     OVURL="$SITE/wp-admin/$OVURL" ;;
esac
[ -n "$OVURL" ] || { echo "FAIL: no overwrite link/form in response"; grep -o '<title>[^<]*' /tmp/_up.html; exit 1; }
echo "   -> $OVURL"
curl -sS -b "$CJ" -c "$CJ" "$OVURL" -o /tmp/_ov.html

if grep -qi "Plugin updated successfully\|Plugin activated\|replace" /tmp/_ov.html; then
  echo "OK: overwrite applied"
else
  echo "WARN: could not confirm overwrite result"; grep -o '<title>[^<]*\|error[^<]*' /tmp/_ov.html | head -5
fi

# 5. activation link (fresh install path) — overwrite keeps active state.
ACT=$(grep -o 'href="[^"]*action=activate-plugin[^"]*"' /tmp/_up.html /tmp/_ov.html 2>/dev/null | head -1 | sed 's/.*href="//;s/"$//;s/&amp;/\&/g')
if [ -n "$ACT" ]; then
  case "$ACT" in /*) ACT="https://boards.surf-thailand.com$ACT";; http*) :;; *) ACT="$SITE/wp-admin/$ACT";; esac
  echo "== 5. activate: $ACT"
  curl -sS -b "$CJ" -c "$CJ" "$ACT" -o /dev/null
fi
echo "DONE"
