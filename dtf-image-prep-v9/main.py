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

from PySide6.QtCore import QObject, QThread, Signal, Qt, QSettings, QStandardPaths, QRunnable, QThreadPool
from PySide6.QtGui import QColor, QFont, QPalette, QImageReader, QPixmap, QPainter, QBrush, QPen, QPainterPath
from PySide6.QtWidgets import (
    QStyledItemDelegate, QProxyStyle, QStyle, QDoubleSpinBox, QSplitter, QGraphicsView, QGraphicsScene,
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QRadioButton, QButtonGroup, QSpinBox, QVBoxLayout, QWidget,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QAbstractItemView, QGroupBox, QPlainTextEdit, QScrollArea, QBoxLayout,
)

from png_inspection import inspect_png

from image_engine import APP_NAME, prepare_image, save_prepared_png, export_tiff_image_with_w1, verify_tiff_structure

class InspectionSignals(QObject):
    result = Signal(int, int, object)


class InspectionJob(QRunnable):
    def __init__(self, generation, paths, cancel):
        super().__init__()
        self.generation, self.paths, self.cancel = generation, paths, cancel
        self.signals = InspectionSignals()

    def run(self):
        for row, path in enumerate(self.paths):
            if self.cancel.is_set():
                break
            try:
                result = inspect_png(path)
            except Exception as exc:
                result = {"error": str(exc)}
            if not self.cancel.is_set():
                self.signals.result.emit(self.generation, row, result)


class WhiteCheckStyle(QProxyStyle):
    """Paint real white checkbox squares, including item-view indicators."""
    def drawPrimitive(self, element, option, painter, widget=None):
        if element in (QStyle.PrimitiveElement.PE_IndicatorCheckBox, QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck):
            painter.save();r=option.rect.adjusted(1,1,-1,-1)
            painter.setPen(QPen(QColor('#8192a6'),1));painter.setBrush(QColor('white'));painter.drawRoundedRect(r,2,2)
            painter.setPen(QPen(QColor('#101820'),2))
            if option.state & QStyle.StateFlag.State_NoChange:
                painter.drawLine(r.left()+3,r.center().y(),r.right()-3,r.center().y())
            elif option.state & QStyle.StateFlag.State_On:
                path=QPainterPath();path.moveTo(r.left()+2,r.center().y());path.lineTo(r.center().x()-1,r.bottom()-3);path.lineTo(r.right()-2,r.top()+3);painter.drawPath(path)
            painter.restore();return
        super().drawPrimitive(element,option,painter,widget)


class PreviewSignals(QObject):
    result=Signal(int,object,str,str)


class PreviewJob(QRunnable):
    def __init__(self,generation,path):
        super().__init__();self.generation=generation;self.path=path;self.signals=PreviewSignals()
    def run(self):
        reader=QImageReader(str(self.path));image=reader.read()
        self.signals.result.emit(self.generation,image,self.path.name,reader.errorString() if image.isNull() else '')


class FileTable(QTreeWidget):
    def resizeEvent(self,event):
        super().resizeEvent(event)
        # Preserve a readable filename column; smaller panes scroll horizontally.
        other=sum(self.columnWidth(i) for i in (0,2,3,4))
        self.setColumnWidth(1,max(120,self.viewport().width()-other))


class GhostDotDelegate(QStyledItemDelegate):
    def initStyleOption(self,option,index):
        super().initStyleOption(option,index)
        if index.data()=="●":
            option.palette.setColor(QPalette.ColorRole.HighlightedText,QColor("#ff6666"))
            option.palette.setColor(QPalette.ColorRole.Text,QColor("#ff6666"))


