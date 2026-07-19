use std::io::{self, Read};
use vertext_core::{layout_text, LayoutConfig, Slot};

fn escape(text: &str) -> String {
    text.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;").replace('"', "&quot;")
}

fn main() {
    let arguments: Vec<String> = std::env::args().collect();
    let code_mode = arguments.iter().any(|argument| argument == "--code");
    let code_width = code_mode || arguments.iter().any(|argument| argument == "--code-width");
    let preserve_spaces = code_width || arguments.iter().any(|argument| argument == "--preserve-spaces");
    let mut input = String::new();
    io::stdin().read_to_string(&mut input).expect("read standard input");
    let mut config = LayoutConfig::default();
    // Source code has compound identifiers that are not English prose words.
    // Keep those readable while preserving the tighter prose column policy.
    if code_width {
        config.max_latin_word_width = 24;
    }
    if preserve_spaces {
        config.preserve_spaces = true;
    }
    let layout = layout_text(&input, &config);
    let root_class = if code_mode { "vertext vertext-code" } else { "vertext" };
    print!("<div class=\"{root_class}\" data-column-advance=\"left\">");
    // Source order is right-to-left; CSS flex row-reverse places it that way.
    for column in layout.columns {
        print!("<div class=\"vertext-column\">");
        for slot in column.slots {
            let (class, text) = match slot {
                Slot::Upright(s) => ("vertext-upright", s),
                Slot::LatinWord(s) => ("vertext-latin", s),
                Slot::MongolianRun(s) => ("vertext-mongolian", s),
                Slot::Space => ("vertext-space", "&nbsp;".into()),
                Slot::PairedPunctuation(s) => ("vertext-paired", s),
                Slot::Neutral(s) => ("vertext-neutral", s),
            };
            print!("<span class=\"{class}\">{}</span>", escape(&text));
        }
        print!("</div>");
    }
    println!("</div>");
}
