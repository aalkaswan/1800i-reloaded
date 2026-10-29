#!/usr/bin/env python3
"""
Test reading ASIC SRAM directly via:
1. Register 0x80 read (0x100023d0)
2. DMA descriptor [0, 0, 0, 0, length] from 0x10002260
3. Comparing 0x12 vs 0x16 scan trigger
"""

import sys
import time
import struct
import usb.core
import usb.util

VENDOR_ID = 0x05e3
PRODUCT_ID = 0x0120
EP_IN = 0x81

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
    asic_write(dev, 0xad, 0x0b)
    asic_write(dev, 0x85, 0x30)
    time.sleep(1.0)

    # Configure exposure
    asic_write(dev, 0x9c, 0x54)
    asic_write(dev, 0x9d, 0x0b)
    asic_write(dev, 0x9e, 0x54)
    asic_write(dev, 0x9f, 0x0b)
    asic_write(dev, 0xa0, 0x54)
    asic_write(dev, 0xa1, 0x0b)

    # Set window: 0..5400
    asic_write(dev, 0x90, 5400 & 0xff)
    asic_write(dev, 0x91, (5400 >> 8) & 0xff)
    asic_write(dev, 0x92, 0x00)
    asic_write(dev, 0x93, 0x00)
    asic_write(dev, 0x94, 0x00)
    asic_write(dev, 0x95, 0x00)

    # Exposure limits
    asic_read(dev, 0x87)
    for r in range(0xa2, 0xab):
        asic_write(dev, r, 0xff)

    wait_idle(dev)

    # Trigger scan
    print("[*] Triggering scan line (0x85 -> 0x12)...")
    asic_write(dev, 0x85, 0x12)
    wait_idle(dev)

    # Reset read pointer to 0
    asic_write(dev, 0x93, 0x00)
    asic_write(dev, 0x94, 0x00)
    asic_write(dev, 0x95, 0x00)

    # Method 1: Read directly through register 0x80 (0x100023d0)
    print("\n--- METHOD 1: Direct Reg 0x80 Read (32 bytes via EPP) ---")
    direct_bytes = []
    for i in range(32):
        b = asic_read(dev, 0x80)
        direct_bytes.append(b)
    print("  Direct Reg 0x80 bytes:", [f"0x{b:02x}" for b in direct_bytes])

    # Method 2: DMA with [0, 0, 0, 0, length] descriptor from 0x10002260
    print("\n--- METHOD 2: DMA with 0x10002260 Descriptor (all zeros header) ---")
    asic_write(dev, 0x93, 0x00)
    asic_write(dev, 0x94, 0x00)
    asic_write(dev, 0x95, 0x00)
    wctl(dev, 0x83, 0x80)
    desc_zeros = struct.pack("<BBBB I", 0x00, 0x00, 0x00, 0x00, 5400)
    wctl(dev, 0x82, desc_zeros)
    try:
        dma_data = bytes(dev.read(EP_IN, 5400, timeout=2000))
        print("  DMA (zeros header): Min={}, Max={}, Avg={:.2f}".format(min(dma_data), max(dma_data), sum(dma_data)/len(dma_data)))
        print("  First 32 bytes:", dma_data[:32].hex(" "))
    except Exception as e:
        print("  DMA error:", e)

    # Method 3: Try 0x16 trigger instead of 0x12
    print("\n--- METHOD 3: Trigger via 0x85 -> 0x16 (from 0x10002cbb) ---")
    asic_write(dev, 0x98, 0x01)
    asic_write(dev, 0x99, 0x00)
    asic_write(dev, 0x9a, 0x01)
    asic_write(dev, 0x9b, 0x40)
    asic_write(dev, 0x85, 0x16)
    asic_write(dev, 0x81, 0x00)
    wait_idle(dev)

    # Reset read pointer
    asic_write(dev, 0x93, 0x00)
    asic_write(dev, 0x94, 0x00)
    asic_write(dev, 0x95, 0x00)
    wctl(dev, 0x83, 0x80)
    wctl(dev, 0x82, desc_zeros)
    try:
        dma_data = bytes(dev.read(EP_IN, 5400, timeout=2000))
        print("  DMA (0x16 trigger): Min={}, Max={}, Avg={:.2f}".format(min(dma_data), max(dma_data), sum(dma_data)/len(dma_data)))
        print("  First 32 bytes:", dma_data[:32].hex(" "))
    except Exception as e:
        print("  DMA error:", e)

    # Turn lamp OFF
    asic_write(dev, 0xad, 0x4b)
    asic_write(dev, 0x85, 0x10)
    print("\n[+] Test complete. Lamp OFF.")

if __name__ == '__main__':
    main()