class ImagePreview(QGraphicsView):
    def __init__(self):
        super().__init__();self.setScene(QGraphicsScene(self));self.fit_mode=True;self.image_item=None
        tile=QPixmap(24,24);tile.fill(QColor('#dce0e5'));p=QPainter(tile)
        p.fillRect(0,0,12,12,QColor('#aab2be'));p.fillRect(12,12,12,12,QColor('#aab2be'));p.end()
        self.checker_brush=QBrush(tile);self.setBackgroundBrush(self.checker_brush);self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setMinimumSize(220,280)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    def drawBackground(self,painter,rect):
        painter.save();painter.resetTransform()
        painter.fillRect(self.viewport().rect(),self.checker_brush);painter.restore()
    def show_image(self,image):
        self.scene().clear();self.image_item=self.scene().addPixmap(QPixmap.fromImage(image))
        self.scene().setSceneRect(self.image_item.boundingRect());self.set_fit(True)
    def clear_image(self):
        self.scene().clear();self.image_item=None
    def set_fit(self,enabled):
        self.fit_mode=enabled;self.resetTransform()
        policy=Qt.ScrollBarPolicy.ScrollBarAlwaysOff if enabled else Qt.ScrollBarPolicy.ScrollBarAsNeeded
        self.setHorizontalScrollBarPolicy(policy);self.setVerticalScrollBarPolicy(policy)
        if self.image_item:
            if enabled:self.fitInView(self.image_item,Qt.AspectRatioMode.KeepAspectRatio)
            else:
                # QGraphicsView units are device-independent; 100% means one
                # source pixel per physical screen pixel even on HiDPI screens.
                ratio=self.devicePixelRatioF();self.scale(1/ratio,1/ratio)
                self.centerOn(self.image_item)
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self.fit_mode:self.set_fit(True)


@dataclass
class JobSettings:
    source_dir: Path
    overwrite: bool
    save_png: bool
    shrink_px: int
    make_tiffs: bool
    alpha_threshold: int
    remove_islands: bool
    selected_files: Optional[tuple[Path, ...]] = None
    trim: bool = True
    canvas_inches: float = 0.5


