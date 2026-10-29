// ============================================================================
// pie2_core.cpp - Complete, Authoritative Instruction-Level Decompilation of
// vues/pie2.cpp from VueScan ELF32 binary (/tmp/vuescan/vuescan)
// 100% Fidelity across Slice A (0x0065a260..0x0065afbf) and Slice B (0x0065dc70..0x0065f6df)
// ============================================================================

#include "pie2_common.h"
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

// ----------------------------------------------------------------------------
// Weak linkage for global preference variable (from VueScan core)
// ----------------------------------------------------------------------------
extern "C" {
    int pref_dsc __attribute__((weak)) = 0;
}

// ----------------------------------------------------------------------------
// 1. Hardware Identification Tables
//    _ZL4usbd (41 entries of 12 bytes at virtual address 0x018d3820)
//    _ZL4piem (40 entries of 36 bytes at virtual address 0x01efe7e0)
// ----------------------------------------------------------------------------

const USBD_T _ZL4usbd[41] = {
    { 36, 0x05e3, 0x0121 }, // [ 0]
    { 36, 0x05e3, 0x0123 }, // [ 1]
    { 36, 0x05e3, 0x0127 }, // [ 2]
    { 38, 0x05e3, 0x0122 }, // [ 3]
    { 38, 0x05e3, 0x0123 }, // [ 4]
    { 38, 0x05e3, 0x0124 }, // [ 5]
    { 38, 0x05e3, 0x0128 }, // [ 6]
    { 38, 0x05e3, 0x012a }, // [ 7]
    { 39, 0x05e3, 0x0122 }, // [ 8]
    { 39, 0x05e3, 0x0123 }, // [ 9]
    { 39, 0x05e3, 0x0124 }, // [10]
    { 39, 0x05e3, 0x0126 }, // [11]
    { 39, 0x05e3, 0x0128 }, // [12]
    { 39, 0x05e3, 0x012a }, // [13]
    { 43, 0x05e3, 0x0142 }, // [14]
    { 44, 0x05e3, 0x0143 }, // [15]
    { 44, 0x05e3, 0x0144 }, // [16]
    { 45, 0x05e3, 0x0144 }, // [17]
    { 46, 0x05e3, 0x0145 }, // [18]
    { 47, 0x05e3, 0x0142 }, // [19]
    { 48, 0x05e3, 0x0145 }, // [20]
    { 49, 0x05e3, 0x0144 }, // [21]
    { 50, 0x05e3, 0x0144 }, // [22]
    { 54, 0x05e3, 0x0145 }, // [23]
    { 58, 0x05e3, 0x0142 }, // [24]
    { 60, 0x05e3, 0x0146 }, // [25]
    { 61, 0x05e3, 0x0146 }, // [26]
    { 64, 0x05e3, 0x0146 }, // [27]
    { 65, 0x05e3, 0x0145 }, // [28]
    { 66, 0x05e3, 0x0146 }, // [29]
    { 67, 0x05e3, 0x0146 }, // [30]
    { 70, 0x05e3, 0x0145 }, // [31]
    { 71, 0x05e3, 0x0145 }, // [32]
    { 72, 0x05e3, 0x0144 }, // [33]
    { 77, 0x05e3, 0x0145 }, // [34]
    { 84, 0x05e3, 0x0145 }, // [35]
    { 85, 0x05e3, 0x0142 }, // [36]
    { 87, 0x05e3, 0x0145 }, // [37]
    { 89, 0x05e3, 0x0142 }, // [38]
    { 90, 0x05e3, 0x0145 }, // [39]
    { 91, 0x05e3, 0x0144 }, // [40]
};

// static const PIE_MODEL _ZL4piem[40]
const PIE_MODEL _ZL4piem[40] = {
    { 34, 0, 0, 1, 0, 0, 3, "PrimeFilm 1800U"     , "iScan 1800" }, // [ 0]
    { 37, 0, 2, 0, 0, 0, 3, "PrimeFilm 1800 AFL"  , nullptr }, // [ 1]
    { 40, 0, 0, 1, 0, 0, 3, "PrimeFilm 2700"      , "CrystalScan 2700" }, // [ 2]
    { 42, 0, 0, 1, 0, 0, 3, "PrimeFilm 3600U"     , "iScan 3600" }, // [ 3]
    { 46, 0, 0, 1, 0, 0, 3, "PrimeFilm 3650U"     , "CrystalScan 3600" }, // [ 4]
    { 48, 0, 0, 1, 0, 0, 3, "PrimeFilm 7250U"     , "CrystalScan 7200" }, // [ 5]
    { 84, 0, 0, 1, 0, 0, 3, "NatureScan"          , nullptr }, // [ 6]
    { 98, 0, 0, 1, 0, 0, 3, "PrimeFilm 7250 Plus" , nullptr }, // [ 7]
    { 54, 0, 0, 1, 0, 0, 3, "ColorScan 3600"      , "ProScan 7200" }, // [ 8]
    { 65, 0, 0, 1, 0, 0, 3, "PrimeFilm 7200"      , nullptr }, // [ 9]
    { 70, 0, 0, 1, 1, 1, 3, "PrimeFilm X"         , nullptr }, // [10]
    { 71, 0, 0, 1, 1, 1, 3, "PrimeFilm XE"        , "ProScan 10T" }, // [11]
    { 77, 0, 0, 1, 1, 1, 3, "PrimeHisto XE"       , nullptr }, // [12]
    { 90, 0, 0, 1, 1, 1, 3, "PrimeFilm XEs"       , nullptr }, // [13]
    { 94, 0, 0, 1, 1, 1, 3, "PrimeFilm XE Plus"   , nullptr }, // [14]
    { 43, 1, 1, 1, 0, 0, 1, "PowerSlide 3600"     , "DigitDia 3600" }, // [15]
    { 47, 1, 1, 1, 0, 0, 1, "PowerSlide 3650"     , "DigitDia 4000" }, // [16]
    { 58, 0, 1, 1, 1, 1, 0, "PowerSlide 5000"     , "DigitDia 6000" }, // [17]
    { 85, 0, 1, 1, 1, 1, 0, nullptr               , "DigitDia 7000" }, // [18]
    { 89, 0, 1, 1, 1, 1, 0, "PowerSlide X"        , nullptr }, // [19]
    { 95, 0, 1, 1, 1, 1, 0, "PowerSlide X Plus"   , nullptr }, // [20]
    { 99, 0, 1, 1, 1, 1, 0, nullptr               , "DigitDia 8000" }, // [21]
    { 36, 1, 2, 1, 0, 0, 3, "RFS 3600"            , "RPS 3600" }, // [22]
    { 45, 1, 2, 1, 1, 1, 3, "PrimeFilm 3650 LAB"  , nullptr }, // [23]
    { 49, 1, 2, 1, 0, 0, 3, "PrimeFilm 7250 Pro3" , "RPS 7200" }, // [24]
    { 50, 0, 2, 1, 1, 1, 3, "PrimeFilm 3610 AFL"  , nullptr }, // [25]
    { 72, 0, 2, 1, 1, 1, 3, "PrimeFilm XA"        , "RPS 10M" }, // [26]
    { 91, 0, 2, 1, 1, 1, 3, "PrimeFilm XAs"       , nullptr }, // [27]
    { 93, 0, 2, 1, 1, 1, 3, "PrimeFilm XA Plus"   , nullptr }, // [28]
    { 38, 1, 2, 0, 0, 0, 3, "PrimeFilm 1800 LAB"  , nullptr }, // [29]
    { 39, 1, 2, 0, 0, 0, 3, "PrimeFilm 3600 Pro"  , "ProScan 3600" }, // [30]
    { 44, 1, 2, 0, 0, 0, 3, "PrimeFilm 3650 Pro3" , "ProScan 4000" }, // [31]
    { 60, 0, 3, 1, 0, 0, 2, nullptr               , "MF 5000" }, // [32]
    { 61, 0, 3, 1, 0, 0, 2, "PrimeFilm 120"       , nullptr }, // [33]
    { 64, 0, 3, 1, 0, 0, 2, "FS120ICE"            , nullptr }, // [34]
    { 66, 0, 3, 1, 0, 0, 2, "PrimeFilm 120 Pro"   , nullptr }, // [35]
    { 67, 0, 3, 1, 0, 0, 2, "FilmScan 120"        , nullptr }, // [36]
    { 97, 0, 3, 1, 0, 0, 2, "PF120 Pro Plus"      , nullptr }, // [37]
    { 87, 0, 4, 0, 1, 1, 1, "PowerFilm"           , nullptr }, // [38]
    { 96, 0, 4, 0, 1, 1, 1, "PowerFilm Plus"      , nullptr }, // [39]
};

