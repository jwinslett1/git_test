PhotoCraft 0.15.1 -- TIFF/PSD spot repair, including CMYK
Credit for reporting and Photoshop/printing tests: @jwinslett1

This is a SOURCE update. It does not patch an installed EXE.
Rust 1.95 or newer is required by PhotoCraft 0.15.1.

EASIEST OPTION
Download PhotoCraft-0.15.1-patched-source.zip and extract it to a NEW folder.
It already contains the fix on a complete, pinned 0.15.1 source tree.
Open a terminal in its photocraft-main folder and run:

cargo check --locked
cargo build --release -p photocraft

On Windows, the built program is target\release\photocraft.exe.
The archive does not contain the bulky target build directory.

REPLACEMENT-FILE OPTION
Back up your source folder first. Extract PhotoCraft-0.15.1-replacement-files.zip.
Copy the contents of its photocraft-main folder (crates and docs) into your
0.15.1 photocraft-main source folder, accepting file replacements.
Use a clean 0.15.1 source tree if you previously copied old patch files into it.
The complete patched-source ZIP above avoids source-version mismatches.
Run the same Cargo commands above.

Do not reuse replacement files across future PhotoCraft versions. The files
are based on main commit 28f3c18c0d11d69005d224a0a5d5edc56f1fe858, version 0.15.1.
Developers can apply developer-fix.patch to that base instead.

WHAT CHANGED
- Rebased on current 0.15.1 code; DICOM and IFF support is retained. This fixes
  the non-exhaustive Format::Dicom / Format::Iff Cargo errors in the supplied log.
- RGB and CMYK TIFF spot export, with optional independent transparency.
- CMYK + transparency + spot writes six samples, not an RGB five-sample file.
- A plain single CMYK raster layer keeps its original C/M/Y/K separations.
- Names, spot color, solidity, polarity, layer data and extra samples survive
  export/import. The document's chosen name and ink settings are preserved;
  this does not forcibly rename existing channels or assign ink colors.
- Keeps the PSD polarity correction, applies boundary inversion once, and
  retains the Photoshop layer-data repair. Interactive brush painting is not changed.
- Older TIFFs with Pascal-only channel names retain correct transparency/spot alignment.

WHAT TO VERIFY ON YOUR COMPUTER
Save an RGB PNG with a white w1 spot, then repeat with a CMYK image.
Save layered and composite-only TIFFs. Reopen in PhotoCraft and Photoshop.
Check artwork, transparency, white w1 at 100% solidity, polarity and printing.
Automated file tests do not prove Photoshop or RIP acceptance. No Windows
binary or actual Adobe Photoshop session was available for this rebuild.
See VALIDATION.txt for executed checks and the external-corpus limitation.
