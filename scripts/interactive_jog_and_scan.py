#!/usr/bin/env python3
"""
PrimeFilm 1800u / 1800i Interactive Carriage Positioner & Live Scanner
Allows step-by-step interactive jogging to align the optical head over the film frame,
live scanline sampling, and preview capture.
"""

import sys
import time
import struct
import usb.core
import usb.util

VENDOR_ID = 0x05e3
PRODUCT_ID = 0x0120

EP_IN = 0x81
LINE_BYTES = 5400  # 1800 pixels * 3 channels
PIXELS_PER_LINE = 1800

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

def set_window(dev, start=0, length=LINE_BYTES):
    asic_write(dev, 0x90, length & 0xff)
    asic_write(dev, 0x91, (length >> 8) & 0xff)
    asic_write(dev, 0x92, (length >> 16) & 0xff)
    asic_write(dev, 0x93, start & 0xff)
    asic_write(dev, 0x94, (start >> 8) & 0xff)
    asic_write(dev, 0x95, (start >> 16) & 0xff)

def move_carriage(dev, direction_cmd, steps):
    asic_write(dev, 0x85, direction_cmd)
    remaining = steps
    while remaining > 0:
        chunk = min(remaining, 200)
        asic_write(dev, 0x81, chunk)
        asic_write(dev, 0x83, 0x01)
        wait_idle(dev)
        remaining -= chunk
        time.sleep(0.005)

def capture_single_line(dev, exposure=2900, gain=31):
    # Set integration times
    exp_lsb = exposure & 0xff
    exp_msb = (exposure >> 8) & 0xff
    for r_lsb, r_msb in [(0x9c, 0x9d), (0x9e, 0x9f), (0xa0, 0xa1)]:
        asic_write(dev, r_lsb, exp_lsb)
        asic_write(dev, r_msb, exp_msb)

    # Set gains
    for r in [0xe0, 0xe4, 0xe8]:
        asic_write(dev, r, gain)

    # Offsets
    for r in [0xe2, 0xe6, 0xea]:
        asic_write(dev, r, 0x02)

    set_window(dev, start=0, length=LINE_BYTES)
    set_exposure_limits(dev)
    wait_idle(dev)

    # Trigger scan
    asic_write(dev, 0x85, 0x12)
    wait_idle(dev)

    # Reset read pointer to 0
    asic_write(dev, 0x93, 0x00)
    asic_write(dev, 0x94, 0x00)
    asic_write(dev, 0x95, 0x00)

    # Arm DMA
    wctl(dev, 0x83, 0x80)
    dma_desc = struct.pack("<BBBB I", 0x00, 0x00, 0x00, 0x00, LINE_BYTES)
    wctl(dev, 0x82, dma_desc)

    raw = bytes(dev.read(EP_IN, LINE_BYTES, timeout=3000))
    return raw

def save_ppm(filename, width, height, data):
    with open(filename, "wb") as f:
        header = f"P6\n{width} {height}\n255\n".encode("ascii")
        f.write(header)
        f.write(data)

