"""DTF Image Prep - Windows desktop application prototype."""
from __future__ import annotations

import sys
import threading
import traceback
import tempfile
from time import perf_counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal, Qt, QSettings
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QRadioButton, QButtonGroup, QSpinBox, QVBoxLayout, QWidget,
    QListWidget, QListWidgetItem, QGroupBox, QPlainTextEdit, QScrollArea, QBoxLayout,
)

from image_engine import APP_NAME, prepare_image, save_prepared_png, export_tiff_image_with_w1, verify_tiff_structure

@dataclass
class JobSettings:
    source_dir: Path
    overwrite: bool
    save_png: bool
    shrink_px: int
    make_tiffs: bool
    alpha_threshold: int
    remove_islands: bool


class Worker(QObject):
    progress = Signal(int, int, str)
    log = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, settings: JobSettings):
        super().__init__()
        self.settings = settings
        self.cancel_event = threading.Event()

    def request_stop(self):
        """Cooperative cancellation; current image finishes safely before stopping."""
        self.cancel_event.set()

    def run(self):
        try:
            files = sorted(p for p in self.settings.source_dir.iterdir()
                           if p.is_file() and p.suffix.lower() == ".png"
                           and not p.name.endswith(".dtfprep-tmp.png")
                           and ".dtfprep-" not in p.name)
            if not files:
                self.finished.emit(False, "No PNG files were found in the selected directory.")
                return
            resized_dir = self.settings.source_dir if self.settings.overwrite else self.settings.source_dir / "RESIZED"
            tiff_dir = self.settings.source_dir / "TIFF FILES"
            if self.settings.save_png and not self.settings.overwrite:
                resized_dir.mkdir(parents=True, exist_ok=True)
            if self.settings.make_tiffs:
                tiff_dir.mkdir(parents=True, exist_ok=True)
            errors = []
            completed = 0
            for i, source in enumerate(files, 1):
                if self.cancel_event.is_set():
                    self.finished.emit(False, f"Stopped by user after {completed} of {len(files)} images. Already completed outputs were kept.")
                    return
                temp_png = None
                temp_tiff = None
                prepared = None
                started = perf_counter()
                try:
                    final_png = source if self.settings.overwrite else resized_dir / f"{source.stem}_resized.png"
                    prepared = prepare_image(source, self.settings.alpha_threshold, self.settings.remove_islands)
                    size = prepared.size
                    # TIFF-only jobs never encode or reload an intermediate PNG.
                    if self.settings.save_png:
                        temp_png = self._temporary_path(final_png, ".png")
                        save_prepared_png(prepared, temp_png)

                    final_tiff = None
                    if self.settings.make_tiffs:
                        final_tiff = tiff_dir / (final_png.stem + ".tif")
                        temp_tiff = self._temporary_path(final_tiff, ".tif")
                        export_tiff_image_with_w1(prepared, temp_tiff, self.settings.shrink_px)
                        verified, detail = verify_tiff_structure(temp_tiff)
                        if not verified:
                            raise RuntimeError(detail)
                        self.log.emit(f"TIFF structure: {detail}")

                    # Stop safely at the image boundary, before committing its outputs.
                    if self.cancel_event.is_set():
                        self.log.emit(f"Stopped before saving {source.name}; removing temporary outputs.")
                        for temporary in (temp_png, temp_tiff):
                            if temporary is not None:
                                temporary.unlink(missing_ok=True)
                        self.finished.emit(False, f"Stopped by user after {completed} of {len(files)} images. Already completed outputs were kept.")
                        return
                    # Commit outputs only after PNG and TIFF (if enabled) have succeeded.
                    if self.settings.save_png:
                        temp_png.replace(final_png)
                    if self.settings.make_tiffs and final_tiff is not None and temp_tiff is not None:
                        temp_tiff.replace(final_tiff)
                    msg = f"Processed {source.name} → {size[0]} × {size[1]} px; PNG {'saved' if self.settings.save_png else 'not saved'}; W1 TIFF {'created' if self.settings.make_tiffs else 'not requested'}; {perf_counter() - started:.2f} s"
                    self.log.emit(msg)
                    completed += 1
                except Exception as exc:
                    for temporary in (temp_png, temp_tiff):
                        if temporary is not None:
                            try:
                                temporary.unlink(missing_ok=True)
                            except Exception:
                                pass
                    errors.append(f"{source.name}: {exc}")
                    self.log.emit(f"ERROR: {source.name}: {exc}")
                finally:
                    if prepared is not None:
                        prepared.close()
                self.progress.emit(i, len(files), source.name)
            if errors:
                self.finished.emit(False, f"Finished with {len(errors)} error(s) out of {len(files)} file(s).\n" + "\n".join(errors[:12]))
            else:
                self.finished.emit(True, f"Finished processing {len(files)} PNG file(s).")
        except Exception as exc:
            self.finished.emit(False, f"Processing failed: {exc}\n{traceback.format_exc()}")

    @staticmethod
    def _temporary_path(destination: Path, suffix: str) -> Path:
        # Unique same-directory staging files allow atomic per-output replacement,
        # without overwriting or deleting a pre-existing temporary file.
        import os
        fd, name = tempfile.mkstemp(prefix=f".{destination.stem}.dtfprep-", suffix=suffix, dir=destination.parent)
        os.close(fd)
        return Path(name)


