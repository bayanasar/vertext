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

/// The crates the library is compiled from: any change to them rebuilds it.
const _sources = [
  'Cargo.toml',
  'Cargo.lock',
  'crates/vertext-core',
  'crates/vertext-html',
  'crates/vertext-ffi',
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
      for (final source in _sources) workspace.resolve(source),
    ]);
  });
}

/// Where rustup keeps its toolchains, for the cargo it runs.
///
/// A hook runs with a filtered environment that keeps HOME and PATH but drops
/// RUSTUP_HOME and CARGO_HOME, so a toolchain installed anywhere but
/// `$HOME/.rustup` (a container's `/usr/local/rustup`, a home directory that
/// is not $HOME) is invisible to the cargo the hook starts. In order:
///
/// - `rustup_home` and `cargo_home` from the root pubspec's user-defines;
/// - otherwise, the cargo on PATH: rustup installs its proxies in
///   `$CARGO_HOME/bin`, which gives CARGO_HOME exactly, and RUSTUP_HOME is
///   the sibling `.rustup` or `rustup` that holds `toolchains/` (the two
///   layouts rustup's installer and the official images use);
/// - otherwise nothing, and rustup falls back to `$HOME/.rustup` itself.
Map<String, String> _rustupEnvironment(BuildInput input) {
  final definedRustup = input.userDefines.path('rustup_home');
  final definedCargo = input.userDefines.path('cargo_home');
  if (definedRustup != null || definedCargo != null) {
    return {
      if (definedRustup != null) 'RUSTUP_HOME': definedRustup.toFilePath(),
      if (definedCargo != null) 'CARGO_HOME': definedCargo.toFilePath(),
    };
  }
  final path = Platform.environment['PATH'] ?? '';
  final bin = path
      .split(':')
      .firstWhere(
        (dir) => dir.isNotEmpty && File('$dir/cargo').existsSync(),
        orElse: () => '',
      );
  if (bin.isEmpty ||
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
