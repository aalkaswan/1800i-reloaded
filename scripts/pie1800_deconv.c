#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

/**
 * PrimeFilm 1800u / 1800i Optical Point Spread Function (PSF) Deconvolution
 * Restores optical lens MTF and micro-detail using iterative Richardson-Lucy deconvolution.
 */

static void gaussian_blur_channel(const float *src, float *dst, int w, int h, float sigma) {
    int radius = (int)ceilf(sigma * 3.0f);
    int ksize = radius * 2 + 1;
    float *kernel = (float*)malloc(ksize * sizeof(float));
    float sum = 0.0f;
    for (int i = -radius; i <= radius; i++) {
        float v = expf(-(float)(i * i) / (2.0f * sigma * sigma));
        kernel[i + radius] = v;
        sum += v;
    }
    for (int i = 0; i < ksize; i++) kernel[i] /= sum;

    float *temp = (float*)malloc(w * h * sizeof(float));

    // Horizontal pass
    for (int y = 0; y < h; y++) {
        int row_offset = y * w;
        for (int x = 0; x < w; x++) {
            float val = 0.0f;
            for (int k = -radius; k <= radius; k++) {
                int px = x + k;
                if (px < 0) px = 0;
                else if (px >= w) px = w - 1;
                val += src[row_offset + px] * kernel[k + radius];
            }
            temp[row_offset + x] = val;
        }
    }

    // Vertical pass
    for (int y = 0; y < h; y++) {
        for (int x = 0; x < w; x++) {
            float val = 0.0f;
            for (int k = -radius; k <= radius; k++) {
                int py = y + k;
                if (py < 0) py = 0;
                else if (py >= h) py = h - 1;
                val += temp[py * w + x] * kernel[k + radius];
            }
            dst[y * w + x] = val;
        }
    }

    free(kernel);
    free(temp);
}

static void richardson_lucy_channel(float *d, int w, int h, float sigma, int iterations) {
    int total = w * h;
    float *estimate = (float*)malloc(total * sizeof(float));
    float *blurred = (float*)malloc(total * sizeof(float));
    float *ratio = (float*)malloc(total * sizeof(float));
    float *correction = (float*)malloc(total * sizeof(float));

    // Initial estimate I_0 = D
    memcpy(estimate, d, total * sizeof(float));

    for (int it = 0; it < iterations; it++) {
        // Step 1: Forward projection (blur current estimate by lens PSF)
        gaussian_blur_channel(estimate, blurred, w, h, sigma);

        // Step 2: Error ratio R = D / (blurred + epsilon)
        for (int i = 0; i < total; i++) {
            float b = blurred[i];
            ratio[i] = (b > 1e-4f) ? (d[i] / b) : 1.0f;
        }

        // Step 3: Backward projection (blur error ratio by adjoint PSF)
        gaussian_blur_channel(ratio, correction, w, h, sigma);

        // Step 4: Multiplicative update: I_{t+1} = I_t * correction
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
}

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <input.ppm> <output.ppm> [sigma] [iterations]\n", argv[0]);
        return 1;
    }

    const char *in_path = argv[1];
    const char *out_path = argv[2];
    float sigma = (argc >= 4) ? atof(argv[3]) : 1.25f;
    int iterations = (argc >= 5) ? atoi(argv[4]) : 8;

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
    fgetc(fin); // Consume single delimiter byte after max_val

    int total_pixels = w * h;
    unsigned char *raw_rgb = (unsigned char*)malloc(total_pixels * 3);
    if (fread(raw_rgb, 1, total_pixels * 3, fin) != (size_t)(total_pixels * 3)) {
        fprintf(stderr, "Error reading pixel data.\n");
        fclose(fin);
        free(raw_rgb);
        return 1;
    }
    fclose(fin);

    printf("[*] Deconvolving %dx%d image using Richardson-Lucy (sigma=%.2f, iters=%d)...\n", w, h, sigma, iterations);

    float *chan_r = (float*)malloc(total_pixels * sizeof(float));
    float *chan_g = (float*)malloc(total_pixels * sizeof(float));
    float *chan_b = (float*)malloc(total_pixels * sizeof(float));

    for (int i = 0; i < total_pixels; i++) {
        chan_r[i] = (float)raw_rgb[i * 3 + 0];
        chan_g[i] = (float)raw_rgb[i * 3 + 1];
        chan_b[i] = (float)raw_rgb[i * 3 + 2];
    }

    richardson_lucy_channel(chan_r, w, h, sigma, iterations);
    richardson_lucy_channel(chan_g, w, h, sigma, iterations);
    richardson_lucy_channel(chan_b, w, h, sigma, iterations);

    for (int i = 0; i < total_pixels; i++) {
        int r = (int)(chan_r[i] + 0.5f);
        int g = (int)(chan_g[i] + 0.5f);
        int b = (int)(chan_b[i] + 0.5f);
        raw_rgb[i * 3 + 0] = (unsigned char)(r < 0 ? 0 : (r > 255 ? 255 : r));
        raw_rgb[i * 3 + 1] = (unsigned char)(g < 0 ? 0 : (g > 255 ? 255 : g));
        raw_rgb[i * 3 + 2] = (unsigned char)(b < 0 ? 0 : (b > 255 ? 255 : b));
    }

    FILE *fout = fopen(out_path, "wb");
    if (!fout) {
        perror("Failed to open output PPM");
        return 1;
    }
    fprintf(fout, "P6\n%d %d\n255\n", w, h);
    fwrite(raw_rgb, 1, total_pixels * 3, fout);
    fclose(fout);

    printf("[+] Successfully saved optical deconvolved PPM: %s\n", out_path);

    free(raw_rgb);
    free(chan_r);
    free(chan_g);
    free(chan_b);
    return 0;
}
