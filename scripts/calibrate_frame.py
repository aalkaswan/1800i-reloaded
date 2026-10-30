#!/usr/bin/env python3
"""
PrimeFilm 1800u / 1800i Frame Offset & Aperture Calibration Tool
Scans a fast, full-travel preview across the carriage axis with an optical ruler
overlay so you can visually pinpoint the exact start and end steps of the film frame.
"""

import sys
import os
import time
import struct
import usb.core
import usb.util

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

VENDOR_ID = 0x05e3
PRODUCT_ID = 0x0120
EP_IN = 0x81
FULL_LINE_BYTES = 16200
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
    # Disarm motor driver / enter standby mode
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
    while not is_home(dev) and total < 2800:
        move_carriage(dev, 0x14, 50)
        total += 50
    asic_write(dev, 0x85, 0x10)
    return total

def capture_line_16bit(dev):
    asic_write(dev, 0x85, 0x12)
    asic_write(dev, 0x81, 0x00)
    wait_idle(dev)

    asic_write(dev, 0x90, 0x00)
    asic_write(dev, 0x91, 0x00)
    asic_write(dev, 0x92, 0x00)
    asic_write(dev, 0x93, 0x00)
    asic_write(dev, 0x94, 0x00)
    asic_write(dev, 0x95, 0x00)
    wait_idle(dev)

    wctl(dev, 0x83, 0x80)
    desc = struct.pack("<BBBB I", 0x00, 0x00, 0x00, 0x00, FULL_LINE_BYTES)
    wctl(dev, 0x82, desc)

    raw = bytes(dev.read(EP_IN, FULL_LINE_BYTES, timeout=4000))
    return raw

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Aperture & Offset Calibration Tool")
    parser.add_argument("--start", type=int, default=300,
                        help="Initial steps to advance forward before starting sweep (default: 300)")
    parser.add_argument("--travel", type=int, default=2100,
                        help="Total forward steps to sweep (default: 2100)")
    parser.add_argument("--step-size", type=int, default=4,
                        help="Microsteps per line (default: 4)")
    parser.add_argument("--home-first", action="store_true",
                        help="Retract to home bumper before starting (only use if carriage is out in the bay)")
    args = parser.parse_args()

    START_OFFSET = args.start
    TOTAL_TRAVEL = args.travel
    STEP_SIZE = args.step_size
    NUM_LINES = TOTAL_TRAVEL // STEP_SIZE

    print("=" * 70)
    print("PRIME FILM 1800u / 1800i APERTURE & OFFSET CALIBRATION TOOL")
    print(f"Sweep Range : {START_OFFSET} -> {START_OFFSET + TOTAL_TRAVEL} steps ({START_OFFSET*25.4/1800:.1f} -> {(START_OFFSET+TOTAL_TRAVEL)*25.4/1800:.1f} mm)")
    print(f"Resolution  : {NUM_LINES} lines @ step={STEP_SIZE} ({PIXELS_PER_LINE} px wide)")
    print("=" * 70)

    dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
    if dev is None:
        print("[!] Scanner not found!")
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

    wctl(dev, 0x8b, 0x00)
    time.sleep(0.05)
    wctl(dev, 0x8b, 0x40)
    time.sleep(0.05)
    cyberview_init(dev)
    configure_hardware(dev)

    # Optical Home Sensor Check
    if is_home(dev):
        print("[+] Optical Home Sensor: Carriage is currently docked at HOME (Step 0).")
    else:
        print("[*] Optical Home Sensor: Carriage is out in the bay. Homing to sensor...")
        retracted = auto_home(dev)
        print(f"[+] Homing complete (retracted {retracted} steps). Docked at HOME.")

    # Fast integration (1500 clocks)
    for r_lsb, r_msb in [(0x9c, 0x9d), (0x9e, 0x9f), (0xa0, 0xa1)]:
        asic_write(dev, r_lsb, 0xdc)
        asic_write(dev, r_msb, 0x05)

    for r in [0xe0, 0xe4, 0xe8]:
        asic_write(dev, r, 0x1f)
    for r in [0xe2, 0xe6, 0xea]:
        asic_write(dev, r, 0x02)

    set_exposure_limits(dev)

    # Gate clocks
    asic_write(dev, 0x98, 0x01)
    asic_write(dev, 0x99, 0x00)
    asic_write(dev, 0x9a, 0x8d)
    asic_write(dev, 0x9b, 0x2a)

    print("[*] Turning LAMP ON & warming up...")
    asic_write(dev, 0xad, 0x0b)
    asic_write(dev, 0x85, 0x30)
    time.sleep(1.0)

    total_moved = 0
    raw_lines = []

    try:
        print(f"[*] Moving carriage to start position ({START_OFFSET} steps = {START_OFFSET*25.4/1800:.1f} mm)...")
        move_carriage(dev, 0x16, START_OFFSET)
        total_moved += START_OFFSET

        print(f"[*] Scanning {NUM_LINES} calibration lines across the full film aperture...")
        t0 = time.time()

        for l in range(NUM_LINES):
            raw = capture_line_16bit(dev)
            raw_lines.append(raw)

            move_carriage(dev, 0x16, STEP_SIZE)
            total_moved += STEP_SIZE

            if (l + 1) % 50 == 0 or l == NUM_LINES - 1:
                curr_step = START_OFFSET + (l + 1) * STEP_SIZE
                curr_mm = curr_step * 25.4 / 1800.0
                print(f"    Line {l+1:3d}/{NUM_LINES} | Pos: {curr_step:4d} steps ({curr_mm:4.1f} mm)")

        print(f"[+] Scan completed in {time.time() - t0:.1f}s!")

    finally:
        if total_moved > 0 or not is_home(dev):
            print("[*] Returning carriage home via Optical Sensor...")
            retracted = auto_home(dev)
            print(f"[+] Carriage safely docked at home stop (retracted {retracted} steps).")

        print("[*] Turning LAMP OFF...")
        try:
            asic_write(dev, 0xad, 0x4b)
            asic_write(dev, 0x85, 0x10)
        except Exception:
            pass

    print("\n[*] Processing calibration preview and drawing measurement ruler...")
    lines_r = []
    lines_g = []
    lines_b = []

    for raw in raw_lines:
        words = struct.unpack(f"<{len(raw)//2}H", raw)
        lines_r.append(words[0:2700])
        lines_g.append(words[2700:5400])
        lines_b.append(words[5400:8100])

    def get_bounds(lines):
        flat = [p for line in lines for p in line]
        return min(flat), max(flat)

    r_min, r_max = get_bounds(lines_r)
    g_min, g_max = get_bounds(lines_g)
    b_min, b_max = get_bounds(lines_b)

    r_rng = max(r_max - r_min, 1)
    g_rng = max(g_max - g_min, 1)
    b_rng = max(b_max - b_min, 1)

    rgb_bytes = bytearray()
    for y in range(NUM_LINES):
        row_r = lines_r[y]
        row_g = lines_g[y]
        row_b = lines_b[y]

        for x in range(PIXELS_PER_LINE):
            vr = int((row_r[x] - r_min) / r_rng * 255.0)
            vg = int((row_g[x] - g_min) / g_rng * 255.0)
            vb = int((row_b[x] - b_min) / b_rng * 255.0)
            rgb_bytes.extend([max(0, min(255, vr)),
                              max(0, min(255, vg)),
                              max(0, min(255, vb))])

    desktop_dir = "/home/aalkaswan/Desktop/1800i-reloaded"
    out_png = f"{desktop_dir}/aperture_calibration.png"

    if HAS_PILLOW:
        img = Image.frombytes("RGB", (PIXELS_PER_LINE, NUM_LINES), bytes(rgb_bytes))
        draw = ImageDraw.Draw(img)

        # Draw ruler ticks and labels along left margin (pixels 0..200) and right margin (pixels 2500..2700)
        for l in range(NUM_LINES):
            curr_step = START_OFFSET + l * STEP_SIZE
            curr_mm = curr_step * 25.4 / 1800.0

            if curr_step % 100 == 0:
                # 100-step tick mark
                is_major = (curr_step % 500 == 0)
                tick_len = 120 if is_major else 50
                color = (255, 255, 0) if is_major else (0, 255, 255)

                draw.line([(0, l), (tick_len, l)], fill=color, width=2 if is_major else 1)
                draw.line([(PIXELS_PER_LINE - tick_len, l), (PIXELS_PER_LINE, l)], fill=color, width=2 if is_major else 1)

                if is_major:
                    label = f"STEP {curr_step} ({curr_mm:.1f}mm)"
                    draw.text((130, l - 6), label, fill=(255, 255, 0))

        img.save(out_png)
        print(f"[+] Saved Calibrated Image with Measurement Ruler: {out_png}")
    else:
        # Fallback PPM
        out_ppm = f"{desktop_dir}/aperture_calibration.ppm"
        with open(out_ppm, "wb") as f:
            f.write(f"P6\n{PIXELS_PER_LINE} {NUM_LINES}\n255\n".encode("ascii"))
            f.write(bytes(rgb_bytes))
        print(f"[+] Saved Calibration PPM: {out_ppm}")

    print("\n[+] Calibration sweep complete! Open aperture_calibration.png to see exact frame step boundaries.")

if __name__ == '__main__':
    main()
