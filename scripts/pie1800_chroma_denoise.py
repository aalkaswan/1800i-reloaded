#!/usr/bin/env python3
"""
PrimeFilm 1800u / 1800i Native Chroma-Only Grain-Preserving Denoiser
(scripts/pie1800_chroma_denoise.py)

Decouples luminance and chrominance in perceptual color space (CIE-LAB or YCbCr),
leaving the luminance channel 100% untouched to preserve every natural film grain
particle and fine optical transition, while applying an edge-preserving bilateral or
guided filter solely to chrominance to eliminate electronic sensor noise speckles
and shadow blotches.
"""

import sys
import os
import time
import ctypes
import argparse
import subprocess
from pathlib import Path

try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

# Color space constants
COLORSPACE_LAB   = 0
COLORSPACE_YCBCR = 1

# Filter constants
FILTER_BILATERAL = 0
FILTER_GUIDED    = 1

REPO_ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = REPO_ROOT / "bin"
LIB_SO = BIN_DIR / "libpie1800_chroma_denoise.so"
C_SRC = Path(__file__).resolve().parent / "pie1800_chroma_denoise.c"


def _ensure_c_library():
    """Builds the C shared library on-the-fly if not already present."""
    if LIB_SO.is_file():
        return str(LIB_SO)

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    if not C_SRC.is_file():
        return None

    cmd = [
        "gcc", "-O3", "-march=native", "-fopenmp", "-fPIC", "-shared",
        str(C_SRC), "-o", str(LIB_SO), "-lm"
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return str(LIB_SO)
    except Exception as e:
        print(f"[!] Warning: Failed to build C library ({e}), falling back.", file=sys.stderr)
        return None


# Load C library if available
_c_lib = None
_lib_path = _ensure_c_library()
if _lib_path:
    try:
        _c_lib = ctypes.CDLL(_lib_path)
        # int denoise_chroma_rgb24(const uint8_t *rgb_in, uint8_t *rgb_out, int w, int h,
        #                          int radius, float strength, int colorspace, int filter_type);
        _c_lib.denoise_chroma_rgb24.argtypes = [
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_float,
            ctypes.c_int,
            ctypes.c_int,
        ]
        _c_lib.denoise_chroma_rgb24.restype = ctypes.c_int
    except Exception as e:
        _c_lib = None
        print(f"[!] Warning: Could not bind C library: {e}", file=sys.stderr)


def denoise_chroma_bytes(rgb_bytes: bytes, width: int, height: int,
                         radius: int = 5, strength: float = 12.0,
                         colorspace: str = "lab", filter_type: str = "bilateral") -> bytes:
    """
    Denoises raw RGB24 bytes (width * height * 3 bytes).
    Returns new denoised RGB24 bytes.
    """
    cs_code = COLORSPACE_YCBCR if colorspace.lower() == "ycbcr" else COLORSPACE_LAB
    flt_code = FILTER_GUIDED if filter_type.lower() == "guided" else FILTER_BILATERAL

    total_bytes = width * height * 3
    if len(rgb_bytes) != total_bytes:
        raise ValueError(f"Expected {total_bytes} bytes for {width}x{height} RGB image, got {len(rgb_bytes)}")

    if _c_lib is not None:
        in_buf = (ctypes.c_uint8 * total_bytes).from_buffer_copy(rgb_bytes)
        out_buf = (ctypes.c_uint8 * total_bytes)()
        ret = _c_lib.denoise_chroma_rgb24(
            in_buf, out_buf, width, height, radius, float(strength), cs_code, flt_code
        )
        if ret == 0:
            return bytes(out_buf)
        else:
            raise RuntimeError(f"C denoise_chroma_rgb24 returned error code {ret}")

    # Fallback to binary execution if shared library binding is unavailable
    bin_exe = BIN_DIR / "pie1800_chroma_denoise"
    if bin_exe.is_file():
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".ppm", delete=False) as fin, \
             tempfile.NamedTemporaryFile(suffix=".ppm", delete=False) as fout:
            fin_path = fin.name
            fout_path = fout.name
            fin.write(f"P6\n{width} {height}\n255\n".encode("ascii") + rgb_bytes)
            fin.flush()

        try:
            subprocess.run([
                str(bin_exe), fin_path, fout_path,
                str(radius), str(strength), colorspace, filter_type
            ], check=True, stdout=subprocess.DEVNULL)
            with open(fout_path, "rb") as f:
                header = f.readline()
                dim = f.readline()
                maxv = f.readline()
                return f.read()
        finally:
            if os.path.exists(fin_path): os.unlink(fin_path)
            if os.path.exists(fout_path): os.unlink(fout_path)

    raise RuntimeError("No C accelerator or executable available for chroma denoising")


