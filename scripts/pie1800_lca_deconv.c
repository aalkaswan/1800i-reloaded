/**
 * Pacific Image PrimeFilm 1800u / 1800i (05e3:0120)
 * Spatially-Varying PSF Modeling, Radial Lateral Chromatic Aberration (LCA) Correction,
 * and Cross-Channel Gradient Guided Richardson-Lucy Optical Deconvolution Engine.
 *
 * (scripts/pie1800_lca_deconv.c)
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <stdint.h>
#include <time.h>
#ifdef _OPENMP
#include <omp.h>
#endif

#define MAX_KERNEL_RADIUS 10
#define KERNEL_SPAN (2 * MAX_KERNEL_RADIUS + 1)

typedef struct {
    int enable_lca;            // 1 = perform subpixel LCA registration before deconv
    int auto_lca;              // 1 = measure & fit empirical LCA from image gradients
    float lca_kr0;             // Red subpixel sampling offset (default: +0.50)
    float lca_kr1;             // Red radial coefficient k1 (default: +0.08)
    float lca_kr3;             // Red radial coefficient k3 (default: +0.04)
    float lca_kb0;             // Blue subpixel sampling offset (default: +0.50)
    float lca_kb1;             // Blue radial coefficient k1 (default: -0.06)
    float lca_kb3;             // Blue radial coefficient k3 (default: -0.03)

    float sigma_g_center;      // Green PSF sigma at optical center x=1350 (default: 1.20)
    float alpha_g;             // Green PSF radial expansion factor (default: 0.35)

    float sigma_r_center;      // Red PSF sigma at optical center (default: 1.25)
    float alpha_r;             // Red PSF radial expansion factor (default: 0.40)

    float sigma_b_center;      // Blue PSF sigma at optical center (default: 1.30)
    float alpha_b;             // Blue PSF radial expansion factor (default: 0.45)

    int iterations;            // Richardson-Lucy iteration count (default: 8)
    int enable_guided;         // 1 = use Green channel gradient prior for Red & Blue
    float guided_tau;          // Edge sensitivity threshold (default: 6.0)
    float guided_strength;     // Regularization prior strength in flat areas (default: 0.80)
} DeconvOptions;

static void get_default_options(DeconvOptions *opts) {
    opts->enable_lca = 1;
    opts->auto_lca = 1;
    opts->lca_kr0 = 0.50f;
    opts->lca_kr1 = 0.05f;
    opts->lca_kr3 = 0.02f;
    opts->lca_kb0 = 0.50f;
    opts->lca_kb1 = -0.05f;
    opts->lca_kb3 = -0.02f;

    opts->sigma_g_center = 1.20f;
    opts->alpha_g = 0.35f;

    opts->sigma_r_center = 1.25f;
    opts->alpha_r = 0.40f;

    opts->sigma_b_center = 1.30f;
    opts->alpha_b = 0.45f;

    opts->iterations = 8;
    opts->enable_guided = 1;
    opts->guided_tau = 6.0f;
    opts->guided_strength = 0.80f;
}

/**
 * Solve a 3x3 linear system A * X = B using Cramer's Rule.
 */
static int solve_3x3(const double A[3][3], const double B[3], double X[3]) {
    double det = A[0][0] * (A[1][1] * A[2][2] - A[1][2] * A[2][1])
               - A[0][1] * (A[1][0] * A[2][2] - A[1][2] * A[2][0])
               + A[0][2] * (A[1][0] * A[2][1] - A[1][1] * A[2][0]);

    if (fabs(det) < 1e-12) {
        X[0] = 0; X[1] = 0; X[2] = 0;
        return -1;
    }

    double inv_det = 1.0 / det;
    for (int i = 0; i < 3; i++) {
        double M[3][3];
        for (int r = 0; r < 3; r++) {
            for (int c = 0; c < 3; c++) {
                M[r][c] = (c == i) ? B[r] : A[r][c];
            }
        }
        double d = M[0][0] * (M[1][1] * M[2][2] - M[1][2] * M[2][1])
                 - M[0][1] * (M[1][0] * M[2][2] - M[1][2] * M[2][0])
                 + M[0][2] * (M[1][0] * M[2][1] - M[1][1] * M[2][0]);
        X[i] = d * inv_det;
    }
    return 0;
}

/**
 * Precompute spatially-varying 1D Gaussian kernels for each column x.
 * sigma(x) = sigma_center + alpha * ((x - x_mid) / x_mid)^2
 */
