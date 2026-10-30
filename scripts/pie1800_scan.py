#!/usr/bin/env python3
"""
PrimeFilm 1800u / 1800i Native Scanner Utility (pie1800_scan.py)
Acquires high-resolution scans at 2,700 optical RGB pixels per line,
with automatic carriage positioning, 16-bit linear sampling,
contrast normalization, negative inversion, and PNG/PPM export.
"""

import sys
import os
import time
import struct
import argparse
import subprocess
import usb.core
import usb.util

try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

try:
    from pie1800_shading import FlatFieldCalibration, apply_flat_field, load_calibration, calibrate_scanner
    HAS_SHADING = True
except ImportError:
    HAS_SHADING = False

VENDOR_ID = 0x05e3
PRODUCT_ID = 0x0120

EP_IN = 0x81
FULL_LINE_BYTES = 16200  # 0x3f48: 2700 pixels * 3 channels * 2 bytes uint16
PIXELS_PER_LINE = 2700

def wctl(dev, reg, data, timeout=1000):
    if isinstance(data, int):
        data = bytes([data])
    return dev.ctrl_transfer(0x40, 0x0c, reg, 0, data, timeout=timeout)

def rctl(dev, reg, timeout=1000):
    buf = dev.ctrl_transfer(0xc0, 0x0c, reg, 0, 1, timeout=timeout)
    return buf[0] if buf else None

def ieee_handshake_stage(dev, mode):
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
    ieee_handshake_stage(dev, 0x30)
    time.sleep(0.02)
    ieee_handshake_stage(dev, 0x00)
    time.sleep(0.02)
    ieee_handshake_stage(dev, 0x80)
    time.sleep(0.02)

def asic_write(dev, reg, val, timeout=1000):
    wctl(dev, 0x83, reg, timeout=timeout)
    wctl(dev, 0x85, val, timeout=timeout)

def asic_read(dev, reg, timeout=1000):
    wctl(dev, 0x83, reg, timeout=timeout)
    return rctl(dev, 0x84, timeout=timeout)

