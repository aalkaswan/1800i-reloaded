#!/usr/bin/env python3
"""
Test reading ASIC SRAM with CCD Sampling Gate registers (0x98..0x9b) configured:
0x98 = 0x01, 0x99 = 0x00, 0x9a = 0x8d, 0x9b = 0x2a (from 0x10003e72)
"""

import sys
import time
import struct
import usb.core
import usb.util

VENDOR_ID = 0x05e3
PRODUCT_ID = 0x0120
EP_IN = 0x81
LINE_BYTES = 5400

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

def main():
    dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
    if dev is None:
        print("[!] Device not found")
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

    # Turn lamp ON
    print("[*] Turning LAMP ON...")
    asic_write(dev, 0xad, 0x0b)
    asic_write(dev, 0x85, 0x30)
    time.sleep(1.0)

    # Integration times (2900 clocks)
    for r_lsb, r_msb in [(0x9c, 0x9d), (0x9e, 0x9f), (0xa0, 0xa1)]:
        asic_write(dev, r_lsb, 0x54)
        asic_write(dev, r_msb, 0x0b)

    # Gains and offsets
    for r in [0xe0, 0xe4, 0xe8]:
        asic_write(dev, r, 0x1f)
    for r in [0xe2, 0xe6, 0xea]:
        asic_write(dev, r, 0x02)

    # Max exposure limits
    asic_read(dev, 0x87)
    for r in range(0xa2, 0xab):
        asic_write(dev, r, 0xff)

    # STEP 1: CCD Sampling Gate & Clock Generator (0x10003e72)
    print("[*] Configuring CCD Sampling Gate (0x98=0x01, 0x99=0x00, 0x9a=0x8d, 0x9b=0x2a)...")
    asic_write(dev, 0x98, 0x01)
    asic_write(dev, 0x99, 0x00)
    asic_write(dev, 0x9a, 0x8d)
    asic_write(dev, 0x9b, 0x2a)

    # Trigger scan
    print("[*] Triggering scan line (0x85 -> 0x12)...")
    asic_write(dev, 0x85, 0x12)
    asic_write(dev, 0x81, 0x00)
    wait_idle(dev)

    # Set window end to 0 (0x10002ae0(0))
    asic_write(dev, 0x90, 0x00)
    asic_write(dev, 0x91, 0x00)
    asic_write(dev, 0x92, 0x00)

    # Reset read pointer to 0 (0x10002aa0(0))
    asic_write(dev, 0x93, 0x00)
    asic_write(dev, 0x94, 0x00)
    asic_write(dev, 0x95, 0x00)
    wait_idle(dev)

    # Method 1: Direct Reg 0x80 Read (EPP control transfer)
    print("\n--- TEST 1: Direct Reg 0x80 EPP Read (32 bytes) ---")
    reg80_bytes = [asic_read(dev, 0x80) for _ in range(32)]
    print("  Bytes:", [f"0x{b:02x}" for b in reg80_bytes])

    # Method 2: Bulk Read via DMA (0x10002260 descriptor)
    print("\n--- TEST 2: Bulk EP 0x81 DMA Read ---")
    asic_write(dev, 0x93, 0x00)
    asic_write(dev, 0x94, 0x00)
    asic_write(dev, 0x95, 0x00)
    wctl(dev, 0x83, 0x80)
    desc = struct.pack("<BBBB I", 0x00, 0x00, 0x00, 0x00, LINE_BYTES)
    wctl(dev, 0x82, desc)

    try:
        raw = bytes(dev.read(EP_IN, LINE_BYTES, timeout=3000))
        print(f"  Received: {len(raw)} bytes. Min={min(raw)}, Max={max(raw)}, Avg={sum(raw)/len(raw):.2f}")
        print("  First 32 bytes:", raw[:32].hex(" "))
        print("  Center 32 bytes:", raw[2688:2720].hex(" "))
    except Exception as e:
        print("  Bulk error:", e)

    # Also test with Lamp OFF
    print("\n--- TEST 3: Repeat with Lamp OFF ---")
    asic_write(dev, 0xad, 0x4b)
    asic_write(dev, 0x85, 0x10)
    time.sleep(0.5)

    asic_write(dev, 0x98, 0x01)
    asic_write(dev, 0x99, 0x00)
    asic_write(dev, 0x9a, 0x8d)
    asic_write(dev, 0x9b, 0x2a)
    asic_write(dev, 0x85, 0x12)
    asic_write(dev, 0x81, 0x00)
    wait_idle(dev)

    asic_write(dev, 0x93, 0x00)
    asic_write(dev, 0x94, 0x00)
    asic_write(dev, 0x95, 0x00)
    wctl(dev, 0x83, 0x80)
    wctl(dev, 0x82, desc)
    try:
        raw_dark = bytes(dev.read(EP_IN, LINE_BYTES, timeout=3000))
        print(f"  Lamp OFF: Min={min(raw_dark)}, Max={max(raw_dark)}, Avg={sum(raw_dark)/len(raw_dark):.2f}")
        print("  First 32 bytes:", raw_dark[:32].hex(" "))
    except Exception as e:
        print("  Bulk dark error:", e)

    print("\n[+] Done.")

if __name__ == '__main__':
    main()
