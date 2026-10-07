# vertext for Dart

The slots vertext lays out, for a Dart or Flutter host that shapes and paints
text itself. It is a binding and nothing else: no widgets, no painting, no
fonts. A Flutter layout theme sits on top of it.

```dart
import 'package:vertext/vertext.dart';

switch (layout('山川异域，风月同天')) {
  case Vertical(:final progression, :final columns):
    // Columns in source order; `progression` says which side the first is on.
    // Each slot has a kind (upright, latin, mongolian, space, vform, corner,
    // neutral, combine), the text it shows, and its range in the string, in
    // UTF-16.
  case Horizontal():
    // vertext would set this text horizontally: draw it as ordinary text.
}
```

The slots are the ones the page renderer draws for the same text, classified
by the same table, so a Flutter page and a web page cut a text the same way.
What needs a font stays with the host: shaping each slot, measuring it,
breaking a column into lines, painting and hit-testing. Three things a host
must not do with them: rotate a whole run (orientation is per slot; a
Mongolian run turns as one slot), substitute a character (a vertical
punctuation form is a view of the author's character, never a replacement),
or assume the progression.

## Building

The native half is `crates/vertext-ffi` in this repository. A build hook
compiles it with cargo when the package is built, so a consumer places no
library by hand; it needs a Rust toolchain on PATH. Linux only so far.

In the Dart 3.13 SDK, hooks run with a filtered environment that drops
`RUSTUP_HOME` and `CARGO_HOME`. Where the hook receives either, it uses it as
given; otherwise, if the cargo on PATH is a rustup proxy, it recovers both from
there, and a cargo that is not rustup's needs neither. Where that is wrong,
name them in the application's `pubspec.yaml`:

```yaml
hooks:
  user_defines:
    vertext:
      rustup_home: /path/to/rustup
      cargo_home: /path/to/cargo
```

The binding and the library carry the same version handshake as the Quarto
filter and the binary: a library from another release is refused with both
versions named.

## Testing

```sh
cd bindings/dart
dart test
```