def output_folder(parent: Path, name: str) -> Path:
    matches = sorted(p for p in parent.iterdir() if p.is_dir() and p.name.strip().casefold() == name.casefold())
    exact = parent / name
    return exact if exact in matches else (matches[0] if matches else exact)


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
            files = sorted(p for p in (self.settings.selected_files if self.settings.selected_files is not None else self.settings.source_dir.iterdir())
                           if p.is_file() and p.suffix.lower() == ".png"
                           and not p.name.endswith(".dtfprep-tmp.png")
                           and ".dtfprep-" not in p.name)
            if not files:
                self.finished.emit(False, "No PNG files were found in the selected directory.")
                return
            resized_dir = self.settings.source_dir if self.settings.overwrite else output_folder(self.settings.source_dir, "RESIZED")
            tiff_dir = output_folder(self.settings.source_dir, "TIFF FILES")
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
                    prepared = prepare_image(source, self.settings.alpha_threshold, self.settings.remove_islands, self.settings.trim, self.settings.canvas_inches)
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
                    msg = f"Processed {source.name} → {size[0]} × {size[1]} px; PNG {'saved' if self.settings.save_png else 'not saved'}; w1 TIFF {'created' if self.settings.make_tiffs else 'not requested'}; {perf_counter() - started:.2f} s"
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME + " v9")
        self.resize(1360, 820)
        self.setMinimumSize(1020, 640)
        self.settings_store = QSettings("DTF Image Prep", "DTF Image Prep")
        saved_geometry = self.settings_store.value("window_geometry")
        if saved_geometry is not None:
            self.restoreGeometry(saved_geometry)
        self.source_dir: Optional[Path] = None
        self.thread: Optional[QThread] = None
        self.worker: Optional[Worker] = None
        self.inspection_pool = QThreadPool(self)
        self.inspection_pool.setMaxThreadCount(1)
        self.inspection_cancel = threading.Event()
        self.inspection_generation = 0
        self.preview_pool=QThreadPool(self);self.preview_pool.setMaxThreadCount(1)
        self.preview_generation=0
        app=QApplication.instance()
        if not isinstance(app.style(),WhiteCheckStyle):app.setStyle(WhiteCheckStyle('Fusion'))
        self._build_ui()
        self._apply_style()

    def _build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12,10,12,10)
        layout.setSpacing(8)
        heading = QHBoxLayout()
        title = QLabel("DTF Image Prep  ·  v9");title.setObjectName("appTitle")
        heading.addWidget(title);heading.addStretch()
        self.status_badge = QLabel("●  READY");self.status_badge.setObjectName("statusBadge")
        heading.addWidget(self.status_badge);layout.addLayout(heading)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(8)
        left = QWidget();ll = QVBoxLayout(left);ll.setContentsMargins(0,0,0,0)
        folder = QGroupBox("01  ·  Source PNGs");fl=QVBoxLayout(folder)
        pathrow=QHBoxLayout();self.folder_edit=QLineEdit();self.folder_edit.setReadOnly(True)
        self.folder_edit.setPlaceholderText("Choose your PNG folder")
        self.browse_btn=QPushButton("Browse…");self.browse_btn.clicked.connect(self.choose_folder)
        pathrow.addWidget(self.folder_edit,1);pathrow.addWidget(self.browse_btn);fl.addLayout(pathrow)
        self.select_all=QCheckBox("Select all");self.select_all.setTristate(True)
        self.select_all.setChecked(True);self.select_all.clicked.connect(self.toggle_all)
        fl.addWidget(self.select_all)
        self.file_list=FileTable();self.file_list.setColumnCount(5)
        self.file_list.setHeaderLabels(["✓", "PNG file", "Transparent BG", "Ghost pixels", "DPI"])
        self.file_list.setItemDelegateForColumn(3,GhostDotDelegate(self.file_list))
        self.file_list.setRootIsDecorated(False);self.file_list.setUniformRowHeights(True)
        self.file_list.header().setStretchLastSection(False)
        self.file_list.header().setSectionResizeMode(1,QHeaderView.ResizeMode.Interactive)
        self.file_list.header().setMinimumSectionSize(28)
        for col in (0,2,3,4):self.file_list.header().setSectionResizeMode(col,QHeaderView.ResizeMode.ResizeToContents)
        self.file_list.setMinimumHeight(180)
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.file_list.itemChanged.connect(self.on_file_checked)
        self.file_list.currentItemChanged.connect(self.preview_selected)
        fl.addWidget(self.file_list,1)
        self.file_count=QLabel("0 PNGs");self.file_count.setObjectName("muted");fl.addWidget(self.file_count)
        ll.addWidget(folder,1)
        output=QGroupBox("02  ·  PNG output");ol=QVBoxLayout(output)
        self.png_output=QComboBox();self.png_output.addItems(["None", "Save resized files in new folder", "Overwrite existing files"])
        self.png_output.setCurrentIndex(1);self.png_output.currentIndexChanged.connect(self.refresh_summary)
        ol.addWidget(self.png_output)
        self.summary=QLabel("Select a folder to begin.");self.summary.setWordWrap(True);self.summary.setObjectName("muted")
        ol.addWidget(self.summary);ll.addWidget(output)
        self.splitter.addWidget(left)
        previewbox=QGroupBox("Image preview");pl=QVBoxLayout(previewbox)
        zoomrow=QHBoxLayout();fit=QPushButton("Fit");actual=QPushButton("100%")
        fit.clicked.connect(lambda:self.preview.set_fit(True));actual.clicked.connect(lambda:self.preview.set_fit(False))
        zoomrow.addWidget(fit);zoomrow.addWidget(actual);zoomrow.addStretch();pl.addLayout(zoomrow)
        self.preview=ImagePreview();pl.addWidget(self.preview,1)
        self.preview_caption=QLabel("Click a filename to preview the original PNG.")
        self.preview_caption.setWordWrap(True);self.preview_caption.setObjectName("muted");pl.addWidget(self.preview_caption)
        self.splitter.addWidget(previewbox)
        right=QWidget();rl=QVBoxLayout(right);rl.setContentsMargins(0,0,0,0)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.Shape.NoFrame)
        group=QGroupBox("03  ·  Canvas resolution / Spot Color Channel");grid=QGridLayout(group)
        self.trim_edges=QComboBox();self.trim_edges.addItems(["Enable","Disable"])
        self.canvas_increase=QDoubleSpinBox();self.canvas_increase.setRange(0,100);self.canvas_increase.setDecimals(2)
        self.canvas_increase.setSingleStep(.1);self.canvas_increase.setValue(.5);self.canvas_increase.setSuffix(" in total")
        self.canvas_increase.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.canvas_increase.setToolTip("Added to EACH total dimension; 0.5 inch adds 0.25 inch per side. Source DPI is preserved.")
        self.trim_edges.currentIndexChanged.connect(lambda i:self.canvas_increase.setEnabled(i==0))
        self.alpha_threshold=QComboBox()
        for n in range(1,11):self.alpha_threshold.addItem(str(n),n)
        self.alpha_threshold.setCurrentIndex(3)
        self.alpha_threshold.setToolTip("Pixels with alpha at or below this number become fully transparent (out of 255).")
        self.remove_islands=QComboBox();self.remove_islands.addItems(["On","Off"])
        self.remove_islands.setToolTip("Removes tiny disconnected components, including opaque specks. Turn off to preserve intentional tiny dots.")
        for row,(text,widget) in enumerate([("Trim transparent edges",self.trim_edges),("Total canvas increase",self.canvas_increase),("Ghost-pixel cleanup",self.alpha_threshold),("Remove tiny pixel islands",self.remove_islands)]):
            grid.addWidget(QLabel(text),row,0);grid.addWidget(widget,row,1)
        self.make_tiff=QCheckBox("Create TIFF exports in “TIFF FILES”");self.make_tiff.setChecked(True)
        grid.addWidget(self.make_tiff,4,0,1,2)
        self.contraction=QComboBox()
        for n in range(4):self.contraction.addItem(f"{n} pixel{'s' if n!=1 else ''}",n)
        self.contraction.setCurrentIndex(1)
        self.contraction.setToolTip("0 keeps the alpha mask unchanged, without contraction or edge blur.")
        self.make_tiff.toggled.connect(self.contraction.setEnabled);self.make_tiff.toggled.connect(self.refresh_summary)
        grid.addWidget(QLabel("Mask contraction"),5,0);grid.addWidget(self.contraction,5,1)
        note=QLabel("w1 · White · 100% solidity");note.setObjectName("notice");note.setMaximumHeight(50);grid.addWidget(note,6,0,1,2)
        grid.setColumnStretch(1,1);scroll.setWidget(group);rl.addWidget(scroll,3)
        activity=QGroupBox("Processing activity");al=QVBoxLayout(activity)
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setPlaceholderText("Processing activity and errors appear here.")
        al.addWidget(self.log);rl.addWidget(activity,2);self.splitter.addWidget(right)
        self.splitter.setSizes([440,410,410])
        for i in range(3):self.splitter.setStretchFactor(i,1)
        left.setMinimumWidth(330);previewbox.setMinimumWidth(240);right.setMinimumWidth(350)
        layout.addWidget(self.splitter,1)
        bottom=QFrame();bottom.setObjectName("bottomPanel");bl=QVBoxLayout(bottom)
        row=QHBoxLayout();self.progress_label=QLabel("Ready to process");self.progress_percent=QLabel("0%")
        row.addWidget(self.progress_label);row.addStretch();row.addWidget(self.progress_percent);bl.addLayout(row)
        self.progress=QProgressBar();self.progress.setTextVisible(False);bl.addWidget(self.progress)
        buttons=QHBoxLayout();self.open_folder_btn=QPushButton("Open source folder")
        self.open_folder_btn.setEnabled(False);self.open_folder_btn.clicked.connect(self.open_source_folder);buttons.addWidget(self.open_folder_btn);buttons.addStretch()
        self.stop_btn=QPushButton("Stop processing");self.stop_btn.setObjectName("stopButton");self.stop_btn.setEnabled(False);self.stop_btn.clicked.connect(self.stop_processing)
        self.run_btn=QPushButton("Process checked images");self.run_btn.setObjectName("primaryButton");self.run_btn.clicked.connect(self.start_processing)
        buttons.addWidget(self.stop_btn);buttons.addWidget(self.run_btn);bl.addLayout(buttons);layout.addWidget(bottom)
        self.setCentralWidget(root)

    def closeEvent(self, event):
        if self.thread is not None and self.thread.isRunning():
            QMessageBox.information(self, APP_NAME, "Processing is still running. Click Stop processing and wait for it to finish before closing.")
            event.ignore()
            return
        self.preview_pool.clear()
        self.preview_pool.waitForDone()
        self.inspection_cancel.set()
        self.inspection_pool.clear()
        self.inspection_pool.waitForDone()
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
            QLineEdit, QTreeWidget, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: #090d12; color: #e6edf3; border: 1px solid #36465c; border-radius: 7px; padding: 8px; selection-background-color: #3478f6; selection-color: #ffffff; }
            QTreeWidget::item { padding: 5px; }
            QHeaderView::section { background: #202b3a; color: #e6edf3; border: 1px solid #36465c; padding: 5px; }
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

    def selected_sources(self):
        return tuple(Path(item.data(0,Qt.ItemDataRole.UserRole))
                     for item in (self.file_list.topLevelItem(i) for i in range(self.file_list.topLevelItemCount()))
                     if item.checkState(0)==Qt.CheckState.Checked)

    def toggle_all(self, *_):
        checked=self.select_all.checkState()!=Qt.CheckState.Unchecked
        self.file_list.blockSignals(True)
        for i in range(self.file_list.topLevelItemCount()):
            self.file_list.topLevelItem(i).setCheckState(0,Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.file_list.blockSignals(False);self.refresh_summary()

    def on_file_checked(self,item,column):
        if column==0:self.refresh_summary()

    def refresh_summary(self, *_):
        count=len(self.selected_sources());total=self.file_list.topLevelItemCount()
        self.select_all.blockSignals(True)
        self.select_all.setCheckState(Qt.CheckState.Checked if count and count==total else (Qt.CheckState.PartiallyChecked if count else Qt.CheckState.Unchecked))
        self.select_all.blockSignals(False)
        self.summary.setText(f"{count} of {total} PNGs checked\n" + ("Original PNGs will be replaced." if self.png_output.currentIndex()==2 else ""))
        self.file_count.setText(f"{count} / {total} PNGs checked")

    def preview_selected(self,current,previous=None):
        self.preview_generation+=1;self.preview_pool.clear();self.preview.clear_image()
        if current is None:
            self.preview_caption.setText("Click a filename to preview the original PNG.")
            return
        path=Path(current.data(0,Qt.ItemDataRole.UserRole));self.preview_caption.setText(f"Loading {path.name}…")
        job=PreviewJob(self.preview_generation,path);job.signals.result.connect(self.on_preview_result);self.preview_pool.start(job)

    def on_preview_result(self,generation,image,name,error):
        if generation!=self.preview_generation:return
        if error:
            self.preview.clear_image();self.preview_caption.setText(f"Cannot preview {name}: {error}");return
        self.preview.show_image(image);self.preview_caption.setText(f"{name} · {image.width()} × {image.height()} px · Original")

    def browse_start(self):
        remembered = self.settings_store.value("last_source_dir", "")
        if remembered and Path(str(remembered)).is_dir():
            return str(remembered)
        documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        return documents if documents and Path(documents).is_dir() else str(Path.home())

    def show_sources(self, folder, files):
        self.source_dir = Path(folder)
        self.settings_store.setValue("last_source_dir", str(self.source_dir))
        self.folder_edit.setText(str(self.source_dir))
        self.inspection_cancel.set()
        self.inspection_pool.clear()
        self.inspection_cancel = threading.Event()
        self.inspection_generation += 1
        self.file_list.blockSignals(True)
        self.file_list.clear()
        for file in files:
            item = QTreeWidgetItem(["",file.name, "Checking…", "Checking…", "…"])
            item.setCheckState(0,Qt.CheckState.Checked)
            item.setData(0, Qt.ItemDataRole.UserRole, str(file))
            item.setToolTip(1, str(file))
            for column in (2,3,4):
                item.setTextAlignment(column, Qt.AlignmentFlag.AlignCenter)
            self.file_list.addTopLevelItem(item)
        self.file_list.blockSignals(False)
        job = InspectionJob(self.inspection_generation, tuple(files), self.inspection_cancel)
        job.signals.result.connect(self.on_inspection_result)
        self.inspection_pool.start(job)
        self.file_count.setText(f"{len(files)} PNG files")
        self.refresh_summary()
        self.open_folder_btn.setEnabled(True)
        self.preview_selected(None)
        if self.file_list.topLevelItemCount():self.file_list.setCurrentItem(self.file_list.topLevelItem(0))

    def on_inspection_result(self, generation, row, result):
        if generation != self.inspection_generation:
            return
        item = self.file_list.topLevelItem(row)
        if item is None:
            return
        colors = {"green": "#9de5bf", "amber": "#f3cc87", "red": "#ff9292"}
        if "error" in result:
            for column in (2,3,4):
                item.setText(column, "Error")
                item.setForeground(column, QColor(colors["red"]))
                item.setToolTip(column, result["error"])
            return
        for column, key in ((2,"transparency"),(3,"ghost")):
            item.setText(column, ("●" if result[key]=="✓ Possible" else ("" if result[key]=="— None found" else result[key])) if key=="ghost" else result[key])
            item.setForeground(column, QColor(("#ff6666" if key=="ghost" and result[key]=="✓ Possible" else colors[result[key+"_tone"]])))
            item.setToolTip(column, result[key+"_detail"])
        item.setText(4, result["dpi"])
        item.setToolTip(4, "Embedded DPI; Unknown means missing or invalid. DPI alone does not measure image detail.")

    def choose_folder(self):
        selected = QFileDialog.getExistingDirectory(
            self, "Select folder containing PNG files", self.browse_start())
        if selected:
            folder = Path(selected)
            files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".png" and ".dtfprep-" not in p.name)
            self.show_sources(folder, files)

    def choose_files(self):
        names, _ = QFileDialog.getOpenFileNames(self, "Select one or more PNG files", self.browse_start(), "PNG images (*.png *.PNG)")
        if names:
            files = sorted(Path(name) for name in names)
            self.show_sources(files[0].parent, files)

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
        if self.png_output.currentIndex()==0 and not self.make_tiff.isChecked():
            QMessageBox.information(self, APP_NAME, "Select at least one output: PNG or TIFF.")
            return
        if self.png_output.currentIndex()!=0 and self.png_output.currentIndex()==2:
            answer = QMessageBox.warning(self, "Confirm overwrite", "Original PNG files will be replaced after each file is processed. Continue?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        if not self.selected_sources():
            QMessageBox.information(self,APP_NAME,"Check at least one PNG to process.")
            return
        shrink = self.contraction.currentData()
        settings = JobSettings(self.source_dir, self.png_output.currentIndex()==2, self.png_output.currentIndex()!=0, shrink, self.make_tiff.isChecked(), self.alpha_threshold.currentData(), self.remove_islands.currentIndex()==0, self.selected_sources(), self.trim_edges.currentIndex()==0, self.canvas_increase.value())
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
            QMessageBox.information(self, APP_NAME, message + "\n\nImportant: the TIFF now includes w1 spot-channel metadata, but confirm that your RIIN version recognizes it before production printing.")
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