static void build_sv_kernels(float sigma_center, float alpha, int w,
                             float *kernels, int *rads) {
    float x_mid = (float)(w - 1) * 0.5f;
    if (x_mid < 1.0f) x_mid = 1.0f;

    for (int x = 0; x < w; x++) {
        float r_norm = (float)(x - x_mid) / x_mid;
        float sigma = sigma_center + alpha * (r_norm * r_norm);
        if (sigma < 0.5f) sigma = 0.5f;

        int r = (int)ceilf(sigma * 3.0f);
        if (r < 1) r = 1;
        if (r > MAX_KERNEL_RADIUS) r = MAX_KERNEL_RADIUS;
        rads[x] = r;

        float *kptr = &kernels[x * KERNEL_SPAN];
        float sum = 0.0f;
        for (int k = -r; k <= r; k++) {
            float v = expf(-(float)(k * k) / (2.0f * sigma * sigma));
            kptr[k + MAX_KERNEL_RADIUS] = v;
            sum += v;
        }
        for (int k = -r; k <= r; k++) {
            kptr[k + MAX_KERNEL_RADIUS] /= sum;
        }
    }
}

/**
 * Forward Spatially-Varying Separable Blur:
 * K f(x, y)
 */
static void sv_blur_forward(const float *src, float *dst, int w, int h,
                            const float *kernels, const int *rads) {
    float *temp = (float*)malloc(w * h * sizeof(float));
    if (!temp) return;

    // Horizontal pass: each column x applies its local kernel
    #pragma omp parallel for schedule(static)
    for (int y = 0; y < h; y++) {
        int row = y * w;
        for (int x = 0; x < w; x++) {
            int r = rads[x];
            const float *kptr = &kernels[x * KERNEL_SPAN];
            float sum = 0.0f;
            for (int k = -r; k <= r; k++) {
                int px = x + k;
                if (px < 0) px = 0;
                else if (px >= w) px = w - 1;
                sum += src[row + px] * kptr[k + MAX_KERNEL_RADIUS];
            }
            temp[row + x] = sum;
        }
    }

    // Vertical pass: column x applies vertical blur of width sigma(x)
    #pragma omp parallel for schedule(static)
    for (int y = 0; y < h; y++) {
        for (int x = 0; x < w; x++) {
            int r = rads[x];
            const float *kptr = &kernels[x * KERNEL_SPAN];
            float sum = 0.0f;
            for (int k = -r; k <= r; k++) {
                int py = y + k;
                if (py < 0) py = 0;
                else if (py >= h) py = h - 1;
                sum += temp[py * w + x] * kptr[k + MAX_KERNEL_RADIUS];
            }
            dst[y * w + x] = sum;
        }
    }

    free(temp);
}

/**
 * Adjoint Spatially-Varying Separable Blur:
 * K^T v(x, y)
 */
static void sv_blur_adjoint(const float *src, float *dst, int w, int h,
                            const float *kernels, const int *rads) {
    float *temp = (float*)malloc(w * h * sizeof(float));
    if (!temp) return;

    // Vertical adjoint pass (symmetric in y)
    #pragma omp parallel for schedule(static)
    for (int y = 0; y < h; y++) {
        for (int x = 0; x < w; x++) {
            int r = rads[x];
            const float *kptr = &kernels[x * KERNEL_SPAN];
            float sum = 0.0f;
            for (int k = -r; k <= r; k++) {
                int py = y + k;
                if (py < 0) py = 0;
                else if (py >= h) py = h - 1;
                sum += src[py * w + x] * kptr[k + MAX_KERNEL_RADIUS];
            }
            temp[y * w + x] = sum;
        }
    }

    // Horizontal adjoint pass: (K_x^T temp)(x) = sum_k temp(x + k) * kernel[x + k][-k]
    #pragma omp parallel for schedule(static)
    for (int y = 0; y < h; y++) {
        int row = y * w;
        for (int x = 0; x < w; x++) {
            float sum = 0.0f;
            for (int k = -MAX_KERNEL_RADIUS; k <= MAX_KERNEL_RADIUS; k++) {
                int px = x + k;
                if (px < 0 || px >= w) continue;
                int r = rads[px];
                if (abs(k) <= r) {
                    const float *kptr = &kernels[px * KERNEL_SPAN];
                    sum += temp[row + px] * kptr[-k + MAX_KERNEL_RADIUS];
                }
            }
            dst[row + x] = sum;
        }
    }

    free(temp);
}

/**
 * Sub-Pixel Bicubic Catmull-Rom Warping along horizontal line.
 * dst(x, y) = src(x + shift_table[x], y)
 */
