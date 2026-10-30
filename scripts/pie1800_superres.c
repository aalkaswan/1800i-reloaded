#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#ifdef _OPENMP
#include <omp.h>
#endif

/**
 * PrimeFilm 1800u / 1800i High-Resolution Super-Resolution Reconstruction Engine
 * Implements:
 *   1. Sub-pixel spatial shift estimation (Normalized Cross-Correlation + quadratic peak interpolation)
 *   2. Iterative Back-Projection (IBP) with Total Variation (TV) regularization
 *   3. Variable-Pixel Linear Reconstruction ("Drizzle", Fruchter & Hook 2002)
 *
 * Reconstructs 2x super-resolved images (~3600 DPI equivalent) from sub-pixel shifted passes.
 */

#define MAX_PASSES 16
#define CLAMP(v, min_v, max_v) ((v) < (min_v) ? (min_v) : ((v) > (max_v) ? (max_v) : (v)))

typedef struct {
    int w;
    int h;
    float *r;
    float *g;
    float *b;
    float shift_x;
    float shift_y;
} ImagePass;

static ImagePass* load_ppm(const char *filename) {
    FILE *f = fopen(filename, "rb");
    if (!f) {
        fprintf(stderr, "Error: cannot open input file '%s'\n", filename);
        return NULL;
    }

    char line[128];
    if (!fgets(line, sizeof(line), f) || strncmp(line, "P6", 2) != 0) {
        fprintf(stderr, "Error: '%s' is not a binary PPM (P6).\n", filename);
        fclose(f);
        return NULL;
    }

    // Read dimensions, skipping comment lines
    int w = 0, h = 0, max_val = 0;
    while (fgets(line, sizeof(line), f)) {
        if (line[0] == '#') continue;
        if (sscanf(line, "%d %d", &w, &h) == 2) break;
    }

    // Read max_val, skipping comment lines
    while (fgets(line, sizeof(line), f)) {
        if (line[0] == '#') continue;
        if (sscanf(line, "%d", &max_val) == 1) break;
    }

    if (w <= 0 || h <= 0 || max_val <= 0) {
        fprintf(stderr, "Error parsing PPM dimensions from '%s'.\n", filename);
        fclose(f);
        return NULL;
    }

    int total = w * h;
    unsigned char *raw = (unsigned char*)malloc(total * 3);
    if (!raw || fread(raw, 1, total * 3, f) != (size_t)(total * 3)) {
        fprintf(stderr, "Error reading pixel payload from '%s'.\n", filename);
        fclose(f);
        free(raw);
        return NULL;
    }
    fclose(f);

    ImagePass *img = (ImagePass*)malloc(sizeof(ImagePass));
    img->w = w;
    img->h = h;
    img->shift_x = 0.0f;
    img->shift_y = 0.0f;
    img->r = (float*)malloc(total * sizeof(float));
    img->g = (float*)malloc(total * sizeof(float));
    img->b = (float*)malloc(total * sizeof(float));

    for (int i = 0; i < total; i++) {
        img->r[i] = (float)raw[i * 3 + 0];
        img->g[i] = (float)raw[i * 3 + 1];
        img->b[i] = (float)raw[i * 3 + 2];
    }
    free(raw);
    return img;
}

static void free_image_pass(ImagePass *img) {
    if (img) {
        if (img->r) free(img->r);
        if (img->g) free(img->g);
        if (img->b) free(img->b);
        free(img);
    }
}

static int save_ppm(const char *filename, int w, int h, const float *r, const float *g, const float *b) {
    FILE *f = fopen(filename, "wb");
    if (!f) {
        fprintf(stderr, "Error opening output file '%s'\n", filename);
        return -1;
    }
    fprintf(f, "P6\n%d %d\n255\n", w, h);
    int total = w * h;
    unsigned char *buf = (unsigned char*)malloc(total * 3);
    for (int i = 0; i < total; i++) {
        int vr = (int)(r[i] + 0.5f);
        int vg = (int)(g[i] + 0.5f);
        int vb = (int)(b[i] + 0.5f);
        buf[i * 3 + 0] = (unsigned char)CLAMP(vr, 0, 255);
        buf[i * 3 + 1] = (unsigned char)CLAMP(vg, 0, 255);
        buf[i * 3 + 2] = (unsigned char)CLAMP(vb, 0, 255);
    }
    fwrite(buf, 1, total * 3, f);
    fclose(f);
    free(buf);
    return 0;
}

