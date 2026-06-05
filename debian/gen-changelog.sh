#!/bin/sh
# Generate debian/changelog from pyproject.toml version + CHANGELOG.md body.
# The deb version is single-sourced from pyproject.toml; the entry body is the
# matching "## [x.y.z]" section of CHANGELOG.md, with Keep-a-Changelog markup
# flattened into Debian "  * " bullets and wrapped to keep lines under 80 cols.
set -eu
cd "$(dirname "$0")/.."

VERSION=$(grep -m1 -E '^version = ' pyproject.toml | sed -E 's/version = "([^"]+)".*/\1/')
DEBFULLNAME=${DEBFULLNAME:-Sean Reifschneider}
DEBEMAIL=${DEBEMAIL:-jafo00@gmail.com}
DATE=$(date -R)

# Extract the section for $VERSION as one un-prefixed line per bullet (wrapped
# CHANGELOG continuation lines are joined; "### Added"-style headers dropped).
RAW=$(awk -v ver="$VERSION" '
  $0 ~ "^## \\[" ver "\\]" { grab=1; next }
  grab && /^## \[/ { exit }
  grab {
    if ($0 ~ /^### /) next
    if ($0 ~ /^[[:space:]]*$/) next
    if ($0 ~ /^- /) { if (cur != "") print cur; cur = substr($0, 3) }
    else { sub(/^[[:space:]]+/, "", $0); cur = (cur == "" ? $0 : cur " " $0) }
  }
  END { if (cur != "") print cur }
' CHANGELOG.md)

if [ -n "$RAW" ]; then
  # Wrap each bullet to <80 cols: "  * " on the first line, 4-space indent after.
  BODY=$(printf '%s\n' "$RAW" | while IFS= read -r item; do
    printf '%s\n' "$item" | fold -s -w 74 \
      | sed -e 's/[[:space:]]*$//' -e '1s/^/  * /' -e '2,$s/^/    /'
  done)
else
  BODY="  * Release ${VERSION}."
fi

mkdir -p debian
{
  printf 'pxv (%s) unstable; urgency=medium\n\n' "$VERSION"
  printf '%s\n\n' "$BODY"
  printf ' -- %s <%s>  %s\n' "$DEBFULLNAME" "$DEBEMAIL" "$DATE"
} > debian/changelog