static void warp_subpixel_bicubic(const float *src, float *dst, int w, int h,
                                  const float *shift_table) {
    #pragma omp parallel for schedule(static)
    for (int y = 0; y < h; y++) {
        int row = y * w;
        for (int x = 0; x < w; x++) {
            float shift = shift_table[x];
            float fx = (float)x + shift;
            int ix = (int)floorf(fx);
            float u = fx - (float)ix;

            // Catmull-Rom cubic spline weights
            float u2 = u * u;
            float u3 = u2 * u;
            float w_m1 = -0.5f * u3 + u2 - 0.5f * u;
            float w_0  =  1.5f * u3 - 2.5f * u2 + 1.0f;
            float w_1  = -1.5f * u3 + 2.0f * u2 + 0.5f * u;
            float w_2  =  0.5f * u3 - 0.5f * u2;

            int x_m1 = ix - 1;
            int x_0  = ix;
            int x_1  = ix + 1;
            int x_2  = ix + 2;

            if (x_m1 < 0) x_m1 = 0;
            if (x_0 < 0)  x_0 = 0;
            if (x_1 >= w) x_1 = w - 1;
            if (x_2 >= w) x_2 = w - 1;
            if (x_0 >= w) x_0 = w - 1;
            if (x_m1 >= w) x_m1 = w - 1;

            float val = w_m1 * src[row + x_m1]
                      + w_0  * src[row + x_0]
                      + w_1  * src[row + x_1]
                      + w_2  * src[row + x_2];

            if (val < 0.0f) val = 0.0f;
            else if (val > 255.0f) val = 255.0f;
            dst[row + x] = val;
        }
    }
}

/**
 * Measure empirical Lateral Chromatic Aberration (LCA) and CCD sampling phase
 * across the sensor aperture by evaluating subpixel gradient normalized cross-correlation.
 * Fits: shift(r) = k0 + k1 * r + k3 * r^3
 */
