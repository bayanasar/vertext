#!/bin/sh
# Renders the API documentation from the doc comments in crates/.
#
# Output is derived and git-ignored (/target/). Nothing here is committed:
# rustdoc renders the doc comments, it is not a second source for them.
set -eu

cd "$(dirname "$0")/.."
cargo doc --no-deps --workspace "$@"

echo
echo "Entry point: target/doc/vertext_core/index.html"
