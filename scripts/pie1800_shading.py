#!/usr/bin/env python3
"""
PrimeFilm 1800u / 1800i Flat-Field Shading Calibration Module (pie1800_shading.py)
Photo-Response Non-Uniformity (PRNU) & Dark Current (DSNU) Correction.

Calibration Equation:
    I_calibrated(x, y) = (I_raw(x, y) - D(x)) / (W_eff(x) - D(x)) * TargetWhite
    or
    I_calibrated(x, y) = (I_raw(x, y) - D(x)) * C(x)
where:
    D(x) is the per-pixel dark reference (lamp OFF, DSNU subtraction).
    W(x) is the per-pixel white reference (lamp ON, carriage at clear aperture).
    W_eff(x) is the smoothed/filtered white reference preserving true PRNU & dust lines
             while suppressing temporal shot noise amplification.
    C(x) is the per-channel normalized gain correction curve.
"""

import sys
import os
import time
import math
import struct
import json
import argparse
from typing import Tuple, List, Dict, Any, Optional, Union

# Optional dependencies
try:
    import usb.core
    import usb.util
    HAS_USB = True
except ImportError:
    HAS_USB = False

try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

# Scanner Constants
VENDOR_ID = 0x05e3
PRODUCT_ID = 0x0120
EP_IN = 0x81
FULL_LINE_BYTES = 16200  # 2,700 pixels * 3 channels * 2 bytes uint16
PIXELS_PER_LINE = 2700
WORDS_PER_LINE = 8100
MAX_RAIL_STEPS = 4800
SAFE_DOCK_STEP_MAX = 200  # Calibration dock range: 0..200 (well before film aperture at 1250)
MAGIC_HEADER = b"PF1800FF\x01\x00"


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

def wait_idle(dev, timeout: float = 5.0) -> bool:
    """Poll ASIC status register 0x84 until scan and motor bits are idle."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        val = asic_read(dev, 0x84)
        if val is not None and (val & 0x1e) == 0:
            return True
        time.sleep(0.002)
    return False

def configure_hardware(dev):
    """Configure default GL640USB ASIC registers for optical scanning."""
    asic_write(dev, 0xc4, 0x00)
    asic_write(dev, 0xab, 0xaa)
    asic_write(dev, 0xac, 0xca)
    asic_write(dev, 0xad, 0x4b)  # Default lamp off
    asic_write(dev, 0xae, 0x05)
    asic_write(dev, 0xc1, 0x07)
    asic_write(dev, 0xc2, 0x04)
    asic_write(dev, 0xc3, 0x12)
    asic_write(dev, 0xc5, 0x12)
    asic_write(dev, 0xe1, 0x00)
    asic_write(dev, 0xe5, 0x00)
    asic_write(dev, 0xe9, 0x00)
    asic_write(dev, 0x86, 0x10)

def set_exposure_limits(dev):
    """Set window exposure limits."""
    asic_read(dev, 0x87)
    for r in range(0xa2, 0xab):
        asic_write(dev, r, 0xff)

def set_exposure(dev, exp_r: int, exp_g: int, exp_b: int):
    """Set integration time clocks per channel."""
    asic_write(dev, 0x9c, exp_r & 0xff)
    asic_write(dev, 0x9d, (exp_r >> 8) & 0xff)
    asic_write(dev, 0x9e, exp_g & 0xff)
    asic_write(dev, 0x9f, (exp_g >> 8) & 0xff)
    asic_write(dev, 0xa0, exp_b & 0xff)
    asic_write(dev, 0xa1, (exp_b >> 8) & 0xff)

def set_gain_and_offset(dev, gain: int = 31, offset: int = 2):
    """Set AFE PGA gain (0..31) and DAC offset for Red, Green, Blue."""
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
            time.sleep(0.004)
    finally:
        # Crucial hardware safety: disarm motor driver pulses to prevent coil overheating
        asic_write(dev, 0x85, 0x10)

def is_home(dev) -> bool:
    """Optical Home Sensor: Reg 0x84 bit 5 is 0 at home dock, 1 when away."""
    s84 = asic_read(dev, 0x84)
    return s84 is not None and (s84 & 0x20) == 0

def auto_home(dev) -> int:
    """Closed-loop optical homing: retracts until home sensor trips."""
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
    Capture a single raw 16,200-byte line from Bulk IN endpoint (0x81).
    Unpacks as 8,100 uint16 words (2,700 R, 2,700 G, 2,700 B).
    """
    # Trigger optical exposure
    asic_write(dev, 0x85, 0x12)
    asic_write(dev, 0x81, 0x00)
    wait_idle(dev)

    # Set window end = 0
    asic_write(dev, 0x90, 0x00)
    asic_write(dev, 0x91, 0x00)
    asic_write(dev, 0x92, 0x00)

    # Reset read pointer
    asic_write(dev, 0x93, 0x00)
    asic_write(dev, 0x94, 0x00)
    asic_write(dev, 0x95, 0x00)
    wait_idle(dev)

    # Arm DMA on 0x82 for 16,200 bytes
    wctl(dev, 0x83, 0x80)
    desc = struct.pack("<BBBB I", 0x00, 0x00, 0x00, 0x00, FULL_LINE_BYTES)
    wctl(dev, 0x82, desc)

    raw = bytes(dev.read(EP_IN, FULL_LINE_BYTES, timeout=4000))
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

    # CCD Sampling Gate & Clock Generator
    asic_write(dev, 0x98, 0x01)
    asic_write(dev, 0x99, 0x00)
    asic_write(dev, 0x9a, 0x8d)
    asic_write(dev, 0x9b, 0x2a)
    return dev


# ==============================================================================
# Filtering, Smoothing, and Mathematical Primitives
# ==============================================================================

