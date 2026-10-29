#!/usr/bin/env python3
"""
PrimeFilm 1800u / 1800i Multi-Line Preview & Image Scanner
Captures N scanlines @ 1800 DPI and generates viewable PPM and raw binary files.
Reconstructed from PF1800U.dll (functions 0x10002410, 0x10002520, 0x10002920, 0x100035a0).
"""

import sys
import os
import time
import struct
import argparse
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

def set_exposure_limits(dev, r_limit=0xffffff, g_limit=0xffffff, b_limit=0xffffff):
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

def set_window(dev, start=0, length=LINE_BYTES):
    asic_write(dev, 0x90, length & 0xff)
    asic_write(dev, 0x91, (length >> 8) & 0xff)
    asic_write(dev, 0x92, (length >> 16) & 0xff)
    asic_write(dev, 0x93, start & 0xff)
    asic_write(dev, 0x94, (start >> 8) & 0xff)
    asic_write(dev, 0x95, (start >> 16) & 0xff)

def step_motor_forward(dev, steps=1):
    """Step motor forward into scan area (0x10002638 / 0x10002cbb: 0x85 -> 0x16)."""
    asic_write(dev, 0x85, 0x16)
    asic_write(dev, 0x81, steps)
    asic_write(dev, 0x83, 0x01)
    wait_idle(dev)
    time.sleep(0.005)

def step_motor_backward(dev, steps=1):
    """Step motor backward toward home stop (0x1000263c / 0x1000286c: 0x85 -> 0x14)."""
    asic_write(dev, 0x85, 0x14)
    asic_write(dev, 0x81, steps)
    asic_write(dev, 0x83, 0x01)
    wait_idle(dev)
    time.sleep(0.005)

def save_ppm(filename, width, height, data):
    """Save raw RGB data as binary Netpbm PPM."""
    with open(filename, "wb") as f:
        header = f"P6\n{width} {height}\n255\n".encode("ascii")
        f.write(header)
        f.write(data)

