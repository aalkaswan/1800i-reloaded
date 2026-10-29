#!/usr/bin/env python3
"""
PrimeFilm 1800u / 1800i CyberView ASIC Register Interrogation Tool
Reconstructed from disassembled manufacturer Windows driver (PF1800U.dll).

Protocol Flow:
1. Bridge Transceiver Enable via 0x8b (wctl 0x00 -> 0x40)
2. 3-Stage IEEE 1284.4 Handshake (0x10001ed0):
   - Stage 1: Negotiate Mode 0x30 with 0x87 Line Strobe toggle
   - Stage 2: Negotiate Mode 0x00 with 0x87 Line Strobe toggle
   - Stage 3: Negotiate Mode 0x80 (EPP Data Mode) with 0x87 Line Strobe toggle
3. ASIC Register Access via EPP Bridge:
   - Write: wctl(0x83, asic_reg) -> wctl(0x85, val)
   - Read:  wctl(0x83, asic_reg) -> rctl(0x84)
"""

import sys
import time
import usb.core
import usb.util

VENDOR_ID = 0x05e3
PRODUCT_ID = 0x0120

def wctl(dev, reg, val, timeout=1000):
    """Write 1 byte to Genesys Logic bridge register."""
    # bmRequestType=0x40 (Vendor Host-to-Device), bRequest=0x0c, wValue=reg, wIndex=0
    return dev.ctrl_transfer(0x40, 0x0c, reg, 0, bytes([val]), timeout=timeout)

def rctl(dev, reg, timeout=1000):
    """Read 1 byte from Genesys Logic bridge register."""
    # bmRequestType=0xc0 (Vendor Device-to-Host), bRequest=0x0c, wValue=reg, wIndex=0
    buf = dev.ctrl_transfer(0xc0, 0x0c, reg, 0, 1, timeout=timeout)
    return buf[0] if buf else None

def ieee_handshake_stage(dev, mode):
    """
    Executes one stage of the 1284.4 negotiation sequence exactly as coded in
    PF1800U.dll at 0x10001ed0.
    """
    # 1. Assert Line Strobe (0x04) twice
    wctl(dev, 0x87, 0x04)
    wctl(dev, 0x87, 0x04)

    # 2. Signature synchronization sequence (repeated twice each)
    sync_pattern = [0xff, 0xaa, 0x55, 0x00, 0xff, 0x87, 0x78]
    for b in sync_pattern:
        wctl(dev, 0x88, b)
        wctl(dev, 0x88, b)

    # 3. Mode negotiation byte
    wctl(dev, 0x88, mode)
    wctl(dev, 0x88, mode)

    # 4. Line Strobe handshake toggle (0x05 -> 0x04)
    wctl(dev, 0x87, 0x05)
    wctl(dev, 0x87, 0x05)
    wctl(dev, 0x87, 0x04)
    wctl(dev, 0x87, 0x04)

    # 5. Handshake confirm
    wctl(dev, 0x88, 0xff)
    wctl(dev, 0x88, 0xff)

def cyberview_init(dev):
    """Full 3-stage CyberView bridge handshake from 0x10001ed0."""
    print("[*] Stage 1: Negotiating IEEE Mode 0x30...")
    ieee_handshake_stage(dev, 0x30)
    time.sleep(0.02)

    print("[*] Stage 2: Negotiating IEEE Mode 0x00...")
    ieee_handshake_stage(dev, 0x00)
    time.sleep(0.02)

    print("[*] Stage 3: Negotiating IEEE Mode 0x80 (EPP Data Mode)...")
    ieee_handshake_stage(dev, 0x80)
    time.sleep(0.02)
    print("[+] CyberView 3-stage handshake complete!")

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
    print("PRIME FILM 1800u / 1800i CYBERVIEW ASIC PROTOCOL PROBE")
    print("Reconstructed from PF1800U.dll (GL640USB -> Scanner ASIC)")
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

    # Step 1: Enable transceiver on GL640USB
    print("[*] Step 1: Enabling GL640USB transceiver (reg 0x8b -> 0x00, 0x40)...")
    wctl(dev, 0x8b, 0x00)
    time.sleep(0.05)
    wctl(dev, 0x8b, 0x40)
    time.sleep(0.05)

    # Step 2: 3-stage CyberView IEEE handshake
    print("[*] Step 2: Executing CyberView 3-stage initialization handshake...")
    try:
        cyberview_init(dev)
    except Exception as e:
        print(f"[!] Handshake failed: {e}")
        sys.exit(1)

    # Step 3: Test reading ASIC registers!
    print("\n[*] Step 3: Reading Scanner ASIC Registers via EPP (0x83 -> 0x84)...")
    test_regs = [
        (0x80, "Status / Control 0"),
        (0x81, "Status / Control 1"),
        (0x82, "Status / Control 2"),
        (0x86, "Motor / Busy Status"),
        (0x87, "Line Status"),
        (0x90, "Window End LSB"),
        (0x91, "Window End MID"),
        (0x92, "Window End MSB"),
        (0x9c, "Red Exposure LSB"),
        (0x9d, "Red Exposure MSB"),
        (0x9e, "Green Exposure LSB"),
        (0x9f, "Green Exposure MSB"),
        (0xa0, "Blue Exposure LSB"),
        (0xa1, "Blue Exposure MSB"),
        (0xe0, "Red PGA Gain"),
        (0xe2, "Red Offset Clamp"),
        (0xe4, "Green PGA Gain"),
        (0xe6, "Green Offset Clamp"),
        (0xe8, "Blue PGA Gain"),
        (0xea, "Blue Offset Clamp"),
    ]

    for reg, desc in test_regs:
        try:
            val = asic_read(dev, reg, timeout=500)
            print(f"  ASIC[0x{reg:02x}] ({desc:22}) = 0x{val:02x} ({val:3d})")
        except usb.core.USBError as e:
            print(f"  ASIC[0x{reg:02x}] ({desc:22}) = TIMEOUT/STALL ({e})")

    # Step 4: Test a safe write & read-back to an exposure or gain register
    print("\n[*] Step 4: Testing safe register write & readback on Red Gain (0xe0)...")
    try:
        orig = asic_read(dev, 0xe0)
        print(f"  Original Red Gain (0xe0): 0x{orig:02x}")
        test_val = 0x1f
        asic_write(dev, 0xe0, test_val)
        readback = asic_read(dev, 0xe0)
        print(f"  Wrote 0x{test_val:02x} -> Readback: 0x{readback:02x}")
        # Restore
        asic_write(dev, 0xe0, orig)
        restored = asic_read(dev, 0xe0)
        print(f"  Restored original value -> Readback: 0x{restored:02x}")
        if readback == test_val:
            print("[+] SUCCESS! Full bidirectional read/write to scanner ASIC verified!")
    except Exception as e:
        print(f"[!] Register readback test encountered: {e}")

    print("\n[+] Diagnostic test completed.")

if __name__ == '__main__':
    main()
