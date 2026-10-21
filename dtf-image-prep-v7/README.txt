DTF IMAGE PREP v7

UPDATE
Close the app. Back up main.py and image_engine.py, replace BOTH files
with these versions, and launch as usual. A packaged EXE must be rebuilt.
Existing Python dependencies are unchanged from v6.

SELECT INPUT
Browse selects a folder; this browser shows files as well as folders.
Choose PNG files selects one or several files (Ctrl/Shift for multiple).
The app lists PNGs after selection. Select specific entries using Ctrl/Shift,
or leave all unselected to process the entire list.
The browser remembers your last source folder. Initially it starts in
Documents, falling back to your user home folder if Documents is unavailable.

CHANGES
- Spot channel is now lowercase w1, white, 100% solidity.
- TIFF carries Unicode channel names (1045) and modern display metadata
  (1077), alongside legacy metadata. This lets PhotoCraft skip transparency
  and identify the spot entry correctly.
- RGB, transparency and spot pixels retain their previous processing.
- Order remains trim, add 0.5 inch TOTAL per canvas dimension, then spot/TIFF.
- Ghost cleanup input is centered; black GUI retained.
- Existing RESIZED and TIFF FILES folders are reused, ignoring capitalization
  and trailing spaces. Output files with matching names are replaced as before.
- v6 performance improvements remain; processing is one image at a time.

VERIFICATION
18 regression tests passed: metadata alignment and spot settings, selection,
existing output folder reuse, centered input and remembered path, canvas order,
mask equivalence, TIFF-only output, failure/cancel cleanup, 60 small images,
and two consecutive GUI batches.
Teacherfall artwork was re-exported through old and updated writers: all five
TIFF sample planes match exactly. This checks the metadata update does not
change the generated mask; existing TIFFs need re-exporting for new metadata.
Qt dark GUI visually checked with offscreen rendering on Linux.
Actual PhotoCraft/Photoshop reopening and Windows native file-dialog behavior
still require verification on your computer. Source artwork samples are not
included in this public update.

NEW PYTHON ENVIRONMENT
python -m pip install -r requirements.txt
python main.py

DEVELOPER TESTS
python -m pip install pytest
python -m pytest tests -q