static void auto_profile_lca(const float *chan_r, const float *chan_g, const float *chan_b,
                             int w, int h,
                             float *shift_table_r, float *shift_table_b,
                             float *out_kr0, float *out_kr1, float *out_kr3,
                             float *out_kb0, float *out_kb1, float *out_kb3) {
    float *gr = (float*)malloc(w * h * sizeof(float));
    float *gg = (float*)malloc(w * h * sizeof(float));
    float *gb = (float*)malloc(w * h * sizeof(float));
    if (!gr || !gg || !gb) return;

    #pragma omp parallel for schedule(static)
    for (int y = 0; y < h; y++) {
        int row = y * w;
        for (int x = 1; x < w - 1; x++) {
            gr[row + x] = (chan_r[row + x + 1] - chan_r[row + x - 1]) * 0.5f;
            gg[row + x] = (chan_g[row + x + 1] - chan_g[row + x - 1]) * 0.5f;
            gb[row + x] = (chan_b[row + x + 1] - chan_b[row + x - 1]) * 0.5f;
        }
        gr[row] = 0; gr[row + w - 1] = 0;
        gg[row] = 0; gg[row + w - 1] = 0;
        gb[row] = 0; gb[row + w - 1] = 0;
    }

    int nzones = 20;
    int zone_w = w / nzones;
    float x_mid = (float)(w - 1) * 0.5f;

    double r_norm[20];
    double shift_r[20];
    double shift_b[20];
    double weights_r[20];
    double weights_b[20];

    for (int z = 0; z < nzones; z++) {
        int x0 = z * zone_w;
        int x1 = (z + 1) * zone_w;
        int xc = (x0 + x1) / 2;
        r_norm[z] = (double)(xc - x_mid) / x_mid;

        double best_sr = 0.0, best_sb = 0.0;
        double max_ncc_r = -1.0, max_ncc_b = -1.0;
        int valid_edges = 0;

        // Subpixel search: -1.50 to +1.50 in 0.02 increments
        for (int s = -75; s <= 75; s++) {
            float delta = s * 0.02f;
            double sum_rg = 0, sum_rr = 0, sum_gg = 0;
            double sum_bg = 0, sum_bb = 0;
            int count = 0;

            for (int y = 10; y < h - 10; y += 2) {
                int row = y * w;
                for (int x = x0 + 6; x < x1 - 6; x += 2) {
                    float gval = gg[row + x];
                    if (fabsf(gval) < 5.0f) continue;

                    float fx = (float)x + delta;
                    int ix = (int)floorf(fx);
                    float u = fx - (float)ix;
                    if (ix < 1 || ix >= w - 2) continue;

                    float rval = (1.0f - u) * gr[row + ix] + u * gr[row + ix + 1];
                    float bval = (1.0f - u) * gb[row + ix] + u * gb[row + ix + 1];

                    sum_rg += gval * rval;
                    sum_rr += rval * rval;
                    sum_gg += gval * gval;

                    sum_bg += gval * bval;
                    sum_bb += bval * bval;
                    count++;
                }
            }

            if (count > 25 && sum_rr > 1e-4 && sum_gg > 1e-4) {
                double ncc_r = sum_rg / sqrt(sum_rr * sum_gg);
                if (ncc_r > max_ncc_r) { max_ncc_r = ncc_r; best_sr = delta; }
            }
            if (count > 25 && sum_bb > 1e-4 && sum_gg > 1e-4) {
                double ncc_b = sum_bg / sqrt(sum_bb * sum_gg);
                if (ncc_b > max_ncc_b) { max_ncc_b = ncc_b; best_sb = delta; }
            }
            if (s == 0) valid_edges = count;
        }

        shift_r[z] = best_sr;
        shift_b[z] = best_sb;
        weights_r[z] = (max_ncc_r > 0.4 && valid_edges > 20) ? (max_ncc_r * valid_edges) : 0.0;
        weights_b[z] = (max_ncc_b > 0.4 && valid_edges > 20) ? (max_ncc_b * valid_edges) : 0.0;
    }

    // Weighted least-squares fit: shift(r) = k0 + k1 * r + k3 * r^3
    double A_r[3][3] = {0}, B_r[3] = {0}, X_r[3] = {0};
    double A_b[3][3] = {0}, B_b[3] = {0}, X_b[3] = {0};

    for (int z = 0; z < nzones; z++) {
        double r = r_norm[z];
        double r2 = r * r;
        double r3 = r * r2;
        double r4 = r2 * r2;
        double r6 = r3 * r3;

        double wr = weights_r[z];
        A_r[0][0] += wr;
        A_r[0][1] += wr * r;
        A_r[0][2] += wr * r3;
        A_r[1][0] += wr * r;
        A_r[1][1] += wr * r2;
        A_r[1][2] += wr * r4;
        A_r[2][0] += wr * r3;
        A_r[2][1] += wr * r4;
        A_r[2][2] += wr * r6;

        B_r[0] += wr * shift_r[z];
        B_r[1] += wr * r * shift_r[z];
        B_r[2] += wr * r3 * shift_r[z];

        double wb = weights_b[z];
        A_b[0][0] += wb;
        A_b[0][1] += wb * r;
        A_b[0][2] += wb * r3;
        A_b[1][0] += wb * r;
        A_b[1][1] += wb * r2;
        A_b[1][2] += wb * r4;
        A_b[2][0] += wb * r3;
        A_b[2][1] += wb * r4;
        A_b[2][2] += wb * r6;

        B_b[0] += wb * shift_b[z];
        B_b[1] += wb * r * shift_b[z];
        B_b[2] += wb * r3 * shift_b[z];
    }

    solve_3x3(A_r, B_r, X_r);
    solve_3x3(A_b, B_b, X_b);

    // Safeguard limits
    if (fabs(X_r[0]) > 1.5) X_r[0] = 0.5;
    if (fabs(X_r[1]) > 1.0) X_r[1] = 0.0;
    if (fabs(X_r[2]) > 1.0) X_r[2] = 0.0;

    if (fabs(X_b[0]) > 1.5) X_b[0] = 0.5;
    if (fabs(X_b[1]) > 1.0) X_b[1] = 0.0;
    if (fabs(X_b[2]) > 1.0) X_b[2] = 0.0;

    *out_kr0 = (float)X_r[0]; *out_kr1 = (float)X_r[1]; *out_kr3 = (float)X_r[2];
    *out_kb0 = (float)X_b[0]; *out_kb1 = (float)X_b[1]; *out_kb3 = (float)X_b[2];

    // Populate continuous per-column lookup tables
    for (int x = 0; x < w; x++) {
        float r = ((float)x - x_mid) / x_mid;
        float r3 = r * r * r;
        shift_table_r[x] = (float)(X_r[0] + X_r[1] * r + X_r[2] * r3);
        shift_table_b[x] = (float)(X_b[0] + X_b[1] * r + X_b[2] * r3);
    }

    free(gr); free(gg); free(gb);
}

/**
 * Richardson-Lucy Deconvolution with Spatially-Varying Rod Lens PSF.
 */
static void richardson_lucy_single_channel_sv(float *d, int w, int h,
                                             float sigma_center, float alpha,
                                             int iterations) {
    int total = w * h;
    float *estimate   = (float*)malloc(total * sizeof(float));
    float *blurred    = (float*)malloc(total * sizeof(float));
    float *ratio      = (float*)malloc(total * sizeof(float));
    float *correction = (float*)malloc(total * sizeof(float));

    float *kernels = (float*)malloc(w * KERNEL_SPAN * sizeof(float));
    int *rads      = (int*)malloc(w * sizeof(int));

    build_sv_kernels(sigma_center, alpha, w, kernels, rads);

    memcpy(estimate, d, total * sizeof(float));

    for (int it = 0; it < iterations; it++) {
        // Step 1: Forward projection (blur current estimate by lens PSF)
        sv_blur_forward(estimate, blurred, w, h, kernels, rads);

        // Step 2: Error ratio R = D / (blurred + epsilon)
        #pragma omp parallel for schedule(static)
        for (int i = 0; i < total; i++) {
            float b = blurred[i];
            ratio[i] = (b > 1e-4f) ? (d[i] / b) : 1.0f;
        }

        // Step 3: Backward projection (adjoint blur error ratio)
        sv_blur_adjoint(ratio, correction, w, h, kernels, rads);

        // Step 4: Multiplicative update: I_{t+1} = I_t * correction
        #pragma omp parallel for schedule(static)
        for (int i = 0; i < total; i++) {
            float val = estimate[i] * correction[i];
            if (val < 0.0f) val = 0.0f;
            else if (val > 255.0f) val = 255.0f;
            estimate[i] = val;
        }
    }

    memcpy(d, estimate, total * sizeof(float));

    free(estimate);
    free(blurred);
    free(ratio);
    free(correction);
    free(kernels);
    free(rads);
}

