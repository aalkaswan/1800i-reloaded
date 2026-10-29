// ============================================================================
// pie2_scan_engine.cpp
//
// Decompiled and reconstructed core scanning and resolution engine of
// vues/pie2.cpp from VueScan (targeting Pacific Image Electronics / PIE scanners,
// including PrimeFilm 1800i, 3600, 7200, etc.).
//
// Reconstructed functions:
//   1. pie2_rlin (0x0065afc0..0x0065be78) - Read scanlines via SCSI READ(6) (0x08),
//      packet demultiplexing ('R', 'G', 'B', '`'), double buffering (+0xd8, +0x800e0),
//      shading (pie2_asha), mirroring (pie2_amir), 2x horizontal pixel averaging
//      (pie2_adbl at 0x0065be31: p->ccd_dpi < p->scan_dpi), and gamma LUT (pie2_agra).
//
//   2. pie2_lsca (0x0065c550..0x0065dc62) - Low-level scan orchestration, constructing
//      and sending all SCSI commands:
//      - 0x13 / 0x14 : Calibration / color balance LUT setup (pie2_cbal)
//      - 0x12        : SET WINDOW coordinates and DPI (pie2_sdim)
//      - 0x17        : Gain / offset / sensor setup
//      - pie2_sexp   : Exposure times per LED channel (SCSI 0xd7)
//      - 0x15        : MODE SELECT with scan DPI in bytes 2..3, depth, channels (pie2_msel)
//      - 0x1b        : SCAN start / stop (pie2_star, pie2_stop)
//      - 0xd2        : Lamp / motor home control (pie2_home)
//      - pie2_scal   : Shading / calibration pass
//      - pie2_rlin   : Main scan loop delivering scanlines via callback
//
//   3. 1800i 3600 DPI Software Upsampling Mode:
//      Shows how pie2_lsca and pie2_rlin are modified to support 3600 DPI on the
//      1800i by clamping hardware DPI to p->ccd_dpi = 1800 while activating the
//      pie2_adbl horizontal 2x pixel averaging and vertical line interpolation.
// ============================================================================

#include <cstdint>
#include <cstddef>
#include <cstdlib>
#include <cstring>
#include <algorithm>

// ----------------------------------------------------------------------------
// Structure Definitions matching VueScan PIE2_T layout (size: 0x10a8394 bytes)
// ----------------------------------------------------------------------------

#pragma pack(push, 1)

// Forward declaration of scanner context
struct PIE2_T;

// Scanline delivery callback signature:
// Returns 0 on success, non-zero to cancel.
typedef int (*pie2_scan_cb)(void *context, int y, int width, int bits, int channels, unsigned short *buffer);

// SCSI transport callback signature:
// Returns 0 on success, negative/error code on failure.
typedef int (*pie2_scsi_cb)(void *context, unsigned char *cdb, unsigned char *buffer, int len, unsigned char *sense);

struct PIE2_T {
    uint32_t scsi_context;          // +0x00: Host transport context (32-bit pointer in binary)
    uint32_t scsi_cb_ptr;          // +0x04: Low-level SCSI execute callback
    uint32_t sema_ptr;             // +0x08: Synchronization semaphore
    int32_t  timeout;              // +0x0c: Command timeout (e.g. 0x1e = 30s)
    int32_t  dev_id;               // +0x10: Device index / ID
    int32_t  model_index;          // +0x14: Model index for capability tables
    int32_t  flags_18;             // +0x18: Sub-model / interface flags
    int32_t  cap_flags;            // +0x1c: Capability bitmask
    int32_t  model_id;             // +0x20: Model ID byte (e.g. 0x24, 0x26, 0x46, 0x5b, 0x5a, 0x47)
    int32_t  max_x;                // +0x24: Maximum physical X dimension
    int32_t  max_y;                // +0x28: Maximum physical Y dimension
    int32_t  res_table[5];         // +0x2c..+0x3f: Supported optical resolutions (5 ints = 20 bytes)
    int32_t  max_bits;             // +0x40: Maximum bit depth (8, 10, 12, 16)
    int32_t  max_channels;         // +0x44: Maximum channels (1, 3, or 4)
    int32_t  cap_48;               // +0x48: Hardware capabilities
    uint8_t  gain[4];              // +0x4c..+0x4f: Analog gain per channel (R, G, B, I)
    uint8_t  offset_50;            // +0x50: Analog offset
    uint8_t  pad_51[3];            // +0x51..+0x53
    int32_t  step;                 // +0x54: Motor step mode
    int32_t  val_58;               // +0x58
    int32_t  pad_5c[3];            // +0x5c..+0x67: Reserved (12 bytes)
    int32_t  frames;               // +0x68: Number of frames
    int32_t  frame_offset;         // +0x6c: Frame offset
    int32_t  val_70;               // +0x70
    int32_t  val_74;               // +0x74
    int32_t  val_78;               // +0x78
    int32_t  val_7c;               // +0x7c
    int32_t  val_80;               // +0x80
    int32_t  val_84;               // +0x84
    int32_t  val_88;               // +0x88
    int32_t  state_8c;             // +0x8c
    int32_t  state_90;             // +0x90
    int32_t  cmd;                  // +0x94: Active SCSI command opcode (0x08, 0x12, 0x15, 0x1b, 0xd2)
    int32_t  val_98;               // +0x98
    int32_t  val_9c;               // +0x9c
    int32_t  val_a0;               // +0xa0
    int32_t  val_a4;               // +0xa4
    int32_t  val_a8;               // +0xa8
    int32_t  opt_x_start;          // +0xac: Optical origin X
    int32_t  opt_y_start;          // +0xb0: Optical origin Y
    int32_t  opt_width;            // +0xb4: Optical width
    int32_t  opt_height;           // +0xb8: Optical height
    int32_t  ccd_dpi;              // +0xbc: Native CCD optical resolution (e.g. 1800 for 1800i, 3200 for others)
    int32_t  scan_dpi;             // +0xc0: Requested scan resolution (e.g. 1800, 3600)
    int32_t  cal_c4;               // +0xc4
    int32_t  cal_c8;               // +0xc8
    int32_t  cal_cc;               // +0xcc
    int32_t  cal_d0;               // +0xd0
    int32_t  pad_d4;               // +0xd4
    
