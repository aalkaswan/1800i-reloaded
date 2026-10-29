#!/usr/bin/env python3
"""
probe_1800i.py - Strictly Read-Only SCSI INQUIRY probe for PIE film scanners (05e3:0120)
Based on decompiled VueScan GL646 bridge driver: /tmp/vuescan/decomp/usbi_gl_bridge.cpp

Implements:
  1. pies_ieee: IEEE 1284.4 / EPP Handshake initialization (0x00669030)
  2. usbi_icmd: Write SCSI CDB bytes to bridge register 0x85
  3. usbi_irsp: Read bridge status byte from register 0x84
  4. usbi_irda: DMA setup descriptor and Bulk IN transfer (ep 0x81)
  5. scsi_usbi: Read-only INQUIRY (opcode 0x12, alloc_len 0xb8 = 184 bytes)
  6. INQUIRY block parser (VID, PID, Rev, max_dpi, firmware, model_id @ +0x74)

STRICTLY READ-ONLY: Never sends any write, erase, or flash commands.
"""

import sys
import time
import struct
import argparse
import ctypes

# Genesys Logic GL646 Constants
GL_REQ_REG_READ  = 0x0c
GL_REQ_REG_WRITE = 0x0c
GL_REQ_DMA_SETUP = 0x04

GL_REG_STATUS    = 0x84
GL_REG_DATA      = 0x85
GL_REG_CONTROL   = 0x87
GL_REG_HANDSHAKE = 0x88

GL_STATUS_GOOD       = 0x00
GL_STATUS_DATA_IN    = 0x01
GL_STATUS_CHECK_COND = 0x02
GL_STATUS_BUSY       = 0x03

USB_CTRL_OUT = 0x40
USB_CTRL_IN  = 0xc0

EP_IN_DEFAULT  = 0x81
EP_OUT_DEFAULT = 0x02

