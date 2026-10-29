# PrimeFilm 1800i / 1800u (`05e3:0120`) Reloaded

Reverse-engineering documentation, decompiled driver sources, diagnostic tools, and native Linux driver implementation for the **Pacific Image Electronics (PIE) PrimeFilm 1800i / 1800u** 35mm film scanner (`USB VID:PID 05e3:0120`).

---

## 1. Executive Summary & Root Cause Analysis

### The Problem
When running VueScan on Linux with the PrimeFilm 1800i/1800u connected, VueScan either reports that the scanner is unsupported or hangs/fails during initialization with:
```text
INQUIRY 12 0 0 0 24 0 -> 80005bff 0400
```

### The Root Cause
1. **Architectural Separation in VueScan (`pie1` vs `pie2`)**:
   - In VueScan's driver dispatch table at `0x1efa584`, entry `0xb0` maps `05e3:0120` (`PF1800U`) and entry `0xb1` maps `05e3:0129` (`PF2700`) to the **`pie1`** driver module.
   - On **Windows**, `pie1` (`pie1_gplu` / `pie1_plus`) acts as a wrapper around the manufacturer's proprietary Windows CyberView DLLs (`ScanAce.dll` / `Twain_32.dll`).
   - On **Linux**, PIE never published Linux CyberView libraries. Ed Hamrick stubbed out `pie1.cpp` to return `0` and configured `prob_gmsg` to report:
     > *"VueScan found PIE PF1800U, but this scanner isn't supported on this operating system."*
   - Hamrick's native Linux driver, **`pie2.cpp`**, was developed exclusively for newer, SCSI-compliant PIE models: `05e3:0121` (PrimeFilm 1800 AFL), `3600u`, `3650u`, `7250u`.
   - `pie2_usup` explicitly rejects the `0120` and `0129` PIDs:
     ```cpp
     if (pid == 0x0120 || pid == 0x0129) return 0;
     ```

2. **The `80005bff 0400` Error Explained**:
   - When `pie2_usup` is patched to force VueScan's native `pie2` SCSI engine onto the `05e3:0120`, VueScan attempts to issue a standard 6-byte SCSI INQUIRY CDB (`12 00 00 00 24 00`) via `scsi_exec` $\rightarrow$ `pies_exec`.
   - `pies_exec` attempts to write the SCSI CDB bytes one-by-one to USB bridge register `0x85` (Genesys Logic EPP Data Register).
   - In the GL640USB / GL646 bridge architecture, a write to register `0x85` initiates an **external hardware EPP Data Strobe cycle** (`nWRITE=0`, `nDATASTB=0`) on the internal parallel bus and waits for the attached ASIC to acknowledge via `nWAIT`.
   - The older `05e3:0120` scanner ASIC is **pre-SCSI**; it communicates via direct internal register writes rather than a SCSI command block parser. As a result, the ASIC never asserts `nWAIT`, causing the USB control endpoint transfer on CDB byte 1 (`0x00`) to time out with `LIBUSB_ERROR_TIMEOUT` (`status = -7`).
   - `pies_exec` returns `-1` (`0xff`), which `scsi_exec` packs as `0x80005b00 | (uint8_t)status` $\rightarrow$ `0x80005bff 0400`.

3. **Bridge Hardware Verification**:
   - Live hardware interrogation via safe indirect registers `0x89` $\rightarrow$ `0x8a` confirmed the bridge chip is an early **Genesys Logic GL640USB** (`Indirect[0x71] == 0x06`), distinct from the GL646 (`0x64`).
   - In GL640USB mode, the internal transceiver must be enabled by writing `0x00` followed by `0x40` to register `0x8b` (`lm98_iint`). While this successfully enables the bridge, SCSI CDB transfers on `0x85` remain unsupported by the underlying ASIC.

---

## 2. Repository Layout

```text
1800i-reloaded/
├── README.md                      # This documentation
├── bin/
│   └── vuescan-1800i-patched      # 32-bit Linux binary patched to bypass PID rejection in pie2_usup
├── decomp/
│   ├── pie2_common.h              # Unified header with complete PIE2_T struct (17,466,260 bytes)
│   ├── test_offsets.cpp           # Struct layout & offset verification test
│   ├── pie2_core.cpp              # 33 native driver core methods (alloc, open, close, calibration)
│   ├── pie2_rlin.cpp              # 4-channel RGBI line readout with 16-bit channel scaling
│   ├── pie2_lsca.cpp              # Scan geometry, line deinterleaving, exposure compensation
│   ├── pie2_scan_engine.cpp       # Scan coordination, autofocus, optical calibration loops
│   ├── pied.cpp                   # 59 complete SCSI CDB command packet builders
│   ├── pie1.cpp                   # Legacy CyberView plugin wrapper stubs
│   ├── usbi_gl_bridge.cpp         # Genesys Logic GL640/GL646 USB transport layer
│   └── *.o                        # Precompiled 32-bit ELF object files
└── scripts/
    ├── safe_gl_check.py           # Safe non-stalling hardware query via GL indirect registers
    ├── test_inquiry_after_8b.py   # Transceiver enable (0x8b) and IEEE 1284.4 handshake test
    ├── diag_gl_regs.py            # Comprehensive bridge register diagnostics
    ├── probe_1800i.py             # Low-level SCSI / IEEE inquiry probe
    └── 60-vuescan.rules           # Udev rule for non-root USB access
```

