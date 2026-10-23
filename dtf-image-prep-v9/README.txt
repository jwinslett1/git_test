DTF IMAGE PREP v9

UPDATE AN EXISTING INSTALLATION
Close the app. Back up main.py, image_engine.py, and png_inspection.py.
Replace all THREE files with these versions in the same app folder.
Launch the app as usual. Dependencies are unchanged from v8.1.
A previously packaged EXE needs rebuilding to include source changes.

LAYOUT
Three resizable columns: checked PNGs and PNG output; image preview;
canvas/spot settings and processing activity. Drag the dividers to resize.
Browse uses the standard system folder picker, including network locations
available to your operating-system user. Source PNGs are listed afterward.
All files initially have white checkboxes with dark ticks. Select all controls
the batch. Clicking a filename changes the preview without changing its check.
Only checked files are processed. An empty checked list processes nothing.

PREVIEW
Displays the ORIGINAL PNG with a checkerboard behind transparency.
Fit preserves proportions; 100% uses one source pixel per physical screen pixel.
At 100%, drag or use scrollbars to navigate. This is not a processed-output preview.

INSPECTION
Transparent BG: green Yes means at least 95% of the outer edge is fully
transparent. No means completely opaque; Partial and Empty require review.
This cannot prove that every interior background region is clear.
Ghost pixels: red dot means possible ghosts; blank means none detected.
Five or more faint pixels (alpha 1-30), farther than 10 pixels in a square
neighborhood from stronger artwork, triggers the advisory flag. Intentional faint
details may also trigger it. No flag cannot guarantee every stray pixel is absent.
Hover for explanations. Checking, Review, and Error states remain explicit.
DPI shows embedded resolution, not an image-quality rating; Unknown means missing
or invalid metadata. Separate X/Y values appear when resolutions differ.

PROCESSING OPTIONS
PNG output: None / Save resized files in new folder / Overwrite existing files.
Overwrite requires confirmation. Existing RESIZED and TIFF FILES folders are
reused regardless of capitalization or trailing spaces. Matching outputs replace
previous outputs, as in prior versions.
Trim Enable: cleanup, trim, then expand each TOTAL canvas dimension by the chosen
inches. Default 0.5 inch adds 0.25 inch per side. Zero expansion is allowed.
Trim Disable: cleanup still applies, but dimensions are preserved and expansion
is skipped. The disabled expansion value is retained for when trim is re-enabled.
Source DPI is preserved. Files without valid DPI retain the previous 300-DPI
processing fallback (the inspection table still shows Unknown).
Ghost cleanup dropdown: 1-10, default 4; alpha at or below this becomes zero.
Tiny islands: On/Off, default On. Removes small disconnected components,
including opaque specks the alpha threshold cannot remove. Turn Off for
intentional tiny dots or very fine disconnected details.
TIFF option enables separate w1 spot exports: white, 100% solidity, correct
Photoshop polarity, independent of artwork transparency.
Mask contraction: 0-3 pixels, default 1 (previous default was 2).
0 uses alpha unchanged, without contraction or blur. 1-3 retain the previous
minimum filter and slight edge blur. The new default deliberately changes the
underbase compared with old default 2; choose 2 to match that old setting.

VERIFICATION
33 regression tests passed, including file checking, Select all, preview switching,
custom canvas sizes, trim disabled, zero contraction, cleanup, TIFF resources,
asynchronous inspection, cancellation, failure cleanup, and batch processing.
Tiger Creek exported at matching old settings has all five TIFF sample planes
and Photoshop resource bytes identical to v8.1. GUI inspected offscreen on Linux
at 1440x850 and 1100x700. Smaller panes can scroll; dividers adjust the balance.
Windows native rendering, screen scaling, and printing with changed settings still
need checking on your computer. No user artwork is included in this package.

NEW PYTHON ENVIRONMENT
python -m pip install -r requirements.txt
python main.py

DEVELOPER TESTS
python -m pip install pytest
python -m pytest tests -q
