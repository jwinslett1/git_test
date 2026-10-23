## Update for PhotoCraft 0.15.1: RGB and CMYK TIFF spot-channel repair

Follow-up to https://github.com/storytold/photocraft/issues/8122.

The repair has been rebuilt against PhotoCraft **0.15.1**, upstream commit `28f3c18c0d11d69005d224a0a5d5edc56f1fe858`, and now covers **CMYK TIFF export with a separate spot channel** as well as RGB.

The previous replacement files were incompatible with newer source: overwriting `crates/codecs/src/lib.rs` removed the newer DICOM/IFF match arms and caused Cargo E0004 errors. This update preserves those format paths.

Changes:
- RGB or CMYK artwork, optional transparency, and one separate spot plane at 8-bit, 16-bit integer, and 32-bit float depths.
- CMYK + transparency + spot exports six samples with ExtraSamples `[2, 0]`; the spot is not another transparency channel.
- Preserves native C/M/Y/K separations for a plain single raster layer.
- Retains the Photoshop embedded-layer-data repairs and PSD spot-polarity correction, with conversion once at the file boundary. Internal coverage remains 1 = ink; brush painting semantics are unchanged.
- Restores TIFF spot samples and channel metadata on import, including Pascal-only legacy channel names.

### Manual testing by @jwinslett1

Both RGB and CMYK TIFF exports opened successfully in Adobe Photoshop. Both reopened in the patched PhotoCraft build with `w1` retained. The spot overlay was initially hidden; enabling visibility displayed it correctly. Production RIP testing of this 0.15.1 rebuild remains pending.

### Automated validation

- 2,148 normal tests passed, zero failed; 15 normally ignored tests.
- Two supplied Photoshop reference tests were run separately and passed (these are among the normally ignored tests).
- Full workspace Cargo check, strict Clippy for affected crates, formatting, dependency layering and WebAssembly checks passed on Linux/Rust 1.95.
- Independent TIFF reading confirmed that both layered and composite-only CMYK cat exports preserve alpha and spot pixels exactly. CMYK pixels match Photoshop exactly after accounting for associated versus straight alpha.
- The external corpus runner stopped because the required PngSuite download returned HTTP 403; that full corpus run did not execute.
- Windows execution and interactive spot-painting behavior were not verified by the automated checks.

### Files for review

- [Developer patch](https://github.com/jwinslett1/git_test/blob/photocraft-tiff-fix-0.15.1/photocraft-0.15.1-tiff-fix/developer-fix.patch)
- [Validation details](https://github.com/jwinslett1/git_test/blob/photocraft-tiff-fix-0.15.1/photocraft-0.15.1-tiff-fix/VALIDATION.txt)
- [Replacement source files ZIP](https://github.com/jwinslett1/git_test/raw/refs/heads/photocraft-tiff-fix-0.15.1/photocraft-0.15.1-tiff-fix/PhotoCraft-0.15.1-replacement-files.zip)
- [Complete patched 0.15.1 source ZIP](https://github.com/jwinslett1/git_test/raw/refs/heads/photocraft-tiff-fix-0.15.1/photocraft-0.15.1-tiff-fix/PhotoCraft-0.15.1-patched-source.zip)

Could you review this update for inclusion in a future release, including the CMYK export case? Any overlapping polarity work should be reconciled so PSD spot samples are not inverted twice.

Credit: @jwinslett1.