/**
 * Cross-Channel Gradient Guided Richardson-Lucy Deconvolution for Red & Blue channels.
 * Uses the pristine deconvolved Green channel as a joint edge-preserving prior.
 */
static void richardson_lucy_guided_sv(float *d_r, float *d_b, const float *i_g,
                                      int w, int h,
                                      float sigma_r_center, float alpha_r,
                                      float sigma_b_center, float alpha_b,
                                      int iterations, float tau, float strength) {
    int total = w * h;

    // Step 1: Compute Green edge magnitude map and spatial confidence weight
    float *w_edge = (float*)malloc(total * sizeof(float));
    float tau_sq = 2.0f * tau * tau;

    #pragma omp parallel for schedule(static)
    for (int y = 0; y < h; y++) {
        int row = y * w;
        for (int x = 0; x < w; x++) {
            int x_prev = (x > 0) ? (x - 1) : 0;
            int x_next = (x < w - 1) ? (x + 1) : (w - 1);
            int y_prev = (y > 0) ? (y - 1) : 0;
            int y_next = (y < h - 1) ? (y + 1) : (h - 1);

            float gx = (i_g[row + x_next] - i_g[row + x_prev]) * 0.5f;
            float gy = (i_g[y_next * w + x] - i_g[y_prev * w + x]) * 0.5f;
            float g_mag_sq = gx * gx + gy * gy;

            // Edge confidence: 1.0 at sharp boundaries, 0.0 in smooth areas
            w_edge[row + x] = 1.0f - expf(-g_mag_sq / tau_sq);
        }
    }

    // Allocate buffers
    float *est_r   = (float*)malloc(total * sizeof(float));
    float *blur_r  = (float*)malloc(total * sizeof(float));
    float *ratio_r = (float*)malloc(total * sizeof(float));
    float *corr_r  = (float*)malloc(total * sizeof(float));
    float *color_ratio_r = (float*)malloc(total * sizeof(float));
    float *smooth_ratio_r = (float*)malloc(total * sizeof(float));

    float *est_b   = (float*)malloc(total * sizeof(float));
    float *blur_b  = (float*)malloc(total * sizeof(float));
    float *ratio_b = (float*)malloc(total * sizeof(float));
    float *corr_b  = (float*)malloc(total * sizeof(float));
    float *color_ratio_b = (float*)malloc(total * sizeof(float));
    float *smooth_ratio_b = (float*)malloc(total * sizeof(float));

    float *kernels_r = (float*)malloc(w * KERNEL_SPAN * sizeof(float));
    int *rads_r      = (int*)malloc(w * sizeof(int));
    float *kernels_b = (float*)malloc(w * KERNEL_SPAN * sizeof(float));
    int *rads_b      = (int*)malloc(w * sizeof(int));

    build_sv_kernels(sigma_r_center, alpha_r, w, kernels_r, rads_r);
    build_sv_kernels(sigma_b_center, alpha_b, w, kernels_b, rads_b);

    memcpy(est_r, d_r, total * sizeof(float));
    memcpy(est_b, d_b, total * sizeof(float));

    for (int it = 0; it < iterations; it++) {
        // Forward projections
        sv_blur_forward(est_r, blur_r, w, h, kernels_r, rads_r);
        sv_blur_forward(est_b, blur_b, w, h, kernels_b, rads_b);

        #pragma omp parallel for schedule(static)
        for (int i = 0; i < total; i++) {
            float br = blur_r[i];
            float bb = blur_b[i];
            ratio_r[i] = (br > 1e-4f) ? (d_r[i] / br) : 1.0f;
            ratio_b[i] = (bb > 1e-4f) ? (d_b[i] / bb) : 1.0f;
        }

        // Backward adjoint projections
        sv_blur_adjoint(ratio_r, corr_r, w, h, kernels_r, rads_r);
        sv_blur_adjoint(ratio_b, corr_b, w, h, kernels_b, rads_b);

        // Compute unconstrained update & color ratio relative to Green
        #pragma omp parallel for schedule(static)
        for (int i = 0; i < total; i++) {
            float vr = est_r[i] * corr_r[i];
            float vb = est_b[i] * corr_b[i];
            if (vr < 0.0f) vr = 0.0f; else if (vr > 255.0f) vr = 255.0f;
            if (vb < 0.0f) vb = 0.0f; else if (vb > 255.0f) vb = 255.0f;
            est_r[i] = vr;
            est_b[i] = vb;

            float g = i_g[i] + 1.0f;
            color_ratio_r[i] = vr / g;
            color_ratio_b[i] = vb / g;
        }

        // 3x3 box smoothing of chrominance ratio
        #pragma omp parallel for schedule(static)
        for (int y = 0; y < h; y++) {
            int y_prev = (y > 0) ? (y - 1) : 0;
            int y_next = (y < h - 1) ? (y + 1) : (h - 1);
            for (int x = 0; x < w; x++) {
                int x_prev = (x > 0) ? (x - 1) : 0;
                int x_next = (x < w - 1) ? (x + 1) : (w - 1);

                float sr = 0.0f, sb = 0.0f;
                int idxs[9] = {
                    y_prev * w + x_prev, y_prev * w + x, y_prev * w + x_next,
                    y * w + x_prev,      y * w + x,      y * w + x_next,
                    y_next * w + x_prev, y_next * w + x, y_next * w + x_next
                };
                for (int k = 0; k < 9; k++) {
                    sr += color_ratio_r[idxs[k]];
                    sb += color_ratio_b[idxs[k]];
                }
                smooth_ratio_r[y * w + x] = sr * (1.0f / 9.0f);
                smooth_ratio_b[y * w + x] = sb * (1.0f / 9.0f);
            }
        }

        // Cross-channel regularized blend:
        // At edges (w_edge ~ 1): full optical deconvolution
        // In flat areas (w_edge ~ 0): guided ratio preserves pristine Green luminance without color noise
        #pragma omp parallel for schedule(static)
        for (int i = 0; i < total; i++) {
            float w_e = w_edge[i];
            float g = i_g[i] + 1.0f;

            float guided_r = smooth_ratio_r[i] * g;
            float guided_b = smooth_ratio_b[i] * g;

            float blend_weight = strength * (1.0f - w_e);
            float final_r = (1.0f - blend_weight) * est_r[i] + blend_weight * guided_r;
            float final_b = (1.0f - blend_weight) * est_b[i] + blend_weight * guided_b;

            if (final_r < 0.0f) final_r = 0.0f; else if (final_r > 255.0f) final_r = 255.0f;
            if (final_b < 0.0f) final_b = 0.0f; else if (final_b > 255.0f) final_b = 255.0f;

            est_r[i] = final_r;
            est_b[i] = final_b;
        }
    }

    memcpy(d_r, est_r, total * sizeof(float));
    memcpy(d_b, est_b, total * sizeof(float));

    free(w_edge);
    free(est_r); free(blur_r); free(ratio_r); free(corr_r);
    free(color_ratio_r); free(smooth_ratio_r);
    free(est_b); free(blur_b); free(ratio_b); free(corr_b);
    free(color_ratio_b); free(smooth_ratio_b);
    free(kernels_r); free(rads_r);
    free(kernels_b); free(rads_b);
}

