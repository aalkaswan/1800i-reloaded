#!/usr/bin/env python3
"""
PrimeFilm 1800u / 1800i Home Sensor Diagnostic Tool (test_home_sensor.py)
Monitors registers 0x86 and 0x84 during small forward and backward steps
to determine the exact bit corresponding to the physical home sensor.
"""

import sys
import time
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

def move_steps(dev, direction, steps):
    asic_write(dev, 0x85, direction)
    asic_write(dev, 0x81, steps)
    asic_write(dev, 0x83, 0x01)
    wait_idle(dev)
    time.sleep(0.01)

def print_status(dev, label):
    s86 = asic_read(dev, 0x86)
    s84 = asic_read(dev, 0x84)
    b86 = f"{s86:08b}" if s86 is not None else "None"
    b84 = f"{s84:08b}" if s84 is not None else "None"
    print(f"  {label:<30} -> Reg 0x86: 0x{s86:02x} ({b86}b) | Reg 0x84: 0x{s84:02x} ({b84}b)")
    return s86, s84

def main():
    print("=" * 70)
    print("PRIME FILM 1800u / 1800i HOME SENSOR PROBE")
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

    # Basic setup
    asic_write(dev, 0x86, 0x10)

    print("[*] Current Status:")
    print_status(dev, "Current position")

    print("\n[*] Stepping FORWARD by 200 steps (away from bumper)...")
    move_steps(dev, 0x16, 200)
    print_status(dev, "After 200 steps forward")

    print("\n[*] Stepping FORWARD by another 200 steps (400 total)...")
    move_steps(dev, 0x16, 200)
    print_status(dev, "After 400 steps forward")

    print("\n[*] Stepping BACKWARD by 200 steps...")
    move_steps(dev, 0x14, 200)
    print_status(dev, "After 200 steps back")

    print("\n[*] Stepping BACKWARD by 200 steps (back to start)...")
    move_steps(dev, 0x14, 200)
    print_status(dev, "Returned to start")

    print("\n[+] Done.")

if __name__ == '__main__':
    main()
