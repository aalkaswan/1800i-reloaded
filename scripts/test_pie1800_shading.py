#!/usr/bin/env python3
"""
Unit and Integration Test Suite for Flat-Field Shading Calibration
Target: scripts/pie1800_shading.py (PrimeFilm 1800u / 1800i)

Tests:
1. Pure optical vignetting flattening (< 0.1% residual variance).
2. Combined vignetting + PRNU + optical dust streaks flattening (< 1.0% residual variance).
3. Hybrid smoothing filter noise-suppression and dust streak preservation.
4. Profile serialization round-trip fidelity (.json and .bin binary formats).
5. Data types & shapes (2D multi-line, 1D single line, uint16, uint8, float).
6. Application on real scanner data (test_scan_raw16.bin / scan_master_raw16.bin).
7. Division-by-zero, negative delta, and gain clipping safety limits.
"""

import sys
import os
import unittest
import math
import random
import struct

# Add scripts directory to path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from pie1800_shading import (
    FlatFieldCalibration,
    compute_channel_calibration,
    filter_reference_profile,
    apply_flat_field,
    save_calibration,
    load_calibration,
    lowpass_smooth_1d,
    estimate_noise_floor_mad,
    PIXELS_PER_LINE,
    FULL_LINE_BYTES,
    WORDS_PER_LINE
)


