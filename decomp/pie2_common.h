// ============================================================================
// pie2_common.h - Authoritative Layout, Declarations, and Prototypes
// Pacific Image Electronics (PIE) Scanner Architecture for VueScan
// ============================================================================

#ifndef PIE2_COMMON_H
#define PIE2_COMMON_H

#include <cstdint>
#include <cstddef>
#include <cstdlib>
#include <cstring>
#include <algorithm>

// Forward declarations for external VueScan runtime types
struct SEMA_T;
struct POLL_T;
struct PIE2_T;

// Scanline and SCSI callback signatures
typedef int (*pie2_scan_cb)(void* context, int y, int width, int bits, int channels, unsigned short* buffer);
typedef int (*pie2_scsi_cb)(void* context, unsigned char* cdb, unsigned char* buffer, int len, unsigned char* sense);

// External runtime support functions
extern "C" {
    SEMA_T*     sema_open();
    int         sema_lock(void* sema, int timeout);
    void        sema_unlk(void* sema);
    int         sema_canc();
    void        sema_clos(void** sema);

    POLL_T*     poll_open(void* context, int (*poll_func)(void*, int*));
    int         poll_lock(void* poll);
    void        poll_unlk(void* poll, int flag);
    void        poll_clos(void** poll);
    int         poll_gbut(void* poll);
    int         poll_gmed(void* poll);

    int         user_time();
    void        user_wait(int milliseconds);

    int         pie1_plus(int vendor_id, int product_id);
    int         pie1_gplu(int vendor_id, int product_id);

    const char* pied_gvnd(int model_id, int alt_flag);
    const char* pied_gmdl(int model_id, int alt_flag);

    double      gamm_gtol(double val);
}

// ----------------------------------------------------------------------------
// USB Identification and Hardware Table Types
// ----------------------------------------------------------------------------

struct USBD_T {
    int32_t model_id;
    int32_t vendor_id;
    int32_t product_id;
};
typedef USBD_T PIE_USBD;
static_assert(sizeof(USBD_T) == 12, "USBD_T must be exactly 12 bytes");

struct PIE_MODEL {
    int32_t     model_id;       // +0x00: Model code
    int32_t     field_4;        // +0x04: Capability flag
    int32_t     feeder_type;    // +0x08: 0=flatbed, 1=slide feeder, 2=filmstrip roll, 3=medium format, 4=powerfilm
    int32_t     field_c;        // +0x0c: Hardware button capability (1 = has buttons)
    int32_t     field_10;       // +0x10: Firmware protocol family (0, 1, 2, 3)
    int32_t     field_14;       // +0x14: Stepper controller type
    int32_t     field_18;       // +0x18: Sensor type
    const char* model_name;     // +0x1c: Primary marketing name
    const char* alt_name;       // +0x20: Alternate brand OEM name
};
typedef PIE_MODEL PIEM_T;
#if defined(__i386__) || defined(_M_IX86) || (defined(__SIZEOF_POINTER__) && __SIZEOF_POINTER__ == 4)
static_assert(sizeof(PIE_MODEL) == 36, "PIE_MODEL must be exactly 36 bytes on 32-bit");
#endif

// Hardware tables
extern const USBD_T _ZL4usbd[41];
extern const PIE_MODEL _ZL4piem[40];

// ----------------------------------------------------------------------------
// PIE2_T Driver Structure Definition (Size: 0x10a8394 = 17,466,260 bytes)
// ----------------------------------------------------------------------------

#pragma pack(push, 1)

