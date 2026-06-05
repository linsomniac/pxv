# Design: Debian packaging + GitHub Release publishing for pxv

- **Date:** 2026-06-05
- **Status:** Approved (design); pending implementation plan
- **Author:** Sean Reifschneider (with Claude)

## Goal

Build a native Debian package (`.deb`) for `pxv` in GitHub Actions and attach it
as an asset to the GitHub release. The package is a properly-formed, lintian-clean
native Debian package named `pxv` (it is an application, not a library, so no
`python3-` prefix), with full desktop integration (launcher + icon + MIME
registration).

### In scope

- A maintained `debian/` directory built with `dpkg-buildpackage`.
- `Architecture: all` package (pure-Python, no compiled extensions).
- Desktop integration: `.desktop` launcher, scalable SVG icon, MIME-type
  registration for common image formats.
- A `deb.yml` workflow that **validates** the package on PRs/pushes and
  **attaches** it to the release on publish.
- A `--version` CLI flag on `pxv` (improves the package smoke test and is
  expected hygiene for an installed command).

### Out of scope (future work)

- Hosting an apt repository (reprepro/aptly) or a Launchpad PPA.
- Submission to the official Debian/Ubuntu archive (that would require switching
  the source format from `3.0 (native)` to `3.0 (quilt)` with a sponsor).
