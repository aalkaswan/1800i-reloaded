#include "pie1800u.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

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

int main(int argc, char **argv) {
    int offset = 2000;
    int lines = 100;
    const char *out_name = "c_scan_preview.ppm";

    if (argc > 1) lines = atoi(argv[1]);
    if (argc > 2) offset = atoi(argv[2]);
    if (argc > 3) out_name = argv[3];

    printf("======================================================================\n");
    printf("PRIME FILM 1800u / 1800i NATIVE C SCANNER CLI\n");
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

    uint16_t *line_buf = (uint16_t *)malloc(PIE1800_LINE_BYTES);
    uint8_t *img_8bit = (uint8_t *)malloc(PIE1800_LINE_PIXELS * lines * 3);
    if (!line_buf || !img_8bit) {
        fprintf(stderr, "[!] Out of memory\n");
        pie1800_close(dev);
        return 1;
    }

    printf("[*] Acquiring %d scan lines...\n", lines);
    for (int l = 0; l < lines; l++) {
        ret = pie1800_scan_line(dev, line_buf);
        if (ret < 0) {
            fprintf(stderr, "[!] Error reading line %d: %d\n", l, ret);
            break;
        }

        // Deplanarize 14-bit ADC samples (Planar R, G, B) to 8-bit Interleaved RGB
        uint8_t *line_dest = &img_8bit[l * PIE1800_LINE_PIXELS * 3];
        for (int x = 0; x < PIE1800_LINE_PIXELS; x++) {
            // Raw 14-bit ADC count is shifted left by 2
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
            printf("    Line %4d/%d acquired\n", l + 1, lines);
        }
    }

    printf("[*] Saving PPM image to %s...\n", out_name);
    save_ppm(out_name, PIE1800_LINE_PIXELS, lines, img_8bit);
    printf("[+] Image saved!\n");

    free(line_buf);
    free(img_8bit);

    printf("[*] Returning carriage home and shutting down...\n");
    pie1800_close(dev);
    printf("[+] Done.\n");

    return 0;
}