# Known PIE Model Descriptors from VueScan (_ZL4piem)
PIE_MODELS = {
    0x20: "PrimeFilm 1800",
    0x21: "PrimeFilm 1800 Silver",
    0x22: "PrimeFilm 1800U / iScan 1800",
    0x23: "PrimeFilm 2700 / iScan 2700",
    0x24: "PrimeFilm 3600 / iScan 3600 Pro",
    0x25: "PrimeFilm 1800i",
    0x26: "PrimeFilm 3600u",
    0x27: "PrimeFilm 3650u",
    0x28: "PrimeFilm 3650 Pro3",
    0x29: "PrimeFilm 7250u",
    0x2a: "PrimeFilm 7250 Pro3",
    0x2b: "PrimeFilm 120",
    0x2c: "PrimeFilm 120 Pro",
    0x30: "PowerSlide 3600",
    0x31: "PowerSlide 3650",
    0x32: "PowerSlide 5000",
    0x34: "PrimeFilm X",
    0x35: "PrimeFilm XA",
    0x36: "PrimeFilm XE",
    0x40: "Uniscan Film Scanner",
    0x43: "Braun FS 120",
    0x46: "PrimeFilm 7200",
    0x47: "PrimeFilm 7250",
    0x48: "PrimeFilm 120 (Reflecta MF5000)",
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

        self.lib.libusb_bulk_transfer.argtypes = [
            ctypes.POINTER(libusb_device_handle),
            ctypes.c_uint8,                 # endpoint
            ctypes.POINTER(ctypes.c_uint8), # data
            ctypes.c_int,                   # length
            ctypes.POINTER(ctypes.c_int),   # transferred
            ctypes.c_uint                   # timeout
        ]
        self.lib.libusb_bulk_transfer.restype = ctypes.c_int

        self.ctx = ctypes.POINTER(libusb_context)()
        r = self.lib.libusb_init(ctypes.byref(self.ctx))
        if r < 0:
            raise RuntimeError(f"libusb_init failed: {r}")

        self.handle = None

    def strerror(self, code):
        s = self.lib.libusb_strerror(code)
        return s.decode() if s else f"code {code}"

    def open(self, vid=0x05e3, pid=0x0120):
        self.handle = self.lib.libusb_open_device_with_vid_pid(self.ctx, vid, pid)
        if not self.handle:
            return False
        # Try to detach kernel driver if active
        self.lib.libusb_detach_kernel_driver(self.handle, 0)
        # Claim interface 0
        r = self.lib.libusb_claim_interface(self.handle, 0)
        if r < 0:
            print(f"[!] Warning: libusb_claim_interface failed: {self.strerror(r)}")
        return True

    def reset(self):
        if self.handle:
            r = self.lib.libusb_reset_device(self.handle)
            return r >= 0
        return False

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

    def control_out(self, req, value, index, data, timeout=5000):
        n = len(data)
        buf = (ctypes.c_uint8 * n)(*data) if n > 0 else ctypes.POINTER(ctypes.c_uint8)()
        r = self.lib.libusb_control_transfer(self.handle, USB_CTRL_OUT, req, value, index, buf, n, timeout)
        return r

    def control_in(self, req, value, index, length, timeout=5000):
        buf = (ctypes.c_uint8 * length)()
        r = self.lib.libusb_control_transfer(self.handle, USB_CTRL_IN, req, value, index, buf, length, timeout)
        if r < 0:
            return r, bytes()
        return r, bytes(buf[:r])

    def bulk_in(self, ep, length, timeout=5000):
        buf = (ctypes.c_uint8 * length)()
        transferred = ctypes.c_int(0)
        r = self.lib.libusb_bulk_transfer(self.handle, ep, buf, length, ctypes.byref(transferred), timeout)
        if r < 0:
            return r, bytes()
        return transferred.value, bytes(buf[:transferred.value])


class UsbiGlBridge:
    def __init__(self, backend, timeout_ms=5000):
        self.backend = backend
        self.timeout_ms = timeout_ms

    def write_reg(self, reg, val):
        """Write single byte to GL646 bridge register (0x00582a3c / usbi_gl_bridge.cpp)."""
        r = self.backend.control_out(GL_REQ_REG_WRITE, reg, 0, bytes([val]), timeout=self.timeout_ms)
        return r

    def read_reg(self, reg):
        """Read single byte from GL646 bridge register."""
        r, data = self.backend.control_in(GL_REQ_REG_READ, reg, 0, 1, timeout=self.timeout_ms)
        if r >= 0 and len(data) > 0:
            return data[0]
        return -1

    def pies_ieee(self, mode=0xe0):
        """
        IEEE 1284.4 / EPP Handshake initialization (0x00669030 in VueScan).
        Writes 7 magic bytes to register 0x88, mode to 0x88, pulses reg 0x87, then 0xff to 0x88.
        """
        magic = [0xff, 0xaa, 0x55, 0x00, 0xff, 0x87, 0x78]
        for i, b in enumerate(magic):
            if self.write_reg(GL_REG_HANDSHAKE, b) < 0:
                print(f"[!] pies_ieee failed writing magic byte {i} (0x{b:02x})")
                return -1

        if self.write_reg(GL_REG_HANDSHAKE, mode) < 0:
            print(f"[!] pies_ieee failed setting mode 0x{mode:02x}")
            return -1

        time.sleep(0.020)  # 20ms VueScan stabilization delay

        if self.write_reg(GL_REG_CONTROL, 0x05) < 0:
            return -1
        if self.write_reg(GL_REG_CONTROL, 0x04) < 0:
            return -1
        if self.write_reg(GL_REG_HANDSHAKE, 0xff) < 0:
            return -1

        time.sleep(0.020)  # 20ms delay
        return 0

    def dump_registers(self, label=""):
        """Dump GL registers 0x80..0x8f and 0x00..0x0f."""
        print(f"\n--- [GL Register Dump: {label}] ---")
        regs_high = [f"0x{r:02x}: " + (f"0x{v:02x}" if (v := self.read_reg(r)) is not None and v >= 0 else "ERR") for r in range(0x80, 0x90)]
        regs_low = [f"0x{r:02x}: " + (f"0x{v:02x}" if (v := self.read_reg(r)) is not None and v >= 0 else "ERR") for r in range(0x00, 0x10)]
        print("  0x80..0x87: " + " ".join(regs_high[:8]))
        print("  0x88..0x8f: " + " ".join(regs_high[8:]))
        print("  0x00..0x07: " + " ".join(regs_low[:8]))
        print("  0x08..0x0f: " + " ".join(regs_low[8:]))

    def usbi_icmd(self, cdb):
        """Send SCSI CDB (6 bytes) sequentially to data register 0x85 (0x0066928d)."""
        for i, b in enumerate(cdb):
            r = self.write_reg(GL_REG_DATA, b)
            if r < 0:
                print(f"[!] usbi_icmd failed on CDB byte {i} (0x{b:02x}), return code: {r}")
                st = self.read_reg(GL_REG_STATUS)
                if st is not None and st >= 0:
                    print(f"    Bridge status reg 0x84 after failure: 0x{st:02x} (nBusy={(st>>7)&1}, nAck={(st>>6)&1}, PError={(st>>5)&1}, Select={(st>>4)&1}, nFault={(st>>3)&1})")
                else:
                    print(f"    Failed to read reg 0x84 after failure")
                return -1
        return 0

    def usbi_irsp(self):
        """Read status byte from register 0x84 (0x006692cf)."""
        st = self.read_reg(GL_REG_STATUS)
        return st

    def usbi_irda(self, length, ep_in=EP_IN_DEFAULT):
        """
        Setup DMA transfer descriptor and execute Bulk IN read (0x00669425).
        DMA descriptor (8 bytes): [len[0], len[1], len[2], 0x01 (IN), 0, 0, 0, 0]
        """
        max_chunk = 0xfe00
        received = bytearray()

        while len(received) < length:
            chunk = min(length - len(received), max_chunk)

            # Setup DMA transfer descriptor
            dma_desc = bytes([
                chunk & 0xff,
                (chunk >> 8) & 0xff,
                (chunk >> 16) & 0xff,
                0x01,  # Direction: IN
                0x00, 0x00, 0x00, 0x00
            ])

            r_dma = self.backend.control_out(GL_REQ_DMA_SETUP, 0x0082, 0x0008, dma_desc, timeout=self.timeout_ms)
            if r_dma < 0:
                print(f"[!] usbi_irda: DMA setup failed: {r_dma}")
                return bytes(received)

            # Bulk read from endpoint 0x81
            transferred, chunk_data = self.backend.bulk_in(ep_in, chunk, timeout=self.timeout_ms)
            if transferred < 0:
                print(f"[!] usbi_irda: Bulk read failed: {transferred}")
                break

            received.extend(chunk_data)
            if transferred < chunk:
                break  # Short packet

        return bytes(received)

    def scsi_usbi_inquiry(self, alloc_len=184):
        """
        Top-level dispatcher executing SCSI INQUIRY (0x12) via scsi_usbi (0x00669230).
        alloc_len=0xb8 (184 bytes).
        """
        self.dump_registers("Stage 1: Raw initial state before handshake")

        print(f"[*] Step 1a: Performing pies_init handshake (pies_ieee, mode=0x30)...")
        self.pies_ieee(mode=0x30)
        self.dump_registers("Stage 2: After pies_init (mode=0x30)")

        print(f"[*] Step 1b: Performing IEEE 1284.4 handshake (pies_ieee, mode=0xe0)...")
        if self.pies_ieee(mode=0xe0) < 0:
            print("[!] Bridge negotiation failed.")
            return -1, bytes()
        self.dump_registers("Stage 3: After pies_exec (mode=0xe0)")

        print(f"[*] Step 2: Sending SCSI INQUIRY CDB (0x12, alloc_len={alloc_len} = 0x{alloc_len:02x})...")
        cdb = [0x12, 0x00, 0x00, 0x00, alloc_len & 0xff, 0x00]
        if self.usbi_icmd(cdb) < 0:
            print("[!] CDB send failed.")
            return -1, bytes()

        print(f"[*] Step 3: Querying bridge execution status (register 0x84)...")
        st = self.usbi_irsp()
        print(f"    Bridge status byte: 0x{st:02x} (status_name: {self.status_name(st)})")

        data = bytes()
        if st == GL_STATUS_DATA_IN or st == GL_STATUS_GOOD:
            print(f"[*] Step 4: Device ready for data phase. Reading {alloc_len} bytes via DMA...")
            data = self.usbi_irda(alloc_len)
            print(f"    Received {len(data)} / {alloc_len} bytes.")

        print(f"[*] Step 5: Reading final completion status...")
        final_st = self.usbi_irsp()
        print(f"    Final status: 0x{final_st:02x} ({self.status_name(final_st)})")

        return final_st, data

    @staticmethod
    def status_name(st):
        names = {
            0x00: "GL_STATUS_GOOD",
            0x01: "GL_STATUS_DATA_IN",
            0x02: "GL_STATUS_CHECK_COND",
            0x03: "GL_STATUS_BUSY",
        }
        return names.get(st, f"UNKNOWN (0x{st:02x})")


def parse_inquiry_block(data):
    """
    Parses the 184-byte (0xb8) Pacific Image Electronics / VueScan INQUIRY block.
    Reference: pied_dump (0x006610c0..0x00665bf5) and pie2_open (0x0065ddc0..0x0065de50).
    """
    if len(data) < 36:
        print(f"[!] Warning: INQUIRY payload too short ({len(data)} bytes, minimum standard 36).")
        return

    print("\n" + "=" * 70)
    print("PACIFIC IMAGE ELECTRONICS - SCSI INQUIRY (184-BYTE BLOCK) PARSED FIELDS")
    print("=" * 70)

    # Standard SCSI Inquiry fields
    periph_device_type = data[0] & 0x1f
    rmb = (data[1] >> 7) & 1
    version = data[2]
    response_data_format = data[3] & 0x0f
    additional_length = data[4]

    vendor = data[8:16].decode("latin1", errors="replace").strip()
    product = data[16:32].decode("latin1", errors="replace").strip()
    revision = data[32:36].decode("latin1", errors="replace").strip()

    print(f"  [+0x00] Peripheral Device Type : 0x{periph_device_type:02x} "
          f"({'Scanner' if periph_device_type == 6 else 'Unknown'})")
    print(f"  [+0x01] Removable Media Bit (RMB): {rmb}")
    print(f"  [+0x02] SCSI Version           : 0x{version:02x}")
    print(f"  [+0x03] Response Data Format   : 0x{response_data_format:02x}")
    print(f"  [+0x04] Additional Length      : {additional_length} bytes")
    print(f"  [+0x08] Vendor Identification  : '{vendor}'")
    print(f"  [+0x10] Product Identification : '{product}'")
    print(f"  [+0x20] Product Revision Level : '{revision}'")

    if len(data) >= 0x28:
        # Resolutions (+0x24..0x27): Optical and Maximum DPI
        # pie2_open: [esp+0x5a] = WORD PTR [esp+0x34 + 0x26]
        opt_dpi = struct.unpack(">H", data[0x24:0x26])[0] if len(data) >= 0x26 else 0
        max_dpi = struct.unpack(">H", data[0x26:0x28])[0] if len(data) >= 0x28 else 0
        # Check little-endian alternative if big-endian is anomalous
        if max_dpi > 20000 or max_dpi == 0:
            max_dpi_le = struct.unpack("<H", data[0x26:0x28])[0]
            if 600 <= max_dpi_le <= 10000:
                max_dpi = max_dpi_le
        print(f"  [+0x24] Optical Resolution     : {opt_dpi} DPI")
        print(f"  [+0x26] Maximum Resolution     : {max_dpi} DPI (max_dpi)")

    if len(data) >= 0x30:
        fw_ver = data[0x2c:0x30].decode("latin1", errors="replace").strip()
        print(f"  [+0x2c] Firmware Version       : '{fw_ver}'")

    # PIE Model ID at offset +0x74 (pie2_open @ 0x0065dde2: movzx eax, WORD PTR [esp+0xa8 = 0x34+0x74])
    if len(data) > 0x74:
        model_id = data[0x74]
        model_name = PIE_MODELS.get(model_id, f"Unknown Model (0x{model_id:02x})")
        print(f"  [+0x74] PIE Model ID           : 0x{model_id:02x} ({model_id} dec) -> {model_name}")

    if len(data) >= 0x76:
        max_w = struct.unpack(">H", data[0x70:0x72])[0] if len(data) >= 0x72 else 0
        max_h = struct.unpack(">H", data[0x72:0x74])[0] if len(data) >= 0x74 else 0
        if max_w > 0 or max_h > 0:
            print(f"  [+0x70] Maximum Scan Dimensions: Width={max_w}, Height={max_h}")

    # Capability flags decoded by pied_dump (0x00663cd0..0x00665bc0)
    print("\n  [Detected Hardware Capabilities / Flags]:")
    caps = []
    if len(data) > 0x35 and (data[0x35] & 0x01): caps.append("Transparency Unit / Film Holder")
    if len(data) > 0x37 and (data[0x37] & 0x02): caps.append("Multi-Exposure Support")
    if len(data) > 0x38 and (data[0x38] & 0x04): caps.append("Digital ICE / Infrared Channel")
    if len(data) > 0x39 and (data[0x39] & 0x08): caps.append("Hardware Auto-Focus")
    if len(data) > 0x40 and (data[0x40] & 0x01): caps.append("16-bit Color Depth")
    if len(data) > 0x41 and (data[0x41] & 0x02): caps.append("Calibration Equation Table")
    if len(data) > 0x44 and (data[0x44] & 0x04): caps.append("Optical System Shading Calibration")
    if caps:
        for c in caps:
            print(f"    * {c}")
    else:
        print("    * Standard single-pass film scanner profile")

    # Formatted Hex / ASCII Dump
    print("\n" + "=" * 70)
    print(f"RAW HEX DUMP OF INQUIRY BLOCK ({len(data)} BYTES)")
    print("=" * 70)
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hex_str = " ".join(f"{b:02x}" for b in chunk)
        asc_str = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
        print(f"  0x{i:03x} (0x{i:03x}):  {hex_str:<48}  |{asc_str}|")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Probe PIE 05e3:0120 Film Scanner using read-only SCSI INQUIRY (184 bytes)"
    )
    parser.add_argument("--vid", type=lambda x: int(x, 16), default=0x05e3,
                        help="USB Vendor ID (default: 0x05e3)")
    parser.add_argument("--pid", type=lambda x: int(x, 16), default=0x0120,
                        help="USB Product ID (default: 0x0120)")
    parser.add_argument("--mode", type=lambda x: int(x, 16), default=0xe0,
                        help="IEEE 1284.4 negotiation mode (default: 0xe0, alt: 0x30)")
    parser.add_argument("--timeout", type=int, default=10000,
                        help="Transfer timeout in ms (default: 10000)")
    parser.add_argument("--alloc-len", type=int, default=184,
                        help="INQUIRY allocation length in bytes (default: 184 = 0xb8)")
    parser.add_argument("--reset", action="store_true",
                        help="Issue USB device reset before probe")
    parser.add_argument("--out", type=str, default="/tmp/vuescan/inquiry_dump.bin",
                        help="Path to save raw 184-byte binary dump")
    args = parser.parse_args()

    print("=" * 70)
    print("PIE FILM SCANNER READ-ONLY INQUIRY PROBE (05e3:0120)")
    print("Strictly read-only: No write or flash commands are executed.")
    print("=" * 70)
    print(f"Target VID:PID : 0x{args.vid:04x}:0x{args.pid:04x}")
    print(f"Bridge Mode    : 0x{args.mode:02x}")
    print(f"Timeout        : {args.timeout} ms")
    print(f"Alloc Length   : {args.alloc_len} bytes (0x{args.alloc_len:02x})")

    backend = LibUsbBackend()
    try:
        print(f"\n[*] Opening USB device 0x{args.vid:04x}:0x{args.pid:04x}...")
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

        bridge = UsbiGlBridge(backend, timeout_ms=args.timeout)

        # Execute read-only SCSI INQUIRY (184 bytes)
        status, inq_data = bridge.scsi_usbi_inquiry(alloc_len=args.alloc_len)

        if inq_data and len(inq_data) > 0:
            print(f"\n[+] Successfully dumped {len(inq_data)} bytes from scanner!")
            parse_inquiry_block(inq_data)

            if args.out:
                try:
                    with open(args.out, "wb") as f:
                        f.write(inq_data)
                    print(f"\n[+] Saved raw binary INQUIRY block to: {args.out}")
                except Exception as e:
                    print(f"[!] Could not save binary dump: {e}")
            return 0
        else:
            print(f"\n[!] INQUIRY command did not return data (status=0x{status:02x}).")
            print("    Note: The physical scanner hardware may need to be power-cycled or")
            print("    its optical carriage may be in transit.")
            return 2

    finally:
        backend.exit()


if __name__ == "__main__":
    sys.exit(main())
