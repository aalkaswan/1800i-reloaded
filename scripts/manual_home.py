#!/usr/bin/env python3
"""
PrimeFilm 1800u / 1800i Manual Carriage Return & Homing Tool (manual_home.py)
Manually retracts the carriage backwards toward the home stop bumper in safe increments,
shuts off the lamp, and resets the scanner state.
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

def step_backward(dev, steps):
    """Retracts carriage backwards in direction 0x14 toward home dock."""
    asic_write(dev, 0x85, 0x14)
    remaining = steps
    while remaining > 0:
        chunk = min(remaining, 100)
        asic_write(dev, 0x81, chunk)
        asic_write(dev, 0x83, 0x01)
        wait_idle(dev)
        remaining -= chunk
        time.sleep(0.005)

def step_forward(dev, steps):
    """Advances carriage forward in direction 0x16 into bay."""
    asic_write(dev, 0x85, 0x16)
    remaining = steps
    while remaining > 0:
        chunk = min(remaining, 100)
        asic_write(dev, 0x81, chunk)
        asic_write(dev, 0x83, 0x01)
        wait_idle(dev)
        remaining -= chunk
        time.sleep(0.005)

def lamp_off(dev):
    try:
        asic_write(dev, 0xad, 0x4b)
        asic_write(dev, 0x85, 0x10)
    except Exception:
        pass

def main():
    parser = argparse.ArgumentParser(description="Manual Carriage Homing & Reset Tool")
    parser.add_argument("steps", type=int, nargs="?", default=None,
                        help="Number of steps to move backward to reach home (e.g. 500, 1000, 2000)")
    parser.add_argument("-i", "--interactive", action="store_true",
                        help="Interactive step-by-step nudging mode")
    args = parser.parse_args()

    print("=" * 70)
    print("PRIME FILM 1800u / 1800i MANUAL HOMING TOOL")
    print("=" * 70)

    dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
    if dev is None:
        print("[!] Scanner not found! Check USB cable.")
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

    # Always ensure lamp is off
    lamp_off(dev)

    # Initial status
    status_86 = asic_read(dev, 0x86)
    status_84 = asic_read(dev, 0x84)
    print(f"[*] Initial Status: Reg 0x86 = 0x{status_86:02x}, Reg 0x84 = 0x{status_84:02x}")

    if args.steps is not None and not args.interactive:
        steps = args.steps
        print(f"[*] Retracting carriage BACKWARD by {steps} steps ({steps * 25.4 / 1800:.1f} mm)...")
        step_backward(dev, steps)
        print(f"[+] Carriage moved {steps} steps backward.")
        lamp_off(dev)
        print("[+] Lamp turned OFF. Done.")
        return

    # Interactive mode
    print("\n--- INTERACTIVE NUDGE MODE ---")
    print("Controls:")
    print("  [Enter] or 'b' : Nudge backward 200 steps (2.8 mm)")
    print("  'B'            : Retract backward 500 steps (7.1 mm)")
    print("  'bb'           : Retract backward 1000 steps (14.1 mm)")
    print("  'f'            : Nudge forward 200 steps (2.8 mm)")
    print("  'q'            : Quit")
    print("---------------------------------")

    total_backed = 0
    try:
        while True:
            cmd = input(f"[Retracted: {total_backed} steps | Status 0x86: 0x{asic_read(dev, 0x86):02x}] > ").strip()
            if cmd == "q":
                break
            elif cmd == "" or cmd == "b":
                step_backward(dev, 200)
                total_backed += 200
                print(f"  <- Backed 200 steps (total: {total_backed})")
            elif cmd == "B":
                step_backward(dev, 500)
                total_backed += 500
                print(f"  <-- Backed 500 steps (total: {total_backed})")
            elif cmd == "bb":
                step_backward(dev, 1000)
                total_backed += 1000
                print(f"  <--- Backed 1000 steps (total: {total_backed})")
            elif cmd == "f":
                step_forward(dev, 200)
                total_backed -= 200
                print(f"  -> Forward 200 steps (total: {total_backed})")
            elif cmd.isdigit():
                n = int(cmd)
                step_backward(dev, n)
                total_backed += n
                print(f"  <- Backed {n} steps (total: {total_backed})")
            else:
                print("Unknown command. Type 'b' (200), 'B' (500), 'bb' (1000), 'f' (forward), or 'q' (quit).")
    finally:
        lamp_off(dev)
        print(f"\n[+] Finished. Total retracted: {total_backed} steps. Lamp OFF.")

if __name__ == '__main__':
    main()