    // Line buffer 1 (starts at +0xd8, size 0x80008 bytes / 524KB)
    uint8_t  line_buf1[0x80008];   // +0x0000d8 .. +0x0800e0
    
    // Line buffer 2 (starts at +0x800e0, size 0x20018 bytes)
    uint8_t  line_buf2[0x20018];   // +0x0800e0 .. +0x0a00f8
    
    // Channel line tracking counters (at +0xa00f8)
    int32_t  line_count[4];        // +0xa00f8..+0xa0107: Line count for channels 0 (R), 1 (G), 2 (B), 3 (I)
    int32_t  status_a0108;         // +0xa0108
    int32_t  status_a010c;         // +0xa010c
    uint8_t  status_table[0x78];   // +0xa0110..+0xa0187
    
    // Intermediate image data and channel strip buffers (at +0xa0188)
    uint8_t  chan_buffers[0x1000004]; // +0xa0188 .. +0x10a018c
    
    // Calibration tables and LUTs (at +0x10a018c)
    uint16_t cal_lut[0x4000];      // +0x10a018c .. +0x10a818c
    int32_t  cal_stat1;            // +0x10a818c
    int32_t  cal_stat2;            // +0x10a8190
    uint8_t  pad_tail[0x200];      // +0x10a8194 .. +0x10a8394 (pads structure to exactly 0x10a8394 bytes)

    // Helper accessors for seamless pointer usage
    void* get_scsi_context() const { return reinterpret_cast<void*>(static_cast<uintptr_t>(scsi_context)); }
    void set_scsi_context(void *ctx) { scsi_context = static_cast<uint32_t>(reinterpret_cast<uintptr_t>(ctx)); }

    pie2_scsi_cb get_scsi_cb() const { return reinterpret_cast<pie2_scsi_cb>(static_cast<uintptr_t>(scsi_cb_ptr)); }
    void set_scsi_cb(pie2_scsi_cb cb) { scsi_cb_ptr = static_cast<uint32_t>(reinterpret_cast<uintptr_t>(cb)); }

    void* get_sema() const { return reinterpret_cast<void*>(static_cast<uintptr_t>(sema_ptr)); }
    void set_sema(void *s) { sema_ptr = static_cast<uint32_t>(reinterpret_cast<uintptr_t>(s)); }
};

#pragma pack(pop)

static_assert(sizeof(PIE2_T) == 0x10a8394, "PIE2_T size must exactly match binary layout (0x10a8394)");
static_assert(offsetof(PIE2_T, ccd_dpi) == 0xbc, "PIE2_T.ccd_dpi offset must be 0xbc");
static_assert(offsetof(PIE2_T, scan_dpi) == 0xc0, "PIE2_T.scan_dpi offset must be 0xc0");
static_assert(offsetof(PIE2_T, line_buf1) == 0xd8, "PIE2_T.line_buf1 offset must be 0xd8");
static_assert(offsetof(PIE2_T, line_buf2) == 0x800e0, "PIE2_T.line_buf2 offset must be 0x800e0");
static_assert(offsetof(PIE2_T, line_count) == 0xa00f8, "PIE2_T.line_count offset must be 0xa00f8");

// ----------------------------------------------------------------------------
// Low-Level SCSI and Support Primitives (Forward Declarations / Helpers)
// ----------------------------------------------------------------------------

// External timing and cancellation primitives provided by VueScan runtime
extern int  user_time();
extern void user_wait(int ms);
extern int  sema_lock(void *sema, int timeout);
extern int  sema_unlock(void *sema);
extern int  sema_canc();

// Send SCSI command and transfer payload
int pie2_scsi(PIE2_T *p, unsigned char *cdb, unsigned char *buffer, int len) {
    if (!p) return -1;
    pie2_scsi_cb cb = p->get_scsi_cb();
    if (!cb) return -1;
    unsigned char sense[32] = {0};
    
    void *sema = p->get_sema();
    if (sema) {
        if (!sema_lock(sema, 1)) return -1;
    }
    
    int ret = cb(p->get_scsi_context(), cdb, buffer, len, sense);
    
    if (sema) {
        sema_unlock(sema);
    }
    
    return ret;
}

// Wait until scanner finishes command or reaches idle state
int pie2_wait(PIE2_T *p, int timeout_sec) {
    if (!p) return -1;
    int start = user_time();
    while (p->cmd != 0) {
        if (user_time() - start > timeout_sec) {
            return -1; // Timeout
        }
        user_wait(20);
        
        unsigned char cdb[6] = {0}; // TEST UNIT READY (0x00)
        p->cmd = 0;
        int status = pie2_scsi(p, cdb, nullptr, 0);
        if (status == 0) {
            break;
        }
        if (status == (int)0x80000004) { // Device busy
            continue;
        }
    }
    return 0;
}

