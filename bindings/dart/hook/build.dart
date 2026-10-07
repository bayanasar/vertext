// Builds the native half of this package: the `vertext-ffi` crate of the Rust
// workspace this package sits in, compiled by cargo and bundled as a code
// asset, so a consumer never places a library by hand.
//
// Linux only for now. Other targets fail here with a message rather than
// producing a library that does not load.

import 'dart:io';

import 'package:code_assets/code_assets.dart';
import 'package:hooks/hooks.dart';

const _crate = 'vertext-ffi';
const _library = 'vertext_ffi';

/// The manifests the library is built from. Its source files are not listed
/// here: cargo writes them to a depfile beside the library, and the hook
/// reads them from there (see [_compiledFrom]).
const _manifests = [
  'Cargo.toml',
  'Cargo.lock',
  'crates/vertext-core/Cargo.toml',
  'crates/vertext-html/Cargo.toml',
  'crates/vertext-ffi/Cargo.toml',
];

void main(List<String> args) async {
  await build(args, (input, output) async {
    if (!input.config.buildCodeAssets) return;
    final code = input.config.code;
    if (code.targetOS != OS.linux) {
      throw UnsupportedError(
        'vertext: this build hook only builds for Linux so far, '
        'not ${code.targetOS}',
      );
    }
    final triple = switch (code.targetArchitecture) {
      Architecture.x64 => 'x86_64-unknown-linux-gnu',
      Architecture.arm64 => 'aarch64-unknown-linux-gnu',
      final other => throw UnsupportedError(
        'vertext: no Rust target for Linux on $other',
      ),
    };

    final workspace = input.packageRoot.resolve('../../');
    final manifest = File.fromUri(workspace.resolve('Cargo.toml'));
    if (!manifest.existsSync() ||
        !manifest.readAsStringSync().contains('"crates/$_crate"')) {
      throw StateError(
        'vertext: expected the Rust workspace two levels above this '
        'package, at ${workspace.toFilePath()}',
      );
    }

    final targetDir = input.outputDirectoryShared.resolve('cargo/');
    final environment = _rustupEnvironment(input);
    final result = await Process.run(
      'cargo',
      [
        'build',
        '--release',
        '--locked',
        '--quiet',
        '-p',
        _crate,
        '--target',
        triple,
        '--target-dir',
        targetDir.toFilePath(),
      ],
      workingDirectory: workspace.toFilePath(),
      environment: environment,
    );
    if (result.exitCode != 0) {
      throw StateError(
        'vertext: cargo build failed with $environment\n'
        '${result.stderr}\n'
        'If the toolchain is not where these say, name it in the root '
        'pubspec.yaml under hooks: user_defines: vertext: (rustup_home, '
        'cargo_home).',
      );
    }

    final library = targetDir.resolve(
      '$triple/release/${OS.linux.dylibFileName(_library)}',
    );
    output.assets.code.add(
      CodeAsset(
        package: input.packageName,
        name: 'src/bindings.dart',
        linkMode: DynamicLoadingBundled(),
        file: library,
      ),
    );
    output.dependencies.addAll([
      for (final manifest in _manifests) workspace.resolve(manifest),
      ..._compiledFrom(targetDir.resolve('$triple/release/lib$_library.d')),
    ]);
  });
}

/// Every source file cargo read to build the library, from the depfile it
/// writes beside it (`<output>: <source> <source> ...`, spaces in a path
/// escaped). A hook dependency must be a file: a directory is hashed by the
/// names of its direct children only, so an edit inside `src/` would not
/// rebuild, and a directory URI without its trailing slash is taken for a
/// missing file that changes on every build.
List<Uri> _compiledFrom(Uri depfile) {
  final sources = <Uri>[];
  for (final line in File.fromUri(depfile).readAsLinesSync()) {
    final colon = line.indexOf(': ');
    if (colon < 0) continue;
    for (final path in line.substring(colon + 2).split(RegExp(r'(?<!\\) '))) {
      if (path.isNotEmpty) sources.add(Uri.file(path.replaceAll(r'\ ', ' ')));
    }
  }
  if (sources.isEmpty) {
    throw StateError(
      'vertext: cargo listed no sources in ${depfile.toFilePath()}',
    );
  }
  return sources;
}

/// Where rustup keeps its toolchains, for the cargo it runs.
///
/// The hook runner of the SDK this was written against (Dart 3.13) starts a
/// hook with a filtered environment that keeps HOME and PATH but drops
/// RUSTUP_HOME and CARGO_HOME, so a toolchain installed anywhere but
/// `$HOME/.rustup` (a container's `/usr/local/rustup`, a home directory that
/// is not $HOME) is invisible to the cargo the hook starts. In order:
///
/// - `rustup_home` and `cargo_home` from the root pubspec's user-defines;
/// - otherwise, either variable as the hook received it: a runner that passes
///   them through knows better than a guess, and cargo inherits them;
/// - otherwise, when the cargo on PATH is a rustup proxy (a `rustup` sits in
///   the same directory): rustup installs its proxies in `$CARGO_HOME/bin`,
///   which gives CARGO_HOME exactly, and RUSTUP_HOME is the sibling `.rustup`
///   or `rustup` that holds `toolchains/` (the two layouts rustup's installer
///   and the official images use);
/// - otherwise nothing. A cargo that is not rustup's, a distribution's in
///   `/usr/bin` say, needs neither variable, and guessing CARGO_HOME=/usr
///   would only break it.
Map<String, String> _rustupEnvironment(BuildInput input) {
  final definedRustup = input.userDefines.path('rustup_home');
  final definedCargo = input.userDefines.path('cargo_home');
  if (definedRustup != null || definedCargo != null) {
    return {
      if (definedRustup != null) 'RUSTUP_HOME': definedRustup.toFilePath(),
      if (definedCargo != null) 'CARGO_HOME': definedCargo.toFilePath(),
    };
  }
  final inherited = Platform.environment;
  if (inherited.containsKey('RUSTUP_HOME') ||
      inherited.containsKey('CARGO_HOME')) {
    return {};
  }
  final path = inherited['PATH'] ?? '';
  final bin = path
      .split(':')
      .firstWhere(
        (dir) => dir.isNotEmpty && File('$dir/cargo').existsSync(),
        orElse: () => '',
      );
  if (bin.isEmpty ||
      !File('$bin/rustup').existsSync() ||
      Directory(bin).uri.pathSegments.lastWhere((s) => s.isNotEmpty) != 'bin') {
    return {};
  }
  final cargoHome = Directory(bin).parent;
  for (final name in ['.rustup', 'rustup']) {
    final candidate = '${cargoHome.parent.path}/$name';
    if (Directory('$candidate/toolchains').existsSync()) {
      return {'CARGO_HOME': cargoHome.path, 'RUSTUP_HOME': candidate};
    }
  }
  return {'CARGO_HOME': cargoHome.path};
}
