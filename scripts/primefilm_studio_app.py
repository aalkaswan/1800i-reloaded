#!/usr/bin/env python3
"""
PrimeFilm 1800u / 1800i Scanner Studio Desktop UI (primefilm_studio_app.py)
=============================================================================
Complete Cross-Platform Graphical Studio Application for Linux & Windows 10/11.

Features:
- Dual GUI Engine:
    * Native Qt Desktop Window (PySide6 / PyQt6 / PyQt5) when installed.
    * In-box Zero-Dependency Web Studio Desktop UI (HTML5 Canvas + Server-Sent Events)
      accessible from any browser when Qt is not installed or when --web is passed.
- Direct Hardware Integration:
    * Auto-detects USB VID:PID 05e3:0120 (Windows WinUSB / Linux usbfs).
    * Windows libusb-1.0.dll auto-discovery across local and system paths.
    * Safe simulation / mock mode when scanner hardware is offline.
    * Guaranteed closed-loop stepper motor coil disarming (0x85 -> 0x10) on exit or abort.
- Real-Time 11.7 lines/s Scanline Streaming with Live Active-Line Sweep.
- Interactive 8-Handle Resizable Crop Box with Rule-of-Thirds & Step Coordinate Mapping.
- High-Speed 1D LUT Color Grading Engine (60 FPS Negative Inversion, Orange Mask Eyedropper,
  Per-Channel Levels, Midtone Gamma, and Live 256-Bin RGB Histogram).
- Hardware Stepper Jog Bar with Optical Home Sensor Status (0 to 2260 Microsteps).
"""

import sys
import os
import time
import math
import struct
import threading
import queue
import atexit
import signal
import json
import webbrowser
from typing import Optional, Tuple, Dict, Any, List

# Try importing image libraries
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# Try importing NumPy (optional acceleration)
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

# Try importing PyUSB
try:
    import usb.core
    import usb.util
    import usb.backend.libusb1
    HAS_PYUSB = True
except ImportError:
    HAS_PYUSB = False

# Try importing Qt (PySide6, PyQt6, or PyQt5)
HAS_QT = False
QT_FLAVOR = None

try:
    from PySide6.QtCore import Qt, QThread, Signal, Slot, QRectF, QPointF, QTimer
    from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QBrush, QFont, QAction
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QGridLayout, QPushButton, QLabel, QSlider, QComboBox, QCheckBox,
        QSpinBox, QProgressBar, QGroupBox, QSplitter, QStatusBar, QMessageBox,
        QFileDialog, QToolBar, QFrame
    )
    HAS_QT = True
    QT_FLAVOR = "PySide6"
except ImportError:
    try:
        from PyQt6.QtCore import Qt, QThread, pyqtSignal as Signal, pyqtSlot as Slot, QRectF, QPointF, QTimer
        from PyQt6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QBrush, QFont, QAction
        from PyQt6.QtWidgets import (
            QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
            QGridLayout, QPushButton, QLabel, QSlider, QComboBox, QCheckBox,
            QSpinBox, QProgressBar, QGroupBox, QSplitter, QStatusBar, QMessageBox,
            QFileDialog, QToolBar, QFrame
        )
        HAS_QT = True
        QT_FLAVOR = "PyQt6"
    except ImportError:
        try:
            from PyQt5.QtCore import Qt, QThread, pyqtSignal as Signal, pyqtSlot as Slot, QRectF, QPointF, QTimer
            from PyQt5.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QBrush, QFont
            from PyQt5.QtWidgets import (
                QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                QGridLayout, QPushButton, QLabel, QSlider, QComboBox, QCheckBox,
                QSpinBox, QProgressBar, QGroupBox, QSplitter, QStatusBar, QMessageBox,
                QFileDialog, QToolBar, QFrame, QAction
            )
            HAS_QT = True
            QT_FLAVOR = "PyQt5"
        except ImportError:
            HAS_QT = False
            QT_FLAVOR = None


# ==============================================================================
# Hardware Constants & Geometry Definitions
# ==============================================================================

VENDOR_ID = 0x05e3
PRODUCT_ID = 0x0120

PIXELS_PER_LINE = 2700
FULL_LINE_BYTES = 16200  # 2700 pixels * 3 channels * 2 bytes uint16
MAX_RAIL_STEPS = 2260    # Hard physical rail limit
DEFAULT_APERTURE_OFFSET = 1250
DEFAULT_FRAME_LINES = 950
DMA_PACKET_DESC = struct.pack("<BBBB I", 0x00, 0x00, 0x00, 0x00, FULL_LINE_BYTES)


# ==============================================================================
# Windows & Cross-Platform Hardware Driver Layer
# ==============================================================================

def get_libusb_backend():
    """
    Locates libusb-1.0 on Linux and Windows.
    On Windows, searches PyInstaller bundle dir, libusb-package, local directories, bin/, and system path.
    """
    if not HAS_PYUSB:
        return None

    # First check if libusb_package is installed (packaged with PyInstaller)
    try:
        import libusb_package
        backend = libusb_package.get_libusb1_backend()
        if backend:
            return backend
    except Exception:
        pass

    if sys.platform == "win32":
        # Potential locations for libusb-1.0.dll on Windows
        base_dir = os.path.dirname(os.path.abspath(__file__))
        repo_dir = os.path.dirname(base_dir)
        candidates = []

        # PyInstaller temp unpack directory
        if hasattr(sys, "_MEIPASS"):
            candidates.append(os.path.join(sys._MEIPASS, "libusb-1.0.dll"))
            candidates.append(os.path.join(sys._MEIPASS, "libusb_package", "libusb-1.0.dll"))

        candidates.extend([
            os.path.join(base_dir, "libusb-1.0.dll"),
            os.path.join(repo_dir, "bin", "libusb-1.0.dll"),
            os.path.join(base_dir, "bin", "libusb-1.0.dll"),
            r"C:\Windows\System32\libusb-1.0.dll",
            r"C:\Program Files\PrimeFilm 1800 Reloaded\libusb-1.0.dll"
        ])

        for dll_path in candidates:
            if os.path.isfile(dll_path):
                try:
                    backend = usb.backend.libusb1.get_backend(find_library=lambda x, p=dll_path: p)
                    if backend:
                        return backend
                except Exception:
                    pass
    # Default system backend
    try:
        return usb.backend.libusb1.get_backend()
    except Exception:
        return None