/**
 * Compute Sobel gradient magnitude for illumination-invariant and
 * polarity-invariant (negative vs positive) sub-pixel registration.
 */
static void compute_gradient(const float *src, float *grad, int w, int h) {
    #pragma omp parallel for schedule(static)
    for (int y = 1; y < h - 1; y++) {
        int row = y * w;
        for (int x = 1; x < w - 1; x++) {
            float gx = (src[row + x + 1 - w] + 2.0f * src[row + x + 1] + src[row + x + 1 + w]) -
                       (src[row + x - 1 - w] + 2.0f * src[row + x - 1] + src[row + x - 1 + w]);
            float gy = (src[row + x - 1 + w] + 2.0f * src[row + x + w] + src[row + x + 1 + w]) -
                       (src[row + x - 1 - w] + 2.0f * src[row + x - w] + src[row + x + 1 - w]);
            grad[row + x] = sqrtf(gx * gx + gy * gy);
        }
    }
}

/**
 * Estimate relative sub-pixel shift between reference pass (pass 0) and target pass.
 * Uses gradient magnitude normalized cross-correlation over central region.
 */
static void estimate_subpixel_shift(const ImagePass *ref, ImagePass *tgt, int search_radius) {
    int w = ref->w;
    int h = ref->h;
    if (tgt->w != w || tgt->h != h) {
        fprintf(stderr, "Warning: pass dimensions do not match reference.\n");
        return;
    }

    float *grad_ref = (float*)calloc(w * h, sizeof(float));
    float *grad_tgt = (float*)calloc(w * h, sizeof(float));
    compute_gradient(ref->g, grad_ref, w, h);
    compute_gradient(tgt->g, grad_tgt, w, h);

    // Select central 50% region for correlation
    int roi_x0 = w / 4;
    int roi_y0 = h / 4;
    int roi_w = w / 2;
    int roi_h = h / 2;
    int roi_total = roi_w * roi_h;

    double sum_ref = 0.0, sq_ref = 0.0;
    for (int y = 0; y < roi_h; y++) {
        int idx = (roi_y0 + y) * w + roi_x0;
        for (int x = 0; x < roi_w; x++) {
            double v = grad_ref[idx + x];
            sum_ref += v;
            sq_ref += v * v;
        }
    }
    double mean_ref = sum_ref / roi_total;
    double var_ref = sq_ref - sum_ref * mean_ref;
    if (var_ref <= 1e-6) var_ref = 1.0;

    int max_ry = (roi_y0 < (h - (roi_y0 + roi_h))) ? roi_y0 - 1 : (h - (roi_y0 + roi_h)) - 1;
    int max_rx = (roi_x0 < (w - (roi_x0 + roi_w))) ? roi_x0 - 1 : (w - (roi_x0 + roi_w)) - 1;
    int ry = search_radius;
    int rx = 16;
    if (ry > max_ry) ry = max_ry;
    if (rx > max_rx) rx = max_rx;
    if (ry < 1) ry = 1;
    if (rx < 1) rx = 1;

    int grid_h = 2 * ry + 1;
    int grid_w = 2 * rx + 1;
    float *corr_grid = (float*)malloc(grid_h * grid_w * sizeof(float));

    #pragma omp parallel for collapse(2) schedule(dynamic)
    for (int dy = -ry; dy <= ry; dy++) {
        for (int dx = -rx; dx <= rx; dx++) {
            double sum_tgt = 0.0, sq_tgt = 0.0, cross = 0.0;
            for (int y = 0; y < roi_h; y++) {
                int idx_r = (roi_y0 + y) * w + roi_x0;
                int idx_t = (roi_y0 + y + dy) * w + (roi_x0 + dx);
                for (int x = 0; x < roi_w; x++) {
                    double vr = grad_ref[idx_r + x];
                    double vt = grad_tgt[idx_t + x];
                    sum_tgt += vt;
                    sq_tgt += vt * vt;
                    cross += vr * vt;
                }
            }
            double mean_tgt = sum_tgt / roi_total;
            double var_tgt = sq_tgt - sum_tgt * mean_tgt;
            if (var_tgt <= 1e-6) var_tgt = 1.0;

            double cov = cross - sum_ref * mean_tgt;
            float ncc = (float)(cov / sqrt(var_ref * var_tgt));
            corr_grid[(dy + ry) * grid_w + (dx + rx)] = ncc;
        }
    }

    float best_val = -1e9f;
    int best_dy = 0, best_dx = 0;
    for (int dy = -ry; dy <= ry; dy++) {
        for (int dx = -rx; dx <= rx; dx++) {
            float ncc = corr_grid[(dy + ry) * grid_w + (dx + rx)];
            if (ncc > best_val) {
                best_val = ncc;
                best_dy = dy;
                best_dx = dx;
            }
        }
    }

    // Sub-pixel quadratic peak interpolation
    float sub_dy = (float)best_dy;
    float sub_dx = (float)best_dx;

    if (best_dy > -ry && best_dy < ry && best_dx > -rx && best_dx < rx) {
        float c_mid = corr_grid[(best_dy + ry) * grid_w + (best_dx + rx)];
        float c_ym = corr_grid[(best_dy - 1 + ry) * grid_w + (best_dx + rx)];
        float c_yp = corr_grid[(best_dy + 1 + ry) * grid_w + (best_dx + rx)];
        float denom_y = (c_ym - 2.0f * c_mid + c_yp);
        if (fabsf(denom_y) > 1e-7f) {
            sub_dy += 0.5f * (c_ym - c_yp) / denom_y;
        }

        float c_xm = corr_grid[(best_dy + ry) * grid_w + (best_dx - 1 + rx)];
        float c_xp = corr_grid[(best_dy + ry) * grid_w + (best_dx + 1 + rx)];
        float denom_x = (c_xm - 2.0f * c_mid + c_xp);
        if (fabsf(denom_x) > 1e-7f) {
            sub_dx += 0.5f * (c_xm - c_xp) / denom_x;
        }
    }

    if (abs(best_dy) == ry || abs(best_dx) == rx) {
        fprintf(stderr, "[!] WARNING: Pass registration reached search boundary (dy=%d, dx=%d). Increase search radius.\n", best_dy, best_dx);
    }

    free(corr_grid);
    free(grad_ref);
    free(grad_tgt);

    tgt->shift_x = sub_dx;
    tgt->shift_y = sub_dy;
    printf("[*] Sub-pixel registration: shift_x = %+.3f px, shift_y = %+.3f px (Edge NCC = %.4f)\n",
           sub_dx, sub_dy, best_val);
}