struct PIE2_T {
    void*       scsi_context;        // +0x00: SCSI callback context (scsi_arg)
    int       (*scsi_func)(void*, uint8_t*, uint8_t*, int, uint8_t*); // +0x04: SCSI transport callback
    void*       sema;                // +0x08: Transport semaphore (SEMA_T*)
    int32_t     timeout_sec;         // +0x0c: Command timeout (default 0x1e = 30s)
    int32_t     usbd_index;          // +0x10: Index into _ZL4usbd mapping table (-1 if none)
    int32_t     piem_index;          // +0x14: Index into _ZL4piem capability table (-1 if none)
    int32_t     flags_18;            // +0x18: Sub-model / transport flags (is_usb)
    int32_t     cap_flags;           // +0x1c: Polling thread / capability flags (poll)
    int32_t     model_id;            // +0x20: Active PIE model ID code (e.g. 0x24, 0x26, 0x47, 0x5b)
    int32_t     max_x;               // +0x24: Maximum physical scan width in pixels
    int32_t     max_y;               // +0x28: Maximum physical scan height in scanlines
    int32_t     res_table[5];        // +0x2c..+0x3f: Optical resolution table (5 entries)
    int32_t     max_bits;            // +0x40: Maximum bit depth (8, 10, 12, 16)
    int32_t     max_channels;        // +0x44: Maximum channel count (1, 3, or 4)
    int32_t     cap_48;              // +0x48: Sensor / optical capability flags
    uint8_t     gain[4];             // +0x4c..+0x4f: Analog gain per channel (R, G, B, I)
    uint8_t     offset_50;           // +0x50: Lamp / offset status
    uint8_t     pad_51[3];           // +0x51..+0x53: Reserved padding
    int32_t     step;                // +0x54: Motor step / line distance mode
    int32_t     val_58;              // +0x58: Motor parameter setting
    uint8_t     status_buf[12];      // +0x5c..+0x67: Hardware status buffer
    int32_t     frames;              // +0x68: Number of motorized frames / feeder mode
    int32_t     frame_offset;        // +0x6c: Film frame position offset
    int32_t     frame_width;         // +0x70: Frame width in motor steps
    int32_t     max_frames;          // +0x74: Maximum frame capacity
    int32_t     curr_frame;          // +0x78: Current active frame index
    int32_t     val_7c;              // +0x7c: Transport parameter
    int32_t     val_80;              // +0x80: Transport parameter
    int32_t     val_84;              // +0x84: Transport parameter
    int32_t     film_advance_speed;  // +0x88: Motorized film advance velocity
    int32_t     state_8c;            // +0x8c: Device calibration state flag
    int32_t     state_90;            // +0x90: Front panel button pressed status
    int32_t     cmd;                 // +0x94: Active SCSI command opcode (0x08, 0x12, 0x15, 0x1b, 0xd2)
    int32_t     val_98;              // +0x98: Motor execution parameter
    int32_t     val_9c;              // +0x9c: Scan boundary parameter
    int32_t     val_a0;              // +0xa0: Scan coordinate parameter
    int32_t     val_a4;              // +0xa4: Scan coordinate parameter
    int32_t     val_a8;              // +0xa8: Scan coordinate parameter
    int32_t     opt_x_start;         // +0xac: Requested horizontal origin (dpi_x)
    int32_t     opt_y_start;         // +0xb0: Requested vertical origin (dpi_y)
    int32_t     opt_width;           // +0xb4: Output scan image width in pixels (scan_width)
    int32_t     opt_height;          // +0xb8: Output scan image height in scanlines (scan_height)
    int32_t     ccd_dpi;             // +0xbc: Native CCD optical resolution (e.g. 1800, 3200)
    int32_t     scan_dpi;            // +0xc0: Requested scan resolution
    int32_t     width_pixels;        // +0xc4: Row pixel count before interpolation (cal_c4)
    int32_t     height_pixels;       // +0xc8: Column line count before interpolation (cal_c8)
    int32_t     bytes_per_line;      // +0xcc: Unpacked byte width per line (cal_cc)
    int32_t     line_count;          // +0xd0: Active scanlines acquired (cal_d0)
    int32_t     field_d4;            // +0xd4: Scanline accumulator / buffer index (pad_d4)

