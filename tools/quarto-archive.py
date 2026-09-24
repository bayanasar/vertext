#!/usr/bin/env python3
"""Build the archive `quarto add` installs the filter from.

Why an archive, and why this shape
----------------------------------
The filter's source is `extensions/vertext/`, but `quarto add <org>/<repo>`
looks for an `_extensions/` directory at the root of the repository, and there
is none. Adding one would be a third copy of the filter beside
`extensions/vertext/` and the one `extensions/vertext-theme/` must vendor, and
two copies have already drifted once (#25). So the filter ships as a release
artifact instead, built from the one source:

    vertext-quarto-<version>.zip
      _extensions/vertext/_extension.yml
      _extensions/vertext/vertext.css
      _extensions/vertext/vertext.lua

and is installed with

    quarto add https://github.com/bayanasar/vertext/releases/download/v<version>/vertext-quarto-<version>.zip

Two details in Quarto's installer decide the format, read from its source
(`src/extension/install.ts`, `src/extension/extension-host.ts`):

- A URL that is not a GitHub repository or archive URL is saved as
  `extension.zip` whatever it really is, and the name picks the unpacker. A
  tarball behind such a URL fails to unpack, so this is a zip.
- After unpacking, Quarto uses the archive root if it holds `_extensions/`,
  so the entries start there and nothing wraps them.

The binary half comes from crates.io at the same version. The filter refuses a
binary whose wire version differs (see tools/versions.py), so the two halves
must come from one release: the archive carries the version in its name for
that reason.

The zip is byte-reproducible: entries are sorted, timestamps are fixed and the
permission bits are constant, so the same tree always gives the same sha256.

Usage
-----
    python3 tools/quarto-archive.py              # writes target/quarto/
    python3 tools/quarto-archive.py --out DIR
"""

import argparse
import hashlib
import pathlib
import sys
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import versions  # noqa: E402  (tools/versions.py)

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "extensions" / "vertext"
FILES = ["_extension.yml", "vertext.css", "vertext.lua"]
# 1980-01-01 is the earliest time a zip entry can carry.
EPOCH = (1980, 1, 1, 0, 0, 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "target" / "quarto"))
    args = ap.parse_args()

    # CI already holds these equal; the archive checks again because it is the
    # thing that goes out, and a zip named for one version carrying another is
    # the mismatched pair this release exists to prevent.
    disagree = versions.check()
    if disagree:
        sys.exit("\n".join(disagree))
    version = versions.version()
    problem = versions.release_problem(version)
    if problem:
        sys.exit(f"refusing to name an archive for {version}: {problem}")

    missing = [name for name in FILES if not (SOURCE / name).is_file()]
    extra = sorted(p.name for p in SOURCE.iterdir() if p.name not in FILES)
    if missing or extra:
        sys.exit(f"extensions/vertext is not the three files this archive ships\n"
                 f"  missing: {missing}\n  unexpected: {extra}")

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    archive = out / f"vertext-quarto-{version}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(FILES):
            info = zipfile.ZipInfo(f"_extensions/vertext/{name}", date_time=EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            zf.writestr(info, (SOURCE / name).read_bytes())

    with zipfile.ZipFile(archive) as zf:
        for name in FILES:
            if zf.read(f"_extensions/vertext/{name}") != (SOURCE / name).read_bytes():
                sys.exit(f"{archive.name}: {name} does not round-trip")

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    shown = archive.relative_to(ROOT) if archive.is_relative_to(ROOT) else archive
    print(f"{shown}  sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
