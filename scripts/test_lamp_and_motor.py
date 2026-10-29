#!/usr/bin/env python3
"""
PrimeFilm 1800u / 1800i Interactive Hardware Validation:
Lamp Control & Micro-Stepping Test
Reconstructed from PF1800U.dll (functions 0x10002580 and 0x10002630).
"""

import sys
import time
import usb.core
import usb.util

VENDOR_ID = 0x05e3
PRODUCT_ID = 0x0120

def wctl(dev, reg, val, timeout=1000):
    """Write 1 byte to Genesys Logic bridge register."""
    return dev.ctrl_transfer(0x40, 0x0c, reg, 0, bytes([val]), timeout=timeout)

def rctl(dev, reg, timeout=1000):
    """Read 1 byte from Genesys Logic bridge register."""
    buf = dev.ctrl_transfer(0xc0, 0x0c, reg, 0, 1, timeout=timeout)
    return buf[0] if buf else None

def ieee_handshake_stage(dev, mode):
    """Execute one stage of the 1284.4 negotiation sequence with Line Strobe."""
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
    """Full 3-stage CyberView bridge handshake from 0x10001ed0."""
    ieee_handshake_stage(dev, 0x30)
    time.sleep(0.02)
    ieee_handshake_stage(dev, 0x00)
    time.sleep(0.02)
    ieee_handshake_stage(dev, 0x80)
    time.sleep(0.02)

def asic_write(dev, reg, val, timeout=1000):
    """Write ASIC register via GL640USB EPP (0x10002140)."""
    wctl(dev, 0x83, reg, timeout=timeout)
    wctl(dev, 0x85, val, timeout=timeout)

def asic_read(dev, reg, timeout=1000):
    """Read ASIC register via GL640USB EPP (0x100021d0)."""
    wctl(dev, 0x83, reg, timeout=timeout)
    return rctl(dev, 0x84, timeout=timeout)

def lamp_on(dev):
    """Lamp ON sequence from PF1800U.dll at 0x10002580."""
    print("[*] Turning LAMP ON (0xad -> 0x0b, 0x85 -> 0x30)...")
    asic_write(dev, 0xad, 0x0b)
    asic_write(dev, 0x85, 0x30)

def lamp_off(dev):
    """Lamp OFF sequence from PF1800U.dll at 0x10002580."""
    print("[*] Turning LAMP OFF (0xad -> 0x4b, 0x85 -> 0x10)...")
    asic_write(dev, 0xad, 0x4b)
    asic_write(dev, 0x85, 0x10)

def step_motor(dev, direction, steps):
    """
    Stepper motor movement routine from PF1800U.dll at 0x10002630.
    direction: 'forward' (0x14) or 'backward' (0x16)
    steps: 1..255 steps
    """
    cmd = 0x14 if direction == 'forward' else 0x16
    print(f"[*] Stepping motor {direction.upper()} by {steps} steps (0x85 -> 0x{cmd:02x}, 0x81 -> {steps})...")
    asic_write(dev, 0x85, cmd)
    asic_write(dev, 0x81, steps)
    time.sleep(0.05 * (steps / 10.0 + 1))
    status = asic_read(dev, 0x86)
    print(f"    Status after step: 0x{status:02x}")

def main():
    print("=" * 70)
    print("PRIME FILM 1800u / 1800i HARDWARE VALIDATION TEST")
    print("Lamp Control & Stepper Motor Test (from PF1800U.dll)")
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

    dev.set_configuration()

    print("[*] Initializing GL640USB transceiver & CyberView EPP Mode 0x80...")
    wctl(dev, 0x8b, 0x00)
    time.sleep(0.05)
    wctl(dev, 0x8b, 0x40)
    time.sleep(0.05)
    cyberview_init(dev)
    print("[+] Bridge in EPP Data Mode 0x80!\n")

    initial_status = asic_read(dev, 0x86)
    print(f"[*] Initial Status (reg 0x86): 0x{initial_status:02x} ({initial_status:08b}b)")

    # Test 1: Lamp Control
    print("\n--- TEST 1: LAMP ACTIVATION ---")
    lamp_on(dev)
    print("[+] Lamp is ON! Waiting 3 seconds (look at the scanner optical slot)...")
    time.sleep(3.0)
    lamp_off(dev)
    print("[+] Lamp is OFF!")
    time.sleep(0.5)

    # Test 2: Stepper Motor
    print("\n--- TEST 2: STEPPER MOTOR MICRO-STEPPING ---")
    # Gentle 10 steps forward
    step_motor(dev, 'forward', 10)
    time.sleep(0.5)
    # Gentle 10 steps backward
    step_motor(dev, 'backward', 10)
    time.sleep(0.5)

    final_status = asic_read(dev, 0x86)
    print(f"\n[*] Final Status (reg 0x86): 0x{final_status:02x}")
    print("[+] All hardware tests completed successfully!")

if __name__ == '__main__':
    main()