def denoise_chroma(image_input, out_path=None, radius: int = 5, strength: float = 12.0,
                   colorspace: str = "lab", filter_type: str = "bilateral"):
    """
    High-level entry point for Chroma-Only Grain-Preserving Denoising.

    Accepts:
      - File path (str or Path): .png, .ppm, .tif, .jpg
      - PIL.Image.Image object
      - numpy.ndarray (H, W, 3) uint8 or float
      - tuple of (bytes, width, height)

    Parameters:
      image_input: Input image in any supported representation.
      out_path:    Optional output file path to save result (.png, .ppm, etc.).
      radius:      Filter spatial radius (default: 5).
      strength:    Chroma range filter strength (default: 12.0).
      colorspace:  'lab' (CIE-LAB perceptual) or 'ycbcr' (default: 'lab').
      filter_type: 'bilateral' or 'guided' (default: 'bilateral').

    Returns:
      Same type as input representation (numpy array, PIL Image, or path string).
    """
    is_path = isinstance(image_input, (str, Path))
    # Numpy array or array-like duck typing
    if hasattr(image_input, "shape") and hasattr(image_input, "tobytes") and hasattr(image_input, "dtype"):
        is_numpy = True
        arr = image_input
        np_mod = sys.modules.get("numpy")
        h, w = arr.shape[0], arr.shape[1]
        c = arr.shape[2] if len(arr.shape) > 2 else 1
        if c != 3:
            raise ValueError(f"Expected 3 channels (RGB), got shape {arr.shape}")
        
        if str(arr.dtype) != "uint8":
            if np_mod:
                arr = (arr * 255.0).clip(0, 255).astype(np_mod.uint8)
            else:
                raise TypeError("Input array must be uint8 or numpy must be installed for dtype conversion")
        
        rgb_bytes = arr.tobytes()
        out_bytes = denoise_chroma_bytes(rgb_bytes, w, h, radius, strength, colorspace, filter_type)
        
        if out_path:
            if HAS_PILLOW:
                Image.frombytes("RGB", (w, h), out_bytes).save(out_path)
            else:
                with open(out_path, "wb") as f:
                    f.write(f"P6\n{w} {h}\n255\n".encode("ascii") + out_bytes)
        
        if np_mod is not None:
            return np_mod.frombuffer(out_bytes, dtype=np_mod.uint8).reshape((h, w, 3))
        return out_bytes

    # Path input
    if is_path:
        p = Path(image_input)
        if not p.is_file():
            raise FileNotFoundError(f"Input file not found: {p}")

        if p.suffix.lower() == ".ppm":
            with open(p, "rb") as f:
                magic = f.readline().decode().strip()
                dims = f.readline().decode().strip().split()
                while dims[0].startswith("#"):
                    dims = f.readline().decode().strip().split()
                w, h = int(dims[0]), int(dims[1])
                maxv = f.readline()
                rgb_bytes = f.read()
            out_bytes = denoise_chroma_bytes(rgb_bytes, w, h, radius, strength, colorspace, filter_type)
            if out_path:
                out_p = Path(out_path)
                if out_p.suffix.lower() == ".ppm":
                    with open(out_p, "wb") as f:
                        f.write(f"P6\n{w} {h}\n255\n".encode("ascii") + out_bytes)
                elif HAS_PILLOW:
                    img = Image.frombytes("RGB", (w, h), out_bytes)
                    img.save(out_p)
                return str(out_p)
            else:
                if HAS_PILLOW:
                    return Image.frombytes("RGB", (w, h), out_bytes)
                return out_bytes

        if not HAS_PILLOW:
            raise RuntimeError("Pillow required to open non-PPM formats (.png, .tif, etc.)")
        img = Image.open(p).convert("RGB")
        w, h = img.size
        rgb_bytes = img.tobytes()
        out_bytes = denoise_chroma_bytes(rgb_bytes, w, h, radius, strength, colorspace, filter_type)
        out_img = Image.frombytes("RGB", (w, h), out_bytes)
        if out_path:
            out_img.save(out_path)
            return str(out_path)
        return out_img

    # PIL Image input
    if HAS_PILLOW and isinstance(image_input, Image.Image):
        img = image_input.convert("RGB")
        w, h = img.size
        rgb_bytes = img.tobytes()
        out_bytes = denoise_chroma_bytes(rgb_bytes, w, h, radius, strength, colorspace, filter_type)
        out_img = Image.frombytes("RGB", (w, h), out_bytes)
        if out_path:
            out_img.save(out_path)
        return out_img

    # Raw tuple input: (bytes, width, height)
    if isinstance(image_input, tuple) and len(image_input) == 3:
        rgb_bytes, w, h = image_input
        out_bytes = denoise_chroma_bytes(rgb_bytes, w, h, radius, strength, colorspace, filter_type)
        if out_path:
            with open(out_path, "wb") as f:
                f.write(f"P6\n{w} {h}\n255\n".encode("ascii") + out_bytes)
        return out_bytes

    raise TypeError(f"Unsupported image input type: {type(image_input)}")


