#!/usr/bin/env python3
"""
Unit tests for PrimeFilm 1800u / 1800i Super-Resolution Engine.
Tests Sub-Pixel Registration, Iterative Back-Projection (IBP-TV),
Variable-Pixel Linear Reconstruction (Drizzle), and Acutance Metrics.

(scripts/test_pie1800_superres.py)
"""

import os
import sys
import unittest
import subprocess
import math
from pathlib import Path

try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

from pie1800_superres import (
    ensure_binary,
    compute_metrics,
    simulate_jittered_passes,
    save_tiff_rgb16,
    BIN_SUPERRES,
    SRC_SUPERRES,
    REPO_ROOT,
)


class TestSuperResolutionEngine(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        ensure_binary()

    def test_accelerator_binary_exists(self):
        """Verify that the OpenMP C superres accelerator binary compiles and exists."""
        self.assertTrue(os.path.isfile(BIN_SUPERRES), f"Expected binary at {BIN_SUPERRES}")
        self.assertTrue(os.access(BIN_SUPERRES, os.X_OK), "Binary must be executable")

    def test_metrics_calculation(self):
        """Verify that Laplacian variance and Sobel gradient metrics compute reliably."""
        if not HAS_PILLOW:
            self.skipTest("Pillow not installed")

        # Flat image should have zero gradient and zero laplacian
        flat = Image.new("RGB", (100, 100), (128, 128, 128))
        var_lap, mean_sobel = compute_metrics(flat, max_dim=100)
        self.assertAlmostEqual(var_lap, 0.0, places=4)
        self.assertAlmostEqual(mean_sobel, 0.0, places=4)

        # High contrast checkerboard should have positive acutance
        checker = Image.new("L", (100, 100))
        for y in range(100):
            for x in range(100):
                if (x // 10 + y // 10) % 2 == 0:
                    checker.putpixel((x, y), 255)
        checker_rgb = checker.convert("RGB")
        var_lap_c, mean_sobel_c = compute_metrics(checker_rgb, max_dim=100)
        self.assertGreater(var_lap_c, 10.0)
        self.assertGreater(mean_sobel_c, 5.0)

    def test_tiff_16bit_export(self):
        """Verify that 16-bit linear uncompressed TIFF exporter generates valid TIFF files."""
        out_tif = "/tmp/test_sr_16bit.tif"
        w, h = 64, 64
        total = w * h
        r = [float(i % 256) for i in range(total)]
        g = [float((i * 2) % 256) for i in range(total)]
        b = [float((i * 3) % 256) for i in range(total)]

        save_tiff_rgb16(out_tif, w, h, r, g, b)
        self.assertTrue(os.path.isfile(out_tif))

        if HAS_PILLOW:
            with Image.open(out_tif) as im:
                self.assertEqual(im.size, (w, h))
                self.assertIn(im.mode, ("RGB", "I;16"))
        if os.path.exists(out_tif):
            os.remove(out_tif)

    def test_superres_acutance_gain(self):
        """
        Verify that 4-pass sub-pixel jittered IBP reconstruction achieves
        statistically significant acutance gain over baseline interpolation.
        """
        if not HAS_PILLOW:
            self.skipTest("Pillow not installed")

        sample_photo = os.path.join(REPO_ROOT, "photo_950lines_lanczos.ppm")
        crop_path = "/tmp/test_crop_sr.ppm"
        if os.path.isfile(sample_photo):
            im = Image.open(sample_photo).crop((500, 500, 750, 750))
            im.save(crop_path)
        else:
            # Multi-frequency pseudo-random texture
            w, h = 250, 250
            im = Image.new("RGB", (w, h))
            pix = im.load()
            for y in range(h):
                for x in range(w):
                    v = int(128 + 60 * math.sin(x * 0.15 + y * 0.1) + 40 * math.cos(x * 0.45 - y * 0.35))
                    pix[x, y] = (v, v, v)
            im.save(crop_path)

        # Simulate 4 sub-pixel jittered passes
        pass_paths = simulate_jittered_passes(crop_path, num_passes=4, output_dir="/tmp")
        self.assertEqual(len(pass_paths), 4)

        # Run IBP superres
        out_ibp = "/tmp/test_crop_ibp.ppm"
        cmd = [
            BIN_SUPERRES,
            out_ibp,
            "ibp",
            *pass_paths,
        ]
        env = os.environ.copy()
        env["PIE_SCALE"] = "2"
        env["PIE_ITERS"] = "6"
        env["PIE_SIGMA"] = "1.0"
        env["PIE_TV"] = "0.02"

        res = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(res.returncode, 0, f"C engine failed: {res.stderr}")
        self.assertTrue(os.path.isfile(out_ibp))

        # Baseline Lanczos 2x
        im_baseline = im.resize((im.size[0] * 2, im.size[1] * 2), Image.Resampling.LANCZOS)
        with Image.open(out_ibp) as im_ibp:
            var_base, sobel_base = compute_metrics(im_baseline)
            var_ibp, sobel_ibp = compute_metrics(im_ibp)

        print(f"\n[Test Result] Baseline Lanczos Acutance: {var_base:.2f}, IBP Acutance: {var_ibp:.2f}")
        print(f"[Test Result] Baseline Sobel Gradient: {sobel_base:.2f}, IBP Gradient: {sobel_ibp:.2f}")

        # Verify acutance improvement
        self.assertGreater(var_ibp, var_base, "IBP must improve Laplacian MTF acutance")
        self.assertGreater(sobel_ibp, sobel_base, "IBP must improve Sobel edge gradient")

        # Cleanup
        if os.path.exists(crop_path):
            os.remove(crop_path)
        for p in pass_paths:
            if os.path.exists(p):
                os.remove(p)
        if os.path.exists(out_ibp):
            os.remove(out_ibp)

    def test_drizzle_reconstruction(self):
        """Verify that Drizzle variable-pixel reconstruction runs cleanly."""
        if not HAS_PILLOW:
            self.skipTest("Pillow not installed")

        sample_photo = os.path.join(REPO_ROOT, "photo_950lines_lanczos.ppm")
        crop_path = "/tmp/test_crop_drizzle.ppm"
        if os.path.isfile(sample_photo):
            im = Image.open(sample_photo).crop((400, 400, 600, 600))
            im.save(crop_path)
        else:
            im = Image.new("RGB", (200, 200), (100, 150, 200))
            im.save(crop_path)

        pass_paths = simulate_jittered_passes(crop_path, num_passes=4, output_dir="/tmp")
        out_drizzle = "/tmp/test_pattern_drizzle_out.ppm"
        cmd = [
            BIN_SUPERRES,
            out_drizzle,
            "drizzle",
            *pass_paths,
        ]
        env = os.environ.copy()
        env["PIE_SCALE"] = "2"
        env["PIE_PIXFRAC"] = "0.7"

        res = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(res.returncode, 0, f"Drizzle failed: {res.stderr}")
        self.assertTrue(os.path.isfile(out_drizzle))

        with Image.open(out_drizzle) as im_drizzle:
            self.assertEqual(im_drizzle.size, (im.size[0] * 2, im.size[1] * 2))

        # Cleanup
        if os.path.exists(crop_path):
            os.remove(crop_path)
        for p in pass_paths:
            if os.path.exists(p):
                os.remove(p)
        if os.path.exists(out_drizzle):
            os.remove(out_drizzle)


if __name__ == "__main__":
    unittest.main()