---

## 3. Decompiled C++11 Driver Modules

The decompiled modules in `decomp/` are instruction-level matching C++11 implementations reversed from VueScan:

| File | Purpose | Key Symbols / Capabilities |
| :--- | :--- | :--- |
| [`pie2_common.h`](decomp/pie2_common.h) | Unified Data Structures | Defines `PIE2_T` (`sizeof == 0x10a8394`), buffer pointers, scan parameters, geometry limits |
| [`pie2_core.cpp`](decomp/pie2_core.cpp) | Core Engine | `pie2_init`, `pie2_open`, `pie2_clos`, `pie2_scsi`, `pie2_cbuf`, `pie2_errs` (33 functions) |
| [`pie2_rlin.cpp`](decomp/pie2_rlin.cpp) | Line Read Engine | `pie2_rlin` (4-channel RGB + Infrared 16-bit packed scaling and line acquisition) |
| [`pie2_lsca.cpp`](decomp/pie2_lsca.cpp) | Geometry & Deinterleave | `pie2_lsca` (line deinterleaving, CCD staggered line spacing, optical cropping) |
| [`pie2_scan_engine.cpp`](decomp/pie2_scan_engine.cpp) | Calibration & Orchestration | `pie2_scan`, `pie2_sexp`, `pie2_afoc` (motor control loops, exposure calibration) |
| [`pied.cpp`](decomp/pied.cpp) | SCSI Protocol Builder | 59 command block builders: `pied_inquiry`, `pied_scan`, `pied_read`, `pied_set_window`, etc. |
| [`pie1.cpp`](decomp/pie1.cpp) | Legacy Plugin Stubs | `pie1_init`, `pie1_gplu`, `pie1_plus` (Windows DLL bridge stubs) |
| [`usbi_gl_bridge.cpp`](decomp/usbi_gl_bridge.cpp) | Genesys Logic Transport | `usbi_icmd`, `usbi_wctl`, `usbi_rctl`, `usbi_rbul`, `usbi_wbul` |

### Building the Decompiled Modules
To compile the modules into 32-bit ELF object files:
```bash
cd decomp
g++ -m32 -O3 -std=c++11 -Wall -Wextra -c pie2_core.cpp
g++ -m32 -O3 -std=c++11 -Wall -Wextra -c pie2_rlin.cpp
g++ -m32 -O3 -std=c++11 -Wall -Wextra -c pie2_lsca.cpp
g++ -m32 -O3 -std=c++11 -Wall -Wextra -c pied.cpp
g++ -m32 -O3 -std=c++11 -Wall -Wextra -c pie1.cpp
g++ -m32 -O3 -std=c++11 -Wall -Wextra -c usbi_gl_bridge.cpp
g++ -m32 -O3 -std=c++11 -o test_offsets test_offsets.cpp
./test_offsets
```

---

## 4. Hardware Verification & Diagnostic Scripts

### Udev Permissions
Ensure your user has access to the scanner device node without needing `sudo`:
```bash
sudo cp scripts/60-vuescan.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

### Safe GL640USB Register Check (`safe_gl_check.py`)
Queries the Genesys Logic internal indirect registers (`0x89` $\rightarrow$ `0x8a`) and exercises the `0x8b` transceiver enable safely without touching external parallel bus strobes:
```bash
python3 scripts/safe_gl_check.py
```
*Observed Output on Physical PrimeFilm 1800i:*
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

---

## 5. Roadmap: Building the Native Driver (Option 2)

Because the `05e3:0120` ASIC does not support SCSI encapsulation over EPP, building full open-source Linux support requires implementing the CyberView ASIC protocol directly:

1. **Phase 1: Disassemble CyberView Windows Driver**:
   - Extract the 32-bit Windows CyberView driver package (`ScanAce.dll` / `PfsLoader.exe`).
   - Disassemble the register I/O routines communicating through GL640USB registers (`0x83`, `0x84`, `0x86`, `0x87`).
2. **Phase 2: Protocol Mapping**:
   - Document the ASIC register addresses for:
     - Optical carriage stepper motor (forward/backward step pulses, home sensor detection).
     - Analog Front End (AFE) configuration: Red, Green, Blue, Infrared gain, black level clamp, ADC calibration.
     - Exposure integration time and LED lamp control.
     - Bulk IN line buffer readout parameters over Endpoint 1 (`0x81`).
3. **Phase 3: Standalone Python/C++ Driver**:
   - Implement `scripts/pie1800_driver.py` using `pyusb` / `libusb-1.0` to initialize the bridge, home the carriage, and capture raw scanline buffers.
4. **Phase 4: SANE Backend (`sane-pie1800u`)**:
   - Port the standalone driver logic into a standard SANE backend for seamless integration with XSane, Simple Scan, and GIMP on Linux.
