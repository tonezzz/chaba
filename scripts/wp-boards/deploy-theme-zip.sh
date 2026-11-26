#!/usr/bin/env bash
# Deploy a wordpress.org theme zip to boards.surf-thailand.com via the
# wp-admin theme upload flow (theme-install.php?tab=upload +
# update.php?action=upload-theme + overwrite link). Runs on a host that
# holds ~/.config/secrets/boards-surf-thailand-com-wp-admin-credential
# (format: "<user>,<password>") — currently tony-omen.
#
# Usage: deploy-theme-zip.sh /path/to/<slug>.zip [--activate]
#   --activate  follow the "Activate" link after install/overwrite so the
#               theme goes live immediately (reversible via themes.php).
set -euo pipefail

ZIP="${1:?usage: $0 /path/to/theme.zip [--activate]}"
ACTIVATE=0
[ "${2:-}" = "--activate" ] && ACTIVATE=1
SITE="https://boards.surf-thailand.com/wp"
CRED_FILE="$HOME/.config/secrets/boards-surf-thailand-com-wp-admin-credential"
CJ="$(mktemp)"; trap 'rm -f "$CJ" /tmp/_ti.html /tmp/_tu.html /tmp/_to.html /tmp/_th.html' EXIT

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
curl -sS -b "$CJ" -c "$CJ" "$SITE/wp-admin/theme-install.php?tab=upload" -o /tmp/_ti.html
NONCE=$(grep -o 'name="_wpnonce" value="[^"]*"' /tmp/_ti.html | head -1 | sed 's/.*value="//;s/"//')
[ -n "$NONCE" ] || { echo "FAIL: no _wpnonce on theme-install page"; exit 1; }

echo "== 3. upload zip"
curl -sS -b "$CJ" -c "$CJ" \
  -F "_wpnonce=$NONCE" \
  -F "_wp_http_referer=/wp/wp-admin/theme-install.php?tab=upload" \
  -F "themezip=@$ZIP;type=application/zip" \
  -F "install-theme-submit=Install Now" \
  "$SITE/wp-admin/update.php?action=upload-theme" -o /tmp/_tu.html

if grep -q "Theme installed successfully" /tmp/_tu.html; then
  echo "OK: installed (no overwrite needed)"
elif grep -q "destination folder already exists" /tmp/_tu.html; then
  echo "== 4. overwrite confirm"
  OVURL=$(grep -o 'href="[^"]*overwrite[^"]*"' /tmp/_tu.html | head -1 | sed 's/href="//;s/"$//;s/&amp;/\&/g')
  if [ -z "$OVURL" ]; then
    OVURL=$(grep -o 'action="[^"]*"' /tmp/_tu.html | grep -i "update.php" | head -1 | sed 's/action="//;s/"$//;s/&amp;/\&/g')
  fi
  case "$OVURL" in
    http*) : ;;
    /*)    OVURL="https://boards.surf-thailand.com$OVURL" ;;
    *)     OVURL="$SITE/wp-admin/$OVURL" ;;
  esac
  [ -n "$OVURL" ] || { echo "FAIL: no overwrite link/form in response"; grep -o '<title>[^<]*' /tmp/_tu.html; exit 1; }
  echo "   -> $OVURL"
  curl -sS -b "$CJ" -c "$CJ" "$OVURL" -o /tmp/_to.html
  grep -qi "Theme updated successfully\|overwrite" /tmp/_to.html || { echo "WARN: overwrite result unclear"; }
else
  echo "FAIL: unexpected upload response"; grep -o '<title>[^<]*\|class="error[^"]*"[^<]*' /tmp/_tu.html | head -5; exit 1
fi

# Activation link lives on themes.php (or the post-upload page).
ACT=$(grep -o 'href="[^"]*action=activate[^"&]*&[^"<]*stylesheet=[^"]*"' /tmp/_tu.html /tmp/_to.html 2>/dev/null | head -1 | sed 's/.*href="//;s/"$//;s/&amp;/\&/g')
if [ -z "$ACT" ]; then
  curl -sS -b "$CJ" -c "$CJ" "$SITE/wp-admin/themes.php" -o /tmp/_th.html
  # pick the activate link matching the uploaded theme's stylesheet
  SLUG=$(python3 -c "import zipfile,sys; print(zipfile.ZipFile('$ZIP').namelist()[0].split('/')[0])" 2>/dev/null || true)
  if [ -n "$SLUG" ]; then
    ACT=$(grep -o "href=\"[^\"]*action=activate[^\"]*stylesheet=$SLUG[^\"]*\"" /tmp/_th.html | head -1 | sed 's/.*href="//;s/"$//;s/&amp;/\&/g')
  fi
  [ -z "$ACT" ] && ACT=$(grep -o 'href="[^"]*action=activate[^"]*"' /tmp/_th.html | head -1 | sed 's/.*href="//;s/"$//;s/&amp;/\&/g')
fi

if [ "$ACTIVATE" = "1" ] && [ -n "$ACT" ]; then
  case "$ACT" in /*) ACT="https://boards.surf-thailand.com$ACT";; http*) :;; *) ACT="$SITE/wp-admin/$ACT";; esac
  echo "== 5. activate: $ACT"
  curl -sS -b "$CJ" -c "$CJ" "$ACT" -o /dev/null
  echo "OK: activation requested"
elif [ "$ACTIVATE" = "1" ]; then
  echo "WARN: --activate given but no activate link found"
fi
echo "DONE"
