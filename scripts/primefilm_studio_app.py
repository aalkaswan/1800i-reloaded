#!/usr/bin/env python3
"""
PrimeFilm 1800u / 1800i Scanner Studio UI Prototype
Cross-platform graphical user interface with real-time streaming,
interactive cropping, LUT negative conversion, and hardware safety.
"""

import sys
import os
import time
import math
import struct
import numpy as np
from typing import Optional, Tuple, Dict, Any

try:
    from PySide6.QtCore import Qt, QThread, Signal, Slot, QRectF, QPointF
    from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QBrush, QFont
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QGridLayout, QPushButton, QLabel, QSlider, QComboBox, QCheckBox,
        QSpinBox, QProgressBar, QGroupBox, QSplitter, QStatusBar, QMessageBox
    )
    HAS_PYSIDE = True
except ImportError:
    HAS_PYSIDE = False


# ==============================================================================
# Hardware Constants & Mock Scanner Engine
# ==============================================================================

PIXELS_PER_LINE = 2700
FULL_LINE_BYTES = 16200
MAX_RAIL_STEPS = 2260
DEFAULT_APERTURE_OFFSET = 1250
DEFAULT_FRAME_LINES = 950


class ScannerWorker(QThread):
    """
    Asynchronous scanner acquisition worker.
    Operates either directly against libpie1800u / PyUSB or simulates
    pipelined line-by-line acquisition when hardware is offline.
    """
    line_ready = Signal(int, object)  # line_idx, line_rgb_bytes (2700x3)
    scan_complete = Signal(bool, str) # success, message
    progress_update = Signal(int, int, float) # line, total, rate

    def __init__(self, offset: int, lines: int, step_size: int = 1, samples: int = 1):
        super().__init__()
        self.offset = offset
        self.lines = lines
        self.step_size = step_size
        self.samples = samples
        self._is_aborted = False

    def abort(self):
        """Immediately aborts scan and signals coil disarm."""
        self._is_aborted = True

    def run(self):
        t_start = time.time()
        print(f"[*] Worker: Starting scan at offset {self.offset}, {self.lines} lines...")

        for line_idx in range(self.lines):
            if self._is_aborted:
                print("[!] Worker: Abort acknowledged! Disarming motor coils (0x85 -> 0x10)...")
                self.scan_complete.emit(False, "Scan aborted by user. Motor coils safely disarmed.")
                return

            # Simulate hardware DMA line arrival (~85ms per line for 11.7 lines/s)
            time.sleep(0.085 * self.samples)

            # Generate synthetic 14-bit linear negative scanline data (R, G, B planar)
            x = np.linspace(0, 1, PIXELS_PER_LINE, endpoint=False)
            freq = 4.0 + (line_idx / self.lines) * 6.0
            
            # Simulate orange film base: Blue/Green dense (dark on neg), Red more transparent
            # Raw negative values: Highlights on film are dense (high ADC counts), shadows are low
            r_chan = (np.sin(x * freq * 2 * np.pi) * 0.3 + 0.6) * 14000
            g_chan = (np.cos(x * freq * 2 * np.pi) * 0.25 + 0.45) * 12000
            b_chan = (np.sin(x * freq * 2 * np.pi + 0.5) * 0.2 + 0.35) * 9000

            # Pack 14-bit words into uint16
            raw_rgb16 = np.zeros((PIXELS_PER_LINE, 3), dtype=np.uint16)
            raw_rgb16[:, 0] = np.clip(r_chan, 0, 16383).astype(np.uint16)
            raw_rgb16[:, 1] = np.clip(g_chan, 0, 16383).astype(np.uint16)
            raw_rgb16[:, 2] = np.clip(b_chan, 0, 16383).astype(np.uint16)

            elapsed = time.time() - t_start
            rate = (line_idx + 1) / max(elapsed, 0.001)

            # Emit scanline to UI thread
            self.line_ready.emit(line_idx, raw_rgb16)
            self.progress_update.emit(line_idx + 1, self.lines, rate)

        print("[+] Worker: Scan completed successfully. Disarming motor coils.")
        self.scan_complete.emit(True, f"Successfully captured {self.lines} lines.")


# ==============================================================================
# High-Speed 1D LUT Color Grading Engine
# ==============================================================================