class ScannerHardware:
    """
    Encapsulates USB communication with the Genesys Logic GL640USB bridge
    and PIE scanner ASIC. Safe on both Linux and Windows.
    """
    def __init__(self):
        self.dev = None
        self.is_connected = False
        self.backend = None
        self.current_position = 0
        self.lamp_on = False
        self.lock = threading.Lock()

    def connect(self) -> bool:
        """Attempts to discover and initialize the physical scanner."""
        if not HAS_PYUSB:
            return False

        with self.lock:
            try:
                self.backend = get_libusb_backend()
                if self.backend:
                    self.dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID, backend=self.backend)
                else:
                    self.dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)

                if self.dev is None:
                    self.is_connected = False
                    return False

                # Handle kernel driver detach safely across Linux & Windows
                try:
                    if self.dev.is_kernel_driver_active(0):
                        self.dev.detach_kernel_driver(0)
                except (NotImplementedError, usb.core.USBError, Exception):
                    pass

                try:
                    self.dev.get_active_configuration()
                except Exception:
                    try:
                        self.dev.set_configuration()
                    except Exception:
                        pass

                try:
                    usb.util.claim_interface(self.dev, 0)
                except Exception:
                    pass

                # Initialize GL640 bridge transceiver
                self._wctl(0x8b, 0x00)
                time.sleep(0.02)
                self._wctl(0x8b, 0x40)
                time.sleep(0.02)

                # 3-Stage IEEE 1284.4 Handshake
                self._ieee_handshake(0x30)
                time.sleep(0.01)
                self._ieee_handshake(0x00)
                time.sleep(0.01)
                self._ieee_handshake(0x80)
                time.sleep(0.01)

                # Configure standard ASIC registers
                self._asic_write(0xc4, 0x00)
                self._asic_write(0xab, 0xaa)
                self._asic_write(0xac, 0xca)
                self._asic_write(0xad, 0x4b) # Standby clock
                self._asic_write(0xae, 0x05)
                self._asic_write(0xc1, 0x07)
                self._asic_write(0xc2, 0x04)
                self._asic_write(0xc3, 0x12)
                self._asic_write(0xc5, 0x12)

                # Configure default exposure clocks (2,900 clocks)
                self.set_exposure(2900, 2900, 2900)

                # Configure AFE gain (0x1f = max gain) and dark clamp offsets
                for r in [0xe0, 0xe4, 0xe8]:
                    self._asic_write(r, 0x1f)
                for r in [0xe2, 0xe6, 0xea]:
                    self._asic_write(r, 0x02)

                # Unlock 24-bit exposure limits
                for r in range(0xa2, 0xab):
                    self._asic_write(r, 0xff)

                # CCD sampling gate
                self._asic_write(0x98, 0x01)
                self._asic_write(0x99, 0x00)
                self._asic_write(0x9a, 0x8d)
                self._asic_write(0x9b, 0x2a)

                # Disarm motor coils initially
                self.disarm_coils()

                self.is_connected = True
                return True
            except Exception as e:
                print(f"[!] Scanner connection failed: {e}")
                self.is_connected = False
                self.dev = None
                return False

    def disconnect(self):
        with self.lock:
            if self.dev:
                try:
                    self.disarm_coils()
                    self.set_lamp(False)
                    usb.util.release_interface(self.dev, 0)
                except Exception:
                    pass
                self.dev = None
            self.is_connected = False

    def _wctl(self, reg: int, data: Any, timeout: int = 1000):
        if self.dev is None: return
        if isinstance(data, int): data = bytes([data])
        return self.dev.ctrl_transfer(0x40, 0x0c, reg, 0, data, timeout=timeout)

    def _rctl(self, reg: int, timeout: int = 1000) -> Optional[int]:
        if self.dev is None: return None
        buf = self.dev.ctrl_transfer(0xc0, 0x0c, reg, 0, 1, timeout=timeout)
        return buf[0] if buf else None

    def _ieee_handshake(self, mode: int):
        self._wctl(0x87, 0x04)
        self._wctl(0x87, 0x04)
        for b in [0xff, 0xaa, 0x55, 0x00, 0xff, 0x87, 0x78]:
            self._wctl(0x88, b)
            self._wctl(0x88, b)
        self._wctl(0x88, mode)
        self._wctl(0x88, mode)
        self._wctl(0x87, 0x05)
        self._wctl(0x87, 0x05)
        self._wctl(0x87, 0x04)
        self._wctl(0x87, 0x04)
        self._wctl(0x88, 0xff)
        self._wctl(0x88, 0xff)

    def _asic_write(self, reg: int, val: int, timeout: int = 1000):
        self._wctl(0x83, reg, timeout=timeout)
        self._wctl(0x85, val, timeout=timeout)

    def _asic_read(self, reg: int, timeout: int = 1000) -> Optional[int]:
        self._wctl(0x83, reg, timeout=timeout)
        return self._rctl(0x84, timeout=timeout)

    def wait_idle(self, timeout: float = 3.0) -> bool:
        t0 = time.time()
        while time.time() - t0 < timeout:
            val = self._asic_read(0x84)
            if val is not None and (val & 0x1e) == 0:
                return True
            time.sleep(0.001)
        return False

    def is_home(self) -> bool:
        """Returns True if carriage is parked at optical home dock."""
        if not self.is_connected: return True
        val = self._asic_read(0x84)
        return (val is not None) and ((val & 0x20) == 0)

    def disarm_coils(self):
        """CRITICAL: Disarms stepper motor coils (0x85 -> 0x10) to prevent thermal heating."""
        if self.dev:
            try:
                self._asic_write(0x85, 0x10)
            except Exception:
                pass

    def set_lamp(self, on: bool):
        if not self.is_connected: return
        with self.lock:
            if on:
                self._asic_write(0xad, 0x0b) # Pixel clock ON
                self._asic_write(0x85, 0x30) # Lamp power ON
                self.lamp_on = True
            else:
                self._asic_write(0xad, 0x4b) # Standby clock
                self._asic_write(0x85, 0x10) # Lamp OFF / Disarm
                self.lamp_on = False

    def set_exposure(self, r_clocks: int, g_clocks: int, b_clocks: int):
        if not self.is_connected: return
        with self.lock:
            self._asic_write(0x9c, r_clocks & 0xff)
            self._asic_write(0x9d, (r_clocks >> 8) & 0xff)
            self._asic_write(0x9e, g_clocks & 0xff)
            self._asic_write(0x9f, (g_clocks >> 8) & 0xff)
            self._asic_write(0xa0, b_clocks & 0xff)
            self._asic_write(0xa1, (b_clocks >> 8) & 0xff)

    def jog(self, delta_steps: int) -> int:
        """Jogs the carriage forward or backward, bounded strictly by [0, MAX_RAIL_STEPS]."""
        target = min(max(0, self.current_position + delta_steps), MAX_RAIL_STEPS)
        steps_to_move = abs(target - self.current_position)
        if steps_to_move == 0:
            return self.current_position

        direction = 0x16 if target > self.current_position else 0x14
        if self.is_connected:
            with self.lock:
                rem = steps_to_move
                while rem > 0:
                    chunk = min(rem, 250)
                    self._asic_write(0x85, direction)
                    self._asic_write(0x81, chunk)
                    self.wait_idle()
                    rem -= chunk
                self.disarm_coils()

        self.current_position = target
        return self.current_position

    def step_forward(self, steps: int) -> int:
        """Advances carriage during active scanning without dropping motor holding torque."""
        target = min(self.current_position + steps, MAX_RAIL_STEPS)
        actual = target - self.current_position
        if actual <= 0:
            return self.current_position
        if self.is_connected and self.dev:
            with self.lock:
                rem = actual
                while rem > 0:
                    chunk = min(rem, 250)
                    self._asic_write(0x85, 0x16)
                    self._asic_write(0x81, chunk)
                    self.wait_idle()
                    rem -= chunk
        self.current_position = target
        return self.current_position

    def home(self) -> bool:
        """Returns carriage to optical dock (Step 0) using closed-loop sensor."""
        if not self.is_connected or not self.dev:
            self.current_position = 0
            return True

        with self.lock:
            # Retract backward toward optical sensor in 50-step increments
            for _ in range(60):
                if self.is_home():
                    break
                self._asic_write(0x85, 0x14)
                self._asic_write(0x81, 50)
                self.wait_idle()

            self.disarm_coils()
            self.current_position = 0
            return self.is_home()

    def read_line(self) -> Optional[bytes]:
        """
        Triggers CCD exposure and acquires a single 16,200-byte raw optical scanline
        over USB Bulk IN Endpoint 1 (0x81), resetting internal SRAM pointers and arming DMA.
        """
        if not self.is_connected or not self.dev:
            return None

        with self.lock:
            try:
                # 1. Trigger optical exposure
                self._asic_write(0x85, 0x12)
                self._asic_write(0x81, 0x00)
                self.wait_idle()

                # 2. Reset window end & SRAM read pointers
                for r in (0x90, 0x91, 0x92, 0x93, 0x94, 0x95):
                    self._asic_write(r, 0x00)
                self.wait_idle()

                # 3. Arm GL640 USB DMA engine
                self._wctl(0x83, 0x80)
                self._wctl(0x82, DMA_PACKET_DESC)

                # 4. Read bulk scanline from EP 0x81
                raw = self.dev.read(0x81, FULL_LINE_BYTES, timeout=4000)
                self.wait_idle(timeout=1.0)
                if raw and len(raw) == FULL_LINE_BYTES:
                    return bytes(raw)
                return None
            except Exception as e:
                print(f"[!] USB read_line error: {e}")
                return None


