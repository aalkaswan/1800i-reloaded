#include "pie1800u.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>

static double get_time_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000.0 + ts.tv_nsec / 1000000.0;
}

static void save_ppm(const char *filename, int width, int height, const uint8_t *rgb) {
    FILE *f = fopen(filename, "wb");
    if (!f) {
        perror("fopen");
        return;
    }
    fprintf(f, "P6\n%d %d\n255\n", width, height);
    fwrite(rgb, 1, width * height * 3, f);
    fclose(f);
}

typedef struct {
    uint8_t *img_8bit;
    int total_lines;
    double t_start;
} cli_cb_data_t;

static int cli_line_callback(void *user_data, int line_idx, const uint16_t *line_buf) {
    cli_cb_data_t *d = (cli_cb_data_t *)user_data;
    uint8_t *line_dest = &d->img_8bit[line_idx * PIE1800_LINE_PIXELS * 3];

    // Deplanarize 14-bit ADC samples to 8-bit Interleaved RGB
    for (int x = 0; x < PIE1800_LINE_PIXELS; x++) {
        int r_s = line_buf[x] >> 2;
        int g_s = line_buf[PIE1800_LINE_PIXELS + x] >> 2;
        int b_s = line_buf[PIE1800_LINE_PIXELS * 2 + x] >> 2;

        int vr = (r_s * 255) / 4095;
        int vg = (g_s * 255) / 4095;
        int vb = (b_s * 255) / 4095;

        line_dest[x * 3 + 0] = (uint8_t)(vr > 255 ? 255 : (vr < 0 ? 0 : vr));
        line_dest[x * 3 + 1] = (uint8_t)(vg > 255 ? 255 : (vg < 0 ? 0 : vg));
        line_dest[x * 3 + 2] = (uint8_t)(vb > 255 ? 255 : (vb < 0 ? 0 : vb));
    }

    if ((line_idx + 1) % 20 == 0 || line_idx == d->total_lines - 1) {
        double elapsed = (get_time_ms() - d->t_start) / 1000.0;
        double rate = (line_idx + 1) / (elapsed > 0.001 ? elapsed : 0.001);
        printf("    Line %4d/%d acquired (%.1f lines/s)\n", line_idx + 1, d->total_lines, rate);
    }
    return 0;
}

int main(int argc, char **argv) {
    int offset = 0;
    int lines = 100;
    const char *out_name = "c_scan_preview.ppm";
    bool use_sync = false;

    if (argc > 1) lines = atoi(argv[1]);
    if (argc > 2) offset = atoi(argv[2]);
    if (argc > 3) out_name = argv[3];
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--sync") == 0) use_sync = true;
    }

    printf("======================================================================\n");
    printf("PRIME FILM 1800u / 1800i NATIVE C SCANNER CLI\n");
    printf("Mode:  %s\n", use_sync ? "SYNCHRONOUS (Legacy)" : "PIPELINED / DOUBLE-BUFFERED (Async)");
    printf("Lines: %d | Offset: %d steps | Output: %s\n", lines, offset, out_name);
    printf("======================================================================\n");

    pie1800_device_t *dev = NULL;
    printf("[*] Connecting to USB device 05e3:0120...\n");
    int ret = pie1800_open(&dev, NULL);
    if (ret < 0) {
        fprintf(stderr, "[!] Failed to open scanner (error %d). Are udev rules installed?\n", ret);
        return 1;
    }

    printf("[*] Initializing GL640USB bridge & CyberView EPP Mode 0x80...\n");
    ret = pie1800_init(dev);
    if (ret < 0) {
        fprintf(stderr, "[!] Hardware init failed (error %d)\n", ret);
        pie1800_close(dev);
        return 1;
    }
    printf("[+] Hardware initialized successfully!\n");

    printf("[*] Turning lamp ON & warming up (1.5s)...\n");
    pie1800_set_lamp(dev, true);
    usleep(1500000);

    if (offset > 0) {
        printf("[*] Advancing carriage to aperture offset (%d steps)...\n", offset);
        pie1800_move(dev, PIE1800_DIR_FORWARD, offset);
    }

    uint8_t *img_8bit = (uint8_t *)malloc(PIE1800_LINE_PIXELS * lines * 3);
    if (!img_8bit) {
        fprintf(stderr, "[!] Out of memory\n");
        pie1800_close(dev);
        return 1;
    }

    double t0 = get_time_ms();

    if (!use_sync) {
        printf("[*] Acquiring %d lines via Double-Buffered Pipelined Acquisition...\n", lines);
        cli_cb_data_t cb_data = {
            .img_8bit = img_8bit,
            .total_lines = lines,
            .t_start = t0
        };
        ret = pie1800_scan_pipelined(dev, lines, 1, cli_line_callback, &cb_data);
        if (ret < 0) {
            fprintf(stderr, "[!] Pipelined scan failed: %d\n", ret);
        }
    } else {
        printf("[*] Acquiring %d scan lines via Synchronous Mode...\n", lines);
        uint16_t *line_buf = (uint16_t *)malloc(PIE1800_LINE_BYTES);
        for (int l = 0; l < lines; l++) {
            ret = pie1800_scan_line(dev, line_buf);
            if (ret < 0) {
                fprintf(stderr, "[!] Error reading line %d: %d\n", l, ret);
                break;
            }

            uint8_t *line_dest = &img_8bit[l * PIE1800_LINE_PIXELS * 3];
            for (int x = 0; x < PIE1800_LINE_PIXELS; x++) {
                int r_s = line_buf[x] >> 2;
                int g_s = line_buf[PIE1800_LINE_PIXELS + x] >> 2;
                int b_s = line_buf[PIE1800_LINE_PIXELS * 2 + x] >> 2;

                int vr = (r_s * 255) / 4095;
                int vg = (g_s * 255) / 4095;
                int vb = (b_s * 255) / 4095;

                line_dest[x * 3 + 0] = (uint8_t)(vr > 255 ? 255 : (vr < 0 ? 0 : vr));
                line_dest[x * 3 + 1] = (uint8_t)(vg > 255 ? 255 : (vg < 0 ? 0 : vg));
                line_dest[x * 3 + 2] = (uint8_t)(vb > 255 ? 255 : (vb < 0 ? 0 : vb));
            }

            pie1800_move(dev, PIE1800_DIR_FORWARD, 1);

            if ((l + 1) % 20 == 0 || l == lines - 1) {
                double elapsed = (get_time_ms() - t0) / 1000.0;
                double rate = (l + 1) / (elapsed > 0.001 ? elapsed : 0.001);
                printf("    Line %4d/%d acquired (%.1f lines/s)\n", l + 1, lines, rate);
            }
        }
        free(line_buf);
    }

    double total_sec = (get_time_ms() - t0) / 1000.0;
    printf("[+] Acquisition finished: %d lines in %.2f seconds (%.2f lines/sec)!\n",
           lines, total_sec, lines / (total_sec > 0.001 ? total_sec : 0.001));

    printf("[*] Saving PPM image to %s...\n", out_name);
    save_ppm(out_name, PIE1800_LINE_PIXELS, lines, img_8bit);
    printf("[+] Image saved!\n");

    free(img_8bit);

    printf("[*] Returning carriage home and shutting down...\n");
    pie1800_close(dev);
    printf("[+] Done.\n");

    return 0;
}