def boxcar_filter_1d(signal: List[float], radius: int) -> List[float]:
    """Fast 1D boxcar (moving average) filter using prefix sums in O(N)."""
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

def lowpass_smooth_1d(signal: List[float], radius: int = 25, passes: int = 3) -> List[float]:
    """
    Cascaded boxcar filter approximating a Gaussian low-pass curve in O(N) time.
    Separates the smooth macro illumination profile from high-frequency PRNU.
    """
    cur = list(signal)
    for _ in range(passes):
        cur = boxcar_filter_1d(cur, radius)
    return cur

def estimate_noise_floor_mad(residual: List[float]) -> float:
    """
    Estimate Gaussian noise standard deviation sigma from residual using
    Median Absolute Deviation (MAD), robust against true dust lines and PRNU peaks.
    """
    n = len(residual)
    if n == 0:
        return 1.0
    med_r = sorted(residual)[n // 2]
    deviations = sorted(abs(x - med_r) for x in residual)
    mad = deviations[n // 2]
    # MAD to sigma factor for normal distribution: 1.4826
    return max(1.4826 * mad, 1e-6)

def filter_reference_profile(
    delta_profile: List[float],
    se_profile: Optional[List[float]] = None,
    filter_mode: str = "hybrid",
    radius: int = 25,
    k_sigma: float = 2.0
) -> Tuple[List[float], Dict[str, float]]:
    """
    Filter the net reference profile Delta(x) = W(x) - D(x).

    Modes:
      - 'hybrid': Decomposes Delta(x) into macro illumination envelope L(x) and
                  high-frequency residual R(x). Preserves significant PRNU and
                  dust lines exceeding the noise floor while soft-coring random
                  shot noise to prevent noise amplification in the scan.
      - 'lowpass': Pure low-pass filter (vignetting envelope only).
      - 'raw': Direct unfiltered profile.

    Returns:
      (effective_delta, stats_dict)
    """
    n = len(delta_profile)
    stats: Dict[str, float] = {}

    if filter_mode == "raw":
        return list(delta_profile), {"mode": "raw"}

    # Compute low-pass illumination envelope L(x)
    envelope = lowpass_smooth_1d(delta_profile, radius=radius, passes=3)

    if filter_mode == "lowpass":
        return envelope, {"mode": "lowpass", "radius": radius}

    # Hybrid mode: extract high-frequency residual
    residual = [delta_profile[i] - envelope[i] for i in range(n)]

    # Determine per-pixel noise threshold
    if se_profile is not None and len(se_profile) == n:
        thresholds = [max(k_sigma * se_profile[i], 1e-4) for i in range(n)]
        avg_noise = sum(se_profile) / n
    else:
        mad_sigma = estimate_noise_floor_mad(residual)
        thresh_val = max(k_sigma * mad_sigma, 1e-4)
        thresholds = [thresh_val] * n
        avg_noise = mad_sigma

    # Soft-coring shrinkage: preserve prominent PRNU & dust dips, suppress noise
    filtered_residual = [0.0] * n
    prnu_preserved_count = 0
    dust_preserved_count = 0

    for i in range(n):
        r = residual[i]
        t = thresholds[i]
        if abs(r) > t:
            # Significant feature (PRNU sensel or optical dust line)
            filtered_residual[i] = r
            if r < -3.0 * t:
                dust_preserved_count += 1
            else:
                prnu_preserved_count += 1
        else:
            # Below noise floor: suppress shot noise fluctuation
            filtered_residual[i] = 0.0

    effective_delta = [envelope[i] + filtered_residual[i] for i in range(n)]

    stats = {
        "mode": "hybrid",
        "radius": radius,
        "k_sigma": k_sigma,
        "estimated_noise_sigma": avg_noise,
        "prnu_sensels_preserved": prnu_preserved_count,
        "dust_streaks_preserved": dust_preserved_count,
    }
    return effective_delta, stats


# ==============================================================================
# Flat-Field Calibration Profile Class
# ==============================================================================

class FlatFieldCalibration:
    """
    Encapsulates measured Dark reference, White reference, effective shading profiles,
    and normalized per-channel gain correction curves for PrimeFilm 1800u.
    """
    def __init__(
        self,
        dark_r: List[float],
        dark_g: List[float],
        dark_b: List[float],
        white_r: List[float],
        white_g: List[float],
        white_b: List[float],
        white_eff_r: List[float],
        white_eff_g: List[float],
        white_eff_b: List[float],
        gain_r: List[float],
        gain_g: List[float],
        gain_b: List[float],
        target_white: Union[float, Dict[str, float]],
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.dark_r = dark_r
        self.dark_g = dark_g
        self.dark_b = dark_b
        self.white_r = white_r
        self.white_g = white_g
        self.white_b = white_b
        self.white_eff_r = white_eff_r
        self.white_eff_g = white_eff_g
        self.white_eff_b = white_eff_b
        self.gain_r = gain_r
        self.gain_g = gain_g
        self.gain_b = gain_b
        self.target_white = target_white
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert calibration data to serializable dictionary."""
        return {
            "format": "pie1800_shading_v1",
            "created_at": self.metadata.get("timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
            "pixels_per_line": len(self.dark_r),
            "target_white": self.target_white,
            "metadata": self.metadata,
            "dark": {
                "r": [round(x, 2) for x in self.dark_r],
                "g": [round(x, 2) for x in self.dark_g],
                "b": [round(x, 2) for x in self.dark_b],
            },
            "white_raw": {
                "r": [round(x, 2) for x in self.white_r],
                "g": [round(x, 2) for x in self.white_g],
                "b": [round(x, 2) for x in self.white_b],
            },
            "white_effective": {
                "r": [round(x, 2) for x in self.white_eff_r],
                "g": [round(x, 2) for x in self.white_eff_g],
                "b": [round(x, 2) for x in self.white_eff_b],
            },
            "gain": {
                "r": [round(x, 6) for x in self.gain_r],
                "g": [round(x, 6) for x in self.gain_g],
                "b": [round(x, 6) for x in self.gain_b],
            }
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FlatFieldCalibration":
        """Reconstruct FlatFieldCalibration instance from dictionary."""
        return cls(
            dark_r=data["dark"]["r"],
            dark_g=data["dark"]["g"],
            dark_b=data["dark"]["b"],
            white_r=data["white_raw"]["r"],
            white_g=data["white_raw"]["g"],
            white_b=data["white_raw"]["b"],
            white_eff_r=data["white_effective"]["r"],
            white_eff_g=data["white_effective"]["g"],
            white_eff_b=data["white_effective"]["b"],
            gain_r=data["gain"]["r"],
            gain_g=data["gain"]["g"],
            gain_b=data["gain"]["b"],
            target_white=data.get("target_white", 65535.0),
            metadata=data.get("metadata", {})
        )

    def save(self, filepath: str):
        """Save calibration profile to JSON or Binary file depending on extension."""
        save_calibration(self, filepath)

    def summary(self) -> str:
        """Return formatted diagnostic summary of the calibration profile."""
        lines = [
            "=" * 70,
            "PRIME FILM 1800u / 1800i FLAT-FIELD CALIBRATION PROFILE",
            "=" * 70,
            f"Created      : {self.metadata.get('timestamp', 'N/A')}",
            f"Exposure     : {self.metadata.get('exposure_clocks', 'N/A')} clocks | Gain: {self.metadata.get('gain', 'N/A')}",
            f"Filter Mode  : {self.metadata.get('filter_mode', 'N/A')} (radius={self.metadata.get('filter_radius', 'N/A')})",
            f"Target White : {self.target_white}",
            "-" * 70,
        ]
        for ch, d, w, g in [("Red", self.dark_r, self.white_eff_r, self.gain_r),
                            ("Green", self.dark_g, self.white_eff_g, self.gain_g),
                            ("Blue", self.dark_b, self.white_eff_b, self.gain_b)]:
            d_avg = sum(d) / len(d)
            w_avg = sum(w) / len(w)
            w_min, w_max = min(w), max(w)
            g_min, g_max = min(g), max(g)
            g_avg = sum(g) / len(g)
            vignetting = (w[len(w)//2] / max(w[50], 1.0)) if w[len(w)//2] > w[50] else (w[50] / max(w[len(w)//2], 1.0))
            lines.append(f"{ch:5s} Channel :")
            lines.append(f"  Dark Level  : Avg={d_avg:7.1f} (Min={min(d):7.1f}, Max={max(d):7.1f})")
            lines.append(f"  White Level : Avg={w_avg:7.1f} (Min={w_min:7.1f}, Max={w_max:7.1f})")
            lines.append(f"  Gain Curve  : Avg={g_avg:9.5f} (Min={g_min:9.5f}, Max={g_max:9.5f})")
            lines.append(f"  Vignetting  : Center-to-Edge Ratio = {vignetting:.2f}x")
        lines.append("=" * 70)
        return "\n".join(lines)


# ==============================================================================
# Saving and Loading Functions
# ==============================================================================

def save_calibration(calib: FlatFieldCalibration, filepath: str):
    """
    Save calibration profile. Supports:
      - `.json`: Human-readable JSON format.
      - `.bin`: High-speed binary format with magic header and float32 packed curves.
    """
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".bin":
        # Packed binary format: MAGIC + header_len + JSON_METADATA + float32 arrays
        calib_dict = calib.to_dict()
        meta_dict = {
            "format": calib_dict["format"],
            "created_at": calib_dict["created_at"],
            "pixels_per_line": calib_dict["pixels_per_line"],
            "target_white": calib_dict["target_white"],
            "metadata": calib_dict["metadata"],
        }
        meta_bytes = json.dumps(meta_dict).encode("utf-8")

        # 12 float32 arrays: dark (R,G,B), white_raw (R,G,B), white_eff (R,G,B), gain (R,G,B)
        arrays = [
            calib.dark_r, calib.dark_g, calib.dark_b,
            calib.white_r, calib.white_g, calib.white_b,
            calib.white_eff_r, calib.white_eff_g, calib.white_eff_b,
            calib.gain_r, calib.gain_g, calib.gain_b
        ]
        n_pixels = len(calib.dark_r)
        payload = bytearray()
        for arr in arrays:
            payload.extend(struct.pack(f"<{n_pixels}f", *arr))

        with open(filepath, "wb") as f:
            f.write(MAGIC_HEADER)
            f.write(struct.pack("<I", len(meta_bytes)))
            f.write(meta_bytes)
            f.write(payload)
    else:
        # Default to JSON
        calib_dict = calib.to_dict()
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(calib_dict, f, indent=2)

def load_calibration(filepath: str) -> FlatFieldCalibration:
    """Load calibration profile from either .json or .bin file."""
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Calibration file not found: {filepath}")

    with open(filepath, "rb") as f:
        magic = f.read(10)

    if magic == MAGIC_HEADER:
        # Binary format
        with open(filepath, "rb") as f:
            f.seek(10)
            meta_len = struct.unpack("<I", f.read(4))[0]
            meta_bytes = f.read(meta_len)
            meta_dict = json.loads(meta_bytes.decode("utf-8"))
            n_pixels = meta_dict["pixels_per_line"]

            # Read 12 float32 arrays (n_pixels * 4 bytes each)
            float_count = n_pixels * 12
            raw_payload = f.read(float_count * 4)
            all_floats = struct.unpack(f"<{float_count}f", raw_payload)

            dark_r = list(all_floats[0 * n_pixels : 1 * n_pixels])
            dark_g = list(all_floats[1 * n_pixels : 2 * n_pixels])
            dark_b = list(all_floats[2 * n_pixels : 3 * n_pixels])
            white_r = list(all_floats[3 * n_pixels : 4 * n_pixels])
            white_g = list(all_floats[4 * n_pixels : 5 * n_pixels])
            white_b = list(all_floats[5 * n_pixels : 6 * n_pixels])
            white_eff_r = list(all_floats[6 * n_pixels : 7 * n_pixels])
            white_eff_g = list(all_floats[7 * n_pixels : 8 * n_pixels])
            white_eff_b = list(all_floats[8 * n_pixels : 9 * n_pixels])
            gain_r = list(all_floats[9 * n_pixels : 10 * n_pixels])
            gain_g = list(all_floats[10 * n_pixels : 11 * n_pixels])
            gain_b = list(all_floats[11 * n_pixels : 12 * n_pixels])

            return FlatFieldCalibration(
                dark_r=dark_r, dark_g=dark_g, dark_b=dark_b,
                white_r=white_r, white_g=white_g, white_b=white_b,
                white_eff_r=white_eff_r, white_eff_g=white_eff_g, white_eff_b=white_eff_b,
                gain_r=gain_r, gain_g=gain_g, gain_b=gain_b,
                target_white=meta_dict.get("target_white", 65535.0),
                metadata=meta_dict.get("metadata", {})
            )
    else:
        # JSON format
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return FlatFieldCalibration.from_dict(data)


# ==============================================================================
# Calibration Computation
# ==============================================================================

def compute_channel_calibration(
    dark_mean: List[float],
    white_mean: List[float],
    white_se: Optional[List[float]] = None,
    dark_se: Optional[List[float]] = None,
    target_white: Union[str, float] = 65535.0,
    filter_mode: str = "hybrid",
    radius: int = 25,
    k_sigma: float = 2.0,
    gain_clip_max: float = 8.0,
    gain_clip_min: float = 0.1
) -> Tuple[List[float], List[float], float, Dict[str, Any]]:
    """
    Compute smoothed effective white profile and normalized gain correction curve C(x).

    Returns:
      (white_effective, gain_curve, resolved_target_white, stats)
    """
    n = len(dark_mean)
    # Net transmission delta: W(x) - D(x)
    raw_delta = [white_mean[i] - dark_mean[i] for i in range(n)]

    # Combined standard error of delta
    combined_se: Optional[List[float]] = None
    if white_se is not None:
        if dark_se is not None:
            combined_se = [(white_se[i]**2 + dark_se[i]**2)**0.5 for i in range(n)]
        else:
            combined_se = list(white_se)

    # Filter delta profile
    effective_delta, filter_stats = filter_reference_profile(
        raw_delta, se_profile=combined_se, filter_mode=filter_mode, radius=radius, k_sigma=k_sigma
    )

    # Effective white reference
    white_effective = [dark_mean[i] + effective_delta[i] for i in range(n)]

    # Determine TargetWhite
    abs_deltas = [abs(d) for d in effective_delta]
    sorted_abs = sorted(abs_deltas)
    median_delta = sorted_abs[n // 2]
    max_delta = sorted_abs[-1]

    if target_white == "median":
        resolved_target = median_delta
    elif target_white == "max":
        resolved_target = max_delta
    else:
        resolved_target = float(target_white)

    # Compute gain curve: C(x) = TargetWhite / (W_eff(x) - D(x))
    # Division-by-zero & dead-pixel guard: clamp denominator to epsilon
    gain_curve = [0.0] * n
    nominal_gain = resolved_target / max(median_delta, 1.0)
    max_allowed_gain = abs(nominal_gain) * gain_clip_max
    min_allowed_gain = abs(nominal_gain) * gain_clip_min

    for i in range(n):
        d_val = effective_delta[i]
        sign = 1.0 if d_val >= 0 else -1.0
        abs_d = abs(d_val)
        raw_gain = (resolved_target / d_val) if abs_d > 0.5 else nominal_gain

        # Clamp extreme gain outliers from sensor edge or dead sensels
        if abs(raw_gain) > max_allowed_gain:
            raw_gain = sign * max_allowed_gain
        elif abs(raw_gain) < min_allowed_gain:
            raw_gain = sign * min_allowed_gain

        gain_curve[i] = raw_gain

    stats = {
        "median_delta": median_delta,
        "max_delta": max_delta,
        "resolved_target": resolved_target,
        "filter_stats": filter_stats
    }
    return white_effective, gain_curve, resolved_target, stats


# ==============================================================================
# The Core Flat-Field Application Function
# ==============================================================================

def apply_flat_field(
    lines_r: List[Any],
    lines_g: List[Any],
    lines_b: List[Any],
    calib_data: Union[FlatFieldCalibration, str, Dict[str, Any]],
    clip: bool = True,
    out_dtype: str = "uint16"
) -> Tuple[List[Any], List[Any], List[Any]]:
    """
    Apply Flat-Field Shading Correction (PRNU & DSNU) to raw scan lines.

    Equation:
        I_calibrated(x, y) = (I_raw(x, y) - D(x)) * C(x)

    Parameters:
      lines_r, lines_g, lines_b: 2D lists [y][x] or single 1D lists [x] of raw pixel values.
      calib_data: FlatFieldCalibration object, path to .json/.bin file, or dict.
      clip: Clamps values to output data type range (e.g. [0, 65535] for uint16).
      out_dtype: 'uint16' (default), 'float', or 'uint8'.

    Returns:
      (calibrated_r, calibrated_g, calibrated_b)
    """
    if isinstance(calib_data, str):
        calib = load_calibration(calib_data)
    elif isinstance(calib_data, dict):
        calib = FlatFieldCalibration.from_dict(calib_data)
    else:
        calib = calib_data

    # Check if input is a single line (1D list of ints/floats) or multiple lines (2D list)
    single_line = False
    if len(lines_r) > 0 and not isinstance(lines_r[0], (list, tuple)):
        single_line = True
        r_rows = [lines_r]
        g_rows = [lines_g]
        b_rows = [lines_b]
    else:
        r_rows = lines_r
        g_rows = lines_g
        b_rows = lines_b

    d_r = calib.dark_r
    d_g = calib.dark_g
    d_b = calib.dark_b
    g_r = calib.gain_r
    g_g = calib.gain_g
    g_b = calib.gain_b
    width = len(d_r)

    max_val = 65535.0 if out_dtype == "uint16" else (255.0 if out_dtype == "uint8" else 1e9)

    out_r: List[Any] = []
    out_g: List[Any] = []
    out_b: List[Any] = []

    num_lines = len(r_rows)

    if out_dtype == "uint16":
        for y in range(num_lines):
            row_r = r_rows[y]
            row_g = g_rows[y]
            row_b = b_rows[y]

            # Vector-optimized inner loop with float rounding
            cr_row = [int(round((row_r[x] - d_r[x]) * g_r[x])) for x in range(width)]
            cg_row = [int(round((row_g[x] - d_g[x]) * g_g[x])) for x in range(width)]
            cb_row = [int(round((row_b[x] - d_b[x]) * g_b[x])) for x in range(width)]

            if clip:
                cr_row = [0 if v < 0 else (65535 if v > 65535 else v) for v in cr_row]
                cg_row = [0 if v < 0 else (65535 if v > 65535 else v) for v in cg_row]
                cb_row = [0 if v < 0 else (65535 if v > 65535 else v) for v in cb_row]

            out_r.append(cr_row)
            out_g.append(cg_row)
            out_b.append(cb_row)
    elif out_dtype == "uint8":
        for y in range(num_lines):
            row_r = r_rows[y]
            row_g = g_rows[y]
            row_b = b_rows[y]
            cr_row = [int(round((row_r[x] - d_r[x]) * g_r[x])) for x in range(width)]
            cg_row = [int(round((row_g[x] - d_g[x]) * g_g[x])) for x in range(width)]
            cb_row = [int(round((row_b[x] - d_b[x]) * g_b[x])) for x in range(width)]
            if clip:
                cr_row = [0 if v < 0 else (255 if v > 255 else v) for v in cr_row]
                cg_row = [0 if v < 0 else (255 if v > 255 else v) for v in cg_row]
                cb_row = [0 if v < 0 else (255 if v > 255 else v) for v in cb_row]
            out_r.append(cr_row)
            out_g.append(cg_row)
            out_b.append(cb_row)
    else:  # float
        for y in range(num_lines):
            row_r = r_rows[y]
            row_g = g_rows[y]
            row_b = b_rows[y]
            cr_row = [(row_r[x] - d_r[x]) * g_r[x] for x in range(width)]
            cg_row = [(row_g[x] - d_g[x]) * g_g[x] for x in range(width)]
            cb_row = [(row_b[x] - d_b[x]) * g_b[x] for x in range(width)]
            if clip:
                cr_row = [max(0.0, v) for v in cr_row]
                cg_row = [max(0.0, v) for v in cg_row]
                cb_row = [max(0.0, v) for v in cb_row]
            out_r.append(cr_row)
            out_g.append(cg_row)
            out_b.append(cb_row)

    if single_line:
        return out_r[0], out_g[0], out_b[0]
    return out_r, out_g, out_b


# ==============================================================================
# Live Scanner Acquisition Routines
# ==============================================================================

def measure_dark_reference(
    dev,
    num_lines: int = 16,
    exposure: int = 2900,
    gain: int = 31
) -> Tuple[List[float], List[float], List[float], List[float], List[float], List[float]]:
    """
    Measure dark reference (DSNU) with lamp OFF.
    Averages num_lines (8..16) to minimize temporal thermal noise.
    Carriage remains docked at home (step 0).
    Motor remains safely disarmed with 0x85 -> 0x10.

    Returns:
      (mean_r, mean_g, mean_b, se_r, se_g, se_b)
    """
    print(f"[*] Measuring Dark Reference (DSNU) across {num_lines} lines (Lamp OFF)...")
    set_lamp(dev, False)
    time.sleep(0.3)

    set_exposure(dev, exposure, exposure, exposure)
    set_gain_and_offset(dev, gain=gain, offset=2)

    r_lines: List[List[int]] = []
    g_lines: List[List[int]] = []
    b_lines: List[List[int]] = []

    for i in range(num_lines):
        raw = capture_raw_line(dev)
        words = struct.unpack(f"<{WORDS_PER_LINE}H", raw)
        r_lines.append(list(words[0:2700]))
        g_lines.append(list(words[2700:5400]))
        b_lines.append(list(words[5400:8100]))

    def compute_stats(lines: List[List[int]]):
        m = len(lines)
        w = len(lines[0])
        means = [0.0] * w
        ses = [0.0] * w
        for x in range(w):
            s = sum(lines[k][x] for k in range(m))
            mean_val = s / m
            means[x] = mean_val
            if m > 1:
                var = sum((lines[k][x] - mean_val)**2 for k in range(m)) / (m - 1)
                ses[x] = (var / m)**0.5
            else:
                ses[x] = 1.0
        return means, ses

    m_r, se_r = compute_stats(r_lines)
    m_g, se_g = compute_stats(g_lines)
    m_b, se_b = compute_stats(b_lines)
    print(f"[+] Dark reference acquired: R_avg={sum(m_r)/2700:.1f}, G_avg={sum(m_g)/2700:.1f}, B_avg={sum(m_b)/2700:.1f}")
    return m_r, m_g, m_b, se_r, se_g, se_b

def measure_white_reference(
    dev,
    num_lines: int = 16,
    dock_step: int = 100,
    exposure: int = 2900,
    gain: int = 31,
    analog_balance: bool = False,
    step_carriage: bool = False
) -> Tuple[List[float], List[float], List[float], List[float], List[float], List[float]]:
    """
    Measure white reference (PRNU & Vignetting) with lamp ON in the clear aperture.
    Carriage moves into safe calibration dock region (dock_step: 0..200).
    Averages num_lines (8..16) to suppress photon shot noise.
    Returns carriage home and turns lamp OFF upon completion.

    Returns:
      (mean_r, mean_g, mean_b, se_r, se_g, se_b)
    """
    # Enforce hardware boundary safety
    if dock_step > SAFE_DOCK_STEP_MAX:
        print(f"[!] Warning: Dock step {dock_step} exceeds clear dock range ({SAFE_DOCK_STEP_MAX}). Clamping.")
        dock_step = SAFE_DOCK_STEP_MAX

    print(f"[*] Moving carriage to clear calibration aperture (Step {dock_step})...")
    if not is_home(dev):
        auto_home(dev)

    total_moved = 0
    try:
        if dock_step > 0:
            move_carriage(dev, 0x16, dock_step)
            total_moved += dock_step

        print("[*] Turning LAMP ON & warming up (1.5s)...")
        set_lamp(dev, True)
        time.sleep(1.5)

        if analog_balance:
            exp_r = int(exposure * 0.9)
            exp_g = int(exposure * 1.0)
            exp_b = int(exposure * 1.75)
        else:
            exp_r = exp_g = exp_b = exposure

        set_exposure(dev, exp_r, exp_g, exp_b)
        set_gain_and_offset(dev, gain=gain, offset=2)

        print(f"[*] Measuring White Reference across {num_lines} lines...")
        r_lines: List[List[int]] = []
        g_lines: List[List[int]] = []
        b_lines: List[List[int]] = []

        for i in range(num_lines):
            raw = capture_raw_line(dev)
            words = struct.unpack(f"<{WORDS_PER_LINE}H", raw)
            r_lines.append(list(words[0:2700]))
            g_lines.append(list(words[2700:5400]))
            b_lines.append(list(words[5400:8100]))
            if step_carriage and i < num_lines - 1:
                move_carriage(dev, 0x16, 1)
                total_moved += 1

        def compute_stats(lines: List[List[int]]):
            m = len(lines)
            w = len(lines[0])
            means = [0.0] * w
            ses = [0.0] * w
            for x in range(w):
                s = sum(lines[k][x] for k in range(m))
                mean_val = s / m
                means[x] = mean_val
                if m > 1:
                    var = sum((lines[k][x] - mean_val)**2 for k in range(m)) / (m - 1)
                    ses[x] = (var / m)**0.5
                else:
                    ses[x] = 1.0
            return means, ses

        m_r, se_r = compute_stats(r_lines)
        m_g, se_g = compute_stats(g_lines)
        m_b, se_b = compute_stats(b_lines)
        print(f"[+] White reference acquired: R_avg={sum(m_r)/2700:.1f}, G_avg={sum(m_g)/2700:.1f}, B_avg={sum(m_b)/2700:.1f}")
        return m_r, m_g, m_b, se_r, se_g, se_b

    finally:
        print("[*] Calibration complete: Turning LAMP OFF and homing carriage...")
        set_lamp(dev, False)
        if total_moved > 0 or not is_home(dev):
            auto_home(dev)

def calibrate_scanner(
    dev = None,
    num_dark: int = 16,
    num_white: int = 16,
    dock_step: int = 100,
    exposure: int = 2900,
    gain: int = 31,
    analog_balance: bool = False,
    filter_mode: str = "hybrid",
    radius: int = 25,
    k_sigma: float = 2.0,
    target_white: Union[str, float] = 65535.0,
    save_path: Optional[str] = "shading_calib.json"
) -> FlatFieldCalibration:
    """
    Perform full end-to-end flat-field calibration on connected scanner.
    Measures dark current (lamp OFF) and clear illumination (lamp ON),
    computes gain correction curves, and saves profile.
    """
    should_close = False
    if dev is None:
        dev = connect_scanner()
        should_close = True

    try:
        # Step 1: Dark Reference (Lamp OFF)
        d_r, d_g, d_b, se_dr, se_dg, se_db = measure_dark_reference(
            dev, num_lines=num_dark, exposure=exposure, gain=gain
        )

        # Step 2: White Reference (Lamp ON at clear dock step)
        w_r, w_g, w_b, se_wr, se_wg, se_wb = measure_white_reference(
            dev, num_lines=num_white, dock_step=dock_step,
            exposure=exposure, gain=gain, analog_balance=analog_balance
        )

        # Step 3: Compute Flat-Field Curves
        print(f"[*] Computing Flat-Field Gain Curves (Filter: {filter_mode}, Radius: {radius})...")
        we_r, g_r, tw_r, s_r = compute_channel_calibration(
            d_r, w_r, white_se=se_wr, dark_se=se_dr,
            target_white=target_white, filter_mode=filter_mode, radius=radius, k_sigma=k_sigma
        )
        we_g, g_g, tw_g, s_g = compute_channel_calibration(
            d_g, w_g, white_se=se_wg, dark_se=se_dg,
            target_white=target_white, filter_mode=filter_mode, radius=radius, k_sigma=k_sigma
        )
        we_b, g_b, tw_b, s_b = compute_channel_calibration(
            d_b, w_b, white_se=se_wb, dark_se=se_db,
            target_white=target_white, filter_mode=filter_mode, radius=radius, k_sigma=k_sigma
        )

        metadata = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "exposure_clocks": exposure,
            "gain": gain,
            "analog_balance": analog_balance,
            "dock_step": dock_step,
            "num_dark_lines": num_dark,
            "num_white_lines": num_white,
            "filter_mode": filter_mode,
            "filter_radius": radius,
            "k_sigma": k_sigma,
            "channel_stats": {"red": s_r, "green": s_g, "blue": s_b}
        }

        calib = FlatFieldCalibration(
            dark_r=d_r, dark_g=d_g, dark_b=d_b,
            white_r=w_r, white_g=w_g, white_b=w_b,
            white_eff_r=we_r, white_eff_g=we_g, white_eff_b=we_b,
            gain_r=g_r, gain_g=g_g, gain_b=g_b,
            target_white={"r": tw_r, "g": tw_g, "b": tw_b},
            metadata=metadata
        )

        if save_path:
            calib.save(save_path)
            print(f"[+] Calibration Profile Saved to: {save_path}")

        print(calib.summary())
        return calib

    finally:
        if should_close:
            try:
                set_lamp(dev, False)
                asic_write(dev, 0x85, 0x10)
            except Exception:
                pass


# ==============================================================================
# Simulation & Self-Test Verification (< 1% Variance)
# ==============================================================================

def run_simulation_verification() -> bool:
    """
    Synthetic verification test:
    Simulates optical vignetting (25% parabolic falloff across sensor),
    CCD sensel sensitivity variations (1.5% PRNU), optical dust streaks (up to 15% dip),
    and DSNU dark current offset.
    Verifies that apply_flat_field flattens the non-uniformity to < 1.0% variance (CV).
    """
    print("=" * 70)
    print("RUNNING FLAT-FIELD CALIBRATION SELF-TEST (SYNTHETIC VERIFICATION)")
    print("=" * 70)

    import random
    random.seed(1800)
    n = PIXELS_PER_LINE

    # 1. Physical Vignetting: Parabolic illumination profile (center=1.0, edges=0.75)
    vignetting = [1.0 - 0.25 * ((x - n / 2) / (n / 2))**2 for x in range(n)]

    # 2. Sensel PRNU (+-1.5% fixed pattern sensitivity)
    prnu = [random.gauss(0.0, 0.015) for _ in range(n)]

    # 3. Optical dust streaks on lens/mirrors (stationary dips down the scan)
    dust = [0.0] * n
    dust[450] = -0.15   # 15% light absorption by dust speck
    dust[1350] = -0.08  # 8% dip
    dust[2100] = -0.12  # 12% dip

    # 4. Thermal Dark Current & ADC Black Clamp (DSNU)
    dark_true = [4030.0 + random.gauss(0.0, 15.0) for _ in range(n)]

    # Inverting CCD response: Light lowers ADC count from reset level
    base_signal = 3600.0
    delta_true = [base_signal * vignetting[x] * (1.0 + prnu[x] + dust[x]) for x in range(n)]
    white_true = [dark_true[x] - delta_true[x] for x in range(n)]

    # Simulate 16 noisy calibration exposures
    m_lines = 16
    dark_frames = [[dark_true[x] + random.gauss(0.0, 10.0) for x in range(n)] for _ in range(m_lines)]
    white_frames = [[white_true[x] + random.gauss(0.0, 10.0) for x in range(n)] for _ in range(m_lines)]

    d_mean = [sum(dark_frames[k][x] for k in range(m_lines)) / m_lines for x in range(n)]
    w_mean = [sum(white_frames[k][x] for k in range(m_lines)) / m_lines for x in range(n)]
    w_se = [(sum((white_frames[k][x] - w_mean[x])**2 for k in range(m_lines)) / (m_lines * (m_lines - 1)))**0.5 for x in range(n)]
    d_se = [(sum((dark_frames[k][x] - d_mean[x])**2 for k in range(m_lines)) / (m_lines * (m_lines - 1)))**0.5 for x in range(n)]

    # Compute calibration curves with hybrid filtering
    we, gain, tw, stats = compute_channel_calibration(
        d_mean, w_mean, white_se=w_se, dark_se=d_se,
        target_white=65535.0, filter_mode="hybrid", radius=25, k_sigma=2.0
    )

    dummy_calib = FlatFieldCalibration(
        dark_r=d_mean, dark_g=d_mean, dark_b=d_mean,
        white_r=w_mean, white_g=w_mean, white_b=w_mean,
        white_eff_r=we, white_eff_g=we, white_eff_b=we,
        gain_r=gain, gain_g=gain, gain_b=gain,
        target_white=65535.0, metadata={"test": True}
    )

    # Simulate 50 lines of an unseen uniform test target (transmission = 1.0)
    test_lines = []
    for _ in range(50):
        line = [dark_true[x] - delta_true[x] + random.gauss(0.0, 10.0) for x in range(n)]
        test_lines.append(line)

    # Calibrate
    calib_lines, _, _ = apply_flat_field(test_lines, test_lines, test_lines, dummy_calib, clip=True, out_dtype="uint16")

    # Evaluate non-uniformity across calibrated lines
    # Average across all 50 calibrated lines to measure residual spatial non-uniformity
    mean_profile = [sum(calib_lines[y][x] for y in range(50)) / 50.0 for x in range(n)]
    overall_mean = sum(mean_profile) / n
    var = sum((mean_profile[x] - overall_mean)**2 for x in range(n)) / n
    std_dev = var**0.5
    cv_percent = (std_dev / overall_mean) * 100.0

    print(f"Target Output Value : {65535.0}")
    print(f"Calibrated Mean     : {overall_mean:.1f}")
    print(f"Calibrated Std Dev  : {std_dev:.2f}")
    print(f"Residual Non-Uniformity (CV): {cv_percent:.3f}%")
    print(f"Dust Streak at px 450  (True dip -15%): Calibrated = {mean_profile[450]:.1f} ({mean_profile[450]/overall_mean*100:.2f}%)")
    print(f"Dust Streak at px 1350 (True dip -8%) : Calibrated = {mean_profile[1350]:.1f} ({mean_profile[1350]/overall_mean*100:.2f}%)")
    print(f"Dust Streak at px 2100 (True dip -12%): Calibrated = {mean_profile[2100]:.1f} ({mean_profile[2100]/overall_mean*100:.2f}%)")

    # Check persistence round-trip
    test_json = "/tmp/test_shading_profile.json"
    test_bin = "/tmp/test_shading_profile.bin"
    dummy_calib.save(test_json)
    dummy_calib.save(test_bin)
    loaded_json = load_calibration(test_json)
    loaded_bin = load_calibration(test_bin)

    json_diff = max(abs(dummy_calib.gain_r[i] - loaded_json.gain_r[i]) for i in range(n))
    bin_diff = max(abs(dummy_calib.gain_r[i] - loaded_bin.gain_r[i]) for i in range(n))
    print(f"JSON Save/Load Precision Error : {json_diff:.8f}")
    print(f"Binary Save/Load Precision Error: {bin_diff:.8f}")

    success = cv_percent < 1.0 and json_diff < 1e-4 and bin_diff < 1e-4
    if success:
        print("\n[+] VERIFICATION PASSED: Non-uniformity flattened to within < 1.0% variance!")
    else:
        print("\n[!] VERIFICATION FAILED!")
    return success


# ==============================================================================
# CLI Entry Point
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description="PrimeFilm 1800u / 1800i Flat-Field Shading Calibration")
    parser.add_argument("--calibrate", action="store_true",
                        help="Run live hardware flat-field calibration and generate profile")
    parser.add_argument("--dock-step", type=int, default=100,
                        help="Carriage step position in clear aperture for white calibration (default: 100, max: 200)")
    parser.add_argument("--lines", type=int, default=16,
                        help="Number of lines to average for dark and white reference (default: 16)")
    parser.add_argument("--exposure", type=int, default=2900,
                        help="CCD integration time clocks (default: 2900)")
    parser.add_argument("--gain", type=int, default=31,
                        help="AFE PGA gain (default: 31)")
    parser.add_argument("--filter", choices=["hybrid", "lowpass", "raw"], default="hybrid",
                        help="Smoothing filter mode across white reference (default: hybrid)")
    parser.add_argument("--radius", type=int, default=25,
                        help="Low-pass filter radius across sensel axis (default: 25 px)")
    parser.add_argument("--target-white", type=str, default="65535",
                        help="Target white level ('median', 'max', or numeric e.g. 65535; default: 65535)")
    parser.add_argument("--out", type=str, default="shading_calib.json",
                        help="Output path for calibration profile (default: shading_calib.json)")
    parser.add_argument("--verify", type=str, default=None,
                        help="Verify and print diagnostics of an existing calibration profile (.json or .bin)")
    parser.add_argument("--test-sim", action="store_true",
                        help="Run self-test on simulated sensor data to verify < 1%% variance")
    parser.add_argument("--apply-bin", type=str, default=None,
                        help="Input raw16 binary file to calibrate")
    parser.add_argument("--out-bin", type=str, default=None,
                        help="Output calibrated raw16 binary file")
    parser.add_argument("--calib", type=str, default="shading_calib.json",
                        help="Calibration profile to apply (default: shading_calib.json)")
    args = parser.parse_args()

    if args.test_sim:
        ok = run_simulation_verification()
        sys.exit(0 if ok else 1)

    if args.verify:
        calib = load_calibration(args.verify)
        print(calib.summary())
        sys.exit(0)

    if args.apply_bin:
        if not args.out_bin:
            print("[!] Please specify --out-bin destination.")
            sys.exit(1)
        calib = load_calibration(args.calib)
        print(f"[*] Loading raw scan from {args.apply_bin}...")
        with open(args.apply_bin, "rb") as f:
            raw_data = f.read()
        num_lines = len(raw_data) // FULL_LINE_BYTES
        print(f"[*] Processing {num_lines} scan lines with calibration profile {args.calib}...")

        lines_r, lines_g, lines_b = [], [], []
        for y in range(num_lines):
            chunk = raw_data[y * FULL_LINE_BYTES : (y + 1) * FULL_LINE_BYTES]
            words = struct.unpack(f"<{WORDS_PER_LINE}H", chunk)
            lines_r.append(list(words[0:2700]))
            lines_g.append(list(words[2700:5400]))
            lines_b.append(list(words[5400:8100]))

        cal_r, cal_g, cal_b = apply_flat_field(lines_r, lines_g, lines_b, calib, clip=True, out_dtype="uint16")

        out_raw = bytearray()
        for y in range(num_lines):
            line_words = cal_r[y] + cal_g[y] + cal_b[y]
            out_raw.extend(struct.pack(f"<{WORDS_PER_LINE}H", *line_words))

        with open(args.out_bin, "wb") as f:
            f.write(out_raw)
        print(f"[+] Saved Calibrated Raw Stream: {args.out_bin}")
        sys.exit(0)

    if args.calibrate:
        target_w: Union[str, float]
        try:
            target_w = float(args.target_white)
        except ValueError:
            target_w = args.target_white

        calib = calibrate_scanner(
            num_dark=args.lines,
            num_white=args.lines,
            dock_step=args.dock_step,
            exposure=args.exposure,
            gain=args.gain,
            filter_mode=args.filter,
            radius=args.radius,
            target_white=target_w,
            save_path=args.out
        )
        sys.exit(0)

    parser.print_help()

if __name__ == "__main__":
    main()