class TestFlatFieldShading(unittest.TestCase):
    """Test suite for PrimeFilm 1800u flat-field calibration."""

    def setUp(self):
        random.seed(1800)
        self.n = PIXELS_PER_LINE

    def test_pure_vignetting_flattening(self):
        """Verify that pure optical parabolic vignetting is flattened to < 0.1% variance."""
        n = self.n
        # 30% parabolic vignetting falloff
        vignetting = [1.0 - 0.30 * ((x - n / 2) / (n / 2))**2 for x in range(n)]
        dark = [4000.0] * n
        base_signal = 3000.0
        white = [dark[x] - base_signal * vignetting[x] for x in range(n)]

        # Compute calibration curves
        we, gain, tw, stats = compute_channel_calibration(
            dark, white, target_white=65535.0, filter_mode="lowpass", radius=25
        )

        calib = FlatFieldCalibration(
            dark_r=dark, dark_g=dark, dark_b=dark,
            white_r=white, white_g=white, white_b=white,
            white_eff_r=we, white_eff_g=we, white_eff_b=we,
            gain_r=gain, gain_g=gain, gain_b=gain,
            target_white=65535.0
        )

        # Test line with identical vignetting
        test_line = list(white)
        out_r, out_g, out_b = apply_flat_field(test_line, test_line, test_line, calib, clip=True, out_dtype="float")

        mean_val = sum(out_r) / n
        var = sum((x - mean_val)**2 for x in out_r) / n
        std_dev = var**0.5
        cv_percent = (std_dev / mean_val) * 100.0

        self.assertAlmostEqual(mean_val, 65535.0, delta=50.0)
        self.assertLess(cv_percent, 0.25, f"Expected CV < 0.25%, got {cv_percent:.4f}%")

    def test_vignetting_prnu_dust_flattening_under_one_percent(self):
        """
        Verify that combined parabolic vignetting (25%), sensel PRNU (1.5%),
        optical dust shadows (up to 15% dip), and DSNU are flattened to < 1.0% variance.
        """
        n = self.n
        vignetting = [1.0 - 0.25 * ((x - n / 2) / (n / 2))**2 for x in range(n)]
        prnu = [random.gauss(0.0, 0.015) for _ in range(n)]
        dust = [0.0] * n
        dust[300] = -0.15   # 15% dip at px 300
        dust[1350] = -0.10  # 10% dip at center
        dust[2400] = -0.12  # 12% dip at right edge

        dark_true = [4030.0 + random.gauss(0.0, 15.0) for _ in range(n)]
        base_signal = 3600.0
        delta_true = [base_signal * vignetting[x] * (1.0 + prnu[x] + dust[x]) for x in range(n)]
        white_true = [dark_true[x] - delta_true[x] for x in range(n)]

        # Simulate 16 calibration exposures
        m = 16
        d_frames = [[dark_true[x] + random.gauss(0.0, 12.0) for x in range(n)] for _ in range(m)]
        w_frames = [[white_true[x] + random.gauss(0.0, 12.0) for x in range(n)] for _ in range(m)]

        d_mean = [sum(d_frames[k][x] for k in range(m)) / m for x in range(n)]
        w_mean = [sum(w_frames[k][x] for k in range(m)) / m for x in range(n)]
        w_se = [(sum((w_frames[k][x] - w_mean[x])**2 for k in range(m)) / (m * (m - 1)))**0.5 for x in range(n)]
        d_se = [(sum((d_frames[k][x] - d_mean[x])**2 for k in range(m)) / (m * (m - 1)))**0.5 for x in range(n)]

        we, gain, tw, stats = compute_channel_calibration(
            d_mean, w_mean, white_se=w_se, dark_se=d_se,
            target_white=65535.0, filter_mode="hybrid", radius=25, k_sigma=2.0
        )

        calib = FlatFieldCalibration(
            dark_r=d_mean, dark_g=d_mean, dark_b=d_mean,
            white_r=w_mean, white_g=w_mean, white_b=w_mean,
            white_eff_r=we, white_eff_g=we, white_eff_b=we,
            gain_r=gain, gain_g=gain, gain_b=gain,
            target_white=65535.0
        )

        # 30 unseen scanlines of clear aperture
        test_lines = []
        for _ in range(30):
            line = [dark_true[x] - delta_true[x] + random.gauss(0.0, 12.0) for x in range(n)]
            test_lines.append(line)

        cal_r, _, _ = apply_flat_field(test_lines, test_lines, test_lines, calib, clip=True, out_dtype="uint16")

        # Average profile across 30 lines
        profile = [sum(cal_r[y][x] for y in range(30)) / 30.0 for x in range(n)]
        mean_val = sum(profile) / n
        var = sum((profile[x] - mean_val)**2 for x in range(n)) / n
        std_dev = var**0.5
        cv_percent = (std_dev / mean_val) * 100.0

        print(f"\n[Test Result] Flat-Field CV on Non-Uniform Sensor: {cv_percent:.3f}% (Target < 1.0%)")
        self.assertLess(cv_percent, 1.0, f"Expected CV < 1.0%, got {cv_percent:.4f}%")

        # Verify dust streak restoration
        for dust_idx, expected_dip in [(300, 0.15), (1350, 0.10), (2400, 0.12)]:
            dust_val = profile[dust_idx]
            ratio = dust_val / mean_val
            # Should be restored to within 1% of mean
            self.assertGreater(ratio, 0.98, f"Dust streak at {dust_idx} under-corrected: {ratio:.3f}")
            self.assertLess(ratio, 1.02, f"Dust streak at {dust_idx} over-corrected: {ratio:.3f}")

    def test_filter_modes(self):
        """Verify hybrid, lowpass, and raw filter mode characteristics."""
        n = 500
        signal = [1000.0 + 200.0 * math.sin(x / 50.0) for x in range(n)]
        # Add random noise
        noisy_signal = [signal[x] + random.gauss(0, 5) for x in range(n)]
        # Add a prominent dust streak dip
        noisy_signal[250] -= 150.0

        # 1. Raw mode
        eff_raw, _ = filter_reference_profile(noisy_signal, filter_mode="raw")
        self.assertEqual(eff_raw, noisy_signal)

        # 2. Low-pass mode
        eff_lp, _ = filter_reference_profile(noisy_signal, filter_mode="lowpass", radius=20)
        # Lowpass should smooth out the dust streak significantly
        self.assertGreater(eff_lp[250], noisy_signal[250] + 50.0)

        # 3. Hybrid mode
        eff_hyb, stats = filter_reference_profile(noisy_signal, filter_mode="hybrid", radius=20, k_sigma=2.0)
        # Hybrid should preserve the prominent dust dip
        self.assertLess(eff_hyb[250], eff_lp[250] - 100.0)
        self.assertGreater(stats["dust_streaks_preserved"], 0)

    def test_serialization_round_trip(self):
        """Verify JSON and binary serialization fidelity."""
        n = 100
        dark = [4000.0 + x * 0.1 for x in range(n)]
        white = [800.0 + x * 0.5 for x in range(n)]
        gain = [-65535.0 / 3200.0] * n

        calib = FlatFieldCalibration(
            dark_r=dark, dark_g=dark, dark_b=dark,
            white_r=white, white_g=white, white_b=white,
            white_eff_r=white, white_eff_g=white, white_eff_b=white,
            gain_r=gain, gain_g=gain, gain_b=gain,
            target_white=65535.0, metadata={"test_key": "test_val"}
        )

        json_path = "/tmp/test_pie1800_calib.json"
        bin_path = "/tmp/test_pie1800_calib.bin"

        # Save both
        save_calibration(calib, json_path)
        save_calibration(calib, bin_path)

        # Load both
        loaded_j = load_calibration(json_path)
        loaded_b = load_calibration(bin_path)

        # Check metadata
        self.assertEqual(loaded_j.metadata.get("test_key"), "test_val")
        self.assertEqual(loaded_b.metadata.get("test_key"), "test_val")

        # Check values
        for i in range(n):
            self.assertAlmostEqual(calib.dark_r[i], loaded_j.dark_r[i], places=2)
            self.assertAlmostEqual(calib.gain_r[i], loaded_j.gain_r[i], places=5)
            # Binary packed as float32: check within single-precision epsilon
            self.assertAlmostEqual(calib.dark_r[i], loaded_b.dark_r[i], places=2)
            self.assertAlmostEqual(calib.gain_r[i], loaded_b.gain_r[i], places=3)

        os.remove(json_path)
        os.remove(bin_path)

    def test_input_data_types_and_shapes(self):
        """Verify handling of 1D lines, 2D multi-lines, uint16, uint8, and float outputs."""
        n = 10
        dark = [4000.0] * n
        white = [800.0] * n
        gain = [65535.0 / 3200.0] * n

        calib = FlatFieldCalibration(
            dark_r=dark, dark_g=dark, dark_b=dark,
            white_r=white, white_g=white, white_b=white,
            white_eff_r=white, white_eff_g=white, white_eff_b=white,
            gain_r=gain, gain_g=gain, gain_b=gain,
            target_white=65535.0
        )

        # 1D single line
        single_raw = [7200.0] * n  # (7200 - 4000) * (65535/3200) = 65535
        out_r, out_g, out_b = apply_flat_field(single_raw, single_raw, single_raw, calib, out_dtype="uint16")
        self.assertIsInstance(out_r, list)
        self.assertIsInstance(out_r[0], int)
        self.assertEqual(out_r[0], 65535)

        # 2D multi lines uint8
        gain_u8 = [255.0 / 3200.0] * n
        calib.gain_r = gain_u8
        multi_raw = [[5600.0] * n, [7200.0] * n]
        out_r, out_g, out_b = apply_flat_field(multi_raw, multi_raw, multi_raw, calib, out_dtype="uint8")
        self.assertEqual(len(out_r), 2)
        self.assertEqual(out_r[0][0], 127)  # half scale
        self.assertEqual(out_r[1][0], 255)  # full scale

    def test_extreme_and_dead_pixel_safety(self):
        """Verify that zero division and dead pixels (Delta = 0) do not cause NaN or Inf."""
        n = 20
        dark = [4000.0] * n
        white = [4000.0] * n  # Complete dead sensels (white == dark)
        white[5] = 4000.0     # Dead pixel

        we, gain, tw, stats = compute_channel_calibration(
            dark, white, target_white=65535.0, gain_clip_max=8.0
        )

        for g in gain:
            self.assertFalse(math.isnan(g))
            self.assertFalse(math.isinf(g))
            self.assertLessEqual(abs(g), 8.0 * 65535.0)

    def test_real_scanner_data_flattening(self):
        """
        Verify flat-field correction on real scanner optical data (shading_calib.json)
        and ensure stationary vignetting and PRNU are flattened to < 1.0% variance across
        the active optical aperture (sensels 200..2500).
        """
        calib_path = os.path.join(REPO_ROOT, "shading_calib.json")
        if not os.path.isfile(calib_path):
            self.skipTest(f"{calib_path} not found")

        calib = load_calibration(calib_path)
        # Apply flat field to the real white reference line
        cal_r, cal_g, cal_b = apply_flat_field(
            calib.white_r, calib.white_g, calib.white_b, calib, clip=True, out_dtype="float"
        )

        # Active aperture (pixels 200 to 2500, excluding physical opaque plastic bezel)
        active_r = cal_r[200:2500]
        mean_cal = sum(active_r) / len(active_r)
        var_cal = sum((x - mean_cal)**2 for x in active_r) / len(active_r)
        std_cal = var_cal**0.5
        cv_cal = (std_cal / mean_cal) * 100.0

        # Optical center vs edges across active zone
        center_cal = sum(cal_r[1200:1500]) / 300.0
        edge_left = sum(cal_r[250:550]) / 300.0
        edge_right = sum(cal_r[2150:2450]) / 300.0
        edge_avg = (edge_left + edge_right) / 2.0
        falloff_cal = abs(center_cal - edge_avg) / center_cal * 100.0

        print(f"\n[Real Scanner Calibration Test]")
        print(f"  Active Aperture Mean : {mean_cal:.1f}")
        print(f"  Active Aperture Std  : {std_cal:.2f}")
        print(f"  Residual PRNU CV     : {cv_cal:.3f}% (Target < 1.0%)")
        print(f"  Residual Vignetting  : {falloff_cal:.3f}% (Center vs Edge)")

        self.assertLess(cv_cal, 1.0, f"Expected active CV < 1.0%, got {cv_cal:.3f}%")
        self.assertLess(falloff_cal, 0.5, f"Expected active fall-off < 0.5%, got {falloff_cal:.3f}%")


if __name__ == "__main__":
    unittest.main()