def wait_idle(dev, timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        val = asic_read(dev, 0x84)
        if val is not None and (val & 0x1e) == 0:
            return True
        time.sleep(0.002)
    return False

def configure_hardware(dev):
    asic_write(dev, 0xc4, 0x00)
    asic_write(dev, 0xab, 0xaa)
    asic_write(dev, 0xac, 0xca)
    asic_write(dev, 0xad, 0x4b)
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
    asic_read(dev, 0x87)
    for r in range(0xa2, 0xab):
        asic_write(dev, r, 0xff)

def move_carriage(dev, direction_cmd, steps):
    asic_write(dev, 0x85, direction_cmd)
    remaining = steps
    while remaining > 0:
        chunk = min(remaining, 200)
        asic_write(dev, 0x81, chunk)
        asic_write(dev, 0x83, 0x01)
        wait_idle(dev)
        remaining -= chunk
        time.sleep(0.004)
    # Disarm motor pulses / standby mode
    asic_write(dev, 0x85, 0x10)

def is_home(dev):
    """Optical Home Sensor: Reg 0x84 bit 5 is 0 at home dock, 1 when away."""
    s84 = asic_read(dev, 0x84)
    return s84 is not None and (s84 & 0x20) == 0

def auto_home(dev):
    """Closed-loop optical homing: stops the instant the sensor detects home."""
    if is_home(dev):
        return 0
    total = 0
    while not is_home(dev) and total < 6000:
        move_carriage(dev, 0x14, 50)
        total += 50
    asic_write(dev, 0x85, 0x10)
    return total

def capture_line_16bit(dev):
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

def capture_line_multisample(dev, num_samples=1):
    """
    Temporal multi-exposure stacking: averages N exposures at the same carriage position.
    Reduces thermal and shot noise by sqrt(N), expanding effective dynamic range by ~log2(sqrt(N)) bits.
    """
    if num_samples <= 1:
        return capture_line_16bit(dev)

    first = capture_line_16bit(dev)
    n_words = len(first) // 2
    acc = list(struct.unpack(f"<{n_words}H", first))

    for _ in range(num_samples - 1):
        nxt = capture_line_16bit(dev)
        words = struct.unpack(f"<{n_words}H", nxt)
        for i in range(n_words):
            acc[i] += words[i]

    for i in range(n_words):
        acc[i] //= num_samples

    return struct.pack(f"<{n_words}H", *acc)

def save_ppm(filename, width, height, rgb_bytes):
    with open(filename, "wb") as f:
        header = f"P6\n{width} {height}\n255\n".encode("ascii")
        f.write(header)
        f.write(rgb_bytes)

def save_tiff_rgb16(filename, width, height, r_lines, g_lines, b_lines):
    """
    Writes uncompressed 16-bit linear RGB TIFF master without quantization loss,
    preserving full 14-bit ADC dynamic range for external RAW negative grading tools
    (e.g., Negative Lab Pro, RawTherapee, Darktable).
    """
    data = bytearray(width * height * 6)
    idx = 0
    for y in range(height):
        ry = r_lines[y]
        gy = g_lines[y]
        by = b_lines[y]
        for x in range(width):
            struct.pack_into('<HHH', data, idx, ry[x], gy[x], by[x])
            idx += 6

    header = b'II\x2a\x00\x08\x00\x00\x00'
    # IFD: 10 tags
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

def main():
    parser = argparse.ArgumentParser(description="PrimeFilm 1800u / 1800i Native Image Scanner")
    parser.add_argument("--offset", type=int, default=1250,
                        help="Initial steps to advance carriage to film aperture (default: 1250)")
    parser.add_argument("--lines", type=int, default=950,
                        help="Number of motor lines to scan (default: 950 lines = 2200 max steps)")
    parser.add_argument("--aspect", type=int, default=2,
                        help="Vertical aspect ratio scaling multiplier (default: 2 for 900 DPI motor pitch)")
    parser.add_argument("--step", type=int, default=1,
                        help="Microsteps per line (default: 1)")
    parser.add_argument("--samples", type=int, default=1,
                        help="Multi-exposure temporal stacking: exposures per line to average for noise reduction (e.g. 2, 4, 8; default: 1)")
    parser.add_argument("--exposure", type=int, default=2900,
                        help="CCD integration time clocks (default: 2900 = 0x0b54)")
    parser.add_argument("--analog-balance", action="store_true",
                        help="Enable hardware analog color balancing (boosts Blue integration time to balance dense orange mask)")
    parser.add_argument("--deconvolve", action="store_true",
                        help="Apply Richardson-Lucy optical MTF deconvolution to restore lens sharpness")
    parser.add_argument("--deconv-sigma", type=float, default=1.25,
                        help="PSF blur radius for optical deconvolution (default: 1.25)")
    parser.add_argument("--deconv-iters", type=int, default=8,
                        help="Iterations for Richardson-Lucy deconvolution (default: 8)")
    parser.add_argument("--chroma-denoise", action="store_true",
                        help="Apply Chroma-Only Grain-Preserving Denoising to eliminate sensor color speckles")
    parser.add_argument("--chroma-radius", type=int, default=5,
                        help="Chroma filter spatial radius (default: 5)")
    parser.add_argument("--chroma-strength", type=float, default=12.0,
                        help="Chroma edge-preservation filter strength (default: 12.0)")
    parser.add_argument("--chroma-space", type=str, default="lab", choices=["lab", "ycbcr"],
                        help="Color space for chroma decoupling: 'lab' or 'ycbcr' (default: lab)")
    parser.add_argument("--chroma-filter", type=str, default="bilateral", choices=["bilateral", "guided"],
                        help="Filter mode: 'bilateral' or 'guided' (default: bilateral)")
    parser.add_argument("--linear16", action="store_true", default=True,
                        help="Save uncompressed 16-bit linear RGB TIFF master for RAW negative grading (default: True)")
    parser.add_argument("--no-linear16", dest="linear16", action="store_false",
                        help="Disable 16-bit linear TIFF export")
    parser.add_argument("--gain", type=int, default=31,
                        help="AFE PGA gain (default: 31 = 0x1f)")
    parser.add_argument("--negative", action="store_true",
                        help="Invert colors for negative film")
    parser.add_argument("--stagger", type=int, default=0,
                        help="Row stagger delay between R, G, B channels (default: 0)")
    parser.add_argument("--shading", type=str, nargs="?", const="none", default="none",
                        help="Flat-field calibration profile path (.json/.bin) (default: none / disabled)")
    parser.add_argument("--no-shading", dest="shading", action="store_const", const="none",
                        help="Disable flat-field shading calibration")
    parser.add_argument("--calibrate-first", action="store_true",
                        help="Run live dark & white calibration at step 100 before scanning and save profile")
    parser.add_argument("--shading-filter", choices=["hybrid", "lowpass", "raw"], default="hybrid",
                        help="Smoothing filter mode across white reference (default: hybrid)")
    parser.add_argument("--out", type=str, default="scan_output",
                        help="Output file prefix (default: scan_output)")
    args = parser.parse_args()

    # Hardware rail protection: ensure carriage never exceeds physical endstop (2260 steps)
    MAX_RAIL_STEPS = 2260
    if args.offset + args.lines * args.step > MAX_RAIL_STEPS:
        max_allowed_lines = (MAX_RAIL_STEPS - args.offset) // args.step
        print(f"[!] Warning: Requested scan ({args.offset} + {args.lines}*{args.step} = {args.offset + args.lines*args.step} steps) exceeds physical rail limit ({MAX_RAIL_STEPS})!")
        print(f"[*] Clamping to {max_allowed_lines} lines to protect carriage hardware.\n")
        args.lines = max(1, max_allowed_lines)

    print("=" * 70)
    print("PRIME FILM 1800u / 1800i NATIVE HIGH-RES SCANNER")
    print(f"Optical Width : {PIXELS_PER_LINE} pixels (RGB Interleaved, 16-bit ADC)")
    print(f"Scan Lines    : {args.lines} lines | Step Size: {args.step} microsteps")
    print(f"Aperture Offset: {args.offset} steps (~{args.offset * 25.4 / 1800:.1f} mm)")
    print(f"Temporal Stacking: {args.samples}x exposure(s) per line")
    print(f"Exposure      : {args.exposure} clocks | PGA Gain: {args.gain}")
    print(f"Analog Balance: {'Enabled (Blue Boost ~1.75x)' if args.analog_balance else 'Disabled (Uniform Exposure)'}")
    print(f"Deconvolution : {'Enabled (Richardson-Lucy sigma=' + str(args.deconv_sigma) + ')' if args.deconvolve else 'Disabled'}")
    print(f"Chroma Denoise: {'Enabled (' + args.chroma_space.upper() + ' ' + args.chroma_filter + ' r=' + str(args.chroma_radius) + ' s=' + str(args.chroma_strength) + ')' if args.chroma_denoise else 'Disabled'}")
    print(f"Film Mode     : {'Negative (Inverted)' if args.negative else 'Slide / Transparency (Direct)'}")
    print(f"Flat-Field    : {'Disabled' if args.shading == 'none' else ('Live Pre-Scan Calibration' if args.calibrate_first else f'Active ({args.shading})')}")
    print("=" * 70)

    dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
    if dev is None:
        print("[!] Scanner not found! Please check USB cable.")
        sys.exit(1)

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

    print("[*] Step 1: Initializing bridge & configuring hardware registers...")
    wctl(dev, 0x8b, 0x00)
    time.sleep(0.05)
    wctl(dev, 0x8b, 0x40)
    time.sleep(0.05)
    cyberview_init(dev)
    configure_hardware(dev)

    # Set integration times (per-channel)
    if args.analog_balance:
        # Blue integration boost to balance dense orange negative mask
        exp_r = int(args.exposure * 1.0)
        exp_g = int(args.exposure * 1.0)
        exp_b = int(args.exposure * 1.25)
        print(f"[*] Analog Exposure Balancing Active: Red={exp_r}, Green={exp_g}, Blue={exp_b}")
    else:
        exp_r = exp_g = exp_b = args.exposure

    asic_write(dev, 0x9c, exp_r & 0xff)
    asic_write(dev, 0x9d, (exp_r >> 8) & 0xff)
    asic_write(dev, 0x9e, exp_g & 0xff)
    asic_write(dev, 0x9f, (exp_g >> 8) & 0xff)
    asic_write(dev, 0xa0, exp_b & 0xff)
    asic_write(dev, 0xa1, (exp_b >> 8) & 0xff)

    # Set gains and offsets
    for r in [0xe0, 0xe4, 0xe8]:
        asic_write(dev, r, args.gain)
    for r in [0xe2, 0xe6, 0xea]:
        asic_write(dev, r, 0x02)

    # Exposure limits
    set_exposure_limits(dev)

    # CCD Sampling Gate & Clock Generator (0x10003e72)
    asic_write(dev, 0x98, 0x01)
    asic_write(dev, 0x99, 0x00)
    asic_write(dev, 0x9a, 0x8d)
    asic_write(dev, 0x9b, 0x2a)

    # Optical Home Sensor Check & Alignment
    if is_home(dev):
        print("[+] Optical Home Sensor: Carriage is currently docked at HOME (Step 0).")
    else:
        print("[*] Optical Home Sensor: Aligning carriage to optical home stop...")
        retracted = auto_home(dev)
        print(f"[+] Homing complete (retracted {retracted} steps). Docked at HOME.")

    # Flat-Field Calibration Setup
    shading_profile = None
    if HAS_SHADING and args.shading != "none":
        calib_file = None
        if args.calibrate_first:
            print("\n[*] Flat-Field Calibration: Running live pre-scan calibration...")
            calib_file = "shading_calib.json"
            shading_profile = calibrate_scanner(
                dev, num_dark=8, num_white=8, dock_step=100,
                exposure=args.exposure, gain=args.gain,
                analog_balance=args.analog_balance,
                filter_mode=args.shading_filter, target_white=65535.0,
                save_path=calib_file
            )
        elif args.shading != "auto":
            calib_file = args.shading
        else:
            repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            candidates = [
                "shading_calib.json", "shading_calib.bin",
                os.path.join(repo_root, "shading_calib.json"),
                os.path.join(repo_root, "shading_calib.bin"),
            ]
            for cand in candidates:
                if os.path.isfile(cand):
                    calib_file = cand
                    break

        if calib_file and shading_profile is None and os.path.isfile(calib_file):
            try:
                shading_profile = load_calibration(calib_file)
                print(f"[+] Loaded Flat-Field Calibration Profile: {calib_file}")
            except Exception as e:
                print(f"[!] Warning: Failed loading shading calibration {calib_file}: {e}")

    print("[*] Step 2: Turning LAMP ON & warming up...")
    asic_write(dev, 0xad, 0x0b)
    asic_write(dev, 0x85, 0x30)
    time.sleep(1.5)

    total_steps_moved = 0
    try:
        if args.offset > 0:
            print(f"[*] Step 3: Advancing carriage to aperture offset ({args.offset} steps)...")
            move_carriage(dev, 0x16, args.offset)
            total_steps_moved += args.offset

        print(f"\n[*] Step 4: Starting scan acquisition ({args.lines} lines @ 2,700 px width)...")
        t_start = time.time()

        all_lines_16bit = []
        try:
            for line_num in range(args.lines):
                # Capture line with optional temporal multi-exposure stacking
                raw_line = capture_line_multisample(dev, num_samples=args.samples)
                all_lines_16bit.append(raw_line)

                # Advance motor
                move_carriage(dev, 0x16, args.step)
                total_steps_moved += args.step

                if (line_num + 1) % 25 == 0 or line_num == args.lines - 1:
                    elapsed = time.time() - t_start
                    rate = (line_num + 1) / elapsed if elapsed > 0 else 0
                    print(f"    Line {line_num + 1:4d}/{args.lines} captured ({rate:.1f} lines/s)")
        except KeyboardInterrupt:
            print(f"\n[!] Interrupted by user! Saving {len(all_lines_16bit)} lines scanned so far...")

        actual_lines = len(all_lines_16bit)
        if actual_lines == 0:
            print("[!] No lines captured.")
            return

        total_elapsed = time.time() - t_start
        print(f"[+] {actual_lines} lines acquired in {total_elapsed:.1f}s ({actual_lines / max(total_elapsed, 0.001):.1f} lines/s)!")

        print("\n[*] Step 5: Post-processing planar optical data (2,700 px x 3 channels)...")
        lines_r = []
        lines_g = []
        lines_b = []

        for raw in all_lines_16bit:
            words = struct.unpack(f"<{len(raw)//2}H", raw)
            lines_r.append(words[0:2700])
            lines_g.append(words[2700:5400])
            lines_b.append(words[5400:8100])

        if shading_profile is not None:
            print("[*] Step 5a: Applying Flat-Field Shading Correction (PRNU & DSNU subtraction)...")
            lines_r, lines_g, lines_b = apply_flat_field(
                lines_r, lines_g, lines_b, shading_profile, clip=True, out_dtype="uint16"
            )

        def get_channel_bounds(lines, p_low=1, p_high=99):
            sample = []
            stride = max(1, len(lines) // 100)
            for line in lines[::stride]:
                sample.extend(line[::8])
            sample.sort()
            idx_low = int(len(sample) * p_low / 100.0)
            idx_high = int(len(sample) * p_high / 100.0)
            return max(sample[idx_low], 1), max(sample[idx_high], sample[idx_low] + 1)

        r_min, r_max = get_channel_bounds(lines_r)
        g_min, g_max = get_channel_bounds(lines_g)
        b_min, b_max = get_channel_bounds(lines_b)

        print(f"    Red   Channel: Min={r_min}, Max={r_max}")
        print(f"    Green Channel: Min={g_min}, Max={g_max}")
        print(f"    Blue  Channel: Min={b_min}, Max={b_max}")

        r_range = max(r_max - r_min, 1)
        g_range = max(g_max - g_min, 1)
        b_range = max(b_max - b_min, 1)

        # Stagger row adjustment
        s = args.stagger
        valid_lines = actual_lines - 2 * abs(s) if s != 0 else actual_lines
        if valid_lines <= 0:
            valid_lines = actual_lines
            s = 0

        rgb_8bit = bytearray()
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

                rgb_8bit.extend([vr, vg, vb])

        # Output file paths
        if os.path.isabs(args.out):
            out_base = args.out
        else:
            out_base = os.path.abspath(args.out)

        out_ppm = f"{out_base}.ppm"
        save_ppm(out_ppm, PIXELS_PER_LINE, valid_lines, bytes(rgb_8bit))
        print(f"[+] Saved Reconstructed RGB PPM: {out_ppm}")

        img = None
        if HAS_PILLOW:
            out_png = f"{out_base}.png"
            img = Image.frombytes("RGB", (PIXELS_PER_LINE, valid_lines), bytes(rgb_8bit))
            if args.aspect > 1:
                target_height = valid_lines * args.aspect
                img = img.resize((PIXELS_PER_LINE, target_height), Image.Resampling.LANCZOS)
                print(f"[*] Applied {args.aspect}x optical aspect correction (Lanczos) -> {PIXELS_PER_LINE}x{target_height}")
            img.save(out_png)
            print(f"[+] Saved Reconstructed RGB PNG: {out_png}")

        # Save 16-bit Linear Pro TIFF master
        if args.linear16:
            out_tif = f"{out_base}_linear16.tif"
            save_tiff_rgb16(out_tif, PIXELS_PER_LINE, valid_lines, lines_r, lines_g, lines_b)
            print(f"[+] Saved 16-bit Linear Pro TIFF: {out_tif}")

        # Optical Point Spread Function (PSF) Deconvolution
        if args.deconvolve:
            repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            deconv_bin = os.path.join(repo_root, "bin", "pie1800_deconv")
            if os.path.isfile(deconv_bin):
                out_deconv_ppm = f"{out_base}_deconv.ppm"
                out_deconv_png = f"{out_base}_deconv.png"
                print(f"\n[*] Step 5b: Applying Richardson-Lucy Optical Deconvolution (sigma={args.deconv_sigma}, iters={args.deconv_iters})...")
                # Deconvolve the aspect-scaled image if aspect > 1 or the base PPM
                ppm_to_deconv = out_ppm
                if args.aspect > 1 and img is not None:
                    ppm_to_deconv = f"{out_base}_scaled.ppm"
                    img.save(ppm_to_deconv)
                ret = subprocess.run([deconv_bin, ppm_to_deconv, out_deconv_ppm, str(args.deconv_sigma), str(args.deconv_iters)])
                if ret.returncode == 0:
                    print(f"[+] Saved Deconvolved PPM: {out_deconv_ppm}")
                    if HAS_PILLOW:
                        try:
                            dec_img = Image.open(out_deconv_ppm)
                            dec_img.save(out_deconv_png)
                            print(f"[+] Saved Deconvolved PNG: {out_deconv_png}")
                        except Exception as e:
                            print(f"[!] Warning converting deconvolved PPM to PNG: {e}")
            else:
                print(f"[!] Notice: {deconv_bin} not found. Deconvolution skipped.")

        # Step 5c: Chroma-Only Grain-Preserving Denoising
        if args.chroma_denoise:
            repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            chroma_bin = os.path.join(repo_root, "bin", "pie1800_chroma_denoise")
            ppm_to_denoise = out_ppm
            if args.deconvolve and 'out_deconv_ppm' in locals() and os.path.isfile(out_deconv_ppm):
                ppm_to_denoise = out_deconv_ppm
            elif args.aspect > 1 and img is not None:
                ppm_to_denoise = f"{out_base}_scaled.ppm"
                if not os.path.isfile(ppm_to_denoise):
                    img.save(ppm_to_denoise)

            out_clean_ppm = f"{out_base}_clean.ppm" if not args.deconvolve else f"{out_base}_deconv_clean.ppm"
            out_clean_png = f"{out_base}_clean.png" if not args.deconvolve else f"{out_base}_deconv_clean.png"

            print(f"\n[*] Step 5c: Applying Chroma-Only Grain-Preserving Denoising ({args.chroma_space.upper()}, radius={args.chroma_radius}, strength={args.chroma_strength})...")
            if os.path.isfile(chroma_bin):
                ret = subprocess.run([
                    chroma_bin, ppm_to_denoise, out_clean_ppm,
                    str(args.chroma_radius), str(args.chroma_strength),
                    args.chroma_space, args.chroma_filter
                ])
                if ret.returncode == 0:
                    print(f"[+] Saved Clean PPM: {out_clean_ppm}")
                    if HAS_PILLOW:
                        try:
                            clean_img = Image.open(out_clean_ppm)
                            clean_img.save(out_clean_png)
                            print(f"[+] Saved Clean PNG: {out_clean_png}")
                        except Exception as e:
                            print(f"[!] Warning converting clean PPM to PNG: {e}")
            else:
                try:
                    sys.path.insert(0, os.path.join(repo_root, "scripts"))
                    from pie1800_chroma_denoise import denoise_chroma
                    denoise_chroma(
                        ppm_to_denoise, out_path=out_clean_ppm,
                        radius=args.chroma_radius, strength=args.chroma_strength,
                        colorspace=args.chroma_space, filter_type=args.chroma_filter
                    )
                    print(f"[+] Saved Clean PPM: {out_clean_ppm}")
                    if HAS_PILLOW:
                        clean_img = Image.open(out_clean_ppm)
                        clean_img.save(out_clean_png)
                        print(f"[+] Saved Clean PNG: {out_clean_png}")
                except Exception as e:
                    print(f"[!] Warning during chroma denoising: {e}")

        # Save raw 16-bit data
        out_bin = f"{out_base}_raw16.bin"
        with open(out_bin, "wb") as f:
            f.write(b"".join(all_lines_16bit))
        print(f"[+] Saved Raw 16-bit Binary Stream: {out_bin}")

    finally:
        if total_steps_moved > 0 or not is_home(dev):
            print("\n[*] Step 6: Returning carriage home via Optical Sensor...")
            retracted = auto_home(dev)
            print(f"[+] Carriage safely docked at home (retracted {retracted} steps).")

        print("[*] Turning LAMP OFF...")
        try:
            asic_write(dev, 0xad, 0x4b)
            asic_write(dev, 0x85, 0x10)
            print("[+] Lamp turned OFF.")
        except Exception:
            pass

    print("\n[+] Scan session completed successfully!")

if __name__ == '__main__':
    main()