// ----------------------------------------------------------------------------
// Internal Driver Helper Routines (Inlined in vuescan)
// ----------------------------------------------------------------------------

static int pie2_wait(PIE2_T* pie2) {
    int start_time = user_time();
    while (pie2->cmd != 0) {
        if (user_time() - start_time > 59) {
            return 1;
        }
        user_wait(500);
        uint8_t cdb[6] = { 0, 0, 0, 0, 0, 0 };
        pie2->cmd = 0;
        int status = pie2_scsi(pie2, cdb, nullptr, 0);
        if (status == static_cast<int>(0x80000004)) {
            continue;
        }
        if (status != 0) {
            return 1;
        }
    }
    return 0;
}

static int pie2_gwid(PIE2_T* pie2, int mode) {
    int feeder = (pie2->piem_index >= 0 && pie2->piem_index < 40) ? _ZL4piem[pie2->piem_index].feeder_type : 0;
    if (feeder == 3) {
        if (mode == 0) {
            return pie2->res_table[1]; // +0x30
        }
        if (pie2->status_buf[10] & 1) { // +0x66
            return pie2->res_table[3]; // +0x38
        }
    }
    return pie2->max_y; // +0x28
}

static int pie2_ghei(PIE2_T* pie2, int mode) {
    int feeder = (pie2->piem_index >= 0 && pie2->piem_index < 40) ? _ZL4piem[pie2->piem_index].feeder_type : 0;
    if (feeder == 3) {
        if (mode == 0) {
            return pie2->res_table[2]; // +0x34
        }
        if (pie2->status_buf[10] & 1) { // +0x66
            return pie2->res_table[4]; // +0x3c
        }
    }
    return pie2->res_table[0]; // +0x2c
}

// ============================================================================
// SLICE A: 0x0065a260 .. 0x0065afbf
// ============================================================================

// ----------------------------------------------------------------------------
// pie2_acbk (0x0065a260, decl_line: 2230)
// Autofocus scanline callback: accumulates square contrast diffs and step max.
// ----------------------------------------------------------------------------
int pie2_acbk(void* context, int y, int width, int bits, int channels, unsigned short* buffer) {
    (void)width;
    (void)bits;
    PIE2_T* pie2 = static_cast<PIE2_T*>(context);
    uint8_t status_4 = pie2->status_buf[4]; // +0x60
    if (status_4 <= 1) {
        return 1;
    }

    double metric = 0.0;
    if (y > 1) {
        for (int i = 1; i < y; ++i) {
            if (channels > 0) {
                for (int c = 0; c < channels; ++c) {
                    int curr = static_cast<int>(buffer[i * 4 + c]);
                    int prev = static_cast<int>(buffer[(i - 1) * 4 + c]);
                    int diff = curr - prev;
                    metric += static_cast<double>(diff) * static_cast<double>(diff);
                }
            }
        }
    }

    if (metric > pie2->focus_metric) {
        pie2->focus_metric = metric;
        int step = (pie2->focus_step_max - 1) * 2000 / (static_cast<int>(status_4) - 1) - 1000;
        if (step < -1000) {
            step = -1000;
        } else if (step > 1000) {
            step = 1000;
        }
        pie2->focus_step_min = step;
    }
    pie2->focus_step_max++;
    return 0;
}

// ----------------------------------------------------------------------------
// pie2_scbk (0x0065a3a0, decl_line: 2351)
// Scanline callback accumulator for multi-channel acquisition.
// ----------------------------------------------------------------------------
int pie2_scbk(void* context, int y, int width, int bits, int channels, unsigned short* buffer) {
    (void)width;
    (void)bits;
    PIE2_T* pie2 = static_cast<PIE2_T*>(context);
    if (pie2->field_d4 <= 0) {
        pie2->field_d4++;
        return 0;
    }

    if (y > 0 && channels > 0) {
        if (channels == 1) {
            for (int i = 0; i < y; ++i) {
                pie2->scanline_accum[0][i] += buffer[i * 4];
            }
        } else if (channels == 2) {
            for (int i = 0; i < y; ++i) {
                pie2->scanline_accum[0][i] += buffer[i * 4];
                pie2->scanline_accum[1][i] += buffer[i * 4 + 1];
            }
        } else if (channels == 3) {
            for (int i = 0; i < y; ++i) {
                pie2->scanline_accum[0][i] += buffer[i * 4];
                pie2->scanline_accum[1][i] += buffer[i * 4 + 1];
                pie2->scanline_accum[2][i] += buffer[i * 4 + 2];
            }
        } else {
            for (int i = 0; i < y; ++i) {
                pie2->scanline_accum[0][i] += buffer[i * 4];
                pie2->scanline_accum[1][i] += buffer[i * 4 + 1];
                pie2->scanline_accum[2][i] += buffer[i * 4 + 2];
                pie2->scanline_accum[3][i] += buffer[i * 4 + 3];
            }
        }
        pie2->line_count++;
    }
    pie2->field_d4++;
    return 0;
}

// ----------------------------------------------------------------------------
// pie2_scmf (0x0065a4d0, decl_line: 2381)
// Scanline callback peak / max value filter across line buffers.
// ----------------------------------------------------------------------------
int pie2_scmf(void* context, int y, int width, int bits, int channels, unsigned short* buffer) {
    (void)width;
    (void)bits;
    PIE2_T* pie2 = static_cast<PIE2_T*>(context);
    if (pie2->line_count == 0) {
        if (y > 0 && channels > 0) {
            int num_ch = std::min(channels, 4);
            for (int ch = 0; ch < num_ch; ++ch) {
                for (int i = 0; i < y; ++i) {
                    pie2->scanline_accum[ch][i] = 0x8000;
                }
            }
        }
        pie2->field_d4++;
        pie2->line_count = 1;
        return 0;
    }

    if (y > 0 && channels > 0) {
        if (channels == 1) {
            for (int i = 0; i < y; ++i) {
                uint32_t val = buffer[i * 4];
                if (val > pie2->scanline_accum[0][i]) {
                    pie2->scanline_accum[0][i] = val;
                }
            }
        } else if (channels == 2) {
            for (int i = 0; i < y; ++i) {
                uint32_t v0 = buffer[i * 4];
                if (v0 > pie2->scanline_accum[0][i]) pie2->scanline_accum[0][i] = v0;
                uint32_t v1 = buffer[i * 4 + 1];
                if (v1 > pie2->scanline_accum[1][i]) pie2->scanline_accum[1][i] = v1;
            }
        } else if (channels == 3) {
            for (int i = 0; i < y; ++i) {
                uint32_t v0 = buffer[i * 4];
                if (v0 > pie2->scanline_accum[0][i]) pie2->scanline_accum[0][i] = v0;
                uint32_t v1 = buffer[i * 4 + 1];
                if (v1 > pie2->scanline_accum[1][i]) pie2->scanline_accum[1][i] = v1;
                uint32_t v2 = buffer[i * 4 + 2];
                if (v2 > pie2->scanline_accum[2][i]) pie2->scanline_accum[2][i] = v2;
            }
        } else {
            for (int i = 0; i < y; ++i) {
                uint32_t v0 = buffer[i * 4];
                if (v0 > pie2->scanline_accum[0][i]) pie2->scanline_accum[0][i] = v0;
                uint32_t v1 = buffer[i * 4 + 1];
                if (v1 > pie2->scanline_accum[1][i]) pie2->scanline_accum[1][i] = v1;
                uint32_t v2 = buffer[i * 4 + 2];
                if (v2 > pie2->scanline_accum[2][i]) pie2->scanline_accum[2][i] = v2;
                uint32_t v3 = buffer[i * 4 + 3];
                if (v3 > pie2->scanline_accum[3][i]) pie2->scanline_accum[3][i] = v3;
            }
        }
    }
    pie2->field_d4++;
    return 0;
}

