#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <stdint.h>
#include <omp.h>

/**
 * PrimeFilm 1800u / 1800i High-Performance Chroma-Only Grain-Preserving Denoiser
 *
 * Removes sensor electronic color speckles and shadow blotches from 35mm film scans
 * while keeping 100% of the film grain, edge acutance, and optical MTF untouched.
 *
 * Supports decoupled CIE-LAB and YCbCr color spaces with edge-preserving
 * bilateral and guided chroma filtering.
 */

#define COLORSPACE_LAB    0
#define COLORSPACE_YCBCR  1

#define FILTER_BILATERAL  0
#define FILTER_GUIDED     1

#define EXP_LUT_SIZE 4096
#define MAX_EXP_VAL 16.0f

static float g_exp_lut[EXP_LUT_SIZE];
static float g_exp_lut_scale;
static int   g_luts_initialized = 0;

static float g_srgb_to_lin[256];

static void init_luts(void) {
    if (g_luts_initialized) return;

    g_exp_lut_scale = (float)(EXP_LUT_SIZE - 1) / MAX_EXP_VAL;
    for (int i = 0; i < EXP_LUT_SIZE; i++) {
        float x = (float)i / g_exp_lut_scale;
        g_exp_lut[i] = expf(-x);
    }

    for (int i = 0; i < 256; i++) {
        float v = (float)i / 255.0f;
        g_srgb_to_lin[i] = (v <= 0.04045f) ? (v / 12.92f) : powf((v + 0.055f) / 1.055f, 2.4f);
    }

    g_luts_initialized = 1;
}

static inline float fast_exp_neg(float val) {
    if (val <= 0.0f) return 1.0f;
    if (val >= MAX_EXP_VAL) return 0.0f;
    int idx = (int)(val * g_exp_lut_scale);
    return g_exp_lut[idx];
}

static inline uint8_t lin_to_srgb(float v) {
    if (v <= 0.0f) return 0;
    if (v >= 1.0f) return 255;
    float s = (v <= 0.0031308f) ? (v * 12.92f) : (1.055f * powf(v, 1.0f / 2.4f) - 0.055f);
    int val = (int)(s * 255.0f + 0.5f);
    return (uint8_t)(val < 0 ? 0 : (val > 255 ? 255 : val));
}

/* CIE-LAB forward and inverse using D65 reference white */
static inline float lab_f(float t) {
    return (t > 0.008856451679f) ? cbrtf(t) : (7.787037f * t + 0.137931f);
}

static inline float lab_finv(float t) {
    float t3 = t * t * t;
    return (t3 > 0.008856451679f) ? t3 : ((t - 0.137931f) / 7.787037f);
}

static inline void rgb_to_lab(uint8_t r, uint8_t g, uint8_t b, float *L, float *a, float *b_out) {
    float r_lin = g_srgb_to_lin[r];
    float g_lin = g_srgb_to_lin[g];
    float b_lin = g_srgb_to_lin[b];

    float X = 0.4124564f * r_lin + 0.3575761f * g_lin + 0.1804375f * b_lin;
    float Y = 0.2126729f * r_lin + 0.7151522f * g_lin + 0.0721750f * b_lin;
    float Z = 0.0193339f * r_lin + 0.1191920f * g_lin + 0.9503041f * b_lin;

    float xr = lab_f(X / 0.95047f);
    float yr = lab_f(Y / 1.00000f);
    float zr = lab_f(Z / 1.08883f);

    *L = 116.0f * yr - 16.0f;
    *a = 500.0f * (xr - yr);
    *b_out = 200.0f * (yr - zr);
}

static inline void lab_to_rgb(float L, float a, float b_in, uint8_t *r, uint8_t *g, uint8_t *b) {
    float yr = (L + 16.0f) / 116.0f;
    float xr = yr + a / 500.0f;
    float zr = yr - b_in / 200.0f;

    float X = lab_finv(xr) * 0.95047f;
    float Y = lab_finv(yr) * 1.00000f;
    float Z = lab_finv(zr) * 1.08883f;

    float r_lin =  3.2404542f * X - 1.5371385f * Y - 0.4985314f * Z;
    float g_lin = -0.9692660f * X + 1.8760108f * Y + 0.0415560f * Z;
    float b_lin =  0.0556434f * X - 0.2040259f * Y + 1.0572252f * Z;

    *r = lin_to_srgb(r_lin);
    *g = lin_to_srgb(g_lin);
    *b = lin_to_srgb(b_lin);
}

