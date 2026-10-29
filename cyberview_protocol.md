# Pacific Image Electronics (PIE) PrimeFilm 1800u - CyberView Protocol & USB Driver Analysis

This report documents the reverse-engineering analysis of the Windows driver DLL (`PF1800U.dll`, Image Base `0x10000000`) for the **PrimeFilm 1800u** (and related GL640USB-based scanners).

---

## 1. Overview & Architecture

- **ASIC / Bridge**: Genesys Logic GL640USB (EPP-based USB-to-Scanner ASIC bridge).
- **Control Interface**: Win32 `DeviceIoControl` targeting `usbscan.sys` with custom IOCTL codes:
  - `0x80002010`: `IOCTL_SEND_USB_REQUEST` (USB Control Transfer)
  - `0x80002004` / `0x80002008`: Read / Write ASIC registers
- **Key Register Addresses**:
  - `0x83`: EPP Address Register
  - `0x84`: EPP Data IN Register
  - `0x85`: EPP Data OUT Register
  - `0x87`: Line Strobe / Control Register
  - `0x88`: Handshake / IEEE mode Register

---

## 2. Low-Level Register Read/Write Helpers

Disassembly around `0x10001e30` to `0x10002360` reveals helper routines that wrap `DeviceIoControl`:
- **`write_reg(reg, val)`**: Sends a vendor control transfer (or IOCTL `0x80002010`) setting target register index and output data.
- **`read_reg(reg)`**: Reads back register status over control/EPP bulk transfers.

---

## 3. Bridge Initialization Sequence (`0x10001ed0`)

The initialization handshake sequence executed upon device open/reset writes specific patterns to registers `0x87` and `0x88`:
1. Select EPP Address / Data modes.
2. Write signature byte sequences (`0xFF`, `0xFF`, `0xAA`, `0xAA`, `0x55`, `0x55`, `0x00`, `0x00`, etc.) to reset and synchronize the GL640USB bridge handshake state machine.
3. Configure strobe and handshake lines (`0x87`, `0x88`).

---

## 4. Opcode API (`ScannerDeviceIO`)

Exported via `ScannerDeviceIO(int opcode, void* param)` at `0x10007b90`:
- **Opcode 1 (`0x100050a0`)**: Device initialization / reset & status query.
- **Opcode 2 (`0x10005320`)**: Motor homing & stepping configuration.
- **Opcode 3 (`0x10005460`)**: Lamp control (On/Off).
- **Opcode 4 (`0x10005510`)**: Exposure / gain / ADC setup.
- **Opcode 5 (`0x10005520`)**: Scan acquisition trigger & Bulk IN read (`0x81`/`0x82`).