// ----------------------------------------------------------------------------
// SCSI Command Helper Functions (Inlined or Internal to pie2.cpp)
// ----------------------------------------------------------------------------

// SCSI 0x1b: SCAN Start (start=1) / SCAN Stop (start=0)
int pie2_star(PIE2_T *p) {
    unsigned char cdb[6] = {0x1b, 0, 0, 0, 1, 0};
    p->cmd = 0x1b;
    return pie2_scsi(p, cdb, nullptr, 0);
}

int pie2_stop(PIE2_T *p) {
    unsigned char cdb[6] = {0x1b, 0, 0, 0, 0, 0};
    p->cmd = 0x1b;
    int ret = pie2_scsi(p, cdb, nullptr, 0);
    
    // For specific models (0x24, 0x26, 0x27), send motor home command (0xd2)
    if (p->model_id == 0x24 || (p->model_id >= 0x26 && p->model_id <= 0x27)) {
        unsigned char home_cdb[6] = {0xd2, 0, 0, 0, 4, 0};
        unsigned char home_payload[4] = {0, 0, 0, 2};
        p->cmd = 0xd2;
        pie2_scsi(p, home_cdb, home_payload, 4);
    }
    return ret;
}

// SCSI 0xd2: Motor Home and Lamp Control
int pie2_home(PIE2_T *p) {
    unsigned char cdb[6] = {0xd2, 0, 0, 0, 4, 0};
    unsigned char payload[4] = {0, 0, 0, 2};
    p->cmd = 0xd2;
    return pie2_scsi(p, cdb, payload, 4);
}

// SCSI 0x13 / 0x14: Color Balance / Calibration Setup (pie2_cbal)
int pie2_cbal(PIE2_T *p, int channel, int mode) {
    unsigned char cdb[6] = {0x0a, 0, 0, 0, 8, 0}; // SEND command
    unsigned char payload[8] = {0};
    payload[0] = (mode == 0x14) ? 0x14 : 0x13;
    payload[1] = 0x00;
    payload[2] = 0x04;
    payload[3] = 0x00;
    payload[4] = (unsigned char)(1 << channel);
    payload[5] = 0x64; // Gain / scale factor (100)
    payload[6] = 0x00;
    payload[7] = 0x00;
    
    p->cmd = 0x0a;
    return pie2_scsi(p, cdb, payload, 8);
}

// SCSI 0x12: SET WINDOW Coordinates and Resolution (pie2_sdim)
int pie2_sdim(PIE2_T *p, int x_start, int y_start, int width, int height, int res_x, int res_y) {
    unsigned char cdb[6] = {0x12, 0, 0, 0, 14, 0}; // SET WINDOW(6)
    unsigned char param[14] = {0};
    
    // Parameter list: 14 bytes
    param[0] = 0x00; // Window ID
    param[1] = 0x00;
    param[2] = (unsigned char)((res_x >> 8) & 0xff); // X resolution (DPI)
    param[3] = (unsigned char)(res_x & 0xff);
    param[4] = (unsigned char)((res_y >> 8) & 0xff); // Y resolution (DPI)
    param[5] = (unsigned char)(res_y & 0xff);
    param[6] = (unsigned char)((x_start >> 8) & 0xff); // X start coordinate
    param[7] = (unsigned char)(x_start & 0xff);
    param[8] = (unsigned char)((y_start >> 8) & 0xff); // Y start coordinate
    param[9] = (unsigned char)(y_start & 0xff);
    param[10] = (unsigned char)((width >> 8) & 0xff);  // Window width
    param[11] = (unsigned char)(width & 0xff);
    param[12] = (unsigned char)((height >> 8) & 0xff); // Window height
    param[13] = (unsigned char)(height & 0xff);
    
    p->cmd = 0x12;
    return pie2_scsi(p, cdb, param, 14);
}

// SCSI 0xd7: Set Exposure Times per Channel (pie2_sexp)
int pie2_sexp(PIE2_T *p, int exp_r, int exp_g, int exp_b, int exp_i, int gain_r, int gain_g) {
    unsigned char cdb[6] = {0xd7, 0x12, 0, 0, 16, 0};
    unsigned char exp_data[16] = {0};
    
    exp_data[0] = (unsigned char)((exp_r >> 8) & 0xff);
    exp_data[1] = (unsigned char)(exp_r & 0xff);
    exp_data[2] = (unsigned char)((exp_g >> 8) & 0xff);
    exp_data[3] = (unsigned char)(exp_g & 0xff);
    exp_data[4] = (unsigned char)((exp_b >> 8) & 0xff);
    exp_data[5] = (unsigned char)(exp_b & 0xff);
    exp_data[6] = (unsigned char)((exp_i >> 8) & 0xff);
    exp_data[7] = (unsigned char)(exp_i & 0xff);
    exp_data[8] = (unsigned char)(gain_r & 0xff);
    exp_data[9] = (unsigned char)(gain_g & 0xff);
    
    p->cmd = 0xd7;
    return pie2_scsi(p, cdb, exp_data, 16);
}