/* YCbCr (ITU-R BT.601 full range) forward and inverse */
static inline void rgb_to_ycbcr(uint8_t r, uint8_t g, uint8_t b, float *Y, float *Cb, float *Cr) {
    *Y  =  0.299000f * r + 0.587000f * g + 0.114000f * b;
    *Cb = -0.168736f * r - 0.331264f * g + 0.500000f * b + 128.0f;
    *Cr =  0.500000f * r - 0.418688f * g - 0.081312f * b + 128.0f;
}

static inline void ycbcr_to_rgb(float Y, float Cb, float Cr, uint8_t *r, uint8_t *g, uint8_t *b) {
    float cb_d = Cb - 128.0f;
    float cr_d = Cr - 128.0f;
    float r_f = Y + 1.402000f * cr_d;
    float g_f = Y - 0.344136f * cb_d - 0.714136f * cr_d;
    float b_f = Y + 1.772000f * cb_d;

    int ir = (int)(r_f + 0.5f);
    int ig = (int)(g_f + 0.5f);
    int ib = (int)(b_f + 0.5f);

    *r = (uint8_t)(ir < 0 ? 0 : (ir > 255 ? 255 : ir));
    *g = (uint8_t)(ig < 0 ? 0 : (ig > 255 ? 255 : ig));
    *b = (uint8_t)(ib < 0 ? 0 : (ib > 255 ? 255 : ib));
}

/* Separable box filter for fast O(1) guided filter */
static void box_filter_2d(const float *src, float *dst, int w, int h, int r) {
    float *temp = (float*)malloc(w * h * sizeof(float));

    // Horizontal moving sum
    #pragma omp parallel for schedule(static)
    for (int y = 0; y < h; y++) {
        int row_off = y * w;
        float sum = 0.0f;
        for (int k = -r; k <= r; k++) {
            int px = k < 0 ? 0 : (k >= w ? w - 1 : k);
            sum += src[row_off + px];
        }
        temp[row_off] = sum / (float)(2 * r + 1);

        for (int x = 1; x < w; x++) {
            int x_add = x + r;
            int x_sub = x - r - 1;
            int px_add = x_add >= w ? w - 1 : x_add;
            int px_sub = x_sub < 0 ? 0 : x_sub;
            sum += src[row_off + px_add] - src[row_off + px_sub];
            temp[row_off + x] = sum / (float)(2 * r + 1);
        }
    }

    // Vertical moving sum
    #pragma omp parallel for schedule(static)
    for (int x = 0; x < w; x++) {
        float sum = 0.0f;
        for (int k = -r; k <= r; k++) {
            int py = k < 0 ? 0 : (k >= h ? h - 1 : k);
            sum += temp[py * w + x];
        }
        dst[x] = sum / (float)(2 * r + 1);

        for (int y = 1; y < h; y++) {
            int y_add = y + r;
            int y_sub = y - r - 1;
            int py_add = y_add >= h ? h - 1 : y_add;
            int py_sub = y_sub < 0 ? 0 : y_sub;
            sum += temp[py_add * w + x] - temp[py_sub * w + x];
            dst[y * w + x] = sum / (float)(2 * r + 1);
        }
    }

    free(temp);
}

