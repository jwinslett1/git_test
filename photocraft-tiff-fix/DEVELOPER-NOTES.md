RGB TIFF exports can lose a DTF white-ink spot channel when reopened in PhotoCraft. The existing TIFF path writes only color and transparency samples, and the decoder discards other samples before the document importer can recover their Photoshop channel metadata. The reporter also encountered Photoshop errors reading the embedded layer data.

This change preserves one separate spot plane on RGB TIFF export, alongside optional straight transparency, and restores non-transparency planes on import using Photoshop channel names and DisplayInfo. RGB + transparency + spot uses `ExtraSamples=[2,0]`; an opaque RGB image plus spot uses `[0]`. The supplied `w1` remains white with 100% solidity. Composite-only TIFFs and the damaged-layer fallback retain the spot as well.

It preserves the experimentally verified 8-bit PSD spot-polarity inversion and adds the corresponding 16-bit/float handling without changing ordinary alpha. TIFF uses those exported planes without a second inversion. Embedded layer data omits an absent global mask instead of emitting an empty `LMsk`, and merged-transparency marker blocks precede the layer block.

Validation:

- `cargo check --locked -p photocraft`: passed on Linux/Rust 1.95.
- `cargo test --locked -p photocraft-psd -p photocraft-codecs -p photocraft-io`: 1,907 passed, zero failed, 13 ignored.
- Explicit supplied PSD regression: passed separately.
- Strict Clippy for all targets of those three crates, formatting, `cargo xtask layers`, and `cargo xtask wasm`: passed.
- Independent psdtags/tifffile readers verified identical RGBA layer samples and identical composite transparency/spot samples against the supplied PSD.
- Reporter @jwinslett1 tested the backported 0.10.0 build and confirmed two exported images opened correctly in Adobe Photoshop. The backport also passed 1,836 normal tests plus the supplied PSD regression.

Limitations: this generalizes TIFF import but exports only one spot channel on RGB documents. Photoshop channel options/composite-only opening and RIP output still need independent manual verification. The original Photoshop TIFF reference could not be transferred through the environment's attachment limit; its opt-in regression is not claimed as run. The external corpus runner was blocked at the pinned PngSuite download by HTTP 403. Private reference artwork is not included in this change.
