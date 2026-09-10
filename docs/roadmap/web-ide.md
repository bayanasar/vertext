# Vertext Web IDE

The third product is a browser IDE with a VS Code-like three-pane shape:

`explorer | source editor + vertext preview | terminal / diagnostics`

It shares `vertext-core` through `vertext-wasm`. The editor should keep the
source document horizontal and use a mapped, rendered vertical preview first;
making a vertical surface directly editable comes later, after cursor and IME
mapping are proven in the Neovim preview.
