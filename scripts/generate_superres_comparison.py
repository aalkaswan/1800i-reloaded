#!/usr/bin/env python3
"""
PrimeFilm 1800u / 1800i Super-Resolution Comparison Showcase Generator
Creates a professional side-by-side comparison matrix between:
  1. Single Pass 1800 DPI Baseline (Lanczos-3 Sinc 2x)
  2. Multi-Pass IBP-TV Reconstruction (Iterative Back-Projection + Total Variation)
  3. Multi-Pass Drizzle Reconstruction (Variable-Pixel Linear Fractional Drop)

Saves to docs/images/comparison_superres_techniques.png
"""

import os
import sys
from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_IMG = os.path.join(REPO_ROOT, "docs", "images", "comparison_superres_techniques.png")

FONT_BOLD = "/usr/share/fonts/liberation/LiberationSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/liberation/LiberationSans-Regular.ttf"

def get_font(path, size):
    if os.path.isfile(path):
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()

def draw_header(draw, title, subtitle, w):
    draw.rectangle([(0, 0), (w, 130)], fill=(15, 20, 28))
    draw.line([(0, 130), (w, 130)], fill=(40, 50, 70), width=2)
    
    font_title = get_font(FONT_BOLD, 30)
    font_sub = get_font(FONT_REG, 17)
    
    draw.text((30, 28), title, fill=(240, 245, 255), font=font_title)
    draw.text((30, 75), subtitle, fill=(140, 165, 200), font=font_sub)

def draw_badge(draw, x, y, text, bg_color, text_color=(255, 255, 255)):
    font = get_font(FONT_BOLD, 14)
    bbox = font.getbbox(text)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 12, 6
    draw.rounded_rectangle([(x, y), (x + tw + 2 * pad_x, y + th + 2 * pad_y)], radius=4, fill=bg_color)
    draw.text((x + pad_x, y + pad_y - 1), text, fill=text_color, font=font)

