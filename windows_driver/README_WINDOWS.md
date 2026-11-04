# Windows 10 & 11 Setup Guide: PrimeFilm 1800u / 1800i

This guide covers running the **PrimeFilm Studio UI** and C library on 64-bit Windows 10 and Windows 11.

---

## 1. USB Driver Setup (WinUSB)

The legacy Windows 98/2000/XP driver (`PF1800U.INF` / `PfsLoader.exe`) is a 32-bit driver that cannot load under 64-bit Windows kernel code signing. To use modern user-space USB (`libusb-1.0` / `pyusb` / `libpie1800u`), the scanner must be bound to Microsoft's in-box **WinUSB** driver (`USB\VID_05E3&PID_0120`).

### Method A: Automated Driver Installation with Zadig (Recommended)
1. Download **Zadig** from [https://zadig.akeo.ie/](https://zadig.akeo.ie/).
2. Plug in the PrimeFilm 1800u/1800i via USB and power it on.
3. Launch Zadig.
4. Select **Options -> List All Devices**.
5. In the dropdown, find and select **PrimeFilm 1800u** (or device with USB ID `05E3 0120`).
6. In the target driver box, choose **WinUSB (v6.1.7600.16385 or newer)**.
7. Click **Replace Driver** (or **Install Driver**).
8. Once finished, Windows Device Manager will list the device under *Universal Serial Bus devices* as *PrimeFilm 1800u*.

### Method B: Native INF Installation (`pnputil`)
Run an elevated Windows PowerShell or Command Prompt:
```cmd
pnputil /add-driver windows_driver\pie1800u_winusb.inf /install
```

---

## 2. Running PrimeFilm Studio UI

### Option A: Quick Zero-Dependency Web Studio (Runs out of the box!)
No extra Qt dependencies needed. Works with standard Python 3.9+:
1. Double-click `run_studio.bat` (or open Command Prompt and run `python scripts\primefilm_studio_app.py`).
2. If PySide6 is not installed, the app automatically boots the **Desktop Web Studio** on `http://127.0.0.1:8080` and pops open your default web browser (Edge/Chrome/Firefox).
3. The interface features live scanline streaming, 8-handle crop box, 60 FPS real-time negative color inversion, RGB histograms, and hardware carriage controls.

### Option B: Native Qt Studio Desktop Window (PySide6)
For a standalone native desktop window:
```cmd
pip install PySide6 pyusb libusb-package pillow
python scripts\primefilm_studio_app.py
```

---

## 3. Hardware Access Verification

To verify that Python can communicate with the scanner over WinUSB:
```cmd
python -c "import usb.core; dev = usb.core.find(idVendor=0x05e3, idProduct=0x0120); print('Found Scanner:', dev)"
```
If `Found Scanner: <DEVICE ...>` is printed, your USB permissions and driver are fully configured.
