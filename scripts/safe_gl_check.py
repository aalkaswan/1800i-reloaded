#!/usr/bin/env python3
"""
safe_gl_check.py - Non-wedging GL640USB / GL646 internal register probe for 05e3:0120.
Based on VueScan's gl64_wctl / gl64_rctl in lm98_iint (0x0077e39c..0x0077e4a6).

IMPORTANT HARDWARE NOTE:
On the Genesys Logic GL640USB / GL646 bridge, reading or writing 0x83, 0x84, or 0x85
triggers an external hardware EPP cycle on the parallel bus and stalls EP0 indefinitely
waiting for nWAIT if the scanner ASIC is not in EPP mode.

By contrast, registers 0x89 (Indirect Index), 0x8a (Indirect Data), 0x8b (Bridge Reset/Enable),
0x87 (Parallel Control Latch), and 0x88 (Parallel Data Latch) are internal to the USB bridge
and never block on nWAIT.
"""
import ctypes
import time
import sys

class LibUsb:
    def __init__(self):
        self.lib = ctypes.CDLL("libusb-1.0.so.0")
        class ctx_t(ctypes.Structure): pass
        class dev_t(ctypes.Structure): pass
        self.lib.libusb_init.argtypes = [ctypes.POINTER(ctypes.POINTER(ctx_t))]
        self.lib.libusb_open_device_with_vid_pid.argtypes = [ctypes.POINTER(ctx_t), ctypes.c_uint16, ctypes.c_uint16]
        self.lib.libusb_open_device_with_vid_pid.restype = ctypes.POINTER(dev_t)
        self.lib.libusb_detach_kernel_driver.argtypes = [ctypes.POINTER(dev_t), ctypes.c_int]
        self.lib.libusb_claim_interface.argtypes = [ctypes.POINTER(dev_t), ctypes.c_int]
        self.lib.libusb_release_interface.argtypes = [ctypes.POINTER(dev_t), ctypes.c_int]
        self.lib.libusb_close.argtypes = [ctypes.POINTER(dev_t)]
        self.lib.libusb_control_transfer.argtypes = [
            ctypes.POINTER(dev_t), ctypes.c_uint8, ctypes.c_uint8,
            ctypes.c_uint16, ctypes.c_uint16, ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_uint16, ctypes.c_uint
        ]
        self.ctx = ctypes.POINTER(ctx_t)()
        self.lib.libusb_init(ctypes.byref(self.ctx))
        self.h = self.lib.libusb_open_device_with_vid_pid(self.ctx, 0x05e3, 0x0120)
        if not self.h:
            raise RuntimeError("05e3:0120 not found")
        self.lib.libusb_detach_kernel_driver(self.h, 0)
        self.lib.libusb_claim_interface(self.h, 0)

    def wctl(self, reg, val, timeout=1000):
        buf = (ctypes.c_uint8 * 1)(val)
        return self.lib.libusb_control_transfer(self.h, 0x40, 0x0c, reg, 0, buf, 1, timeout)

    def rctl(self, reg, timeout=1000):
        buf = (ctypes.c_uint8 * 1)(0)
        r = self.lib.libusb_control_transfer(self.h, 0xc0, 0x0c, reg, 0, buf, 1, timeout)
        return (r, buf[0]) if r == 1 else (r, None)

    def close(self):
        if self.h:
            self.lib.libusb_release_interface(self.h, 0)
            self.lib.libusb_close(self.h)
            self.h = None

def main():
    print("=== Safe Internal GL640USB / GL646 Probe (05e3:0120) ===")
    u = LibUsb()
    try:
        # 1. Test whether EP0 is currently responsive by writing 0x71 to 0x89 (lm98_iint @ 0x0077e39c)
        r = u.wctl(0x89, 0x71)
        if r < 0:
            print(f"[!] Bridge EP0 timed out (status={r}).")
            print("    The GL640/GL646 bridge is still wedged in an EPP nWAIT cycle from the previous run.")
            print("    Please power-cycle (turn off/on or unplug power/USB) the scanner and re-run this script.")
            return 1

        time.sleep(0.010)
        r_a, chip_id = u.rctl(0x8a)
        u.wctl(0x89, 0x70)
        print(f"[+] Bridge EP0 is LIVE! Indirect Reg 0x71 (via 0x89/0x8a): status={r_a}, value={f'0x{chip_id:02x}' if chip_id is not None else 'ERR'}")

        # 2. Read safe internal indirect registers 0x70..0x77 via 0x89 -> 0x8a
        print("\n[*] Dumping internal indirect registers 0x70..0x77 via 0x89 -> 0x8a:")
        for idx in range(0x70, 0x78):
            u.wctl(0x89, idx)
            time.sleep(0.005)
            st, val = u.rctl(0x8a)
            print(f"    Indirect[0x{idx:02x}] = {f'0x{val:02x}' if val is not None else f'ERR({st})'}")
        u.wctl(0x89, 0x70)

        # 3. Execute lm98_iint bridge enable (0x8b = 0x00 -> 500ms -> 0x8b = 0x40 -> 500ms)
        if chip_id != 0x64:
            print("\n[*] Chip ID != 0x64; running lm98_iint bridge reset/enable on reg 0x8b (0x00 -> 0x40)...")
            r0 = u.wctl(0x8b, 0x00)
            time.sleep(0.500)
            r1 = u.wctl(0x8b, 0x40)
            time.sleep(0.500)
            print(f"    wctl(0x8b, 0x00) -> {r0}, wctl(0x8b, 0x40) -> {r1}")
            for idx in range(0x70, 0x74):
                u.wctl(0x89, idx)
                time.sleep(0.005)
                st, val = u.rctl(0x8a)
                print(f"    After 0x8b reset: Indirect[0x{idx:02x}] = {f'0x{val:02x}' if val is not None else f'ERR({st})'}")
            u.wctl(0x89, 0x70)
    finally:
        u.close()

if __name__ == "__main__":
    sys.exit(main() or 0)
