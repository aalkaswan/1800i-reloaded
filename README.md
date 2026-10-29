# Pacific Image PrimeFilm 1800i / 1800u (`05e3:0120`) Reloaded

Reverse-engineering documentation, full-fidelity decompiled modules, hardware diagnostics, and native Linux driver roadmap for the **Pacific Image Electronics (PIE) PrimeFilm 1800i / 1800u / Reflecta iScan 1800** film scanner.

---

## 1. Executive Summary & Root Cause Findings

### The Core Problem
On Linux, VueScan and SANE report the PrimeFilm 1800i/1800u (`05e3:0120`) as either undetected or unsupported. When forced to connect via binary patches to `pie2_usup` and `_ZL4usbd`, VueScan's SCSI `INQUIRY` command times out after 30 seconds with error code **`80005bff 0400`**.

### The Root Cause Discovered
1. **Hardware Bridge**:
   - The scanner does not contain a modern USB-to-SCSI controller. It uses an early **Genesys Logic GL640USB** USB-to-Parallel (EPP) bridge chip.
   - Internal bridge identification via registers `0x89` / `0x8a` confirms Chip ID **`0x06`** (`GL640USB`), rather than **`0x64`** (`GL646`).
   - The GL640USB's parallel port transceiver is powered down by default and requires writing `0x00` then `0x40` to register `0x8b` (`lm98_iint` sequence at `0x0077e436`).
2. **Scanner ASIC (Pre-SCSI Generation)**:
   - Behind the GL640USB parallel bridge sits a proprietary Pacific Image scanner ASIC.
   - This ASIC **does not implement the SCSI command set** over EPP register `0x85`. When a SCSI CDB byte (such as `0x12` for `INQUIRY`) is written to `0x85`, the ASIC never asserts `nWAIT` acknowledge, wedging the GL640 hardware state machine until power-cycled.
3. **How VueScan Handled It**:
   - In VueScan, `05e3:0120` was assigned to **`pie1.cpp`**, which on Windows dynamically loads the manufacturer's **CyberView Windows DLL** (`CyberView X_SF` / `ScanAce` DLL) via `pie1_gplu` / `pie1_plus`.
   - On Linux, Hamrick stubbed out all functions in `pie1.cpp` to `return 0` (`xor eax, eax; ret`) because Pacific Image never provided a Linux CyberView library.
   - The native Linux driver (**`pie2.cpp`**) was written exclusively for newer models (`05e3:0121`..`0128` like PrimeFilm 1800 AFL, 3600u, 3650u, 7250u), and Hamrick explicitly blacklisted `05e3:0120` in `pie2_usup`:
     ```c
     if (pid == 0x0120 || pid == 0x0129) return 0;
     ```
   - In VueScan's internal table at `0x1efa584`, entry `0xb0` maps `05e3:0120` to `"PF1800U"`, triggering `prob_gmsg`:
     > *"VueScan found PIE PF1800U, but this scanner isn't supported on this operating system."*

---

## 2. Repository Layout

```
1800i-reloaded/
├── README.md                      # This document
├── bin/
│   └── vuescan-1800i-patched      # 32-bit ELF patched to enable 05e3:0120 in pie2_usup and _ZL4usbd
├── decomp/                        # 100% Instruction-level C++11 decompilation of VueScan's PIE engine
│   ├── pie2_common.h              # Unified PIE2_T (17.4 MB) & PIED_T structs with static_asserts
│   ├── test_offsets.cpp           # Struct offset validator (compiled with g++ -m32)
│   ├── pie2_core.cpp / .o         # Core PIE2 engine (33 functions, calibration tables, color constants)
│   ├── pie2_rlin.cpp / .o         # 4-channel RGBI CCD line readout, gain/offset loop, warmup
│   ├── pie2_lsca.cpp / .o         # Scan geometry, exposure integration, pie2_shuf line deinterleaving
│   ├── pied.cpp / .o              # 59 SCSI CDB builders and pied_dump protocol inspector
│   ├── pie1.cpp / .o              # Legacy CyberView plugin interface stubs (pie1_gplu, pie1_plus)
│   └── usbi_gl_bridge.cpp / .o    # Genesys Logic GL646/GL640 USB-to-EPP transport implementation
└── scripts/                       # Live hardware diagnostic and verification utilities
    ├── safe_gl_check.py           # Safe, non-wedging GL640USB register dump (0x89, 0x8a, 0x8b)
    ├── test_inquiry_after_8b.py   # Tests 0x8b=0x40 transceiver enable + pies_ieee before SCSI CDB
    ├── diag_gl_regs.py            # Comprehensive 0x80..0x8f and 0x00..0x0f register probe
    └── probe_1800i.py             # Read-only SCSI INQUIRY probe with libusb backend
```

---

## 3. Hardware Architecture & Register Specifications

### USB Device Identifiers
- **Vendor ID**: `0x05e3` (Genesys Logic, Inc.)
- **Product ID**: `0x0120` (PrimeFilm 1800u / 1800i)
- **Bulk IN Endpoint**: `0x81` (Max Packet Size: 64 bytes)
- **Bulk OUT Endpoint**: `0x02` (Max Packet Size: 64 bytes)

### Genesys Logic GL640USB Register Map (`bRequest = 0x0c` / `0x04`)