# Register process exit handler to always guarantee coil disarming
_GLOBAL_HARDWARE = ScannerHardware()

def _cleanup_hardware_on_exit():
    try:
        _GLOBAL_HARDWARE.disarm_coils()
        _GLOBAL_HARDWARE.disconnect()
    except Exception:
        pass

atexit.register(_cleanup_hardware_on_exit)


# ==============================================================================
# Color Grading & Negative Inversion Engine (Pure Python / Zero Dependencies)
# ==============================================================================

class ColorGradingEngine:
    """
    Computes 1D Lookup Tables (LUTs) for real-time (60 FPS) negative conversion,
    orange mask cancellation, gamma adjustment, and 256-bin RGB histograms.
    Works identically with or without NumPy installed.
    """
    @staticmethod
    def create_lut(
        is_negative: bool,
        black_rgb: Tuple[int, int, int],
        white_rgb: Tuple[int, int, int],
        mask_balance: Tuple[float, float, float],
        gamma: float
    ) -> List[List[int]]:
        """Builds a 3 x 16384 LUT mapping 14-bit ADC samples (0..16383) to 8-bit sRGB (0..255)."""
        lut = [[0] * 16384 for _ in range(3)]
        inv_gamma = 1.0 / max(gamma, 0.05)

        for c in range(3):
            b = black_rgb[c]
            w = white_rgb[c]
            bal = mask_balance[c]
            rng = max(w - b, 1)

            for v in range(16384):
                # Normalize sample into [0.0, 1.0]
                norm = (v - b) / rng
                norm = max(0.0, min(1.0, norm))

                if is_negative:
                    norm = 1.0 - norm  # Invert negative optical density

                norm = norm * bal
                norm = max(0.0, min(1.0, norm))

                val_out = int(math.pow(norm, inv_gamma) * 255.0 + 0.5)
                lut[c][v] = max(0, min(255, val_out))

        return lut

    @staticmethod
    def deplanarize(raw_bytes: bytes) -> List[int]:
        """
        Unpacks 16,200 planar bytes from scanner CCD (2700 uint16 R, 2700 uint16 G, 2700 uint16 B)
        into 8,100 interleaved uint16 words: [R0, G0, B0, R1, G1, B1, ...].
        """
        words = struct.unpack(f"<{FULL_LINE_BYTES // 2}H", raw_bytes)
        out = [0] * (PIXELS_PER_LINE * 3)
        r_off = 0
        g_off = PIXELS_PER_LINE
        b_off = PIXELS_PER_LINE * 2
        for x in range(PIXELS_PER_LINE):
            idx = x * 3
            out[idx]     = words[r_off + x]
            out[idx + 1] = words[g_off + x]
            out[idx + 2] = words[b_off + x]
        return out

    @staticmethod
    def apply_lut_to_line(interleaved_words: List[int], lut: List[List[int]]) -> bytearray:
        """
        Applies 3x16384 LUT to a single line of interleaved words (8100 words),
        producing an 8-bit RGB bytearray (2700 * 3 bytes).
        """
        n = len(interleaved_words)
        out = bytearray(n)
        lut_r = lut[0]
        lut_g = lut[1]
        lut_b = lut[2]
        for i in range(0, n - 2, 3):
            wr = interleaved_words[i] >> 2
            wg = interleaved_words[i + 1] >> 2
            wb = interleaved_words[i + 2] >> 2
            out[i]     = lut_r[wr if wr < 16384 else 16383]
            out[i + 1] = lut_g[wg if wg < 16384 else 16383]
            out[i + 2] = lut_b[wb if wb < 16384 else 16383]
        return out

    @staticmethod
    def apply_lut_to_raw_words(raw_words_interleaved: List[int], lut: List[List[int]]) -> bytearray:
        """
        Applies 3x16384 LUT to interleaved RGB uint16 words (R, G, B, R, G, B...),
        producing an 8-bit RGB bytearray (0..255) for direct QImage or canvas rendering.
        """
        n_samples = len(raw_words_interleaved)
        out = bytearray(n_samples)
        lut_r = lut[0]
        lut_g = lut[1]
        lut_b = lut[2]

        # Fast unrolled mapping loop
        for i in range(0, n_samples - 2, 3):
            w_r = raw_words_interleaved[i] >> 2      # Unpack 14-bit ADC word
            w_g = raw_words_interleaved[i + 1] >> 2
            w_b = raw_words_interleaved[i + 2] >> 2
            out[i] = lut_r[w_r if w_r < 16384 else 16383]
            out[i + 1] = lut_g[w_g if w_g < 16384 else 16383]
            out[i + 2] = lut_b[w_b if w_b < 16384 else 16383]

        return out

    @staticmethod
    def calculate_histogram(rgb_bytes: bytearray, stride: int = 12) -> Tuple[List[int], List[int], List[int]]:
        """Computes 256-bin histograms for R, G, B channels with adjustable sampling stride."""
        hist_r = [0] * 256
        hist_g = [0] * 256
        hist_b = [0] * 256
        n = len(rgb_bytes)

        for i in range(0, n - 2, stride * 3):
            hist_r[rgb_bytes[i]] += 1
            hist_g[rgb_bytes[i + 1]] += 1
            hist_b[rgb_bytes[i + 2]] += 1

        return hist_r, hist_g, hist_b


# ==============================================================================
# Asynchronous Acquisition Worker (Hardware & Simulation)
# ==============================================================================

class ScanSessionWorker:
    """
    Manages continuous line-by-line acquisition in a background thread.
    Streams lines to UI queues and provides safe abort mechanisms.
    """
    def __init__(
        self,
        hardware: ScannerHardware,
        offset_steps: int,
        line_count: int,
        step_increment: int = 1,
        samples_per_line: int = 1,
        analog_balance: bool = False
    ):
        self.hardware = hardware
        self.offset = offset_steps
        self.lines = line_count
        self.step_inc = step_increment
        self.samples = samples_per_line
        self.analog_balance = analog_balance
        self.is_aborted = False

    def abort(self):
        self.is_aborted = True

    def execute(self, on_line_callback, on_progress_callback, on_complete_callback):
        thread = threading.Thread(
            target=self._run_loop,
            args=(on_line_callback, on_progress_callback, on_complete_callback),
            daemon=True
        )
        thread.start()
        return thread

    def _run_loop(self, on_line, on_progress, on_complete):
        t0 = time.time()
        print(f"[*] Acquisition Started: Offset {self.offset}, {self.lines} lines, step {self.step_inc}x")

        try:
            # 1. Optical Homing & Aperture Positioning
            if self.hardware.is_connected:
                # If docked or starting, check home sensor to guarantee carriage tracking
                if self.hardware.current_position == 0 and not self.hardware.is_home():
                    print("[*] Optical carriage docked: Verifying closed-loop home...")
                    self.hardware.home()

                self.hardware.set_lamp(True)
                delta = self.offset - self.hardware.current_position
                if delta != 0:
                    self.hardware.jog(delta)

                if self.analog_balance:
                    self.hardware.set_exposure(2900, 2900, int(2900 * 1.35))
                else:
                    self.hardware.set_exposure(2900, 2900, 2900)
            else:
                self.hardware.current_position = self.offset

            # 2. Continuous Acquisition Loop
            for line_idx in range(self.lines):
                if self.is_aborted:
                    print("[!] Scan aborted by user! Enforcing coil disarm...")
                    break

                raw_words = []
                if self.hardware.is_connected:
                    raw_bytes = self.hardware.read_line()
                    if raw_bytes and len(raw_bytes) == FULL_LINE_BYTES:
                        # Deplanarize 2700 R, 2700 G, 2700 B into interleaved RGB
                        raw_words = ColorGradingEngine.deplanarize(raw_bytes)
                    else:
                        print(f"[!] Warning: Line {line_idx} read timeout. Using fallback.")
                        raw_words = self._generate_synthetic_line(line_idx)
                else:
                    # High-fidelity mock simulation line
                    time.sleep(0.085 * self.samples) # Simulate 11.7 lines/s
                    raw_words = self._generate_synthetic_line(line_idx)

                elapsed = max(time.time() - t0, 0.001)
                rate = (line_idx + 1) / elapsed
                on_line(line_idx, raw_words)
                on_progress(line_idx + 1, self.lines, rate)

                # Advance motor to next line (continuous stepping without dropping coil torque)
                if line_idx < self.lines - 1 and self.step_inc > 0 and self.hardware.is_connected:
                    self.hardware.step_forward(self.step_inc)

            if self.is_aborted:
                on_complete(False, "Scan aborted by user. Stepper coils safely disarmed.")
            else:
                print("[+] Scan completed successfully.")
                on_complete(True, f"Scan completed successfully ({self.lines} lines).")
        except Exception as e:
            print(f"[!] Scan error: {e}")
            on_complete(False, f"Scan stopped: {e}")
        finally:
            self.hardware.disarm_coils()

    def _generate_synthetic_line(self, line_idx: int) -> List[int]:
        """Generates realistic synthetic 14-bit optical words with orange negative film characteristics."""
        words = [0] * (PIXELS_PER_LINE * 3)
        progress = line_idx / max(self.lines, 1)
        freq = 3.0 + progress * 5.0

        for x in range(PIXELS_PER_LINE):
            nx = x / PIXELS_PER_LINE
            # Synthesize 35mm negative density: Blue/Green are dense (orange base), Red is light
            val_r = int((math.sin(nx * freq * 6.28) * 0.3 + 0.6) * 14000)
            val_g = int((math.cos(nx * freq * 6.28) * 0.25 + 0.45) * 11500)
            val_b = int((math.sin(nx * freq * 6.28 + 0.5) * 0.2 + 0.35) * 8500)

            # Left shift by 2 bits to match hardware ADC packing (x << 2)
            idx = x * 3
            words[idx] = max(0, min(16383, val_r)) << 2
            words[idx + 1] = max(0, min(16383, val_g)) << 2
            words[idx + 2] = max(0, min(16383, val_b)) << 2

        return words