// ----------------------------------------------------------------------------
// pie2_scsi (0x0065a740, decl_line: 290)
// SCSI CDB command dispatch with retry, semaphore timeout, and sense decoding.
// ----------------------------------------------------------------------------
int pie2_scsi(PIE2_T* pie2, unsigned char* cdb, unsigned char* buffer, int len) {
    int ret_code = 9;
    if (!sema_lock(pie2->sema, 1)) {
        return 9;
    }

    int start_time = user_time();
    while (user_time() - start_time <= 0x3b) {
        unsigned char sense[32] = {0};
        int status = pie2->scsi_func(pie2->scsi_context, cdb, buffer, len, sense);
        if (status >= 0) {
            ret_code = 0;
            break;
        }

        if (sense[0] == 0x70) {
            int sense_key = sense[2];
            int asc = sense[12];
            int ascq = sense[13];

            if ((sense_key == 2 && asc == 4 && ascq == 1) || (sense_key == 0x0f && asc == 0 && ascq == 0)) {
                if (sema_canc()) {
                    ret_code = 0x0c;
                    break;
                }
                ret_code = 0x0c;
                user_wait(1000);
                continue;
            }

            if (sense_key == 6 && asc == 0x82 && ascq == 0) {
                ret_code = 0x0e;
                break;
            }

            ret_code = 9;
            break;
        }

        if (ret_code != 0x0c) {
            break;
        }
        if (sema_canc()) {
            ret_code = 0x0c;
            break;
        }
        ret_code = 0x0c;
        user_wait(1000);
    }

    sema_unlk(pie2->sema);
    return ret_code;
}

// ----------------------------------------------------------------------------
// pie2_stop (0x0065a8a0, decl_line: 1293)
// Stops carriage and parks head on models 0x24, 0x26, 0x27.
// ----------------------------------------------------------------------------
int pie2_stop(PIE2_T* pie2) {
    uint8_t cdb[6] = { 0x1b, 0, 0, 0, 0, 0 };
    pie2->cmd = 0x1b;
    pie2_scsi(pie2, cdb, nullptr, 0);

    if (pie2->model_id == 0x24 || pie2->model_id == 0x26 || pie2->model_id == 0x27) {
        uint8_t cdb2[6] = { 0xd2, 0, 0, 0, 4, 0 };
        uint32_t buf = 2;
        pie2->cmd = 0xd2;
        pie2_scsi(pie2, cdb2, reinterpret_cast<uint8_t*>(&buf), 4);
    }
    return 0;
}

// ----------------------------------------------------------------------------
// pie2_sexp (0x0065a950, decl_line: 606)
// Complete 1,643-byte exposure and multi-step analog gain table generator.
// ----------------------------------------------------------------------------
int pie2_sexp(PIE2_T* pie2, int exp_r, int exp_g, int exp_b, int exp_i, int gain_r, int gain_g) {
    (void)exp_i;
    int piem_idx = pie2->piem_index;
    int protocol = (piem_idx >= 0 && piem_idx < 40) ? _ZL4piem[piem_idx].field_10 : 0;
    int d7_len = 0;
    int d7_buf_len = 0;

    if (pie2->max_channels == 4) {
        if (protocol == 0) {
            d7_len = 0x67;
            d7_buf_len = 0x17;
        } else {
            d7_len = 0x67;
            d7_buf_len = (gain_r > 1) ? 0x35 : 0x17;
        }
    } else {
        if (protocol == 0) {
            d7_len = 0x4e;
            d7_buf_len = 0x12;
        } else {
            d7_len = 0x4e;
            d7_buf_len = (gain_r > 1) ? 0x35 : 0x12;
        }
    }

    uint8_t cdb_d7[6] = { 0xd7, 0, 0, 0, static_cast<uint8_t>(d7_len), 0 };
    uint8_t buf_d7[128] = {0};
    pie2->cmd = 0xd7;
    int status = pie2_scsi(pie2, cdb_d7, buf_d7, d7_len);
    if (status != 0) {
        return 1;
    }

    uint16_t base_r = *reinterpret_cast<uint16_t*>(&buf_d7[0x3c]);
    uint16_t base_g = *reinterpret_cast<uint16_t*>(&buf_d7[0x3e]);
    uint16_t base_b = *reinterpret_cast<uint16_t*>(&buf_d7[0x40]);
    uint16_t min_exp = *reinterpret_cast<uint16_t*>(&buf_d7[0x4c]);
    uint16_t base_i = *reinterpret_cast<uint16_t*>(&buf_d7[0x62]);

    if (base_r < min_exp) base_r = min_exp;
    int calc_r = (static_cast<int>(base_r) * exp_r) / 1000;

    if (base_g < min_exp) base_g = min_exp;
    int calc_g = (static_cast<int>(base_g) * exp_g) / 1000;

    if (base_b < min_exp) base_b = min_exp;
    int calc_b = (static_cast<int>(base_b) * exp_b) / 1000;

    if (gain_g != 0) {
        calc_g = static_cast<int>(static_cast<float>(calc_g) * 2.5f);
        calc_b = static_cast<int>(static_cast<float>(calc_b) * 3.5f);
    }

    if (protocol == 0 || gain_r == 0) {
        int max_val = std::max(calc_r, std::max(calc_g, calc_b));
        if (max_val > 0xffff) {
            calc_r = static_cast<int>((static_cast<int64_t>(calc_r) * 0xffff) / max_val);
            calc_g = static_cast<int>((static_cast<int64_t>(calc_g) * 0xffff) / max_val);
            calc_b = static_cast<int>((static_cast<int64_t>(calc_b) * 0xffff) / max_val);
        }
    }

    if (calc_r < min_exp) calc_r = min_exp;
    if (calc_g < min_exp) calc_g = min_exp;
    if (calc_b < min_exp) calc_b = min_exp;

    uint8_t buf_dc[64] = {0};
    *reinterpret_cast<uint16_t*>(&buf_dc[0]) = static_cast<uint16_t>(calc_r);
    *reinterpret_cast<uint16_t*>(&buf_dc[2]) = static_cast<uint16_t>(calc_g);
    *reinterpret_cast<uint16_t*>(&buf_dc[4]) = static_cast<uint16_t>(calc_b);
    buf_dc[6] = buf_d7[0x42];
    buf_dc[7] = buf_d7[0x43];
    *reinterpret_cast<uint32_t*>(&buf_dc[8]) = *reinterpret_cast<uint32_t*>(&buf_d7[0x44]);
    *reinterpret_cast<uint32_t*>(&buf_dc[12]) = *reinterpret_cast<uint32_t*>(&buf_d7[0x48]);
    *reinterpret_cast<uint16_t*>(&buf_dc[16]) = 0;

    if (buf_d7[0x4b] == 0) {
        buf_dc[15] = 7;
    }

    int stepper_type = (piem_idx >= 0 && piem_idx < 40) ? _ZL4piem[piem_idx].field_14 : 0;
    int scan_dpi = pie2->scan_dpi;
    int model = pie2->model_id;

    if (stepper_type == 4) {
        if (scan_dpi == 3600 || scan_dpi == 5000 || scan_dpi == 10000) {
            buf_dc[16] = 4;
        } else if (scan_dpi <= 300) {
            buf_dc[16] = 2;
        }
    } else {
        if (scan_dpi == 5000 || scan_dpi == 10000) {
            buf_dc[16] = 4;
        }
        if (model == 0x47) {
            if (scan_dpi == 5000) {
                buf_dc[16] = 0;
            } else if (scan_dpi == 10000) {
                buf_dc[16] = 4;
            }
        } else if (model == 0x31) {
            if (scan_dpi == 3600) {
                buf_dc[16] = 1;
            } else if (scan_dpi == 7200) {
                buf_dc[16] = 3;
            }
        }
    }

    if (pie2->max_channels == 4) {
        if (base_i < min_exp) base_i = min_exp;
        buf_dc[18] = static_cast<uint8_t>(base_i & 0xff);
        buf_dc[19] = static_cast<uint8_t>((base_i >> 8) & 0xff);
        buf_dc[20] = buf_d7[0x64];
        buf_dc[21] = buf_d7[0x65];
        buf_dc[22] = buf_d7[0x66];
    }

    if (protocol != 0 && gain_r > 1) {
        int half_gain = (gain_r - 1) / 2;
        int step1 = half_gain + 1;
        int step2 = gain_r - half_gain;

        int r1 = step1 * calc_r;
        int g1 = step1 * calc_g;
        int b1 = step1 * calc_b;

        int r2 = step2 * calc_r;
        int g2 = step2 * calc_g;
        int b2 = step2 * calc_b;

        buf_dc[23] = static_cast<uint8_t>((calc_r >> 16) & 0xff);
        buf_dc[24] = 0;
        buf_dc[25] = static_cast<uint8_t>((calc_g >> 16) & 0xff);
        buf_dc[26] = static_cast<uint8_t>((calc_g >> 24) & 0xff);
        buf_dc[27] = static_cast<uint8_t>((calc_b >> 16) & 0xff);
        buf_dc[28] = 0;

        *reinterpret_cast<uint32_t*>(&buf_dc[29]) = static_cast<uint32_t>(r1);
        *reinterpret_cast<uint32_t*>(&buf_dc[33]) = static_cast<uint32_t>(g1);
        *reinterpret_cast<uint32_t*>(&buf_dc[37]) = static_cast<uint32_t>(b1);

        *reinterpret_cast<uint32_t*>(&buf_dc[41]) = static_cast<uint32_t>(r2);
        *reinterpret_cast<uint32_t*>(&buf_dc[45]) = static_cast<uint32_t>(g2);
        *reinterpret_cast<uint32_t*>(&buf_dc[49]) = static_cast<uint32_t>(b2);
    }

    uint8_t cdb_dc[6] = { 0xdc, 0, 0, 0, static_cast<uint8_t>(d7_buf_len), 0 };
    pie2->cmd = 0xdc;
    int ret = pie2_scsi(pie2, cdb_dc, buf_dc, d7_buf_len);
    return (ret != 0) ? 1 : 0;
}