- RPM or other distro packaging.
- A `man` page (we instead suppress lintian's `no-manual-page`).

## Confirmed decisions

| Decision | Choice |
| --- | --- |
| Build mechanism | `debian/rules` calls `uv build` directly + `installer`; **not** pybuild's pyproject plugin (the `uv_build` backend is a Rust shim, not apt-installable). `dh_python3` still computes deps / byte-compiles / relocates to `dist-packages`. |
| Package name | `pxv` (application, not a library). |
| Source format | `3.0 (native)` — we are upstream, packaging lives in-tree, version is plain `1.0.1` (no Debian revision). |
| Architecture | `all`. |
| Workflow triggers | Build + validate on `pull_request` and `push` to `main`; additionally attach to the release on `release: published`. |
| `debian/changelog` | Generated in CI from `pyproject.toml` version + `CHANGELOG.md` body; gitignored (single-sourced, zero drift). |
| `--version` flag | Add it to `pxv` as part of this work. |
| Release upload | `gh` CLI (`gh release upload`), least-privilege (`contents: write` only on the upload job). |

## Background facts (verified)

- Runtime imports: `tkinter` (+ `ttk`, `filedialog`, `messagebox`) and from
  Pillow `Image, ImageEnhance, ImageFilter, ImageChops, ImageOps, ImageTk,
  ImageGrab`. Entry point `pxv = "pxv:main"`.
- The `uv_build` PEP 517 backend published on PyPI as `uv-build` is a thin shim
  that shells out to a per-arch Rust binary; it is **not** in the Debian/Ubuntu
  archive. Calling `uv build` directly (with `uv` on `PATH`) invokes the bundled
  backend cleanly and produces a standard `pxv-<ver>-py3-none-any.whl`. This was
  verified end-to-end against this repo.
- `${python3:Depends}` (from `dh_python3`) maps the `pillow` requirement to
  `python3-pil` automatically. `tkinter` is stdlib (no dist metadata) and
  `PIL.ImageTk` lives in the separate `python3-pil.imagetk` apt package, so both
  must be added to `Depends` **manually**.
- Shipping a hicolor SVG icon and a `/usr/share/applications/*.desktop` file
  needs **no maintainer scripts**: the `hicolor-icon-theme` and
  `desktop-file-utils` dpkg triggers rebuild the caches automatically.
- `pxv --help` and `pxv --version` (argparse) exit before `tk.Tk()` is ever
  constructed, so they are safe to run headlessly in CI (no Xvfb needed).
- Debian's Python uses the `posix_local` sysconfig scheme by default, so
  `python3 -m installer --prefix=/usr` installs under `/usr/local` unless
  `DEB_PYTHON_INSTALL_LAYOUT=deb_system` is set (verified end-to-end in a
  container build). `dpkg-buildpackage` also needs `build-essential`, which is
  preinstalled on GitHub runners but added explicitly to the workflow.
- `app.py` is imported by `pxv/__init__` **before** `__version__` is assigned,
  so `--version` must import `__version__` lazily inside `main()` (mirroring
  `commands.py:361`), not at module top, to avoid a circular import.

## File manifest

### New files

```
debian/control
debian/rules                (executable)
debian/copyright
debian/source/format
debian/pxv.install
debian/pxv.desktop
debian/pxv.svg              (placeholder icon, replaceable)
debian/gen-changelog.sh     (executable)
.github/workflows/deb.yml
```

### Modified files

```
src/pxv/app.py              (add --version flag)
.gitignore                  (ignore debian build artifacts)
CHANGELOG.md                (add an [Unreleased] entry)
README.md                   (note the .deb attached to releases)
```

`debian/changelog` is **generated** by CI and is **not** committed (gitignored).

## Detailed design

### `debian/control`

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

- `python3-pil.imagetk` transitively pulls `python3-pil` and `python3-tk`, but
  `python3-tk` is listed explicitly for clarity/robustness.
- `Recommends`/`Suggests` cover the optional `ImageGrab` screen-capture and
  clipboard-paste paths; they are not required for the app to import or launch.
- `uv` is **not** a `Build-Depends` (it is not in the apt archive); CI provides
  it on `PATH` via `astral-sh/setup-uv`. Local builds require `uv` installed.

### `debian/rules`

```make
#!/usr/bin/make -f
export PYBUILD_NAME=pxv

# Debian's patched Python defaults to the "posix_local" sysconfig scheme, so
# `installer --prefix=/usr` would drop files under /usr/local (tripping
# dh_usrlocal). Force the system layout (/usr/bin + /usr/lib/python3/dist-packages).
export DEB_PYTHON_INSTALL_LAYOUT = deb_system

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

- A dedicated `WHEELDIR` (cleaned each build) avoids a multi-wheel glob if the
  repo's gitignored `dist/` already contains stale wheels — important for local
  builds.
- `dh ... --with python3` runs `dh_python3`, which relocates
  `site-packages → dist-packages`, byte-compiles, normalizes the `/usr/bin/pxv`
  shebang to `#!/usr/bin/python3`, and fills `${python3:Depends}`.
- `override_dh_auto_test` is a no-op: the pytest suite is not run during the
  package build.

### `debian/pxv.install`

```
debian/pxv.desktop usr/share/applications
debian/pxv.svg     usr/share/icons/hicolor/scalable/apps
```

### `debian/pxv.desktop`

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

- `Exec` **must** contain `%F` because `MimeType` is set (otherwise lintian
  raises `desktop-mime-but-no-exec-code` and file managers cannot pass the file).
- `Icon=pxv` is a bare name (no path, no extension) so the theme resolves it to
  `hicolor/scalable/apps/pxv.svg`. The icon filename stem must equal `pxv`.
- `MimeType` lists pxv in "Open with" without seizing the default handler (we do
  **not** ship a `mimeapps.list`, which would override user/admin preference).
- `desktop-file-validate` runs at build time (see `debian/rules`).

### `debian/pxv.svg` (placeholder icon)

A simple, clean scalable SVG (e.g. a stylized framed photo/landscape glyph) of
nominal 256×256 viewBox, committed to the repo. It is explicitly a placeholder
that can be replaced with a nicer icon at any time without touching anything else.

### `debian/source/format`

```
3.0 (native)
```

### `debian/copyright`

Machine-readable DEP-5 format declaring `License: CC0-1.0`. Because CC0-1.0 is
**not** in `/usr/share/common-licenses`, the full CC0-1.0 legal text (copied
from the repo `LICENSE` file) is embedded in the license stanza to keep lintian
happy.

```
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: pxv
Source: https://github.com/linsomniac/pxv

Files: *
Copyright: 2026 Sean Reifschneider <jafo00@gmail.com>
License: CC0-1.0
 <full CC0-1.0 text here>
```

### `debian/gen-changelog.sh`

Generates a valid `debian/changelog`, single-sourcing the version from
`pyproject.toml` and the entry body from the matching `## [x.y.z]` section of
`CHANGELOG.md` (Keep-a-Changelog markup flattened to Debian `  * ` bullets;
wrapped continuation lines are joined; `### Added/Changed/...` subheaders are
dropped). Falls back to `* Release <version>.` if the section is empty.

```sh
#!/bin/sh
# Generate debian/changelog from pyproject.toml version + CHANGELOG.md body.
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

Debian changelog spacing is strict (one space before ` -- `, two spaces before
the date, two-space-indented change lines, `date -R` format); the script above
honors it. Verify with `dpkg-parsechangelog -l debian/changelog`.

### `src/pxv/app.py` — add `--version`

Inside `main()` (before the existing arguments), import `__version__` lazily and
register the flag:

```python
def main() -> None:
    from pxv import __version__  # local import: avoids circular import at module load

    parser = argparse.ArgumentParser(description="pxv - A Python xv image viewer")
    parser.add_argument("--version", action="version", version=f"pxv {__version__}")
    # ... existing "paths" argument ...
```

`action="version"` prints and exits before any Tk window is created, so it is
safe headlessly and in the CI smoke test.

### `.gitignore` additions

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

### `.github/workflows/deb.yml`

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
          lintian -I --pedantic "$DEB" || true            # informational, non-blocking
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

The existing `release.yml` (PyPI publishing) is unchanged; the deb pipeline lives
entirely in `deb.yml`.

## Local build

```sh
./debian/gen-changelog.sh
dpkg-buildpackage -us -uc -b        # requires uv, debhelper, dh-python, python3-installer
```

The `.deb` lands in the parent directory (`../pxv_<version>_all.deb`).

## Acceptance criteria

1. On PR/push: the `build` job is green — produces `pxv_<version>_all.deb`,
   `lintian --fail-on error` passes, the package installs with dependency
   resolution, and the headless smoke test (`pxv --version`, `pxv --help`,
   `import pxv, tkinter, PIL.ImageTk`) passes.
2. `dpkg-deb --info` shows `Architecture: all` and `Depends:` including
   `python3-tk` and `python3-pil.imagetk`.
3. The installed package provides `/usr/bin/pxv`,
   `/usr/share/applications/pxv.desktop`, and
   `/usr/share/icons/hicolor/scalable/apps/pxv.svg`, and the launcher appears in
   the desktop application menu.
4. On `release: published`: the `upload` job attaches `pxv_<version>_all.deb` to
   the triggering release.
5. `pxv --version` prints `pxv <version>` and exits 0 without opening a window.

## Risks and mitigations

- **`uv` not apt-installable.** CI installs it via `astral-sh/setup-uv`; local
  builds require it. Documented; the build fails clearly if `uv` is absent.
- **Stale wheels in `dist/`.** Mitigated by building into a cleaned `WHEELDIR`.
- **Distro Pillow floor.** The package declares `pillow>=10.0`. Debian 12
  (bookworm) ships `python3-pil` 9.4 and would not satisfy a versioned dep;
  Debian 13 (trixie) and Ubuntu 24.04 (noble) ship ≥10 and are fine. The `.deb`
  effectively targets trixie/noble and newer; bookworm support is out of scope
  (would need backports or a floor change). Documented, no pyproject change.
- **lintian noise on a non-debhelper-idiomatic build.** Gate on errors only
  (`--fail-on error`), suppress `no-manual-page`, and run an informational
  `-I --pedantic` pass that never blocks. Add a `debian/source/lintian-overrides`
  only if a specific spurious error appears.
- **Release-asset name collision on re-runs.** `gh release upload --clobber`
  makes the upload idempotent.

## References

Key sources from the pre-design research sweep:

- uv build backend: <https://pypi.org/project/uv-build/>,
  <https://docs.astral.sh/uv/concepts/build-backend/>
- dh-python / pybuild: <https://manpages.debian.org/testing/dh-python/pybuild.1.en.html>,
  <https://debian-python.readthedocs.io/en/latest/dh_python.html>
- Desktop integration / triggers: <https://manpages.debian.org/unstable/debhelper/dh_icons.1.en.html>,
  <https://wiki.debian.org/MimeTypesSupport>
- Dependency package names: <https://packages.ubuntu.com/noble/python3-pil.imagetk>
- Source format: <https://wiki.debian.org/Projects/DebSrc3.0>
- changelog format: <https://manpages.debian.org/unstable/dpkg-dev/deb-changelog.5.en.html>
- Release upload: <https://cli.github.com/manual/gh_release_upload>,
  <https://docs.github.com/actions/security-guides/automatic-token-authentication>
```
