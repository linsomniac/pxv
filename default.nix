# AIDEV-NOTE: Legacy (non-flake) entry point so `nix-build` and `nix-shell -p`
# work without flakes enabled. Delegates to package.nix, the single source of
# truth shared with flake.nix.
{ pkgs ? import <nixpkgs> { } }:

pkgs.callPackage ./package.nix { }

# vim: ts=2 sw=2 ai et
