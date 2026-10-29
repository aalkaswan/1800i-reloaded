// Decompiled from vuescan (vues/pie1.cpp)
// Supporting Pacific Image Electronics (PIE) film scanners USB module 1

#include <cstdint>
#include <cstring>

// Global functions present in vuescan binary (0x007805d0..0x00780600)
// Note: In VueScan 9.x+, PIE support was largely superseded by pie2.cpp,
// leaving stub implementations returning 0 in pie1.cpp.
int pie1_gplu(int vid, int pid) {
    (void)vid; (void)pid;
    return 0;
}

int pie1_usup(int vid, int pid) {
    // In binary: 31 c0 c3 (xor eax, eax; ret)
    (void)vid; (void)pid;
    return 0;
}

void pie1_ubcd(int a, int b, int c) {
    (void)a; (void)b; (void)c;
    // In binary: f3 c3 (repz ret)
    return;
}

int pie1_plus(int vid, int pid) {
    (void)vid; (void)pid;
    // In binary: 31 c0 c3 (xor eax, eax; ret)
    return 0;
}

#ifdef PIE1_LEGACY_SKELETON

struct PIE1_USB_T {
    int vid;
    int pid;
    int flag;
    const char* model;
};

// Reconstructed _ZL4usbd table (0x018ef240 / 0x01efa074, 9 entries)
static const PIE1_USB_T _ZL4usbd[9] = {
    { 0x05da, 0x00cd, 1, "PF1800U" },
    { 0x05e3, 0x0120, 1, "PF2700" },
    { 0x05e3, 0x0129, 1, "PF1800U" },
    { 0x1606, 0x1220, 1, "PF1800AFL" },
    { 0x1606, 0xf000, 1, "PF1800AFL" },
    { 0x2770, 0x0119, 1, "PF1800AFL" },
    { 0x2770, 0x011a, 1, "PF1800AFL" },
    { 0x2770, 0x011b, 1, "PF3600U" },
    { 0x2770, 0x011c, 1, "GT-9400" }
};

struct PIE1_T {
    int vid;
    int pid;
    int dev_idx;
    void* handle;
    int (*scsi_cb)(void*, unsigned char*, unsigned char*, int, unsigned char*);
    int status;
    int x_res;
    int y_res;
    int width;
    int height;
    int bits_per_pixel;
    int channels;
    int timeout;
};

// Probe function: checks if vid/pid is supported by pie1 table
int pie1_usup_table_match(int vid, int pid) {
    for (int i = 0; i < 9; i++) {
        if (_ZL4usbd[i].vid == vid && _ZL4usbd[i].pid == pid) {
            return 1;
        }
    }
    return 0;
}

// Scanner backend interface functions for PIE1 architecture
int pie1_open(int vid, int pid, int dev_idx, void* handle,
              int (*scsi_cb)(void*, unsigned char*, unsigned char*, int, unsigned char*),
              PIE1_T** out_dev) {
    if (!out_dev) return -1;
    PIE1_T* dev = new PIE1_T();
    std::memset(dev, 0, sizeof(PIE1_T));
    dev->vid = vid;
    dev->pid = pid;
    dev->dev_idx = dev_idx;
    dev->handle = handle;
    dev->scsi_cb = scsi_cb;
    dev->timeout = 30;
    *out_dev = dev;
    return 0;
}

int pie1_clos(PIE1_T** pdev) {
    if (!pdev || !*pdev) return 0;
    delete *pdev;
    *pdev = nullptr;
    return 0;
}

int pie1_info(PIE1_T* dev, int mode, int* x_res, int* y_res, int* max_w, int* max_h,
              int* min_x, int* min_y) {
    if (!dev) return -1;
    if (x_res) *x_res = 1800;
    if (y_res) *y_res = 1800;
    if (max_w) *max_w = 2550;
    if (max_h) *max_h = 3600;
    if (min_x) *min_x = 0;
    if (min_y) *min_y = 0;
    (void)mode;
    return 0;
}

int pie1_grdy(PIE1_T* dev, int channel) {
    (void)dev; (void)channel;
    return 1;
}

int pie1_gmsn(PIE1_T* dev) {
    (void)dev;
    return 0;
}

int pie1_gbut(PIE1_T* dev) {
    (void)dev;
    return 0;
}

int pie1_gbsn(PIE1_T* dev) {
    (void)dev;
    return 0;
}

int pie1_scan(PIE1_T* dev, int x_res, int y_res, int x_start, int y_start,
              int width, int height, int bits, int channels,
              int* out_status, void* user_data,
              int (*callback)(void*, int, int, int, int, unsigned char*)) {
    if (!dev) return -1;
    dev->x_res = x_res;
    dev->y_res = y_res;
    dev->width = width;
    dev->height = height;
    dev->bits_per_pixel = bits;
    dev->channels = channels;
    if (out_status) *out_status = 0;
    (void)user_data;
    (void)callback;
    return 0;
}

#endif // PIE1_LEGACY_SKELETON