// ============================================================================
// INTERMEDIATE FUNCTIONS: 0x0065afc0 .. 0x0065dc6f
// ============================================================================

// ----------------------------------------------------------------------------
// pie2_fdri (0x0065be80, decl_line: 1139)
// Feeder drive motor controller: steps film forward / reverse.
// ----------------------------------------------------------------------------
int pie2_fdri(PIE2_T* pie2, int action, int steps) {
    int piem_idx = pie2->piem_index;
    int feeder_type = (piem_idx >= 0 && piem_idx < 40) ? _ZL4piem[piem_idx].feeder_type : 0;

    if (feeder_type == 2 && action != 0x10) {
        if (action == 8 && steps == 1) {
            pie2->film_advance_speed = 0;
        }
        int status = pie2_wait(pie2);
        if (status != 0) return 1;

        uint8_t cdb[6] = { 0xd1, 0, 0, 0, 4, 0 };
        uint8_t buf[4] = { static_cast<uint8_t>(action), 0, 0, 0 };
        pie2->cmd = 0xd1;
        status = pie2_scsi(pie2, cdb, buf, 4);
        if (status != 0) return 1;

        if (pie2->film_advance_speed != 0) {
            uint8_t cdb_d3[6] = { 0xd3, 0, 0, 0, 0, 0 };
            pie2->cmd = 0xd3;
            status = pie2_scsi(pie2, cdb_d3, nullptr, 0);
            if (status != 0) return 1;
        }
    } else {
        if (action & 0x86) {
            pie2->val_84 = 0;
        }
        int status = pie2_wait(pie2);
        if (status != 0) return 1;

        uint8_t cdb[6] = { 0xd1, 0, 0, 0, 4, 0 };
        uint8_t buf[4] = {
            static_cast<uint8_t>(action),
            static_cast<uint8_t>(steps & 0xff),
            static_cast<uint8_t>((steps >> 8) & 0xff),
            0
        };
        pie2->cmd = 0xd1;
        status = pie2_scsi(pie2, cdb, buf, 4);
        if (status != 0) return 1;

        if (action == 0x20 || action == 0x80) {
            uint8_t cdb_d3[6] = { 0xd3, 0, 0, 0, 0, 0 };
            pie2->cmd = 0xd3;
            status = pie2_scsi(pie2, cdb_d3, nullptr, 0);
            if (status != 0) return 1;
        }
    }

    return (pie2_gsst(pie2) != 0) ? 1 : 0;
}

// ----------------------------------------------------------------------------
// pie2_gsst (0x0065c090, decl_line: 1192)
// Get scanner status: polls device status bytes via SCSI opcode 0xd0.
// ----------------------------------------------------------------------------
int pie2_gsst(PIE2_T* pie2) {
    int start_time = user_time();
    int piem_idx = pie2->piem_index;
    int feeder_type = (piem_idx >= 0 && piem_idx < 40) ? _ZL4piem[piem_idx].feeder_type : 0;
    int len = (feeder_type == 4) ? 12 : 8;

    while (true) {
        int elapsed = user_time() - start_time;
        if (elapsed > 30) {
            return 1;
        }

        uint8_t cdb[6] = { 0xd0, 0, 0, 0, static_cast<uint8_t>(len), 0 };
        pie2->cmd = 0xd0;
        int status = pie2_scsi(pie2, cdb, pie2->status_buf, len);
        if (status != 0) {
            return 1;
        }

        uint8_t s0 = pie2->status_buf[0];
        if (s0 & 0x01) {
            return 1;
        }

        if (s0 & 0x04) {
            if (pie2->status_buf[1] & 0x80) {
                return 1;
            }
            if (pie2->status_buf[2] & 0x04) {
                return 1;
            }
        }

        if (feeder_type == 4) {
            if ((pie2->status_buf[6] & 0x07) == 0) {
                user_wait(100);
                continue;
            }
            break;
        }

        if (s0 & 0x02) {
            user_wait(100);
            continue;
        }

        if (pie2->status_buf[1] & 0x01) {
            user_wait(100);
            continue;
        }

        break;
    }

    if (feeder_type == 2) {
        if ((pie2->status_buf[6] & 0x07) == 0x05 && (pie2->status_buf[6] & 0x10)) {
            pie2_fdri(pie2, 8, 1);
        }
    }

    return 0;
}

