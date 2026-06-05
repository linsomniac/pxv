# Debian Packaging + GitHub Release Publishing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a native Debian `.deb` for `pxv` in GitHub Actions and attach it to the GitHub release, with full desktop integration.

**Architecture:** A maintained `debian/` directory (`3.0 (native)`) built with `dpkg-buildpackage`. `debian/rules` builds the wheel with `uv build` and unpacks it with `python3 -m installer` (sidestepping the un-packageable `uv_build` Rust backend) while `dh_python3` handles dependency calculation, byte-compilation, and the `dist-packages` relocation. A `deb.yml` workflow validates the package on PR/push and attaches it to the release on publish. The package version single-sources from `pyproject.toml` via a generated, gitignored `debian/changelog`.

**Tech Stack:** Debian packaging (debhelper-compat 13, dh-python), `uv`, GitHub Actions, `gh` CLI, Tkinter/Pillow.

**Reference spec:** `docs/superpowers/specs/2026-06-05-deb-packaging-design.md`

**Environment note:** The dev host is NixOS (no `apt`/`dpkg-buildpackage`), but Docker is available, so Task 3 verifies the full build end-to-end in an `ubuntu:24.04` container. Only `gh release upload` (Task 4) is inherently CI-only.

---

## File Structure

**New files**
- `tests/test_cli.py` — unit test for the `--version` flag.
- `debian/control` — source + binary package metadata and dependencies.
- `debian/rules` — build/install via `uv build` + `installer`; desktop validation.
- `debian/copyright` — DEP-5, CC0-1.0 (license text from `LICENSE`).
- `debian/source/format` — `3.0 (native)`.
- `debian/pxv.install` — maps the desktop file + icon into the package tree.
- `debian/pxv.desktop` — launcher with MIME associations.
- `debian/pxv.svg` — placeholder scalable icon.
- `debian/gen-changelog.sh` — generates `debian/changelog` from `pyproject.toml` + `CHANGELOG.md`.
- `.github/workflows/deb.yml` — build/validate + release-upload jobs.

**Modified files**
- `src/pxv/app.py` — add `--version`.
- `.gitignore` — ignore debian build artifacts.
- `CHANGELOG.md` — `[Unreleased]` entry.
- `README.md` — `.deb` install note.

`debian/changelog` is generated, not committed (gitignored).

---

## Task 1: Add `--version` CLI flag

**Files:**
- Test: `tests/test_cli.py` (create)
- Modify: `src/pxv/app.py:276-277`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli.py`:

```python
"""Tests for the pxv command-line entry point.

AIDEV-NOTE: argparse's ``--version`` action prints and raises SystemExit before
``tk.Tk()`` is constructed, so this runs headlessly with no display.
"""

from __future__ import annotations

import pytest

import pxv
from pxv.app import main


