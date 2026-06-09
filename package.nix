# AIDEV-NOTE: The pxv derivation. Single source of truth for packaging, reused by
# both flake.nix and the legacy default.nix shim. Builds from the local repo
# source (no fetchPypi / hash to bump) so it tracks whatever ref is checked out.
#
# callPackage-style: `pkgs.callPackage ./package.nix { }`.

{ lib
, python3Packages
}:

python3Packages.buildPythonApplication rec {
  pname = "pxv";

  # AIDEV-NOTE: Single-source the version from pyproject.toml so it can't drift
  # from a hard-coded literal (mirrors how src/pxv/__init__.py reads it back from
  # the installed metadata). A release bump in pyproject.toml is all that's needed.
  version = (lib.importTOML ./pyproject.toml).project.version;

  pyproject = true;

  # AIDEV-NOTE: Restrict the build source to just what the wheel needs. Without
  # this, .venv/, dist/, and the various *_cache dirs would be copied into the
  # store (bloat) and any change to them would needlessly invalidate the build.
  # debian/pxv.{desktop,svg} are pulled in for the postInstall desktop integration.
  src = lib.fileset.toSource {
    root = ./.;
    fileset = lib.fileset.unions [
      ./pyproject.toml
      ./README.md
      ./LICENSE
      ./src
      ./debian/pxv.desktop
      ./debian/pxv.svg
    ];
  };

  # AIDEV-NOTE: pxv's pyproject.toml declares `uv_build` as its PEP 517 backend,
  # but nixpkgs lags on uv-build (and pins are strict). pxv has no uv-build-specific
  # config -- it's a plain src-layout pure-Python package -- so we swap the backend
  # to hatchling at build time. The appended [tool.hatch.build.targets.wheel] block
  # tells hatchling which source directory to include. If the --replace-fail lines
  # start failing, re-check the exact strings against pyproject.toml's [build-system].
  postPatch = ''
    substituteInPlace pyproject.toml \
      --replace-fail 'requires = ["uv_build>=0.11.1,<0.12.0"]' 'requires = ["hatchling"]' \
      --replace-fail 'build-backend = "uv_build"' 'build-backend = "hatchling.build"'
    printf '\n[tool.hatch.build.targets.wheel]\npackages = ["src/pxv"]\n' >> pyproject.toml
  '';

  build-system = with python3Packages; [ hatchling ];

  dependencies = with python3Packages; [
    pillow
    tkinter
  ];

  # AIDEV-NOTE: The test suite drives real Tk widgets and needs an X display, which
  # the sandbox doesn't provide (see memory: pxv Tk tests need Xvfb). Importing the
  # package, however, only imports tkinter (no Tk() root), so it's a safe smoke test.
  doCheck = false;
  pythonImportsCheck = [ "pxv" ];

  # AIDEV-NOTE: Install the freedesktop .desktop entry and scalable icon (shared
  # with the Debian packaging) so pxv shows up in application launchers and image
  # "Open with" menus on NixOS. Icon=pxv in the .desktop resolves to pxv.svg below.
  postInstall = ''
    install -Dm644 debian/pxv.desktop $out/share/applications/pxv.desktop
    install -Dm644 debian/pxv.svg \
      $out/share/icons/hicolor/scalable/apps/pxv.svg
  '';

  meta = {
    description = "A Python clone of the classic Unix xv image viewer";
    homepage = "https://github.com/linsomniac/pxv";
    changelog = "https://github.com/linsomniac/pxv/blob/main/CHANGELOG.md";
    license = lib.licenses.cc0;
    mainProgram = "pxv";
    platforms = lib.platforms.unix;
  };
}

# vim: ts=2 sw=2 ai et