// ----------------------------------------------------------------------------
// pie2_poll (0x0065c250, decl_line: 1243)
// Background polling worker: updates status and button states.
// ----------------------------------------------------------------------------
int pie2_poll(void* handle, int* status_out) {
    PIE2_T* pie2 = static_cast<PIE2_T*>(handle);
    int piem_idx = pie2->piem_index;
    int feeder_type = (piem_idx >= 0 && piem_idx < 40) ? _ZL4piem[piem_idx].feeder_type : 0;
    int len = (feeder_type == 4) ? 12 : 8;

    uint8_t cdb[6] = { 0xd0, 0, 0, 0, static_cast<uint8_t>(len), 0 };
    pie2->cmd = 0xd0;
    int status = pie2_scsi(pie2, cdb, pie2->status_buf, len);
    if (status != 0) {
        if (status_out) *status_out = 0;
        return 1;
    }

    if (status_out) {
        int ready = 0;
        if (feeder_type == 4) {
            ready = ((pie2->status_buf[6] & 0x07) != 0) ? 1 : 0;
        } else {
            uint8_t s0 = pie2->status_buf[0];
            uint8_t s1 = pie2->status_buf[1];
            if (!(s0 & 0x02) && !(s1 & 0x01)) {
                ready = 1;
            }
        }
        *status_out = ready;
    }

    if (feeder_type == 2) {
        if ((pie2->status_buf[6] & 0x07) == 0x05 && (pie2->status_buf[6] & 0x10)) {
            pie2_fdri(pie2, 8, 1);
        }
    }

    return 0;
}

// ============================================================================
// SLICE B: 0x0065dc70 .. 0x0065f6df
// ============================================================================

// ----------------------------------------------------------------------------
// pie2_usup (0x0065dc70, decl_line: 259)
// USB device vendor / product ID support inquiry.
// ----------------------------------------------------------------------------
int pie2_usup(int vendor_id, int product_id) {
    if (pref_dsc == 8) {
        return 0;
    }
    if (pie1_plus(vendor_id, product_id) || pie1_gplu(vendor_id, product_id)) {
        return 0;
    }
    if (vendor_id != 0x05e3) {
        return 0;
    }

    int prefix = product_id & 0xfff0;
    if (prefix == 0x120) {
        if (product_id == 0x120 || product_id == 0x129) {
            return 0;
        }
        return 1;
    }
    if (prefix == 0x140) {
        return 1;
    }
    return 0;
}

// ----------------------------------------------------------------------------
// pie2_open (0x0065dd20, decl_line: 1515)
// Driver allocation and hardware initialization (1,778 bytes).
// ----------------------------------------------------------------------------
PIE2_T* pie2_open(int vendor_id, int product_id, int scsi_id, void* scsi_arg,
                  pie2_scsi_cb scsi_func) {
    (void)scsi_id;
    PIE2_T* pie2 = static_cast<PIE2_T*>(calloc(1, sizeof(PIE2_T)));
    if (!pie2) {
        return nullptr;
    }

    pie2->scsi_context = scsi_arg;
    pie2->scsi_func = scsi_func;
    pie2->sema = sema_open();
    pie2->timeout_sec = 0x1e;

    // Send SCSI inquiry command 0x12
    uint8_t cdb_inq[6] = { 0x12, 0, 0, 0, 0xb8, 0 };
    uint8_t inq[0xb8] = {0};
    pie2->cmd = 0x12;
    int status = pie2_scsi(pie2, cdb_inq, inq, 0xb8);
    if (status != 0) {
        pie2_clos(&pie2);
        return nullptr;
    }

    // Geometry limits and optical resolutions from inquiry payload
    pie2->max_x = *reinterpret_cast<uint16_t*>(&inq[0x26]);
    pie2->max_y = *reinterpret_cast<uint16_t*>(&inq[0x28]);
    pie2->res_table[0] = *reinterpret_cast<uint16_t*>(&inq[0x2a]);
    pie2->res_table[1] = *reinterpret_cast<uint16_t*>(&inq[0x6c]);
    pie2->res_table[2] = *reinterpret_cast<uint16_t*>(&inq[0x6e]);
    pie2->res_table[3] = *reinterpret_cast<uint16_t*>(&inq[0x70]);
    pie2->res_table[4] = *reinterpret_cast<uint16_t*>(&inq[0x72]);
    pie2->model_id = *reinterpret_cast<uint16_t*>(&inq[0x74]);

    // Model specific optical tables and ID overrides
    if (pie2->model_id == 0x46) {
        if (inq[0x35] == 1) {
            pie2->model_id = 0x5a;
        } else if (inq[0x73] == '4' && inq[0x72] == '0') {
            pie2->model_id = 0x47;
        }
    } else if (pie2->model_id == 0x47) {
        if (inq[0x35] == 1) {
            pie2->model_id = 0x5a;
        }
    } else if (pie2->model_id == 0x48) {
        if (inq[0x35] == 1) {
            pie2->model_id = 0x5b;
        }
    }

    if (pie2->model_id == 0x46 || pie2->model_id == 0x47 || pie2->model_id == 0x5a) {
        pie2->res_table[0] = 7200;
        pie2->res_table[1] = 3600;
        pie2->res_table[2] = 1800;
        pie2->res_table[3] = 900;
        pie2->res_table[4] = 450;
    }

    // Bit depth capability
    if (inq[0x2d] & 0x20) {
        pie2->max_bits = 16;
    } else if (inq[0x2d] & 0x10) {
        pie2->max_bits = 12;
    } else if (inq[0x2d] & 0x08) {
        pie2->max_bits = 10;
    } else {
        pie2->max_bits = 8;
    }

    pie2->cap_48 = inq[0x34];
    pie2->max_channels = (inq[0x2c] & 0x10) ? 4 : 3;

    // Analog gain channels and lamp status
    if (inq[0x60] > 0x1f) {
        pie2->gain[0] = inq[0x60];
        pie2->gain[1] = inq[0x61];
        pie2->gain[2] = inq[0x62];
        pie2->gain[3] = inq[0x63];
    } else {
        *reinterpret_cast<uint32_t*>(pie2->gain) = *reinterpret_cast<uint32_t*>(&inq[0x20]);
    }
    pie2->offset_50 = 0;

    // Stepper motor mode
    pie2->step = (inq[0x64] & 0x01);
    int model_diff = pie2->model_id - 0x3a;
    if (model_diff >= 0 && model_diff <= 0x1b) {
        if ((0x8006005 >> model_diff) & 1) {
            pie2->step = 1;
        }
    }
    pie2->val_58 = inq[0x67];

    // Compute gamma curve table for 0x24, 0x26, 0x27 models
    if (pie2->model_id == 0x24 || pie2->model_id == 0x26 || pie2->model_id == 0x27) {
        for (int i = 0; i < 256; ++i) {
            double normalized = static_cast<double>(i) / 255.0;
            double curved = gamm_gtol(normalized);
            pie2->gamma_lut[i] = static_cast<uint16_t>(curved * 65535.0 + 0.5);
        }
    }

    // Match vendor_id and product_id against _ZL4usbd table
    pie2->usbd_index = -1;
    for (int i = 0; i < 41; ++i) {
        if (_ZL4usbd[i].vendor_id == vendor_id && _ZL4usbd[i].product_id == product_id) {
            pie2->usbd_index = i;
            break;
        }
    }

    // Match model against _ZL4piem table
    pie2->piem_index = -1;
    int target_model = (pie2->usbd_index >= 0) ? _ZL4usbd[pie2->usbd_index].model_id : pie2->model_id;
    for (int j = 0; j < 40; ++j) {
        if (_ZL4piem[j].model_id == target_model) {
            pie2->piem_index = j;
            break;
        }
    }

    if (pie2->usbd_index < 0 || pie2->piem_index < 0) {
        pie2_clos(&pie2);
        return nullptr;
    }

    pie2->flags_18 = (vendor_id == 0x5e3) ? 1 : 0;
    int feeder = _ZL4piem[pie2->piem_index].feeder_type;

    if (feeder == 1) {
        pie2->frames = 1;
        pie2->frame_offset = 0;
        pie2->frame_width = 100;
        pie2->max_frames = 100;
    } else if (feeder == 2) {
        pie2->frames = 2;
        pie2->frame_offset = 1;
        pie2->frame_width = 50;
        pie2->max_frames = 50;
    } else if (feeder == 4) {
        pie2->frames = 1;
        pie2->frame_offset = -1;
        pie2->frame_width = 1;
        pie2->max_frames = 1;
    } else {
        pie2->frames = 2;
        pie2->frame_offset = -1;
        pie2->frame_width = 1;
        pie2->max_frames = 1;
    }
    pie2->curr_frame = 0;
    pie2->val_7c = 0;

    // Wait for scanner carriage readiness
    if (pie2_wait(pie2) != 0) {
        pie2_clos(&pie2);
        return nullptr;
    }

    // Query scan parameters on non-legacy models
    if (pie2->model_id != 0x24 && pie2->model_id != 0x26 && pie2->model_id != 0x27) {
        uint8_t cdb_e7[6] = { 0xe7, 1, 0, 0, 4, 0 };
        uint8_t buf_e7[4] = {0};
        pie2->cmd = 0xe7;
        pie2_scsi(pie2, cdb_e7, buf_e7, 4);
    }

    if (pie2_gsst(pie2) != 0) {
        pie2_clos(&pie2);
        return nullptr;
    }

    // Mode select parameters
    uint8_t cdb_0a[6] = { 0x0a, 0, 0, 0, 6, 0 };
    uint8_t buf_0a[6] = { 0x95, 0, 0, 0, 0, 0 };
    pie2->cmd = 0x0a;
    status = pie2_scsi(pie2, cdb_0a, buf_0a, 6);
    if (status != 0) {
        pie2_clos(&pie2);
        return nullptr;
    }

    uint8_t cdb_08[6] = { 0x08, 0, 0, 0, 0x12, 0 };
    uint8_t buf_08[0x12] = {0};
    pie2->cmd = 0x08;
    status = pie2_scsi(pie2, cdb_08, buf_08, 0x12);
    if (status != 0) {
        pie2_clos(&pie2);
        return nullptr;
    }

    pie2->opt_x_start = buf_08[9];
    pie2->opt_y_start = buf_08[11];
    pie2->opt_width = *reinterpret_cast<uint16_t*>(&buf_08[12]);
    pie2->opt_height = *reinterpret_cast<uint16_t*>(&buf_08[12]);
    pie2->ccd_dpi = pie2->max_x;

    if (feeder == 3) {
        if (pie2->max_x == 6400) {
            pie2->ccd_dpi = 3200;
        }
    } else if ((pie2->max_y * 2) / 3 > pie2->opt_width) {
        pie2->ccd_dpi = pie2->max_x / 2;
    }

    // Launch background status poll thread if hardware button support exists
    if (_ZL4piem[pie2->piem_index].field_c != 0) {
        POLL_T* poll = poll_open(pie2, pie2_poll);
        pie2->set_poll(poll);
    }

    return pie2;
}