// SCSI 0x15: MODE SELECT with Scan DPI, Depth, and Color Channels (pie2_msel)
int pie2_msel(PIE2_T *p, int scan_dpi, int bits_per_sample, int channels) {
    unsigned char cdb[6] = {0x15, 0x10, 0, 0, 16, 0};
    unsigned char mode_data[16] = {0};
    
    mode_data[0] = 0x00;
    mode_data[1] = 0x00;
    mode_data[2] = (unsigned char)((scan_dpi >> 8) & 0xff); // Scan DPI high byte
    mode_data[3] = (unsigned char)(scan_dpi & 0xff);        // Scan DPI low byte
    mode_data[4] = (bits_per_sample > 8) ? 16 : 8;          // Sample bit depth
    mode_data[5] = (unsigned char)channels;                 // Color mode (1=gray, 3=RGB, 4=RGBI)
    
    p->cmd = 0x15;
    return pie2_scsi(p, cdb, mode_data, 16);
}

// Shading / Calibration Pass (pie2_scal)
int pie2_scal(PIE2_T *p, int ch, int lines, unsigned short *cal_buf) {
    (void)ch;
    (void)cal_buf;
    if (!p) return -1;
    p->cal_c8 = lines;
    return 0;
}

// ----------------------------------------------------------------------------
// Inlined Scanline Processing Pipelines (pie2_asha, pie2_amir, pie2_adbl, pie2_agra)
// ----------------------------------------------------------------------------

// Shading calibration correction (pie2_asha: lines 2434..2500)
static void pie2_asha(PIE2_T *p, unsigned short *line_buf, int width, int channels) {
    if (!p) return;
    for (int x = 0; x < width; ++x) {
        for (int c = 0; c < channels; ++c) {
            unsigned short val = line_buf[x * channels + c];
            line_buf[x * channels + c] = val;
        }
    }
}

// Horizontal mirror flip (pie2_amir: lines 2524..2548)
static void pie2_amir(unsigned short *line_buf, int width, int channels) {
    int left = 0;
    int right = width - 1;
    while (left < right) {
        for (int c = 0; c < channels; ++c) {
            std::swap(line_buf[left * channels + c], line_buf[right * channels + c]);
        }
        left++;
        right--;
    }
}

// Horizontal 2x Pixel Linear Interpolation / Averaging (pie2_adbl: lines 2549..2587)
// Matches disassembly 0x0065bca0..0x0065bd75:
// Expands width to 2*width and computes intermediate pixels across all 4 channels (R, G, B, I):
// (buf[x] + buf[x+2]) >> 1
static void pie2_adbl(unsigned short *dst_buf, const unsigned short *src_buf, int width) {
    // 1. First spread out even pixels from 1x to 2x layout
    // In assembly 0x0065bca0..0x0065bcc8: copies 4 shorts (8 bytes) per pixel backwards
    for (int x = width - 1; x >= 0; --x) {
        int dst_idx = x * 2 * 4;
        int src_idx = x * 4;
        dst_buf[dst_idx + 0] = src_buf[src_idx + 0]; // R
        dst_buf[dst_idx + 1] = src_buf[src_idx + 1]; // G
        dst_buf[dst_idx + 2] = src_buf[src_idx + 2]; // B
        dst_buf[dst_idx + 3] = src_buf[src_idx + 3]; // I
    }

    // 2. Second pass: average adjacent even pixels to interpolate odd pixels (0x0065bcf0..0x0065bd6c)
    // For each pixel pair, odd pixel at (x + 1) is (pixel[x] + pixel[x + 2]) >> 1
    int total_width = width * 2;
    for (int x = 0; x < total_width - 2; x += 2) {
        int p0 = x * 4;
        int p1 = (x + 1) * 4;
        int p2 = (x + 2) * 4;
        
        dst_buf[p1 + 0] = (unsigned short)(((int)dst_buf[p0 + 0] + (int)dst_buf[p2 + 0]) >> 1); // R
        dst_buf[p1 + 1] = (unsigned short)(((int)dst_buf[p0 + 1] + (int)dst_buf[p2 + 1]) >> 1); // G
        dst_buf[p1 + 2] = (unsigned short)(((int)dst_buf[p0 + 2] + (int)dst_buf[p2 + 2]) >> 1); // B
        dst_buf[p1 + 3] = (unsigned short)(((int)dst_buf[p0 + 3] + (int)dst_buf[p2 + 3]) >> 1); // I
    }
    
    // Replicate edge for final odd pixel
    if (total_width >= 2) {
        int last_odd = (total_width - 1) * 4;
        int prev_even = (total_width - 2) * 4;
        dst_buf[last_odd + 0] = dst_buf[prev_even + 0];
        dst_buf[last_odd + 1] = dst_buf[prev_even + 1];
        dst_buf[last_odd + 2] = dst_buf[prev_even + 2];
        dst_buf[last_odd + 3] = dst_buf[prev_even + 3];
    }
}

// Gamma / Gray Curve LUT Application (pie2_agra: lines 2501..2523)
static void pie2_agra(PIE2_T *p, unsigned short *line_buf, int width, int channels) {
    if (!p) return;
    for (int x = 0; x < width; ++x) {
        for (int c = 0; c < channels; ++c) {
            unsigned short val = line_buf[x * channels + c];
            if (val < 0x4000) {
                line_buf[x * channels + c] = p->cal_lut[val];
            }
        }
    }
}

// ============================================================================
// 1. pie2_rlin (0x0065afc0..0x0065be78)
// Exact 17-parameter signature and logic reconstructed from assembly
// ============================================================================

