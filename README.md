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
   - On **Windows**, `pie1` acts as a wrapper around the manufacturer's proprietary Windows CyberView DLLs (`ScanAce.dll` / `Twain_32.dll` / `PF1800U.dll`).
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
   - In the GL640USB bridge architecture, writing to register `0x85` initiates an **external hardware EPP Data Strobe cycle** (`nWRITE=0`, `nDATASTB=0`) on the internal parallel bus and waits for the attached ASIC to acknowledge via `nWAIT`.
   - Because VueScan only performed a single IEEE mode negotiation (`pies_ieee(0xe0)`) without the required line strobe sequences, the scanner ASIC remained in parallel standby and never asserted `nWAIT`, causing the USB control transfer on CDB byte 1 (`0x00`) to time out with `LIBUSB_ERROR_TIMEOUT` (`status = -7`).
   - `pies_exec` returns `-1` (`0xff`), which `scsi_exec` packs as `0x80005b00 | (uint8_t)status` $\rightarrow$ `0x80005bff 0400`.

---

## 2. CyberView Protocol Breakthrough (Disassembled `PF1800U.dll`)

By extracting and disassembling the official Pacific Image CyberView driver (`PF1800U.dll`, RVA `0x10001000`–`0x10008000`), the exact proprietary ASIC communication protocol has been mapped:

### A. The 3-Stage IEEE 1284.4 Handshake (`0x10001ed0`)
The scanner ASIC requires a strict 3-stage handshake with explicit line strobe toggling (`0x87`) to transition the parallel bus into active EPP Data Mode:
1. **Stage 1 (Mode 0x30)**: Line strobe reset (`wctl(0x87, 0x04)` twice), followed by signature sync (`0xFF 0xAA 0x55 0x00 0xFF 0x87 0x78` to `0x88`), negotiation byte `0x30`, strobe pulse (`wctl(0x87, 0x05)` $\rightarrow$ `0x04`), and handshake confirm (`0xFF` to `0x88`).
2. **Stage 2 (Mode 0x00)**: Repeats the signature sync with mode `0x00` and strobe pulse.
3. **Stage 3 (Mode 0x80 - EPP Mode)**: Repeats the signature sync with mode `0x80` (EPP Data Mode) and strobe pulse.

### B. Direct ASIC Register Architecture
Once EPP Mode `0x80` is established, the host reads and writes the scanner ASIC registers directly through the GL640USB bridge:
- **Write Register** (`0x10002140`): `wctl(0x83, asic_reg)` $\rightarrow$ `wctl(0x85, value)`
- **Read Register** (`0x100021d0`): `wctl(0x83, asic_reg)` $\rightarrow$ `rctl(0x84)`

### C. Mapped ASIC Register Map
| ASIC Register | Function | Description |
| :--- | :--- | :--- |
| `0x83` | EPP Address | Selects target ASIC internal register |
| `0x84` | EPP Data IN | Read 1 byte from selected ASIC register |
| `0x85` | EPP Data OUT | Write 1 byte to selected ASIC register |
| `0x86` | Status / Ready | Motor busy flag, carriage home sensor, scan ready |
| `0x87` | Line Strobe | EPP hardware line control (`0x04` = normal, `0x05` = strobe) |
| `0x88` | Handshake | IEEE 1284.4 mode negotiation register |
| `0x90..0x92` | Window End | 24-bit scanline length / limit |
| `0x93..0x95` | Window Start | 24-bit scan window start position |
| `0x98..0x9b` | Motor Step | Carriage stepper motor speed and step intervals |
| `0x9c, 0x9d` | Red Exposure | Red channel CCD integration time (LSB, MSB) |
| `0x9e, 0x9f` | Green Exposure | Green channel CCD integration time (LSB, MSB) |
| `0xa0, 0xa1` | Blue Exposure | Blue channel CCD integration time (LSB, MSB) |
| `0xe0` | Red Gain | Analog Front End (AFE) PGA amplifier gain (Red) |
| `0xe2` | Red Offset | AFE DAC black-level clamp offset (Red) |
| `0xe4` | Green Gain | Analog Front End (AFE) PGA amplifier gain (Green) |
| `0xe6` | Green Offset | AFE DAC black-level clamp offset (Green) |
| `0xe8` | Blue Gain | Analog Front End (AFE) PGA amplifier gain (Blue) |
| `0xea` | Blue Offset | AFE DAC black-level clamp offset (Blue) |

