#!/usr/bin/env python3
"""
diag_gl_regs.py - Genesys Logic (GL640/GL646) Bridge Register Diagnostic for 05e3:0120

Reads and dumps bridge registers (0x00..0x0f and 0x80..0x8f) via:
  bmRequestType = 0xc0 (USB_DIR_IN | USB_TYPE_VENDOR | USB_RECIP_DEVICE)
  bRequest      = 0x0c (GL_REQ_REG_READ)
  wValue        = register address (0x00..0x0f, 0x80..0x8f)
  wIndex        = 0x0000
  wLength       = 0x0001

Dumps register state across 3 critical lifecycle stages:
  Stage 1: Raw initial state (BEFORE any handshake)
  Stage 2: After pies_ieee(mode=0x30)  [VueScan pies_init @ 0x006691f0]
  Stage 3: After pies_ieee(mode=0xe0)  [VueScan pies_exec @ 0x00669230]
  Stage 4: Indirect chip identification test via reg 0x89 / 0x8a (lm98_iint @ 0x0077e365)
"""

import sys
import time
import argparse
import ctypes

# Known GL Register Definitions
GL_REG_NAMES = {
    0x80: "DMA/FIFO Control 0",
    0x81: "DMA/FIFO Control 1",
    0x82: "DMA Descriptor / Trigger",
    0x83: "EPP Address Register",
    0x84: "EPP Status / Data IN",
    0x85: "EPP Data OUT Register",
    0x86: "EPP Control / Config",
    0x87: "EPP Line Strobe Register",
    0x88: "IEEE 1284.4 Handshake / Mode",
    0x89: "Indirect Register Address",
    0x8a: "Indirect Data / Chip ID",
    0x8b: "Reset / Power Control",
    0x8c: "GPIO / Bus Direction",
    0x8d: "Interrupt Control",
    0x8e: "Clock / Timing Config",
    0x8f: "Bridge Status / Misc",
}