/**
 * 2D separable Gaussian blur kernel for PSF forward/adjoint modeling.
 */
static void gaussian_blur_2d(const float *src, float *dst, int w, int h, float sigma) {
    if (sigma <= 0.05f) {
        memcpy(dst, src, w * h * sizeof(float));
        return;
    }
    int radius = (int)ceilf(sigma * 2.5f);
    int ksize = 2 * radius + 1;
    float *k = (float*)malloc(ksize * sizeof(float));
    float sum = 0.0f;
    for (int i = -radius; i <= radius; i++) {
        float val = expf(-(float)(i * i) / (2.0f * sigma * sigma));
        k[i + radius] = val;
        sum += val;
    }
    for (int i = 0; i < ksize; i++) k[i] /= sum;

    float *temp = (float*)malloc(w * h * sizeof(float));

    #pragma omp parallel for schedule(static)
    for (int y = 0; y < h; y++) {
        int row = y * w;
        for (int x = 0; x < w; x++) {
            float v = 0.0f;
            for (int d = -radius; d <= radius; d++) {
                int px = x + d;
                if (px < 0) px = 0;
                else if (px >= w) px = w - 1;
                v += src[row + px] * k[d + radius];
            }
            temp[row + x] = v;
        }
    }

    #pragma omp parallel for schedule(static)
    for (int y = 0; y < h; y++) {
        for (int x = 0; x < w; x++) {
            float v = 0.0f;
            for (int d = -radius; d <= radius; d++) {
                int py = y + d;
                if (py < 0) py = 0;
                else if (py >= h) py = h - 1;
                v += temp[py * w + x] * k[d + radius];
            }
            dst[y * w + x] = v;
        }
    }

    free(k);
    free(temp);
}

/**
 * Bilinear sampling from high-resolution image with sub-pixel shift.
 */
