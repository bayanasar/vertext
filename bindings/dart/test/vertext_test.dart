import 'dart:convert';
import 'dart:io';

import 'package:test/test.dart';
import 'package:vertext/vertext.dart';

const mixed =
    '山川异域，风月同天。\n「寄诸佛子」 共结来缘\n'
    'ᠮᠣᠩᠭᠣᠯ\u202fᠤᠨ ᠪᠠᠶᠢᠨ\u180eᠠ᠃ 𠀋字';

void main() {
  test('the native library speaks this binding\'s wire version', () {
    expect(wireOf(nativeVersion()), wireOf(version));
  });

  test('a library from another release is refused, naming both', () {
    expect(
      () => checkWire('0.3.0-dev', '0.2.0'),
      throwsA(
        isA<VersionMismatch>().having(
          (e) => e.message,
          'message',
          allOf(contains('0.3.0-dev'), contains('0.2.0')),
        ),
      ),
    );
    expect(() => checkWire('0.3.0', '0.3.1'), returnsNormally);
  });

  test('the wire rule agrees with every pair in tools/wire-pairs.json', () {
    final pairs =
        (jsonDecode(File('../../tools/wire-pairs.json').readAsStringSync())
                as Map<String, Object?>)['pairs']
            as List<Object?>;
    for (final pair in pairs.cast<Map<String, Object?>>()) {
      expect(
        wireOf(pair['ours'] as String) == wireOf(pair['theirs'] as String),
        pair['agree'],
        reason:
            '${pair['ours']} and ${pair['theirs']}: '
            '${pair['why']}',
      );
    }
  });

  test('a mixed run comes back as slots of the page\'s kinds', () {
    final laid = layout(mixed) as Vertical;
    expect(laid.progression, Progression.rightToLeft);
    expect(laid.columns, hasLength(3));
    final first = laid.columns[0];
    expect(first.map((s) => s.kind).take(5), [
      SlotKind.upright,
      SlotKind.upright,
      SlotKind.upright,
      SlotKind.upright,
      SlotKind.corner,
    ]);
    final mongolian = laid.columns[2].where(
      (s) => s.kind == SlotKind.mongolian,
    );
    // The suffix joint keeps the stem and its case ending in one slot.
    expect(mongolian.first.text, 'ᠮᠣᠩᠭᠣᠯ\u202fᠤᠨ');
    // The MVS stays inside the word, and so does the full stop after it.
    expect(mongolian.elementAt(1).text, 'ᠪᠠᠶᠢᠨ\u180eᠠ᠃');
  });

  test('every slot\'s range is its own text in the Dart string', () {
    for (final (text, code) in [
      (mixed, false),
      (mixed, true),
      ('山 internationalization 川', false),
    ]) {
      final laid = layout(text, code: code) as Vertical;
      for (final slot in laid.columns.expand((c) => c)) {
        final shown = slot.hyphen
            ? slot.text.substring(0, slot.text.length - 1)
            : slot.text;
        expect(text.substring(slot.start, slot.end), shown, reason: '$slot');
      }
    }
  });

  test('the progression is read from the layout, not assumed', () {
    final laid =
        layout(mixed, progression: Progression.leftToRight) as Vertical;
    expect(laid.progression, Progression.leftToRight);
  });

  test('text vertext would set horizontally says so', () {
    expect(
      layout('this paragraph is plainly English and goes horizontal'),
      isA<Horizontal>(),
    );
  });
}
