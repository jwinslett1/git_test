DTF IMAGE PREP v6

INSTALL THE UPDATE
Close the app. Back up your existing main.py and image_engine.py.
Replace those two files with the files in this folder, then launch the app
as you normally do. A previously packaged EXE must be rebuilt to include changes.
The other files are optional documentation and developer tests.

The GUI now deliberately uses a black/dark theme with readable text.
Processing order stays: trim transparent edges, add 0.5 inch TOTAL to each
canvas dimension using source DPI, then generate the contracted W1 mask
and TIFF. At 300 DPI this adds 150 pixels total in each dimension.
RGB artwork, transparency and separate W1 spot pixels are preserved.
This update keeps the original app's TIFF format and uppercase W1 name.

Speed improvements:
- Decode and prepare each source only once.
- Export TIFF directly from the resized image in memory.
- Skip intermediate PNG encoding entirely for TIFF-only output.
- Use faster lossless PNG compression. PNG files may be larger; pixels
  and image quality are unchanged.
- Use SciPy's faster equivalent mask filter, with Pillow fallback.
Images are still processed one at a time to limit memory use for large batches.

Measured here on four generated 3600 x 3600 RGBA PNGs at 300 DPI:
Original PNG+TIFF: 76.14 seconds; updated PNG+TIFF: 7.26 seconds.
Updated TIFF-only: 3.42 seconds. These are synthetic benchmarks on the
cloud machine, not predictions for your own artwork or computer.
All four output PNG pixel arrays and all five TIFF sample arrays match
original output exactly, as do the Photoshop channel resource bytes.
15 automated tests passed, including canvas-before-mask order, mask
filter equivalence, cancellation/failure cleanup, a 60-small-image batch,
and two consecutive GUI processing runs. Dark appearance checked using
Qt offscreen rendering on Linux. Windows appearance and production-sized
30-60 image batches still need checking on your machine. This performance
update does not establish Photoshop or RIP compatibility beyond the original
app's TIFF implementation; test actual output in your printing software.

FROM A NEW PYTHON ENVIRONMENT
python -m pip install -r requirements.txt
python main.py

DEVELOPER TESTS
python -m pip install pytest
python -m pytest tests -q