class LibUsbBackend:
    def __init__(self):
        try:
            self.lib = ctypes.CDLL("libusb-1.0.so.0")
        except OSError as e:
            raise RuntimeError(f"Could not load libusb-1.0.so.0: {e}")

        class libusb_context(ctypes.Structure): pass
        class libusb_device_handle(ctypes.Structure): pass

        self.lib.libusb_init.argtypes = [ctypes.POINTER(ctypes.POINTER(libusb_context))]
        self.lib.libusb_init.restype = ctypes.c_int

        self.lib.libusb_open_device_with_vid_pid.argtypes = [
            ctypes.POINTER(libusb_context), ctypes.c_uint16, ctypes.c_uint16
        ]
        self.lib.libusb_open_device_with_vid_pid.restype = ctypes.POINTER(libusb_device_handle)

        self.lib.libusb_reset_device.argtypes = [ctypes.POINTER(libusb_device_handle)]
        self.lib.libusb_reset_device.restype = ctypes.c_int

        self.lib.libusb_claim_interface.argtypes = [ctypes.POINTER(libusb_device_handle), ctypes.c_int]
        self.lib.libusb_claim_interface.restype = ctypes.c_int

        self.lib.libusb_release_interface.argtypes = [ctypes.POINTER(libusb_device_handle), ctypes.c_int]
        self.lib.libusb_release_interface.restype = ctypes.c_int

        self.lib.libusb_detach_kernel_driver.argtypes = [ctypes.POINTER(libusb_device_handle), ctypes.c_int]
        self.lib.libusb_detach_kernel_driver.restype = ctypes.c_int

        self.lib.libusb_close.argtypes = [ctypes.POINTER(libusb_device_handle)]
        self.lib.libusb_close.restype = None

        self.lib.libusb_exit.argtypes = [ctypes.POINTER(libusb_context)]
        self.lib.libusb_exit.restype = None

        self.lib.libusb_strerror.argtypes = [ctypes.c_int]
        self.lib.libusb_strerror.restype = ctypes.c_char_p

        self.lib.libusb_control_transfer.argtypes = [
            ctypes.POINTER(libusb_device_handle),
            ctypes.c_uint8,  # bmRequestType
            ctypes.c_uint8,  # bRequest
            ctypes.c_uint16, # wValue
            ctypes.c_uint16, # wIndex
            ctypes.POINTER(ctypes.c_uint8), # data
            ctypes.c_uint16, # wLength
            ctypes.c_uint    # timeout
        ]
        self.lib.libusb_control_transfer.restype = ctypes.c_int

        self.ctx = ctypes.POINTER(libusb_context)()
        r = self.lib.libusb_init(ctypes.byref(self.ctx))
        if r < 0:
            raise RuntimeError(f"libusb_init failed: {r}")
        self.handle = None

    def open(self, vid, pid):
        self.handle = self.lib.libusb_open_device_with_vid_pid(self.ctx, vid, pid)
        if not self.handle:
            return False
        # Detach kernel drivers if present
        self.lib.libusb_detach_kernel_driver(self.handle, 0)
        # Claim interface 0
        r = self.lib.libusb_claim_interface(self.handle, 0)
        if r < 0:
            print(f"[!] Warning: libusb_claim_interface(0) returned {r} ({self.strerror(r)})")
        return True

    def reset(self):
        if self.handle:
            self.lib.libusb_reset_device(self.handle)

    def close(self):
        if self.handle:
            self.lib.libusb_release_interface(self.handle, 0)
            self.lib.libusb_close(self.handle)
            self.handle = None

    def exit(self):
        self.close()
        if self.ctx:
            self.lib.libusb_exit(self.ctx)
            self.ctx = None

    def strerror(self, code):
        s = self.lib.libusb_strerror(code)
        return s.decode("utf-8") if s else str(code)

    def control_msg(self, req_type, req, val, idx, data, length, timeout=1000):
        buf = (ctypes.c_uint8 * length)(*data) if data else (ctypes.c_uint8 * length)()
        r = self.lib.libusb_control_transfer(
            self.handle, req_type, req, val, idx, buf, length, timeout
        )
        if r < 0:
            return r, bytes()
        return r, bytes(buf[:r])


class GlDiag:
    def __init__(self, backend, timeout_ms=1000):
        self.backend = backend
        self.timeout_ms = timeout_ms

    def read_reg(self, reg):
        """Read 1 byte from GL register via bRequest=0x0c, wValue=reg."""
        r, data = self.backend.control_msg(
            0xc0, 0x0c, reg, 0x0000, None, 1, timeout=self.timeout_ms
        )
        if r == 1 and len(data) >= 1:
            return data[0]
        return None  # None indicates STALL / Timeout / Error

    def write_reg(self, reg, val):
        """Write 1 byte to GL register via bRequest=0x0c, wValue=reg."""
        r, _ = self.backend.control_msg(
            0x40, 0x0c, reg, 0x0000, [val], 1, timeout=self.timeout_ms
        )
        return r

    def pies_ieee(self, mode=0xe0):
        """
        Execute VueScan IEEE 1284.4 handshake sequence (0x00669030):
        1. 7 magic bytes to reg 0x88: ff aa 55 00 ff 87 78
        2. mode byte to reg 0x88 (0x30 or 0xe0)
        3. 20ms delay
        4. write 0x05 to reg 0x87
        5. write 0x04 to reg 0x87
        6. write 0xff to reg 0x88
        7. 20ms delay
        """
        magic = [0xff, 0xaa, 0x55, 0x00, 0xff, 0x87, 0x78]
        for b in magic:
            if self.write_reg(0x88, b) < 0:
                return -1
        if self.write_reg(0x88, mode) < 0:
            return -1
        time.sleep(0.020)
        if self.write_reg(0x87, 0x05) < 0:
            return -1
        if self.write_reg(0x87, 0x04) < 0:
            return -1
        if self.write_reg(0x88, 0xff) < 0:
            return -1
        time.sleep(0.020)
        return 0

    def dump_range(self, reg_list):
        """Dump list of registers into a dictionary {reg: val}."""
        res = {}
        for r in reg_list:
            res[r] = self.read_reg(r)
        return res


