
#include <cstdint>
#include <cstddef>
#include <cassert>

#pragma pack(push, 1)

struct SEMA_T;
struct POLL_T;
struct PIE2_T;

typedef int (*pie2_scan_cb)(void*, int, int, int, int, unsigned short*);
typedef int (*pie2_scsi_cb)(void*, unsigned char*, unsigned char*, int, unsigned char*);

struct PIE2_T {
    void*       scsi_context;        // +0x00
    int       (*scsi_func)(void*, uint8_t*, uint8_t*, int, uint8_t*); // +0x04
    void*       sema;                // +0x08
    int32_t     timeout_sec;         // +0x0c
    int32_t     usbd_index;          // +0x10
    int32_t     piem_index;          // +0x14
    int32_t     flags_18;            // +0x18
    int32_t     cap_flags;           // +0x1c
    int32_t     model_id;            // +0x20
    int32_t     max_x;               // +0x24
    int32_t     max_y;               // +0x28
    int32_t     res_table[5];        // +0x2c..+0x3f
    int32_t     max_bits;            // +0x40
    int32_t     max_channels;        // +0x44
    int32_t     cap_48;              // +0x48
    uint8_t     gain[4];             // +0x4c..+0x4f
    uint8_t     offset_50;           // +0x50
    uint8_t     pad_51[3];           // +0x51..+0x53
    int32_t     step;                // +0x54
    int32_t     val_58;              // +0x58
    uint8_t     status_buf[12];      // +0x5c..+0x67
    int32_t     frames;              // +0x68
    int32_t     frame_offset;        // +0x6c
    int32_t     frame_width;         // +0x70
    int32_t     max_frames;          // +0x74
    int32_t     curr_frame;          // +0x78
    int32_t     val_7c;              // +0x7c
    int32_t     val_80;              // +0x80
    int32_t     val_84;              // +0x84
    int32_t     film_advance_speed;  // +0x88
    int32_t     state_8c;            // +0x8c
    int32_t     state_90;            // +0x90
    int32_t     cmd;                 // +0x94
    int32_t     val_98;              // +0x98
    int32_t     val_9c;              // +0x9c
    int32_t     val_a0;              // +0xa0
    int32_t     val_a4;              // +0xa4
    int32_t     val_a8;              // +0xa8
    int32_t     opt_x_start;         // +0xac
    int32_t     opt_y_start;         // +0xb0
    int32_t     opt_width;           // +0xb4
    int32_t     opt_height;          // +0xb8
    int32_t     ccd_dpi;             // +0xbc
    int32_t     scan_dpi;            // +0xc0
    int32_t     width_pixels;        // +0xc4
    int32_t     height_pixels;       // +0xc8
    int32_t     bytes_per_line;      // +0xcc
    int32_t     line_count;          // +0xd0
    int32_t     field_d4;            // +0xd4

    union {
        // Primary layout (verified from disasm_pie2_full.txt)
        struct {
            uint32_t scanline_accum[4][16384]; // +0xd8..+0x400d7
            uint16_t cal_white[4];             // +0x400d8..+0x400df
            uint16_t cal_line_buf[4][16384];   // +0x400e0..+0x600df
            uint8_t  cal_buf_pad[0x20000 - 0x10]; // +0x600e0..+0x800cf
            uint16_t cal_black[8];             // +0x800d0..+0x800df
            uint8_t  line_buf2[0x20000];       // +0x800e0..+0xa00df
            int32_t  focus_step_min;           // +0xa00e0
            int32_t  focus_step_max;           // +0xa00e4
            double   focus_metric;             // +0xa00e8
            int32_t  focus_pad[2];             // +0xa00f0..+0xa00f7
            int32_t  line_count_chan[4];       // +0xa00f8..+0xa0107
            uint8_t  status_table[124];        // +0xa0108..+0xa0183
            int32_t  cal_status;               // +0xa0184
            uint8_t  chan_buffers[0x1000000];  // +0xa0188..+0x10a0187
            int32_t  cal_stat0;                // +0x10a0188
            uint16_t cal_lut[0x4000];          // +0x10a018c..+0x10a818b
            int32_t  cal_stat1;                // +0x10a818c
            int32_t  cal_stat2;                // +0x10a8190
            uint16_t gamma_lut[256];           // +0x10a8194..+0x10a8393
        };
        // Dual representation for prompt-mentioned offsets and common engine accessors
        struct {
            uint8_t  line_buf1[0x80000];       // +0xd8..+0x800d7
            uint16_t field_800d8[4];           // +0x800d8..+0x800df
            uint8_t  scanline_buf2[0x80000];   // +0x800e0..+0x1000df
            uint8_t  field_1000e0[8];          // +0x1000e0..+0x1000e7
            int32_t  field_1000e8;             // +0x1000e8
            uint8_t  pad_to_1001c0[0xd4];      // +0x1000ec..+0x1001bf
            uint8_t  field_1001c0[8];          // +0x1001c0..+0x1001c7
            uint32_t field_1001c8;             // +0x1001c8
            uint32_t field_1001cc;             // +0x1001cc
            uint8_t  pad_to_1081cc[0x7ffc];    // +0x1001d0..+0x1081cb
            uint32_t field_1081cc[16];         // +0x1081cc..+0x10820b
            uint32_t field_10820c;             // +0x10820c
            uint8_t  pad_to_10a820c[0xfa0000 - 4]; // +0x108210..+0x10a820b
            uint32_t field_10a820c;            // +0x10a820c
            uint8_t  pad_to_10a838c[0x180 - 4];    // +0x10a8210..+0x10a838b
            uint32_t field_10a838c;            // +0x10a838c
            uint32_t field_10a8390;            // +0x10a8390
        };
        uint8_t raw_bytes[0x10a8394 - 0xd8];
    };
};