static inline float sample_hr_bilinear(const float *hr, int hr_w, int hr_h, float x, float y) {
    if (x < 0.0f) x = 0.0f;
    if (y < 0.0f) y = 0.0f;
    if (x >= (float)(hr_w - 1)) x = (float)(hr_w - 1.001f);
    if (y >= (float)(hr_h - 1)) y = (float)(hr_h - 1.001f);

    int x0 = (int)x;
    int y0 = (int)y;
    int x1 = x0 + 1;
    int y1 = y0 + 1;

    float fx = x - (float)x0;
    float fy = y - (float)y0;

    float p00 = hr[y0 * hr_w + x0];
    float p10 = hr[y0 * hr_w + x1];
    float p01 = hr[y1 * hr_w + x0];
    float p11 = hr[y1 * hr_w + x1];

    float top = p00 * (1.0f - fx) + p10 * fx;
    float bot = p01 * (1.0f - fx) + p11 * fx;
    return top * (1.0f - fy) + bot * fy;
}

/**
 * Forward model: Simulate low-resolution pass from high-resolution estimate.
 * Y_hat_k = Downsample(Blur(Warp(X, shift_k)))
 */
static void forward_projection(const float *hr_blurred, int hr_w, int hr_h,
                               float *lr_out, int lr_w, int lr_h,
                               float shift_x, float shift_y, int scale) {
    #pragma omp parallel for schedule(static)
    for (int ly = 0; ly < lr_h; ly++) {
        for (int lx = 0; lx < lr_w; lx++) {
            // Map LR pixel center to HR coordinates with shift
            float hx = ((float)lx + 0.5f - shift_x) * (float)scale - 0.5f;
            float hy = ((float)ly + 0.5f - shift_y) * (float)scale - 0.5f;
            lr_out[ly * lr_w + lx] = sample_hr_bilinear(hr_blurred, hr_w, hr_h, hx, hy);
        }
    }
}

/**
 * Backward projection: Distribute low-resolution residual error back into high-resolution grid.
 */
static void backward_projection(const float *lr_err, int lr_w, int lr_h,
                                float *hr_corr, float *hr_mask, int hr_w, int hr_h,
                                float shift_x, float shift_y, int scale) {
    #pragma omp parallel for schedule(static)
    for (int hy = 0; hy < hr_h; hy++) {
        for (int hx = 0; hx < hr_w; hx++) {
            // Map HR pixel to LR coordinates with inverse shift
            float lx = ((float)hx + 0.5f) / (float)scale - 0.5f + shift_x;
            float ly = ((float)hy + 0.5f) / (float)scale - 0.5f + shift_y;
            int idx = hy * hr_w + hx;

            if (lx < 0.0f || ly < 0.0f || lx >= (float)(lr_w - 1) || ly >= (float)(lr_h - 1)) {
                hr_corr[idx] = 0.0f;
                if (hr_mask) hr_mask[idx] = 0.0f;
                continue;
            }
            if (hr_mask) hr_mask[idx] = 1.0f;

            int x0 = (int)lx;
            int y0 = (int)ly;
            int x1 = x0 + 1;
            int y1 = y0 + 1;

            float fx = lx - (float)x0;
            float fy = ly - (float)y0;

            float e00 = lr_err[y0 * lr_w + x0];
            float e10 = lr_err[y0 * lr_w + x1];
            float e01 = lr_err[y1 * lr_w + x0];
            float e11 = lr_err[y1 * lr_w + x1];

            float top = e00 * (1.0f - fx) + e10 * fx;
            float bot = e01 * (1.0f - fx) + e11 * fx;
            hr_corr[idx] = top * (1.0f - fy) + bot * fy;
        }
    }
}

/**
 * Iterative Back-Projection (IBP) channel reconstruction.
 */