def main():
    print("=" * 70)
    print("PRIME FILM 1800u / 1800i INTERACTIVE JOG & LIVE SCANNER")
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
    print("[+] Bridge in EPP Mode 0x80 & Hardware Configured!")

    lamp_is_on = False
    current_pos_steps = 0  # relative to starting position

    print("\nCommands:")
    print("  f <steps>   : Move FORWARD (e.g., 'f 1000' = ~14 mm, 'f 500' = ~7 mm)")
    print("  b <steps>   : Move BACKWARD (e.g., 'b 500')")
    print("  l           : Toggle LAMP on/off")
    print("  s           : Capture & display 1 live scanline right here")
    print("  scan <n>    : Scan <n> lines forward from current position and save PPM image")
    print("  home        : Return carriage back to starting position (0 steps)")
    print("  q           : Return to home, turn lamp off, and exit")
    print("=" * 70)

    try:
        while True:
            mm = current_pos_steps * 25.4 / 1800.0
            lamp_str = "ON" if lamp_is_on else "OFF"
            prompt = f"[Pos: {current_pos_steps} steps ({mm:.1f} mm) | Lamp: {lamp_str}] > "

            try:
                cmd_line = input(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not cmd_line:
                continue

            parts = cmd_line.split()
            cmd = parts[0].lower()

            if cmd == "q":
                break

            elif cmd == "l":
                lamp_is_on = not lamp_is_on
                if lamp_is_on:
                    print("[*] Turning LAMP ON...")
                    asic_write(dev, 0xad, 0x0b)
                    asic_write(dev, 0x85, 0x30)
                else:
                    print("[*] Turning LAMP OFF...")
                    asic_write(dev, 0xad, 0x4b)
                    asic_write(dev, 0x85, 0x10)

            elif cmd == "f":
                steps = int(parts[1]) if len(parts) > 1 else 500
                print(f"[*] Jogging FORWARD by {steps} steps ({steps * 25.4 / 1800:.1f} mm)...")
                move_carriage(dev, 0x16, steps)
                current_pos_steps += steps

            elif cmd == "b":
                steps = int(parts[1]) if len(parts) > 1 else 500
                steps = min(steps, current_pos_steps)
                print(f"[*] Jogging BACKWARD by {steps} steps ({steps * 25.4 / 1800:.1f} mm)...")
                move_carriage(dev, 0x14, steps)
                current_pos_steps -= steps

            elif cmd == "home":
                if current_pos_steps > 0:
                    print(f"[*] Returning {current_pos_steps} steps to home...")
                    move_carriage(dev, 0x14, current_pos_steps)
                    current_pos_steps = 0
                    print("[+] Returned to home.")
                else:
                    print("[*] Already at home (0 steps).")

            elif cmd == "s":
                print("[*] Capturing live scanline...")
                raw = capture_single_line(dev, exposure=2900, gain=31)
                min_v = min(raw)
                max_v = max(raw)
                avg_v = sum(raw) / len(raw)
                print(f"[+] Scanline captured ({len(raw)} bytes): Min={min_v}, Max={max_v}, Avg={avg_v:.2f}")
                print(f"    First 16 bytes: {raw[:16].hex(' ')}")
                print(f"    Center 16 bytes: {raw[2688:2704].hex(' ')}")

            elif cmd == "scan":
                n_lines = int(parts[1]) if len(parts) > 1 else 100
                print(f"[*] Scanning {n_lines} lines forward from current position...")
                if not lamp_is_on:
                    print("[*] Turning LAMP ON for scan...")
                    asic_write(dev, 0xad, 0x0b)
                    asic_write(dev, 0x85, 0x30)
                    lamp_is_on = True
                    time.sleep(1.0)

                lines_data = []
                t0 = time.time()
                for i in range(n_lines):
                    line = capture_single_line(dev, exposure=2900, gain=31)
                    lines_data.append(line)
                    move_carriage(dev, 0x16, 1)
                    current_pos_steps += 1
                    if (i + 1) % 20 == 0 or i == n_lines - 1:
                        print(f"    Scanned line {i+1}/{n_lines} (line avg={sum(line)/len(line):.1f})")

                print(f"[+] Scan finished in {time.time() - t0:.1f}s.")
                # Save PPM
                planar_img = bytearray()
                for line in lines_data:
                    r = line[0:1800]
                    g = line[1800:3600]
                    b = line[3600:5400]
                    for px in range(1800):
                        planar_img.extend((r[px], g[px], b[px]))

                out_file = "/home/aalkaswan/Desktop/1800i-reloaded/interactive_scan.ppm"
                save_ppm(out_file, PIXELS_PER_LINE, n_lines, bytes(planar_img))
                print(f"[+] Saved viewable PPM image to: {out_file}")

            else:
                print(f"[!] Unknown command '{cmd}'. Use f, b, l, s, scan, home, or q.")

    finally:
        if current_pos_steps > 0:
            print(f"\n[*] Returning carriage to home ({current_pos_steps} steps backward)...")
            move_carriage(dev, 0x14, current_pos_steps)
            print("[+] Carriage returned.")

        print("[*] Turning LAMP OFF...")
        try:
            asic_write(dev, 0xad, 0x4b)
            asic_write(dev, 0x85, 0x10)
        except Exception:
            pass

    print("[+] Done. Exited cleanly.")

if __name__ == '__main__':
    main()
