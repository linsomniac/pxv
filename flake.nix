{
  description = "pxv - a Python clone of the classic Unix xv image viewer";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      # AIDEV-NOTE: pxv supports Linux and macOS (tkinter works on both via
      # nixpkgs). Drop entries here if you want to narrow platform support.
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      pkgsFor = system: nixpkgs.legacyPackages.${system};
    in
    {
      packages = forAllSystems (system:
        let pkgs = pkgsFor system; in
        rec {
          pxv = pkgs.callPackage ./package.nix { };
          default = pxv;
        });

      # AIDEV-NOTE: `nix run github:linsomniac/pxv -- photo.jpg` and
      # `nix run github:linsomniac/pxv#pxv`. program resolves via meta.mainProgram.
      apps = forAllSystems (system:
        let pkg = self.packages.${system}.pxv; in
        rec {
          pxv = {
            type = "app";
            program = nixpkgs.lib.getExe pkg;
            meta = { inherit (pkg.meta) description homepage license mainProgram; };
          };
          default = pxv;
        });

      # AIDEV-NOTE: Add this to a NixOS / home-manager config's nixpkgs.overlays
      # to get `pkgs.pxv`:
      #   nixpkgs.overlays = [ inputs.pxv.overlays.default ];
      #   environment.systemPackages = [ pkgs.pxv ];
      overlays.default = final: _prev: {
        pxv = final.callPackage ./package.nix { };
      };
    };
}

# vim: ts=2 sw=2 ai et