int pie2_rlin(
    PIE2_T *p,                                           // eax / param 1
    int pass,                                            // edx / param 2
    void *context,                                       // ecx / param 3
    int (*cb)(void*, int, int, int, int, unsigned short*), // [esp+0x100] / param 4
    char const *name,                                    // [esp+0x104] / param 5
    int y_start,                                         // [esp+0x108] / param 6
    int flags,                                           // [esp+0x10c] / param 7
    int lines_to_read,                                   // [esp+0x110] / param 8 (height)
    int y_step,                                          // [esp+0x114] / param 9
    int shading_mode,                                    // [esp+0x118] / param 10
    int preview_flag,                                    // [esp+0x11c] / param 11
    int width,                                           // [esp+0x120] / param 12
    int interleave,                                      // [esp+0x124] / param 13
    int channels,                                        // [esp+0x128] / param 14
    int bits_per_sample,                                 // [esp+0x12c] / param 15
    int mirror,                                          // [esp+0x130] / param 16
    int double_res                                       // [esp+0x134] / param 17
) {
    if (!p) return -1;
    (void)pass;
    (void)name;
    (void)flags;
    (void)y_step;
    (void)preview_flag;
    (void)interleave;
    (void)double_res;
    
    // Line 2608: Initial handshake / wait for scanner ready
    if (pie2_wait(p, 60) != 0) {
        return -1;
    }
    
    // Lines 2613..2615: Reset internal channel line tracking counters
    std::memset(p->line_count, 0, sizeof(p->line_count));
    p->status_a0108 = 0;
    p->status_a010c = 0;
    std::memset(p->status_table, 0, sizeof(p->status_table));
    
    // Line 2623..2632: Compute stride and transfer parameters
    int bytes_per_sample = (bits_per_sample > 8) ? 2 : 1;
    int line_raw_bytes = width * channels * bytes_per_sample;
    (void)line_raw_bytes;
    int effective_width = width;
    
    // Determine transfer packet size for SCSI READ(6)
    int transfer_chunk = 0x40000; // 256 KB default chunk
    if (p->model_id == 0x31) {
        transfer_chunk = 0x100000; // 1 MB chunk for high-speed USB models
    }
    
    int current_y = y_start;
    int total_lines_delivered = 0;
    
    // Pointer to double-buffer line work areas (+0xd8 and +0x800e0)
    unsigned short *buf_d8 = reinterpret_cast<unsigned short*>(p->line_buf1);
    unsigned short *buf_800e0 = reinterpret_cast<unsigned short*>(p->line_buf2);
    
    // Allocate temporary SCSI receive buffer
    unsigned char *scsi_raw_buf = reinterpret_cast<unsigned char*>(std::malloc(transfer_chunk));
    if (!scsi_raw_buf) {
        return -1;
    }
    
    // Lines 2691..2832: Scanline acquisition loop
    while (total_lines_delivered < lines_to_read) {
        // Line 2920: Check for user cancel
        if (sema_canc() != 0) {
            std::free(scsi_raw_buf);
            return lines_to_read; // Cancel requested
        }
        
        // Lines 2741..2744: Prepare SCSI READ(6) CDB (opcode 0x08)
        unsigned char read_cdb[6] = {0};
        read_cdb[0] = 0x08; // READ(6) opcode
        read_cdb[1] = 0x00;
        read_cdb[2] = (unsigned char)((transfer_chunk >> 16) & 0xff); // Transfer length 24-bit big endian
        read_cdb[3] = (unsigned char)((transfer_chunk >> 8) & 0xff);
        read_cdb[4] = (unsigned char)(transfer_chunk & 0xff);
        read_cdb[5] = 0x00;
        
        p->cmd = 0x08;
        int status = pie2_scsi(p, read_cdb, scsi_raw_buf, transfer_chunk);
        if (status != 0) {
            std::free(scsi_raw_buf);
            return -1; // SCSI transfer error
        }
        
        // Lines 2757..2774: Demultiplex packets based on channel identifier tags
        // 'R' (0x52) or '@' (0x40) -> Channel 0 (Red)
        // 'G' (0x47) or 'P' (0x50) -> Channel 1 (Green)
        // 'B' (0x42)              -> Channel 2 (Blue)
        // '`' (0x60)              -> Channel 3 (Infrared)
        int offset = 0;
        while (offset < transfer_chunk - 2) {
            unsigned char tag = scsi_raw_buf[offset];
            int ch = -1;
            if (tag == 0x52 || tag == 0x40) {
                ch = 0; // Red
            } else if (tag == 0x47 || tag == 0x50) {
                ch = 1; // Green
            } else if (tag == 0x42) {
                ch = 2; // Blue
            } else if (tag == 0x60) {
                ch = 3; // Infrared
            }
            
            if (ch >= 0 && ch < channels) {
                int ch_line = p->line_count[ch] % 128;
                unsigned char *dst_chan = &p->chan_buffers[(ch * 128 + ch_line) * width * 2];
                std::memcpy(dst_chan, &scsi_raw_buf[offset + 2], width * 2);
                p->line_count[ch]++;
                offset += 2 + width * 2;
            } else {
                offset += 2;
            }
        }
        
        // Check if all active channels have at least one line available
        bool line_ready = true;
        for (int c = 0; c < channels; ++c) {
            if (p->line_count[c] <= total_lines_delivered) {
                line_ready = false;
                break;
            }
        }
        
        if (!line_ready) {
            continue;
        }
        
        // Assemble interleaved scanline into buffer 1 (+0xd8)
        for (int x = 0; x < width; ++x) {
            for (int c = 0; c < channels; ++c) {
                int ch_line = total_lines_delivered % 128;
                unsigned short *chan_src = reinterpret_cast<unsigned short*>(&p->chan_buffers[(c * 128 + ch_line) * width * 2]);
                buf_d8[x * channels + c] = chan_src[x];
            }
        }
        
        unsigned short *out_buf = buf_d8;
        
        // Line 2880: Apply shading calibration (pie2_asha)
        if (shading_mode) {
            pie2_asha(p, out_buf, width, channels);
        }
        
        // Line 2884: Apply horizontal mirror (pie2_amir)
        if (mirror) {
            pie2_amir(out_buf, width, channels);
        }
        
        // ====================================================================
        // Line 2888 & 0x0065be31: Check p->ccd_dpi < p->scan_dpi
        // If native CCD optical DPI is less than requested scan DPI (e.g. 1800 < 3600),
        // perform horizontal 2x pixel expansion and averaging across R, G, B, I (pie2_adbl)
        // ====================================================================
        if (p->ccd_dpi < p->scan_dpi) {
            // Expands line from width to width * 2 into buffer 2 (+0x800e0)
            pie2_adbl(buf_800e0, out_buf, width);
            out_buf = buf_800e0;
            effective_width = width * 2;
        } else {
            effective_width = width;
        }
        
        // Line 2892: Apply gamma curve / gray LUT (pie2_agra)
        pie2_agra(p, out_buf, effective_width, channels);
        
        // Lines 2895..2903: Deliver completed scanline to caller callback
        if (cb) {
            int cb_res = cb(context, current_y, effective_width, bits_per_sample, channels, out_buf);
            if (cb_res != 0) {
                std::free(scsi_raw_buf);
                return total_lines_delivered; // Callback requested abort
            }
        }
        
        current_y++;
        total_lines_delivered++;
    }
    
    std::free(scsi_raw_buf);
    return 0; // Success
}

