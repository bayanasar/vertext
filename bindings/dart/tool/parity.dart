// The Dart binding cuts a text the way the page does.
//
// A Flutter page and a web page showing the same text must show the same
// slots, or one content reads two ways with every other check green. For each
// input below, under each flag set, this lays the text out through the binding
// (native library, JSON, Dart decoding) and renders it through the release
// CLI, then requires:
//
//   * the binding says Horizontal exactly where the page has no column;
//   * otherwise the slots, in order, are the page's slot spans, kind for
//     class and text for text;
//   * every slot's range, in UTF-16, is its own text in the Dart string.
//
//   cargo build --release -p vertext-cli
//   cd bindings/dart && dart run tool/parity.dart [path/to/vertext]

import 'dart:convert';
import 'dart:io';

import 'package:vertext/vertext.dart';

final _slotSpan = RegExp(
  '<span class="vertext-(${SlotKind.values.map((k) => k.name).join('|')})">'
  '(.*?)</span>',
);

String _unescape(String html) => html
    .replaceAll('&lt;', '<')
    .replaceAll('&gt;', '>')
    .replaceAll('&quot;', '"')
    .replaceAll('&amp;', '&');

Future<String> _render(String binary, String text, List<String> flags) async {
  final process = await Process.start(binary, ['html', ...flags]);
  process.stdin.add(utf8.encode(text));
  await process.stdin.close();
  final out = await process.stdout.transform(utf8.decoder).join();
  final err = await process.stderr.transform(utf8.decoder).join();
  if (await process.exitCode != 0) {
    throw StateError('vertext failed on ${jsonEncode(text)}: $err');
  }
  return out;
}

Future<void> main(List<String> args) async {
  final root = Directory.current.uri.resolve('../../');
  final binary = args.isNotEmpty
      ? args.first
      : root.resolve('target/release/vertext').toFilePath();
  if (!File(binary).existsSync()) {
    stderr.writeln(
      'no binary at $binary -- cargo build --release -p vertext-cli',
    );
    exit(2);
  }
  final golden =
      jsonDecode(
            File.fromUri(
              root.resolve('goldens/shaping.json'),
            ).readAsStringSync(),
          )
          as Map<String, Object?>;
  final corpus = golden['corpus'] as Map<String, Object?>;
  final inputs = <String>[
    ...(corpus['runs'] as List<Object?>).cast<String>(),
    for (final line
        in (corpus['lines'] as List<Object?>).cast<Map<String, Object?>>())
      line['text'] as String,
    '',
    '\n',
    '山川异域，风月同天。寄诸佛子，共结来缘。\n',
    '第一行\r\n\r\n第三行\n\n',
    'ᠮᠣᠩᠭᠣᠯ\u{202f}ᠤᠨ (mongɣol-un) ᠨᠣᠮ᠃',
    '山 internationalization 川，𠀋字「引文」',
    // Latin-majority: the page sets these horizontally, and so must a host.
    'this paragraph is plainly English and goes horizontal',
    'the word ᠮᠣᠩᠭᠣᠯ is written in bichig and read here in English',
  ];
  const flagSets = [
    (code: false, progression: Progression.rightToLeft, cli: <String>[]),
    (
      code: false,
      progression: Progression.leftToRight,
      cli: ['--progression', 'lr'],
    ),
    (code: true, progression: Progression.rightToLeft, cli: ['--code']),
  ];

  final fails = <String>[];
  var vertical = 0, horizontal = 0, slots = 0;
  for (final text in inputs) {
    for (final flags in flagSets) {
      final where = '${jsonEncode(text)} ${flags.cli.join(' ')}'.trim();
      final laid = layout(
        text,
        code: flags.code,
        progression: flags.progression,
      );
      final html = await _render(binary, text, flags.cli);
      final hasColumn = html.contains('<div class="vertext-column');
      switch (laid) {
        case Horizontal():
          horizontal++;
          if (hasColumn) {
            fails.add(
              '$where: the binding says horizontal, the page has columns',
            );
          }
        case Vertical(:final columns):
          vertical++;
          final drawn = [
            for (final slot in columns.expand((c) => c))
              '${slot.kind.name} ${jsonEncode(slot.text)}',
          ];
          final page = [
            for (final m in _slotSpan.allMatches(html))
              '${m[1]} ${jsonEncode(_unescape(m[2]!))}',
          ];
          slots += drawn.length;
          if (drawn.join('\n') != page.join('\n')) {
            var at = 0;
            while (at < drawn.length &&
                at < page.length &&
                drawn[at] == page[at]) {
              at++;
            }
            fails.add(
              '$where: slot $at differs\n'
              '     binding ${at < drawn.length ? drawn[at] : '(none)'}\n'
              '     page    ${at < page.length ? page[at] : '(none)'}',
            );
          }
          for (final slot in columns.expand((c) => c)) {
            final shown = slot.hyphen
                ? slot.text.substring(0, slot.text.length - 1)
                : slot.text;
            if (text.substring(slot.start, slot.end) != shown) {
              fails.add('$where: $slot does not show its own source');
            }
          }
      }
    }
  }

  if (fails.isNotEmpty) {
    print('FAIL: ${fails.length} finding(s)\n');
    for (final f in fails.take(15)) {
      print('  $f');
    }
    exit(1);
  }
  print(
    'PASS: ${inputs.length} inputs under ${flagSets.length} flag sets: '
    '$vertical vertical layouts give the page\'s $slots slots in order, each '
    'showing its own source, and the $horizontal horizontal ones have no '
    'column on the page either',
  );
  print('      native library ${nativeVersion()}, binary $binary');
}