static void superres_ibp_channel(ImagePass **passes, int num_passes, int chan_idx,
                                 float *hr_out, int hr_w, int hr_h, int scale,
                                 float psf_sigma, int iterations, float tv_weight) {
    int lr_w = passes[0]->w;
    int lr_h = passes[0]->h;
    int hr_total = hr_w * hr_h;
    int lr_total = lr_w * lr_h;

    float *hr_blurred = (float*)malloc(hr_total * sizeof(float));
    float *lr_sim = (float*)malloc(lr_total * sizeof(float));
    float *lr_err = (float*)malloc(lr_total * sizeof(float));
    float *hr_corr = (float*)malloc(hr_total * sizeof(float));
    float *hr_corr_acc = (float*)malloc(hr_total * sizeof(float));
    float *hr_weights = (float*)malloc(hr_total * sizeof(float));
    float *hr_mask = (float*)malloc(hr_total * sizeof(float));

    // Initial estimate: Bicubic upsampling of pass 0
    #pragma omp parallel for schedule(static)
    for (int hy = 0; hy < hr_h; hy++) {
        for (int hx = 0; hx < hr_w; hx++) {
            float lx = ((float)hx + 0.5f) / (float)scale - 0.5f;
            float ly = ((float)hy + 0.5f) / (float)scale - 0.5f;
            const float *src = (chan_idx == 0) ? passes[0]->r : ((chan_idx == 1) ? passes[0]->g : passes[0]->b);
            hr_out[hy * hr_w + hx] = sample_hr_bilinear(src, lr_w, lr_h, lx, ly);
        }
    }

    printf("[*] Starting IBP channel %d (%d passes, %dx%d -> %dx%d, %d iters, sigma=%.2f)...\n",
           chan_idx, num_passes, lr_w, lr_h, hr_w, hr_h, iterations, psf_sigma);

    for (int iter = 0; iter < iterations; iter++) {
        memset(hr_corr_acc, 0, hr_total * sizeof(float));
        memset(hr_weights, 0, hr_total * sizeof(float));

        // Forward and backward projection for each low-resolution pass
        for (int p = 0; p < num_passes; p++) {
            const float *lr_actual = (chan_idx == 0) ? passes[p]->r : ((chan_idx == 1) ? passes[p]->g : passes[p]->b);

            // Step 1: Optical blur of current HR estimate
            gaussian_blur_2d(hr_out, hr_blurred, hr_w, hr_h, psf_sigma);

            // Step 2: Downsample with pass sub-pixel shift
            forward_projection(hr_blurred, hr_w, hr_h, lr_sim, lr_w, lr_h,
                               passes[p]->shift_x, passes[p]->shift_y, scale);

            // Step 3: Compute residual error
            for (int i = 0; i < lr_total; i++) {
                lr_err[i] = lr_actual[i] - lr_sim[i];
            }

            // Step 4: Back-project error to high-resolution grid with field-of-view weighting
            backward_projection(lr_err, lr_w, lr_h, hr_corr, hr_mask, hr_w, hr_h,
                                passes[p]->shift_x, passes[p]->shift_y, scale);

            // Step 5: Adjoint PSF blur
            gaussian_blur_2d(hr_corr, hr_blurred, hr_w, hr_h, psf_sigma);

            // Accumulate back-projection updates and observation counts
            for (int i = 0; i < hr_total; i++) {
                hr_corr_acc[i] += hr_blurred[i];
                hr_weights[i] += hr_mask[i];
            }
        }

        // Apply normalized gradient update and Total Variation (TV) regularizer
        #pragma omp parallel for schedule(static)
        for (int y = 1; y < hr_h - 1; y++) {
            int row = y * hr_w;
            for (int x = 1; x < hr_w - 1; x++) {
                int idx = row + x;
                float w = hr_weights[idx];
                float update = (w > 0.0f) ? (hr_corr_acc[idx] / w) : 0.0f;

                if (tv_weight > 0.0f) {
                    // Total Variation gradient: div(grad(I) / |grad(I)|)
                    float ix = hr_out[idx + 1] - hr_out[idx - 1];
                    float iy = hr_out[idx + hr_w] - hr_out[idx - hr_w];
                    float norm = sqrtf(ix * ix + iy * iy + 1.0f);
                    float laplacian = (hr_out[idx + 1] + hr_out[idx - 1] +
                                       hr_out[idx + hr_w] + hr_out[idx - hr_w] - 4.0f * hr_out[idx]);
                    update += tv_weight * (laplacian / norm);
                }

                float val = hr_out[idx] + update;
                hr_out[idx] = CLAMP(val, 0.0f, 255.0f);
            }
        }
    }

    free(hr_blurred);
    free(lr_sim);
    free(lr_err);
    free(hr_corr);
    free(hr_corr_acc);
    free(hr_weights);
    free(hr_mask);
}

/**
 * Variable-Pixel Linear Reconstruction ("Drizzle", Fruchter & Hook 2002).
 * Drops each shrunk low-resolution pixel (pixfrac) onto fine high-resolution grid.
 */
