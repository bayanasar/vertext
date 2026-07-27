//! Thin stdin-to-stdout shell over [`vertext_html::render_document`].
//!
//! All rendering logic lives in `vertext-html` so the future `vertext-wasm`
//! host shares it byte for byte. Any of `--code`, `--code-width`, or
//! `--preserve-spaces` selects whole-strip code mode (they were once separate
//! knobs; the Quarto filter always passes all three together, and mixed
//! prose/code inputs use the sentinel protocol instead). `--page` marks the
//! strip as the document's full-page surface. `--progression lr|rl` sets the
//! column advance direction.

use std::io::{self, Read};
use vertext_core::Progression;
use vertext_html::{render_document, RenderOptions};

fn main() {
    let arguments: Vec<String> = std::env::args().collect();
    let has = |name: &str| arguments.iter().any(|argument| argument == name);
    // `lr` is traditional Mongolian, `rl` is CJK. An unrecognised value falls
    // back to the CJK default rather than failing the whole render — a typo in
    // one document's metadata should not take down a site build, and the
    // wrong-but-legible direction is recoverable where no output is not.
    let progression = match arguments.iter().position(|argument| argument == "--progression") {
        Some(index) => match arguments.get(index + 1).map(String::as_str) {
            Some("lr") => Progression::LeftToRight,
            _ => Progression::RightToLeft,
        },
        None => Progression::RightToLeft,
    };
    let options = RenderOptions {
        whole_strip_code: has("--code") || has("--code-width") || has("--preserve-spaces"),
        page: has("--page"),
        progression,
    };
    let mut input = String::new();
    io::stdin().read_to_string(&mut input).expect("read standard input");
    print!("{}", render_document(&input, options));
}
