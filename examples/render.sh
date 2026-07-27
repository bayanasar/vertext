#!/usr/bin/env sh
# Builds the binary and renders the demo.
#
# The extension is copied into `examples/_extensions/` at render time rather
# than committed there: Quarto discovers extensions by directory and does not
# follow symlinks, so a second checked-in copy would be the only alternative —
# and two copies of a filter in one repository will drift. `extensions/vertext`
# is the single source; `examples/_extensions/` is generated and gitignored.
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"

cargo build --release -p vertext-cli
PATH="$root/target/release:$PATH"
export PATH

mkdir -p examples/_extensions
rm -rf examples/_extensions/vertext
cp -R extensions/vertext examples/_extensions/vertext

quarto render examples/quarto-demo.qmd