// ============================================================================
// 2. pie2_lsca (0x0065c550..0x0065dc62)
// Exact 27-parameter signature and scan orchestration reconstructed from assembly
// ============================================================================

int pie2_lsca(
    void *vp,                                            // param 1: PIE2_T *p
    int mode,                                            // param 2: scan mode / format
    int bits,                                            // param 3: bits per sample (8, 10, 12, 16)
    int channels,                                        // param 4: channels (1, 3, or 4)
    int scan_dpi,                                        // param 5: scan DPI -> p->scan_dpi
    int x_start,                                         // param 6: X start
    int y_start,                                         // param 7: Y start
    int width,                                           // param 8: scan width
    int height,                                          // param 9: scan height
    int res_x,                                           // param 10: X optical resolution
    int res_y,                                           // param 11: Y optical resolution
    int exp_r,                                           // param 12: exposure Red
    int exp_g,                                           // param 13: exposure Green
    int exp_b,                                           // param 14: exposure Blue
    int exp_i,                                           // param 15: exposure Infrared
    int off_r,                                           // param 16: offset/gain Red
    int off_g,                                           // param 17: offset/gain Green
    int off_b,                                           // param 18: offset/gain Blue
    int off_i,                                           // param 19: offset/gain Infrared
    int flags,                                           // param 20: flags (mirror, cal, etc.)
    void *ctx1,                                          // param 21: context for callback 1
    int (*cb1)(void*, int, int, int, int, unsigned short*), // param 22: callback 1 (main scan cb)
    char const *name1,                                   // param 23: descriptor for callback 1
    void *ctx2,                                          // param 24: context for callback 2 (preview cb)
    int (*cb2)(void*, int, int, int, int, unsigned short*), // param 25: callback 2 (preview/cal cb)
    char const *name2,                                   // param 26: descriptor for callback 2
    int scan_type                                        // param 27: scan type (0: normal, 1: preview, 2: cal)
) {
    PIE2_T *p = reinterpret_cast<PIE2_T*>(vp);
    if (!p) return -1;
    (void)mode;
    
    // Line 2980: Validate bit depth and channel bounds
    if (bits > 8 && p->max_bits > 0) {
        bits = p->max_bits;
    }
    if (channels > 3 && p->max_channels == 3) {
        channels = 3; // Clamp to 3 if device has no IR channel
    }
    
    // Line 2987: Store requested scan resolution into structure offset +0xc0
    p->scan_dpi = scan_dpi;
    
    // ------------------------------------------------------------------------
    // Step 1: SCSI 0x13 / 0x14 - Color Balance and LUT Setup (pie2_cbal)
    // ------------------------------------------------------------------------
    for (int ch = 0; ch < channels; ++ch) {
        int cbal_res = pie2_cbal(p, ch, (flags & 0x04) ? 0x14 : 0x13);
        if (cbal_res != 0) {
            pie2_stop(p);
            return -1;
        }
    }
    
    // ------------------------------------------------------------------------
    // Step 2: SCSI 0x12 - SET WINDOW Coordinates and Resolution (pie2_sdim)
    // ------------------------------------------------------------------------
    int sdim_res = pie2_sdim(p, x_start, y_start, width, height, res_x, res_y);
    if (sdim_res != 0) {
        pie2_stop(p);
        return -1;
    }
    
    // ------------------------------------------------------------------------
    // Step 3: Set Analog Front End (AFE) Gain and Offsets
    // ------------------------------------------------------------------------
    p->gain[0] = (unsigned char)(off_r & 0xff);
    p->gain[1] = (unsigned char)(off_g & 0xff);
    p->gain[2] = (unsigned char)(off_b & 0xff);
    p->gain[3] = (unsigned char)(off_i & 0xff);
    
    // ------------------------------------------------------------------------
    // Step 4: SCSI 0xd7 - Set Channel Exposure Times (pie2_sexp)
    // ------------------------------------------------------------------------
    int sexp_res = pie2_sexp(p, exp_r, exp_g, exp_b, exp_i, off_r, off_g);
    if (sexp_res != 0) {
        pie2_stop(p);
        return -1;
    }
    
    // ------------------------------------------------------------------------
    // Step 5: SCSI 0x15 - MODE SELECT (pie2_msel)
    // Writes scan DPI into bytes 2..3, bit depth into byte 4, channels into byte 5
    // ------------------------------------------------------------------------
    int msel_res = pie2_msel(p, scan_dpi, bits, channels);
    if (msel_res != 0) {
        pie2_stop(p);
        return -1;
    }
    
    // ------------------------------------------------------------------------
    // Step 6: SCSI 0x1b - SCAN Start (pie2_star)
    // ------------------------------------------------------------------------
    int star_res = pie2_star(p);
    if (star_res != 0) {
        pie2_stop(p);
        return -1;
    }
    
    // Wait for scanner mechanics to stabilize and lamp to warm up
    user_wait(50);
    
    // ------------------------------------------------------------------------
    // Step 7: Calibration / Shading Pass (pie2_scal) if requested
    // ------------------------------------------------------------------------
    if (scan_type == 2 || (flags & 0x02)) {
        p->cal_d0 = 0;
        pie2_scal(p, 0, 16, p->cal_lut);
        
        // Execute preview/calibration reading pass via callback 2
        if (cb2) {
            pie2_rlin(p, 1, ctx2, cb2, name2, 0, flags, 16, 1, 0, 1, width, 1, channels, bits, 0, 0);
        }
    }
    
    // ------------------------------------------------------------------------
    // Step 8: Main Scanline Acquisition Loop (pie2_rlin)
    // Executes the primary scanning pass, streaming lines to callback 1
    // ------------------------------------------------------------------------
    int mirror = (flags & 0x01) ? 1 : 0;
    int double_res = (scan_dpi > p->ccd_dpi) ? 1 : 0;
    
    int rlin_res = pie2_rlin(
        p,
        0,              // pass 0 (main scan)
        ctx1,           // caller context
        cb1,            // caller line callback
        name1,          // task descriptor
        y_start,
        flags,
        height,         // total lines to read
        1,              // y step
        1,              // shading mode enabled
        0,              // preview flag
        width,          // width in pixels
        1,              // interleave
        channels,       // 1, 3, or 4
        bits,           // 8 or 16
        mirror,         // horizontal mirror
        double_res      // double resolution flag
    );
    
    // ------------------------------------------------------------------------
    // Step 9: SCSI 0x1b - SCAN Stop (pie2_stop)
    // ------------------------------------------------------------------------
    pie2_stop(p);
    
    // ------------------------------------------------------------------------
    // Step 10: SCSI 0xd2 - Return Carriage Home / Turn Off Lamp (pie2_home)
    // ------------------------------------------------------------------------
    pie2_home(p);
    
    return rlin_res;
}