/**
 * Public C API: Spatially-Varying Richardson-Lucy Deconvolution with LCA & Guidance.
 */
int deconvolve_lca_rgb24(const uint8_t *rgb_in, uint8_t *rgb_out, int w, int h,
                         const DeconvOptions *opts) {
    if (!rgb_in || !rgb_out || w <= 0 || h <= 0) return -1;

    DeconvOptions opt;
    if (opts) memcpy(&opt, opts, sizeof(DeconvOptions));
    else get_default_options(&opt);

    int total = w * h;
    float *chan_r = (float*)malloc(total * sizeof(float));
    float *chan_g = (float*)malloc(total * sizeof(float));
    float *chan_b = (float*)malloc(total * sizeof(float));
    if (!chan_r || !chan_g || !chan_b) return -2;

    #pragma omp parallel for schedule(static)
    for (int i = 0; i < total; i++) {
        chan_r[i] = (float)rgb_in[i * 3 + 0];
        chan_g[i] = (float)rgb_in[i * 3 + 1];
        chan_b[i] = (float)rgb_in[i * 3 + 2];
    }

    // --- STAGE 1: Lateral Chromatic Aberration Registration ---
    if (opt.enable_lca) {
        float *shift_r = (float*)malloc(w * sizeof(float));
        float *shift_b = (float*)malloc(w * sizeof(float));
        float kr0 = opt.lca_kr0, kr1 = opt.lca_kr1, kr3 = opt.lca_kr3;
        float kb0 = opt.lca_kb0, kb1 = opt.lca_kb1, kb3 = opt.lca_kb3;

        if (opt.auto_lca) {
            auto_profile_lca(chan_r, chan_g, chan_b, w, h, shift_r, shift_b,
                             &kr0, &kr1, &kr3, &kb0, &kb1, &kb3);
            printf("[*] Auto-calibrated LCA: Red (k0=%+0.3f, k1=%+0.3f, k3=%+0.3f), Blue (k0=%+0.3f, k1=%+0.3f, k3=%+0.3f)\n",
                   kr0, kr1, kr3, kb0, kb1, kb3);
        } else {
            float x_mid = (float)(w - 1) * 0.5f;
            for (int x = 0; x < w; x++) {
                float r = ((float)x - x_mid) / x_mid;
                float r3 = r * r * r;
                shift_r[x] = kr0 + kr1 * r + kr3 * r3;
                shift_b[x] = kb0 + kb1 * r + kb3 * r3;
            }
        }

        // Subpixel bicubic warp Red and Blue to align with Green
        float *warped_r = (float*)malloc(total * sizeof(float));
        float *warped_b = (float*)malloc(total * sizeof(float));

        warp_subpixel_bicubic(chan_r, warped_r, w, h, shift_r);
        warp_subpixel_bicubic(chan_b, warped_b, w, h, shift_b);

        memcpy(chan_r, warped_r, total * sizeof(float));
        memcpy(chan_b, warped_b, total * sizeof(float));

        free(shift_r); free(shift_b);
        free(warped_r); free(warped_b);
    }

    // --- STAGE 2: Spatially-Varying Richardson-Lucy Deconvolution ---
    // Deconvolve Green reference channel first
    richardson_lucy_single_channel_sv(chan_g, w, h,
                                      opt.sigma_g_center, opt.alpha_g,
                                      opt.iterations);

    // Deconvolve Red and Blue channels
    if (opt.enable_guided) {
        // Guided Richardson-Lucy with Green edge prior
        richardson_lucy_guided_sv(chan_r, chan_b, chan_g, w, h,
                                  opt.sigma_r_center, opt.alpha_r,
                                  opt.sigma_b_center, opt.alpha_b,
                                  opt.iterations, opt.guided_tau, opt.guided_strength);
    } else {
        // Independent Spatially-Varying Richardson-Lucy
        richardson_lucy_single_channel_sv(chan_r, w, h,
                                          opt.sigma_r_center, opt.alpha_r,
                                          opt.iterations);
        richardson_lucy_single_channel_sv(chan_b, w, h,
                                          opt.sigma_b_center, opt.alpha_b,
                                          opt.iterations);
    }

    // Repack RGB24
    #pragma omp parallel for schedule(static)
    for (int i = 0; i < total; i++) {
        int r = (int)(chan_r[i] + 0.5f);
        int g = (int)(chan_g[i] + 0.5f);
        int b = (int)(chan_b[i] + 0.5f);
        rgb_out[i * 3 + 0] = (uint8_t)(r < 0 ? 0 : (r > 255 ? 255 : r));
        rgb_out[i * 3 + 1] = (uint8_t)(g < 0 ? 0 : (g > 255 ? 255 : g));
        rgb_out[i * 3 + 2] = (uint8_t)(b < 0 ? 0 : (b > 255 ? 255 : b));
    }

    free(chan_r);
    free(chan_g);
    free(chan_b);
    return 0;
}