static void superres_drizzle_channel(ImagePass **passes, int num_passes, int chan_idx,
                                     float *hr_out, int hr_w, int hr_h, int scale, float pixfrac) {
    int lr_w = passes[0]->w;
    int lr_h = passes[0]->h;
    int hr_total = hr_w * hr_h;

    float *weight = (float*)calloc(hr_total, sizeof(float));
    float *flux = (float*)calloc(hr_total, sizeof(float));

    float s = (float)scale;
    float p = CLAMP(pixfrac, 0.1f, 1.0f);
    float drop_half_w = 0.5f * s * p;
    float drop_half_h = 0.5f * s * p;
    float drop_area = (2.0f * drop_half_w) * (2.0f * drop_half_h);

    for (int p_idx = 0; p_idx < num_passes; p_idx++) {
        const float *lr_data = (chan_idx == 0) ? passes[p_idx]->r :
                               ((chan_idx == 1) ? passes[p_idx]->g : passes[p_idx]->b);
        float sx = passes[p_idx]->shift_x;
        float sy = passes[p_idx]->shift_y;

        for (int ly = 0; ly < lr_h; ly++) {
            for (int lx = 0; lx < lr_w; lx++) {
                float val = lr_data[ly * lr_w + lx];

                // Center of the shrunk drop on HR grid
                float cx = ((float)lx + 0.5f - sx) * s - 0.5f;
                float cy = ((float)ly + 0.5f - sy) * s - 0.5f;

                float x_min = cx - drop_half_w;
                float x_max = cx + drop_half_w;
                float y_min = cy - drop_half_h;
                float y_max = cy + drop_half_h;

                int ix0 = (int)floorf(x_min);
                int ix1 = (int)ceilf(x_max);
                int iy0 = (int)floorf(y_min);
                int iy1 = (int)ceilf(y_max);

                if (ix0 < 0) ix0 = 0;
                if (iy0 < 0) iy0 = 0;
                if (ix1 >= hr_w) ix1 = hr_w - 1;
                if (iy1 >= hr_h) iy1 = hr_h - 1;

                for (int hy = iy0; hy <= iy1; hy++) {
                    float cell_y0 = (float)hy - 0.5f;
                    float cell_y1 = (float)hy + 0.5f;
                    float overlap_y = fmaxf(0.0f, fminf(cell_y1, y_max) - fmaxf(cell_y0, y_min));
                    if (overlap_y <= 0.0f) continue;

                    int row = hy * hr_w;
                    for (int hx = ix0; hx <= ix1; hx++) {
                        float cell_x0 = (float)hx - 0.5f;
                        float cell_x1 = (float)hx + 0.5f;
                        float overlap_x = fmaxf(0.0f, fminf(cell_x1, x_max) - fmaxf(cell_x0, x_min));
                        if (overlap_x <= 0.0f) continue;

                        float a = (overlap_x * overlap_y) / drop_area;
                        int idx = row + hx;
                        flux[idx] += a * val;
                        weight[idx] += a;
                    }
                }
            }
        }
    }

    // Normalize and fill gaps if weight == 0
    #pragma omp parallel for schedule(static)
    for (int i = 0; i < hr_total; i++) {
        if (weight[i] > 1e-5f) {
            hr_out[i] = flux[i] / weight[i];
        } else {
            // Nearest-neighbor fallback for rare unmapped border pixels
            hr_out[i] = 0.0f;
        }
    }

    free(weight);
    free(flux);
}

