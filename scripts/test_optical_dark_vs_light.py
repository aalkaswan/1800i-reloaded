#!/usr/bin/env python3
"""
PrimeFilm 1800u / 1800i Optical Response Validation
Tests CCD / AFE sensor output under:
1. Complete Darkness (Lamp OFF)
2. Illumination (Lamp ON, Full Exposure)
3. Reduced Exposure / Gain
Verifies physical photon measurement vs electrical bus behavior.
"""

import sys
import time
import struct
import usb.core
import usb.util

VENDOR_ID = 0x05e3
PRODUCT_ID = 0x0120

EP_IN = 0x81
LINE_BYTES = 5400  # 1800 pixels * 3 channels

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

def move_carriage(dev, direction_cmd, steps):
    asic_write(dev, 0x85, direction_cmd)
    remaining = steps
    while remaining > 0:
        chunk = min(remaining, 200)
        asic_write(dev, 0x81, chunk)
        asic_write(dev, 0x83, 0x01)
        wait_idle(dev)
        remaining -= chunk
        time.sleep(0.005)

def capture_line(dev, exposure_clocks, gain):
    # Set exposure
    exp_lsb = exposure_clocks & 0xff
    exp_msb = (exposure_clocks >> 8) & 0xff
    asic_write(dev, 0x9c, exp_lsb)
    asic_write(dev, 0x9d, exp_msb)
    asic_write(dev, 0x9e, exp_lsb)
    asic_write(dev, 0x9f, exp_msb)
    asic_write(dev, 0xa0, exp_lsb)
    asic_write(dev, 0xa1, exp_msb)

    # Set gain
    asic_write(dev, 0xe0, gain)
    asic_write(dev, 0xe4, gain)
    asic_write(dev, 0xe8, gain)

    # Set window
    set_window(dev, start=0, length=LINE_BYTES)
    set_exposure_limits(dev)
    wait_idle(dev)

    # Trigger scan
    asic_write(dev, 0x85, 0x12)
    wait_idle(dev)

    # Reset read pointer & arm DMA
    asic_write(dev, 0x93, 0x00)
    asic_write(dev, 0x94, 0x00)
    asic_write(dev, 0x95, 0x00)
    wctl(dev, 0x83, 0x80)
    dma_desc = struct.pack("<BBBB I", 0x00, 0x00, 0x01, 0x00, LINE_BYTES)
    wctl(dev, 0x82, dma_desc)

    raw_data = bytes(dev.read(EP_IN, LINE_BYTES, timeout=3000))
    return raw_data

def print_stats(name, data):
    min_v = min(data)
    max_v = max(data)
    avg_v = sum(data) / len(data)
    print(f"  {name:30s}: Min={min_v:3d}, Max={max_v:3d}, Avg={avg_v:6.2f}")
    print(f"    First 16 bytes: {data[:16].hex(' ')}")
    print(f"    Mid   16 bytes: {data[2688:2704].hex(' ')}")

def main():
    print("=" * 70)
    print("PRIME FILM 1800u / 1800i OPTICAL RESPONSE TEST")
    print("Comparing Dark Current (Lamp OFF) vs Illumination (Lamp ON)")
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

    configure_hardware(dev)

    # Move carriage forward into scan bay by 300 steps (~4.2 mm)
    jog_steps = 300
    print(f"\n[*] Positioning carriage into scan bay ({jog_steps} steps forward)...")
    move_carriage(dev, 0x16, jog_steps)

    try:
        # TEST 1: Lamp OFF (Complete darkness)
        print("\n--- TEST 1: LAMP OFF (Dark Current / Black Level) ---")
        asic_write(dev, 0xad, 0x4b)
        asic_write(dev, 0x85, 0x10)  # Lamp OFF
        time.sleep(0.5)

        dark_line = capture_line(dev, exposure_clocks=2900, gain=0x1f)
        print_stats("Lamp OFF (Exp=2900, Gain=31)", dark_line)

        # TEST 2: Lamp ON (Full illumination)
        print("\n--- TEST 2: LAMP ON (Active Illumination) ---")
        asic_write(dev, 0xad, 0x0b)
        asic_write(dev, 0x85, 0x30)  # Lamp ON
        print("[*] Warming up lamp (1.5s)...")
        time.sleep(1.5)

        light_line = capture_line(dev, exposure_clocks=2900, gain=0x1f)
        print_stats("Lamp ON (Exp=2900, Gain=31)", light_line)

        # TEST 3: Lamp ON with Reduced Exposure
        print("\n--- TEST 3: LAMP ON (Reduced Exposure: 500 clocks, Gain=0) ---")
        low_line = capture_line(dev, exposure_clocks=500, gain=0x00)
        print_stats("Lamp ON (Exp=500, Gain=0)", low_line)

        # TEST 4: Lamp ON with Medium Exposure
        print("\n--- TEST 4: LAMP ON (Medium Exposure: 1200 clocks, Gain=10) ---")
        med_line = capture_line(dev, exposure_clocks=1200, gain=10)
        print_stats("Lamp ON (Exp=1200, Gain=10)", med_line)

    finally:
        print("\n[*] Returning carriage back to home stop...")
        move_carriage(dev, 0x14, jog_steps)
        print("[+] Carriage returned.")

        print("[*] Turning LAMP OFF & Entering Standby...")
        try:
            asic_write(dev, 0xad, 0x4b)
            asic_write(dev, 0x85, 0x10)
            print("[+] Lamp turned OFF.")
        except Exception:
            pass

    print("[+] Optical response test completed.")

if __name__ == '__main__':
    main()
