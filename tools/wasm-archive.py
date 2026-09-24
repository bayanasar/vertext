#!/usr/bin/env python3
"""Build the archive a browser host takes vertext-wasm from (#46).

    vertext-wasm-<version>.zip
      vertext.mjs
      vertext.wasm

The module and its glue are two halves of one release, like the Quarto filter
and the binary, and they travel as two files. So they ship together, attached
to the tagged release beside `vertext-quarto-<version>.zip`, and the glue
refuses a module whose MAJOR.MINOR is not its own `WIRE_VERSION`. The crate is
`publish = false`: a C-ABI `.wasm` has no business going out through crates.io,
and this archive is the one official place to take it from.

The builder refuses to write the archive when

- the glue's `WIRE_VERSION` is not the MAJOR.MINOR of the crate version,
- the module does not load through the glue, which runs the handshake itself,
- or the module still carries a path from the machine that built it.

The last one is not hypothetical. A release `.wasm` keeps the source location
of every panic site, and for dependencies that is the absolute path of the
crate under `$CARGO_HOME` -- a build-machine home directory, in a published
file. The module is built here with those prefixes remapped, into its own
target directory so the development build is left alone, and then checked.

The zip is reproducible in the same way as the filter's: sorted entries, fixed
timestamps, constant permissions. With the paths remapped the module no longer
depends on where the checkout or the cargo home is, so one toolchain gives one
sha256 on any machine.

Usage
-----
    python3 tools/wasm-archive.py              # writes target/wasm-archive/
    python3 tools/wasm-archive.py --out DIR
"""

import argparse
import hashlib
import os
import pathlib
import re
import subprocess
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
GLUE = ROOT / "examples" / "wasm" / "vertext.mjs"
TARGET = ROOT / "target" / "wasm-archive-build"
MODULE = TARGET / "wasm32-unknown-unknown" / "release" / "vertext_wasm.wasm"
# The names a host gets from the archive. tools/wasm-caret.py serves the demo
# under the same ones.
GLUE_NAME = "vertext.mjs"
MODULE_NAME = "vertext.wasm"
# 1980-01-01 is the earliest time a zip entry can carry.
EPOCH = (1980, 1, 1, 0, 0, 0)


def versions():
    cargo = re.search(r'^\[workspace\.package\][^\[]*?^version\s*=\s*"([^"]+)"',
                      (ROOT / "Cargo.toml").read_text(encoding="utf-8"),
                      re.MULTILINE | re.DOTALL)
    wire = re.search(r"^export const WIRE_VERSION = '([^']+)';$",
                     GLUE.read_text(encoding="utf-8"), re.MULTILINE)
    return cargo and cargo.group(1), wire and wire.group(1)


def build():
    home = pathlib.Path.home()
    cargo_home = pathlib.Path(os.environ.get("CARGO_HOME", home / ".cargo")).resolve()
    flags = [f"--remap-path-prefix={cargo_home}=/cargo",
             f"--remap-path-prefix={ROOT}=/vertext"]
    env = dict(os.environ, CARGO_ENCODED_RUSTFLAGS="\x1f".join(flags))
    env.pop("RUSTFLAGS", None)
    subprocess.run(["cargo", "build", "--release", "--quiet", "-p", "vertext-wasm",
                    "--target", "wasm32-unknown-unknown", "--target-dir", str(TARGET)],
                   cwd=ROOT, env=env, check=True)
    # What must not survive: the paths just remapped, and any home directory.
    # A container may run with HOME=/, which would match every module.
    paths = [str(p).encode() for p in (cargo_home, ROOT, home) if str(p) != "/"]
    return paths + [b"/home/", b"/Users/", b"/root/"]


def handshake():
    """The version the module reports through the glue's own load()."""
    script = ("import { readFileSync } from 'node:fs';"
              f"const {{ load }} = await import({GLUE.as_uri()!r});"
              f"console.log((await load(readFileSync({str(MODULE)!r}))).version);")
    done = subprocess.run(["node", "--input-type=module", "-e", script],
                          capture_output=True, text=True)
    if done.returncode != 0:
        sys.exit(f"the module does not load through the glue:\n{done.stderr.strip()[-600:]}")
    return done.stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "target" / "wasm-archive"))
    args = ap.parse_args()

    version, wire = versions()
    if not (version and wire):
        sys.exit(f"could not read the versions: Cargo.toml {version}, WIRE_VERSION {wire}")
    if not version.startswith(wire + "."):
        sys.exit(f"the version declarations disagree: Cargo.toml {version}, "
                 f"vertext.mjs WIRE_VERSION {wire}")

    forbidden = build()
    module = MODULE.read_bytes()
    leaked = sorted({f.decode() for f in forbidden if f in module})
    if leaked:
        sys.exit(f"{MODULE.name} still carries build-machine paths: {leaked}")

    reported = handshake()
    if reported != version:
        sys.exit(f"the module reports {reported}, not {version}")

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    archive = out / f"vertext-wasm-{version}.zip"
    files = {GLUE_NAME: GLUE.read_bytes(), MODULE_NAME: module}
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            zf.writestr(info, files[name])

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    shown = archive.relative_to(ROOT) if archive.is_relative_to(ROOT) else archive
    print(f"{shown}  sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