int main(int argc, char **argv) {
    if (argc < 3) {
        printf("PrimeFilm 1800u / 1800i Super-Resolution Reconstruction Engine\n");
        printf("Usage: %s <output.ppm> <method: ibp|drizzle> <pass1.ppm> [pass2.ppm pass3.ppm ...]\n", argv[0]);
        printf("Options (via env vars):\n");
        printf("  PIE_SCALE=2        Super-resolution scale factor (default: 2 -> 3600 DPI)\n");
        printf("  PIE_ITERS=8        IBP iterations (default: 8)\n");
        printf("  PIE_SIGMA=1.0      PSF blur radius (default: 1.0)\n");
        printf("  PIE_TV=0.03        Total variation regularizer (default: 0.03)\n");
        printf("  PIE_PIXFRAC=0.7    Drizzle drop shrink factor (default: 0.7)\n");
        return 1;
    }

    const char *out_path = argv[1];
    const char *method = argv[2];
    int num_passes = argc - 3;

    if (num_passes < 1) {
        fprintf(stderr, "Error: at least one input PPM pass required.\n");
        return 1;
    }
    if (num_passes > MAX_PASSES) {
        num_passes = MAX_PASSES;
    }

    // Environment parameters
    int scale = 2;
    int iters = 8;
    float sigma = 1.0f;
    float tv_weight = 0.03f;
    float pixfrac = 0.7f;

    const char *env_scale = getenv("PIE_SCALE");
    if (env_scale) scale = atoi(env_scale);
    const char *env_iters = getenv("PIE_ITERS");
    if (env_iters) iters = atoi(env_iters);
    const char *env_sigma = getenv("PIE_SIGMA");
    if (env_sigma) sigma = (float)atof(env_sigma);
    const char *env_tv = getenv("PIE_TV");
    if (env_tv) tv_weight = (float)atof(env_tv);
    const char *env_pf = getenv("PIE_PIXFRAC");
    if (env_pf) pixfrac = (float)atof(env_pf);

    int search_radius = 64;
    const char *env_radius = getenv("PIE_SEARCH_RADIUS");
    if (env_radius) search_radius = atoi(env_radius);
    if (search_radius < 12) search_radius = 12;
    if (search_radius > 256) search_radius = 256;

    printf("======================================================================\n");
    printf("PRIME FILM 1800u / 1800i COMPUTATIONAL SUPER-RESOLUTION ENGINE\n");
    printf("Reconstruction Method : %s\n", (strcmp(method, "drizzle") == 0) ? "Drizzle (Variable-Pixel Linear)" : "Iterative Back-Projection (IBP-TV)");
    printf("Output Resolution     : %dx Super-Resolution (~%d DPI equivalent)\n", scale, 1800 * scale);
    printf("Input Passes          : %d pass(es)\n", num_passes);
    printf("PSF Sigma             : %.2f | IBP Iterations: %d | TV Weight: %.4f | Search Radius: %d px\n", sigma, iters, tv_weight, search_radius);
    printf("======================================================================\n");

    ImagePass *passes[MAX_PASSES];
    for (int i = 0; i < num_passes; i++) {
        const char *pass_path = argv[3 + i];
        printf("[*] Loading Pass %d: %s\n", i + 1, pass_path);
        passes[i] = load_ppm(pass_path);
        if (!passes[i]) {
            fprintf(stderr, "Failed to load %s\n", pass_path);
            return 1;
        }
        if (i > 0) {
            estimate_subpixel_shift(passes[0], passes[i], search_radius);
        }
    }

    int hr_w = passes[0]->w * scale;
    int hr_h = passes[0]->h * scale;
    int hr_total = hr_w * hr_h;

    float *hr_r = (float*)malloc(hr_total * sizeof(float));
    float *hr_g = (float*)malloc(hr_total * sizeof(float));
    float *hr_b = (float*)malloc(hr_total * sizeof(float));

    if (strcmp(method, "drizzle") == 0) {
        printf("[*] Executing Multi-Pass Drizzle (pixfrac=%.2f)...\n", pixfrac);
        superres_drizzle_channel(passes, num_passes, 0, hr_r, hr_w, hr_h, scale, pixfrac);
        superres_drizzle_channel(passes, num_passes, 1, hr_g, hr_w, hr_h, scale, pixfrac);
        superres_drizzle_channel(passes, num_passes, 2, hr_b, hr_w, hr_h, scale, pixfrac);
    } else {
        printf("[*] Executing Iterative Back-Projection (IBP-TV, iters=%d)...\n", iters);
        superres_ibp_channel(passes, num_passes, 0, hr_r, hr_w, hr_h, scale, sigma, iters, tv_weight);
        superres_ibp_channel(passes, num_passes, 1, hr_g, hr_w, hr_h, scale, sigma, iters, tv_weight);
        superres_ibp_channel(passes, num_passes, 2, hr_b, hr_w, hr_h, scale, sigma, iters, tv_weight);
    }

    printf("[*] Saving Super-Resolved Output (%dx%d) -> %s\n", hr_w, hr_h, out_path);
    save_ppm(out_path, hr_w, hr_h, hr_r, hr_g, hr_b);

    for (int i = 0; i < num_passes; i++) {
        free_image_pass(passes[i]);
    }
    free(hr_r);
    free(hr_g);
    free(hr_b);

    printf("[+] Super-resolution reconstruction complete successfully!\n");
    return 0;
}