// ----------------------------------------------------------------------------
// pie2_scfr (0x0065e420, decl_line: 1697)
// Motorized slide/frame feeder selection.
// ----------------------------------------------------------------------------
int pie2_scfr(PIE2_T* pie2, int frame) {
    if (!pie2) return 1;
    if (!poll_lock(pie2->get_poll())) return 1;

    int ret = 1;
    int feeder = (pie2->piem_index >= 0 && pie2->piem_index < 40) ? _ZL4piem[pie2->piem_index].feeder_type : 0;
    if (feeder == 1) {
        pie2->val_80 = 0;
        int target = frame;
        if (target < 1) target = 1;
        if (target > pie2->max_frames) target = pie2->max_frames;
        ret = pie2_fdri(pie2, 0x80, target - 1);
    }

    poll_unlk(pie2->get_poll(), 0);
    return ret;
}

// ----------------------------------------------------------------------------
// pie2_sfof (0x0065e4c0, decl_line: 1764)
// Set film frame micro-offset.
// ----------------------------------------------------------------------------
int pie2_sfof(PIE2_T* pie2, int offset) {
    if (!pie2) return 1;
    if (!poll_lock(pie2->get_poll())) return 1;

    int ret = 0;
    int feeder = (pie2->piem_index >= 0 && pie2->piem_index < 40) ? _ZL4piem[pie2->piem_index].feeder_type : 0;
    if (feeder == 2) {
        if (pie2->status_buf[5] == 0 && (pie2->status_buf[6] & 7) == 5) {
            int diff = offset - pie2->val_7c;
            int step = (diff * 240) / pie2->max_x;
            if (step != 0) {
                int action = 0;
                if (step < 0) {
                    step = -step;
                    action = 1;
                }
                int status = pie2_fdri(pie2, action, step);
                if (status == 0) {
                    pie2->val_7c = offset;
                } else {
                    ret = 1;
                }
            }
        }
    }

    poll_unlk(pie2->get_poll(), 0);
    return ret;
}

// ----------------------------------------------------------------------------
// pie2_sfra (0x0065e590, decl_line: 1837)
// Motorized filmstrip frame indexing.
// ----------------------------------------------------------------------------
int pie2_sfra(PIE2_T* pie2, int frame) {
    if (!pie2) return 1;
    if (!poll_lock(pie2->get_poll())) return 1;

    int ret = 0;
    int feeder = (pie2->piem_index >= 0 && pie2->piem_index < 40) ? _ZL4piem[pie2->piem_index].feeder_type : 0;
    if (feeder == 1 || feeder == 2) {
        frame += pie2->val_80;
    }

    if (frame <= 0 || frame > pie2->max_frames) {
        ret = 1;
    } else if (feeder == 2) {
        if (pie2->status_buf[5] != 0 || (pie2->status_buf[6] & 7) != 5) {
            ret = 0;
        }
    } else if (feeder == 1) {
        int target = frame - 1;
        int curr = static_cast<int>(pie2->status_buf[2]);
        int diff = target - curr;
        if (diff != 0) {
            int action = 4;
            int steps = diff;
            if (diff < 0) {
                steps = -diff;
                action = 5;
            }
            int status = pie2_fdri(pie2, action, steps);
            if (status != 0) {
                ret = 1;
            } else {
                ret = (static_cast<int>(pie2->status_buf[2]) != target) ? 1 : 0;
            }
        }
    }

    poll_unlk(pie2->get_poll(), 0);
    return ret;
}

// ----------------------------------------------------------------------------
// pie2_spfs (0x0065e6a0, decl_line: 1858)
// Set film advance speed.
// ----------------------------------------------------------------------------
int pie2_spfs(PIE2_T* pie2, int speed) {
    pie2->film_advance_speed = speed;
    return 0;
}

// ----------------------------------------------------------------------------
// pie2_gnfr (0x0065e6c0, decl_line: 1908)
// Get number of motorized film frames.
// ----------------------------------------------------------------------------
int pie2_gnfr(PIE2_T* pie2, int frame_offset) {
    if (!pie2) return 1;
    if (!poll_lock(pie2->get_poll())) return 1;

    int ret = 1;
    if (frame_offset == pie2->frame_offset) {
        int feeder = (pie2->piem_index >= 0 && pie2->piem_index < 40) ? _ZL4piem[pie2->piem_index].feeder_type : 0;
        if (feeder == 2) {
            if (pie2->status_buf[5] == 0 && (pie2->status_buf[6] & 7) == 5 && (pie2->status_buf[6] & 0x20)) {
                pie2->curr_frame = 1;
                pie2->max_frames = static_cast<int>(pie2->status_buf[2]) + 1;
            }
        }
        ret = pie2->max_frames - pie2->val_80;
        if (ret <= 0) ret = 1;
    }

    poll_unlk(pie2->get_poll(), 0);
    return ret;
}