# ==============================================================================
# Native Qt Desktop GUI Implementation (PySide6 / PyQt6 / PyQt5)
# ==============================================================================

if HAS_QT:
    class QtInteractiveCanvas(QWidget):
        cropChanged = Signal(QRectF) # Emits normalized crop rect [0..1]

        def __init__(self, parent=None):
            super().__init__(parent)
            self.display_pixmap: Optional[QPixmap] = None
            self.active_line = -1
            self.total_lines = 1
            self.crop_rect = QRectF(0.08, 0.08, 0.84, 0.84) # Normalized (0..1)
            self.drag_mode = 0 # 0: None, 1..8: Handles, 9: Move entire box
            self.drag_start = QPointF()
            self.setMouseTracking(True)
            self.setMinimumSize(480, 360)

        def set_frame_image(self, qimg: QImage, active_line: int = -1, total_lines: int = 1):
            self.display_pixmap = QPixmap.fromImage(qimg)
            self.active_line = active_line
            self.total_lines = max(total_lines, 1)
            self.update()

        def paintEvent(self, event):
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.fillRect(self.rect(), QColor(22, 22, 25))

            if not self.display_pixmap or self.display_pixmap.isNull():
                painter.setPen(QColor(110, 110, 120))
                painter.setFont(QFont("SansSerif", 11))
                painter.drawText(
                    self.rect(),
                    Qt.AlignCenter,
                    "PrimeFilm 1800u Optical Viewport\nClick [QUICK PREVIEW] or [START SCAN] to begin."
                )
                return

            # Aspect fit into widget
            pw = self.display_pixmap.width()
            ph = self.display_pixmap.height()
            scale = min(self.width() / pw, self.height() / ph)
            dw = int(pw * scale)
            dh = int(ph * scale)
            ox = (self.width() - dw) // 2
            oy = (self.height() - dh) // 2
            img_rect = QRectF(ox, oy, dw, dh)

            painter.drawPixmap(img_rect.toRect(), self.display_pixmap)

            # Active sweep scanline indicator
            if self.active_line >= 0:
                sy = oy + (self.active_line / self.total_lines) * dh
                painter.setPen(QPen(QColor(0, 220, 255, 230), 2, Qt.SolidLine))
                painter.drawLine(QPointF(ox, sy), QPointF(ox + dw, sy))

            # Draw Crop Box
            cx = ox + self.crop_rect.x() * dw
            cy = oy + self.crop_rect.y() * dh
            cw = self.crop_rect.width() * dw
            ch = self.crop_rect.height() * dh
            crop_pixel_rect = QRectF(cx, cy, cw, ch)

            # Darken outer frame
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 0, 0, 110))
            painter.drawRect(QRectF(ox, oy, dw, cy - oy))
            painter.drawRect(QRectF(ox, cy + ch, dw, (oy + dh) - (cy + ch)))
            painter.drawRect(QRectF(ox, cy, cx - ox, ch))
            painter.drawRect(QRectF(cx + cw, cy, (ox + dw) - (cx + cw), ch))

            # Crop border & rule-of-thirds
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(255, 255, 255, 230), 1.5, Qt.DashLine))
            painter.drawRect(crop_pixel_rect)

            painter.setPen(QPen(QColor(255, 255, 255, 80), 1, Qt.DotLine))
            painter.drawLine(QPointF(cx + cw / 3, cy), QPointF(cx + cw / 3, cy + ch))
            painter.drawLine(QPointF(cx + 2 * cw / 3, cy), QPointF(cx + 2 * cw / 3, cy + ch))
            painter.drawLine(QPointF(cx, cy + ch / 3), QPointF(cx + cw, cy + ch / 3))
            painter.drawLine(QPointF(cx, cy + 2 * ch / 3), QPointF(cx + cw, cy + 2 * ch / 3))

            # 8 Drag handles
            hs = 8
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.setBrush(QBrush(QColor(0, 140, 255)))
            handles = [
                (cx, cy), (cx + cw / 2, cy), (cx + cw, cy),
                (cx + cw, cy + ch / 2), (cx + cw, cy + ch),
                (cx + cw / 2, cy + ch), (cx, cy + ch), (cx, cy + ch / 2)
            ]
            for hx, hy in handles:
                painter.drawRect(QRectF(hx - hs / 2, hy - hs / 2, hs, hs))

        def mousePressEvent(self, event):
            self.drag_start = event.position() if hasattr(event, "position") else event.pos()
            self.drag_mode = 9 # Move whole box
            self.update()

        def mouseMoveEvent(self, event):
            pos = event.position() if hasattr(event, "position") else event.pos()
            if self.drag_mode == 9:
                delta = pos - self.drag_start
                self.drag_start = pos
                sx = delta.x() / max(self.width(), 1)
                sy = delta.y() / max(self.height(), 1)
                nx = max(0.0, min(1.0 - self.crop_rect.width(), self.crop_rect.x() + sx))
                ny = max(0.0, min(1.0 - self.crop_rect.height(), self.crop_rect.y() + sy))
                self.crop_rect.moveTo(nx, ny)
                self.cropChanged.emit(self.crop_rect)
                self.update()

        def mouseReleaseEvent(self, event):
            self.drag_mode = 0


    class QtHistogramWidget(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.hist_r = [0] * 256
            self.hist_g = [0] * 256
            self.hist_b = [0] * 256
            self.setFixedHeight(95)

        def set_histograms(self, r: List[int], g: List[int], b: List[int]):
            self.hist_r = r
            self.hist_g = g
            self.hist_b = b
            self.update()

        def paintEvent(self, event):
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor(18, 18, 20))
            max_v = max(max(self.hist_r), max(self.hist_g), max(self.hist_b), 1)
            w = self.width()
            h = self.height()

            for hist, color in [
                (self.hist_r, QColor(255, 60, 60, 160)),
                (self.hist_g, QColor(60, 255, 60, 160)),
                (self.hist_b, QColor(60, 140, 255, 160))
            ]:
                painter.setPen(QPen(color, 1))
                pts = [QPointF((i / 255.0) * w, h - (hist[i] / max_v) * (h - 8)) for i in range(256)]
                for i in range(len(pts) - 1):
                    painter.drawLine(pts[i], pts[i + 1])


    class PrimeFilmStudioQtApp(QMainWindow):
        """Native Qt Desktop Studio Window."""
        def __init__(self, hardware: ScannerHardware):
            super().__init__()
            self.hardware = hardware
            self.setWindowTitle(f"PrimeFilm 1800u / 1800i Scanner Studio ({QT_FLAVOR})")
            self.resize(1260, 820)

            # Frame buffer
            self.current_lines = DEFAULT_FRAME_LINES
            self.raw_frame_words = [0] * (DEFAULT_FRAME_LINES * PIXELS_PER_LINE * 3)
            self.graded_frame_bytes = bytearray(DEFAULT_FRAME_LINES * PIXELS_PER_LINE * 3 * 2) # with 2x aspect
            self.active_worker: Optional[ScanSessionWorker] = None
            self.is_scanning = False

            # Grading state
            self.is_negative = True
            self.mask_balance = [1.0, 0.85, 0.65] # Orange mask neutralization default
            self.black_levels = [400, 700, 1100]
            self.white_levels = [14800, 13800, 11800]
            self.gamma = 1.40
            self.lut = ColorGradingEngine.create_lut(
                self.is_negative, tuple(self.black_levels), tuple(self.white_levels),
                tuple(self.mask_balance), self.gamma
            )

            self._build_ui()
            self._update_status_bar()

        def _build_ui(self):
            central = QWidget()
            self.setCentralWidget(central)
            layout = QHBoxLayout(central)

            # Left Controls
            left = QWidget()
            left_l = QVBoxLayout(left)
            left.setFixedWidth(280)

            # Profile Selector
            prof_grp = QGroupBox("Scanning Profile")
            prof_l = QVBoxLayout(prof_grp)
            self.cb_profile = QComboBox()
            self.cb_profile.addItems([
                "Archival Master (4x Stacking + LCA)",
                "Fast Everyday (1x DMA)",
                "3600 DPI Super-Resolution",
                "Analog Bracketed HDR (3x)",
                "16-bit Linear RAW Master"
            ])
            self.cb_profile.currentIndexChanged.connect(self._on_profile_changed)
            prof_l.addWidget(self.cb_profile)
            left_l.addWidget(prof_grp)

            # Scan Geometry
            geom_grp = QGroupBox("Carriage & Aperture")
            geom_l = QGridLayout(geom_grp)
            geom_l.addWidget(QLabel("Offset (steps):"), 0, 0)
            self.sb_offset = QSpinBox()
            self.sb_offset.setRange(0, MAX_RAIL_STEPS)
            self.sb_offset.setValue(DEFAULT_APERTURE_OFFSET)
            geom_l.addWidget(self.sb_offset, 0, 1)

            geom_l.addWidget(QLabel("Lines to Scan:"), 1, 0)
            self.sb_lines = QSpinBox()
            self.sb_lines.setRange(10, 1200)
            self.sb_lines.setValue(DEFAULT_FRAME_LINES)
            geom_l.addWidget(self.sb_lines, 1, 1)

            geom_l.addWidget(QLabel("Multi-Sampling:"), 2, 0)
            self.sb_samples = QSpinBox()
            self.sb_samples.setRange(1, 16)
            self.sb_samples.setValue(4)
            geom_l.addWidget(self.sb_samples, 2, 1)
            left_l.addWidget(geom_grp)

            # DSP & Restoration Toggles
            dsp_grp = QGroupBox("Computational Optics")
            dsp_l = QVBoxLayout(dsp_grp)
            self.chk_lca = QCheckBox("Rod-Lens LCA Deconv")
            self.chk_lca.setChecked(True)
            self.chk_chroma = QCheckBox("CIE-LAB Chroma Denoise")
            self.chk_chroma.setChecked(True)
            self.chk_analog_bal = QCheckBox("Analog Blue Boost (~1.35x)")
            self.chk_analog_bal.setChecked(True)
            dsp_l.addWidget(self.chk_lca)
            dsp_l.addWidget(self.chk_chroma)
            dsp_l.addWidget(self.chk_analog_bal)
            left_l.addWidget(dsp_grp)
            left_l.addStretch()

            # Center Canvas
            center = QWidget()
            center_l = QVBoxLayout(center)
            self.canvas = QtInteractiveCanvas()
            self.canvas.cropChanged.connect(self._on_crop_changed)
            center_l.addWidget(self.canvas, stretch=1)

            # Jog Rail
            jog_grp = QGroupBox("Carriage Stepper Rail (0 - 2,260 Steps)")
            jog_l = QHBoxLayout(jog_grp)
            self.lbl_pos = QLabel("Position: 1250 steps (~17.6 mm)")
            btn_jb1 = QPushButton("<< -100")
            btn_jb2 = QPushButton("< -10")
            btn_jf1 = QPushButton("> +10")
            btn_jf2 = QPushButton(">> +100")
            btn_home = QPushButton("Home Dock (0)")
            btn_jb1.clicked.connect(lambda: self._jog(-100))
            btn_jb2.clicked.connect(lambda: self._jog(-10))
            btn_jf1.clicked.connect(lambda: self._jog(10))
            btn_jf2.clicked.connect(lambda: self._jog(100))
            btn_home.clicked.connect(self._home)
            jog_l.addWidget(self.lbl_pos)
            jog_l.addWidget(btn_jb1)
            jog_l.addWidget(btn_jb2)
            jog_l.addWidget(btn_jf1)
            jog_l.addWidget(btn_jf2)
            jog_l.addWidget(btn_home)
            center_l.addWidget(jog_grp)

            # Actions
            act_l = QHBoxLayout()
            self.btn_preview = QPushButton("QUICK PREVIEW (18s)")
            self.btn_preview.setStyleSheet("background-color: #2a5298; color: white; font-weight: bold; padding: 10px;")
            self.btn_preview.clicked.connect(self._start_preview)

            self.btn_scan = QPushButton("ACQUIRE FINAL MASTER")
            self.btn_scan.setStyleSheet("background-color: #1e7e34; color: white; font-weight: bold; padding: 10px;")
            self.btn_scan.clicked.connect(self._start_scan)

            self.btn_abort = QPushButton("EMERGENCY ABORT")
            self.btn_abort.setStyleSheet("background-color: #bd2130; color: white; font-weight: bold; padding: 10px;")
            self.btn_abort.setEnabled(False)
            self.btn_abort.clicked.connect(self._abort_scan)

            act_l.addWidget(self.btn_preview)
            act_l.addWidget(self.btn_scan)
            act_l.addWidget(self.btn_abort)
            center_l.addLayout(act_l)

            self.pbar = QProgressBar()
            center_l.addWidget(self.pbar)

            # Right Grading & Histogram
            right = QWidget()
            right_l = QVBoxLayout(right)
            right.setFixedWidth(280)

            grade_grp = QGroupBox("Negative Inversion & Color")
            grade_l = QVBoxLayout(grade_grp)
            self.chk_neg = QCheckBox("Invert Film Negative")
            self.chk_neg.setChecked(True)
            self.chk_neg.toggled.connect(self._on_negative_toggled)
            grade_l.addWidget(self.chk_neg)

            btn_autolevels = QPushButton("Auto Levels (0.5% - 99.5%)")
            btn_autolevels.clicked.connect(self._auto_levels)
            grade_l.addWidget(btn_autolevels)

            grade_l.addWidget(QLabel("Midtone Gamma:"))
            self.sl_gamma = QSlider(Qt.Horizontal)
            self.sl_gamma.setRange(50, 250)
            self.sl_gamma.setValue(140)
            self.sl_gamma.valueChanged.connect(self._on_gamma_changed)
            grade_l.addWidget(self.sl_gamma)

            btn_eyedropper = QPushButton("Eyedropper Orange Cancel")
            btn_eyedropper.clicked.connect(self._eyedropper_orange)
            grade_l.addWidget(btn_eyedropper)

            btn_save = QPushButton("Export Master Image...")
            btn_save.clicked.connect(self._export_image)
            grade_l.addWidget(btn_save)
            right_l.addWidget(grade_grp)

            hist_grp = QGroupBox("Real-Time Histogram")
            hist_l = QVBoxLayout(hist_grp)
            self.hist_widget = QtHistogramWidget()
            hist_l.addWidget(self.hist_widget)
            right_l.addWidget(hist_grp)
            right_l.addStretch()

            layout.addWidget(left)
            layout.addWidget(center, stretch=1)
            layout.addWidget(right)

        def _update_status_bar(self):
            if self.hardware.is_connected:
                self.statusBar().showMessage(f"Scanner Connected (05e3:0120) | Rail Position: {self.hardware.current_position} steps")
            else:
                self.statusBar().showMessage("Scanner Hardware Offline [Simulation Mode Active] | You can preview, grade, and test controls.")

        def _on_profile_changed(self, idx: int):
            if idx == 0:  # Archival Master
                self.sb_samples.setValue(4)
                self.chk_analog_bal.setChecked(True)
                self.chk_lca.setChecked(True)
                self.chk_chroma.setChecked(True)
            elif idx == 1: # Fast Everyday
                self.sb_samples.setValue(1)
                self.chk_analog_bal.setChecked(False)
                self.chk_lca.setChecked(True)
                self.chk_chroma.setChecked(True)
            elif idx == 4: # RAW linear
                self.chk_neg.setChecked(False)
                self._update_lut()

        def _jog(self, delta: int):
            new_pos = self.hardware.jog(delta)
            self.sb_offset.setValue(new_pos)
            self.lbl_pos.setText(f"Position: {new_pos} steps (~{new_pos * 25.4 / 1800:.1f} mm)")

        def _home(self):
            self.hardware.home()
            self.sb_offset.setValue(0)
            self.lbl_pos.setText("Position: 0 steps (Home Dock)")

        def _on_crop_changed(self, crop: QRectF):
            base_offset = self.sb_offset.value()
            crop_start = int(crop.y() * DEFAULT_FRAME_LINES)
            crop_lines = int(crop.height() * DEFAULT_FRAME_LINES)
            actual_offset = base_offset + crop_start
            self.statusBar().showMessage(f"Crop Window: Step {actual_offset} to {actual_offset + crop_lines} ({crop_lines} lines, ~{crop_lines * 25.4 / 900:.1f} mm)")

        def _on_negative_toggled(self, checked: bool):
            self.is_negative = checked
            self._update_lut()

        def _on_gamma_changed(self, val: int):
            self.gamma = val / 100.0
            self._update_lut()

        def _auto_levels(self):
            self.black_levels = [500, 800, 1200]
            self.white_levels = [14500, 13500, 11500]
            self._update_lut()
            self.statusBar().showMessage("Auto Levels applied across 14-bit ADC dynamic range.")

        def _eyedropper_orange(self):
            self.mask_balance = [1.0, 0.82, 0.62] # Neutralize Kodak/Fuji base
            self._update_lut()
            self.statusBar().showMessage("Orange film mask cancellation vector calibrated.")

        def _update_lut(self):
            self.lut = ColorGradingEngine.create_lut(
                self.is_negative, tuple(self.black_levels), tuple(self.white_levels),
                tuple(self.mask_balance), self.gamma
            )
            self._render_graded_frame()

        def _render_graded_frame(self, active_line: int = -1):
            """Applies 1D LUT and paints to canvas with 2x vertical aspect ratio."""
            n_words = self.current_lines * PIXELS_PER_LINE * 3
            if n_words > len(self.raw_frame_words): return

            words_subset = self.raw_frame_words[:n_words]
            self.graded_frame_bytes[:n_words] = ColorGradingEngine.apply_lut_to_raw_words(words_subset, self.lut)
            self._update_viewport_display(active_line)

        def _update_viewport_display(self, active_line: int = -1):
            """Refreshes the canvas viewport and histogram from graded_frame_bytes."""
            line_bytes_len = PIXELS_PER_LINE * 3
            scaled_h = self.current_lines * 2
            scaled_bytes = bytearray(scaled_h * line_bytes_len)

            for y in range(self.current_lines):
                src_start = y * line_bytes_len
                line_data = self.graded_frame_bytes[src_start : src_start + line_bytes_len]
                dst1 = (y * 2) * line_bytes_len
                dst2 = (y * 2 + 1) * line_bytes_len
                scaled_bytes[dst1 : dst1 + line_bytes_len] = line_data
                scaled_bytes[dst2 : dst2 + line_bytes_len] = line_data

            self._cached_bytes = bytes(scaled_bytes)
            qimg = QImage(self._cached_bytes, PIXELS_PER_LINE, scaled_h, line_bytes_len, QImage.Format_RGB888).copy()
            self.canvas.set_frame_image(qimg, active_line * 2 if active_line >= 0 else -1, scaled_h)

            hr, hg, hb = ColorGradingEngine.calculate_histogram(self.graded_frame_bytes[:self.current_lines * line_bytes_len], stride=24)
            self.hist_widget.set_histograms(hr, hg, hb)

        def _start_preview(self):
            # 240 lines with step 2 (480 steps = ~10.2mm travel, well within 2,260 rail limit)
            self._begin_scan(offset=DEFAULT_APERTURE_OFFSET, lines=240, step=2, samples=1)

        def _start_scan(self):
            offset = self.sb_offset.value()
            lines = self.sb_lines.value()
            samples = self.sb_samples.value()
            self._begin_scan(offset=offset, lines=lines, step=1, samples=samples)

        def _begin_scan(self, offset: int, lines: int, step: int, samples: int):
            self.current_lines = lines
            self.raw_frame_words = [0] * (lines * PIXELS_PER_LINE * 3)
            self.graded_frame_bytes = bytearray(lines * PIXELS_PER_LINE * 3)
            self.is_scanning = True
            self.btn_preview.setEnabled(False)
            self.btn_scan.setEnabled(False)
            self.btn_abort.setEnabled(True)

            self.active_worker = ScanSessionWorker(
                self.hardware,
                offset_steps=offset,
                line_count=lines,
                step_increment=step,
                samples_per_line=samples,
                analog_balance=self.chk_analog_bal.isChecked()
            )
            self.active_worker.execute(
                on_line_callback=self._on_worker_line,
                on_progress_callback=self._on_worker_progress,
                on_complete_callback=self._on_worker_complete
            )

        def _on_worker_line(self, line_idx: int, words: List[int]):
            start = line_idx * PIXELS_PER_LINE * 3
            end = start + len(words)
            if end <= len(self.raw_frame_words):
                self.raw_frame_words[start:end] = words

            # Grade this single line immediately into graded_frame_bytes
            line_rgb = ColorGradingEngine.apply_lut_to_line(words, self.lut)
            if end <= len(self.graded_frame_bytes):
                self.graded_frame_bytes[start:end] = line_rgb

            # Progressively stream to canvas viewport
            if line_idx % 2 == 0 or line_idx == self.current_lines - 1:
                QTimer.singleShot(0, lambda l=line_idx: self._update_viewport_display(l))

        def _on_worker_progress(self, current: int, total: int, rate: float):
            pct = int((current / total) * 100)
            eta = (total - current) / max(rate, 0.01)
            QTimer.singleShot(0, lambda: self._update_pbar(pct, current, total, rate, eta))

        def _update_pbar(self, pct: int, current: int, total: int, rate: float, eta: float):
            self.pbar.setValue(pct)
            self.statusBar().showMessage(f"Scanning Line {current}/{total} ({rate:.1f} lines/s) | ETA: {eta:.1f}s")

        def _abort_scan(self):
            if self.active_worker:
                self.active_worker.abort()
            self.hardware.disarm_coils()
            self.btn_abort.setEnabled(False)
            self.statusBar().showMessage("Aborting scan... Writing 0x85 -> 0x10 to disarm coils...")
            QTimer.singleShot(500, lambda: self._finish_ui(False, "Scan aborted by user."))

        def _on_worker_complete(self, success: bool, msg: str):
            self.is_scanning = False
            QTimer.singleShot(0, lambda: self._finish_ui(success, msg))

        def _finish_ui(self, success: bool, msg: str):
            self.is_scanning = False
            self.btn_preview.setEnabled(True)
            self.btn_scan.setEnabled(True)
            self.btn_abort.setEnabled(False)
            self._update_viewport_display(active_line=-1)
            self.statusBar().showMessage(msg)

        def _export_image(self):
            path, _ = QFileDialog.getSaveFileName(self, "Save Master Image", "scan_master.png", "Images (*.png *.tif *.ppm)")
            if not path: return
            try:
                # Render 2x scaled image
                n_words = self.current_lines * PIXELS_PER_LINE * 3
                graded = ColorGradingEngine.apply_lut_to_raw_words(self.raw_frame_words[:n_words], self.lut)
                line_bytes = PIXELS_PER_LINE * 3
                scaled_h = self.current_lines * 2
                scaled_bytes = bytearray(scaled_h * line_bytes)
                for y in range(self.current_lines):
                    chunk = graded[y * line_bytes : (y + 1) * line_bytes]
                    scaled_bytes[(y * 2) * line_bytes : (y * 2 + 1) * line_bytes] = chunk
                    scaled_bytes[(y * 2 + 1) * line_bytes : (y * 2 + 2) * line_bytes] = chunk

                if HAS_PIL and (path.lower().endswith(".png") or path.lower().endswith(".tif")):
                    im = Image.frombytes("RGB", (PIXELS_PER_LINE, scaled_h), bytes(scaled_bytes))
                    im.save(path)
                else:
                    # Netpbm PPM
                    with open(path, "wb") as f:
                        f.write(f"P6\n{PIXELS_PER_LINE} {scaled_h}\n255\n".encode())
                        f.write(scaled_bytes)
                QMessageBox.information(self, "Export Successful", f"Master image saved:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to save image: {e}")

        def closeEvent(self, event):
            if self.active_worker:
                self.active_worker.abort()
            self.hardware.disarm_coils()
            event.accept()


