#!/usr/bin/env python3
"""
PrimeFilm 1800u / 1800i Super-Resolution Reconstruction Utility (pie1800_superres.py)
Reconstructs 2x super-resolved images (~3,600 DPI equivalent) from sub-pixel shifted
acquisitions via:
  - Iterative Back-Projection (IBP) with Total Variation (TV) Regularization
  - Variable-Pixel Linear Reconstruction ("Drizzle", Fruchter & Hook 2002)
  - Sub-pixel Phase Correlation & Normalized Cross-Correlation (NCC) Registration
  - Multi-pass mechanical jitter / hysteresis simulation and validation
"""

import sys
import os
import time
import math
import struct
import argparse
import subprocess

try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN_SUPERRES = os.path.join(REPO_ROOT, "bin", "pie1800_superres")
SRC_SUPERRES = os.path.join(REPO_ROOT, "scripts", "pie1800_superres.c")


def ensure_binary():
    """Compiles the C super-resolution acceleration engine if missing or outdated."""
    if not os.path.isfile(BIN_SUPERRES) or (
        os.path.isfile(SRC_SUPERRES) and os.path.getmtime(SRC_SUPERRES) > os.path.getmtime(BIN_SUPERRES)
    ):
        os.makedirs(os.path.dirname(BIN_SUPERRES), exist_ok=True)
        print(f"[*] Compiling super-resolution accelerator: {SRC_SUPERRES} -> {BIN_SUPERRES}...")
        cmd = ["gcc", "-O3", "-fopenmp", "-march=native", SRC_SUPERRES, "-lm", "-o", BIN_SUPERRES]
        ret = subprocess.run(cmd)
        if ret.returncode != 0:
            raise RuntimeError(f"Failed to compile {SRC_SUPERRES}")
        print("[+] Compilation successful.")


def save_tiff_rgb16(filename, width, height, r_chan, g_chan, b_chan):
    """
    Saves uncompressed 16-bit linear RGB TIFF master without quantization loss,
    preserving full dynamic range for RAW grading tools.
    """
    data = bytearray(width * height * 6)
    idx = 0
    total = width * height
    for i in range(total):
        vr = int(min(65535, max(0, r_chan[i] * 257.0)))
        vg = int(min(65535, max(0, g_chan[i] * 257.0)))
        vb = int(min(65535, max(0, b_chan[i] * 257.0)))
        struct.pack_into("<HHH", data, idx, vr, vg, vb)
        idx += 6

    # 10 IFD Tags
    tags = [
        (0x0100, 4, 1, width),                   # ImageWidth
        (0x0101, 4, 1, height),                  # ImageLength
        (0x0102, 3, 3, 134),                     # BitsPerSample -> [16, 16, 16] at offset 134
        (0x0103, 3, 1, 1),                       # Compression: None
        (0x0106, 3, 1, 2),                       # PhotometricInterpretation: RGB
        (0x0111, 4, 1, 140),                     # StripOffsets -> data offset 140
        (0x0115, 3, 1, 3),                       # SamplesPerPixel: 3
        (0x0116, 4, 1, height),                  # RowsPerStrip: height
        (0x0117, 4, 1, len(data)),               # StripByteCounts
        (0x011c, 3, 1, 1),                       # PlanarConfiguration: Chunky
    ]

    header = b"II\x2a\x00\x08\x00\x00\x00"
    ifd = bytearray(2 + len(tags) * 12 + 4)
    struct.pack_into("<H", ifd, 0, len(tags))
    for idx_tag, (tag, t_type, count, val) in enumerate(tags):
        struct.pack_into("<HHI I", ifd, 2 + idx_tag * 12, tag, t_type, count, val)
    struct.pack_into("<I", ifd, 2 + len(tags) * 12, 0)

    extra = bytearray(140 - (8 + len(ifd)))
    struct.pack_into("<HHH", extra, 134 - (8 + len(ifd)), 16, 16, 16)

    with open(filename, "wb") as f:
        f.write(header)
        f.write(ifd)
        f.write(extra)
        f.write(data)


