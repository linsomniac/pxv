# Nix packaging for pxv — design

**Date:** 2026-06-08
**Status:** Implemented

## Goal

Provide first-class Nix packaging for pxv that is easy for NixOS users to consume,
using `/etc/nixos/pxv.nix` (a `fetchPypi`-based out-of-tree derivation) as
inspiration but adapting it for in-repo, source-tracking packaging.

## Decisions

- **Format:** Flake (primary) + a legacy `default.nix` shim, both delegating to a
  single `package.nix` derivation. Covers flake users (`nix run`, `nix profile`,
  overlay) and non-flake users (`nix-build`) without duplicating the derivation.
- **Source:** Build from the local repo via `lib.fileset.toSource` (not
  `fetchPypi`). Tracks whatever ref is checked out; no source hash to bump.
- **Extras:** Overlay only. No dev shell and no NixOS module — for a GUI viewer a
  module would only add the package to `systemPackages`, which the overlay +
  `environment.systemPackages` already covers, and the `.desktop` file handles
  launcher/MIME integration.

## Files

| File | Purpose |
|------|---------|
| `package.nix` | The derivation, `callPackage`-style (`{ lib, python3Packages }`). Single source of truth. |
| `flake.nix` | `inputs.nixpkgs`; outputs `packages.{default,pxv}`, `apps.{default,pxv}`, `overlays.default` across linux + darwin. |
| `default.nix` | `{ pkgs ? import <nixpkgs> {} }: pkgs.callPackage ./package.nix {}` so `nix-build` works without flakes. |

## `package.nix` details

- `version` read from `pyproject.toml` via `lib.importTOML` — single-sourced, no
  drift on release bumps (mirrors how `src/pxv/__init__.py` reads it back).
- `src` via `lib.fileset.toSource` limited to `pyproject.toml`, `README.md`,
  `LICENSE`, `src/`, and `debian/pxv.{desktop,svg}` — keeps `.venv`/`dist`/caches
  out of the store and avoids spurious rebuilds.
- `postPatch` swaps the `uv_build` PEP 517 backend → `hatchling` (nixpkgs lags on
  uv-build; pxv has no uv-build-specific config), appending a
  `[tool.hatch.build.targets.wheel]` block pointing at `src/pxv`. Same proven
  approach as `/etc/nixos/pxv.nix`.
- `dependencies = [ pillow tkinter ]`; `build-system = [ hatchling ]`.
- `doCheck = false` (Tk tests need an X display the sandbox lacks);
  `pythonImportsCheck = [ "pxv" ]` as a no-display smoke test (importing only
  imports `tkinter`, it does not create a `Tk()` root).
- `postInstall` installs the shared Debian `.desktop` entry and scalable icon into
  `share/applications` and `share/icons/hicolor/scalable/apps` so pxv shows up in
  launchers and "Open with" menus.
- `meta`: `mainProgram = "pxv"`, `license = cc0`, `platforms.unix`.

## Verification

- `nix-build --no-out-link` → builds, `pythonImportsCheck` passes, binary +
  `.desktop` + icon present in the output.
- `nix build .#pxv` → builds against the flake-pinned nixpkgs.
- `nix flake check` → all outputs (packages, apps, overlays) evaluate; no warnings.
- `nix run .#pxv -- --help` / `--version` → runs the app; `--version` reports the
  version read from `pyproject.toml` (`pxv 1.0.4`).