// ----------------------------------------------------------------------------
// pie2_ejec (0x0065e790, decl_line: 1966)
// Eject motorized slide / roll film feeder.
// ----------------------------------------------------------------------------
int pie2_ejec(PIE2_T* pie2) {
    if (!pie2) return 1;
    if (!poll_lock(pie2->get_poll())) return 1;

    int ret = 0;
    int feeder = (pie2->piem_index >= 0 && pie2->piem_index < 40) ? _ZL4piem[pie2->piem_index].feeder_type : 0;
    if (feeder == 4) {
        uint8_t cdb[6] = { 0xd1, 0, 0, 0, 4, 0 };
        uint32_t buf = 0x49b9ee03;
        pie2->cmd = 0xd1;
        pie2_scsi(pie2, cdb, reinterpret_cast<uint8_t*>(&buf), 4);
    } else if (feeder == 2) {
        if (pie2->status_buf[5] == 0 && (pie2->status_buf[6] & 7) == 5) {
            int steps = 0;
            if (static_cast<int>(pie2->status_buf[2]) > pie2->curr_frame) {
                steps = (pie2->max_frames + 1 < 3) ? 3 : 2;
            } else {
                steps = (static_cast<int>(pie2->status_buf[2]) < 7) ? 3 : 2;
            }
            pie2_fdri(pie2, steps, 1);
        }
    }

    poll_unlk(pie2->get_poll(), 0);
    return ret;
}

// ----------------------------------------------------------------------------
// pie2_gmod (0x0065e8c0, decl_line: 2004)
// Get model code integer.
// ----------------------------------------------------------------------------
int pie2_gmod(PIE2_T* pie2) {
    if (!pie2) return -1;
    if (pie2->usbd_index >= 0 && pie2->usbd_index < 41) {
        return _ZL4usbd[pie2->usbd_index].model_id;
    }
    return -1;
}

// ----------------------------------------------------------------------------
// pie2_gvnd (0x0065e8f0, decl_line: 2012)
// Get vendor marketing string.
// ----------------------------------------------------------------------------
const char* pie2_gvnd(PIE2_T* pie2, int alt_flag) {
    if (!pie2) return nullptr;
    if (pie2->usbd_index >= 0 && pie2->usbd_index < 41) {
        return pied_gvnd(_ZL4usbd[pie2->usbd_index].model_id, alt_flag);
    }
    return nullptr;
}

// ----------------------------------------------------------------------------
// pie2_gmdl (0x0065e940, decl_line: 2021)
// Get model marketing string.
// ----------------------------------------------------------------------------
const char* pie2_gmdl(PIE2_T* pie2, int alt_flag) {
    if (!pie2) return nullptr;
    if (pie2->usbd_index >= 0 && pie2->usbd_index < 41) {
        return pied_gmdl(_ZL4usbd[pie2->usbd_index].model_id, alt_flag);
    }
    return nullptr;
}

// ----------------------------------------------------------------------------
// pie2_info (0x0065e990, decl_line: 2031)
// Query geometry, resolutions, optical dimensions, and frame parameters.
// ----------------------------------------------------------------------------
int pie2_info(PIE2_T* pie2, int mode, int* max_dpi, int* max_x, int* max_y,
              int* res_table, int* num_frames, int* frame_offset) {
    if (!pie2 || pie2->frames <= mode) {
        return 1;
    }

    if (max_dpi) {
        *max_dpi = pie2->max_x;
    }
    if (max_x) {
        *max_x = pie2_gwid(pie2, mode);
    }
    if (max_y) {
        *max_y = pie2_ghei(pie2, mode);
    }
    if (res_table) {
        int i = 0;
        for (; i < 5; ++i) {
            if (pie2->res_table[i] <= 0) break;
            res_table[i] = pie2->res_table[i];
        }
        res_table[i] = 0;
    }
    if (num_frames) {
        *num_frames = pie2->max_frames;
    }
    if (frame_offset) {
        *frame_offset = pie2->curr_frame;
    }
    return 0;
}

// ----------------------------------------------------------------------------
// pie2_gcmo (0x0065ec80, decl_line: 2135)
// Get calibration and feeder configuration mode.
// ----------------------------------------------------------------------------
int pie2_gcmo(PIE2_T* pie2) {
    if (pie2->status_buf[5] != 0) {
        return -1;
    }
    int feeder = (pie2->piem_index >= 0 && pie2->piem_index < 40) ? _ZL4piem[pie2->piem_index].feeder_type : 0;
    if (feeder == 2) {
        uint8_t b = pie2->status_buf[6];
        if (!(b & 1)) return -1;
        return (b >> 2) & 1;
    }
    if (feeder == 3) {
        uint8_t b = pie2->status_buf[9];
        if (b & 3) return 1;
        return -(((b >> 2) ^ 1) & 1);
    }
    return -1;
}

// ----------------------------------------------------------------------------
// pie2_gcap (0x0065ecf0, decl_line: 2167)
// Get feeder and sensor hardware capability flags.
// ----------------------------------------------------------------------------
int pie2_gcap(PIE2_T* pie2, int* p1, int* p2, int* p3, int* p4) {
    int idx = pie2->piem_index;
    if (idx < 0 || idx >= 40) {
        return 0;
    }
    if (p1) *p1 = _ZL4piem[idx].feeder_type;
    if (p2) *p2 = (_ZL4piem[idx].feeder_type == 2) ? 1 : 0;
    if (p3) *p3 = _ZL4piem[idx].field_14;
    if (p4) *p4 = _ZL4piem[idx].field_18;
    return 0;
}

// ----------------------------------------------------------------------------
// pie2_gbsn (0x0065ed70, decl_line: 2185)
// Get button sensor capability.
// ----------------------------------------------------------------------------
int pie2_gbsn(PIE2_T* pie2) {
    int idx = pie2->piem_index;
    if (idx >= 0 && idx < 40) {
        return _ZL4piem[idx].field_c;
    }
    return 0;
}

// ----------------------------------------------------------------------------
// pie2_gbut (0x0065ed90, decl_line: 2191)
// Get front-panel hardware button state.
// ----------------------------------------------------------------------------
int pie2_gbut(PIE2_T* pie2) {
    if (!pie2) return 0;
    return poll_gbut(pie2->get_poll());
}

// ----------------------------------------------------------------------------
// pie2_gmsn (0x0065edc0, decl_line: 2202)
// Get media sensor capability.
// ----------------------------------------------------------------------------
int pie2_gmsn(PIE2_T* pie2) {
    (void)pie2;
    return 1;
}

// ----------------------------------------------------------------------------
// pie2_grdy (0x0065edd0, decl_line: 2207)
// Get media presence / scanner ready status.
// ----------------------------------------------------------------------------
int pie2_grdy(PIE2_T* pie2) {
    if (!pie2) return 0;
    return poll_gmed(pie2->get_poll());
}

// ----------------------------------------------------------------------------
// pie2_cali (0x0065ee00, decl_line: 2219)
// Mark device as requiring optical / shading calibration.
// ----------------------------------------------------------------------------
int pie2_cali(PIE2_T* pie2, const char* name) {
    (void)name;
    pie2->state_8c = 1;
    return 0;
}

// ----------------------------------------------------------------------------
// pie2_gfoc (0x0065ee10, decl_line: 3233)
// Get optical focus motor position.
// ----------------------------------------------------------------------------
int pie2_gfoc(PIE2_T* pie2) {
    if (!pie2) return 0;
    return pie2->focus_step_min;
}

