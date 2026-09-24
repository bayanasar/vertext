"""The version declarations, read once, and the rules that compare them.

Four files declare a version, and a filter or glue built from one checkout
must refuse a binary or module built from another:

    Cargo.toml             [workspace.package] version -- what the binary and
                           the wasm module report
    _extension.yml         what Quarto installs the filter by
    vertext.lua            VERSION, what the filter compares against
    vertext.mjs            VERSION, what the glue compares against

They are typed by hand and must be one string; `check()` says where they
disagree. Every tool reads them here, so there is one parser per file and a
file that moves its declaration fails in one place.

The handshake compares WIRE versions, and `wire()` is the rule, written the
same way in vertext.lua and vertext.mjs:

- A release (`0.3.1`) speaks its MAJOR.MINOR (`0.3`): a patch release may not
  change the wire protocol, an export or what the source map means, so patch
  releases of one minor accept each other.
- A pre-release (`0.4.0-dev`) speaks its whole version. Main carries the next
  minor's pre-release from the day after a tag, so a half built from a
  checkout is refused by a half from any release, including the release of the
  same minor it is heading for. The cost: two checkouts of main between the
  same two tags both say `0.4.0-dev` and accept each other.

A release version is only honest on its tag. `release_problem()` refuses a
version that an existing tag already names unless HEAD is that tag: after
`v0.3.0` is cut, main must move to `0.4.0-dev`, or every build from it would
claim to be 0.3.0.
"""

import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _read(path, pattern, flags=re.MULTILINE):
    found = re.search(pattern, (ROOT / path).read_text(encoding="utf-8"), flags)
    return found and found.group(1)


def declared():
    """{declaration: version or None}, by the name a message should use."""
    return {
        "Cargo.toml": _read("Cargo.toml",
                            r'^\[workspace\.package\][^\[]*?^version\s*=\s*"([^"]+)"',
                            re.MULTILINE | re.DOTALL),
        "_extension.yml": _read("extensions/vertext/_extension.yml", r"^version:\s*(\S+)\s*$"),
        "vertext.lua": _read("extensions/vertext/vertext.lua", r'^local VERSION = "([^"]+)"'),
        "vertext.mjs": _read("examples/wasm/vertext.mjs", r"^export const VERSION = '([^']+)';$"),
    }


def check():
    """Why the declarations are not one version, or [] when they are."""
    found = declared()
    missing = [name for name, v in found.items() if not v]
    if missing:
        return [f"versions: no declaration found in {', '.join(missing)}"]
    if len(set(found.values())) != 1:
        return ["versions: the declarations disagree: " +
                ", ".join(f"{name} {v}" for name, v in found.items())]
    return []


def version():
    """The one version, or None when `check()` has something to say."""
    return None if check() else declared()["Cargo.toml"]


def wire(v):
    """The wire version a half with version `v` speaks."""
    return v if "-" in v else ".".join(v.split(".")[:2])


def _git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True,
                          text=True, check=True).stdout.split()


def release_problem(v):
    """Why version `v` may not be built at HEAD, or None.

    Needs the tags: in a shallow CI checkout, fetch them first. No tags at all
    is an error rather than a pass, because a checkout without tags would let
    every version through.
    """
    tags = _git("tag", "--list", "v*")
    if not tags:
        return "no v* tags are visible, so nothing can be checked: fetch the tags"
    if f"v{v}" in tags and f"v{v}" not in _git("tag", "--points-at", "HEAD"):
        return (f"version {v} is already tagged v{v}, and HEAD is not that tag: "
                f"move main to the next minor's pre-release")
    return None