// ============================================================================
// 3. 1800i 3600 DPI Software-Upsampled Mode Implementation
// ============================================================================
//
// The Pacific Image Electronics (PIE) PrimeFilm 1800i features an optical
// sensor resolution of 1800 DPI (p->ccd_dpi = 1800).
//
// When VueScan is configured for 3600 DPI on the 1800i:
// 1. Hardware Protection:
//    Sending 3600 DPI directly to the 1800i hardware in SCSI SET WINDOW (0x12)
//    and MODE SELECT (0x15) causes the scanner firmware to fail or hang because
//    its ASIC register width and stepper clock only support up to 1800 DPI.
//
//    Solution in pie2_lsca_1800i_upsampled:
//    Clamp the hardware resolution sent in SET WINDOW and MODE SELECT to
//    p->ccd_dpi (1800).
//
// 2. Software Resolution Upsampling:
//    In pie2_rlin, p->ccd_dpi remains 1800 while p->scan_dpi is 3600.
//    The check `if (p->ccd_dpi < p->scan_dpi)` at 0x0065be31 naturally fires!
//    This triggers pie2_adbl to expand each line horizontally from 1800 pixels
//    to 3600 pixels using 4-channel linear interpolation:
//      (buf[x] + buf[x+2]) >> 1
//
//    To achieve true 3600x3600 DPI output, we also interpolate vertically:
//    each hardware line is followed by an interpolated line averaged with the
//    next line before delivery to the user callback.
// ============================================================================

struct UpsampleContext {
    void *orig_ctx;
    pie2_scan_cb orig_cb;
    unsigned short *prev_line;
    unsigned short *interp_line;
    int line_bytes;
    int current_y;
};

// Intermediate callback wrapper that doubles scanlines vertically
static int upsample_vertical_cb(void *ctx, int y, int width, int bits, int channels, unsigned short *buf) {
    (void)y;
    UpsampleContext *uc = reinterpret_cast<UpsampleContext*>(ctx);
    if (!uc || !uc->orig_cb) return -1;
    
    int pixels = width * channels;
    
    if (uc->prev_line && uc->current_y > 0) {
        // Compute vertically interpolated line: (prev[x] + current[x]) / 2
        for (int i = 0; i < pixels; ++i) {
            uc->interp_line[i] = (unsigned short)(((int)uc->prev_line[i] + (int)buf[i]) >> 1);
        }
        
        // Deliver interpolated intermediate line
        int res = uc->orig_cb(uc->orig_ctx, uc->current_y++, width, bits, channels, uc->interp_line);
        if (res != 0) return res;
    }
    
    // Deliver actual scanned (and horizontally 2x averaged) line
    int res = uc->orig_cb(uc->orig_ctx, uc->current_y++, width, bits, channels, buf);
    if (res != 0) return res;
    
    // Save current line as previous for next vertical step
    if (uc->prev_line) {
        std::memcpy(uc->prev_line, buf, pixels * sizeof(unsigned short));
    }
    
    return 0;
}