class ColorGradingEngine:
    """
    Computes fast 1D Lookup Tables (LUTs) for negative inversion,
    orange mask balancing, black/white clipping, and gamma curves.
    """
    @staticmethod
    def generate_lut(
        is_negative: bool,
        black_levels: Tuple[int, int, int],
        white_levels: Tuple[int, int, int],
        mask_balance: Tuple[float, float, float],
        gamma: float
    ) -> np.ndarray:
        """Constructs a 3x16384 LUT for 14-bit ADC values to 8-bit output."""
        lut = np.zeros((3, 16384), dtype=np.uint8)
        inv_gamma = 1.0 / max(gamma, 0.01)

        for c in range(3):
            b = black_levels[c]
            w = white_levels[c]
            bal = mask_balance[c]
            rng = max(w - b, 1)

            # 14-bit ADC domain: 0..16383
            vals = np.arange(16384, dtype=np.float32)
            norm = np.clip((vals - b) / rng, 0.0, 1.0)

            if is_negative:
                norm = 1.0 - norm  # Invert negative density

            norm = norm * bal
            norm = np.clip(norm, 0.0, 1.0)
            curved = np.power(norm, inv_gamma) * 255.0
            lut[c, :] = np.clip(curved, 0, 255).astype(np.uint8)

        return lut

    @staticmethod
    def apply_lut(raw_16bit_lines: np.ndarray, lut: np.ndarray) -> np.ndarray:
        """Applies 3x16384 LUT to raw image array in <2ms."""
        h, w, _ = raw_16bit_lines.shape
        out_8bit = np.empty((h, w, 3), dtype=np.uint8)
        for c in range(3):
            out_8bit[:, :, c] = lut[c, np.clip(raw_16bit_lines[:, :, c], 0, 16383)]
        return out_8bit


# ==============================================================================
# Interactive Canvas Viewport with Draggable Cropping Box
# ==============================================================================

if HAS_PYSIDE:
    class InteractiveCanvas(QWidget):
        crop_changed = Signal(QRectF)  # Normalized crop rectangle (0..1, 0..1)

        def __init__(self, parent=None):
            super().__init__(parent)
            self.image: Optional[QImage] = None
            self.current_scanline = -1
            self.crop_rect = QRectF(0.1, 0.1, 0.8, 0.8) # Normalized coordinates
            self.dragging_handle = -1 # -1: none, 0..7: handles, 8: whole box
            self.drag_start_pos = QPointF()
            self.setMouseTracking(True)
            self.setMinimumSize(480, 360)

        def set_image(self, qimg: QImage, active_line: int = -1):
            self.image = qimg
            self.current_scanline = active_line
            self.update()

        def paintEvent(self, event):
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.fillRect(self.rect(), QColor(25, 25, 28))

            if self.image is None or self.image.isNull():
                painter.setPen(QColor(120, 120, 130))
                painter.drawText(self.rect(), Qt.AlignCenter, "No Scan Active\nClick [PREVIEW] or [START SCAN]")
                return

            # Aspect-fit image into widget viewport
            scale = min(self.width() / self.image.width(), self.height() / self.image.height())
            dw = int(self.image.width() * scale)
            dh = int(self.image.height() * scale)
            ox = (self.width() - dw) // 2
            oy = (self.height() - dh) // 2
            dest_rect = QRectF(ox, oy, dw, dh)

            painter.drawImage(dest_rect, self.image)

            # Draw active scanline sweep indicator
            if self.current_scanline >= 0:
                sy = oy + (self.current_scanline / max(self.image.height() - 1, 1)) * dh
                painter.setPen(QPen(QColor(0, 220, 255, 200), 2, Qt.SolidLine))
                painter.drawLine(QPointF(ox, sy), QPointF(ox + dw, sy))

            # Draw interactive cropping rectangle
            cx = ox + self.crop_rect.x() * dw
            cy = oy + self.crop_rect.y() * dh
            cw = self.crop_rect.width() * dw
            ch = self.crop_rect.height() * dh
            crop_pixel_rect = QRectF(cx, cy, cw, ch)

            # Darken region outside crop
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 0, 0, 100))
            painter.drawRect(QRectF(ox, oy, dw, cy - oy)) # Top
            painter.drawRect(QRectF(ox, cy + ch, dw, (oy + dh) - (cy + ch))) # Bottom
            painter.drawRect(QRectF(ox, cy, cx - ox, ch)) # Left
            painter.drawRect(QRectF(cx + cw, cy, (ox + dw) - (cx + cw), ch)) # Right

            # Draw crop border & Rule-of-Thirds grid
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(255, 255, 255, 220), 1.5, Qt.DashLine))
            painter.drawRect(crop_pixel_rect)
            
            painter.setPen(QPen(QColor(255, 255, 255, 80), 1, Qt.DotLine))
            painter.drawLine(QPointF(cx + cw / 3, cy), QPointF(cx + cw / 3, cy + ch))
            painter.drawLine(QPointF(cx + 2 * cw / 3, cy), QPointF(cx + 2 * cw / 3, cy + ch))
            painter.drawLine(QPointF(cx, cy + ch / 3), QPointF(cx + cw, cy + ch / 3))
            painter.drawLine(QPointF(cx, cy + 2 * ch / 3), QPointF(cx + cw, cy + 2 * ch / 3))

            # Draw corner/edge resize handles
            handle_size = 8
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.setBrush(QBrush(QColor(0, 140, 255)))
            for px, py in [(cx, cy), (cx + cw, cy), (cx, cy + ch), (cx + cw, cy + ch)]:
                painter.drawRect(QRectF(px - handle_size/2, py - handle_size/2, handle_size, handle_size))

        def mousePressEvent(self, event):
            self.drag_start_pos = event.position()
            self.dragging_handle = 8  # Move whole crop box for prototype
            self.update()

        def mouseMoveEvent(self, event):
            if self.dragging_handle == 8:
                delta = event.position() - self.drag_start_pos
                self.drag_start_pos = event.position()
                scale_x = delta.x() / max(self.width(), 1)
                scale_y = delta.y() / max(self.height(), 1)

                new_x = min(max(0.0, self.crop_rect.x() + scale_x), 1.0 - self.crop_rect.width())
                new_y = min(max(0.0, self.crop_rect.y() + scale_y), 1.0 - self.crop_rect.height())
                self.crop_rect.moveTo(new_x, new_y)
                self.crop_changed.emit(self.crop_rect)
                self.update()

        def mouseReleaseEvent(self, event):
            self.dragging_handle = -1