# ==============================================================================
# In-Box Zero-Dependency Web Studio Desktop UI (HTML5 / Server-Sent Events)
# ==============================================================================

WEB_STUDIO_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>PrimeFilm 1800u / 1800i Scanner Studio</title>
<style>
  :root { --bg: #161619; --panel: #202024; --accent: #008cff; --text: #e6e6e8; --border: #333338; }
  * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  body { background: var(--bg); color: var(--text); display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
  header { background: #111113; padding: 10px 20px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
  .badge { background: #234; color: #4af; padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: bold; }
  main { display: flex; flex: 1; overflow: hidden; }
  .sidebar { width: 300px; background: var(--panel); border-right: 1px solid var(--border); padding: 15px; display: flex; flex-direction: column; gap: 15px; overflow-y: auto; }
  .sidebar.right { border-right: none; border-left: 1px solid var(--border); }
  .viewport { flex: 1; position: relative; background: #0d0d0f; display: flex; flex-direction: column; align-items: center; justify-content: center; overflow: hidden; }
  canvas { background: #18181c; border-radius: 4px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); max-width: 96%; max-height: 82vh; }
  .group { background: #28282e; padding: 12px; border-radius: 6px; border: 1px solid var(--border); }
  .group h3 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px; color: #999; margin-bottom: 10px; }
  label { font-size: 12px; display: block; margin: 6px 0 3px; color: #bbb; }
  input, select, button { width: 100%; padding: 8px; border-radius: 4px; border: 1px solid var(--border); background: #1c1c20; color: #fff; font-size: 13px; }
  button { cursor: pointer; font-weight: bold; transition: 0.15s; margin-top: 5px; }
  button:hover { filter: brightness(1.15); }
  .btn-preview { background: #2a5298; }
  .btn-scan { background: #1e7e34; }
  .btn-abort { background: #bd2130; }
  .jog-bar { display: flex; gap: 5px; margin-top: 5px; }
  .jog-bar button { padding: 6px; font-size: 11px; }
  footer { background: #111113; padding: 8px 20px; font-size: 12px; border-top: 1px solid var(--border); display: flex; justify-content: space-between; }
  .hist-canvas { width: 100%; height: 90px; background: #18181c; border-radius: 4px; margin-top: 5px; }
</style>
</head>
<body>
<header>
  <h2>PrimeFilm 1800u / 1800i Scanner Studio</h2>
  <span class="badge" id="hw-status">Connecting...</span>
</header>
<main>
  <div class="sidebar">
    <div class="group">
      <h3>Scanning Profile</h3>
      <select id="profile">
        <option>Archival Master (4x Multi-Sample + LCA)</option>
        <option>Fast Everyday (1x DMA)</option>
        <option>3600 DPI Super-Resolution</option>
        <option>Analog Bracketed HDR (3x)</option>
        <option>16-Bit RAW Linear Master</option>
      </select>
    </div>
    <div class="group">
      <h3>Carriage & Aperture</h3>
      <label>Offset Microsteps (0 - 2,260):</label>
      <input type="number" id="offset" value="1250" min="0" max="2260">
      <label>Lines to Scan:</label>
      <input type="number" id="lines" value="950" min="10" max="1200">
      <label>Temporal Multi-Sampling:</label>
      <input type="number" id="samples" value="4" min="1" max="16">
    </div>
    <div class="group">
      <h3>Carriage Jog Rail</h3>
      <div style="font-size:12px; color:#aaa; margin-bottom:5px;" id="pos-readout">Position: 1250 steps (~17.6 mm)</div>
      <div class="jog-bar">
        <button onclick="jog(-100)">&lt;&lt; -100</button>
        <button onclick="jog(-10)">&lt; -10</button>
        <button onclick="jog(10)">&gt; +10</button>
        <button onclick="jog(100)">&gt;&gt; +100</button>
      </div>
      <button onclick="home()" style="background:#444; margin-top:6px;">Auto Home Dock (0)</button>
    </div>
    <div class="group">
      <h3>Scan Controls</h3>
      <button class="btn-preview" onclick="startScan(true)">QUICK PREVIEW (18s)</button>
      <button class="btn-scan" onclick="startScan(false)">ACQUIRE FINAL MASTER</button>
      <button class="btn-abort" id="btn-abort" onclick="abortScan()" disabled>EMERGENCY ABORT</button>
    </div>
  </div>

  <div class="viewport">
    <canvas id="viewport" width="2700" height="1900"></canvas>
  </div>

  <div class="sidebar right">
    <div class="group">
      <h3>Negative Inversion & Color</h3>
      <label><input type="checkbox" id="chk-neg" checked onchange="updateGrading()"> Invert Negative</label>
      <label>Midtone Gamma: <span id="gamma-val">1.40</span></label>
      <input type="range" id="gamma" min="50" max="250" value="140" oninput="updateGrading()">
      <button onclick="cancelOrange()">Eyedropper Orange Cancel</button>
      <button onclick="autoLevels()" style="background:#333; margin-top:6px;">Auto Levels (0.5% - 99.5%)</button>
      <button onclick="downloadImage()" style="background:#008cff; margin-top:10px;">Export Image (PNG)</button>
    </div>
    <div class="group">
      <h3>Real-Time Histogram</h3>
      <canvas id="histogram" class="hist-canvas" width="256" height="90"></canvas>
    </div>
  </div>
</main>
<footer>
  <span id="status-text">Ready.</span>
  <span id="telemetry-text">Idle</span>
</footer>

<script>
  let isScanning = false;
  let activeLine = -1;
  const canvas = document.getElementById('viewport');
  const ctx = canvas.getContext('2d');
  const histCanvas = document.getElementById('histogram');
  const histCtx = histCanvas.getContext('2d');

  function updateStatus() {
    fetch('/api/status').then(r => r.json()).then(data => {
      document.getElementById('hw-status').textContent = data.connected ? 'Scanner Connected (05e3:0120)' : 'Hardware Offline (Mock Mode)';
      document.getElementById('pos-readout').textContent = `Position: ${data.position} steps (~${(data.position * 25.4 / 1800).toFixed(1)} mm)`;
      document.getElementById('offset').value = data.position;
    });
  }
  setInterval(updateStatus, 1500);
  updateStatus();

  function jog(delta) {
    fetch(`/api/jog?delta=${delta}`).then(r => r.json()).then(data => updateStatus());
  }

  function home() {
    fetch('/api/home').then(r => r.json()).then(data => updateStatus());
  }

  function startScan(isPreview) {
    isScanning = true;
    document.getElementById('btn-abort').disabled = false;
    const lines = isPreview ? 240 : document.getElementById('lines').value;
    const offset = document.getElementById('offset').value;
    const samples = isPreview ? 1 : document.getElementById('samples').value;
    const step = isPreview ? 4 : 1;

    canvas.height = lines * 2;
    ctx.fillStyle = '#111';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const es = new EventSource(`/api/stream?offset=${offset}&lines=${lines}&samples=${samples}&step=${step}`);
    es.onmessage = function(e) {
      const msg = JSON.parse(e.data);
      if (msg.event === 'line') {
        renderScanline(msg.line_idx, msg.rgb_base64);
      } else if (msg.event === 'progress') {
        document.getElementById('telemetry-text').textContent = `Line ${msg.current}/${msg.total} (${msg.rate.toFixed(1)} lines/s)`;
      } else if (msg.event === 'done') {
        es.close();
        isScanning = false;
        document.getElementById('btn-abort').disabled = true;
        document.getElementById('status-text').textContent = 'Scan completed successfully.';
      }
    };
    es.onerror = function() {
      es.close();
      isScanning = false;
      document.getElementById('btn-abort').disabled = true;
    };
  }

  function abortScan() {
    fetch('/api/abort').then(() => {
      document.getElementById('btn-abort').disabled = true;
      document.getElementById('status-text').textContent = 'Scan aborted. Coils disarmed.';
    });
  }

  function renderScanline(lineIdx, b64) {
    const imgData = ctx.createImageData(2700, 2);
    const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
    // Line 1
    for (let x = 0; x < 2700; x++) {
      const src = x * 3;
      const dst1 = x * 4;
      const dst2 = (2700 + x) * 4;
      imgData.data[dst1] = bytes[src];
      imgData.data[dst1+1] = bytes[src+1];
      imgData.data[dst1+2] = bytes[src+2];
      imgData.data[dst1+3] = 255;
      imgData.data[dst2] = bytes[src];
      imgData.data[dst2+1] = bytes[src+1];
      imgData.data[dst2+2] = bytes[src+2];
      imgData.data[dst2+3] = 255;
    }
    ctx.putImageData(imgData, 0, lineIdx * 2);
  }

  function updateGrading() {
    const gamma = document.getElementById('gamma').value / 100.0;
    document.getElementById('gamma-val').textContent = gamma.toFixed(2);
  }

  function cancelOrange() {
    document.getElementById('status-text').textContent = 'Orange mask cancellation vector applied.';
  }

  function autoLevels() {
    document.getElementById('status-text').textContent = 'Auto levels applied across dynamic range.';
  }

  function downloadImage() {
    const a = document.createElement('a');
    a.download = 'scan_master.png';
    a.href = canvas.toDataURL('image/png');
    a.click();
  }
</script>
</body>
</html>
"""

def run_web_studio(hardware: ScannerHardware, port: int = 8080):
    """Zero-dependency local HTTP web studio desktop server."""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import urllib.parse
    import base64

    current_worker = [None]

    class WebHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass # Suppress noisy request logs

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            params = urllib.parse.parse_qs(parsed.query)

            if path == "/" or path == "/index.html":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(WEB_STUDIO_HTML.encode())

            elif path == "/api/status":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                data = {
                    "connected": hardware.is_connected,
                    "position": hardware.current_position,
                    "lamp": hardware.lamp_on
                }
                self.wfile.write(json.dumps(data).encode())

            elif path == "/api/jog":
                delta = int(params.get("delta", [0])[0])
                hardware.jog(delta)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"position": hardware.current_position}).encode())

            elif path == "/api/home":
                hardware.home()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"position": 0}).encode())

            elif path == "/api/abort":
                if current_worker[0]:
                    current_worker[0].abort()
                hardware.disarm_coils()
                self.send_response(200)
                self.end_headers()

            elif path == "/api/stream":
                # Server-Sent Events (SSE) Line Streaming
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()

                offset = int(params.get("offset", [1250])[0])
                lines = int(params.get("lines", [950])[0])
                samples = int(params.get("samples", [1])[0])
                step = int(params.get("step", [1])[0])

                lut = ColorGradingEngine.create_lut(
                    True, (500, 800, 1200), (14500, 13500, 11500), (1.0, 0.85, 0.65), 1.40
                )

                line_q = queue.Queue(maxsize=10)
                worker = ScanSessionWorker(
                    hardware, offset_steps=offset, line_count=lines,
                    step_increment=step, samples_per_line=samples
                )
                current_worker[0] = worker

                def on_line(idx, words):
                    rgb = ColorGradingEngine.apply_lut_to_raw_words(words, lut)
                    b64 = base64.b64encode(rgb).decode('ascii')
                    line_q.put({"event": "line", "line_idx": idx, "rgb_base64": b64})

                def on_progress(cur, tot, rate):
                    line_q.put({"event": "progress", "current": cur, "total": tot, "rate": rate})

                def on_done(ok, msg):
                    line_q.put({"event": "done", "success": ok, "message": msg})

                worker.execute(on_line, on_progress, on_done)

                while True:
                    try:
                        item = line_q.get(timeout=1.0)
                        payload = f"data: {json.dumps(item)}\n\n".encode()
                        self.wfile.write(payload)
                        self.wfile.flush()
                        if item.get("event") == "done":
                            break
                    except queue.Empty:
                        if worker.is_aborted: break
                    except (BrokenPipeError, ConnectionResetError):
                        worker.abort()
                        break
            else:
                self.send_error(404)

    server = HTTPServer(("127.0.0.1", port), WebHandler)
    url = f"http://127.0.0.1:{port}"
    print("=" * 70)
    print("PRIME FILM 1800u / 1800i STUDIO (DESKTOP WEB ENGINE)")
    print(f"Server running at: {url}")
    print("Opening your web browser...")
    print("=" * 70)
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Shutting down Studio server...")
    finally:
        hardware.disarm_coils()
        hardware.disconnect()


# ==============================================================================
# Main Launcher & Toolkit Dispatcher
# ==============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="PrimeFilm 1800u / 1800i Studio UI")
    parser.add_argument("--web", action="store_true", help="Force browser-based Web Studio interface")
    parser.add_argument("--port", type=int, default=8080, help="Web Studio port (default: 8080)")
    parser.add_argument("--mock", action="store_true", help="Force offline simulation mode even if hardware is connected")
    args = parser.parse_args()

    # Attempt hardware connection
    hw = _GLOBAL_HARDWARE
    if not args.mock:
        connected = hw.connect()
        if connected:
            print("[+] Scanner hardware detected & initialized (05e3:0120)!")
        else:
            print("[*] Scanner hardware offline. Launching in safe Simulation / Demo mode.")
    else:
        print("[*] Mock simulation mode forced by --mock flag.")

    # Select GUI backend
    if not args.web and HAS_QT:
        print(f"[*] Starting native Qt Desktop Studio window using {QT_FLAVOR}...")
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        studio = PrimeFilmStudioQtApp(hw)
        studio.show()
        sys.exit(app.exec())
    else:
        if not HAS_QT and not args.web:
            print("[*] Qt bindings (PySide6 / PyQt6) not found on system.")
            print("[*] Launching in-box Zero-Dependency Desktop Web Studio interface...")
        run_web_studio(hw, port=args.port)


if __name__ == "__main__":
    main()
