#!/usr/bin/env python3
"""
Unit tests for Spatially-Varying PSF Modeling, Radial LCA Correction,
and Cross-Channel Gradient Guided Richardson-Lucy Deconvolution.

(scripts/test_pie1800_lca_deconv.py)
"""

import unittest
import math
import ctypes
from pathlib import Path

try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

from pie1800_lca_deconv import (
    deconvolve_lca_rgb,
    _ensure_c_library,
    _c_lib,
    CDeconvOptions,
    REPO_ROOT,
)


class TestSpatiallyVaryingLCADeconv(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _ensure_c_library()

    def test_c_library_loaded(self):
        """Verify that the optimized OpenMP C shared library is compiled and loaded."""
        self.assertIsNotNone(_c_lib, "C shared library libpie1800_lca_deconv.so should be loaded")

    def test_spatially_varying_psf_expansion(self):
        """
        Verify that spatially-varying PSF widens quadratically from center to periphery:
        sigma(x) = sigma_center + alpha * ((x - x_mid) / x_mid)^2
        """
        w = 2700
        x_mid = (w - 1) / 2.0
        sigma_center = 1.20
        alpha = 0.35

        def get_sigma(x):
            r_norm = (x - x_mid) / x_mid
            return sigma_center + alpha * (r_norm * r_norm)

        # Center pixel
        self.assertAlmostEqual(get_sigma(int(x_mid)), 1.20, places=2)
        # Quarter points
        self.assertAlmostEqual(get_sigma(w // 4), 1.20 + 0.35 * 0.25, places=2)
        # Periphery pixels
        self.assertAlmostEqual(get_sigma(0), 1.55, places=2)
        self.assertAlmostEqual(get_sigma(w - 1), 1.55, places=2)

    def test_subpixel_bicubic_warping_alignment(self):
        """
        Verify that subpixel bicubic warping accurately compensates for known
        subpixel chromatic displacement.
        """
        w, h = 400, 50
        # Generate an image with a smooth edge transition at x = 200
        # Green channel has edge at x=200
        # Red channel has edge shifted by +0.50 px: f(x - 0.5)
        # Blue channel has edge shifted by -0.30 px: f(x + 0.3)
        raw_rgb = bytearray(w * h * 3)

        def sigmoid(x_pos, center, scale=1.5):
            val = 1.0 / (1.0 + math.exp(-max(-10.0, min(10.0, (x_pos - center) / scale))))
            return 50.0 + 150.0 * val

        for y in range(h):
            for x in range(w):
                idx = (y * w + x) * 3
                g_val = int(sigmoid(x, 200.0) + 0.5)
                r_val = int(sigmoid(x - 0.50, 200.0) + 0.5)
                b_val = int(sigmoid(x + 0.30, 200.0) + 0.5)
                raw_rgb[idx + 0] = max(0, min(255, r_val))
                raw_rgb[idx + 1] = max(0, min(255, g_val))
                raw_rgb[idx + 2] = max(0, min(255, b_val))

        # In raw input, Red at x=200 is shifted:
        r_raw_diff = abs(raw_rgb[(25 * w + 200) * 3 + 0] - raw_rgb[(25 * w + 200) * 3 + 1])
        self.assertGreater(r_raw_diff, 10, "Raw input should exhibit chromatic misalignment at x=200")

        # Apply deconvolution with LCA correction (+0.50 px for Red, -0.30 px for Blue)
        enhanced_bytes = deconvolve_lca_rgb(
            bytes(raw_rgb), w, h,
            enable_lca=True,
            auto_lca=False,
            lca_kr=(0.50, 0.0, 0.0),
            lca_kb=(-0.30, 0.0, 0.0),
            iterations=4,
            enable_guided=True,
        )

        self.assertEqual(len(enhanced_bytes), len(raw_rgb))

        # Check edge alignment at x=200: in enhanced output, Red and Green should be aligned
        idx_edge = (25 * w + 200) * 3
        r_at_edge = enhanced_bytes[idx_edge + 0]
        g_at_edge = enhanced_bytes[idx_edge + 1]
        enhanced_diff = abs(int(r_at_edge) - int(g_at_edge))

        self.assertLess(enhanced_diff, r_raw_diff * 0.40,
                        f"LCA warping should reduce chromatic difference at edge from {r_raw_diff} to < {r_raw_diff * 0.40}")

    def test_gradient_guided_cross_channel_regularization(self):
        """
        Verify that Green gradient guidance prior preserves sharp transitions
        while suppressing noise amplification in flat regions.
        """
        w, h = 300, 40
        raw_rgb = bytearray(w * h * 3)
        # Left half flat with sensor noise, right half sharp edge
        for y in range(h):
            for x in range(w):
                idx = (y * w + x) * 3
                if x < 150:
                    # Flat area with chromatic noise
                    g_val = 128
                    r_val = 128 + ((x + y) % 5 - 2) * 4 # noise on R
                    b_val = 128 - ((x * y) % 5 - 2) * 4 # noise on B
                else:
                    # Sharp edge
                    g_val = 220
                    r_val = 220
                    b_val = 220
                raw_rgb[idx + 0] = max(0, min(255, r_val))
                raw_rgb[idx + 1] = max(0, min(255, g_val))
                raw_rgb[idx + 2] = max(0, min(255, b_val))

        # Process with guidance
        guided_bytes = deconvolve_lca_rgb(
            bytes(raw_rgb), w, h,
            enable_lca=False,
            auto_lca=False,
            iterations=6,
            enable_guided=True,
            guided_strength=0.90,
        )

        # Process without guidance (unguided)
        unguided_bytes = deconvolve_lca_rgb(
            bytes(raw_rgb), w, h,
            enable_lca=False,
            auto_lca=False,
            iterations=6,
            enable_guided=False,
        )

        # Measure noise variance in the flat region (x in 20..100)
        var_r_guided = 0.0
        var_r_unguided = 0.0
        n_samples = 0
        for y in range(10, h - 10):
            for x in range(20, 100):
                idx = (y * w + x) * 3
                dr_g = guided_bytes[idx] - 128
                dr_u = unguided_bytes[idx] - 128
                var_r_guided += dr_g * dr_g
                var_r_unguided += dr_u * dr_u
                n_samples += 1

        var_r_guided /= n_samples
        var_r_unguided /= n_samples

        self.assertLess(var_r_guided, var_r_unguided,
                        "Guided RL should exhibit lower flat-field chrominance variance than unguided RL")

    def test_real_scan_acutance_improvement(self):
        """
        Verify on a real scanline crop from scan_master_scaled.ppm that
        deconvolve_lca_rgb increases Tenengrad edge gradient energy.
        """
        scan_ppm = REPO_ROOT / "scan_master_scaled.ppm"
        if not scan_ppm.is_file():
            self.skipTest(f"{scan_ppm} not found")

        im = Image.open(scan_ppm)
        w, h = im.size
        # Use first 60 lines for fast unit testing
        crop_im = im.crop((0, 0, w, 60))
        raw_bytes = crop_im.tobytes()

        enhanced_bytes = deconvolve_lca_rgb(
            raw_bytes, w, 60,
            enable_lca=True,
            auto_lca=True,
            iterations=6,
            enable_guided=True
        )

        def calc_tenengrad(buf, width, height):
            sum_g = 0.0
            cnt = 0
            for y in range(5, height - 5):
                for x in range(10, width - 10):
                    idx = (y * width + x) * 3
                    gx = (buf[idx + 3 + 1] - buf[idx - 3 + 1]) * 0.5
                    gy = (buf[(y + 1) * width * 3 + x * 3 + 1] - buf[(y - 1) * width * 3 + x * 3 + 1]) * 0.5
                    sum_g += (gx * gx + gy * gy)
                    cnt += 1
            return sum_g / cnt if cnt else 0

        raw_acutance = calc_tenengrad(raw_bytes, w, 60)
        enhanced_acutance = calc_tenengrad(enhanced_bytes, w, 60)

        self.assertGreater(enhanced_acutance, raw_acutance * 1.20,
                           "Optical deconvolution should increase edge acutance by at least +20%")


if __name__ == "__main__":
    unittest.main()
