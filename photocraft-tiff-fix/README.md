# PhotoCraft TIFF spot-channel repair

Prepared for @jwinslett1. These are replacement **Rust source files**, not an installer or executable patch.

## Pick the ZIP matching your source folder

- [PhotoCraft 0.10.0 replacement files](PhotoCraft-0.10.0-v3-replacement-files.zip): matches the `photocraft-main.zip` supplied by the reporter.
- [PhotoCraft 0.11.1 replacement files](PhotoCraft-0.11.1-v3-replacement-files.zip): matches source commit `b097800e78405aeb2068113988898f991e707eb4`.

On GitHub, open a ZIP and choose **View raw** or **Download raw file** to download it.

## Install using the replace-files workflow

1. Back up your PhotoCraft source folder.
2. Extract the ZIP matching your source version.
3. Copy its `crates` folder into your PhotoCraft source folder, allowing matching files to be replaced.
4. Close PhotoCraft. In the source folder, run `cargo build --release -p photocraft`.
5. After the build succeeds, launch the newly built `target\release\photocraft.exe`.

An installed 0.11.1 program cannot use these `.rs` files without rebuilding. Avoid replacing an older source folder with files for a newer version. The successful v2.1 PSD polarity fix is included in both ZIPs; do not apply v2.1 again afterward.

## What this repairs

- Preserve RGB artwork, transparency and a separate white `w1` spot channel at 100% solidity.
- Preserve PSD/TIFF spot polarity, including 8/16/32-bit samples.
- Restore TIFF extra sample planes and Photoshop channel metadata on import, including composite fallback.
- Omit an empty TIFF `LMsk` record and order merged-transparency markers before the layer block.

Export scope is one spot plane on RGB documents. Multiple spot or non-RGB spot export remains unsupported with an explicit warning.

## Validation

The 0.11.1 source passed its desktop Cargo check, 1,907 normal tests, strict Clippy, formatting, layering and WebAssembly checks. The 0.10.0 backport passed its desktop Cargo check, 1,836 normal tests and the same static checks. The supplied PSD regression passed separately on both. The reporter confirmed two images exported by the patched 0.10.0 build opened correctly in Photoshop. Photoshop spot options, composite-only opening and RIP plate output still need independent verification.

The full external corpus runner was blocked by a PngSuite HTTP 403. The original Photoshop TIFF reference exceeded the environment attachment-transfer limit and its opt-in regression was not run. Original reference artwork is not included.

## For PhotoCraft maintainers

[Developer patch](developer-fix.patch) and [technical notes with validation](DEVELOPER-NOTES.md). The patch targets `storytold/photocraft` commit `b097800e78405aeb2068113988898f991e707eb4`. It includes regression tests and changes no dependency manifests or lockfiles.

This branch publishes the prepared fix in the reporter's repository. It is **not** an upstream PhotoCraft pull request; GitHub API access from the development environment remained blocked.