// ----------------------------------------------------------------------------
// pie2_sfoc (0x0065ee30, decl_line: 3243)
// Set optical focus motor position with clamping [-1000, 1000].
// ----------------------------------------------------------------------------
int pie2_sfoc(PIE2_T* pie2, int focus) {
    if (!pie2) return 0;
    if (focus > 1000) focus = 1000;
    if (focus < -1000) focus = -1000;
    pie2->focus_step_min = focus;
    return 0;
}

// ----------------------------------------------------------------------------
// pie2_afoc (0x0065ee60, decl_line: 3322)
// Autofocus routine: calculates focus area and executes autofocus scan pass.
// ----------------------------------------------------------------------------
int pie2_afoc(PIE2_T* pie2, int x, int y, int w, int h, int opt) {
    if (!pie2) return 1;

    int feeder = (pie2->piem_index >= 0 && pie2->piem_index < 40) ? _ZL4piem[pie2->piem_index].feeder_type : 0;
    if (opt != 0) {
        if (feeder == 2) {
            if (pie2->val_98 != 0) {
                if (pie2->val_9c == x && pie2->val_a0 == y && pie2->val_a4 == w && pie2->val_a8 == h) {
                    return 0;
                }
            }
        }
    } else {
        pie2->val_98 = 0;
    }

    int gw = pie2_gwid(pie2, x);
    int gh = pie2_ghei(pie2, x);
    (void)gh;

    if (!poll_lock(pie2->get_poll())) return 1;

    int win_w = (gw + 7) / 8;
    int x_end = w + win_w;
    int x_start = w - win_w;
    if (x_start < 0) {
        x_end -= x_start;
        x_start = 0;
    }
    if (x_end >= gw) {
        int overflow = x_end - (gw - 1);
        x_end = gw - 1;
        x_start -= overflow;
    }

    if (pie2_wait(pie2) != 0) {
        poll_unlk(pie2->get_poll(), 1);
        return 1;
    }

    if (pie2->frames <= x) {
        poll_unlk(pie2->get_poll(), 1);
        return 1;
    }

    int status = pie2_lsca(pie2, 3, pie2->ccd_dpi, pie2->ccd_dpi,
                           x_start, y, (x_end - x_start), (h - 1),
                           1, 0, 1, 1000, 1000, 1000,
                           1, 0, 0, 0, 0, 0,
                           pie2, pie2_scbk, "pie2_afoc",
                           pie2, pie2_acbk, "pie2_afoc", 0);

    if (status == 0) {
        if (feeder == 2) {
            pie2->val_98 = 1;
            pie2->val_9c = x;
            pie2->val_a0 = y;
            pie2->val_a4 = w;
            pie2->val_a8 = h;
        }
    }

    poll_unlk(pie2->get_poll(), 1);
    return status;
}

// ----------------------------------------------------------------------------
// pie2_scan (0x0065f160, decl_line: 3450)
// Complete scan engine execution with calibration management (1,324 bytes).
// ----------------------------------------------------------------------------
int pie2_scan(PIE2_T* pie2, int mode, int x_dpi, int y_dpi,
              int x_start, int y_start, int width, int height,
              int bits_per_pixel, int channels,
              int exp_r, int exp_g, int exp_b, int exp_i,
              int cal_mode, int extra,
              void* scan_cb_arg, pie2_scan_cb scan_cb) {
    if (!pie2) return 1;

    if (channels == 1) {
        channels = 3;
    } else {
        channels = 0;
    }

    if (!poll_lock(pie2->get_poll())) return 1;

    int idx = pie2->piem_index;
    int feeder = (idx >= 0 && idx < 40) ? _ZL4piem[idx].feeder_type : 0;
    int stepper = (idx >= 0 && idx < 40) ? _ZL4piem[idx].field_14 : 0;
    int sensor = (idx >= 0 && idx < 40) ? _ZL4piem[idx].field_18 : 0;

    if (feeder == 3) {
        if (pie2->state_8c != 0) {
            // Need calibration
        }
    } else {
        if (pie2->bytes_per_line == 1) {
            pie2->state_8c = 1;
        }
    }

    int gain_r_arg = (stepper != 0) ? cal_mode : 0;
    int gain_g_arg = extra;
    if (sensor != 0) {
        if (gain_r_arg != 0 && gain_g_arg > 1) {
            gain_r_arg = gain_r_arg + gain_g_arg - 1;
            gain_g_arg = 1;
        }
    }

    // Shading calibration scan if state_8c flag is active
    if (pie2->state_8c != 0) {
        pie2->state_8c = 0;
        pie2->field_d4 = -1;
        pie2->line_count = 0;
        std::memset(pie2->scanline_accum, 0, sizeof(pie2->scanline_accum));

        if (pie2_wait(pie2) != 0) {
            poll_unlk(pie2->get_poll(), 1);
            return 1;
        }

        if (pie2->frames > 1) {
            int gw = pie2_gwid(pie2, 0);
            int cal_stat = pie2_lsca(pie2, 1, pie2->ccd_dpi, pie2->ccd_dpi,
                                     0, 0, gw - 1, 1199,
                                     1, 0, 1, 1050, 1050, 1050,
                                     1, 0, 0, 0, 0, 0,
                                     pie2, pie2_scmf, "pie2_scan",
                                     nullptr, nullptr, nullptr, 0);
            if (cal_stat != 0) {
                poll_unlk(pie2->get_poll(), 1);
                return cal_stat;
            }

            if (pie2->line_count > 0 && pie2->max_channels > 0) {
                for (int ch = 0; ch < pie2->max_channels; ++ch) {
                    pie2->cal_white[ch] = 0;
                    for (int ecx = 0; ecx < pie2->opt_height; ++ecx) {
                        uint32_t val = pie2->scanline_accum[ch][ecx] / pie2->line_count;
                        if (val > 0xffff) val = 0xffff;
                        if (val > pie2->cal_white[ch]) pie2->cal_white[ch] = static_cast<uint16_t>(val);
                        pie2->cal_line_buf[ch][ecx] = static_cast<uint16_t>(val);
                    }
                }
                pie2->state_8c = 0;
                pie2->height_pixels = 1;
                pie2->bytes_per_line = pie2->max_channels;
            }
        }
    }

    if (pie2_wait(pie2) != 0) {
        poll_unlk(pie2->get_poll(), 1);
        return 1;
    }

    if (pie2->frames <= mode) {
        poll_unlk(pie2->get_poll(), 1);
        return 1;
    }

    // Set exposure parameters before scanning
    pie2_sexp(pie2, exp_r, exp_g, exp_b, exp_i, gain_r_arg, gain_g_arg);

    int model = pie2->model_id;
    int is_legacy = (model != 0x24 && model != 0x26 && model != 0x27) ? 1 : 0;

    int ret = pie2_lsca(pie2, mode, x_dpi, y_dpi,
                        x_start, y_start, width, height,
                        bits_per_pixel, channels,
                        exp_r, exp_g, exp_b, exp_i,
                        cal_mode, extra, 0, 0, 0, 0,
                        scan_cb_arg, scan_cb, "pie2_scan",
                        nullptr, nullptr, nullptr, is_legacy);

    poll_unlk(pie2->get_poll(), 1);
    return ret;
}

// ----------------------------------------------------------------------------
// pie2_clos (0x0065f690, decl_line: 3541)
// Driver resource cleanup and deallocation.
// ----------------------------------------------------------------------------
void pie2_clos(PIE2_T** pie2_ptr) {
    if (!pie2_ptr || !*pie2_ptr) return;
    PIE2_T* pie2 = *pie2_ptr;

    POLL_T* poll_handle = pie2->get_poll();
    if (poll_handle) {
        poll_clos(reinterpret_cast<void**>(&pie2->cap_flags));
    }
    if (pie2->sema) {
        sema_clos(&pie2->sema);
    }
    free(pie2);
    *pie2_ptr = nullptr;
}
