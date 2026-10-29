#!/usr/bin/env python3
"""
PrimeFilm 1800u / 1800i First Optical Line Acquisition Test
Acquires 1 raw 1800-DPI scanline (5,400 bytes = 1800 pixels x 3 channels RGB)
Reconstructed from PF1800U.dll (functions 0x100035e0, 0x100035a0, 0x100034f0).
"""

import sys
import time
import struct
import usb.core
import usb.util

VENDOR_ID = 0x05e3
PRODUCT_ID = 0x0120

EP_IN = 0x81
LINE_BYTES = 5400  # 1800 pixels * 3 channels (RGB)

def wctl(dev, reg, data, timeout=1000):
    """Write bytes to Genesys Logic bridge register."""
    if isinstance(data, int):
        data = bytes([data])
    return dev.ctrl_transfer(0x40, 0x0c, reg, 0, data, timeout=timeout)

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

def main():
    print("=" * 70)
    print("PRIME FILM 1800u / 1800i FIRST OPTICAL SCANLINE ACQUISITION")
    print(f"Target: 1 Scanline @ 1800 DPI ({LINE_BYTES} bytes over Bulk EP 0x{EP_IN:02x})")
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

    print("[*] Step 1: Initializing GL640USB transceiver & CyberView EPP Mode 0x80...")
    wctl(dev, 0x8b, 0x00)
    time.sleep(0.05)
    wctl(dev, 0x8b, 0x40)
    time.sleep(0.05)
    cyberview_init(dev)
    print("[+] Bridge in EPP Data Mode 0x80!")

    status = asic_read(dev, 0x86)
    print(f"[*] Initial Status (reg 0x86): 0x{status:02x}")

    print("\n[*] Step 2: Turning LAMP ON & Configuring Exposure/AFE...")
    asic_write(dev, 0xad, 0x0b)
    asic_write(dev, 0x85, 0x30)  # Lamp ON
    time.sleep(1.0)  # Lamp warm-up stabilization

    # Configure Integration Times (2900 clocks = 0x0b54)
    asic_write(dev, 0x9c, 0x54)  # Red LSB
    asic_write(dev, 0x9d, 0x0b)  # Red MSB
    asic_write(dev, 0x9e, 0x54)  # Green LSB
    asic_write(dev, 0x9f, 0x0b)  # Green MSB
    asic_write(dev, 0xa0, 0x54)  # Blue LSB
    asic_write(dev, 0xa1, 0x0b)  # Blue MSB

    # Configure AFE PGA Gains (0x1f = nominal gain)
    asic_write(dev, 0xe0, 0x1f)  # Red Gain
    asic_write(dev, 0xe4, 0x1f)  # Green Gain
    asic_write(dev, 0xe8, 0x1f)  # Blue Gain

    # Configure AFE Offsets
    asic_write(dev, 0xe2, 0x02)
    asic_write(dev, 0xe6, 0x02)
    asic_write(dev, 0xea, 0x02)

    # Set scan window length (0x1518 = 5400)
    asic_write(dev, 0x90, 0x18)
    asic_write(dev, 0x91, 0x15)
    asic_write(dev, 0x92, 0x00)

    print("\n[*] Step 3: Arming DMA Descriptor on Register 0x82 (0x100035a0)...")
    # Set EPP Address to 0x80 (SRAM Data Port)
    wctl(dev, 0x83, 0x80)

    # 8-byte DMA transfer descriptor: [0, 0, ep_channel=1, 0, length_le32]
    dma_desc = struct.pack("<BBBB I", 0x00, 0x00, 0x01, 0x00, LINE_BYTES)
    wctl(dev, 0x82, dma_desc)

    print("\n[*] Step 4: Triggering Scan Acquisition (0x85 -> 0x12)...")
    asic_write(dev, 0x85, 0x12)

    print(f"[*] Step 5: Reading {LINE_BYTES} bytes from Bulk IN Endpoint 0x{EP_IN:02x}...")
    try:
        raw_data = dev.read(EP_IN, LINE_BYTES, timeout=3000)
        raw_bytes = bytes(raw_data)
        print(f"[+] SUCCESS! Received {len(raw_bytes)} bytes from Bulk IN!")

        # Statistics
        min_v = min(raw_bytes)
        max_v = max(raw_bytes)
        avg_v = sum(raw_bytes) / len(raw_bytes)
        print(f"    Line Pixel Statistics: Min={min_v}, Max={max_v}, Avg={avg_v:.2f}")
        print("    First 32 bytes of raw CCD scanline:")
        print("   ", raw_bytes[:32].hex(" "))

        out_file = "/home/aalkaswan/Desktop/1800i-reloaded/test_scanline.bin"
        with open(out_file, "wb") as f:
            f.write(raw_bytes)
        print(f"[+] Saved raw scanline data to: {out_file}")

    except usb.core.USBError as e:
        print(f"[!] Bulk IN transfer error: {e}")

    finally:
        print("\n[*] Step 6: Turning LAMP OFF & Entering Standby...")
        try:
            asic_write(dev, 0xad, 0x4b)
            asic_write(dev, 0x85, 0x10)  # Lamp OFF
            print("[+] Lamp turned OFF.")
        except Exception:
            pass

    print("[+] Test completed.")

if __name__ == '__main__':
    main()
