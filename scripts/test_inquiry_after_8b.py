#!/usr/bin/env python3
"""
test_inquiry_after_8b.py - Tests whether enabling the GL640USB transceiver (reg 0x8b = 0x00 -> 0x40)
 followed by pies_init (pies_ieee(0x30)) + pies_exec (pies_ieee(0xe0)) allows SCSI INQUIRY on 05e3:0120.
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
        self.lib.libusb_bulk_transfer.argtypes = [
            ctypes.POINTER(dev_t), ctypes.c_uint8, ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.c_uint
        ]
        self.ctx = ctypes.POINTER(ctx_t)()
        self.lib.libusb_init(ctypes.byref(self.ctx))
        self.h = self.lib.libusb_open_device_with_vid_pid(self.ctx, 0x05e3, 0x0120)
        if not self.h:
            raise RuntimeError("05e3:0120 not found")
        self.lib.libusb_detach_kernel_driver(self.h, 0)
        self.lib.libusb_claim_interface(self.h, 0)

    def wctl(self, reg, val, req=0x0c, idx=0, timeout=2000):
        buf = (ctypes.c_uint8 * 1)(val)
        return self.lib.libusb_control_transfer(self.h, 0x40, req, reg, idx, buf, 1, timeout)

    def rctl(self, reg, req=0x0c, idx=0, timeout=2000):
        buf = (ctypes.c_uint8 * 1)(0)
        r = self.lib.libusb_control_transfer(self.h, 0xc0, req, reg, idx, buf, 1, timeout)
        return (r, buf[0]) if r == 1 else (r, None)

    def pies_ieee(self, mode):
        magic = [0xff, 0xaa, 0x55, 0x00, 0xff, 0x87, 0x78]
        for b in magic:
            if self.wctl(0x88, b) < 0:
                return -1
        if self.wctl(0x88, mode) < 0:
            return -1
        time.sleep(0.020)
        if self.wctl(0x87, 0x05) < 0:
            return -1
        if self.wctl(0x87, 0x04) < 0:
            return -1
        if self.wctl(0x88, 0xff) < 0:
            return -1
        time.sleep(0.020)
        return 0

    def close(self):
        if self.h:
            self.lib.libusb_release_interface(self.h, 0)
            self.lib.libusb_close(self.h)
            self.h = None

def main():
    u = LibUsb()
    try:
        print("[1] Checking EP0 via 0x89/0x8a...")
        if u.wctl(0x89, 0x71) < 0:
            print("[!] EP0 wedged; power-cycle scanner first.")
            return 1
        time.sleep(0.010)
        _, cid = u.rctl(0x8a)
        u.wctl(0x89, 0x70)
        print(f"    Indirect[0x71] = 0x{cid:02x}")

        print("[2] Enabling GL640USB transceiver via reg 0x8b (0x00 -> 500ms -> 0x40 -> 500ms)...")
        u.wctl(0x8b, 0x00)
        time.sleep(0.500)
        u.wctl(0x8b, 0x40)
        time.sleep(0.500)

        print("[3] Running pies_init: pies_ieee(0x30)...")
        r30 = u.pies_ieee(0x30)
        print(f"    pies_ieee(0x30) -> {r30}")

        print("[4] Running pies_exec: pies_ieee(0xe0)...")
        re0 = u.pies_ieee(0xe0)
        print(f"    pies_ieee(0xe0) -> {re0}")

        print("[5] Sending 6-byte SCSI INQUIRY CDB (12 00 00 00 24 00) to reg 0x85...")
        cdb = [0x12, 0x00, 0x00, 0x00, 0x24, 0x00]
        for i, b in enumerate(cdb):
            r = u.wctl(0x85, b, timeout=2000)
            print(f"    CDB[{i}] = 0x{b:02x} -> status={r}")
            if r < 0:
                print(f"[!] Timed out at CDB[{i}]! (05e3:0120 ASIC does not ACK SCSI-over-EPP on 0x85)")
                return 1

        st, rsp = u.rctl(0x84, timeout=2000)
        print(f"[6] Bridge status from 0x84: status={st}, rsp={f'0x{rsp:02x}' if rsp is not None else 'ERR'}")
    finally:
        u.close()

if __name__ == "__main__":
    sys.exit(main() or 0)