/* Guided filter for a single channel */
static void guided_filter_channel(const float *guidance, const float *p, float *q, int w, int h, int r, float eps) {
    int total = w * h;
    float *mean_I   = (float*)malloc(total * sizeof(float));
    float *mean_p   = (float*)malloc(total * sizeof(float));
    float *corr_I   = (float*)malloc(total * sizeof(float));
    float *corr_Ip  = (float*)malloc(total * sizeof(float));
    float *a        = (float*)malloc(total * sizeof(float));
    float *b        = (float*)malloc(total * sizeof(float));
    float *mean_a   = (float*)malloc(total * sizeof(float));
    float *mean_b   = (float*)malloc(total * sizeof(float));
    float *buf      = (float*)malloc(total * sizeof(float));

    box_filter_2d(guidance, mean_I, w, h, r);
    box_filter_2d(p, mean_p, w, h, r);

    #pragma omp parallel for schedule(static)
    for (int i = 0; i < total; i++) buf[i] = guidance[i] * guidance[i];
    box_filter_2d(buf, corr_I, w, h, r);

    #pragma omp parallel for schedule(static)
    for (int i = 0; i < total; i++) buf[i] = guidance[i] * p[i];
    box_filter_2d(buf, corr_Ip, w, h, r);

    #pragma omp parallel for schedule(static)
    for (int i = 0; i < total; i++) {
        float var_I = corr_I[i] - mean_I[i] * mean_I[i];
        float cov_Ip = corr_Ip[i] - mean_I[i] * mean_p[i];
        a[i] = cov_Ip / (var_I + eps);
        b[i] = mean_p[i] - a[i] * mean_I[i];
    }

    box_filter_2d(a, mean_a, w, h, r);
    box_filter_2d(b, mean_b, w, h, r);

    #pragma omp parallel for schedule(static)
    for (int i = 0; i < total; i++) {
        q[i] = mean_a[i] * guidance[i] + mean_b[i];
    }

    free(mean_I); free(mean_p); free(corr_I); free(corr_Ip);
    free(a); free(b); free(mean_a); free(mean_b); free(buf);
}

/**
 * High-performance edge-preserving bilateral filter on decoupled chrominance channels.
 * Luminance is 100% UNTOUCHED to guarantee zero grain blurring.
 */
static void bilateral_filter_chroma(const float *c1, const float *c2,
                                   float *c1_out, float *c2_out,
                                   int w, int h, int radius, float strength) {
    float sigma_s = (float)radius / 2.0f;
    if (sigma_s < 0.8f) sigma_s = 0.8f;
    float sigma_c = strength;
    if (sigma_c < 1.0f) sigma_c = 1.0f;

    float inv_2_sig_s2 = 1.0f / (2.0f * sigma_s * sigma_s);
    float inv_2_sig_c2 = 1.0f / (2.0f * sigma_c * sigma_c);

    int klen = 2 * radius + 1;
    float *spatial_w = (float*)malloc(klen * klen * sizeof(float));
    for (int dy = -radius; dy <= radius; dy++) {
        for (int dx = -radius; dx <= radius; dx++) {
            float dist2 = (float)(dx * dx + dy * dy);
            spatial_w[(dy + radius) * klen + (dx + radius)] = expf(-dist2 * inv_2_sig_s2);
        }
    }

    #pragma omp parallel for schedule(dynamic, 16)
    for (int y = 0; y < h; y++) {
        int is_y_interior = (y >= radius && y < h - radius);
        int row_off = y * w;

        for (int x = 0; x < w; x++) {
            int idx = row_off + x;
            float center_c1 = c1[idx];
            float center_c2 = c2[idx];

            float sum_w = 0.0f;
            float sum_c1 = 0.0f;
            float sum_c2 = 0.0f;

            if (is_y_interior && x >= radius && x < w - radius) {
                // Branchless fast path for >98% of pixels
                for (int dy = -radius; dy <= radius; dy++) {
                    int nrow_off = (y + dy) * w;
                    int k_row = (dy + radius) * klen;
                    #pragma GCC unroll 4
                    for (int dx = -radius; dx <= radius; dx++) {
                        int nidx = nrow_off + x + dx;
                        float sw = spatial_w[k_row + (dx + radius)];

                        float dc1 = c1[nidx] - center_c1;
                        float dc2 = c2[nidx] - center_c2;
                        float c_dist2 = dc1 * dc1 + dc2 * dc2;

                        float rw = fast_exp_neg(c_dist2 * inv_2_sig_c2);
                        float w_val = sw * rw;

                        sum_w += w_val;
                        sum_c1 += w_val * c1[nidx];
                        sum_c2 += w_val * c2[nidx];
                    }
                }
            } else {
                // Border clamped path
                for (int dy = -radius; dy <= radius; dy++) {
                    int ny = y + dy;
                    if (ny < 0) ny = 0;
                    else if (ny >= h) ny = h - 1;

                    int nrow_off = ny * w;
                    int k_row = (dy + radius) * klen;

                    for (int dx = -radius; dx <= radius; dx++) {
                        int nx = x + dx;
                        if (nx < 0) nx = 0;
                        else if (nx >= w) nx = w - 1;

                        int nidx = nrow_off + nx;
                        float sw = spatial_w[k_row + (dx + radius)];

                        float dc1 = c1[nidx] - center_c1;
                        float dc2 = c2[nidx] - center_c2;
                        float c_dist2 = dc1 * dc1 + dc2 * dc2;

                        float rw = fast_exp_neg(c_dist2 * inv_2_sig_c2);
                        float w_val = sw * rw;

                        sum_w += w_val;
                        sum_c1 += w_val * c1[nidx];
                        sum_c2 += w_val * c2[nidx];
                    }
                }
            }

            c1_out[idx] = sum_c1 / sum_w;
            c2_out[idx] = sum_c2 / sum_w;
        }
    }

    free(spatial_w);
}