| Register | Direction | Function | Hardware Behavior on GL640USB |
| :--- | :--- | :--- | :--- |
| **`0x87`** | Write | Parallel Port Control Latch | Sets raw `/STROBE`, `/AUTOFD`, `/INIT`, `/SELECTIN` GPIO lines. Safe to write. |
| **`0x88`** | Write | Parallel Port Data Latch | Latches 8-bit data onto parallel pins without hardware strobe. Used for IEEE-1284 unlock (`ff aa 55 00 ff 87 78`). Safe to write. |
| **`0x89`** | Write | Indirect Register Address | Selects internal GL640 configuration register (e.g. `0x71`). |
| **`0x8a`** | Read | Indirect Register Data | Reads selected internal register. Returns **`0x06`** on GL640USB (vs `0x64` on GL646). |
| **`0x8b`** | Write | Transceiver & Power Control | **`0x00` $\rightarrow$ wait 500ms $\rightarrow$ `0x40`** powers on and enables the parallel bus transceiver. |
| **`0x83`** | Write | EPP Address Strobe (`nADDRSTB`) | Asserts hardware address strobe on parallel bus. **Will wedge EP0 if peripheral does not assert `nWAIT`!** |
| **`0x84`** | Read | EPP Data Read (`nDATASTB`) | Reads data byte from parallel bus. **Will wedge EP0 if peripheral does not assert `nWAIT`!** |
| **`0x85`** | Write | EPP Data Write (`nDATASTB`) | Latches byte and asserts data strobe. **Will wedge EP0 if peripheral does not assert `nWAIT`!** |

> [!WARNING]
> If a software command writes to `0x85` or `0x83` and the scanner ASIC does not toggle `nWAIT`, the GL640 chip's internal 8051 state machine hangs. All subsequent USB control requests on `EP0` will return `LIBUSB_ERROR_TIMEOUT` (`-7`) until the scanner's 12V DC power is cycled.

---

## 4. Live Verification Results on Hardware

### Result 1: Internal Register Probe (`scripts/safe_gl_check.py`)
```text
=== Safe Internal GL640USB / GL646 Probe (05e3:0120) ===
[+] Bridge EP0 is LIVE! Indirect Reg 0x71 (via 0x89/0x8a): status=1, value=0x06

[*] Dumping internal indirect registers 0x70..0x77 via 0x89 -> 0x8a:
    Indirect[0x70] = 0x00
    Indirect[0x71] = 0x06
    Indirect[0x72] = 0x05
    Indirect[0x73] = 0x04
    Indirect[0x74] = 0x03
    Indirect[0x75] = 0x02
    Indirect[0x76] = 0x01
    Indirect[0x77] = 0x00

[*] Chip ID != 0x64; running lm98_iint bridge reset/enable on reg 0x8b (0x00 -> 0x40)...
    wctl(0x8b, 0x00) -> 1, wctl(0x8b, 0x40) -> 1
```

### Result 2: SCSI-over-EPP Attempt (`scripts/test_inquiry_after_8b.py`)
```text
[1] Checking EP0 via 0x89/0x8a...
    Indirect[0x71] = 0x06
[2] Enabling GL640USB transceiver via reg 0x8b (0x00 -> 500ms -> 0x40 -> 500ms)...
[3] Running pies_init: pies_ieee(0x30)...
    pies_ieee(0x30) -> 0
[4] Running pies_exec: pies_ieee(0xe0)...
    pies_ieee(0xe0) -> 0
[5] Sending 6-byte SCSI INQUIRY CDB (12 00 00 00 24 00) to reg 0x85...
    CDB[0] = 0x12 -> status=1
    CDB[1] = 0x00 -> status=-7
[!] Timed out at CDB[1]! (05e3:0120 ASIC does not ACK SCSI-over-EPP on 0x85)
```

---

## 5. Roadmap: Building the Native Linux Driver (Option 2)

Because the scanner ASIC expects the proprietary CyberView protocol rather than SCSI-over-EPP, the path to a native open-source driver is to dissect the 32-bit Windows CyberView driver package.

### Step 1: Obtain the Windows CyberView Driver Archive
- Target package: **`PrimeFilm 1800U / 1800I / 1800 Silver Scanner Driver v1.171`** (or `CyberView X_SF` installer for Windows 98/2000/XP).
- Extract the installer using `innoextract`, `7z`, or `cabextract`.
- Identify the core transport DLLs (typically `ScanAce.dll`, `PIE1800.dll`, or `Twain_32.dll`).

### Step 2: Reverse-Engineer the Driver Transport Boundary
- Disassemble the DLLs to map:
  1. **Handshake Sequence**: How CyberView initializes the GL640USB bridge and scanner ASIC.
  2. **Register Protocol**: How CyberView addresses registers (e.g., using EPP address register `0x83` followed by data `0x85`/`0x84`, or raw control line pulsing via `0x87`).
  3. **Stepper Motor Commands**: Stepping the slide carriage forward/backward.
  4. **Exposure & Lamp Control**: Setting LED/CCFL exposure times and analog front-end (AFE) gain/offset.
  5. **CCD Line Readout**: Triggering line scans and reading pixel data over Bulk IN (`0x81`).

### Step 3: Implement Standalone Driver & SANE Backend
- Create a standalone user-space CLI tool in Python/C (`pie1800-scan`) using `libusb-1.0`.
- Once verified on hardware, package the driver as a SANE backend (`sane-pie1800u`) to provide native scanning in XSane, Simple Scan, and GIMP on modern Linux systems.