    // Buffers and trailing calibration state (+0xd8 .. +0x10a8393, total 17,466,044 bytes)
    union {
        // Concrete verified layout matching all disasm_pie2_full.txt references
        struct {
            uint32_t scanline_accum[4][16384]; // +0xd8..+0x400d7 (4 channels * 16384 uint32_t = 0x40000 bytes)
            uint16_t cal_white[4];             // +0x400d8..+0x400df (4 uint16_t words = 8 bytes)
            uint16_t cal_line_buf[4][16384];   // +0x400e0..+0x600df (4 channels * 16384 uint16_t = 0x40000 bytes)
            uint8_t  cal_buf_pad[0x20000 - 0x10]; // +0x600e0..+0x800cf
            uint16_t cal_black[8];             // +0x800d0..+0x800df (8 uint16_t words = 16 bytes; +0x800d8 is cal_black[4])
            uint8_t  line_buf2[0x20000];       // +0x800e0..+0xa00df (secondary scanline buffer = 0x20000 bytes)
            int32_t  focus_step_min;           // +0xa00e0: Minimum focus search bound (0xfffffc18 = -1000)
            int32_t  focus_step_max;           // +0xa00e4: Focus iteration count / bound (0x3e8 = 1000)
            double   focus_metric;             // +0xa00e8: Best autofocus contrast metric (8-byte IEEE 754 double)
            int32_t  focus_pad[2];             // +0xa00f0..+0xa00f7: Reserved focus state
            int32_t  line_count_chan[4];       // +0xa00f8..+0xa0107: Acquired scanlines per channel [R, G, B, I]
            uint8_t  status_table[124];        // +0xa0108..+0xa0183: Shading / line status table
            int32_t  cal_status;               // +0xa0184..+0xa0187: Calibration validity status flag
            uint8_t  chan_buffers[0x1000000];  // +0xa0188..+0x10a0187: Main intermediate image buffer (16 MB)
            int32_t  cal_stat0;                // +0x10a0188..+0x10a018b: Calibration white point status
            uint16_t cal_lut[0x4000];          // +0x10a018c..+0x10a818b: Color balance / calibration LUT (16384 words)
            int32_t  cal_stat1;                // +0x10a818c..+0x10a818f: Shading dark status
            int32_t  cal_stat2;                // +0x10a8190..+0x10a8193: Shading light status
            uint16_t gamma_lut[256];           // +0x10a8194..+0x10a8393: 8-bit gamma curve LUT (256 words = 512 bytes)
        };
        // Dual representation providing all prompt-mentioned offsets and common engine accessors
        struct {
            uint8_t  line_buf1[0x80000];       // +0xd8..+0x800d7
            uint16_t field_800d8[4];           // +0x800d8..+0x800df
            uint8_t  scanline_buf2[0x80000];   // +0x800e0..+0x1000df
            uint8_t  field_1000e0[8];          // +0x1000e0..+0x1000e7
            int32_t  field_1000e8;             // +0x1000e8: focus_step alias
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

