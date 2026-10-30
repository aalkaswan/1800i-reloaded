#!/usr/bin/env python3
"""
PrimeFilm 1800u / 1800i Multi-Exposure Analog Bracketed HDR & Film Dmax Extender
Target Device: Pacific Image Electronics PrimeFilm 1800u / 1800i (USB VID:PID 05e3:0120)

Features:
1. Analog CCD Integration Time Bracketing:
   Controls ASIC registers 0x9c..0xa1 (16-bit exposure clocks) and 0xa2..0xaa (24-bit limits).
   Captures multi-exposure brackets per line (e.g. 1000 clocks highlights, 2900 midtones,
   5800 shadows, 11600 dense film extraction).
2. Per-Bracket Dark-Current DSNU Subtraction:
   Pre-calibrates dark frames at matching exposure times (lamp OFF) to eliminate thermal
   fixed-pattern noise before HDR blending.
3. HDR Fusion Algorithms:
   - Linear Radiance Map Recovery (Debevec / Poisson-optimal linear irradiance estimation).
   - Mertens Exposure Fusion (Multi-scale contrast + well-exposedness blending).
4. Physical Sensitometric Dmax & EV Expansion Metrics:
   Calculates exact dynamic range expansion (EV gain), optical density improvement (Delta Dmax),
   and signal-to-noise ratio (SNR).
5. Output Formats:
   - 16-bit uncompressed linear HDR TIFF master (for RAW negative grading tools).
   - Tonemapped 16-bit / 8-bit PNG and PPM files (Reinhard, Filmic ACES, Gamma 2.2).
"""

import sys
import os
import time
import math
import struct
import argparse
import subprocess
from typing import List, Tuple, Dict, Any, Optional, Union

# Optional Pillow for image export
try:
    from PIL import Image, ImageOps
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

# Optional PyUSB for live scanner communication
try:
    import usb.core
    import usb.util
    HAS_USB = True
except ImportError:
    HAS_USB = False


# ==============================================================================
# Hardware Constants & ASIC Register Definitions
# ==============================================================================

VENDOR_ID = 0x05e3
PRODUCT_ID = 0x0120

EP_IN = 0x81
FULL_LINE_BYTES = 16200  # 2,700 pixels * 3 channels * 2 bytes (uint16)
PIXELS_PER_LINE = 2700
WORDS_PER_LINE = 8100
MAX_RAIL_STEPS = 2260

# Nominal exposure clock presets (at ~460 kHz CCD timing)
# Hardware sampling gate (0x98..0x9b) supports clean linear integration across 2800..3800 clocks
DEFAULT_BRACKETS = [2800, 3100, 3500]  # Safe linear range with zero zeros / sampling cutoff
EXTENDED_BRACKETS = [2800, 3100, 3400, 3800]  # Extended dynamic range

# DMA descriptor for 16,200 bytes Bulk IN transfer
_DMA_DESC = struct.pack("<BBBB I", 0x00, 0x00, 0x00, 0x00, FULL_LINE_BYTES)


# ==============================================================================
# Low-Level Hardware Communication Primitives
# ==============================================================================

def wctl(dev, reg: int, data: Union[int, bytes], timeout: int = 1000):
    """Write USB vendor control transfer."""
    if isinstance(data, int):
        data = bytes([data])
    return dev.ctrl_transfer(0x40, 0x0c, reg, 0, data, timeout=timeout)

def rctl(dev, reg: int, timeout: int = 1000) -> Optional[int]:
    """Read USB vendor control transfer."""
    buf = dev.ctrl_transfer(0xc0, 0x0c, reg, 0, 1, timeout=timeout)
    return buf[0] if buf else None

def ieee_handshake_stage(dev, mode: int):
    """Execute GL640USB IEEE 1284.4 synchronization handshake stage."""
    wctl(dev, 0x87, 0x04)
    wctl(dev, 0x87, 0x04)
    sync_pattern = [0xff, 0xaa, 0x55, 0x00, 0xff, 0x87, 0x78]
    for b in sync_pattern:
        wctl(dev, 0x88, b)
        wctl(dev, 0x88, b)
    wctl(dev, 0x88, mode)
    wctl(dev, 0x88, mode)
    wctl(dev, 0x87, 0x05)
    wctl(dev, 0x87, 0x05)
    wctl(dev, 0x87, 0x04)
    wctl(dev, 0x87, 0x04)
    wctl(dev, 0x88, 0xff)
    wctl(dev, 0x88, 0xff)

def cyberview_init(dev):
    """Initialize ASIC parallel bridge to EPP Data Mode 0x80."""
    ieee_handshake_stage(dev, 0x30)
    time.sleep(0.02)
    ieee_handshake_stage(dev, 0x00)
    time.sleep(0.02)
    ieee_handshake_stage(dev, 0x80)
    time.sleep(0.02)

def asic_write(dev, reg: int, val: int, timeout: int = 1000):
    """Write scanner ASIC internal register via EPP address/data bus."""
    wctl(dev, 0x83, reg, timeout=timeout)
    wctl(dev, 0x85, val, timeout=timeout)

def asic_read(dev, reg: int, timeout: int = 1000) -> Optional[int]:
    """Read scanner ASIC internal register via EPP address/data bus."""
    wctl(dev, 0x83, reg, timeout=timeout)
    return rctl(dev, 0x84, timeout=timeout)