def print_comparison_table(regs, s1, s2, s3):
    print("+" + "-"*8 + "+" + "-"*12 + "+" + "-"*12 + "+" + "-"*12 + "+" + "-"*28 + "+")
    print(f"| {'Reg':<6} | {'Stage 1 (Raw)':<10} | {'Stage 2 (0x30)':<10} | {'Stage 3 (0xe0)':<10} | {'Description':<26} |")
    print("+" + "-"*8 + "+" + "-"*12 + "+" + "-"*12 + "+" + "-"*12 + "+" + "-"*28 + "+")

    for r in regs:
        def fmt(val):
            if val is None:
                return "ERR/STALL"
            return f"0x{val:02x} ({val:3d})"

        name = GL_REG_NAMES.get(r, f"Generic Register 0x{r:02x}")
        diff = ""
        v1, v2, v3 = s1.get(r), s2.get(r), s3.get(r)
        if v1 != v2 or v2 != v3:
            diff = " *"
        print(f"| 0x{r:02x}   | {fmt(v1):<10} | {fmt(v2):<10} | {fmt(v3):<10} | {name:<26}{diff}|")

    print("+" + "-"*8 + "+" + "-"*12 + "+" + "-"*12 + "+" + "-"*12 + "+" + "-"*28 + "+")