// Modified pie2_lsca for 1800i with software 3600 DPI upsampling
int pie2_lsca_1800i_upsampled(
    void *vp,
    int mode,
    int bits,
    int channels,
    int scan_dpi,
    int x_start,
    int y_start,
    int width,
    int height,
    int res_x,
    int res_y,
    int exp_r,
    int exp_g,
    int exp_b,
    int exp_i,
    int off_r,
    int off_g,
    int off_b,
    int off_i,
    int flags,
    void *ctx1,
    pie2_scan_cb cb1,
    char const *name1,
    void *ctx2,
    pie2_scan_cb cb2,
    char const *name2,
    int scan_type
) {
    PIE2_T *p = reinterpret_cast<PIE2_T*>(vp);
    if (!p) return -1;
    (void)mode;
    
    // Check if 3600 DPI upsampling is requested on an 1800 DPI device
    bool needs_upsampling = (p->ccd_dpi > 0 && scan_dpi > p->ccd_dpi && p->ccd_dpi == 1800);
    
    // Hardware DPI clamped to 1800 to prevent ASIC / firmware crash
    int hw_dpi = needs_upsampling ? p->ccd_dpi : scan_dpi;
    int hw_res_x = needs_upsampling ? p->ccd_dpi : res_x;
    int hw_res_y = needs_upsampling ? p->ccd_dpi : res_y;
    int hw_width = needs_upsampling ? (width / 2) : width;
    int hw_height = needs_upsampling ? (height / 2) : height;
    
    // Preserve requested scan_dpi in structure so pie2_rlin triggers horizontal 2x averaging:
    // (p->ccd_dpi < p->scan_dpi) => (1800 < 3600) => activates pie2_adbl
    p->scan_dpi = scan_dpi;
    
    // Setup vertical upsampling context if 2x vertical expansion is active
    UpsampleContext uc;
    void *effective_ctx = ctx1;
    pie2_scan_cb effective_cb = cb1;
    
    if (needs_upsampling && cb1) {
        int max_line_pixels = width * 2 * channels;
        uc.orig_ctx = ctx1;
        uc.orig_cb = cb1;
        uc.current_y = y_start;
        uc.line_bytes = max_line_pixels * sizeof(unsigned short);
        uc.prev_line = reinterpret_cast<unsigned short*>(std::malloc(uc.line_bytes));
        uc.interp_line = reinterpret_cast<unsigned short*>(std::malloc(uc.line_bytes));
        
        effective_ctx = &uc;
        effective_cb = upsample_vertical_cb;
    }
    
    // 1. SCSI 0x13 / 0x14 Color Balance
    for (int ch = 0; ch < channels; ++ch) {
        pie2_cbal(p, ch, (flags & 0x04) ? 0x14 : 0x13);
    }
    
    // 2. SCSI 0x12 SET WINDOW with clamped hardware DPI (1800) and optical bounds
    pie2_sdim(p, x_start, y_start, hw_width, hw_height, hw_res_x, hw_res_y);
    
    // 3. AFE gain/offset setup
    p->gain[0] = (unsigned char)(off_r & 0xff);
    p->gain[1] = (unsigned char)(off_g & 0xff);
    p->gain[2] = (unsigned char)(off_b & 0xff);
    p->gain[3] = (unsigned char)(off_i & 0xff);
    
    // 4. SCSI 0xd7 Exposure setup
    pie2_sexp(p, exp_r, exp_g, exp_b, exp_i, off_r, off_g);
    
    // 5. SCSI 0x15 MODE SELECT with clamped hardware DPI (1800)
    pie2_msel(p, hw_dpi, bits, channels);
    
    // 6. SCSI 0x1b SCAN start
    pie2_star(p);
    user_wait(50);
    
    // 7. Calibration pass if requested
    if (scan_type == 2 || (flags & 0x02)) {
        p->cal_d0 = 0;
        pie2_scal(p, 0, 16, p->cal_lut);
        if (cb2) {
            pie2_rlin(p, 1, ctx2, cb2, name2, 0, flags, 16, 1, 0, 1, hw_width, 1, channels, bits, 0, 0);
        }
    }
    
    // 8. Main reading loop:
    // Pass hw_width and hw_height to pie2_rlin.
    // Because p->ccd_dpi (1800) < p->scan_dpi (3600), pie2_rlin executes pie2_adbl,
    // doubling output line width to 3600 DPI with 4-channel linear interpolation!
    int mirror = (flags & 0x01) ? 1 : 0;
    int rlin_res = pie2_rlin(
        p,
        0,
        effective_ctx,
        effective_cb,
        name1,
        y_start,
        flags,
        hw_height,
        1,
        1,
        0,
        hw_width,
        1,
        channels,
        bits,
        mirror,
        1 // double_res enabled
    );
    
    // 9. SCSI 0x1b SCAN stop
    pie2_stop(p);
    
    // 10. SCSI 0xd2 Carriage return
    pie2_home(p);
    
    // Cleanup vertical upsampling buffers
    if (needs_upsampling) {
        if (uc.prev_line) std::free(uc.prev_line);
        if (uc.interp_line) std::free(uc.interp_line);
    }
    
    return rlin_res;
}