### D. Bulk Image Line Acquisition & Sensor Architecture
Image data is acquired over Bulk IN Endpoint 1 (`0x81`) in chunks of **16,200 bytes** (`0x3F48`) triggered by writing the transfer descriptor to register `0x82`:
- **Sensor geometry**: 2,700 physical optical pixels across the 1.5-inch active aperture at 1,800 DPI.
- **Color format**: Interleaved RGB triplets (R, G, B, R, G, B...).
- **Bit depth**: 14-bit linear ADC packed as Little-Endian `uint16_t` words shifted left by 2 bits (`x << 2`, multiples of 4).
- **Line buffer size**: 2,700 pixels $\times$ 3 channels $\times$ 2 bytes = **16,200 bytes** (8,100 `uint16_t` samples).
- **CCD Sampling Gate Clocks**: Registers `0x98=0x01, 0x99=0x00, 0x9a=0x8d, 0x9b=0x2a` configure internal pixel sampling timing.
- **Carriage Stepper Polarity**: Register `0x85 = 0x16` steps forward into film bay; `0x85 = 0x14` retracts to home dock.

---

## 3. Repository Layout

```text
1800i-reloaded/
├── README.md                      # This documentation
├── cyberview_protocol.md          # Technical disassembly analysis of PF1800U.dll
├── libpie1800u/                   # Standalone native C driver library
│   ├── pie1800u.h                 # Driver API header
│   ├── pie1800u.c                 # libusb-1.0 hardware implementation
│   ├── pie1800_cli.c              # Lightweight C acquisition CLI
│   └── Makefile                   # Builds libpie1800u.so, libpie1800u.a, pie1800_cli
├── sane-backend/                  # SANE scanner backend (sane-pie1800u)
│   ├── sane-pie1800u.h            # SANE API interface & types
│   ├── sane-pie1800u.c            # SANE backend driver implementation
│   ├── pie1800u.conf              # SANE daemon device configuration
│   └── Makefile                   # Builds libsane-pie1800u.so.1
├── scripts/
│   ├── pie1800_scan.py            # High-resolution image scanner with auto-positioning & PNG/PPM export
│   ├── test_full_line_16200.py    # 16,200-byte 16-bit uint16 optical line readout benchmark
│   ├── test_sram_read.py          # CCD sampling gate & dark vs light modulation test
│   ├── interactive_jog_and_scan.py# Interactive carriage jogger & optical test console
│   ├── test_motor_jog.py          # Stepper motor distance & speed verification
│   ├── test_cyberview_asic.py     # Live hardware ASIC register reader & 3-stage handshake
│   └── 60-vuescan.rules           # Udev rule for non-root USB access
└── windows_driver/                # Extracted official Pacific Image CyberView components
    ├── PF1800U.dll                # Core hardware driver DLL (exports ScannerDeviceIO)
    ├── RawScan.dll                # Image post-processing & RGB conversion DLL
    ├── PfsLoader.exe              # CyberView loader application
    ├── PScanner.CFG               # Factory calibration profile (PIE Macross 1.103)
    ├── RESOLUTION.RES             # Supported optical resolutions (72 dpi - 7200 dpi)
    ├── CyberViewX.ini             # Driver configuration settings
    └── PF1800U.INF                # Windows driver INF (VID 05E3 & PID 0120)
```

---

## 4. Hardware Acquisition & Scanning

### A. Scanning Full Images with Python
To acquire a high-resolution scan (e.g. 150 lines starting at aperture offset):
```fish
python3 ~/Desktop/1800i-reloaded/scripts/pie1800_scan.py --offset 2000 --lines 150 --out test_scan
```
Options:
- `--offset <steps>`: Advance carriage to active film holder (default: 2000 steps = ~28.2 mm).
- `--lines <N>`: Number of lines to scan (e.g. 1800 lines for a full 1-inch frame).
- `--negative`: Invert colors for color negative film.
- `--out <name>`: Base filename for output `.png`, `.ppm`, and `_raw16.bin`.

### B. Building & Running the Native C Driver Library
```fish
cd ~/Desktop/1800i-reloaded/libpie1800u
make
./pie1800_cli 100 2000 c_scan_preview.ppm
```

### C. Building the SANE Backend
```fish
cd ~/Desktop/1800i-reloaded/sane-backend
make
sudo make install
```