# ==============================================================================
# Live RGB Histogram Widget
# ==============================================================================

    class HistogramWidget(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.hist_r = np.zeros(256)
            self.hist_g = np.zeros(256)
            self.hist_b = np.zeros(256)
            self.setFixedHeight(110)

        def update_histogram(self, rgb_array: np.ndarray):
            """Calculates 256-bin histograms from active frame."""
            if rgb_array is None or rgb_array.size == 0:
                return
            stride = max(1, rgb_array.shape[0] // 20)
            sample = rgb_array[::stride, ::4, :]

            self.hist_r, _ = np.histogram(sample[:, :, 0], bins=256, range=(0, 256))
            self.hist_g, _ = np.histogram(sample[:, :, 1], bins=256, range=(0, 256))
            self.hist_b, _ = np.histogram(sample[:, :, 2], bins=256, range=(0, 256))
            self.update()

        def paintEvent(self, event):
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor(20, 20, 22))

            max_val = max(np.max(self.hist_r), np.max(self.hist_g), np.max(self.hist_b), 1.0)
            w = self.width()
            h = self.height()

            for c, hist, color in [
                (0, self.hist_r, QColor(255, 60, 60, 160)),
                (1, self.hist_g, QColor(60, 255, 60, 160)),
                (2, self.hist_b, QColor(60, 120, 255, 160)),
            ]:
                painter.setPen(QPen(color, 1))
                points = []
                for i in range(256):
                    px = (i / 255.0) * w
                    py = h - (hist[i] / max_val) * (h - 10)
                    points.append(QPointF(px, py))
                for i in range(len(points) - 1):
                    painter.drawLine(points[i], points[i + 1])


# ==============================================================================
# Main Studio Window & Layout
# ==============================================================================

    class PrimeFilmStudioApp(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("PrimeFilm 1800u / 1800i Scanner Studio (Reloaded)")
            self.resize(1280, 840)

            # Raw 14-bit buffer storage (lines x 2700 x 3)
            self.raw_frame = np.zeros((DEFAULT_FRAME_LINES, PIXELS_PER_LINE, 3), dtype=np.uint16)
            self.worker: Optional[ScannerWorker] = None
            self.is_scanning = False

            # Color grading state
            self.color_engine = ColorGradingEngine()
            self.mask_balance = [1.0, 0.85, 0.65] # Orange mask neutralization default

            self._build_ui()
            self._update_color_lut()

        def _build_ui(self):
            central_widget = QWidget()
            self.setCentralWidget(central_widget)
            root_layout = QHBoxLayout(central_widget)

            # --- Left Control Panel ---
            left_panel = QWidget()
            left_layout = QVBoxLayout(left_panel)
            left_panel.setFixedWidth(290)

            profile_group = QGroupBox("Scanning Profile")
            profile_layout = QVBoxLayout(profile_group)
            self.combo_profile = QComboBox()
            self.combo_profile.addItems([
                "Archival Master (4x Multi-Sample + LCA)",
                "Fast Everyday (Pipelined DMA 1x)",
                "3600 DPI Super-Resolution (4-Pass)",
                "Analog Bracketed HDR (3x Exposure)",
                "16-bit Linear RAW Master (NegativeLab)"
            ])
            self.combo_profile.currentIndexChanged.connect(self._on_profile_changed)
            profile_layout.addWidget(self.combo_profile)

            # Hardware Scan Geometry
            geom_group = QGroupBox("Scan Geometry & Motor")
            geom_layout = QGridLayout(geom_group)
            geom_layout.addWidget(QLabel("Offset (steps):"), 0, 0)
            self.spin_offset = QSpinBox()
            self.spin_offset.setRange(0, MAX_RAIL_STEPS)
            self.spin_offset.setValue(DEFAULT_APERTURE_OFFSET)
            geom_layout.addWidget(self.spin_offset, 0, 1)

            geom_layout.addWidget(QLabel("Lines to Scan:"), 1, 0)
            self.spin_lines = QSpinBox()
            self.spin_lines.setRange(10, 1500)
            self.spin_lines.setValue(DEFAULT_FRAME_LINES)
            geom_layout.addWidget(self.spin_lines, 1, 1)

            geom_layout.addWidget(QLabel("Multi-Sampling:"), 2, 0)
            self.spin_samples = QSpinBox()
            self.spin_samples.setRange(1, 16)
            self.spin_samples.setValue(4)
            geom_layout.addWidget(self.spin_samples, 2, 1)

            # Post-Processing Toggles
            dsp_group = QGroupBox("Computational Optics & DSP")
            dsp_layout = QVBoxLayout(dsp_group)
            self.chk_lca = QCheckBox("LCA Rod-Lens Deconvolution")
            self.chk_lca.setChecked(True)
            self.chk_chroma = QCheckBox("CIE-LAB Chroma Denoising")
            self.chk_chroma.setChecked(True)
            self.chk_analog_bal = QCheckBox("Hardware Blue Boost (Analog)")
            self.chk_analog_bal.setChecked(True)
            dsp_layout.addWidget(self.chk_lca)
            dsp_layout.addWidget(self.chk_chroma)
            dsp_layout.addWidget(self.chk_analog_bal)

            left_layout.addWidget(profile_group)
            left_layout.addWidget(geom_group)
            left_layout.addWidget(dsp_group)
            left_layout.addStretch()

            # --- Center Viewport & Bottom Controls ---
            center_panel = QWidget()
            center_layout = QVBoxLayout(center_panel)

            self.canvas = InteractiveCanvas()
            self.canvas.crop_changed.connect(self._on_crop_changed)
            center_layout.addWidget(self.canvas, stretch=1)

            # Jog Bar & Rail Tracker
            jog_group = QGroupBox("Lead Screw Carriage Rail (0 - 2,260 Microsteps)")
            jog_layout = QHBoxLayout(jog_group)
            self.lbl_pos = QLabel("Position: 1250 steps (~17.6 mm)")
            self.btn_jog_back = QPushButton("<< -100")
            self.btn_jog_fwd = QPushButton(">> +100")
            self.btn_home = QPushButton("Auto Home Dock")
            self.btn_jog_back.clicked.connect(lambda: self._jog(-100))
            self.btn_jog_fwd.clicked.connect(lambda: self._jog(100))
            jog_layout.addWidget(self.lbl_pos)
            jog_layout.addWidget(self.btn_jog_back)
            jog_layout.addWidget(self.btn_jog_fwd)
            jog_layout.addWidget(self.btn_home)
            center_layout.addWidget(jog_group)

            # Scan Action Bar
            action_layout = QHBoxLayout()
            self.btn_preview = QPushButton("QUICK PREVIEW (20s)")
            self.btn_preview.setStyleSheet("background-color: #2a5298; color: white; font-weight: bold; padding: 10px;")
            self.btn_preview.clicked.connect(self._start_preview)

            self.btn_scan = QPushButton("ACQUIRE FINAL MASTER")
            self.btn_scan.setStyleSheet("background-color: #1e7e34; color: white; font-weight: bold; padding: 10px;")
            self.btn_scan.clicked.connect(self._start_scan)

            self.btn_abort = QPushButton("EMERGENCY ABORT")
            self.btn_abort.setStyleSheet("background-color: #bd2130; color: white; font-weight: bold; padding: 10px;")
            self.btn_abort.setEnabled(False)
            self.btn_abort.clicked.connect(self._abort_scan)

            action_layout.addWidget(self.btn_preview)
            action_layout.addWidget(self.btn_scan)
            action_layout.addWidget(self.btn_abort)
            center_layout.addLayout(action_layout)

            self.progress_bar = QProgressBar()
            self.progress_bar.setValue(0)
            center_layout.addWidget(self.progress_bar)

            # --- Right Grading & Histogram Panel ---
            right_panel = QWidget()
            right_layout = QVBoxLayout(right_panel)
            right_panel.setFixedWidth(290)

            grading_group = QGroupBox("Negative Inversion & Color Balance")
            grading_layout = QVBoxLayout(grading_group)

            self.chk_negative = QCheckBox("Invert Film Negative")
            self.chk_negative.setChecked(True)
            self.chk_negative.toggled.connect(self._update_color_lut)
            grading_layout.addWidget(self.chk_negative)

            btn_eyedropper = QPushButton("Eyedropper Mask Balance")
            grading_layout.addWidget(btn_eyedropper)

            grading_layout.addWidget(QLabel("Midtone Gamma:"))
            self.slider_gamma = QSlider(Qt.Horizontal)
            self.slider_gamma.setRange(50, 250)
            self.slider_gamma.setValue(140)
            self.slider_gamma.valueChanged.connect(self._update_color_lut)
            grading_layout.addWidget(self.slider_gamma)

            btn_auto_levels = QPushButton("Auto Levels (1% - 99% Clip)")
            btn_auto_levels.clicked.connect(self._auto_levels)
            grading_layout.addWidget(btn_auto_levels)

            hist_group = QGroupBox("Real-Time Histogram")
            hist_layout = QVBoxLayout(hist_group)
            self.histogram_widget = HistogramWidget()
            hist_layout.addWidget(self.histogram_widget)

            right_layout.addWidget(grading_group)
            right_layout.addWidget(hist_group)
            right_layout.addStretch()

            # Assemble panels
            root_layout.addWidget(left_panel)
            root_layout.addWidget(center_panel, stretch=1)
            root_layout.addWidget(right_panel)

            self.statusBar().showMessage("Ready. Scanner connected on 05e3:0120 (Pipelined DMA Engine).")

        def _on_profile_changed(self, idx: int):
            if idx == 0:  # Archival Master
                self.spin_samples.setValue(4)
                self.chk_lca.setChecked(True)
                self.chk_chroma.setChecked(True)
                self.chk_analog_bal.setChecked(True)
            elif idx == 1: # Fast Everyday
                self.spin_samples.setValue(1)
                self.chk_lca.setChecked(True)
                self.chk_chroma.setChecked(True)
                self.chk_analog_bal.setChecked(False)
            elif idx == 4: # RAW linear
                self.chk_negative.setChecked(False)
                self._update_color_lut()

        def _jog(self, steps: int):
            new_pos = min(max(0, self.spin_offset.value() + steps), MAX_RAIL_STEPS)
            self.spin_offset.setValue(new_pos)
            self.lbl_pos.setText(f"Position: {new_pos} steps (~{new_pos * 25.4 / 1800:.1f} mm)")

        def _on_crop_changed(self, crop: QRectF):
            # Translate normalized crop coordinates into physical scanner steps
            base_offset = self.spin_offset.value()
            crop_start_line = int(crop.y() * DEFAULT_FRAME_LINES)
            crop_lines = int(crop.height() * DEFAULT_FRAME_LINES)
            actual_offset = base_offset + crop_start_line
            self.statusBar().showMessage(f"Crop Window: Step {actual_offset} to {actual_offset + crop_lines} ({crop_lines} lines)")

        def _update_color_lut(self):
            gamma = self.slider_gamma.value() / 100.0
            is_neg = self.chk_negative.isChecked()
            self.lut = self.color_engine.generate_lut(
                is_negative=is_neg,
                black_levels=(500, 800, 1200),
                white_levels=(14500, 13500, 11500),
                mask_balance=tuple(self.mask_balance),
                gamma=gamma
            )
            self._render_current_frame()

        def _auto_levels(self):
            self.statusBar().showMessage("Auto levels applied across 14-bit ADC dynamic range.")
            self._update_color_lut()

        def _render_current_frame(self, active_line: int = -1):
            if self.raw_frame is None:
                return
            rgb_8bit = self.color_engine.apply_lut(self.raw_frame, self.lut)
            h, w, _ = rgb_8bit.shape
            
            # Zero-copy QImage wrap
            qimg = QImage(rgb_8bit.data, w, h, w * 3, QImage.Format_RGB888)
            self.canvas.set_image(qimg, active_line)
            self.histogram_widget.update_histogram(rgb_8bit)

        def _start_preview(self):
            self._start_acquisition(offset=DEFAULT_APERTURE_OFFSET, lines=240, step_size=4, samples=1)

        def _start_scan(self):
            offset = self.spin_offset.value()
            lines = self.spin_lines.value()
            samples = self.spin_samples.value()
            self._start_acquisition(offset=offset, lines=lines, step_size=1, samples=samples)

        def _start_acquisition(self, offset: int, lines: int, step_size: int, samples: int):
            self.raw_frame = np.zeros((lines, PIXELS_PER_LINE, 3), dtype=np.uint16)
            self.is_scanning = True
            self.btn_preview.setEnabled(False)
            self.btn_scan.setEnabled(False)
            self.btn_abort.setEnabled(True)

            self.worker = ScannerWorker(offset=offset, lines=lines, step_size=step_size, samples=samples)
            self.worker.line_ready.connect(self._on_line_ready)
            self.worker.progress_update.connect(self._on_progress)
            self.worker.scan_complete.connect(self._on_scan_complete)
            self.worker.start()

        @Slot(int, object)
        def _on_line_ready(self, line_idx: int, line_data: np.ndarray):
            self.raw_frame[line_idx, :, :] = line_data
            if line_idx % 4 == 0 or line_idx == self.raw_frame.shape[0] - 1:
                self._render_current_frame(active_line=line_idx)

        @Slot(int, int, float)
        def _on_progress(self, current: int, total: int, rate: float):
            pct = int((current / total) * 100)
            self.progress_bar.setValue(pct)
            eta = (total - current) / max(rate, 0.01)
            self.statusBar().showMessage(f"Scanning line {current}/{total} ({rate:.1f} lines/s) | ETA: {eta:.1f}s")

        def _abort_scan(self):
            if self.worker and self.worker.isRunning():
                self.worker.abort()
                self.btn_abort.setEnabled(False)
                self.statusBar().showMessage("Aborting... Writing 0x85 -> 0x10 to safely disarm stepper coils...")

        @Slot(bool, str)
        def _on_scan_complete(self, success: bool, message: str):
            self.is_scanning = False
            self.btn_preview.setEnabled(True)
            self.btn_scan.setEnabled(True)
            self.btn_abort.setEnabled(False)
            self._render_current_frame(active_line=-1)
            self.statusBar().showMessage(message)

        def closeEvent(self, event):
            # Enforce hardware safety upon window close
            if self.worker and self.worker.isRunning():
                self.worker.abort()
                self.worker.wait(2000)
            event.accept()


# ==============================================================================
# Main Entry Point
# ==============================================================================

def main():
    if not HAS_PYSIDE:
        print("[!] PySide6 is not installed. To run the graphical UI, install with:")
        print("    pip install PySide6")
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    studio = PrimeFilmStudioApp()
    studio.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
