// The C ABI of crates/vertext-ffi, resolved from the code asset the build
// hook bundles under this library's id.
@DefaultAsset('package:vertext/src/bindings.dart')
library;

import 'dart:ffi';

import 'package:ffi/ffi.dart';

@Native<Pointer<Utf8> Function()>(symbol: 'vertext_version')
external Pointer<Utf8> vertextVersion();

@Native<Pointer<Uint8> Function(Pointer<Uint8>, Size, Uint32, Pointer<Size>)>(
  symbol: 'vertext_layout',
)
external Pointer<Uint8> vertextLayout(
  Pointer<Uint8> input,
  int len,
  int flags,
  Pointer<Size> outLen,
);

@Native<Void Function(Pointer<Uint8>, Size)>(symbol: 'vertext_free')
external void vertextFree(Pointer<Uint8> pointer, int len);

/// The flags vertext_layout takes, as crates/vertext-ffi declares them.
const flagCode = 1;
const flagLeftToRight = 4;