def main():
    parser = argparse.ArgumentParser(
        description="PrimeFilm 1800u / 1800i Chroma-Only Grain-Preserving Denoiser"
    )
    parser.add_argument("input", type=str, help="Input image (.png, .ppm, etc.)")
    parser.add_argument("output", type=str, help="Output image (.png, .ppm, etc.)")
    parser.add_argument("--radius", "-r", type=int, default=5,
                        help="Filter spatial radius in pixels (default: 5)")
    parser.add_argument("--strength", "-s", type=float, default=12.0,
                        help="Chroma edge-preservation filter strength (default: 12.0)")
    parser.add_argument("--colorspace", "-c", type=str, default="lab", choices=["lab", "ycbcr"],
                        help="Perceptual color space for chroma decoupling: 'lab' or 'ycbcr' (default: lab)")
    parser.add_argument("--filter", "-f", type=str, default="bilateral", choices=["bilateral", "guided"],
                        help="Filter algorithm: 'bilateral' (edge-preserving) or 'guided' (default: bilateral)")
    parser.add_argument("--benchmark", action="store_true",
                        help="Measure and display high-precision processing throughput")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"[!] Error: Input image '{args.input}' not found.", file=sys.stderr)
        sys.exit(1)

    print("=" * 70)
    print("PRIME FILM 1800i / 1800u CHROMA-ONLY GRAIN-PRESERVING DENOISER")
    print(f"Input Image : {args.input}")
    print(f"Output Image: {args.output}")
    print(f"Color Space : {args.colorspace.upper()} (Luminance Decoupled & 100% Untouched)")
    print(f"Filter Mode : {args.filter.capitalize()} | Radius: {args.radius} px | Strength: {args.strength}")
    print("=" * 70)

    t0 = time.perf_counter()
    if args.benchmark and HAS_PILLOW and Path(args.input).suffix.lower() != ".ppm":
        t_read_start = time.perf_counter()
        img = Image.open(args.input).convert("RGB")
        w, h = img.size
        rgb_bytes = img.tobytes()
        t_read = time.perf_counter() - t_read_start

        t_denoise_start = time.perf_counter()
        out_bytes = denoise_chroma_bytes(
            rgb_bytes, w, h,
            radius=args.radius, strength=args.strength,
            colorspace=args.colorspace, filter_type=args.filter
        )
        t_denoise = time.perf_counter() - t_denoise_start

        t_save_start = time.perf_counter()
        out_img = Image.frombytes("RGB", (w, h), out_bytes)
        out_img.save(args.output)
        t_save = time.perf_counter() - t_save_start
        total_time = time.perf_counter() - t0

        mp = (w * h) / 1e6
        throughput = mp / t_denoise if t_denoise > 0 else 0
        print(f"[+] Image Resolution : {w} x {h} ({mp:.2f} Megapixels)")
        print(f"[*] Benchmark Timings:")
        print(f"    - Image Decode   : {t_read:.3f} s")
        print(f"    - Chroma Filter  : {t_denoise:.3f} s  -->  Throughput: {throughput:.2f} MP/s")
        print(f"    - Image Encode   : {t_save:.3f} s")
        print(f"    - Total Wall Time: {total_time:.3f} s")
    else:
        denoise_chroma(
            args.input,
            out_path=args.output,
            radius=args.radius,
            strength=args.strength,
            colorspace=args.colorspace,
            filter_type=args.filter,
        )
        elapsed = time.perf_counter() - t0
        print(f"[+] Denoising completed in {elapsed:.3f} seconds!")
    print(f"[+] Cleaned master scan saved to: {args.output}")


if __name__ == "__main__":
    main()
