/// Vertical text layout for a host that shapes and paints text itself.
///
/// [layout] returns what vertext's page renderer would draw for a run of
/// text: its columns, and in each column its slots, every slot classified as
/// the page classifies it. Everything that needs a font stays with the host:
/// shaping each slot, measuring it, breaking a column into lines, painting,
/// hit-testing.
///
/// What a host must not do with these slots is the same as on the page:
/// never rotate a whole run (orientation is per slot), never substitute a
/// character (a vertical punctuation form is a view of the author's
/// character, not a replacement for it), and never assume the progression.
library;

import 'dart:convert';
import 'dart:ffi';

import 'package:ffi/ffi.dart';

import 'src/bindings.dart' as native;

/// The version this binding was released as. The native library reports its
/// own, and the two must speak one wire version (tools/wire-pairs.json).
const version = '0.3.0-dev';

/// The wire version a half with version [v] speaks: a release its
/// MAJOR.MINOR, a pre-release its whole version.
String wireOf(String v) => v.contains('-') ? v : v.split('.').take(2).join('.');

/// The native library does not speak this binding's wire version.
final class VersionMismatch extends StateError {
  VersionMismatch(this.binding, this.library)
    : super(
        'vertext: the Dart binding is $binding (wire version '
        '${wireOf(binding)}) and the native library is $library '
        '(wire version ${wireOf(library)}): build both from one release',
      );

  final String binding;
  final String library;
}

/// Which way successive columns advance. Data, never a constant: CJK columns
/// advance right to left, traditional Mongolian left to right.
enum Progression { rightToLeft, leftToRight }

/// What a slot is, by the name of its class on the page.
enum SlotKind {
  /// An upright ideograph, kana or hangul cluster.
  upright,

  /// One Latin word, set as a unit.
  latin,

  /// A Mongolian run, kept whole so the font can join it; it turns as one.
  mongolian,

  /// Whitespace from the source, carried through.
  space,

  /// Punctuation that turns a quarter in vertical text: brackets, quotes,
  /// dashes, ellipses.
  vform,

  /// A pause or stop mark (、，。．；：), which never turns. It sits in the
  /// upper-right corner of its square in the Mainland style and in the centre
  /// in Taiwan and Hong Kong. A host that shapes vertically gets that from the
  /// face's vertical forms; one that shapes horizontally places it itself.
  corner,

  /// Anything else, upright.
  neutral,

  /// Two question or exclamation marks used together (`？！`), set side by
  /// side in one character's space.
  combine,
}

/// One slot of a column.
final class Slot {
  const Slot({
    required this.kind,
    required this.text,
    required this.start,
    required this.end,
    required this.graphemes,
    required this.hyphen,
  });

  final SlotKind kind;

  /// What the slot shows, including a hyphen the layout inserted.
  final String text;

  /// The slot's source in the string passed to [layout], as UTF-16 indices
  /// (`text.substring(start, end)`), excluding an inserted hyphen.
  final int start;
  final int end;

  /// How many grapheme clusters of source the slot holds.
  final int graphemes;

  /// The text ends in a hyphen the layout inserted, which has no source.
  final bool hyphen;

  @override
  String toString() => 'Slot($kind, ${jsonEncode(text)}, $start..$end)';
}

/// What [layout] returns.
sealed class Layout {
  const Layout();
}

/// vertext would set this text horizontally: its Latin outweighs its
/// vertical script, or it is not one run. The host sets it as plain
/// horizontal text.
final class Horizontal extends Layout {
  const Horizontal();
}

/// The text as one vertical strip.
final class Vertical extends Layout {
  const Vertical(this.progression, this.columns);

  final Progression progression;

  /// Columns in source order; [progression] says which side the first one
  /// sits on.
  final List<List<Slot>> columns;
}

/// Throws [VersionMismatch] unless a [binding] and a native [library] speak
/// one wire version.
void checkWire(String binding, String library) {
  if (wireOf(binding) != wireOf(library)) {
    throw VersionMismatch(binding, library);
  }
}

bool _checked = false;

/// The native library's version, after checking it speaks our wire version.
String nativeVersion() {
  final reported = native.vertextVersion().toDartString();
  if (!_checked) {
    checkWire(version, reported);
    _checked = true;
  }
  return reported;
}

/// Lays [text] out as vertext's page would: as [code] (spaces kept, longer
/// Latin slots) or as prose, with columns advancing as [progression] says.
Layout layout(
  String text, {
  bool code = false,
  Progression progression = Progression.rightToLeft,
}) {
  nativeVersion();
  final bytes = utf8.encode(text);
  final flags =
      (code ? native.flagCode : 0) |
      (progression == Progression.leftToRight ? native.flagLeftToRight : 0);
  return using((arena) {
    final input = arena<Uint8>(bytes.isEmpty ? 1 : bytes.length);
    input.asTypedList(bytes.length).setAll(0, bytes);
    final outLen = arena<Size>();
    final out = native.vertextLayout(input, bytes.length, flags, outLen);
    if (out == nullptr) {
      throw StateError(
        'vertext: the native library returned no layout (the input was not '
        'UTF-8, or the layout failed)',
      );
    }
    final String json;
    try {
      json = utf8.decode(out.asTypedList(outLen.value));
    } finally {
      native.vertextFree(out, outLen.value);
    }
    return _decode(
      text,
      bytes.length,
      jsonDecode(json) as Map<String, Object?>,
    );
  });
}

Layout _decode(String text, int byteLength, Map<String, Object?> json) {
  if (json['horizontal'] == true) return const Horizontal();
  // The library reports UTF-8 byte offsets; a Dart string is indexed in
  // UTF-16 code units. Every offset it reports falls on a code point.
  final utf16At = List<int>.filled(byteLength + 1, -1);
  var byte = 0, unit = 0;
  for (final rune in text.runes) {
    utf16At[byte] = unit;
    byte += rune < 0x80
        ? 1
        : rune < 0x800
        ? 2
        : rune < 0x10000
        ? 3
        : 4;
    unit += rune < 0x10000 ? 1 : 2;
  }
  utf16At[byte] = unit;
  int at(Object? offset) {
    final index = utf16At[offset as int];
    if (index < 0)
      throw StateError('vertext: offset $offset splits a character');
    return index;
  }

  final progression = switch (json['progression']) {
    'rl' => Progression.rightToLeft,
    'lr' => Progression.leftToRight,
    final other => throw StateError('vertext: unknown progression $other'),
  };
  final columns = [
    for (final column in json['columns'] as List<Object?>)
      [
        for (final slot
            in (column as List<Object?>).cast<Map<String, Object?>>())
          Slot(
            kind: SlotKind.values.byName(slot['kind'] as String),
            text: slot['text'] as String,
            start: at(slot['start']),
            end: at(slot['end']),
            graphemes: slot['graphemes'] as int,
            hyphen: slot['hyphen'] as bool,
          ),
      ],
  ];
  return Vertical(progression, columns);
}
