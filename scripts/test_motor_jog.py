#!/usr/bin/env python3
"""
PrimeFilm 1800u / 1800i Motor Jog and Calibration Utility
Tests motor movement in both directions with distance control and status monitoring.
"""

import sys
import time
import argparse
import usb.core
import usb.util

VENDOR_ID = 0x05e3
PRODUCT_ID = 0x0120

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

def move_carriage(dev, direction_cmd, steps):
    """
    Move motor using chunked steps (up to 255 per hardware chunk).
    direction_cmd: 0x16 (Forward / Scan direction) or 0x14 (Backward / Home direction)
    """
    dir_name = "FORWARD (0x16)" if direction_cmd == 0x16 else "BACKWARD (0x14)"
    print(f"[*] Moving {dir_name} by {steps} steps (~{steps * 25.4 / 1800:.2f} mm)...")

    # Set motor direction in register 0x85
    asic_write(dev, 0x85, direction_cmd)

    remaining = steps
    while remaining > 0:
        chunk = min(remaining, 200)
        # Write step count to 0x81
        asic_write(dev, 0x81, chunk)
        # Trigger step in 0x83
        asic_write(dev, 0x83, 0x01)
        wait_idle(dev, timeout=3.0)
        remaining -= chunk
        time.sleep(0.005)

    status_86 = asic_read(dev, 0x86)
    status_84 = asic_read(dev, 0x84)
    print(f"[+] Movement complete. Status reg 0x86: 0x{status_86:02x}, reg 0x84: 0x{status_84:02x}")

def main():
    parser = argparse.ArgumentParser(description="PrimeFilm 1800u / 1800i Motor Jog Utility")
    parser.add_argument("direction", choices=["forward", "backward", "test"],
                        help="'forward' (0x16), 'backward' (0x14), or 'test' (forward then back)")
    parser.add_argument("--steps", type=int, default=500,
                        help="Number of microsteps to move (default: 500 = ~7.0 mm)")
    args = parser.parse_args()

    print("=" * 70)
    print("PRIME FILM 1800u / 1800i MOTOR DIRECTION & JOG UTILITY")
    print(f"Action: {args.direction.upper()} ({args.steps} steps = {args.steps * 25.4 / 1800:.2f} mm)")
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

    wctl(dev, 0x8b, 0x00)
    time.sleep(0.05)
    wctl(dev, 0x8b, 0x40)
    time.sleep(0.05)
    cyberview_init(dev)
    print("[+] Bridge in EPP Data Mode 0x80!")

    # Initial sensor status
    s86 = asic_read(dev, 0x86)
    print(f"[*] Initial Status (reg 0x86): 0x{s86:02x}")

    try:
        if args.direction == "forward":
            # 0x16 moves forward into the scan bed
            move_carriage(dev, 0x16, args.steps)

        elif args.direction == "backward":
            # 0x14 moves backward toward the home bumper
            move_carriage(dev, 0x14, args.steps)

        elif args.direction == "test":
            print("\n--- PHASE 1: Moving FORWARD (0x16) into scan area ---")
            move_carriage(dev, 0x16, args.steps)
            print("[*] Pausing 2 seconds (look at the carriage)...")
            time.sleep(2.0)

            print("\n--- PHASE 2: Moving BACKWARD (0x14) toward home ---")
            move_carriage(dev, 0x14, args.steps)
            print("[+] Carriage returned to original position.")

    except Exception as e:
        print(f"[!] Error: {e}")

    print("\n[+] Done.")

if __name__ == '__main__':
    main()