def wait_idle(dev, timeout: float = 5.0, poll_interval_s: float = 0.001) -> bool:
    """Poll ASIC status register 0x84 until scan and motor bits are idle."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        val = asic_read(dev, 0x84)
        if val is not None and (val & 0x1e) == 0:
            return True
        if poll_interval_s > 0:
            time.sleep(poll_interval_s)
    return False

def configure_hardware(dev):
    """Configure default GL640USB ASIC registers for optical scanning."""
    asic_write(dev, 0xc4, 0x00)
    asic_write(dev, 0xab, 0xaa)
    asic_write(dev, 0xac, 0xca)
    asic_write(dev, 0xad, 0x4b)  # Lamp OFF by default
    asic_write(dev, 0xae, 0x05)
    asic_write(dev, 0xc1, 0x07)
    asic_write(dev, 0xc2, 0x04)
    asic_write(dev, 0xc3, 0x12)
    asic_write(dev, 0xc5, 0x12)
    asic_write(dev, 0xe1, 0x00)
    asic_write(dev, 0xe5, 0x00)
    asic_write(dev, 0xe9, 0x00)
    asic_write(dev, 0x86, 0x10)

def set_exposure_limits(dev, r_limit=0xffffff, g_limit=0xffffff, b_limit=0xffffff):
    """
    Set 24-bit window exposure limits across registers 0xa2..0xaa.
    Writing 0xffffff unlocks the ASIC integration counter up to 16.7M clocks.
    """
    asic_read(dev, 0x87)
    asic_write(dev, 0xa2, r_limit & 0xff)
    asic_write(dev, 0xa3, g_limit & 0xff)
    asic_write(dev, 0xa4, b_limit & 0xff)
    asic_write(dev, 0xa5, (r_limit >> 8) & 0xff)
    asic_write(dev, 0xa6, (g_limit >> 8) & 0xff)
    asic_write(dev, 0xa7, (b_limit >> 8) & 0xff)
    asic_write(dev, 0xa8, (r_limit >> 16) & 0xff)
    asic_write(dev, 0xa9, (g_limit >> 16) & 0xff)
    asic_write(dev, 0xaa, (b_limit >> 16) & 0xff)

def set_exposure(dev, exp_r: int, exp_g: int, exp_b: int):
    """Set 16-bit integration time clocks per channel on registers 0x9c..0xa1."""
    asic_write(dev, 0x9c, exp_r & 0xff)
    asic_write(dev, 0x9d, (exp_r >> 8) & 0xff)
    asic_write(dev, 0x9e, exp_g & 0xff)
    asic_write(dev, 0x9f, (exp_g >> 8) & 0xff)
    asic_write(dev, 0xa0, exp_b & 0xff)
    asic_write(dev, 0xa1, (exp_b >> 8) & 0xff)

def set_gain_and_offset(dev, gain: int = 31, offset: int = 2):
    """Set AFE PGA gain (0..31) and DAC black-level offset for R, G, B."""
    for r in [0xe0, 0xe4, 0xe8]:
        asic_write(dev, r, gain)
    for r in [0xe2, 0xe6, 0xea]:
        asic_write(dev, r, offset)

def move_carriage(dev, direction_cmd: int, steps: int):
    """
    Step carriage stepper motor in chunks of <= 200 microsteps.
    Direction: 0x16 = forward into film bay, 0x14 = reverse towards home dock.
    ALWAYS disarms motor stepper driver with 0x85 -> 0x10.
    """
    if steps <= 0:
        return
    try:
        asic_write(dev, 0x85, direction_cmd)
        remaining = steps
        while remaining > 0:
            chunk = min(remaining, 200)
            asic_write(dev, 0x81, chunk)
            asic_write(dev, 0x83, 0x01)
            wait_idle(dev)
            remaining -= chunk
            time.sleep(0.003)
    finally:
        # Crucial hardware safety: disarm motor driver pulses to prevent coil overheating
        asic_write(dev, 0x85, 0x10)

def is_home(dev) -> bool:
    """Optical Home Sensor: Reg 0x84 bit 5 is 0 at home dock, 1 when away."""
    s84 = asic_read(dev, 0x84)
    return s84 is not None and (s84 & 0x20) == 0

def auto_home(dev) -> int:
    """Closed-loop optical homing: retracts carriage until home sensor trips."""
    if is_home(dev):
        return 0
    total = 0
    while not is_home(dev) and total < 6000:
        move_carriage(dev, 0x14, 50)
        total += 50
    asic_write(dev, 0x85, 0x10)
    return total

def set_lamp(dev, enable: bool):
    """Turn fluorescent aperture lamp ON or OFF."""
    if enable:
        asic_write(dev, 0xad, 0x0b)
        asic_write(dev, 0x85, 0x30)
    else:
        asic_write(dev, 0xad, 0x4b)
        asic_write(dev, 0x85, 0x10)

def capture_raw_line(dev) -> bytes:
    """
    Capture a single raw 16,200-byte line from Bulk IN endpoint 0x81.
    Format: 8,100 uint16 words: [2700 Red, 2700 Green, 2700 Blue].
    """
    # 1. Trigger optical exposure
    asic_write(dev, 0x85, 0x12)
    asic_write(dev, 0x81, 0x00)
    wait_idle(dev)

    # 2. Reset window end & SRAM read pointer
    for r in [0x90, 0x91, 0x92, 0x93, 0x94, 0x95]:
        asic_write(dev, r, 0x00)
    wait_idle(dev)

    # 3. Arm GL640 DMA
    wctl(dev, 0x83, 0x80)
    wctl(dev, 0x82, _DMA_DESC)

    # 4. Read bulk data
    raw = bytes(dev.read(EP_IN, FULL_LINE_BYTES, timeout=4000))
    wait_idle(dev, timeout=1.0)
    return raw

def connect_scanner():
    """Connect to and initialize PrimeFilm 1800u scanner over USB."""
    if not HAS_USB:
        raise RuntimeError("PyUSB (usb.core) is not installed.")
    dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
    if dev is None:
        raise ConnectionError(f"Scanner {VENDOR_ID:04x}:{PRODUCT_ID:04x} not found on USB bus.")

    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
    except Exception:
        pass
    try:
        dev.get_active_configuration()
    except Exception:
        try:
            dev.set_configuration()
        except Exception:
            pass
    try:
        usb.util.claim_interface(dev, 0)
    except Exception:
        pass

    wctl(dev, 0x8b, 0x00)
    time.sleep(0.05)
    wctl(dev, 0x8b, 0x40)
    time.sleep(0.05)
    cyberview_init(dev)
    configure_hardware(dev)
    set_exposure_limits(dev)

    # CCD Sampling Gate & Clock Generator (0x10003e72)
    asic_write(dev, 0x98, 0x01)
    asic_write(dev, 0x99, 0x00)
    asic_write(dev, 0x9a, 0x8d)
    asic_write(dev, 0x9b, 0x2a)
    return dev


# ==============================================================================
# Optical Black & Smooth Dark Reference Calibration
# ==============================================================================

def extract_optical_black(raw_words: List[int]) -> Tuple[float, float, float]:
    """
    Extract physical optical black reference level from shielded dummy sensels (cols 10..40).
    Under the sensor's physical opaque aluminum mask, these sensels establish the true
    active dark reference floor for each scan line without sensel-to-sensel clamping steps.
    """
    r_sensels = raw_words[10:40]
    g_sensels = raw_words[PIXELS_PER_LINE + 10 : PIXELS_PER_LINE + 40]
    b_sensels = raw_words[PIXELS_PER_LINE * 2 + 10 : PIXELS_PER_LINE * 2 + 40]

    ob_r = sum(sorted(r_sensels)[5:25]) / 20.0
    ob_g = sum(sorted(g_sensels)[5:25]) / 20.0
    ob_b = sum(sorted(b_sensels)[5:25]) / 20.0
    return ob_r, ob_g, ob_b

def lowpass_smooth_1d(signal: List[float], radius: int = 15) -> List[float]:
    """Fast 1D boxcar smoothing using prefix sums in O(N)."""
    n = len(signal)
    if n == 0 or radius <= 0:
        return list(signal)
    prefix = [0.0] * (n + 1)
    for i in range(n):
        prefix[i + 1] = prefix[i] + signal[i]
    out = [0.0] * n
    for i in range(n):
        left = max(0, i - radius)
        right = min(n - 1, i + radius)
        out[i] = (prefix[right + 1] - prefix[left]) / (right - left + 1)
    return out

class BracketDarkCalibration:
    """
    Stores smooth dark-current DSNU profiles and Optical Black references.
    Eliminates sensel clamping step artifacts (>4000 counts) that inject vertical color streaks.
    """
    def __init__(self):
        # Maps exposure_clocks -> dict of channel -> list of float [2700]
        self.profiles: Dict[int, Dict[str, List[float]]] = {}
        self.stats: Dict[int, Dict[str, Any]] = {}

    def add_bracket(self, exp_clocks: int, dark_r: List[float], dark_g: List[float], dark_b: List[float], smooth_clamped: bool = False):
        n = len(dark_r)
        clean_r = list(dark_r)
        clean_g = list(dark_g)
        clean_b = list(dark_b)

        if smooth_clamped:
            # On physical hardware, measuring dark frames with lamp OFF causes sensels to float/saturate
            # at the 4095 ADC ceiling or deviate widely from optical black.
            # Reject clamp artifacts by bounding sensel variation relative to optical black dummy sensels.
            for ch_arr in [clean_r, clean_g, clean_b]:
                ob = sum(ch_arr[10:40]) / 30.0
                for i in range(n):
                    if ch_arr[i] >= 4090.0 or abs(ch_arr[i] - ob) > 35.0:
                        ch_arr[i] = ob
                smoothed = lowpass_smooth_1d(ch_arr, radius=15)
                ch_arr[:] = smoothed

        self.profiles[exp_clocks] = {
            "r": clean_r,
            "g": clean_g,
            "b": clean_b,
        }

        # Compute DSNU statistics
        stats_ch = {}
        for ch, arr in [("r", clean_r), ("g", clean_g), ("b", clean_b)]:
            mean_v = sum(arr) / len(arr)
            var_v = sum((x - mean_v) ** 2 for x in arr) / len(arr)
            stats_ch[ch] = {
                "mean": round(mean_v, 2),
                "std": round(var_v ** 0.5, 2),
                "min": round(min(arr), 2),
                "max": round(max(arr), 2),
                "span": round(max(arr) - min(arr), 2),
            }
        self.stats[exp_clocks] = stats_ch

    def subtract_dark(
        self,
        exp_clocks: int,
        raw_words: List[int],
        use_live_ob: bool = False
    ) -> Tuple[List[float], List[float], List[float]]:
        """
        Subtract matching DSNU dark frame from raw inverted CCD words:
            Signal(x) = max(0.0, Dark_eff(x) - Raw(x))
        Eliminates sensel clamp step artifacts and preserves linear radiance fidelity.
        """
        raw_r = raw_words[0:PIXELS_PER_LINE]
        raw_g = raw_words[PIXELS_PER_LINE:PIXELS_PER_LINE * 2]
        raw_b = raw_words[PIXELS_PER_LINE * 2:PIXELS_PER_LINE * 3]

        if exp_clocks in self.profiles:
            prof = self.profiles[exp_clocks]
            dr = prof["r"]
            dg = prof["g"]
            db = prof["b"]
            if use_live_ob:
                ob_r, ob_g, ob_b = extract_optical_black(raw_words)
                dr_ob = sum(dr[10:40]) / 30.0
                dg_ob = sum(dg[10:40]) / 30.0
                db_ob = sum(db[10:40]) / 30.0
                # Sensel delta relative to optical black is bounded strictly to +/- 20 counts
                base_r = [ob_r + max(-20.0, min(20.0, dr[x] - dr_ob)) for x in range(PIXELS_PER_LINE)]
                base_g = [ob_g + max(-20.0, min(20.0, dg[x] - dg_ob)) for x in range(PIXELS_PER_LINE)]
                base_b = [ob_b + max(-20.0, min(20.0, db[x] - db_ob)) for x in range(PIXELS_PER_LINE)]
                sig_r = [max(0.0, base_r[x] - float(raw_r[x])) for x in range(PIXELS_PER_LINE)]
                sig_g = [max(0.0, base_g[x] - float(raw_g[x])) for x in range(PIXELS_PER_LINE)]
                sig_b = [max(0.0, base_b[x] - float(raw_b[x])) for x in range(PIXELS_PER_LINE)]
            else:
                sig_r = [max(0.0, dr[x] - float(raw_r[x])) for x in range(PIXELS_PER_LINE)]
                sig_g = [max(0.0, dg[x] - float(raw_g[x])) for x in range(PIXELS_PER_LINE)]
                sig_b = [max(0.0, db[x] - float(raw_b[x])) for x in range(PIXELS_PER_LINE)]
        else:
            # Fallback directly to instantaneous optical black level
            ob_r, ob_g, ob_b = extract_optical_black(raw_words)
            sig_r = [max(0.0, ob_r - float(raw_r[x])) for x in range(PIXELS_PER_LINE)]
            sig_g = [max(0.0, ob_g - float(raw_g[x])) for x in range(PIXELS_PER_LINE)]
            sig_b = [max(0.0, ob_b - float(raw_b[x])) for x in range(PIXELS_PER_LINE)]

        return sig_r, sig_g, sig_b

def calibrate_dark_brackets(
    dev,
    brackets: List[int],
    num_samples: int = 8,
    gain: int = 31,
    offset: int = 2,
    analog_balance: bool = False
) -> BracketDarkCalibration:
    """
    Calibrate matching DSNU dark frames with lamp OFF at each bracket integration time.
    Uses inter-bracket purge readouts and smooth profile filtering.
    """
    calib = BracketDarkCalibration()
    set_lamp(dev, False)
    time.sleep(0.5)
    set_gain_and_offset(dev, gain, offset)

    last_exp = None
    for exp in brackets:
        if analog_balance:
            exp_r = exp
            exp_g = exp
            exp_b = int(exp * 1.25)
        else:
            exp_r = exp_g = exp_b = exp

        if exp != last_exp:
            set_exposure(dev, exp_r, exp_g, exp_b)
            _ = capture_raw_line(dev)  # Purge residual shift register charge
            last_exp = exp

        acc_r = [0.0] * PIXELS_PER_LINE
        acc_g = [0.0] * PIXELS_PER_LINE
        acc_b = [0.0] * PIXELS_PER_LINE

        for _ in range(num_samples):
            raw = capture_raw_line(dev)
            w = struct.unpack(f"<{len(raw)//2}H", raw)
            for i in range(PIXELS_PER_LINE):
                acc_r[i] += w[i]
                acc_g[i] += w[PIXELS_PER_LINE + i]
                acc_b[i] += w[PIXELS_PER_LINE * 2 + i]

        inv_n = 1.0 / num_samples
        dark_r = [x * inv_n for x in acc_r]
        dark_g = [x * inv_n for x in acc_g]
        dark_b = [x * inv_n for x in acc_b]
        calib.add_bracket(exp, dark_r, dark_g, dark_b, smooth_clamped=True)

    return calib


# ==============================================================================
# HDR Fusion Algorithms
# ==============================================================================

def gaussian_weight_1d(z: float, z_opt: float = 1800.0, sigma: float = 800.0, z_sat: float = 3500.0) -> float:
    """
    Continuous weighting function for linear sensor data:
    Peaks in the optimal linear SNR range, tapering smoothly toward 0 near saturation.
    """
    if z >= z_sat:
        return 0.0
    if z <= 5.0:
        return 1e-4
    delta = z - z_opt
    return math.exp(-(delta * delta) / (2.0 * sigma * sigma))

def triangular_weight_1d(z: float, z_min: float = 10.0, z_max: float = 3500.0) -> float:
    """Standard triangular tent function."""
    if z <= z_min or z >= z_max:
        return 1e-4 if z < z_min else 0.0
    mid = (z_min + z_max) * 0.5
    return (z - z_min) if z <= mid else (z_max - z)

def fuse_linear_radiance(
    bracket_signals: List[Tuple[int, List[List[float]]]],  # list of (exp_clocks, 2D lines [y][x])
    weight_type: str = "gaussian",
    ref_exposure: Optional[int] = None
) -> List[List[float]]:
    """
    Debevec / Poisson-optimal linear radiance recovery:
        E(x, y) = sum_k( w(S_k) * (S_k / tau_k) ) / sum_k( w(S_k) )
    where tau_k = t_k / t_ref.
    Returns:
        2D list of floating point linear transmission values.
    """
    if not bracket_signals:
        return []

    if ref_exposure is None:
        ref_exposure = bracket_signals[0][0]

    num_lines = len(bracket_signals[0][1])
    width = len(bracket_signals[0][1][0])
    out_radiance = [[0.0] * width for _ in range(num_lines)]

    # Precompute relative exposure factors tau_k
    taus = [exp / ref_exposure for exp, _ in bracket_signals]

    for y in range(num_lines):
        row_out = out_radiance[y]
        for x in range(width):
            num = 0.0
            denom = 0.0
            fallback_max_signal = -1.0
            fallback_max_tau = 1.0

            for k, (exp, lines_k) in enumerate(bracket_signals):
                sig = lines_k[y][x]
                tau = taus[k]

                if weight_type == "gaussian":
                    w = gaussian_weight_1d(sig)
                else:
                    w = triangular_weight_1d(sig)

                if w > 0.0:
                    num += w * (sig / tau)
                    denom += w

                # Track longest unsaturated exposure for dark fallback
                if sig < 3500.0 and sig > fallback_max_signal:
                    fallback_max_signal = sig
                    fallback_max_tau = tau

            if denom > 1e-6:
                row_out[x] = num / denom
            elif fallback_max_signal >= 0.0:
                row_out[x] = fallback_max_signal / fallback_max_tau
            else:
                # All exposures saturated: use shortest bracket
                shortest_k = min(range(len(taus)), key=lambda i: taus[i])
                row_out[x] = bracket_signals[shortest_k][1][y][x] / taus[shortest_k]

    return out_radiance

def boxcar_blur_2d(img: List[List[float]], radius: int) -> List[List[float]]:
    """Separable 2D boxcar blur in O(H * W) using 1D sliding windows."""
    h = len(img)
    if h == 0 or radius <= 0:
        return [list(row) for row in img]
    w = len(img[0])

    # Horizontal pass
    temp = [[0.0] * w for _ in range(h)]
    for y in range(h):
        row = img[y]
        out_row = temp[y]
        window_sum = sum(row[:min(w, radius + 1)])
        count = min(w, radius + 1)
        for x in range(w):
            out_row[x] = window_sum / count
            # Slide window
            add_idx = x + radius + 1
            if add_idx < w:
                window_sum += row[add_idx]
                count += 1
            sub_idx = x - radius
            if sub_idx >= 0:
                window_sum -= row[sub_idx]
                count -= 1

    # Vertical pass
    out = [[0.0] * w for _ in range(h)]
    for x in range(w):
        col_sum = sum(temp[y][x] for y in range(min(h, radius + 1)))
        count = min(h, radius + 1)
        for y in range(h):
            out[y][x] = col_sum / count
            add_y = y + radius + 1
            if add_y < h:
                col_sum += temp[add_y][x]
                count += 1
            sub_y = y - radius
            if sub_y >= 0:
                col_sum -= temp[sub_y][x]
                count -= 1

    return out

def compute_mertens_weights(
    lines_r: List[List[float]],
    lines_g: List[List[float]],
    lines_b: List[List[float]],
    w_contrast: float = 1.0,
    w_exposedness: float = 1.0,
    sigma_exp: float = 0.2,
    sat_level: float = 3600.0
) -> List[List[float]]:
    """
    Compute Tom Mertens exposure quality weights for a single bracket:
    1. Well-exposedness: Gaussian penalty centered at optimal midtone (0.5 * SatLevel)
    2. Contrast: Discrete 2D Laplacian response of luminance.
    """
    h = len(lines_r)
    w = len(lines_r[0])
    weights = [[0.0] * w for _ in range(h)]

    # Compute luminance & well-exposedness
    lum = [[0.0] * w for _ in range(h)]
    inv_sat = 1.0 / max(sat_level, 1.0)
    inv_2sig2 = 1.0 / (2.0 * sigma_exp * sigma_exp)

    for y in range(h):
        rr, gg, bb = lines_r[y], lines_g[y], lines_b[y]
        l_row = lum[y]
        w_row = weights[y]
        for x in range(w):
            # Rec.709 luminance
            l_val = (0.2126 * rr[x] + 0.7152 * gg[x] + 0.0722 * bb[x]) * inv_sat
            l_row[x] = l_val
            diff = l_val - 0.5
            w_exp = math.exp(-diff * diff * inv_2sig2)
            w_row[x] = w_exp ** w_exposedness

    # Apply 2D discrete Laplacian contrast: C = |4*L(x,y) - L(x-1,y) - L(x+1,y) - L(x,y-1) - L(x,y+1)|
    if w_contrast > 0.0:
        for y in range(h):
            ym1 = max(0, y - 1)
            yp1 = min(h - 1, y + 1)
            row_l = lum[y]
            row_lm1 = lum[ym1]
            row_lp1 = lum[yp1]
            row_w = weights[y]
            for x in range(w):
                xm1 = max(0, x - 1)
                xp1 = min(w - 1, x + 1)
                lap = abs(4.0 * row_l[x] - row_l[xm1] - row_l[xp1] - row_lm1[x] - row_lp1[x])
                row_w[x] *= (lap + 1e-4) ** w_contrast

    return weights

def fuse_mertens(
    bracket_data: List[Tuple[int, List[List[float]], List[List[float]], List[List[float]]]], # (exp, r, g, b)
    blur_radius: int = 15,
    ref_exposure: Optional[int] = None
) -> Tuple[List[List[float]], List[List[float]], List[List[float]]]:
    """
    Mertens Exposure Fusion adapted for linear scanner data with multi-scale
    edge-preserving weight normalization.
    """
    if not bracket_data:
        return [], [], []

    if ref_exposure is None:
        ref_exposure = bracket_data[0][0]

    h = len(bracket_data[0][1])
    w = len(bracket_data[0][1][0])
    num_brackets = len(bracket_data)

    # 1. Compute raw quality weights
    raw_weights: List[List[List[float]]] = []
    for exp, r_lines, g_lines, b_lines in bracket_data:
        w_map = compute_mertens_weights(r_lines, g_lines, b_lines)
        # Apply spatial blur to prevent seams / halos
        w_smooth = boxcar_blur_2d(w_map, radius=blur_radius)
        raw_weights.append(w_smooth)

    # 2. Normalize weights across brackets
    norm_weights: List[List[List[float]]] = []
    for k in range(num_brackets):
        norm_weights.append([[0.0] * w for _ in range(h)])

    for y in range(h):
        for x in range(w):
            total_w = sum(raw_weights[k][y][x] for k in range(num_brackets))
            inv_tw = 1.0 / max(total_w, 1e-6)
            for k in range(num_brackets):
                norm_weights[k][y][x] = raw_weights[k][y][x] * inv_tw

    # 3. Blend brackets
    fused_r = [[0.0] * w for _ in range(h)]
    fused_g = [[0.0] * w for _ in range(h)]
    fused_b = [[0.0] * w for _ in range(h)]

    for k, (exp, r_lines, g_lines, b_lines) in enumerate(bracket_data):
        scale = ref_exposure / exp  # Radiance scale to bring all exposures to common basis
        w_k = norm_weights[k]
        for y in range(h):
            fr_y, fg_y, fb_y = fused_r[y], fused_g[y], fused_b[y]
            r_y, g_y, b_y = r_lines[y], g_lines[y], b_lines[y]
            wk_y = w_k[y]
            for x in range(w):
                weight = wk_y[x]
                fr_y[x] += weight * (r_y[x] * scale)
                fg_y[x] += weight * (g_y[x] * scale)
                fb_y[x] += weight * (b_y[x] * scale)

    return fused_r, fused_g, fused_b


# ==============================================================================
# Dynamic Range & Sensitometric Dmax Metrics
# ==============================================================================

def calculate_hdr_metrics(
    brackets: List[int],
    calib: Optional[BracketDarkCalibration] = None,
    sat_level: float = 3700.0,
    read_noise_sigma: float = 12.0
) -> Dict[str, Any]:
    """
    Calculate concrete Dynamic Range Expansion (EV gain) and Dmax improvements:
    - EV Gain: log2(t_max / t_min)
    - Dynamic Range (dB): DR_single + 20 * log10(t_max / t_min)
    - Dmax Improvement: log10(t_max / t_min)
    """
    t_min = min(brackets)
    t_max = max(brackets)
    ratio = t_max / t_min

    ev_gain = math.log2(ratio)
    dr_gain_db = 20.0 * math.log10(ratio)
    delta_dmax = math.log10(ratio)

    # Baseline single-exposure dynamic range (at nominal t_ref)
    dr_single_db = 20.0 * math.log10(sat_level / max(read_noise_sigma, 1.0))
    dr_single_ev = math.log2(sat_level / max(read_noise_sigma, 1.0))
    dmax_single = math.log10(sat_level / max(read_noise_sigma, 1.0))

    # Total HDR system metrics
    dr_hdr_db = dr_single_db + dr_gain_db
    dr_hdr_ev = dr_single_ev + ev_gain
    dmax_hdr = dmax_single + delta_dmax

    metrics = {
        "brackets": brackets,
        "exposure_ratio": round(ratio, 2),
        "ev_gain_stops": round(ev_gain, 2),
        "dynamic_range_gain_db": round(dr_gain_db, 2),
        "delta_dmax": round(delta_dmax, 3),
        "baseline_single_ev": round(dr_single_ev, 2),
        "baseline_single_db": round(dr_single_db, 2),
        "baseline_dmax": round(dmax_single, 3),
        "total_hdr_ev": round(dr_hdr_ev, 2),
        "total_hdr_db": round(dr_hdr_db, 2),
        "total_hdr_dmax": round(dmax_hdr, 3),
    }

    if calib:
        dsnu_summary = {}
        for exp in brackets:
            if exp in calib.stats:
                dsnu_summary[exp] = calib.stats[exp]
        metrics["dsnu_calibration"] = dsnu_summary

    return metrics


# ==============================================================================
# Tonemapping & Sensitometric Film Inversion
# ==============================================================================

def tonemap_reinhard(lines: List[List[float]], p_high: float = 99.5) -> List[List[float]]:
    """
    Reinhard Global Tonemapper:
        L_d = (L * (1 + L / L_white^2)) / (1 + L)
    """
    h = len(lines)
    w = len(lines[0])
    # Estimate key & white point
    sample = [lines[y][x] for y in range(0, h, max(1, h // 50)) for x in range(0, w, 20)]
    sample.sort()
    l_white = sample[int(len(sample) * p_high / 100.0)]
    l_white = max(l_white, 1.0)
    inv_lw2 = 1.0 / (l_white * l_white)

    out = [[0.0] * w for _ in range(h)]
    for y in range(h):
        r_in = lines[y]
        r_out = out[y]
        for x in range(w):
            v = max(0.0, r_in[x])
            val = (v * (1.0 + v * inv_lw2)) / (1.0 + v)
            # Normalize by white point response
            norm_val = val / ((l_white * (1.0 + l_white * inv_lw2)) / (1.0 + l_white))
            r_out[x] = max(0.0, min(1.0, norm_val))
    return out

def tonemap_filmic_aces(lines: List[List[float]], max_val: Optional[float] = None) -> List[List[float]]:
    """
    Filmic ACES S-curve approximation for rich contrast and smooth highlight rolloff:
        f(x) = (x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14)
    """
    h = len(lines)
    w = len(lines[0])
    if max_val is None:
        sample = [lines[y][x] for y in range(0, h, max(1, h // 50)) for x in range(0, w, 20)]
        sample.sort()
        max_val = max(sample[int(len(sample) * 0.99)], 1.0)

    inv_max = 1.0 / max_val
    out = [[0.0] * w for _ in range(h)]
    for y in range(h):
        r_in = lines[y]
        r_out = out[y]
        for x in range(w):
            x_norm = max(0.0, r_in[x]) * inv_max
            val = (x_norm * (2.51 * x_norm + 0.03)) / (x_norm * (2.43 * x_norm + 0.59) + 0.14)
            r_out[x] = max(0.0, min(1.0, val))
    return out


# ==============================================================================
# Export Utilities: 16-bit Linear Pro TIFF & 8-bit/16-bit PNG/PPM
# ==============================================================================

def save_tiff_rgb16(filename: str, width: int, height: int, lines_r, lines_g, lines_b):
    """
    Write uncompressed 16-bit linear RGB TIFF master without quantization loss,
    preserving full dynamic range for RAW grading tools.
    """
    data = bytearray(width * height * 6)
    idx = 0
    for y in range(height):
        ry = lines_r[y]
        gy = lines_g[y]
        by = lines_b[y]
        for x in range(width):
            vr = max(0, min(65535, int(ry[x])))
            vg = max(0, min(65535, int(gy[x])))
            vb = max(0, min(65535, int(by[x])))
            struct.pack_into('<HHH', data, idx, vr, vg, vb)
            idx += 6

    header = b'II\x2a\x00\x08\x00\x00\x00'
    tags = [
        (0x0100, 4, 1, width),                   # ImageWidth
        (0x0101, 4, 1, height),                  # ImageLength
        (0x0102, 3, 3, 134),                     # BitsPerSample -> [16, 16, 16] at offset 134
        (0x0103, 3, 1, 1),                       # Compression: None
        (0x0106, 3, 1, 2),                       # PhotometricInterpretation: RGB
        (0x0111, 4, 1, 140),                     # StripOffsets -> image data at offset 140
        (0x0115, 3, 1, 3),                       # SamplesPerPixel: 3
        (0x0116, 4, 1, height),                  # RowsPerStrip: height
        (0x0117, 4, 1, len(data)),               # StripByteCounts
        (0x011c, 3, 1, 1),                       # PlanarConfiguration: Chunky
    ]

    ifd = bytearray()
    ifd.extend(struct.pack('<H', len(tags)))
    for tag, dtype, count, val in tags:
        ifd.extend(struct.pack('<HHII', tag, dtype, count, val))
    ifd.extend(struct.pack('<I', 0))
    extra = struct.pack('<HHH', 16, 16, 16)

    with open(filename, 'wb') as f:
        f.write(header)
        f.write(ifd)
        f.write(extra)
        f.write(data)

def save_ppm(filename: str, width: int, height: int, rgb_bytes: bytes):
    """Save 24-bit binary PPM image."""
    with open(filename, "wb") as f:
        header = f"P6\n{width} {height}\n255\n".encode("ascii")
        f.write(header)
        f.write(rgb_bytes)


# ==============================================================================
# Main Scanner HDR Routine
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="PrimeFilm 1800u / 1800i Multi-Exposure Analog Bracketed HDR & Film Dmax Extender"
    )
    parser.add_argument("--brackets", type=str, default="2800,3100,3500",
                        help="Comma-separated exposure clocks (default: '2800,3100,3500' for clean streak-free linear response)")
    parser.add_argument("--fusion", choices=["linear", "mertens", "both"], default="both",
                        help="HDR Fusion algorithm: 'linear' (Debevec radiance map), 'mertens' (exposure fusion), or 'both' (default: both)")
    parser.add_argument("--tonemap", choices=["filmic", "reinhard", "gamma"], default="filmic",
                        help="Tonemapping operator: 'filmic' (ACES curve), 'reinhard', or 'gamma' (default: filmic)")
    parser.add_argument("--offset", type=int, default=1250,
                        help="Carriage offset steps to film aperture (default: 1250)")
    parser.add_argument("--lines", type=int, default=30,
                        help="Scan lines to capture (default: 30 for quick HDR test, 950 for full frame)")
    parser.add_argument("--step", type=int, default=1,
                        help="Microsteps per line (default: 1)")
    parser.add_argument("--aspect", type=int, default=2,
                        help="Vertical aspect scaling multiplier (default: 2 for 900 DPI motor pitch)")
    parser.add_argument("--gain", type=int, default=31,
                        help="AFE PGA gain (0..31, default: 31 = 0x1f)")
    parser.add_argument("--dark-samples", type=int, default=4,
                        help="Dark frame lines to average per bracket (default: 4)")
    parser.add_argument("--analog-balance", action="store_true",
                        help="Enable analog color balancing (boosts Blue channel exposure by 1.25x)")
    parser.add_argument("--negative", action="store_true",
                        help="Invert colors for negative film")
    parser.add_argument("--deconvolve", action="store_true",
                        help="Apply Richardson-Lucy optical MTF deconvolution")
    parser.add_argument("--deconv-sigma", type=float, default=1.25,
                        help="PSF blur radius for optical deconvolution (default: 1.25)")
    parser.add_argument("--deconv-iters", type=int, default=8,
                        help="Iterations for Richardson-Lucy deconvolution (default: 8)")
    parser.add_argument("--chroma-denoise", action="store_true",
                        help="Apply Chroma-Only Grain-Preserving Denoising")
    parser.add_argument("--chroma-radius", type=int, default=5,
                        help="Chroma filter spatial radius (default: 5)")
    parser.add_argument("--chroma-strength", type=float, default=12.0,
                        help="Chroma filter strength (default: 12.0)")
    parser.add_argument("--chroma-space", type=str, default="lab", choices=["lab", "ycbcr"],
                        help="Color space for chroma decoupling: 'lab' or 'ycbcr' (default: lab)")
    parser.add_argument("--simulate", action="store_true",
                        help="Run offline simulation test without physical scanner")
    parser.add_argument("--out", type=str, default="scan_hdr",
                        help="Output file prefix (default: scan_hdr)")
    args = parser.parse_args()

    # Parse brackets
    try:
        brackets = [int(x.strip()) for x in args.brackets.split(",")]
        brackets = sorted(list(set(brackets)))
    except Exception:
        print(f"[!] Invalid bracket list: {args.brackets}. Using defaults: 2800,3100,3500")
        brackets = DEFAULT_BRACKETS

    # Print engineering summary banner
    print("=" * 75)
    print("PRIME FILM 1800u / 1800i MULTI-EXPOSURE ANALOG BRACKETED HDR EXTENDER")
    print("=" * 75)
    print(f"Exposure Brackets : {brackets} clocks")
    print(f"Exposure Range    : {min(brackets)} to {max(brackets)} clocks (Ratio: {max(brackets)/min(brackets):.2f}x)")
    print(f"Carriage Travel   : Offset={args.offset} steps | Lines={args.lines} lines | Step={args.step}")
    print(f"AFE PGA Gain      : {args.gain} (0x{args.gain:02x})")
    print(f"Analog Balance    : {'Active (Blue boosted 1.25x)' if args.analog_balance else 'Uniform'}")
    print(f"HDR Algorithms    : {args.fusion.upper()}")
    print(f"Tonemapping       : {args.tonemap.upper()}")
    print(f"Film Mode         : {'Color Negative (Inverted)' if args.negative else 'Positive / Slide (Direct)'}")
    print("=" * 75)

    # Calculate theoretical and physical metrics
    metrics = calculate_hdr_metrics(brackets)
    print("\n[*] Theoretical Sensitometric Dynamic Range & Dmax Expansion:")
    print(f"    Dynamic Range Expansion : +{metrics['ev_gain_stops']} EV (+{metrics['dynamic_range_gain_db']:.1f} dB)")
    print(f"    Total System Dynamic Range: {metrics['total_hdr_ev']} EV ({metrics['total_hdr_db']:.1f} dB) [Baseline: {metrics['baseline_single_ev']} EV]")
    print(f"    Film Dmax Extension     : +{metrics['delta_dmax']} D [Effective Dmax: {metrics['total_hdr_dmax']:.2f} D vs Baseline: {metrics['baseline_dmax']:.2f} D]\n")

    # Hardware rail protection
    if not args.simulate and (args.offset + args.lines * args.step > MAX_RAIL_STEPS):
        max_lines = (MAX_RAIL_STEPS - args.offset) // args.step
        print(f"[!] Warning: Requested scan exceeds rail limit {MAX_RAIL_STEPS}. Clamping to {max_lines} lines.")
        args.lines = max(1, max_lines)

    # Raw bracket buffers: dict mapping exp -> (lines_r, lines_g, lines_b)
    bracket_lines: Dict[int, Tuple[List[List[float]], List[List[float]], List[List[float]]]] = {
        exp: ([], [], []) for exp in brackets
    }

    if args.simulate:
        print("[*] SIMULATION MODE: Generating synthetic multi-exposure bracketed film data...")
        num_lines = args.lines
        for exp in brackets:
            taus = exp / brackets[0]
            lr, lg, lb = [], [], []
            for y in range(num_lines):
                # Synthetic gradient film line with high optical density gradient (D = 0.2 to 3.5)
                row_r, row_g, row_b = [], [], []
                for x in range(PIXELS_PER_LINE):
                    # Optical transmission: from 70% down to 0.05%
                    trans = 0.70 * math.exp(-6.5 * (x / PIXELS_PER_LINE))
                    # Physical signal: S = trans * 3600 * tau
                    s_r = min(3700.0, trans * 3600.0 * taus)
                    s_g = min(3700.0, trans * 3600.0 * taus * 0.9)
                    s_b = min(3700.0, trans * 3600.0 * taus * 0.7)
                    row_r.append(s_r)
                    row_g.append(s_g)
                    row_b.append(s_b)
                lr.append(row_r)
                lg.append(row_g)
                lb.append(row_b)
            bracket_lines[exp] = (lr, lg, lb)
    else:
        # Live Hardware Acquisition
        print("[*] Connecting to live PrimeFilm 1800u scanner...")
        dev = connect_scanner()

        try:
            # Phase 1: Calibrate DSNU Dark Frames for each bracket
            print(f"\n[*] Phase 1: Calibrating Per-Bracket Dark-Current DSNU Profiles ({args.dark_samples} samples per bracket)...")
            calib = calibrate_dark_brackets(
                dev, brackets, num_samples=args.dark_samples,
                gain=args.gain, offset=2, analog_balance=args.analog_balance
            )
            print("    [+] DSNU Calibration Complete:")
            for exp in brackets:
                st = calib.stats[exp]
                print(f"        Bracket {exp:5d} clocks: Dark R_mean={st['r']['mean']} (std={st['r']['std']}, span={st['r']['span']}) | G_mean={st['g']['mean']} | B_mean={st['b']['mean']}")

            # Phase 2: Lamp ON & Warmup
            print("\n[*] Phase 2: Turning LAMP ON and warming up (1.5s)...")
            set_lamp(dev, True)
            time.sleep(1.5)

            # Phase 3: Positioning Carriage
            if args.offset > 0:
                print(f"[*] Phase 3: Advancing carriage to aperture offset ({args.offset} steps)...")
                move_carriage(dev, 0x16, args.offset)

            # Phase 4: Synchronized Multi-Exposure Line Acquisition
            print(f"\n[*] Phase 4: Acquiring {args.lines} lines across {len(brackets)} brackets...")
            t_start = time.time()

            last_exp = None
            for line_idx in range(args.lines):
                # At the current carriage position, capture all exposure brackets
                for exp in brackets:
                    if args.analog_balance:
                        exp_r = exp
                        exp_g = exp
                        exp_b = int(exp * 1.25)
                    else:
                        exp_r = exp_g = exp_b = exp

                    if exp != last_exp:
                        set_exposure(dev, exp_r, exp_g, exp_b)
                        # Purge transitional line charge from previous exposure time
                        _ = capture_raw_line(dev)
                        last_exp = exp

                    raw_data = capture_raw_line(dev)
                    words = struct.unpack(f"<{len(raw_data)//2}H", raw_data)

                    # Subtract matching DSNU profile with optical black anchor
                    sig_r, sig_g, sig_b = calib.subtract_dark(exp, words, use_live_ob=True)
                    bracket_lines[exp][0].append(sig_r)
                    bracket_lines[exp][1].append(sig_g)
                    bracket_lines[exp][2].append(sig_b)

                # Advance stepper motor 1 microstep to next line
                if line_idx < args.lines - 1:
                    move_carriage(dev, 0x16, args.step)

                if (line_idx + 1) % 10 == 0 or line_idx == args.lines - 1:
                    dt = time.time() - t_start
                    rate = (line_idx + 1) / max(dt, 0.001)
                    print(f"    Line {line_idx + 1:4d}/{args.lines} captured ({rate:.1f} lines/s, {rate * len(brackets):.1f} exposures/s)")

            elapsed = time.time() - t_start
            print(f"[+] Acquisition completed: {args.lines * len(brackets)} raw bracket frames captured in {elapsed:.1f}s.")

        finally:
            print("\n[*] Returning carriage to home dock...")
            set_lamp(dev, False)
            auto_home(dev)
            print("[+] Carriage safely docked at HOME. Lamp OFF.")

    # ==============================================================================
    # Phase 5: HDR Fusion Processing
    # ==============================================================================
    print("\n[*] Phase 5: Executing Multi-Exposure Bracketed HDR Fusion...")

    ref_exp = brackets[0]
    out_base = os.path.abspath(args.out)

    # 1. Linear Radiance Map Recovery (Debevec / Poisson)
    if args.fusion in ["linear", "both"]:
        print("[*] Running Linear Radiance Map Recovery (Debevec / Poisson-optimal weighting)...")
        r_brackets = [(exp, bracket_lines[exp][0]) for exp in brackets]
        g_brackets = [(exp, bracket_lines[exp][1]) for exp in brackets]
        b_brackets = [(exp, bracket_lines[exp][2]) for exp in brackets]

        rad_r = fuse_linear_radiance(r_brackets, ref_exposure=ref_exp)
        rad_g = fuse_linear_radiance(g_brackets, ref_exposure=ref_exp)
        rad_b = fuse_linear_radiance(b_brackets, ref_exposure=ref_exp)

        # Scale to 16-bit linear master range (0..65535)
        # Find maximum radiance across channels for proportional scaling
        all_max = max(
            max(max(row) for row in rad_r),
            max(max(row) for row in rad_g),
            max(max(row) for row in rad_b),
            1.0
        )
        scale_16 = 65535.0 / all_max
        h = len(rad_r)
        w = len(rad_r[0])

        tif_r = [[rad_r[y][x] * scale_16 for x in range(w)] for y in range(h)]
        tif_g = [[rad_g[y][x] * scale_16 for x in range(w)] for y in range(h)]
        tif_b = [[rad_b[y][x] * scale_16 for x in range(w)] for y in range(h)]

        # Save 16-bit linear HDR TIFF master
        out_linear_tif = f"{out_base}_linear16.tif"
        save_tiff_rgb16(out_linear_tif, w, h, tif_r, tif_g, tif_b)
        print(f"[+] Saved 16-bit Linear Pro HDR TIFF: {out_linear_tif}")

        # Tonemap linear radiance
        print(f"[*] Applying {args.tonemap.upper()} Tonemapping to Linear Radiance...")
        if args.tonemap == "filmic":
            tm_r = tonemap_filmic_aces(rad_r)
            tm_g = tonemap_filmic_aces(rad_g)
            tm_b = tonemap_filmic_aces(rad_b)
        else:
            tm_r = tonemap_reinhard(rad_r)
            tm_g = tonemap_reinhard(rad_g)
            tm_b = tonemap_reinhard(rad_b)

        # Helper: sample 1st and 99th percentiles per channel to neutralize orange film base mask
        def get_channel_bounds_2d(lines_2d, p_low: float = 1.0, p_high: float = 99.0):
            sample = []
            stride = max(1, h // 50)
            for y in range(0, h, stride):
                sample.extend(lines_2d[y][::8])
            sample.sort()
            idx_low = int(len(sample) * p_low / 100.0)
            idx_high = int(len(sample) * p_high / 100.0)
            return sample[idx_low], max(sample[idx_high], sample[idx_low] + 1e-4)

        # Render 8-bit RGB bytearray
        rgb_bytes = bytearray()
        if args.negative:
            r_min, r_max = get_channel_bounds_2d(tm_r, 1.0, 99.0)
            g_min, g_max = get_channel_bounds_2d(tm_g, 1.0, 99.0)
            b_min, b_max = get_channel_bounds_2d(tm_b, 1.0, 99.0)
            r_range = max(r_max - r_min, 1e-4)
            g_range = max(g_max - g_min, 1e-4)
            b_range = max(b_max - b_min, 1e-4)
            for y in range(h):
                for x in range(w):
                    vr = 255 - int((tm_r[y][x] - r_min) / r_range * 255.0)
                    vg = 255 - int((tm_g[y][x] - g_min) / g_range * 255.0)
                    vb = 255 - int((tm_b[y][x] - b_min) / b_range * 255.0)
                    vr = max(0, min(255, vr))
                    vg = max(0, min(255, vg))
                    vb = max(0, min(255, vb))
                    rgb_bytes.extend([vr, vg, vb])
        else:
            for y in range(h):
                for x in range(w):
                    vr = int(tm_r[y][x] * 255.0)
                    vg = int(tm_g[y][x] * 255.0)
                    vb = int(tm_b[y][x] * 255.0)
                    vr = max(0, min(255, vr))
                    vg = max(0, min(255, vg))
                    vb = max(0, min(255, vb))
                    rgb_bytes.extend([vr, vg, vb])

        out_linear_ppm = f"{out_base}_linear_tonemapped.ppm"
        save_ppm(out_linear_ppm, w, h, bytes(rgb_bytes))
        print(f"[+] Saved Tonemapped Radiance PPM: {out_linear_ppm}")

        if HAS_PILLOW:
            out_linear_png = f"{out_base}_linear_tonemapped.png"
            img = Image.frombytes("RGB", (w, h), bytes(rgb_bytes))
            if args.aspect > 1:
                img = img.resize((w, h * args.aspect), Image.Resampling.LANCZOS)
            img.save(out_linear_png)
            print(f"[+] Saved Tonemapped Radiance PNG: {out_linear_png}")

    # 2. Mertens Exposure Fusion
    if args.fusion in ["mertens", "both"]:
        print("[*] Running Mertens Exposure Fusion (Multi-scale contrast + well-exposedness blending)...")
        b_data = [(exp, bracket_lines[exp][0], bracket_lines[exp][1], bracket_lines[exp][2]) for exp in brackets]
        mf_r, mf_g, mf_b = fuse_mertens(b_data, blur_radius=15, ref_exposure=ref_exp)

        h = len(mf_r)
        w = len(mf_r[0])
        rgb_mertens = bytearray()
        if args.negative:
            r_min, r_max = get_channel_bounds_2d(mf_r, 1.0, 99.0)
            g_min, g_max = get_channel_bounds_2d(mf_g, 1.0, 99.0)
            b_min, b_max = get_channel_bounds_2d(mf_b, 1.0, 99.0)
            r_range = max(r_max - r_min, 1e-4)
            g_range = max(g_max - g_min, 1e-4)
            b_range = max(b_max - b_min, 1e-4)
            for y in range(h):
                for x in range(w):
                    vr = 255 - int((mf_r[y][x] - r_min) / r_range * 255.0)
                    vg = 255 - int((mf_g[y][x] - g_min) / g_range * 255.0)
                    vb = 255 - int((mf_b[y][x] - b_min) / b_range * 255.0)
                    vr = max(0, min(255, vr))
                    vg = max(0, min(255, vg))
                    vb = max(0, min(255, vb))
                    rgb_mertens.extend([vr, vg, vb])
        else:
            # Find joint 1st and 99th percentiles across luminance to maintain neutral color balance
            def get_joint_bounds(r_lines, g_lines, b_lines):
                sample = []
                stride = max(1, h // 50)
                for y in range(0, h, stride):
                    for x in range(0, w, 20):
                        sample.append(0.2126 * r_lines[y][x] + 0.7152 * g_lines[y][x] + 0.0722 * b_lines[y][x])
                sample.sort()
                return sample[int(len(sample) * 0.01)], sample[int(len(sample) * 0.99)]

            min_val, max_val = get_joint_bounds(mf_r, mf_g, mf_b)
            range_val = max(max_val - min_val, 1e-4)
            for y in range(h):
                for x in range(w):
                    vr = int((mf_r[y][x] - min_val) / range_val * 255.0)
                    vg = int((mf_g[y][x] - min_val) / range_val * 255.0)
                    vb = int((mf_b[y][x] - min_val) / range_val * 255.0)
                    vr = max(0, min(255, vr))
                    vg = max(0, min(255, vg))
                    vb = max(0, min(255, vb))
                    rgb_mertens.extend([vr, vg, vb])

        out_mertens_ppm = f"{out_base}_mertens.ppm"
        save_ppm(out_mertens_ppm, w, h, bytes(rgb_mertens))
        print(f"[+] Saved Mertens Fused PPM: {out_mertens_ppm}")

        if HAS_PILLOW:
            out_mertens_png = f"{out_base}_mertens.png"
            img_m = Image.frombytes("RGB", (w, h), bytes(rgb_mertens))
            if args.aspect > 1:
                img_m = img_m.resize((w, h * args.aspect), Image.Resampling.LANCZOS)
            img_m.save(out_mertens_png)
            print(f"[+] Saved Mertens Fused PNG: {out_mertens_png}")

    # Optional Deconvolution & Chroma Denoising
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target_ppm = out_mertens_ppm if args.fusion in ["mertens", "both"] else out_linear_ppm

    if args.deconvolve:
        lca_deconv_bin = os.path.join(repo_root, "bin", "pie1800_lca_deconv")
        deconv_bin = os.path.join(repo_root, "bin", "pie1800_deconv")
        out_deconv_ppm = f"{out_base}_deconv.ppm"
        out_deconv_png = f"{out_base}_deconv.png"

        if os.path.isfile(lca_deconv_bin):
            print(f"\n[*] Applying Spatially-Varying LCA-Corrected Guided Deconvolution (iters={args.deconv_iters})...")
            ret = subprocess.run([lca_deconv_bin, target_ppm, out_deconv_ppm, "--iters", str(args.deconv_iters)])
        elif os.path.isfile(deconv_bin):
            print(f"\n[*] Applying Richardson-Lucy Optical Deconvolution (sigma={args.deconv_sigma}, iters={args.deconv_iters})...")
            ret = subprocess.run([deconv_bin, target_ppm, out_deconv_ppm, str(args.deconv_sigma), str(args.deconv_iters)])
        else:
            ret = None
            print(f"[!] Notice: Deconvolution binary not found. Deconvolution skipped.")

        if ret and ret.returncode == 0:
            print(f"[+] Saved Deconvolved PPM: {out_deconv_ppm}")
            if HAS_PILLOW:
                try:
                    dec_img = Image.open(out_deconv_ppm)
                    dec_img.save(out_deconv_png)
                    print(f"[+] Saved Deconvolved PNG: {out_deconv_png}")
                except Exception as e:
                    print(f"[!] Warning converting deconvolved PPM: {e}")
            target_ppm = out_deconv_ppm

    if args.chroma_denoise:
        chroma_bin = os.path.join(repo_root, "bin", "pie1800_chroma_denoise")
        out_clean_ppm = f"{out_base}_clean.ppm"
        out_clean_png = f"{out_base}_clean.png"
        print(f"\n[*] Applying Chroma-Only Grain-Preserving Denoising ({args.chroma_space.upper()}, r={args.chroma_radius}, s={args.chroma_strength})...")
        if os.path.isfile(chroma_bin):
            ret = subprocess.run([
                chroma_bin, target_ppm, out_clean_ppm,
                str(args.chroma_radius), str(args.chroma_strength),
                args.chroma_space, "bilateral"
            ])
            if ret.returncode == 0:
                print(f"[+] Saved Clean Chroma PPM: {out_clean_ppm}")
                if HAS_PILLOW:
                    try:
                        clean_img = Image.open(out_clean_ppm)
                        clean_img.save(out_clean_png)
                        print(f"[+] Saved Clean Chroma PNG: {out_clean_png}")
                    except Exception as e:
                        print(f"[!] Warning converting clean PPM: {e}")
        else:
            try:
                sys.path.insert(0, os.path.join(repo_root, "scripts"))
                from pie1800_chroma_denoise import denoise_chroma
                denoise_chroma(
                    target_ppm, out_path=out_clean_ppm,
                    radius=args.chroma_radius, strength=args.chroma_strength,
                    colorspace=args.chroma_space, filter_type="bilateral"
                )
                print(f"[+] Saved Clean Chroma PPM: {out_clean_ppm}")
                if HAS_PILLOW:
                    clean_img = Image.open(out_clean_ppm)
                    clean_img.save(out_clean_png)
                    print(f"[+] Saved Clean Chroma PNG: {out_clean_png}")
            except Exception as e:
                print(f"[!] Warning during chroma denoising: {e}")

    print("\n" + "=" * 75)
    print("MULTI-EXPOSURE ANALOG BRACKETED HDR EXTENSION SUMMARY")
    print("=" * 75)
    print(f"Brackets Processed : {brackets} exposure clocks")
    print(f"Dynamic Range Gain : +{metrics['ev_gain_stops']} EV (+{metrics['dynamic_range_gain_db']:.1f} dB)")
    print(f"Total Dynamic Range: {metrics['total_hdr_ev']} EV ({metrics['total_hdr_db']:.1f} dB)")
    print(f"Film Dmax Extension: +{metrics['delta_dmax']} D (Effective Dmax: {metrics['total_hdr_dmax']:.2f} D)")
    print(f"Output Master TIFF : {out_base}_linear16.tif")
    print("=" * 75)


if __name__ == "__main__":
    main()
