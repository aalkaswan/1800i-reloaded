#!/usr/bin/env python3
"""
PrimeFilm 1800u / 1800i First Optical Line Acquisition Test
Acquires 1 raw 1800-DPI scanline (5,400 bytes = 1800 pixels x 3 channels RGB)
Reconstructed from PF1800U.dll (functions 0x10002410, 0x10002520, 0x10002920, 0x100035a0).
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

def wait_idle(dev, timeout=5.0):
    """Wait until ASIC busy bits (0x1e) in register 0x84 clear (0x10002920)."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        val = asic_read(dev, 0x84)
        if val is not None and (val & 0x1e) == 0:
            return True
        time.sleep(0.002)
    return False

def configure_hardware(dev):
    """Hardware configuration sequence from PF1800U.dll at 0x10002410."""
    print("[*] Writing ASIC clock, timing, and AFE registers (0x10002410)...")
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
    """Max exposure limits from 0x10002bc0."""
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
    """Set SRAM window start and length (0x10002aa0 and 0x10002ae0)."""
    # Window End: 0x90..0x92
    asic_write(dev, 0x90, length & 0xff)
    asic_write(dev, 0x91, (length >> 8) & 0xff)
    asic_write(dev, 0x92, (length >> 16) & 0xff)
    # Window Start / Read Pointer: 0x93..0x95
    asic_write(dev, 0x93, start & 0xff)
    asic_write(dev, 0x94, (start >> 8) & 0xff)
    asic_write(dev, 0x95, (start >> 16) & 0xff)

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

    configure_hardware(dev)

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

    # Set scan window (start=0, end=5400)
    set_window(dev, start=0, length=LINE_BYTES)

    # Set exposure limits
    set_exposure_limits(dev)

    # Wait for sensor idle
    wait_idle(dev)

    print("\n[*] Step 3: Triggering Scan Acquisition (0x85 -> 0x12)...")
    asic_write(dev, 0x85, 0x12)

    print("[*] Waiting for ASIC optical integration to finish (polling reg 0x84)...")
    if wait_idle(dev):
        print("[+] Optical exposure complete! Data ready in ASIC SRAM.")
    else:
        print("[!] Warning: Optical exposure wait timed out.")

    print("\n[*] Step 4: Arming DMA Descriptor on Register 0x82 (0x100035a0)...")
    # Reset read pointer to 0 before DMA
    asic_write(dev, 0x93, 0x00)
    asic_write(dev, 0x94, 0x00)
    asic_write(dev, 0x95, 0x00)

    # Set EPP Address to 0x80 (SRAM Data Port)
    wctl(dev, 0x83, 0x80)

    # 8-byte DMA transfer descriptor: [0, 0, ep_channel=1, 0, length_le32]
    dma_desc = struct.pack("<BBBB I", 0x00, 0x00, 0x01, 0x00, LINE_BYTES)
    wctl(dev, 0x82, dma_desc)

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
        print("    Middle 32 bytes (around center):")
        print("   ", raw_bytes[2688:2720].hex(" "))

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