    // Accessor helpers
    void*       get_scsi_context() const { return scsi_context; }
    void        set_scsi_context(void* ctx) { scsi_context = ctx; }
    void*       get_sema() const { return sema; }
    void        set_sema(void* s) { sema = s; }
    POLL_T*     get_poll() const { return reinterpret_cast<POLL_T*>(static_cast<uintptr_t>(cap_flags)); }
    void        set_poll(POLL_T* p) { cap_flags = static_cast<int32_t>(reinterpret_cast<uintptr_t>(p)); }
};

#pragma pack(pop)

// ----------------------------------------------------------------------------
// Compile-Time Layout and Offset Assertions
// ----------------------------------------------------------------------------

static_assert(sizeof(PIE2_T) == 0x10a8394, "PIE2_T size must be exactly 0x10a8394 (17,466,260 bytes)");

// Header fields (+0x00 .. +0xd4)
static_assert(offsetof(PIE2_T, scsi_context)       == 0x00, "scsi_context offset must be 0x00");
static_assert(offsetof(PIE2_T, scsi_func)          == 0x04, "scsi_func offset must be 0x04");
static_assert(offsetof(PIE2_T, sema)               == 0x08, "sema offset must be 0x08");
static_assert(offsetof(PIE2_T, timeout_sec)        == 0x0c, "timeout_sec offset must be 0x0c");
static_assert(offsetof(PIE2_T, usbd_index)         == 0x10, "usbd_index offset must be 0x10");
static_assert(offsetof(PIE2_T, piem_index)         == 0x14, "piem_index offset must be 0x14");
static_assert(offsetof(PIE2_T, flags_18)           == 0x18, "flags_18 offset must be 0x18");
static_assert(offsetof(PIE2_T, cap_flags)          == 0x1c, "cap_flags offset must be 0x1c");
static_assert(offsetof(PIE2_T, model_id)           == 0x20, "model_id offset must be 0x20");
static_assert(offsetof(PIE2_T, max_x)              == 0x24, "max_x offset must be 0x24");
static_assert(offsetof(PIE2_T, max_y)              == 0x28, "max_y offset must be 0x28");
static_assert(offsetof(PIE2_T, res_table)          == 0x2c, "res_table offset must be 0x2c");
static_assert(offsetof(PIE2_T, max_bits)           == 0x40, "max_bits offset must be 0x40");
static_assert(offsetof(PIE2_T, max_channels)       == 0x44, "max_channels offset must be 0x44");
static_assert(offsetof(PIE2_T, cap_48)             == 0x48, "cap_48 offset must be 0x48");
static_assert(offsetof(PIE2_T, gain)               == 0x4c, "gain offset must be 0x4c");
static_assert(offsetof(PIE2_T, offset_50)          == 0x50, "offset_50 offset must be 0x50");
static_assert(offsetof(PIE2_T, pad_51)             == 0x51, "pad_51 offset must be 0x51");
static_assert(offsetof(PIE2_T, step)               == 0x54, "step offset must be 0x54");
static_assert(offsetof(PIE2_T, val_58)             == 0x58, "val_58 offset must be 0x58");
static_assert(offsetof(PIE2_T, status_buf)         == 0x5c, "status_buf offset must be 0x5c");
static_assert(offsetof(PIE2_T, frames)             == 0x68, "frames offset must be 0x68");
static_assert(offsetof(PIE2_T, frame_offset)       == 0x6c, "frame_offset offset must be 0x6c");
static_assert(offsetof(PIE2_T, frame_width)        == 0x70, "frame_width offset must be 0x70");
static_assert(offsetof(PIE2_T, max_frames)         == 0x74, "max_frames offset must be 0x74");
static_assert(offsetof(PIE2_T, curr_frame)         == 0x78, "curr_frame offset must be 0x78");
static_assert(offsetof(PIE2_T, val_7c)             == 0x7c, "val_7c offset must be 0x7c");
static_assert(offsetof(PIE2_T, val_80)             == 0x80, "val_80 offset must be 0x80");
static_assert(offsetof(PIE2_T, val_84)             == 0x84, "val_84 offset must be 0x84");
static_assert(offsetof(PIE2_T, film_advance_speed) == 0x88, "film_advance_speed offset must be 0x88");
static_assert(offsetof(PIE2_T, state_8c)           == 0x8c, "state_8c offset must be 0x8c");
static_assert(offsetof(PIE2_T, state_90)           == 0x90, "state_90 offset must be 0x90");
static_assert(offsetof(PIE2_T, cmd)                == 0x94, "cmd offset must be 0x94");
static_assert(offsetof(PIE2_T, val_98)             == 0x98, "val_98 offset must be 0x98");
static_assert(offsetof(PIE2_T, val_9c)             == 0x9c, "val_9c offset must be 0x9c");
static_assert(offsetof(PIE2_T, val_a0)             == 0xa0, "val_a0 offset must be 0xa0");
static_assert(offsetof(PIE2_T, val_a4)             == 0xa4, "val_a4 offset must be 0xa4");
static_assert(offsetof(PIE2_T, val_a8)             == 0xa8, "val_a8 offset must be 0xa8");
static_assert(offsetof(PIE2_T, opt_x_start)        == 0xac, "opt_x_start offset must be 0xac");
static_assert(offsetof(PIE2_T, opt_y_start)        == 0xb0, "opt_y_start offset must be 0xb0");
static_assert(offsetof(PIE2_T, opt_width)          == 0xb4, "opt_width offset must be 0xb4");
static_assert(offsetof(PIE2_T, opt_height)         == 0xb8, "opt_height offset must be 0xb8");
static_assert(offsetof(PIE2_T, ccd_dpi)            == 0xbc, "ccd_dpi offset must be 0xbc");
static_assert(offsetof(PIE2_T, scan_dpi)           == 0xc0, "scan_dpi offset must be 0xc0");
static_assert(offsetof(PIE2_T, width_pixels)       == 0xc4, "width_pixels offset must be 0xc4");
static_assert(offsetof(PIE2_T, height_pixels)      == 0xc8, "height_pixels offset must be 0xc8");
static_assert(offsetof(PIE2_T, bytes_per_line)     == 0xcc, "bytes_per_line offset must be 0xcc");
static_assert(offsetof(PIE2_T, line_count)         == 0xd0, "line_count offset must be 0xd0");
static_assert(offsetof(PIE2_T, field_d4)           == 0xd4, "field_d4 offset must be 0xd4");

// Verified buffer and calibration offsets from disasm_pie2_full.txt
static_assert(offsetof(PIE2_T, scanline_accum)     == 0xd8,      "scanline_accum offset must be 0xd8");
static_assert(offsetof(PIE2_T, line_buf1)          == 0xd8,      "line_buf1 offset must be 0xd8");
static_assert(offsetof(PIE2_T, cal_white)          == 0x400d8,   "cal_white offset must be 0x400d8");
static_assert(offsetof(PIE2_T, cal_line_buf)       == 0x400e0,   "cal_line_buf offset must be 0x400e0");
static_assert(offsetof(PIE2_T, cal_black)          == 0x800d0,   "cal_black offset must be 0x800d0");
static_assert(offsetof(PIE2_T, field_800d8)        == 0x800d8,   "field_800d8 offset must be 0x800d8");
static_assert(offsetof(PIE2_T, line_buf2)          == 0x800e0,   "line_buf2 offset must be 0x800e0");
static_assert(offsetof(PIE2_T, scanline_buf2)      == 0x800e0,   "scanline_buf2 offset must be 0x800e0");
static_assert(offsetof(PIE2_T, focus_step_min)     == 0xa00e0,   "focus_step_min offset must be 0xa00e0");
static_assert(offsetof(PIE2_T, focus_step_max)     == 0xa00e4,   "focus_step_max offset must be 0xa00e4");
static_assert(offsetof(PIE2_T, focus_metric)       == 0xa00e8,   "focus_metric offset must be 0xa00e8");
static_assert(offsetof(PIE2_T, line_count_chan)    == 0xa00f8,   "line_count_chan offset must be 0xa00f8");
static_assert(offsetof(PIE2_T, status_table)       == 0xa0108,   "status_table offset must be 0xa0108");
static_assert(offsetof(PIE2_T, cal_status)         == 0xa0184,   "cal_status offset must be 0xa0184");
static_assert(offsetof(PIE2_T, chan_buffers)       == 0xa0188,   "chan_buffers offset must be 0xa0188");
static_assert(offsetof(PIE2_T, cal_stat0)          == 0x10a0188, "cal_stat0 offset must be 0x10a0188");
static_assert(offsetof(PIE2_T, cal_lut)            == 0x10a018c, "cal_lut offset must be 0x10a018c");
static_assert(offsetof(PIE2_T, cal_stat1)          == 0x10a818c, "cal_stat1 offset must be 0x10a818c");
static_assert(offsetof(PIE2_T, cal_stat2)          == 0x10a8190, "cal_stat2 offset must be 0x10a8190");
static_assert(offsetof(PIE2_T, gamma_lut)          == 0x10a8194, "gamma_lut offset must be 0x10a8194");

// Prompt listed boundary offsets
static_assert(offsetof(PIE2_T, field_1000e0)       == 0x1000e0,  "field_1000e0 offset must be 0x1000e0");
static_assert(offsetof(PIE2_T, field_1000e8)       == 0x1000e8,  "field_1000e8 offset must be 0x1000e8");
static_assert(offsetof(PIE2_T, field_1001c0)       == 0x1001c0,  "field_1001c0 offset must be 0x1001c0");
static_assert(offsetof(PIE2_T, field_1001c8)       == 0x1001c8,  "field_1001c8 offset must be 0x1001c8");
static_assert(offsetof(PIE2_T, field_1001cc)       == 0x1001cc,  "field_1001cc offset must be 0x1001cc");
static_assert(offsetof(PIE2_T, field_1081cc)       == 0x1081cc,  "field_1081cc offset must be 0x1081cc");
static_assert(offsetof(PIE2_T, field_10820c)       == 0x10820c,  "field_10820c offset must be 0x10820c");
static_assert(offsetof(PIE2_T, field_10a820c)      == 0x10a820c, "field_10a820c offset must be 0x10a820c");
static_assert(offsetof(PIE2_T, field_10a838c)      == 0x10a838c, "field_10a838c offset must be 0x10a838c");
static_assert(offsetof(PIE2_T, field_10a8390)      == 0x10a8390, "field_10a8390 offset must be 0x10a8390");

// ----------------------------------------------------------------------------
// Prototypes for all 35 pie2_* Functions in pie2.cpp
// ----------------------------------------------------------------------------

// Slice A functions (0x0065a260 .. 0x0065afbf)
int         pie2_acbk(void* context, int y, int width, int bits, int channels, unsigned short* buffer);
int         pie2_scbk(void* context, int y, int width, int bits, int channels, unsigned short* buffer);
int         pie2_scmf(void* context, int y, int width, int bits, int channels, unsigned short* buffer);
int         pie2_scsi(PIE2_T* pie2, unsigned char* cdb, unsigned char* buffer, int len);
int         pie2_stop(PIE2_T* pie2);
int         pie2_sexp(PIE2_T* pie2, int exp_r, int exp_g, int exp_b, int exp_i, int gain_r, int gain_g);

// Intermediate Scan Engine functions (0x0065afc0 .. 0x0065dc6f)
int         pie2_rlin(PIE2_T* pie2, int mode, void* scan_cb_arg, pie2_scan_cb scan_cb, const char* name,
                      int a6, int a7, int a8, int a9, int a10, int a11, int a12, int a13, int a14, int a15, int a16);
int         pie2_fdri(PIE2_T* pie2, int action, int steps);
int         pie2_gsst(PIE2_T* pie2);
int         pie2_poll(void* context, int* status_out);
int         pie2_lsca(void* context, int mode, int x_dpi, int y_dpi, int x_start, int y_start,
                      int width, int height, int bits_per_pixel, int channels,
                      int exp_r, int exp_g, int exp_b, int exp_i,
                      int cal_mode, int extra, int a17, int a18, int a19, int a20,
                      void* cb_arg1, pie2_scan_cb cb1, const char* name1,
                      void* cb_arg2, pie2_scan_cb cb2, const char* name2, int a27);

// Slice B functions (0x0065dc70 .. 0x0065f6df)
int         pie2_usup(int vendor_id, int product_id);
PIE2_T*     pie2_open(int vendor_id, int product_id, int scsi_id, void* scsi_arg,
                      pie2_scsi_cb scsi_func);
int         pie2_scfr(PIE2_T* pie2, int frame);
int         pie2_sfof(PIE2_T* pie2, int offset);
int         pie2_sfra(PIE2_T* pie2, int frame);
int         pie2_spfs(PIE2_T* pie2, int speed);
int         pie2_gnfr(PIE2_T* pie2, int frame_offset);
int         pie2_ejec(PIE2_T* pie2);
int         pie2_gmod(PIE2_T* pie2);
const char* pie2_gvnd(PIE2_T* pie2, int alt_flag);
const char* pie2_gmdl(PIE2_T* pie2, int alt_flag);
int         pie2_info(PIE2_T* pie2, int mode, int* max_dpi, int* max_x, int* max_y,
                      int* res_table, int* num_frames, int* frame_offset);
int         pie2_gcmo(PIE2_T* pie2);
int         pie2_gcap(PIE2_T* pie2, int* p1, int* p2, int* p3, int* p4);
int         pie2_gbsn(PIE2_T* pie2);
int         pie2_gbut(PIE2_T* pie2);
int         pie2_gmsn(PIE2_T* pie2);
int         pie2_grdy(PIE2_T* pie2);
int         pie2_cali(PIE2_T* pie2, const char* name);
int         pie2_gfoc(PIE2_T* pie2);
int         pie2_sfoc(PIE2_T* pie2, int focus);
int         pie2_afoc(PIE2_T* pie2, int x, int y, int w, int h, int opt);
int         pie2_scan(PIE2_T* pie2, int mode, int x_dpi, int y_dpi,
                      int x_start, int y_start, int width, int height,
                      int bits_per_pixel, int channels,
                      int exp_r, int exp_g, int exp_b, int exp_i,
                      int cal_mode, int extra,
                      void* scan_cb_arg, pie2_scan_cb scan_cb);
void        pie2_clos(PIE2_T** pie2_ptr);

#endif // PIE2_COMMON_H