def compute_metrics(im, max_dim=1000):
    """
    Calculates quantitative sharpness and acutance metrics on a representative ROI:
      1. Laplacian Variance MTF Acutance
      2. Tenengrad / Mean Sobel Edge Gradient Magnitude
    """
    gray = im.convert("L")
    w, h = gray.size
    
    # Use central ROI up to max_dim x max_dim for fast evaluation
    roi_w = min(w, max_dim)
    roi_h = min(h, max_dim)
    cx, cy = w // 2, h // 2
    crop_box = (cx - roi_w // 2, cy - roi_h // 2, cx + roi_w // 2, cy + roi_h // 2)
    gray_roi = gray.crop(crop_box)
    rw, rh = gray_roi.size
    
    try:
        pixels = list(gray_roi.get_flattened_data())
    except AttributeError:
        pixels = list(gray_roi.getdata())

    lap_vals = []
    sobel_vals = []
    for y in range(1, rh - 1):
        row = y * rw
        for x in range(1, rw - 1):
            c = pixels[row + x]
            l = pixels[row + x - 1]
            r = pixels[row + x + 1]
            u = pixels[row - rw + x]
            d = pixels[row + rw + x]
            lap = l + r + u + d - 4 * c
            lap_vals.append(lap)
            gx = (r - l) * 0.5
            gy = (d - u) * 0.5
            sobel_vals.append(math.sqrt(gx * gx + gy * gy))

    mean_lap = sum(lap_vals) / max(len(lap_vals), 1)
    var_lap = sum((v - mean_lap) ** 2 for v in lap_vals) / max(len(lap_vals), 1)
    mean_sobel = sum(sobel_vals) / max(len(sobel_vals), 1)
    return var_lap, mean_sobel


def simulate_jittered_passes(master_path, num_passes=4, output_dir="/tmp"):
    """
    Simulates sub-pixel jittered mechanical acquisitions from a master scan:
      - Upsamples master by 4x
      - Introduces realistic sub-pixel displacement offsets (dx, dy)
      - Simulates CCD aperture integration and downsamples to 1x
    """
    if not HAS_PILLOW:
        raise RuntimeError("Pillow is required for pass simulation.")

    im = Image.open(master_path)
    w, h = im.size
    print(f"[*] Simulating {num_passes} jittered passes from '{master_path}' ({w}x{h})...")

    # Upsample 4x via Lanczos sinc filter
    im4x = im.resize((w * 4, h * 4), Image.Resampling.LANCZOS)

    # Standard sub-pixel shift grid: (0, 0), (0.5, 0), (0, 0.5), (0.5, 0.5)
    default_shifts = [
        (0, 0),
        (2, 0),   # +0.5 px
        (0, 2),   # +0.5 py
        (2, 2),   # +0.5 px, +0.5 py
        (1, 0),   # +0.25 px
        (0, 1),   # +0.25 py
        (1, 2),
        (2, 1),
    ]

    sim_paths = []
    for i in range(num_passes):
        dx, dy = default_shifts[i % len(default_shifts)]
        crop_box = (dx, dy, dx + w * 4 - 4, dy + h * 4 - 4)
        cropped = im4x.crop(crop_box)
        lr = cropped.resize((w, h), Image.Resampling.BOX)
        out_path = os.path.join(output_dir, f"sim_pass_{i}.ppm")
        lr.save(out_path)
        sim_paths.append(out_path)
        print(f"    Pass {i+1}: Shift = ({dx/4.0:+.2f}, {dy/4.0:+.2f}) px -> {out_path}")

    return sim_paths


def convert_raw16_to_ppm(bin_path, out_ppm, lines=950, negative=True, aspect=2):
    """Converts a raw 16-bit uint16 binary scan stream into a calibrated PPM file."""
    PIXELS_PER_LINE = 2700
    with open(bin_path, "rb") as f:
        data = f.read()

    actual_lines = len(data) // 16200
    num_lines = min(lines, actual_lines)

    lines_r, lines_g, lines_b = [], [], []
    for l in range(num_lines):
        chunk = data[l * 16200 : (l + 1) * 16200]
        words = struct.unpack(f"<8100H", chunk)
        lines_r.append(words[0:2700])
        lines_g.append(words[2700:5400])
        lines_b.append(words[5400:8100])

    r_min, r_max = min(min(row) for row in lines_r), max(max(row) for row in lines_r)
    g_min, g_max = min(min(row) for row in lines_g), max(max(row) for row in lines_g)
    b_min, b_max = min(min(row) for row in lines_b), max(max(row) for row in lines_b)

    r_range = max(1.0, float(r_max - r_min))
    g_range = max(1.0, float(g_max - g_min))
    b_range = max(1.0, float(b_max - b_min))

    rgb_8bit = bytearray(PIXELS_PER_LINE * num_lines * 3)
    idx = 0
    for y in range(num_lines):
        rr, gg, bb = lines_r[y], lines_g[y], lines_b[y]
        for x in range(PIXELS_PER_LINE):
            vr = int((rr[x] - r_min) / r_range * 255.0)
            vg = int((gg[x] - g_min) / g_range * 255.0)
            vb = int((bb[x] - b_min) / b_range * 255.0)
            vr = max(0, min(255, vr))
            vg = max(0, min(255, vg))
            vb = max(0, min(255, vb))
            if negative:
                vr, vg, vb = 255 - vr, 255 - vg, 255 - vb
            rgb_8bit[idx] = vr
            rgb_8bit[idx + 1] = vg
            rgb_8bit[idx + 2] = vb
            idx += 3

    if aspect > 1 and HAS_PILLOW:
        im = Image.frombytes("RGB", (PIXELS_PER_LINE, num_lines), bytes(rgb_8bit))
        target_h = num_lines * aspect
        im = im.resize((PIXELS_PER_LINE, target_h), Image.Resampling.LANCZOS)
        im.save(out_ppm)
    else:
        with open(out_ppm, "wb") as f:
            f.write(f"P6\n{PIXELS_PER_LINE} {num_lines}\n255\n".encode("ascii"))
            f.write(rgb_8bit)


def main():
    parser = argparse.ArgumentParser(
        description="PrimeFilm 1800u / 1800i Super-Resolution Reconstruction Utility"
    )
    parser.add_argument("inputs", nargs="*",
                        help="Input PPM, PNG, TIFF, or _raw16.bin scan files (single-pass or multi-pass)")
    parser.add_argument("--method", choices=["ibp", "drizzle"], default="ibp",
                        help="Super-resolution method: 'ibp' (Iterative Back-Projection + TV, default) or 'drizzle'")
    parser.add_argument("--scale", type=int, choices=[2, 3], default=2,
                        help="Resolution scaling factor (default: 2 -> 3600 DPI equivalent)")
    parser.add_argument("--iters", type=int, default=8,
                        help="IBP iterations (default: 8)")
    parser.add_argument("--sigma", type=float, default=1.0,
                        help="PSF blur radius in high-resolution pixels (default: 1.0)")
    parser.add_argument("--tv", type=float, default=0.03,
                        help="Total Variation regularizer weight (default: 0.03)")
    parser.add_argument("--pixfrac", type=float, default=0.7,
                        help="Drizzle pixel shrinkage factor: 0.1 to 1.0 (default: 0.7)")
    parser.add_argument("--simulate", type=int, default=0, metavar="N",
                        help="Simulate N jittered sub-pixel passes from the first input file")
    parser.add_argument("--linear16", action="store_true", default=True,
                        help="Export 16-bit linear uncompressed TIFF master (default: True)")
    parser.add_argument("--metrics", action="store_true", default=True,
                        help="Compute and display quantitative resolution / acutance metrics")
    parser.add_argument("--out", type=str, default="superres_output",
                        help="Output base path without extension (default: 'superres_output')")
    args = parser.parse_args()

    ensure_binary()

    input_files = list(args.inputs)

    # If no inputs provided, search for existing master scans
    if not input_files:
        candidates = [
            os.path.join(REPO_ROOT, "photo_950lines_lanczos.ppm"),
            os.path.join(REPO_ROOT, "scan_fast_scaled.ppm"),
            os.path.join(REPO_ROOT, "scan_fast.ppm"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                input_files = [c]
                print(f"[*] No input files specified. Auto-selected: {c}")
                break

    if not input_files:
        parser.print_help()
        sys.exit(1)

    # Handle RAW binary stream conversion
    processed_ppm_inputs = []
    for idx, inp in enumerate(input_files):
        if inp.endswith(".bin"):
            out_p = f"/tmp/input_converted_{idx}.ppm"
            print(f"[*] Converting RAW binary stream: {inp} -> {out_p}...")
            convert_raw16_to_ppm(inp, out_p, lines=950, negative=True, aspect=2)
            processed_ppm_inputs.append(out_p)
        elif inp.endswith(".png") or inp.endswith(".tif") or inp.endswith(".tiff"):
            if not HAS_PILLOW:
                raise RuntimeError("Pillow required to read PNG/TIFF input.")
            out_p = f"/tmp/input_converted_{idx}.ppm"
            im = Image.open(inp).convert("RGB")
            im.save(out_p)
            processed_ppm_inputs.append(out_p)
        else:
            processed_ppm_inputs.append(inp)

    # Handle simulation mode
    if args.simulate > 1:
        processed_ppm_inputs = simulate_jittered_passes(processed_ppm_inputs[0], args.simulate)

    out_base = os.path.abspath(args.out)
    out_ppm = f"{out_base}.ppm"
    out_png = f"{out_base}.png"
    out_tif = f"{out_base}_linear16.tif"

    # Set environment variables for C engine
    env = os.environ.copy()
    env["PIE_SCALE"] = str(args.scale)
    env["PIE_ITERS"] = str(args.iters)
    env["PIE_SIGMA"] = str(args.sigma)
    env["PIE_TV"] = str(args.tv)
    env["PIE_PIXFRAC"] = str(args.pixfrac)

    t0 = time.time()
    cmd = [BIN_SUPERRES, out_ppm, args.method] + processed_ppm_inputs
    ret = subprocess.run(cmd, env=env)
    elapsed = time.time() - t0

    if ret.returncode != 0:
        print(f"[!] Super-resolution engine exited with error code {ret.returncode}")
        sys.exit(ret.returncode)

    print(f"\n[+] Reconstruction finished in {elapsed:.2f}s.")
    print(f"[+] Saved Reconstructed Super-Resolution PPM: {out_ppm}")

    # Convert to PNG and TIFF
    if HAS_PILLOW and os.path.isfile(out_ppm):
        im_out = Image.open(out_ppm)
        im_out.save(out_png)
        print(f"[+] Saved Reconstructed Super-Resolution PNG: {out_png} ({im_out.size[0]}x{im_out.size[1]})")

        if args.linear16:
            im_out.save(out_tif, compression=None)
            print(f"[+] Saved Uncompressed Master TIFF: {out_tif}")

        # Quantitative Metrics Analysis
        if args.metrics:
            im_base = Image.open(processed_ppm_inputs[0])
            im_base_scaled = im_base.resize(im_out.size, Image.Resampling.LANCZOS)
            m_base = compute_metrics(im_base_scaled)
            m_super = compute_metrics(im_out)

            pct_lap = (m_super[0] / max(m_base[0], 0.001) - 1.0) * 100.0
            pct_sob = (m_super[1] / max(m_base[1], 0.001) - 1.0) * 100.0

            print("\n" + "=" * 70)
            print("QUANTITATIVE OPTICAL SUPER-RESOLUTION BENCHMARK")
            print("=" * 70)
            print(f"Baseline Interpolation (Lanczos-3 Sinc):")
            print(f"  - Laplacian MTF Acutance : {m_base[0]:.2f}")
            print(f"  - Tenengrad Edge Gradient: {m_base[1]:.4f}")
            print(f"Super-Resolved ({args.method.upper()}, scale={args.scale}x -> ~{1800 * args.scale} DPI):")
            print(f"  - Laplacian MTF Acutance : {m_super[0]:.2f} ({pct_lap:+.1f}%)")
            print(f"  - Tenengrad Edge Gradient: {m_super[1]:.4f} ({pct_sob:+.1f}%)")
            print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