def main():
    parser = argparse.ArgumentParser(description="PrimeFilm 1800u / 1800i Preview & Image Scanner")
    parser.add_argument("--lines", type=int, default=100, help="Number of scan lines to capture (default: 100)")
    parser.add_argument("--step", type=int, default=1, help="Motor steps between lines (default: 1)")
    parser.add_argument("--exposure", type=int, default=2900, help="CCD integration time clocks (default: 2900 = 0x0b54)")
    parser.add_argument("--gain", type=int, default=0x1f, help="AFE PGA gain 0..63 (default: 31 = 0x1f)")
    parser.add_argument("--out", type=str, default="preview", help="Output filename prefix (default: preview)")
    args = parser.parse_args()

    num_lines = args.lines
    step_size = args.step

    print("=" * 70)
    print("PRIME FILM 1800u / 1800i MULTI-LINE SCANNER")
    print(f"Acquisition: {num_lines} lines @ 1800 DPI (Width: {PIXELS_PER_LINE} px, Line: {LINE_BYTES} bytes)")
    print(f"Exposure Clocks: {args.exposure}, PGA Gain: 0x{args.gain:02x}, Motor Step: {step_size}")
    print("=" * 70)

    print(f"[*] Connecting to USB device {VENDOR_ID:04x}:{PRODUCT_ID:04x}...")
    dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
    if dev is None:
        print("[!] Scanner not found! Check USB connection.")
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

    print("[*] Initializing GL640USB transceiver & CyberView EPP Mode 0x80...")
    wctl(dev, 0x8b, 0x00)
    time.sleep(0.05)
    wctl(dev, 0x8b, 0x40)
    time.sleep(0.05)
    cyberview_init(dev)
    print("[+] Bridge in EPP Data Mode 0x80!")

    configure_hardware(dev)

    print("\n[*] Turning LAMP ON & Configuring Exposure/AFE...")
    asic_write(dev, 0xad, 0x0b)
    asic_write(dev, 0x85, 0x30)  # Lamp ON
    time.sleep(1.0)  # Lamp warm-up stabilization

    # Exposure configuration
    exp_lsb = args.exposure & 0xff
    exp_msb = (args.exposure >> 8) & 0xff
    asic_write(dev, 0x9c, exp_lsb)
    asic_write(dev, 0x9d, exp_msb)
    asic_write(dev, 0x9e, exp_lsb)
    asic_write(dev, 0x9f, exp_msb)
    asic_write(dev, 0xa0, exp_lsb)
    asic_write(dev, 0xa1, exp_msb)

    # Gains and offsets
    asic_write(dev, 0xe0, args.gain)
    asic_write(dev, 0xe4, args.gain)
    asic_write(dev, 0xe8, args.gain)
    asic_write(dev, 0xe2, 0x02)
    asic_write(dev, 0xe6, 0x02)
    asic_write(dev, 0xea, 0x02)

    set_window(dev, start=0, length=LINE_BYTES)
    set_exposure_limits(dev)
    wait_idle(dev)

    all_lines = []
    print(f"\n[*] Starting scan acquisition loop ({num_lines} lines)...")
    dma_desc = struct.pack("<BBBB I", 0x00, 0x00, 0x01, 0x00, LINE_BYTES)

    try:
        t_start = time.time()
        for line_idx in range(num_lines):
            # 1. Trigger exposure
            asic_write(dev, 0x85, 0x12)
            if not wait_idle(dev, timeout=2.0):
                print(f"[!] Warning: Line {line_idx} exposure timeout")

            # 2. Setup DMA transfer
            asic_write(dev, 0x93, 0x00)
            asic_write(dev, 0x94, 0x00)
            asic_write(dev, 0x95, 0x00)
            wctl(dev, 0x83, 0x80)
            wctl(dev, 0x82, dma_desc)

            # 3. Read bulk line
            raw_data = bytes(dev.read(EP_IN, LINE_BYTES, timeout=3000))
            all_lines.append(raw_data)

            # 4. Advance motor
            step_motor_forward(dev, steps=step_size)

            if (line_idx + 1) % 10 == 0 or line_idx == num_lines - 1:
                elapsed = time.time() - t_start
                rate = (line_idx + 1) / elapsed if elapsed > 0 else 0
                avg_val = sum(raw_data) / len(raw_data)
                print(f"    Line {line_idx + 1:4d}/{num_lines} acquired ({rate:.1f} lines/s, line avg={avg_val:.1f})")

        print(f"[+] All {num_lines} lines captured successfully in {time.time() - t_start:.2f}s!")

        raw_all = b"".join(all_lines)
        out_raw = f"/home/aalkaswan/Desktop/1800i-reloaded/{args.out}_raw.bin"
        with open(out_raw, "wb") as f:
            f.write(raw_all)
        print(f"[+] Saved raw binary capture: {out_raw}")

        # Planar interpretation (1800 R, 1800 G, 1800 B)
        planar_image = bytearray()
        for line in all_lines:
            r = line[0:1800]
            g = line[1800:3600]
            b = line[3600:5400]
            for i in range(1800):
                planar_image.extend((r[i], g[i], b[i]))

        out_planar = f"/home/aalkaswan/Desktop/1800i-reloaded/{args.out}_planar.ppm"
        save_ppm(out_planar, PIXELS_PER_LINE, num_lines, bytes(planar_image))
        print(f"[+] Saved Planar RGB PPM: {out_planar}")

        # Interleaved interpretation (R0, G0, B0, ...)
        out_interleaved = f"/home/aalkaswan/Desktop/1800i-reloaded/{args.out}_interleaved.ppm"
        save_ppm(out_interleaved, PIXELS_PER_LINE, num_lines, raw_all)
        print(f"[+] Saved Interleaved RGB PPM: {out_interleaved}")

        print("\n[*] Carriage return: Returning carriage back to start...")
        step_motor_backward(dev, steps=num_lines * step_size)
        print("[+] Carriage returned.")

    except Exception as e:
        print(f"[!] Scan error: {e}")

    finally:
        print("\n[*] Turning LAMP OFF & Entering Standby...")
        try:
            asic_write(dev, 0xad, 0x4b)
            asic_write(dev, 0x85, 0x10)  # Lamp OFF
            print("[+] Lamp turned OFF.")
        except Exception:
            pass

    print("[+] Scanner session completed.")

if __name__ == '__main__':
    main()