def test_version_flag_prints_version_and_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["pxv", "--version"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    output = capsys.readouterr()
    assert f"pxv {pxv.__version__}" in (output.out + output.err)
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL — argparse treats `--version` as an unrecognized argument (SystemExit code 2), so the `code == 0` assertion fails.

- [ ] **Step 3: Add the flag**

In `src/pxv/app.py`, replace:

```python
    parser = argparse.ArgumentParser(description="pxv - A Python xv image viewer")
    parser.add_argument("paths", nargs="*", help="Image files or directories to open")
```

with:

```python
    parser = argparse.ArgumentParser(description="pxv - A Python xv image viewer")
    # AIDEV-NOTE: Imported lazily (not at module top) because app.py is imported
    # during pxv/__init__ before __version__ is assigned — a top-level import
    # would be circular. Mirrors commands.py's local import.
    from pxv import __version__

    parser.add_argument("--version", action="version", version=f"pxv {__version__}")
    parser.add_argument("paths", nargs="*", help="Image files or directories to open")
```

- [ ] **Step 4: Run the test and verify it passes**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Run the full check suite**

Run: `uv run ruff format src/ tests/ && uv run ruff check src/ tests/ && uv run mypy src/pxv/ && uv run pytest`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/pxv/app.py tests/test_cli.py
git commit -m "feat: add --version flag to pxv CLI"
```

---

## Task 2: Create the `debian/` packaging files

**Files:** all under `debian/`, plus `.gitignore`.

- [ ] **Step 1: `debian/control`**

```
Source: pxv
Section: graphics
Priority: optional
Maintainer: Sean Reifschneider <jafo00@gmail.com>
Build-Depends: debhelper-compat (= 13), dh-python, python3-all,
 python3-installer, desktop-file-utils
Standards-Version: 4.7.0
Homepage: https://github.com/linsomniac/pxv
Rules-Requires-Root: no

Package: pxv
Architecture: all
Depends: ${python3:Depends}, ${misc:Depends}, python3-tk, python3-pil.imagetk
Recommends: gnome-screenshot | grim | spectacle
Suggests: xclip | wl-clipboard
Description: Python clone of the classic Unix xv image viewer
 pxv is a lightweight Tkinter image viewer and light editor inspired by John
 Bradley's xv. It supports viewing and navigating a directory of images,
 zoom and pan, cropping, and basic enhancements such as brightness, contrast,
 and filters.
 .
 This package installs the pxv command and a desktop launcher.
```

- [ ] **Step 2: `debian/rules` (must be executable)**

```make
#!/usr/bin/make -f
export PYBUILD_NAME=pxv

WHEELDIR := debian/tmp-wheel

%:
	dh $@ --with python3

override_dh_auto_build:
	rm -rf $(WHEELDIR)
	uv build --wheel --no-cache --out-dir $(WHEELDIR)

override_dh_auto_install:
	python3 -m installer --destdir=debian/pxv --prefix=/usr $(WHEELDIR)/pxv-*.whl

override_dh_install:
	dh_install
	desktop-file-validate debian/pxv/usr/share/applications/pxv.desktop

override_dh_auto_test:
	:

override_dh_clean:
	rm -rf $(WHEELDIR) dist *.egg-info
	dh_clean
```

Then: `chmod +x debian/rules`

> **Indentation:** the recipe lines under each target MUST be real tabs, not spaces, or `make` fails with "missing separator".

- [ ] **Step 3: `debian/source/format`**

```
3.0 (native)
```

(Create the `debian/source/` directory first.)

- [ ] **Step 4: `debian/copyright`** — generate from the repo `LICENSE`:

```bash
{
  cat <<'HDR'
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: pxv
Source: https://github.com/linsomniac/pxv

Files: *
Copyright: 2026 Sean Reifschneider <jafo00@gmail.com>
License: CC0-1.0
HDR
  sed -e 's/[[:space:]]*$//' -e 's/^$/./' -e 's/^/ /' LICENSE
} > debian/copyright
```

This indents every line of the CC0-1.0 text by one space and turns blank lines into ` .`, producing a valid DEP-5 inline license stanza (CC0-1.0 is not in `/usr/share/common-licenses`, so the text must be embedded).

- [ ] **Step 5: `debian/pxv.install`**

```
debian/pxv.desktop usr/share/applications
debian/pxv.svg     usr/share/icons/hicolor/scalable/apps
```

- [ ] **Step 6: `debian/pxv.desktop`**

```ini
[Desktop Entry]
Type=Application
Version=1.0
Name=pxv
GenericName=Image Viewer
Comment=View and manipulate images, a Python clone of xv
Exec=pxv %F
TryExec=pxv
Icon=pxv
Terminal=false
Categories=Graphics;Viewer;2DGraphics;RasterGraphics;
MimeType=image/png;image/jpeg;image/gif;image/bmp;image/tiff;image/webp;
Keywords=image;viewer;photo;picture;xv;
```

- [ ] **Step 7: `debian/pxv.svg`** (placeholder icon)

```svg
<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256" role="img" aria-label="pxv image viewer">
  <defs>
    <clipPath id="photo">
      <rect x="44" y="60" width="168" height="136" rx="10"/>
    </clipPath>
  </defs>
  <rect x="24" y="40" width="208" height="176" rx="20" fill="#2b6cb0"/>
  <rect x="44" y="60" width="168" height="136" rx="10" fill="#ebf4ff"/>
  <g clip-path="url(#photo)">
    <circle cx="92" cy="102" r="20" fill="#f6ad55"/>
    <path d="M44 196 L104 130 L150 176 L178 150 L212 184 L212 196 Z" fill="#38a169"/>
    <path d="M44 196 L100 148 L140 196 Z" fill="#2f855a"/>
  </g>
</svg>
```

- [ ] **Step 8: `debian/gen-changelog.sh` (must be executable)**

```sh
#!/bin/sh
# Generate debian/changelog from pyproject.toml version + CHANGELOG.md body.
# The deb version is single-sourced from pyproject.toml; the entry body is the
# matching "## [x.y.z]" section of CHANGELOG.md, with Keep-a-Changelog markup
# flattened into Debian "  * " bullets.
set -eu
cd "$(dirname "$0")/.."

VERSION=$(grep -m1 -E '^version = ' pyproject.toml | sed -E 's/version = "([^"]+)".*/\1/')
DEBFULLNAME=${DEBFULLNAME:-Sean Reifschneider}
DEBEMAIL=${DEBEMAIL:-jafo00@gmail.com}
DATE=$(date -R)

BODY=$(awk -v ver="$VERSION" '
  $0 ~ "^## \\[" ver "\\]" { grab=1; next }
  grab && /^## \[/ { exit }
  grab {
    if ($0 ~ /^### /) next
    if ($0 ~ /^[[:space:]]*$/) next
    if ($0 ~ /^- /) { if (cur != "") print "  * " cur; cur = substr($0, 3) }
    else { sub(/^[[:space:]]+/, "", $0); cur = (cur == "" ? $0 : cur " " $0) }
  }
  END { if (cur != "") print "  * " cur }
' CHANGELOG.md)

[ -n "$BODY" ] || BODY="  * Release ${VERSION}."

mkdir -p debian
{
  printf 'pxv (%s) unstable; urgency=medium\n\n' "$VERSION"
  printf '%s\n\n' "$BODY"
  printf ' -- %s <%s>  %s\n' "$DEBFULLNAME" "$DEBEMAIL" "$DATE"
} > debian/changelog
```

Then: `chmod +x debian/gen-changelog.sh`

- [ ] **Step 9: `.gitignore` — append the debian build artifacts block**

```
# Debian build artifacts
/debian/changelog
/debian/tmp-wheel/
/debian/pxv/
/debian/.debhelper/
/debian/files
/debian/debhelper-build-stamp
/debian/*.substvars
/debian/*.debhelper.log
```

- [ ] **Step 10: Sanity-check the generator locally**

Run: `./debian/gen-changelog.sh && cat debian/changelog`
Expected: a well-formed entry headed `pxv (1.0.1) unstable; urgency=medium`, with `  * ` bullets drawn from the `## [1.0.1]` section of `CHANGELOG.md`, and a trailer ` -- Sean Reifschneider <jafo00@gmail.com>  <RFC-2822 date>`. (The generated `debian/changelog` is gitignored — leave it in place for Task 3.)

- [ ] **Step 11: Commit**

```bash
git add debian/ .gitignore
git commit -m "build: add native Debian packaging (debian/ dir, desktop integration)"
```

(`git add debian/` will not stage the gitignored `debian/changelog`.)

---

## Task 3: Verify the full deb build end-to-end (Docker)

This is the real test for Task 2 — it reproduces what `deb.yml`'s `build` job does, in a clean `ubuntu:24.04` container. The host repo is mounted read-only and copied into the container, so no root-owned files leak into the working tree.

**Files:** none (verification only).

- [ ] **Step 1: Build, lint, install, and smoke-test in a container**

Run (from the repo root):

```bash
docker run --rm -v "$PWD":/src:ro ubuntu:24.04 bash -euxc '
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends \
    debhelper dh-python python3-all python3-installer \
    desktop-file-utils devscripts lintian ca-certificates curl
  mkdir /build
  tar -C /src -c \
    --exclude=.git --exclude=.venv --exclude=__pycache__ \
    --exclude=.mypy_cache --exclude=.ruff_cache --exclude=dist . \
    | tar -C /build -x
  cd /build
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="/root/.local/bin:$PATH"
  ./debian/gen-changelog.sh
  dpkg-parsechangelog -l debian/changelog
  dpkg-buildpackage -us -uc -b
  DEB=$(ls /pxv_*_all.deb)
  echo "=== Built: $DEB ==="
  dpkg-deb --info "$DEB"
  dpkg-deb --contents "$DEB"
  dpkg-deb --contents "$DEB" | grep -E " \./usr/bin/pxv$"
  dpkg-deb --contents "$DEB" | grep -E "\.desktop$"
  dpkg-deb --contents "$DEB" | grep -E "/icons/.*\.svg$"
  lintian -I --pedantic "$DEB" || true
  lintian --fail-on error --suppress-tags no-manual-page "$DEB"
  apt-get install -y "$DEB"
  command -v pxv
  head -1 "$(command -v pxv)"
  python3 -c "import pxv, tkinter, PIL.ImageTk; print(\"imports OK\")"
  pxv --version
  pxv --help
  test -f /usr/share/applications/pxv.desktop
  test -f /usr/share/icons/hicolor/scalable/apps/pxv.svg
  echo "=== VERIFICATION OK ==="
'
```

Expected:
- `dpkg-deb --info` shows `Architecture: all` and `Depends:` including `python3-tk` and `python3-pil.imagetk`.
- The contents include `/usr/bin/pxv`, `/usr/share/applications/pxv.desktop`, `/usr/share/icons/hicolor/scalable/apps/pxv.svg`.
- `head -1 $(command -v pxv)` is `#!/usr/bin/python3` (dh_python3 normalized the shebang).
- `lintian --fail-on error ...` exits 0 (warnings are fine).
- `pxv --version` prints `pxv 1.0.1`; the run ends with `=== VERIFICATION OK ===`.

- [ ] **Step 2: If anything fails, fix the `debian/` files and re-run**

Common fixes:
- A `make` "missing separator" error → `debian/rules` recipe lines must be tabs.
- A lintian **error** (not warning) → address the specific tag; if it is a spurious-but-correct case, add `debian/source/lintian-overrides` with the tag and a comment, then `git add` it.
- `desktop-file-validate` failure → fix the `.desktop` key it names.

Re-run Step 1 until it ends with `VERIFICATION OK`. Amend the Task 2 commit with any fixes:

```bash
git add debian/
git commit --amend --no-edit
```

---

## Task 4: Add the `deb.yml` workflow

**Files:**
- Create: `.github/workflows/deb.yml`

- [ ] **Step 1: Create the workflow**

```yaml
name: Debian package

on:
  release:
    types: [published]
  pull_request:
  push:
    branches: [main]

# Least privilege by default; only the upload job opts into contents: write.
permissions:
  contents: read

jobs:
  build:
    name: Build & validate .deb
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false

      - name: Install uv
        uses: astral-sh/setup-uv@v5

      - name: Install Debian build tooling
        run: |
          sudo apt-get update
          sudo apt-get install -y --no-install-recommends \
            debhelper dh-python python3-all python3-installer \
            desktop-file-utils devscripts lintian

      - name: Verify tag matches project version
        if: github.event_name == 'release'
        run: |
          PROJECT_VERSION=$(grep -m1 -E '^version = ' pyproject.toml | sed -E 's/version = "([^"]+)".*/\1/')
          TAG="${GITHUB_REF##*/}"
          TAG_VERSION="${TAG#v}"
          if [ "$PROJECT_VERSION" != "$TAG_VERSION" ]; then
            echo "Tag version ($TAG_VERSION) != pyproject version ($PROJECT_VERSION)" >&2
            exit 1
          fi

      - name: Generate debian/changelog
        run: ./debian/gen-changelog.sh

      - name: Build .deb
        run: dpkg-buildpackage -us -uc -b

      - name: Collect artifact
        run: |
          mkdir -p dist
          mv ../pxv_*_all.deb dist/

      - name: Inspect package
        run: |
          set -euxo pipefail
          DEB=$(ls dist/pxv_*_all.deb)
          dpkg-deb --info "$DEB"
          dpkg-deb --contents "$DEB"
          dpkg-deb --contents "$DEB" | grep -E ' \./usr/bin/pxv$'
          dpkg-deb --contents "$DEB" | grep -E '\.desktop$'
          dpkg-deb --contents "$DEB" | grep -E '/icons/.*\.svg$'

      - name: Lintian
        run: |
          set -euxo pipefail
          DEB=$(ls dist/pxv_*_all.deb)
          lintian -I --pedantic "$DEB" || true
          lintian --fail-on error --suppress-tags no-manual-page "$DEB"

      - name: Install with dependency resolution
        env:
          DEBIAN_FRONTEND: noninteractive
        run: |
          set -euxo pipefail
          sudo apt-get update
          sudo apt-get install -y "./$(ls dist/pxv_*_all.deb)"

      - name: Smoke test (headless)
        run: |
          set -euxo pipefail
          command -v pxv
          test -x /usr/bin/pxv
          python3 -c "import pxv, tkinter, PIL.ImageTk; print('imports OK')"
          pxv --version
          pxv --help
          test -f /usr/share/applications/pxv.desktop

      - name: Upload workflow artifact
        uses: actions/upload-artifact@v4
        with:
          name: deb
          path: dist/pxv_*_all.deb

  upload:
    name: Attach .deb to release
    needs: build
    if: ${{ github.event_name == 'release' }}
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - name: Download artifact
        uses: actions/download-artifact@v4
        with:
          name: deb
          path: dist/

      - name: Upload to release
        env:
          GH_TOKEN: ${{ github.token }}
        run: gh release upload "${{ github.event.release.tag_name }}" dist/pxv_*_all.deb --clobber
```

- [ ] **Step 2: Validate the YAML**

Run: `uv run python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/deb.yml')); print('deb.yml OK')"`
Expected: `deb.yml OK`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/deb.yml
git commit -m "ci: build the .deb and attach it to GitHub releases"
```

---

## Task 5: Update docs

**Files:**
- Modify: `CHANGELOG.md` (the `## [Unreleased]` section)
- Modify: `README.md` (after the quickstart usage block, before `## Keyboard Shortcuts`)

- [ ] **Step 1: `CHANGELOG.md` — fill in the `[Unreleased]` section**

Replace:

```
## [Unreleased]
```

with:

```
## [Unreleased]

### Added

- `--version` command-line flag that prints the installed version and exits.
- A native Debian package (`.deb`), built in CI and attached to each GitHub
  release. Installs the `pxv` command plus a desktop launcher, scalable icon,
  and "Open with" associations for common image formats.
```

- [ ] **Step 2: `README.md` — add an install subsection**

After the usage block that ends with:

```
pxv                        # open file dialog
```
```

insert (before `## Keyboard Shortcuts`):

```markdown
### Debian / Ubuntu (.deb)

Each [GitHub release](https://github.com/linsomniac/pxv/releases) includes a
`pxv_<version>_all.deb`. Install it (apt pulls in `python3-tk` and Pillow):

```sh
sudo apt install ./pxv_1.0.1_all.deb
```

It targets current distributions (Debian 13 / Ubuntu 24.04 or newer, which ship
Pillow ≥ 10). After installing, `pxv` is on your `PATH` and appears in the
applications menu and image "Open with" lists.
```
```

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md README.md
git commit -m "docs: document the .deb install and --version flag"
```

---

## Self-Review

**Spec coverage:**
- Native `debian/` build with `uv build` + `installer` → Task 2 (`control`, `rules`), verified in Task 3. ✓
- `Architecture: all`, `3.0 (native)`, manual `python3-tk`/`python3-pil.imagetk` deps → Task 2 (`control`, `source/format`); asserted in Task 3. ✓
- Desktop integration (`.desktop` + SVG + MIME, no maintainer scripts) → Task 2 (steps 5–7), `pxv.install`; validated by `desktop-file-validate` in `rules` and Task 3. ✓
- Generated, gitignored `debian/changelog` single-sourced from `pyproject.toml` → Task 2 (steps 8–9), exercised in Tasks 2/3. ✓
- `--version` flag (lazy import to avoid circular import) → Task 1. ✓
- `deb.yml`: validate on PR/push, attach on release; least-privilege `contents: write` only on the `upload` job; `gh release upload` → Task 4. ✓
- Docs (CHANGELOG, README) → Task 5. ✓
- Risk: stale-wheel glob (dedicated `WHEELDIR`), distro Pillow floor (documented target), lintian gating (errors only + suppress `no-manual-page`) → encoded in Tasks 2/3/4. ✓

**Placeholder scan:** No TBD/TODO; every file's full content is present; the CC0 text is produced from `LICENSE` by a concrete command. ✓

**Type consistency:** `__version__` (from `pxv`) is referenced consistently in Task 1 code and the Task 1 test; package/binary name `pxv` is consistent across `control`, `rules`, `pxv.install`, `gen-changelog.sh`, and the workflow's `pxv_*_all.deb` glob. ✓