#pragma pack(pop)

static_assert(sizeof(PIE2_T) == 0x10a8394, "PIE2_T size must be 0x10a8394");
static_assert(offsetof(PIE2_T, scsi_context) == 0x00, "scsi_context offset");
static_assert(offsetof(PIE2_T, scsi_func) == 0x04, "scsi_func offset");
static_assert(offsetof(PIE2_T, sema) == 0x08, "sema offset");
static_assert(offsetof(PIE2_T, timeout_sec) == 0x0c, "timeout_sec offset");
static_assert(offsetof(PIE2_T, usbd_index) == 0x10, "usbd_index offset");
static_assert(offsetof(PIE2_T, piem_index) == 0x14, "piem_index offset");
static_assert(offsetof(PIE2_T, flags_18) == 0x18, "flags_18 offset");
static_assert(offsetof(PIE2_T, cap_flags) == 0x1c, "cap_flags offset");
static_assert(offsetof(PIE2_T, model_id) == 0x20, "model_id offset");
static_assert(offsetof(PIE2_T, max_x) == 0x24, "max_x offset");
static_assert(offsetof(PIE2_T, max_y) == 0x28, "max_y offset");
static_assert(offsetof(PIE2_T, res_table) == 0x2c, "res_table offset");
static_assert(offsetof(PIE2_T, max_bits) == 0x40, "max_bits offset");
static_assert(offsetof(PIE2_T, max_channels) == 0x44, "max_channels offset");
static_assert(offsetof(PIE2_T, cap_48) == 0x48, "cap_48 offset");
static_assert(offsetof(PIE2_T, gain) == 0x4c, "gain offset");
static_assert(offsetof(PIE2_T, offset_50) == 0x50, "offset_50 offset");
static_assert(offsetof(PIE2_T, step) == 0x54, "step offset");
static_assert(offsetof(PIE2_T, val_58) == 0x58, "val_58 offset");
static_assert(offsetof(PIE2_T, status_buf) == 0x5c, "status_buf offset");
static_assert(offsetof(PIE2_T, frames) == 0x68, "frames offset");
static_assert(offsetof(PIE2_T, frame_offset) == 0x6c, "frame_offset offset");
static_assert(offsetof(PIE2_T, frame_width) == 0x70, "frame_width offset");
static_assert(offsetof(PIE2_T, max_frames) == 0x74, "max_frames offset");
static_assert(offsetof(PIE2_T, curr_frame) == 0x78, "curr_frame offset");
static_assert(offsetof(PIE2_T, val_7c) == 0x7c, "val_7c offset");
static_assert(offsetof(PIE2_T, val_80) == 0x80, "val_80 offset");
static_assert(offsetof(PIE2_T, val_84) == 0x84, "val_84 offset");
static_assert(offsetof(PIE2_T, film_advance_speed) == 0x88, "film_advance_speed offset");
static_assert(offsetof(PIE2_T, state_8c) == 0x8c, "state_8c offset");
static_assert(offsetof(PIE2_T, state_90) == 0x90, "state_90 offset");
static_assert(offsetof(PIE2_T, cmd) == 0x94, "cmd offset");
static_assert(offsetof(PIE2_T, val_98) == 0x98, "val_98 offset");
static_assert(offsetof(PIE2_T, val_9c) == 0x9c, "val_9c offset");
static_assert(offsetof(PIE2_T, val_a0) == 0xa0, "val_a0 offset");
static_assert(offsetof(PIE2_T, val_a4) == 0xa4, "val_a4 offset");
static_assert(offsetof(PIE2_T, val_a8) == 0xa8, "val_a8 offset");
static_assert(offsetof(PIE2_T, opt_x_start) == 0xac, "opt_x_start offset");
static_assert(offsetof(PIE2_T, opt_y_start) == 0xb0, "opt_y_start offset");
static_assert(offsetof(PIE2_T, opt_width) == 0xb4, "opt_width offset");
static_assert(offsetof(PIE2_T, opt_height) == 0xb8, "opt_height offset");
static_assert(offsetof(PIE2_T, ccd_dpi) == 0xbc, "ccd_dpi offset");
static_assert(offsetof(PIE2_T, scan_dpi) == 0xc0, "scan_dpi offset");
static_assert(offsetof(PIE2_T, width_pixels) == 0xc4, "width_pixels offset");
static_assert(offsetof(PIE2_T, height_pixels) == 0xc8, "height_pixels offset");
static_assert(offsetof(PIE2_T, bytes_per_line) == 0xcc, "bytes_per_line offset");
static_assert(offsetof(PIE2_T, line_count) == 0xd0, "line_count offset");
static_assert(offsetof(PIE2_T, field_d4) == 0xd4, "field_d4 offset");
static_assert(offsetof(PIE2_T, line_buf1) == 0xd8, "line_buf1 offset");
static_assert(offsetof(PIE2_T, scanline_accum) == 0xd8, "scanline_accum offset");
static_assert(offsetof(PIE2_T, cal_white) == 0x400d8, "cal_white offset");
static_assert(offsetof(PIE2_T, cal_line_buf) == 0x400e0, "cal_line_buf offset");
static_assert(offsetof(PIE2_T, cal_black) == 0x800d0, "cal_black offset");
static_assert(offsetof(PIE2_T, field_800d8) == 0x800d8, "field_800d8 offset");
static_assert(offsetof(PIE2_T, line_buf2) == 0x800e0, "line_buf2 offset");
static_assert(offsetof(PIE2_T, scanline_buf2) == 0x800e0, "scanline_buf2 offset");
static_assert(offsetof(PIE2_T, focus_step_min) == 0xa00e0, "focus_step_min offset");
static_assert(offsetof(PIE2_T, focus_step_max) == 0xa00e4, "focus_step_max offset");
static_assert(offsetof(PIE2_T, focus_metric) == 0xa00e8, "focus_metric offset");
static_assert(offsetof(PIE2_T, line_count_chan) == 0xa00f8, "line_count_chan offset");
static_assert(offsetof(PIE2_T, status_table) == 0xa0108, "status_table offset");
static_assert(offsetof(PIE2_T, cal_status) == 0xa0184, "cal_status offset");
static_assert(offsetof(PIE2_T, chan_buffers) == 0xa0188, "chan_buffers offset");
static_assert(offsetof(PIE2_T, cal_stat0) == 0x10a0188, "cal_stat0 offset");
static_assert(offsetof(PIE2_T, cal_lut) == 0x10a018c, "cal_lut offset");
static_assert(offsetof(PIE2_T, cal_stat1) == 0x10a818c, "cal_stat1 offset");
static_assert(offsetof(PIE2_T, cal_stat2) == 0x10a8190, "cal_stat2 offset");
static_assert(offsetof(PIE2_T, gamma_lut) == 0x10a8194, "gamma_lut offset");

// Prompt listed offsets
static_assert(offsetof(PIE2_T, field_1000e0) == 0x1000e0, "field_1000e0 offset");
static_assert(offsetof(PIE2_T, field_1000e8) == 0x1000e8, "field_1000e8 offset");
static_assert(offsetof(PIE2_T, field_1001c0) == 0x1001c0, "field_1001c0 offset");
static_assert(offsetof(PIE2_T, field_1001c8) == 0x1001c8, "field_1001c8 offset");
static_assert(offsetof(PIE2_T, field_1001cc) == 0x1001cc, "field_1001cc offset");
static_assert(offsetof(PIE2_T, field_1081cc) == 0x1081cc, "field_1081cc offset");
static_assert(offsetof(PIE2_T, field_10820c) == 0x10820c, "field_10820c offset");
static_assert(offsetof(PIE2_T, field_10a820c) == 0x10a820c, "field_10a820c offset");
static_assert(offsetof(PIE2_T, field_10a838c) == 0x10a838c, "field_10a838c offset");
static_assert(offsetof(PIE2_T, field_10a8390) == 0x10a8390, "field_10a8390 offset");

int main() {
    return 0;
}