class DropPanel(QFrame):
    clicked = Signal()
    def __init__(self):
        super().__init__()
        self.setObjectName("dropPanel")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(6)
        icon = QLabel("▣")
        icon.setObjectName("dropIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Choose your PNG folder")
        title.setObjectName("dropTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("Batch process transparent artwork from one directory")
        hint.setObjectName("muted")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addWidget(hint)
    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME + " v6")
        self.resize(1060, 780)
        self.setMinimumSize(510, 440)
        self.settings_store = QSettings("DTF Image Prep", "DTF Image Prep")
        saved_geometry = self.settings_store.value("window_geometry")
        if saved_geometry is not None:
            self.restoreGeometry(saved_geometry)
        self.source_dir: Optional[Path] = None
        self.thread: Optional[QThread] = None
        self.worker: Optional[Worker] = None
        self._build_ui()
        self._apply_style()

    def _build_ui(self):
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(14, 12, 14, 12)
        root_layout.setSpacing(9)

        header = QHBoxLayout()
        brand = QVBoxLayout()
        title = QLabel("DTF Image Prep")
        title.setObjectName("appTitle")
        subtitle = QLabel("Transparent PNG preparation and W1 white-ink TIFFs")
        subtitle.setObjectName("muted")
        brand.addWidget(title)
        brand.addWidget(subtitle)
        header.addLayout(brand)
        header.addStretch(1)
        self.status_badge = QLabel("●  READY")
        self.status_badge.setObjectName("statusBadge")
        header.addWidget(self.status_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        root_layout.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        settings_content = QWidget()
        self.settings_columns = QBoxLayout(QBoxLayout.Direction.LeftToRight, settings_content)
        self.settings_columns.setContentsMargins(0, 0, 0, 0)
        self.settings_columns.setSpacing(14)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(14)

        folder_group = QGroupBox("01  ·  Source files")
        folder_layout = QVBoxLayout(folder_group)
        self.drop_panel = DropPanel()
        self.drop_panel.clicked.connect(self.choose_folder)
        folder_layout.addWidget(self.drop_panel)
        path_row = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("No folder selected")
        self.folder_edit.setReadOnly(True)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.choose_folder)
        path_row.addWidget(self.folder_edit, 1)
        path_row.addWidget(browse)
        folder_layout.addLayout(path_row)
        self.file_list = QListWidget()
        self.file_list.setMinimumHeight(100)
        folder_layout.addWidget(self.file_list)
        self.file_count = QLabel("0 PNG files found")
        self.file_count.setObjectName("muted")
        folder_layout.addWidget(self.file_count)
        left_layout.addWidget(folder_group, 3)

        output_group = QGroupBox("02  ·  PNG output")
        output_layout = QVBoxLayout(output_group)
        self.save_png = QCheckBox("Save resized PNG files")
        self.save_png.setChecked(True)
        self.save_png.setStyleSheet("font-weight:700")
        output_layout.addWidget(self.save_png)
        self.overwrite_radio = QRadioButton("Overwrite original PNG files")
        self.new_folder_radio = QRadioButton('Create “RESIZED” folder and append _resized')
        self.new_folder_radio.setChecked(True)
        self.output_group = QButtonGroup(self)
        self.output_group.addButton(self.overwrite_radio)
        self.output_group.addButton(self.new_folder_radio)
        self.save_png.toggled.connect(self.update_output_choice)
        self.save_png.toggled.connect(self.refresh_summary)
        output_layout.addWidget(self.overwrite_radio)
        output_layout.addWidget(self.new_folder_radio)
        self.output_choice = QLabel()
        self.output_choice.setObjectName("outputChoice")
        self.output_choice.setWordWrap(True)
        output_layout.addWidget(self.output_choice)
        self.overwrite_radio.toggled.connect(self.update_output_choice)
        self.new_folder_radio.toggled.connect(self.update_output_choice)
        self.update_output_choice()
        self.overwrite_warning = QLabel("Overwriting replaces source PNGs only after the PNG and requested TIFF export both succeed.")
        self.overwrite_warning.setObjectName("muted")
        self.overwrite_warning.setWordWrap(True)
        output_layout.addWidget(self.overwrite_warning)
        left_layout.addWidget(output_group, 1)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(14)

        canvas_group = QGroupBox("03  ·  Canvas & resolution")
        canvas_layout = QGridLayout(canvas_group)
        canvas_layout.addWidget(QLabel("Trim transparent edges"), 0, 0)
        trim_label = QLabel("Enabled")
        trim_label.setObjectName("valueLabel")
        canvas_layout.addWidget(trim_label, 0, 1, Qt.AlignmentFlag.AlignRight)
        canvas_layout.addWidget(QLabel("Total canvas increase"), 1, 0)
        pad_label = QLabel("+0.5 in W and H")
        pad_label.setObjectName("valueLabel")
        canvas_layout.addWidget(pad_label, 1, 1, Qt.AlignmentFlag.AlignRight)
        canvas_layout.addWidget(QLabel("Resolution"), 2, 0)
        resolution_label = QLabel("Preserve source PPI")
        resolution_label.setObjectName("valueLabel")
        canvas_layout.addWidget(resolution_label, 2, 1, Qt.AlignmentFlag.AlignRight)
        canvas_layout.addWidget(QLabel("Ghost-pixel cleanup"), 3, 0)
        self.alpha_threshold = QSpinBox()
        self.alpha_threshold.setRange(0, 50)
        self.alpha_threshold.setValue(4)
        self.alpha_threshold.setSuffix(" / 255")
        self.alpha_threshold.setToolTip("Alpha values at or below this threshold become fully transparent. Start at 4; increase cautiously for ghost pixels.")
        canvas_layout.addWidget(self.alpha_threshold, 3, 1)
        self.remove_islands = QCheckBox("Remove tiny disconnected pixel islands")
        self.remove_islands.setChecked(True)
        self.remove_islands.setToolTip("Removes tiny disconnected fragments, not connected artwork edges. Turn off if your design contains intentional tiny dots.")
        canvas_layout.addWidget(self.remove_islands, 4, 0, 1, 2)
        canvas_layout.setColumnStretch(0, 1)
        right_layout.addWidget(canvas_group)

        spot_group = QGroupBox("04  ·  White underbase / spot mask")
        spot_layout = QVBoxLayout(spot_group)
        self.make_tiff = QCheckBox("Create TIFF exports in “TIFF FILES”")
        self.make_tiff.setChecked(True)
        spot_layout.addWidget(self.make_tiff)
        self.make_tiff.toggled.connect(self.refresh_summary)
        contraction_label = QLabel("Mask contraction")
        contraction_label.setStyleSheet("font-weight:700; font-size:11pt")
        spot_layout.addWidget(contraction_label)
        pixel_row = QHBoxLayout()
        self.shrink_checks = []
        self.shrink_group = QButtonGroup(self)
        self.shrink_group.setExclusive(True)
        for pixels in (1, 2, 3):
            option = QCheckBox(f"{pixels} pixel{'s' if pixels != 1 else ''}")
            self.shrink_group.addButton(option, pixels)
            option.setChecked(pixels == 2)
            pixel_row.addWidget(option)
            self.shrink_checks.append(option)
        pixel_row.addStretch(1)
        spot_layout.addLayout(pixel_row)
        self.make_tiff.toggled.connect(self.update_tiff_controls)
        self.update_tiff_controls()
        note = QLabel("Spot plate: white · 100% solidity · channel “W1”\nTIFF keeps artwork transparency separate from the W1 white-ink mask. Test the exported TIFF in RIIN before production printing.")
        note.setObjectName("notice")
        note.setWordWrap(True)
        spot_layout.addWidget(note)
        right_layout.addWidget(spot_group, 2)

        summary_group = QGroupBox("05  ·  Output summary")
        summary_layout = QVBoxLayout(summary_group)
        self.summary = QLabel("Select a source folder to preview the batch.")
        self.summary.setWordWrap(True)
        self.summary.setObjectName("muted")
        summary_layout.addWidget(self.summary)
        right_layout.addWidget(summary_group, 1)

        self.settings_columns.addWidget(left, 1)
        self.settings_columns.addWidget(right, 1)
        scroll.setWidget(settings_content)
        root_layout.addWidget(scroll, 1)
        self._settings_scroll = scroll
        self._update_layout_mode()

        bottom = QFrame()
        bottom.setObjectName("bottomPanel")
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(16, 14, 16, 14)
        bottom_layout.setSpacing(10)
        progress_row = QHBoxLayout()
        self.progress_label = QLabel("Ready to process")
        self.progress_label.setObjectName("muted")
        progress_row.addWidget(self.progress_label)
        progress_row.addStretch(1)
        self.progress_percent = QLabel("0%")
        self.progress_percent.setObjectName("valueLabel")
        progress_row.addWidget(self.progress_percent)
        bottom_layout.addLayout(progress_row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        bottom_layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        self.open_folder_btn = QPushButton("Open source folder")
        self.open_folder_btn.setObjectName("secondaryButton")
        self.open_folder_btn.setEnabled(False)
        self.open_folder_btn.clicked.connect(self.open_source_folder)
        buttons.addWidget(self.open_folder_btn)
        buttons.addStretch(1)
        self.stop_btn = QPushButton("■   Stop processing")
        self.stop_btn.setObjectName("stopButton")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setToolTip("Stop safely at the next image boundary. Completed files remain saved; the current unfinished image is discarded.")
        self.stop_btn.clicked.connect(self.stop_processing)
        buttons.addWidget(self.stop_btn)
        self.run_btn = QPushButton("▶   Process images")
        self.run_btn.setObjectName("primaryButton")
        self.run_btn.clicked.connect(self.start_processing)
        buttons.addWidget(self.run_btn)
        bottom_layout.addLayout(buttons)
        root_layout.addWidget(bottom)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(72)
        self.log.setPlaceholderText("Processing activity and errors will appear here.")
        root_layout.addWidget(self.log)
        self.log.setFixedHeight(72)
        self.setCentralWidget(root)

    def _update_layout_mode(self):
        narrow = self.width() < 850
        direction = QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight
        if self.settings_columns.direction() != direction:
            self.settings_columns.setDirection(direction)
        # Prevent the left-hand file list from taking excessive height in narrow mode.
        self.file_list.setMaximumHeight(180 if narrow else 16777215)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "settings_columns"):
            self._update_layout_mode()

    def closeEvent(self, event):
        if self.thread is not None and self.thread.isRunning():
            QMessageBox.information(self, APP_NAME, "Processing is still running. Click Stop processing and wait for it to finish before closing.")
            event.ignore()
            return
        self.settings_store.setValue("window_geometry", self.saveGeometry())
        super().closeEvent(event)

    def _apply_style(self):
        # This string is Qt CSS, so comments use /* ... */, not Python's # syntax.
        palette = self.palette()
        for role, color in (
            (QPalette.ColorRole.Window, "#0d1117"),
            (QPalette.ColorRole.WindowText, "#e6edf3"),
            (QPalette.ColorRole.Base, "#090d12"),
            (QPalette.ColorRole.AlternateBase, "#1b2430"),
            (QPalette.ColorRole.Text, "#e6edf3"),
            (QPalette.ColorRole.Button, "#253042"),
            (QPalette.ColorRole.ButtonText, "#e6edf3"),
            (QPalette.ColorRole.Highlight, "#3478f6"),
            (QPalette.ColorRole.HighlightedText, "#ffffff"),
            (QPalette.ColorRole.PlaceholderText, "#98a6b9"),
            (QPalette.ColorRole.ToolTipBase, "#1b2430"),
            (QPalette.ColorRole.ToolTipText, "#e6edf3"),
        ):
            palette.setColor(role, QColor(color))
        self.setPalette(palette)
        self.setStyleSheet("""
            /* Black theme with readable controls, independent of the OS theme. */
            QMainWindow, QWidget { background: #0d1117; color: #e6edf3; font-family: 'Segoe UI'; font-size: 10pt; }
            QLabel, QCheckBox, QRadioButton { background: transparent; }
            QLabel#appTitle { font-size: 25pt; font-weight: 700; color: #f0f6fc; }
            QLabel#muted { color: #a7b3c4; }
            QLabel#dropIcon { color: #80adff; font-size: 27pt; font-weight: 600; }
            QLabel#dropTitle { color: #dbeafe; font-size: 12pt; font-weight: 650; }
            QLabel#valueLabel { color: #e6edf3; font-weight: 650; }
            QLabel#statusBadge { background: #143525; color: #9de5bf; padding: 8px 12px; border-radius: 10px; font-weight: 700; }
            QLabel#notice { background: #14243c; color: #b6d1fa; border: 1px solid #29466a; border-radius: 8px; padding: 10px; }
            QGroupBox { background: #171e29; border: 1px solid #303d50; border-radius: 12px; margin-top: 13px; padding: 14px; font-weight: 700; color: #e6edf3; }
            QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 5px; }
            QFrame#dropPanel { background: #111b2a; border: 1px dashed #42618a; border-radius: 10px; }
            QFrame#bottomPanel { background: #171e29; border: 1px solid #303d50; border-radius: 12px; }
            QLineEdit, QListWidget, QPlainTextEdit, QComboBox, QSpinBox { background: #090d12; color: #e6edf3; border: 1px solid #36465c; border-radius: 7px; padding: 8px; selection-background-color: #3478f6; selection-color: #ffffff; }
            QListWidget::item { padding: 5px; }
            QPushButton { background: #253042; color: #e6edf3; border: 1px solid #42536c; border-radius: 8px; padding: 9px 14px; font-weight: 600; }
            QPushButton:hover { background: #304465; border-color: #80adff; }
            QPushButton:disabled { color: #78869b; background: #1c2430; border-color: #303d50; }
            QPushButton#primaryButton { background: #3478f6; color: #ffffff; border: none; padding: 11px 22px; font-size: 11pt; }
            QPushButton#primaryButton:hover { background: #2466df; }
            QPushButton#secondaryButton { background: #202b3a; }
            QPushButton#stopButton { background: #3a2022; color: #ffb4ab; border: 1px solid #784349; }
            QPushButton#stopButton:disabled { color: #78869b; background: #1c2430; border: 1px solid #303d50; }
            QRadioButton, QCheckBox { spacing: 8px; padding: 4px 0; }
            QProgressBar { background: #293448; border: none; border-radius: 5px; height: 10px; }
            QProgressBar::chunk { background: #528dff; border-radius: 5px; }
            QSplitter::handle { background: #303d50; width: 2px; }
            QToolTip { background: #1b2430; color: #e6edf3; border: 1px solid #42536c; }
        """)

    def update_tiff_controls(self, *_):
        for option in self.shrink_checks:
            option.setEnabled(self.make_tiff.isChecked())

    def update_output_choice(self, *_):
        self.overwrite_radio.setEnabled(self.save_png.isChecked())
        self.new_folder_radio.setEnabled(self.save_png.isChecked())
        if not self.save_png.isChecked():
            self.output_choice.setText("ACTIVE: PNG saving OFF — TIFF export only")
            self.output_choice.setStyleSheet("background:#14243c;color:#b6d1fa;border-radius:6px;padding:9px;font-weight:700")
        elif self.overwrite_radio.isChecked():
            self.output_choice.setText("ACTIVE: OVERWRITE ORIGINALS — source PNGs will be replaced")
            self.output_choice.setStyleSheet("background:#3a2c16;color:#f3cc87;border:1px solid #705431;border-radius:6px;padding:9px;font-weight:700")
        else:
            self.output_choice.setText("ACTIVE: SAVE COPIES — RESIZED folder; originals remain unchanged")
            self.output_choice.setStyleSheet("background:#143525;color:#9de5bf;border:1px solid #2e6446;border-radius:6px;padding:9px;font-weight:700")
        if self.source_dir:
            self.refresh_summary()

    def refresh_summary(self, *_):
        if self.source_dir:
            count = sum(p.is_file() and p.suffix.lower() == ".png" and ".dtfprep-" not in p.name for p in self.source_dir.iterdir())
            png_mode = "disabled" if not self.save_png.isChecked() else ("OVERWRITE ORIGINALS" if self.overwrite_radio.isChecked() else "RESIZED folder")
            self.summary.setText(f"{count} source PNG(s)\nPNG output: {png_mode}\nTIFF output: {'TIFF FILES' if self.make_tiff.isChecked() else 'disabled'}")

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select folder containing PNG files")
        if not folder:
            return
        self.source_dir = Path(folder)
        self.folder_edit.setText(str(self.source_dir))
        files = sorted(p for p in self.source_dir.iterdir() if p.is_file() and p.suffix.lower() == ".png")
        self.file_list.clear()
        for file in files[:500]:
            self.file_list.addItem(QListWidgetItem("▧  " + file.name))
        if len(files) > 500:
            self.file_list.addItem(QListWidgetItem(f"… and {len(files)-500} more files"))
        self.file_count.setText(f"{len(files)} PNG file{'s' if len(files) != 1 else ''} found")
        self.refresh_summary()
        self.open_folder_btn.setEnabled(True)

    def open_source_folder(self):
        if self.source_dir and self.source_dir.exists():
            import os, subprocess
            if sys.platform == "win32":
                os.startfile(str(self.source_dir))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(self.source_dir)])
            else:
                subprocess.Popen(["xdg-open", str(self.source_dir)])

    def start_processing(self):
        if not self.source_dir or not self.source_dir.exists():
            QMessageBox.information(self, APP_NAME, "Choose a source folder first.")
            return
        if not self.save_png.isChecked() and not self.make_tiff.isChecked():
            QMessageBox.information(self, APP_NAME, "Select at least one output: PNG or TIFF.")
            return
        if self.save_png.isChecked() and self.overwrite_radio.isChecked():
            answer = QMessageBox.warning(self, "Confirm overwrite", "Original PNG files will be replaced after each file is processed. Continue?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        shrink = self.shrink_group.checkedId()
        settings = JobSettings(self.source_dir, self.overwrite_radio.isChecked(), self.save_png.isChecked(), shrink, self.make_tiff.isChecked(), self.alpha_threshold.value(), self.remove_islands.isChecked())
        self.thread = QThread(self)
        self.worker = Worker(settings)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.log.connect(self.log.appendPlainText)
        self.worker.finished.connect(self.on_finished)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self._thread_finished)
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_badge.setText("●  PROCESSING")
        self.status_badge.setStyleSheet("background:#3a2c16;color:#f3cc87;padding:8px 12px;border-radius:10px;font-weight:700")
        self.progress.setValue(0)
        self.log.clear()
        self.thread.start()

    def _thread_finished(self):
        self.thread = None
        self.worker = None
        self.run_btn.setEnabled(True)

    def stop_processing(self):
        if self.worker is not None:
            self.worker.request_stop()
            self.stop_btn.setEnabled(False)
            self.progress_label.setText("Stop requested — waiting for safe stopping point…")
            self.log.appendPlainText("Stop requested. The current image will finish its computation, then temporary outputs are discarded. Completed files are retained.")

    def on_progress(self, current, total, filename):
        pct = int(current * 100 / max(total, 1))
        self.progress.setValue(pct)
        self.progress_percent.setText(f"{pct}%")
        self.progress_label.setText(f"Processing {current} of {total}: {filename}")

    def on_finished(self, ok, message):
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.status_badge.setText("●  COMPLETE" if ok else "●  REVIEW LOG")
        self.status_badge.setStyleSheet("background:#143525;color:#9de5bf;padding:8px 12px;border-radius:10px;font-weight:700" if ok else "background:#3a2c16;color:#f3cc87;padding:8px 12px;border-radius:10px;font-weight:700")
        self.progress_label.setText("Batch complete" if ok else "Batch finished with issues")
        self.log.appendPlainText(message)
        if ok:
            QMessageBox.information(self, APP_NAME, message + "\n\nImportant: the TIFF now includes W1 spot-channel metadata, but confirm that your RIIN version recognizes it before production printing.")
        else:
            QMessageBox.warning(self, APP_NAME, message)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Segoe UI", 10))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