def main():
    parser = argparse.ArgumentParser(
        description="Genesys Logic (GL640/GL646) Bridge Register Diagnostic for 05e3:0120"
    )
    parser.add_argument("--vid", type=lambda x: int(x, 16), default=0x05e3,
                        help="USB Vendor ID (default: 0x05e3)")
    parser.add_argument("--pid", type=lambda x: int(x, 16), default=0x0120,
                        help="USB Product ID (default: 0x0120)")
    parser.add_argument("--timeout", type=int, default=1000,
                        help="Transfer timeout in ms (default: 1000)")
    parser.add_argument("--reset", action="store_true",
                        help="Issue USB device reset before diagnostic")
    args = parser.parse_args()

    print("=" * 76)
    print("GENESYS LOGIC BRIDGE REGISTER DIAGNOSTIC (05e3:0120)")
    print("=" * 76)
    print(f"Target VID:PID : 0x{args.vid:04x}:0x{args.pid:04x}")
    print(f"Read Timeout   : {args.timeout} ms")

    backend = LibUsbBackend()
    try:
        print(f"\n[*] Connecting to 0x{args.vid:04x}:0x{args.pid:04x}...")
        if not backend.open(args.vid, args.pid):
            print(f"[!] Device 0x{args.vid:04x}:0x{args.pid:04x} not found or permission denied.")
            return 1

        if args.reset:
            print("[*] Performing USB bus reset on device...")
            backend.reset()
            backend.close()
            time.sleep(1.0)
            if not backend.open(args.vid, args.pid):
                print("[!] Failed to re-open device after reset.")
                return 1

        diag = GlDiag(backend, timeout_ms=args.timeout)

        regs_low = list(range(0x00, 0x10))
        regs_high = list(range(0x80, 0x90))
        all_regs = regs_low + regs_high

        # STAGE 1: RAW STATE BEFORE ANY HANDSHAKE
        print("\n[*] STAGE 1: Reading bridge registers in raw initial state (before pies_ieee)...")
        stage1 = diag.dump_range(all_regs)

        # STAGE 2: AFTER pies_ieee(0x30) (VueScan pies_init)
        print("\n[*] STAGE 2: Executing pies_ieee(mode=0x30) [VueScan pies_init]...")
        r2 = diag.pies_ieee(mode=0x30)
        if r2 < 0:
            print("[!] Warning: pies_ieee(0x30) returned error!")
        else:
            print("    pies_ieee(0x30) ACKed successfully.")
        stage2 = diag.dump_range(all_regs)

        # STAGE 3: AFTER pies_ieee(0xe0) (VueScan pies_exec)
        print("\n[*] STAGE 3: Executing pies_ieee(mode=0xe0) [VueScan pies_exec]...")
        r3 = diag.pies_ieee(mode=0xe0)
        if r3 < 0:
            print("[!] Warning: pies_ieee(0xe0) returned error!")
        else:
            print("    pies_ieee(0xe0) ACKed successfully.")
        stage3 = diag.dump_range(all_regs)

        # PRINT RESULTS
        print("\n" + "=" * 76)
        print("BRIDGE REGISTERS 0x80..0x8f (CONTROL / IEEE 1284.4 / EPP INTERFACE)")
        print("=" * 76)
        print_comparison_table(regs_high, stage1, stage2, stage3)

        print("\n" + "=" * 76)
        print("BRIDGE REGISTERS 0x00..0x0f (STANDARD CONFIGURATION)")
        print("=" * 76)
        print_comparison_table(regs_low, stage1, stage2, stage3)

        # STAGE 4: INDIRECT CHIP ID CHECK (lm98_iint @ 0x0077e365)
        print("\n" + "=" * 76)
        print("STAGE 4: INDIRECT CHIP ID & VERSION QUERY (via reg 0x89 / 0x8a)")
        print("=" * 76)
        # Write 0x71 to reg 0x89, read reg 0x8a
        w1 = diag.write_reg(0x89, 0x71)
        r_id1 = diag.read_reg(0x8a)
        # Write 0x70 to reg 0x89, read reg 0x8a
        w2 = diag.write_reg(0x89, 0x70)
        r_id2 = diag.read_reg(0x8a)

        def fmid(v): return f"0x{v:02x}" if v is not None else "ERR/STALL"
        print(f"  Write 0x71 -> Reg 0x89 (status={w1}), Read Reg 0x8a: {fmid(r_id1)}")
        print(f"  Write 0x70 -> Reg 0x89 (status={w2}), Read Reg 0x8a: {fmid(r_id2)}")
        if r_id1 is not None and r_id1 == 0x64:
            print("  ==> Identified as Genesys Logic GL640/GL646 architecture (ChipID=0x64)!")
        elif r_id1 is not None:
            print(f"  ==> Chip ID reported: 0x{r_id1:02x}")

        # STAGE 5: EPP ADDRESS & STATUS INTERACTION TEST
        print("\n" + "=" * 76)
        print("STAGE 5: EPP ADDRESS REGISTER (0x83) & STATUS (0x84) INTERACTION TEST")
        print("=" * 76)
        # Test reading EPP status register 0x84
        st84 = diag.read_reg(0x84)
        print(f"  Current Reg 0x84 (EPP Status) : {fmid(st84)}")
        if st84 is not None:
            nBusy   = (st84 >> 7) & 1
            nAck    = (st84 >> 6) & 1
            PError  = (st84 >> 5) & 1
            Select  = (st84 >> 4) & 1
            nFault  = (st84 >> 3) & 1
            print(f"    Decoding IEEE-1284 Status Lines:")
            print(f"      Bit 7 (nBusy / nWait): {nBusy} (1=Ready/High, 0=Busy/Wait)")
            print(f"      Bit 6 (nAck)         : {nAck}")
            print(f"      Bit 5 (PError)       : {PError}")
            print(f"      Bit 4 (Select)       : {Select}")
            print(f"      Bit 3 (nFault)       : {nFault}")

        print("\n[+] Diagnostic completed successfully.")
        return 0

    finally:
        backend.exit()


if __name__ == "__main__":
    sys.exit(main())