/**
 * Public C API: Denoises RGB24 pixel buffer in-place or into separate output buffer.
 *
 * Parameters:
 *   rgb_in:      Pointer to input RGB buffer (w * h * 3 bytes).
 *   rgb_out:     Pointer to output buffer (can be identical to rgb_in for in-place).
 *   w, h:        Width and height of the image.
 *   radius:      Spatial filter radius (default: 5).
 *   strength:    Chroma range filter strength (default: 12.0).
 *   colorspace:  0 = CIE-LAB, 1 = YCbCr.
 *   filter_type: 0 = Bilateral, 1 = Guided.
 */
int denoise_chroma_rgb24(const uint8_t *rgb_in, uint8_t *rgb_out, int w, int h,
                         int radius, float strength, int colorspace, int filter_type) {
    if (!rgb_in || !rgb_out || w <= 0 || h <= 0) return -1;
    init_luts();

    int total = w * h;
    float *ch_lum = (float*)malloc(total * sizeof(float));
    float *ch_c1  = (float*)malloc(total * sizeof(float));
    float *ch_c2  = (float*)malloc(total * sizeof(float));
    float *out_c1 = (float*)malloc(total * sizeof(float));
    float *out_c2 = (float*)malloc(total * sizeof(float));

    if (!ch_lum || !ch_c1 || !ch_c2 || !out_c1 || !out_c2) {
        free(ch_lum); free(ch_c1); free(ch_c2); free(out_c1); free(out_c2);
        return -2;
    }

    // Step 1: Forward conversion to decoupled color space
    if (colorspace == COLORSPACE_LAB) {
        #pragma omp parallel for schedule(static)
        for (int i = 0; i < total; i++) {
            rgb_to_lab(rgb_in[i * 3 + 0], rgb_in[i * 3 + 1], rgb_in[i * 3 + 2],
                       &ch_lum[i], &ch_c1[i], &ch_c2[i]);
        }
    } else {
        #pragma omp parallel for schedule(static)
        for (int i = 0; i < total; i++) {
            rgb_to_ycbcr(rgb_in[i * 3 + 0], rgb_in[i * 3 + 1], rgb_in[i * 3 + 2],
                         &ch_lum[i], &ch_c1[i], &ch_c2[i]);
        }
    }

    // Step 2: Edge-preserving filter applied ONLY to chrominance channels
    if (filter_type == FILTER_GUIDED) {
        float eps = strength * strength;
        guided_filter_channel(ch_c1, ch_c1, out_c1, w, h, radius, eps);
        guided_filter_channel(ch_c2, ch_c2, out_c2, w, h, radius, eps);
    } else {
        bilateral_filter_chroma(ch_c1, ch_c2, out_c1, out_c2, w, h, radius, strength);
    }

    // Step 3: Inverse conversion back to RGB.
    // LUMINANCE IS 100% PRESERVED: ch_lum is passed completely untouched!
    if (colorspace == COLORSPACE_LAB) {
        #pragma omp parallel for schedule(static)
        for (int i = 0; i < total; i++) {
            lab_to_rgb(ch_lum[i], out_c1[i], out_c2[i],
                       &rgb_out[i * 3 + 0], &rgb_out[i * 3 + 1], &rgb_out[i * 3 + 2]);
        }
    } else {
        #pragma omp parallel for schedule(static)
        for (int i = 0; i < total; i++) {
            ycbcr_to_rgb(ch_lum[i], out_c1[i], out_c2[i],
                         &rgb_out[i * 3 + 0], &rgb_out[i * 3 + 1], &rgb_out[i * 3 + 2]);
        }
    }

    free(ch_lum); free(ch_c1); free(ch_c2); free(out_c1); free(out_c2);
    return 0;
}

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "PrimeFilm 1800u / 1800i Chroma Denoising Engine\n");
        fprintf(stderr, "Usage: %s <input.ppm> <output.ppm> [radius=5] [strength=12.0] [colorspace=lab|ycbcr] [filter=bilateral|guided]\n", argv[0]);
        return 1;
    }

    const char *in_path = argv[1];
    const char *out_path = argv[2];
    int radius = (argc >= 4) ? atoi(argv[3]) : 5;
    float strength = (argc >= 5) ? (float)atof(argv[4]) : 12.0f;
    int colorspace = COLORSPACE_LAB;
    if (argc >= 6) {
        if (strcasecmp(argv[5], "ycbcr") == 0) colorspace = COLORSPACE_YCBCR;
    }
    int filter_type = FILTER_BILATERAL;
    if (argc >= 7) {
        if (strcasecmp(argv[6], "guided") == 0) filter_type = FILTER_GUIDED;
    }

    FILE *fin = fopen(in_path, "rb");
    if (!fin) {
        perror("Failed to open input PPM");
        return 1;
    }

    char magic[3];
    int w, h, max_val;
    if (fscanf(fin, "%2s %d %d %d", magic, &w, &h, &max_val) != 4 || strcmp(magic, "P6") != 0) {
        fprintf(stderr, "Error: only binary PPM (P6) supported.\n");
        fclose(fin);
        return 1;
    }
    fgetc(fin); // Consume exactly single whitespace/newline delimiter after max_val

    int total_pixels = w * h;
    uint8_t *rgb = (uint8_t*)malloc(total_pixels * 3);
    if (fread(rgb, 1, total_pixels * 3, fin) != (size_t)(total_pixels * 3)) {
        fprintf(stderr, "Error reading PPM pixel data.\n");
        fclose(fin);
        free(rgb);
        return 1;
    }
    fclose(fin);

    printf("[*] Chroma Denoising %dx%d image...\n", w, h);
    printf("    Color Space: %s | Filter: %s\n",
           colorspace == COLORSPACE_LAB ? "CIE-LAB" : "YCbCr",
           filter_type == FILTER_BILATERAL ? "Bilateral" : "Guided");
    printf("    Radius     : %d px | Strength: %.2f\n", radius, strength);

    double t0 = omp_get_wtime();
    int ret = denoise_chroma_rgb24(rgb, rgb, w, h, radius, strength, colorspace, filter_type);
    double elapsed = omp_get_wtime() - t0;

    if (ret != 0) {
        fprintf(stderr, "Error processing image: code %d\n", ret);
        free(rgb);
        return 1;
    }

    printf("[+] Denoising completed in %.3f seconds (%.1f MP/s)!\n", elapsed, (double)total_pixels / (elapsed * 1e6));

    FILE *fout = fopen(out_path, "wb");
    if (!fout) {
        perror("Failed to open output PPM");
        free(rgb);
        return 1;
    }
    fprintf(fout, "P6\n%d %d\n255\n", w, h);
    fwrite(rgb, 1, total_pixels * 3, fout);
    fclose(fout);

    printf("[+] Successfully saved chroma-denoised PPM: %s\n", out_path);
    free(rgb);
    return 0;
}