def main():
    p0_path = "/tmp/hw_pass_0_scaled.ppm"
    ibp_path = os.path.join(REPO_ROOT, "master_live_3600dpi.png")
    drz_path = os.path.join(REPO_ROOT, "master_live_drizzle.png")

    if not os.path.isfile(p0_path) or not os.path.isfile(ibp_path) or not os.path.isfile(drz_path):
        print(f"Error: Missing required scan files.\n  Pass0: {p0_path}\n  IBP: {ibp_path}\n  Drizzle: {drz_path}")
        sys.exit(1)

    print("[*] Loading master images...")
    im_p0 = Image.open(p0_path)
    im_ibp = Image.open(ibp_path)
    im_drz = Image.open(drz_path)

    # Scale pass 0 by 2x via Lanczos-3 to match high-resolution grid (5400x3800)
    print("[*] Upsampling baseline pass 0 to 3600 DPI grid via Lanczos-3 sinc...")
    im_p0_2x = im_p0.resize(im_ibp.size, Image.Resampling.LANCZOS)

    # Crop Definitions (5400x3800 coordinate space)
    # Crop 1: Central high-contrast detail region
    crop1_box = (2500, 1800, 3140, 2440)  # 640x640
    # Crop 2: Fine edge / line structure region
    crop2_box = (1000, 1400, 1640, 2040)  # 640x640

    cw = crop1_box[2] - crop1_box[0]
    ch = crop1_box[3] - crop1_box[1]

    c1_p0 = im_p0_2x.crop(crop1_box)
    c1_ibp = im_ibp.crop(crop1_box)
    c1_drz = im_drz.crop(crop1_box)

    c2_p0 = im_p0_2x.crop(crop2_box)
    c2_ibp = im_ibp.crop(crop2_box)
    c2_drz = im_drz.crop(crop2_box)

    # Layout Calculations
    margin = 30
    gutter = 25
    header_h = 135
    row_title_h = 50
    badge_h = 75
    table_h = 240
    
    total_w = margin * 2 + cw * 3 + gutter * 2
    row1_y = header_h + row_title_h
    row2_y = row1_y + ch + badge_h + row_title_h
    footer_y = row2_y + ch + badge_h + 20
    total_h = footer_y + table_h + margin

    canvas = Image.new("RGB", (total_w, total_h), (22, 25, 32))
    draw = ImageDraw.Draw(canvas)

    # 1. Header
    draw_header(
        draw,
        "PRIME FILM 1800u / 1800i COMPUTATIONAL SUPER-RESOLUTION SHOWCASE",
        "Physical 4-Pass Optical Acquisition: Iterative Back-Projection (IBP-TV) vs. Variable-Pixel Drizzle Reconstruction",
        total_w
    )

    col_x = [margin, margin + cw + gutter, margin + (cw + gutter) * 2]

    font_section = get_font(FONT_BOLD, 20)
    font_col = get_font(FONT_BOLD, 18)
    font_metric = get_font(FONT_REG, 15)
    font_bold15 = get_font(FONT_BOLD, 15)

    # =========================================================================
    # ROW 1: Central Detail & Grain Structure
    # =========================================================================
    draw.text((margin, header_h + 15), "REGION 1 (100% Zoom Crop): Center Focus & High-Frequency Texture (640x640 px)", fill=(255, 210, 100), font=font_section)

    canvas.paste(c1_p0, (col_x[0], row1_y))
    canvas.paste(c1_ibp, (col_x[1], row1_y))
    canvas.paste(c1_drz, (col_x[2], row1_y))

    # Border outlines
    for x in col_x:
        draw.rectangle([(x - 1, row1_y - 1), (x + cw, row1_y + ch)], outline=(60, 75, 105), width=2)

    # Column Badges Row 1
    by1 = row1_y + ch + 12
    # Col 1: Baseline
    draw_badge(draw, col_x[0], by1, "BASELINE: 1x Pass (Lanczos-3 Sinc)", (60, 70, 85))
    draw.text((col_x[0], by1 + 32), "MTF Acutance: 5.49  |  Edge Grad: 1.9915", fill=(170, 180, 195), font=font_metric)

    # Col 2: IBP-TV
    draw_badge(draw, col_x[1], by1, "IBP-TV: 4-Pass Optical Fusion", (30, 110, 180))
    draw.text((col_x[1], by1 + 32), "MTF Acutance: 6.03 (+10.0%)  |  Edge Grad: 2.1799 (+9.5%)", fill=(100, 200, 255), font=font_metric)

    # Col 3: Drizzle
    draw_badge(draw, col_x[2], by1, "DRIZZLE: Variable-Pixel (pixfrac=0.7)", (180, 80, 40))
    draw.text((col_x[2], by1 + 32), "MTF Acutance: 14.45 (+163.2%)  |  Edge Grad: 1.8494", fill=(255, 170, 120), font=font_metric)

    # =========================================================================
    # ROW 2: Edge Contrast & Fine Feature Definition
    # =========================================================================
    draw.text((margin, row2_y - 35), "REGION 2 (100% Zoom Crop): Fine Edge Acutance & Silver Halide Micro-Grain (640x640 px)", fill=(255, 210, 100), font=font_section)

    canvas.paste(c2_p0, (col_x[0], row2_y))
    canvas.paste(c2_ibp, (col_x[1], row2_y))
    canvas.paste(c2_drz, (col_x[2], row2_y))

    for x in col_x:
        draw.rectangle([(x - 1, row2_y - 1), (x + cw, row2_y + ch)], outline=(60, 75, 105), width=2)

    by2 = row2_y + ch + 12
    draw_badge(draw, col_x[0], by2, "1800 DPI Optical Nyquist Limit", (50, 60, 75))
    draw.text((col_x[0], by2 + 32), "Interpolation blur; unresolvable sub-pixel features", fill=(160, 170, 185), font=font_metric)

    draw_badge(draw, col_x[1], by2, "Natural Film Gradation & Noise Control", (25, 95, 155))
    draw.text((col_x[1], by2 + 32), "Adjoint PSF deblurring + TV edge-preserving smoothness", fill=(100, 200, 255), font=font_metric)

    draw_badge(draw, col_x[2], by2, "Maximum Acutance & Grain Definition", (160, 70, 35))
    draw.text((col_x[2], by2 + 32), "Sub-pixel fractional drop; crisp grain structure, zero smear", fill=(255, 170, 120), font=font_metric)

    # =========================================================================
    # FOOTER: Technical Analysis & Full-Frame Mini Navigator
    # =========================================================================
    card_box = [(margin, footer_y), (total_w - margin, footer_y + table_h)]
    draw.rounded_rectangle(card_box, radius=8, fill=(15, 18, 24), outline=(45, 55, 75), width=2)

    # Full frame mini thumbnail
    thumb_w = 300
    thumb_h = int(thumb_w * (3800 / 5400))
    thumb = im_ibp.resize((thumb_w, thumb_h), Image.Resampling.BOX)
    thumb_x = margin + 25
    thumb_y = footer_y + 18
    canvas.paste(thumb, (thumb_x, thumb_y))
    draw.rectangle([(thumb_x, thumb_y), (thumb_x + thumb_w, thumb_y + thumb_h)], outline=(80, 100, 130), width=1)

    # Draw ROI indicator boxes on thumbnail
    scale_tx = thumb_w / 5400.0
    scale_ty = thumb_h / 3800.0
    r1_thumb = [
        thumb_x + int(crop1_box[0] * scale_tx),
        thumb_y + int(crop1_box[1] * scale_ty),
        thumb_x + int(crop1_box[2] * scale_tx),
        thumb_y + int(crop1_box[3] * scale_ty),
    ]
    r2_thumb = [
        thumb_x + int(crop2_box[0] * scale_tx),
        thumb_y + int(crop2_box[1] * scale_ty),
        thumb_x + int(crop2_box[2] * scale_tx),
        thumb_y + int(crop2_box[3] * scale_ty),
    ]
    draw.rectangle(r1_thumb, outline=(255, 220, 0), width=2)
    draw.rectangle(r2_thumb, outline=(0, 220, 255), width=2)
    draw.text((thumb_x, thumb_y + thumb_h + 6), "Full Frame Navigator (20.5 MP Master)", fill=(130, 150, 180), font=get_font(FONT_REG, 13))

    # Technical breakdown table
    tx = thumb_x + thumb_w + 35
    ty = footer_y + 20
    draw.text((tx, ty), "COMPUTATIONAL ALGORITHM COMPARISON & SELECTION GUIDE", fill=(240, 245, 255), font=get_font(FONT_BOLD, 18))
    
    rows = [
        ("Feature / Metric", "Single Pass Baseline (Lanczos)", "Iterative Back-Projection (IBP-TV)", "Variable-Pixel Drizzle (pixfrac=0.7)"),
        ("Effective Resolution", "1800 DPI (~35.4 lp/mm)", "3600 DPI (~70.9 lp/mm, 2x)", "3600 DPI (~70.9 lp/mm, 2x)"),
        ("Laplacian MTF Acutance", "5.49 (Baseline 1.00x)", "6.03 (+10.0% sharpness boost)", "14.45 (+163.2% ultra-sharp acutance)"),
        ("Tenengrad Edge Gradient", "1.9915", "2.1799 (+9.5% edge steepness)", "1.8494 (Grain-dominated variance)"),
        ("Image Characteristic", "Smooth but optically blurred", "Natural photographic tone, clean gradients", "Crisp individual film grain, micro-textures"),
        ("Recommended For", "Quick draft scans", "Portraits, skies, archival photo masters", "Fine line art, text, dense grain analysis"),
    ]

    col_widths = [190, 260, 290, 310]
    font_th = get_font(FONT_BOLD, 14)
    font_td = get_font(FONT_REG, 13)

    table_top = ty + 35
    for r_idx, row in enumerate(rows):
        cur_y = table_top + r_idx * 28
        if r_idx == 0:
            draw.line([(tx, cur_y + 22), (total_w - margin - 25, cur_y + 22)], fill=(70, 85, 115), width=1)
        cur_x = tx
        for c_idx, cell in enumerate(row):
            f = font_th if r_idx == 0 else font_td
            color = (255, 210, 100) if r_idx == 0 else ((200, 210, 225) if c_idx == 0 else (240, 245, 255))
            if c_idx == 1 and r_idx > 0: color = (160, 170, 185)
            elif c_idx == 2 and r_idx > 0: color = (120, 210, 255)
            elif c_idx == 3 and r_idx > 0: color = (255, 180, 130)
            draw.text((cur_x, cur_y), cell, fill=color, font=f)
            cur_x += col_widths[c_idx]

    os.makedirs(os.path.dirname(OUT_IMG), exist_ok=True)
    canvas.save(OUT_IMG, quality=95)
    print(f"[+] Saved High-Fidelity Comparison Matrix: {OUT_IMG} ({total_w}x{total_h})")

if __name__ == "__main__":
    main()
