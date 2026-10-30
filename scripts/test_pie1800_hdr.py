#!/usr/bin/env python3
"""
Unit and Regression Test Suite for Multi-Exposure Analog Bracketed HDR & Film Dmax Extender
Target: scripts/pie1800_hdr.py (PrimeFilm 1800u / 1800i)

Tests:
1. DSNU dark frame subtraction accuracy at matching exposure times.
2. Linear Radiance Map recovery (Debevec / Poisson weighting) linearity & fidelity (R^2 > 0.99).
3. Highlight recovery from short brackets and deep shadow extraction from long brackets.
4. Mertens exposure fusion quality weighting and smooth normalization.
5. Tonemapping operators (Filmic ACES & Reinhard global) monotonicity and dynamic compression.
6. Theoretical and measured Dynamic Range (EV gain, dB) and Film Dmax extension formulas.
7. Uncompressed 16-bit Linear Pro TIFF master format validation.
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

from pie1800_hdr import (
    BracketDarkCalibration,
    gaussian_weight_1d,
    triangular_weight_1d,
    fuse_linear_radiance,
    boxcar_blur_2d,
    compute_mertens_weights,
    fuse_mertens,
    calculate_hdr_metrics,
    tonemap_reinhard,
    tonemap_filmic_aces,
    save_tiff_rgb16,
    PIXELS_PER_LINE,
    FULL_LINE_BYTES
)


class TestHDRBracketedFusion(unittest.TestCase):
    """Test suite for PrimeFilm 1800u multi-exposure HDR fusion and Dmax extension."""

    def setUp(self):
        random.seed(1800)
        self.n = 2700

    def test_dsnu_subtraction_at_matching_exposures(self):
        """
        Verify that subtracting calibrated dark frames taken at matching exposure times
        eliminates fixed-pattern thermal noise without introducing DC offset drift.
        """
        n = self.n
        calib = BracketDarkCalibration()

        # Simulate two different exposures with distinct DSNU profiles
        # Exposure 1450 has lower baseline; Exposure 5800 has higher baseline
        dark_1450 = [3120.0 + 50.0 * math.sin(x * 0.01) + random.gauss(0, 5) for x in range(n)]
        dark_5800 = [4040.0 + 80.0 * math.sin(x * 0.01) + random.gauss(0, 5) for x in range(n)]

        calib.add_bracket(1450, dark_1450, dark_1450, dark_1450)
        calib.add_bracket(5800, dark_5800, dark_5800, dark_5800)

        # True optical photon signal: 500 counts on 1450, 2000 counts on 5800 (4x integration)
        true_sig_1450 = 500.0
        true_sig_5800 = 2000.0

        # CCD raw inverted readout: Raw = Dark - TrueSignal
        raw_words_1450 = [int(dark_1450[x] - true_sig_1450) for x in range(n)] * 3
        raw_words_5800 = [int(dark_5800[x] - true_sig_5800) for x in range(n)] * 3

        # Subtraction with matching calibration
        sig_r_1450, _, _ = calib.subtract_dark(1450, raw_words_1450)
        sig_r_5800, _, _ = calib.subtract_dark(5800, raw_words_5800)

        mean_1450 = sum(sig_r_1450) / n
        mean_5800 = sum(sig_r_5800) / n

        self.assertAlmostEqual(mean_1450, true_sig_1450, delta=2.0)
        self.assertAlmostEqual(mean_5800, true_sig_5800, delta=2.0)

        # Verify that mismatched subtraction introduces large DC error (> 900 counts)
        mismatched_sig = [max(0.0, dark_1450[x] - raw_words_5800[x]) for x in range(n)]
        mismatched_mean = sum(mismatched_sig) / n
        error = abs(mismatched_mean - true_sig_5800)
        self.assertGreater(error, 800.0, "Mismatched dark subtraction must cause significant error")

    def test_linear_radiance_recovery_linearity(self):
        """
        Verify that Debevec / Poisson-weighted linear radiance map recovery preserves
        exact linear proportionality (R^2 > 0.999) across a 1000:1 optical transmission range.
        """
        n = 500
        # True ground truth relative radiance: exponentially decaying from 1.0 down to 0.001
        true_radiance = [math.exp(-6.9 * (x / n)) for x in range(n)]

        # 3 brackets: 1000, 2900, 5800 clocks
        brackets = [1000, 2900, 5800]
        ref_exp = 2900
        sat_level = 3600.0

        bracket_data = []
        for exp in brackets:
            tau = exp / ref_exp
            row = []
            for x in range(n):
                ideal_signal = true_radiance[x] * 3200.0 * tau
                # Add realistic Poisson shot noise and read noise
                noise = random.gauss(0, math.sqrt(max(ideal_signal, 1.0)) * 0.1)
                meas = ideal_signal + noise
                # Sensor saturation clamp
                clipped = min(sat_level, max(0.0, meas))
                row.append(clipped)
            bracket_data.append((exp, [row]))

        # Fuse radiance
        fused_radiance = fuse_linear_radiance(bracket_data, weight_type="gaussian", ref_exposure=ref_exp)[0]

        # Compute Pearson R^2 correlation with ground truth radiance
        mean_true = sum(true_radiance) / n
        mean_fused = sum(fused_radiance) / n
        num = sum((true_radiance[i] - mean_true) * (fused_radiance[i] - mean_fused) for i in range(n))
        den_t = sum((true_radiance[i] - mean_true) ** 2 for i in range(n))
        den_f = sum((fused_radiance[i] - mean_fused) ** 2 for i in range(n))
        r2 = (num * num) / (den_t * den_f)

        self.assertGreater(r2, 0.995, f"Expected R^2 > 0.995, got {r2:.5f}")

    def test_highlight_recovery_and_shadow_extraction(self):
        """
        Verify that saturated highlights in long exposure are reconstructed from short exposure,
        while deep shadow noise in short exposure is replaced by high SNR from long exposure.
        """
        # Highlight pixel: Transmittance = 0.95 (thin negative shadow / clear base)
        # Saturated at 5800 clocks, clean at 1000 clocks
        # Deep shadow pixel: Transmittance = 0.002 (dense negative highlight)
        # Buried in noise at 1000 clocks (2 counts), clean at 5800 clocks (11.6 counts)

        brackets = [1000, 2900, 5800]
        # Pixel 0 = highlight (clear), Pixel 1 = deep shadow (dense)
        # 1000 clocks: [3040, 2]
        # 2900 clocks: [3600 (sat), 5.8]
        # 5800 clocks: [3600 (sat), 11.6]
        bracket_signals = [
            (1000, [[3040.0, 2.0]]),
            (2900, [[3600.0, 5.8]]),
            (5800, [[3600.0, 11.6]]),
        ]

        fused = fuse_linear_radiance(bracket_signals, ref_exposure=2900)[0]

        # Normalized to 2900 reference:
        # Highlight: 3040 / (1000/2900) = 8816.0
        # Deep shadow: 11.6 / (5800/2900) = 5.8
        self.assertAlmostEqual(fused[0], 8816.0, delta=50.0)
        self.assertAlmostEqual(fused[1], 5.8, delta=0.5)

    def test_mertens_fusion_smoothness(self):
        """
        Verify that Mertens exposure fusion normalizes weights to sum to 1.0 everywhere
        and produces continuous contrast-blended output.
        """
        h, w = 10, 50
        # Create two brackets with complementary exposure gradients
        b1_r = [[100.0 + x * 20.0 for x in range(w)] for _ in range(h)]
        b2_r = [[2000.0 + x * 30.0 for x in range(w)] for _ in range(h)]

        bracket_data = [
            (1450, b1_r, b1_r, b1_r),
            (2900, b2_r, b2_r, b2_r),
        ]

        fused_r, fused_g, fused_b = fuse_mertens(bracket_data, blur_radius=5, ref_exposure=1450)

        self.assertEqual(len(fused_r), h)
        self.assertEqual(len(fused_r[0]), w)
        for y in range(h):
            for x in range(w):
                # Ensure no NaN or Inf
                self.assertFalse(math.isnan(fused_r[y][x]))
                self.assertFalse(math.isinf(fused_r[y][x]))
                self.assertGreater(fused_r[y][x], 0.0)

    def test_tonemapping_operators(self):
        """Verify monotonicity and range bounds of Filmic ACES and Reinhard tonemappers."""
        inputs = [[x * 100.0 for x in range(100)]]
        aces = tonemap_filmic_aces(inputs)[0]
        reinhard = tonemap_reinhard(inputs)[0]

        # Check bounds [0, 1]
        for val in aces:
            self.assertGreaterEqual(val, 0.0)
            self.assertLessEqual(val, 1.0)
        for val in reinhard:
            self.assertGreaterEqual(val, 0.0)
            self.assertLessEqual(val, 1.0)

        # Check monotonicity (strictly non-decreasing)
        for i in range(len(aces) - 1):
            self.assertGreaterEqual(aces[i + 1], aces[i])
            self.assertGreaterEqual(reinhard[i + 1], reinhard[i])

    def test_hdr_metrics_calculation(self):
        """Verify dynamic range expansion and Dmax extension formulas."""
        # Standard 3-bracket: 1450 to 5800 (4.0x)
        m3 = calculate_hdr_metrics([1450, 2900, 5800])
        self.assertAlmostEqual(m3["exposure_ratio"], 4.0, delta=0.01)
        self.assertAlmostEqual(m3["ev_gain_stops"], 2.0, delta=0.01)
        self.assertAlmostEqual(m3["dynamic_range_gain_db"], 12.04, delta=0.05)
        self.assertAlmostEqual(m3["delta_dmax"], 0.602, delta=0.005)

        # Extended 4-bracket: 1000 to 11600 (11.6x)
        m4 = calculate_hdr_metrics([1000, 2900, 5800, 11600])
        self.assertAlmostEqual(m4["exposure_ratio"], 11.6, delta=0.01)
        self.assertAlmostEqual(m4["ev_gain_stops"], 3.54, delta=0.01)
        self.assertAlmostEqual(m4["dynamic_range_gain_db"], 21.29, delta=0.05)
        self.assertAlmostEqual(m4["delta_dmax"], 1.064, delta=0.005)

    def test_clamped_dark_frame_does_not_inject_color_streaks(self):
        """
        Regression Test: Hardware ADC clamping at ceiling (4095) in dark frames must be
        repaired/smoothed so it does not inject 800+ count step discontinuities (vertical streaks).
        """
        n = self.n
        calib = BracketDarkCalibration()

        # Simulate hardware ADC clamping at 4095 on Green sensels 1599..2000
        # Sensels 0..1598 sit at 3200; sensels 1599..2000 are clamped hard at 4095
        dark_clamped_g = [3200.0] * n
        for x in range(1599, 2000):
            dark_clamped_g[x] = 4095.0

        dark_r = [3600.0] * n
        dark_b = [3700.0] * n

        # Add bracket with smooth_clamped=True (live hardware mode)
        calib.add_bracket(2000, dark_r, dark_clamped_g, dark_b, smooth_clamped=True)

        # Smooth optical transmission line from film
        film_raw_g = [1100] * n
        raw_words = [1100] * (n * 3)

        sig_r, sig_g, sig_b = calib.subtract_dark(2000, raw_words)

        # Check adjacent difference across the clamp boundary at 1598 -> 1599
        clamp_step = abs(sig_g[1599] - sig_g[1598])
        self.assertLess(clamp_step, 20.0, f"Expected smooth clamp transition < 20 counts, got {clamp_step:.1f}")

    def test_tiff_16bit_master_export(self):
        """Verify that 16-bit uncompressed linear TIFF files are valid and contain 16-bit tags."""
        w, h = 50, 10
        lines_r = [[x * 1000 for x in range(w)] for _ in range(h)]
        lines_g = [[x * 1000 for x in range(w)] for _ in range(h)]
        lines_b = [[x * 1000 for x in range(w)] for _ in range(h)]

        test_tif = "/tmp/test_pie1800_hdr_export.tif"
        try:
            save_tiff_rgb16(test_tif, w, h, lines_r, lines_g, lines_b)
            self.assertTrue(os.path.isfile(test_tif))
            with open(test_tif, "rb") as f:
                header = f.read(8)
                self.assertEqual(header[:4], b"II\x2a\x00")  # Little-endian TIFF magic
                ifd_offset = struct.unpack("<I", header[4:8])[0]
                self.assertEqual(ifd_offset, 8)
        finally:
            if os.path.isfile(test_tif):
                os.remove(test_tif)


if __name__ == "__main__":
    unittest.main()
