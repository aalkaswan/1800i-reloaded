#!/usr/bin/env python3
"""
PrimeFilm 1800u / 1800i Raw Scan Processor (process_raw_scan.py)
Reconstructs true full-color RGB images from planar raw scanline data.
Sensor Format: Planar RGB (2,700 Red px, 2,700 Green px, 2,700 Blue px per line)
"""

import sys
import os
import struct
import argparse

try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

PIXELS_PER_LINE = 2700
FULL_LINE_BYTES = 16200 # 2700 * 3 * 2 bytes uint16
WORDS_PER_LINE = 8100

def save_ppm(filename, width, height, rgb_bytes):
    with open(filename, "wb") as f:
        header = f"P6\n{width} {height}\n255\n".encode("ascii")
        f.write(header)
        f.write(rgb_bytes)

def main():
    parser = argparse.ArgumentParser(description="Process Planar 16-bit Raw Scans from PrimeFilm 1800u")
    parser.add_argument("input_bin", nargs="?", default="test_scan_raw16.bin",
                        help="Input raw binary file (default: test_scan_raw16.bin)")
    parser.add_argument("--out", type=str, default=None,
                        help="Output image prefix (default: derived from input)")
    parser.add_argument("--negative", action="store_true",
                        help="Invert colors for negative film")
    parser.add_argument("--stagger", type=int, default=0,
                        help="Line delay/stagger between R, G, B channels in rows (default: 0)")
    parser.add_argument("--channel-split", action="store_true",
                        help="Export separate R, G, B grayscale PNG images")
    args = parser.parse_args()

    desktop_dir = "/home/aalkaswan/Desktop/1800i-reloaded"
    bin_path = args.input_bin if os.path.isabs(args.input_bin) else os.path.join(desktop_dir, args.input_bin)

    if not os.path.exists(bin_path):
        print(f"[!] File not found: {bin_path}")
        sys.exit(1)

    file_size = os.path.getsize(bin_path)
    if file_size % FULL_LINE_BYTES != 0:
        print(f"[!] Warning: File size ({file_size}) is not an exact multiple of line size ({FULL_LINE_BYTES})")
    
    num_lines = file_size // FULL_LINE_BYTES
    print("=" * 70)
    print("PRIME FILM 1800u / 1800i RAW SCAN PROCESSOR")
    print(f"Input file   : {bin_path}")
    print(f"Total lines  : {num_lines} lines ({file_size} bytes)")
    print(f"Geometry     : {PIXELS_PER_LINE} x {num_lines} pixels (Planar RGB)")
    print(f"Film Mode    : {'Negative (Inverted)' if args.negative else 'Slide / Direct'}")
    print(f"Line Stagger : {args.stagger} rows")
    print("=" * 70)

    # Read all lines
    lines_r = []
    lines_g = []
    lines_b = []

    with open(bin_path, "rb") as f:
        for _ in range(num_lines):
            raw_line = f.read(FULL_LINE_BYTES)
            if len(raw_line) < FULL_LINE_BYTES:
                break
            words = struct.unpack(f"<{WORDS_PER_LINE}H", raw_line)
            # Channel 1: Red (samples 0..2699)
            # Channel 2: Green (samples 2700..5399)
            # Channel 3: Blue (samples 5400..8099)
            lines_r.append(words[0:2700])
            lines_g.append(words[2700:5400])
            lines_b.append(words[5400:8100])

    num_lines = len(lines_r)

    # Compute per-channel statistics
    def get_stats(lines):
        flat = [p for line in lines for p in line]
        return min(flat), max(flat), sum(flat) / len(flat)

    r_min, r_max, r_avg = get_stats(lines_r)
    g_min, g_max, g_avg = get_stats(lines_g)
    b_min, b_max, b_avg = get_stats(lines_b)

    print(f"Red   Channel: Min={r_min:5d}, Max={r_max:5d}, Avg={r_avg:.1f}")
    print(f"Green Channel: Min={g_min:5d}, Max={g_max:5d}, Avg={g_avg:.1f}")
    print(f"Blue  Channel: Min={b_min:5d}, Max={b_max:5d}, Avg={b_avg:.1f}")

    r_range = max(r_max - r_min, 1)
    g_range = max(g_max - g_min, 1)
    b_range = max(b_max - b_min, 1)

    # Output filename base
    if args.out:
        out_base = args.out if os.path.isabs(args.out) else os.path.join(desktop_dir, args.out)
    else:
        out_base = os.path.splitext(bin_path)[0]
        if out_base.endswith("_raw16"):
            out_base = out_base[:-6]

    # Stagger alignment
    # If stagger > 0, Red is at line y, Green is at y + stagger, Blue is at y + 2*stagger
    s = args.stagger
    valid_lines = num_lines - 2 * abs(s) if s != 0 else num_lines
    if valid_lines <= 0:
        print("[!] Too few lines for requested stagger amount!")
        sys.exit(1)

    rgb_interleaved = bytearray()
    for y in range(valid_lines):
        y_r = y
        y_g = y + s if s >= 0 else y - s
        y_b = y + 2 * s if s >= 0 else y

        row_r = lines_r[y_r]
        row_g = lines_g[y_g]
        row_b = lines_b[y_b]

        for x in range(PIXELS_PER_LINE):
            vr = int((row_r[x] - r_min) / r_range * 255.0)
            vg = int((row_g[x] - g_min) / g_range * 255.0)
            vb = int((row_b[x] - b_min) / b_range * 255.0)

            vr = max(0, min(255, vr))
            vg = max(0, min(255, vg))
            vb = max(0, min(255, vb))

            if args.negative:
                vr = 255 - vr
                vg = 255 - vg
                vb = 255 - vb

            rgb_interleaved.extend([vr, vg, vb])

    # Save Composite RGB image
    out_ppm = f"{out_base}_color.ppm"
    save_ppm(out_ppm, PIXELS_PER_LINE, valid_lines, bytes(rgb_interleaved))
    print(f"[+] Saved Reconstructed RGB PPM: {out_ppm}")

    if HAS_PILLOW:
        out_png = f"{out_base}_color.png"
        img = Image.frombytes("RGB", (PIXELS_PER_LINE, valid_lines), bytes(rgb_interleaved))
        img.save(out_png)
        print(f"[+] Saved Reconstructed RGB PNG: {out_png}")

        if args.channel_split:
            for name, lines, c_min, c_range in [("red", lines_r, r_min, r_range),
                                               ("green", lines_g, g_min, g_range),
                                               ("blue", lines_b, b_min, b_range)]:
                gray_bytes = bytearray()
                for line in lines:
                    for p in line:
                        v = int((p - c_min) / c_range * 255.0)
                        v = max(0, min(255, v))
                        if args.negative:
                            v = 255 - v
                        gray_bytes.append(v)
                c_img = Image.frombytes("L", (PIXELS_PER_LINE, num_lines), bytes(gray_bytes))
                c_out = f"{out_base}_{name}.png"
                c_img.save(c_out)
                print(f"[+] Saved Channel PNG: {c_out}")

    print("[+] Reconstruction complete!")

if __name__ == '__main__':
    main()