/**
 * Standalone CLI application for batch processing PPM files.
 */
int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr,
            "PrimeFilm 1800u / 1800i Spatially-Varying LCA & Guided Deconvolution Engine\n"
            "Usage: %s <input.ppm> <output.ppm> [options]\n\n"
            "Options:\n"
            "  --iters <n>              RL iterations (default: 8)\n"
            "  --sigma-g <c> <a>        Green center sigma and alpha (default: 1.20 0.35)\n"
            "  --sigma-r <c> <a>        Red center sigma and alpha (default: 1.25 0.40)\n"
            "  --sigma-b <c> <a>        Blue center sigma and alpha (default: 1.30 0.45)\n"
            "  --no-lca                 Disable Lateral Chromatic Aberration registration\n"
            "  --no-auto-lca            Use manual LCA coefficients instead of auto fit\n"
            "  --lca-kr <k0> <k1> <k3>  Manual Red LCA radial coefficients\n"
            "  --lca-kb <k0> <k1> <k3>  Manual Blue LCA radial coefficients\n"
            "  --no-guided              Disable Green gradient guidance\n"
            "  --guided-tau <val>       Edge sensitivity threshold (default: 6.0)\n"
            "  --guided-strength <v>    Guidance regularization strength (default: 0.80)\n",
            argv[0]);
        return 1;
    }

    const char *in_path = argv[1];
    const char *out_path = argv[2];

    DeconvOptions opts;
    get_default_options(&opts);

    for (int i = 3; i < argc; i++) {
        if (strcmp(argv[i], "--iters") == 0 && i + 1 < argc) {
            opts.iterations = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--sigma-g") == 0 && i + 2 < argc) {
            opts.sigma_g_center = (float)atof(argv[++i]);
            opts.alpha_g = (float)atof(argv[++i]);
        } else if (strcmp(argv[i], "--sigma-r") == 0 && i + 2 < argc) {
            opts.sigma_r_center = (float)atof(argv[++i]);
            opts.alpha_r = (float)atof(argv[++i]);
        } else if (strcmp(argv[i], "--sigma-b") == 0 && i + 2 < argc) {
            opts.sigma_b_center = (float)atof(argv[++i]);
            opts.alpha_b = (float)atof(argv[++i]);
        } else if (strcmp(argv[i], "--no-lca") == 0) {
            opts.enable_lca = 0;
        } else if (strcmp(argv[i], "--no-auto-lca") == 0) {
            opts.auto_lca = 0;
        } else if (strcmp(argv[i], "--lca-kr") == 0 && i + 3 < argc) {
            opts.lca_kr0 = (float)atof(argv[++i]);
            opts.lca_kr1 = (float)atof(argv[++i]);
            opts.lca_kr3 = (float)atof(argv[++i]);
        } else if (strcmp(argv[i], "--lca-kb") == 0 && i + 3 < argc) {
            opts.lca_kb0 = (float)atof(argv[++i]);
            opts.lca_kb1 = (float)atof(argv[++i]);
            opts.lca_kb3 = (float)atof(argv[++i]);
        } else if (strcmp(argv[i], "--no-guided") == 0) {
            opts.enable_guided = 0;
        } else if (strcmp(argv[i], "--guided-tau") == 0 && i + 1 < argc) {
            opts.guided_tau = (float)atof(argv[++i]);
        } else if (strcmp(argv[i], "--guided-strength") == 0 && i + 1 < argc) {
            opts.guided_strength = (float)atof(argv[++i]);
        }
    }

    FILE *fin = fopen(in_path, "rb");
    if (!fin) {
        perror("Failed to open input PPM");
        return 1;
    }

    char magic[3];
    int w, h, max_val;
    if (fscanf(fin, "%2s\n%d %d\n%d\n", magic, &w, &h, &max_val) != 4 || strcmp(magic, "P6") != 0) {
        fprintf(stderr, "Error: only binary PPM (P6) supported.\n");
        fclose(fin);
        return 1;
    }

    int total_pixels = w * h;
    uint8_t *rgb_in = (uint8_t*)malloc(total_pixels * 3);
    uint8_t *rgb_out = (uint8_t*)malloc(total_pixels * 3);
    if (!rgb_in || !rgb_out) {
        fprintf(stderr, "Memory allocation failed.\n");
        fclose(fin);
        return 1;
    }

    if (fread(rgb_in, 1, total_pixels * 3, fin) != (size_t)(total_pixels * 3)) {
        fprintf(stderr, "Error reading image data.\n");
        fclose(fin);
        return 1;
    }
    fclose(fin);

    printf("[*] Input image: %s (%dx%d)\n", in_path, w, h);
    printf("[*] Spatially-varying PSF: G(%.2f+%.2fr^2), R(%.2f+%.2fr^2), B(%.2f+%.2fr^2)\n",
           opts.sigma_g_center, opts.alpha_g,
           opts.sigma_r_center, opts.alpha_r,
           opts.sigma_b_center, opts.alpha_b);
    printf("[*] LCA correction: %s | Guidance: %s (tau=%.1f, str=%.2f) | Iters: %d\n",
           opts.enable_lca ? (opts.auto_lca ? "Enabled (Auto)" : "Enabled (Manual)") : "Disabled",
           opts.enable_guided ? "Enabled" : "Disabled",
           opts.guided_tau, opts.guided_strength, opts.iterations);

#ifdef _OPENMP
    double t0 = omp_get_wtime();
#else
    clock_t t0 = clock();
#endif

    int ret = deconvolve_lca_rgb24(rgb_in, rgb_out, w, h, &opts);

#ifdef _OPENMP
    double elapsed = omp_get_wtime() - t0;
#else
    double elapsed = (double)(clock() - t0) / CLOCKS_PER_SEC;
#endif

    if (ret != 0) {
        fprintf(stderr, "Deconvolution failed with code %d\n", ret);
        return 1;
    }
    printf("[+] Deconvolution completed in %.3f seconds (wall-clock).\n", elapsed);

    FILE *fout = fopen(out_path, "wb");
    if (!fout) {
        perror("Failed to open output PPM");
        return 1;
    }
    fprintf(fout, "P6\n%d %d\n255\n", w, h);
    fwrite(rgb_out, 1, total_pixels * 3, fout);
    fclose(fout);

    printf("[+] Saved enhanced optical scan to: %s\n", out_path);

    free(rgb_in);
    free(rgb_out);
    return 0;
}
