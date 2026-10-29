// ============================================================================
// pie2_lsca.cpp - Pacific Image Electronics (PIE) Scan Orchestration
// Instruction-level faithful decompile of pie2_lsca (0x0065c550..0x0065dc6f)
// ============================================================================

#include "pie2_common.h"
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <algorithm>
#include <cmath>

// External gamma conversion routine from binary (0x00686d40)
float gamm_ltog(float);

// ----------------------------------------------------------------------------
// Internal Helper: Scanner Stop and Return Home (lines 65c82f..65c89f)
// ----------------------------------------------------------------------------
static void pie2_stop_and_cleanup(PIE2_T *p) {
    if (!p) return;
    uint8_t cdb_stop[6] = { 0x1b, 0, 0, 0, 0, 0 };
    p->cmd = 0x1b;
    pie2_scsi(p, cdb_stop, nullptr, 0);

    if (p->model_id == 0x24 || p->model_id == 0x26 || p->model_id == 0x27) {
        uint8_t cdb_home[6] = { 0xd2, 0, 0, 0, 4, 0 };
        uint32_t buf = 2;
        p->cmd = 0xd2;
        pie2_scsi(p, cdb_home, reinterpret_cast<uint8_t*>(&buf), 4);
    }
}

// ----------------------------------------------------------------------------
// pie2_lsca (0x0065c550..0x0065dc6f, 5,919 bytes)
// Master Low-Level Line Scan Orchestration Function
// ----------------------------------------------------------------------------
int pie2_lsca(
    void*       vp,
    int         mode,
    int         bits,
    int         channels,
    int         scan_dpi,
    int         x_start,
    int         y_start,
    int         width,
    int         height,
    int         res_x,
    int         res_y,
    int         exp_r,
    int         exp_g,
    int         exp_b,
    int         exp_i,
    int         off_r,
    int         off_g,
    int         off_b,
    int         off_i,
    int         flags,
    void*       ctx1,
    pie2_scan_cb cb1,
    const char* name1,
    void*       ctx2,
    pie2_scan_cb cb2,
    const char* name2,
    int         scan_type
) {
    PIE2_T *p = reinterpret_cast<PIE2_T*>(vp);
    if (!p) return 1;
    (void)off_i;

    // ------------------------------------------------------------------------
    // Phase 1: Input Validation and Parameter Clamping (lines 2977..2987)
    // ------------------------------------------------------------------------
    if (bits > 8) {
        bits = p->max_bits;
    }
    if (channels > 3 && p->max_channels == 3) {
        channels = 3;
    }
    p->scan_dpi = scan_dpi;

    // ------------------------------------------------------------------------
    // Phase 2: Color Balance Setup (pie2_cbal inlined, lines 456..469)
    // ------------------------------------------------------------------------
    for (int opcode = 0x13; opcode <= 0x14; ++opcode) {
        for (int ch = 1; ch <= 3; ++ch) {
            uint8_t cdb[6] = { 0x0a, 0, 0, 0, 8, 0 };
            uint8_t buf[8];
            buf[0] = static_cast<uint8_t>(opcode);
            buf[1] = 0;
            buf[2] = (ch == 2) ? 0 : 4;
            buf[3] = (ch == 2) ? 4 : 0;
            buf[4] = static_cast<uint8_t>(1 << ch);
            buf[5] = 0;
            buf[6] = 0x64;
            buf[7] = 0;

            p->cmd = 0x0a;
            if (pie2_scsi(p, cdb, buf, 8) != 0) {
                pie2_stop_and_cleanup(p);
                return 1;
            }
        }
    }

    // ------------------------------------------------------------------------
    // Phase 3: Dimension Mirroring and SET WINDOW (pie2_sdim / pie2_gwid, lines 2994..3003)
    // ------------------------------------------------------------------------
    if (p->model_id == 0x31) {
        if (p->scan_dpi > 7199) {
            p->opt_height = p->opt_width;
        } else {
            p->opt_height = (p->opt_width + (p->opt_width < 0 ? 1 : 0)) / 2;
        }
    }

    int piem_idx = p->piem_index;
    const PIE_MODEL* piem = (piem_idx >= 0 && piem_idx < 40) ? &_ZL4piem[piem_idx] : nullptr;

    if (piem && (piem->field_18 & (1 << mode))) {
        int max_bound = p->max_y;
        if (piem->feeder_type == 3) {
            if (mode == 0) {
                max_bound = p->res_table[1]; // +0x30
            } else if (p->status_buf[10] & 1) {
                max_bound = p->res_table[3]; // +0x38
            }
        }
        int new_w = max_bound - 1 - x_start;
        int new_x = max_bound - 1 - width;
        x_start = new_x;
        width = new_w;
    }

    // SCSI 0x0a SET WINDOW (14 bytes)
    {
        uint8_t cdb[6] = { 0x0a, 0, 0, 0, 0x0e, 0 };
        uint8_t buf[14];
        buf[0] = 0x12;
        buf[1] = 0;
        buf[2] = 0x0a;
        buf[3] = 0;
        buf[4] = 0x80;
        buf[5] = 0;
        buf[6]  = static_cast<uint8_t>(x_start & 0xff);
        buf[7]  = static_cast<uint8_t>((x_start >> 8) & 0xff);
        buf[8]  = static_cast<uint8_t>(y_start & 0xff);
        buf[9]  = static_cast<uint8_t>((y_start >> 8) & 0xff);
        buf[10] = static_cast<uint8_t>(width & 0xff);
        buf[11] = static_cast<uint8_t>((width >> 8) & 0xff);
        buf[12] = static_cast<uint8_t>(height & 0xff);
        buf[13] = static_cast<uint8_t>((height >> 8) & 0xff);

        p->cmd = 0x0a;
        if (pie2_scsi(p, cdb, buf, 14) != 0) {
            pie2_stop_and_cleanup(p);
            return 1;
        }
    }

    // ------------------------------------------------------------------------
    // Phase 4: AFE Gain (pie2_snsa), Step Calculation, and Exposure (pie2_sexp, lines 3007..3029)
    // ------------------------------------------------------------------------
    int local_off_r = off_r;
    if (piem && piem->field_18 != 0) {
        int clamped_gain = local_off_r;
        if (clamped_gain < 1) clamped_gain = 1;
        if (clamped_gain > 16) clamped_gain = 16;

        uint8_t cdb[6] = { 0x0a, 0, 0, 0, 6, 0 };
        uint8_t buf[6] = { 0x17, 0, 2, 0, 0, static_cast<uint8_t>(clamped_gain) };

        p->cmd = 0x0a;
        pie2_scsi(p, cdb, buf, 6);
    } else {
        local_off_r = 1;
    }

    int step = 0;
    if (res_x != 0) {
        if (scan_dpi > 2500 || p->model_id == 0x24 || p->model_id == 0x26 || p->model_id == 0x27) {
            step = 0;
        } else {
            step = 1;
        }
    } else {
        step = 0;
    }
    p->width_pixels = step;

    if (pie2_sexp(p, exp_r, exp_g, exp_b, exp_i, off_r, off_g) != 0) {
        pie2_stop_and_cleanup(p);
        return 1;
    }

    // ------------------------------------------------------------------------
    // Phase 5: MODE SELECT (pie2_msel inlined, lines 839..921)
    // ------------------------------------------------------------------------
    uint8_t msel_buf[16];
    std::memset(msel_buf, 0, sizeof(msel_buf));
    msel_buf[0] = 0;
    msel_buf[1] = 0x0f;
    msel_buf[2] = static_cast<uint8_t>(scan_dpi & 0xff);
    msel_buf[3] = static_cast<uint8_t>((scan_dpi >> 8) & 0xff);

    if (channels == 4) {
        msel_buf[4] = 0x90;
    } else {
        msel_buf[4] = (channels == 1) ? 0x04 : 0x80;
    }

    if (bits > 15) {
        msel_buf[5] = 0x20;
    } else if (bits > 11) {
        msel_buf[5] = 0x10;
    } else if (bits >= 10) {
        msel_buf[5] = 0x08;
    } else {
        msel_buf[5] = 0x04;
    }

    msel_buf[6] = (channels != 1) ? 0x04 : 0x01;

    if ((p->model_id == 0x24 || p->model_id == 0x26 || p->model_id == 0x27) && off_g) {
        msel_buf[7] |= 0x01;
    }

    msel_buf[8] = 0x01;

    int feeder = piem ? piem->feeder_type : 0;
    if (feeder != 3 && channels == 4) {
        if (scan_dpi != 3600 && !(feeder == 4 && (scan_dpi == 5000 || scan_dpi == 10000)) && scan_dpi != 7200) {
            msel_buf[9] |= 0x80;
        }
    }

    if (exp_r) {
        msel_buf[10] |= 0x04;
    }
    if (off_g) {
        if (feeder == 3 && mode == 1) {
            msel_buf[10] |= 0x20;
            msel_buf[9]  |= 0x08;
        }
    } else {
        msel_buf[9] |= 0x08;
    }

    if (feeder == 2 && res_y) {
        msel_buf[10] |= 0x08;
    }

    if (feeder == 4) {
        msel_buf[12] |= 0x41;
    }

    if (p->model_id != 0x24 && off_b) {
        if (p->model_id != 0x26 && p->model_id != 0x27) {
            if (p->step != 0) {
                msel_buf[12] |= 0x01;
            }
        }
    }

    if (!off_g && p->model_id == 0x31) {
        msel_buf[12] |= 0x02;
    }
    msel_buf[13] |= 0x80;

    if (res_x || exp_r) {
        msel_buf[14] |= 0x20;
    } else if (local_off_r > 1) {
        msel_buf[14] |= 0x10;
    }

    {
        uint8_t cdb[6] = { 0x15, 0, 0, 0, 0x10, 0 };
        p->cmd = 0x15;
        if (pie2_scsi(p, cdb, msel_buf, 16) != 0) {
            pie2_stop_and_cleanup(p);
            return 1;
        }
    }

    // ------------------------------------------------------------------------
    // Phase 6: Autofocus / Feed Mechanics and SCAN Start (pie2_mfoc / pie2_star, lines 3037..3068)
    // ------------------------------------------------------------------------
    if (feeder == 2) {
        if (p->status_buf[4] <= 1) {
            pie2_stop_and_cleanup(p);
            return 1;
        }
        int pos = (res_y != 0) ? -1000 : p->focus_step_min;
        if (res_y != 0) {
            p->focus_step_min = -1000;
            p->focus_step_max = 1;
            p->focus_metric = 0.0;
        }
        if (pos > 1000) pos = 1000;
        if (pos < -1000) pos = -1000;

        int range = p->status_buf[4] - 1;
        int steps = ((pos + 1000) * range) / 1000 + 1;
        if (pie2_fdri(p, 16, steps) != 0) {
            pie2_stop_and_cleanup(p);
            return 1;
        }
    }

    if (feeder == 3 && mode == 1) {
        off_g = 0;
    }

    uint8_t cdb_star[6] = { 0x1b, 0, 0, 0, 1, 0 };
    p->cmd = 0x1b;
    int star_res = pie2_scsi(p, cdb_star, nullptr, 0);
    if (star_res != 0 && star_res != 0x0e) {
        pie2_stop_and_cleanup(p);
        return 1;
    }

    // Test Unit Ready wait loop after START
    {
        int t = user_time();
        for (;;) {
            uint8_t cdb_tur[6] = { 0, 0, 0, 0, 0, 0 };
            p->cmd = 0;
            int r = pie2_scsi(p, cdb_tur, nullptr, 0);
            if (r == static_cast<int>(0x80000004)) {
                if (user_time() - t > 59) {
                    pie2_stop_and_cleanup(p);
                    return 1;
                }
                user_wait(500);
                continue;
            }
            if (r != 0) {
                pie2_stop_and_cleanup(p);
                return 1;
            }
            break;
        }
    }

    if (star_res == 0x0e) {
        off_g = 1;
        int t = user_time();
        for (;;) {
            uint8_t cdb_tur[6] = { 0, 0, 0, 0, 0, 0 };
            p->cmd = 0;
            int r = pie2_scsi(p, cdb_tur, nullptr, 0);
            if (r == static_cast<int>(0x80000004)) {
                if (user_time() - t > 59) break;
                user_wait(500);
                continue;
            }
            break;
        }
    }

    // ------------------------------------------------------------------------
    // Phase 7: Preview / Calibration Pass & Shading Upload (pie2_scal / pie2_ssha, lines 3070..3132)
    // ------------------------------------------------------------------------
    if (off_g != 0) {
        p->cal_stat0 = 0;
        if (pie2_sexp(p, exp_r, exp_g, exp_b, exp_i, off_r, off_g) != 0) {
            pie2_stop_and_cleanup(p);
            return 1;
        }

        bool do_cal = (flags != 0 && ctx1 != nullptr);
        if (do_cal) {
            p->line_count = 0;
            p->field_d4 = 0;
            std::memset(p->scanline_accum, 0, sizeof(p->scanline_accum));
        }

        int rch = (channels == 1) ? 1 : p->max_channels;
        int rlin_stat = pie2_rlin(
            p,
            0,
            ctx1,
            cb1,
            name1,
            1,
            1,
            0,
            1,
            0,
            0,
            p->opt_width,
            p->opt_height,
            p->opt_y_start,
            rch,
            p->opt_x_start
        );
        if (rlin_stat != 0) {
            pie2_stop_and_cleanup(p);
            return 1;
        }

        {
            int t = user_time();
            for (;;) {
                uint8_t cdb_tur[6] = { 0, 0, 0, 0, 0, 0 };
                p->cmd = 0;
                int r = pie2_scsi(p, cdb_tur, nullptr, 0);
                if (r == static_cast<int>(0x80000004)) {
                    if (user_time() - t > 59) break;
                    user_wait(500);
                    continue;
                }
                break;
            }
        }

        if (do_cal && p->line_count > 0) {
            for (int c = 0; c < p->max_channels; ++c) {
                p->cal_white[c] = 0;
                for (int x = 0; x < p->opt_height; ++x) {
                    uint32_t sum = p->scanline_accum[c][x];
                    uint32_t avg = sum / static_cast<uint32_t>(p->line_count);
                    if (avg > 0xffff) avg = 0xffff;
                    if (avg > p->cal_white[c]) {
                        p->cal_white[c] = static_cast<uint16_t>(avg);
                    }
                    p->cal_line_buf[c][x] = static_cast<uint16_t>(avg);
                }
            }
            p->state_8c = 0;
            p->height_pixels = mode;
            p->bytes_per_line = rch;
        }

        if (p->model_id == 0x24 || p->model_id == 0x26 || p->model_id == 0x27) {
            if (p->line_count == 0) {
                for (int c = 0; c < 3; ++c) {
                    for (int x = 0; x < p->opt_height; ++x) {
                        p->cal_line_buf[c][x] = 0x7fff;
                    }
                }
            }

            {
                int t = user_time();
                for (;;) {
                    uint8_t cdb_tur[6] = { 0, 0, 0, 0, 0, 0 };
                    p->cmd = 0;
                    int r = pie2_scsi(p, cdb_tur, nullptr, 0);
                    if (r == static_cast<int>(0x80000004)) {
                        if (user_time() - t > 59) {
                            pie2_stop_and_cleanup(p);
                            return 1;
                        }
                        user_wait(500);
                        continue;
                    }
                    if (r != 0) {
                        pie2_stop_and_cleanup(p);
                        return 1;
                    }
                    break;
                }
            }

            int scale_mode = 0;
            if (p->val_58 == 1) scale_mode = 1;
            else if (p->val_58 == 2) scale_mode = 3;
            else if (p->val_58 == 3) scale_mode = 7;

            uint16_t max_sample = 0;
            for (int c = 0; c < 3; ++c) {
                for (int x = 0; x < p->opt_height; ++x) {
                    if (p->cal_line_buf[c][x] > max_sample) {
                        max_sample = p->cal_line_buf[c][x];
                    }
                }
            }

            size_t ssha_len = (static_cast<size_t>(p->opt_height) * 3 + 5) * 2;
            uint8_t* ssha_buf = static_cast<uint8_t*>(std::malloc(ssha_len));
            if (!ssha_buf) {
                pie2_stop_and_cleanup(p);
                return 1;
            }

            uint16_t* words = reinterpret_cast<uint16_t*>(ssha_buf);
            words[0] = 0x16;
            words[1] = static_cast<uint16_t>(ssha_len - 4);
            size_t widx = 2;
            int threshold = (scale_mode != 0) ? (max_sample / (scale_mode + 1)) : 0;

            for (int c = 0; c < 3; ++c) {
                words[widx++] = static_cast<uint16_t>(2 << c);
                for (int x = 0; x < p->opt_height; ++x) {
                    if (scale_mode == 0) {
                        words[widx++] = max_sample;
                    } else {
                        uint16_t sample = p->cal_line_buf[c][x];
                        if (sample <= threshold) {
                            words[widx++] = max_sample;
                        } else {
                            int32_t num = static_cast<int32_t>(max_sample - sample) * static_cast<int32_t>(max_sample);
                            int32_t den = static_cast<int32_t>(sample) * scale_mode;
                            words[widx++] = static_cast<uint16_t>(num / den);
                        }
                    }
                }
            }

            uint8_t cdb_ssha[6] = {
                0x0a,
                0,
                static_cast<uint8_t>((ssha_len >> 16) & 0xff),
                static_cast<uint8_t>((ssha_len >> 8) & 0xff),
                static_cast<uint8_t>(ssha_len & 0xff),
                0
            };
            p->cmd = 0x0a;
            int ssha_res = pie2_scsi(p, cdb_ssha, ssha_buf, static_cast<int>(ssha_len));
            std::free(ssha_buf);
            if (ssha_res != 0) {
                pie2_stop_and_cleanup(p);
                return 1;
            }
        }
    }

    // ------------------------------------------------------------------------
    // Phase 8: Gamma LUT and White Level Calibration (pie2_sgam / pie2_gwtl, lines 3138..3176)
    // ------------------------------------------------------------------------
    if (p->model_id != 0x24 && p->model_id != 0x26 && p->model_id != 0x27) {
        {
            int t = user_time();
            for (;;) {
                uint8_t cdb_tur[6] = { 0, 0, 0, 0, 0, 0 };
                p->cmd = 0;
                int r = pie2_scsi(p, cdb_tur, nullptr, 0);
                if (r == static_cast<int>(0x80000004)) {
                    if (user_time() - t > 59) {
                        pie2_stop_and_cleanup(p);
                        return 1;
                    }
                    user_wait(500);
                    continue;
                }
                if (r != 0) {
                    pie2_stop_and_cleanup(p);
                    return 1;
                }
                break;
            }
        }

        int cap = p->cap_48;
        if (cap > 16) cap = 16;
        if (cap < 8) cap = 8;
        int num_entries = 1 << cap;
        size_t gamma_buf_len = static_cast<size_t>(num_entries) * 2 + 6;
        uint8_t* gamma_buf = static_cast<uint8_t*>(std::malloc(gamma_buf_len));
        if (!gamma_buf) {
            pie2_stop_and_cleanup(p);
            return 1;
        }

        uint16_t* gw = reinterpret_cast<uint16_t*>(gamma_buf);
        gw[0] = 0x10;
        gw[1] = static_cast<uint16_t>(gamma_buf_len - 4);

        for (int ch = 0; ch < 3; ++ch) {
            gw[2] = static_cast<uint16_t>(2 << ch);
            for (int i = 0; i < num_entries; ++i) {
                float v = gamm_ltog(static_cast<float>(i) / static_cast<float>(num_entries - 1));
                gw[3 + i] = static_cast<uint16_t>(v * static_cast<float>(num_entries - 1) + 0.5f);
            }

            uint8_t cdb[6] = {
                0x0a,
                0,
                static_cast<uint8_t>((gamma_buf_len >> 16) & 0xff),
                static_cast<uint8_t>((gamma_buf_len >> 8) & 0xff),
                static_cast<uint8_t>(gamma_buf_len & 0xff),
                0
            };
            p->cmd = 0x0a;
            if (pie2_scsi(p, cdb, gamma_buf, static_cast<int>(gamma_buf_len)) != 0) {
                std::free(gamma_buf);
                pie2_stop_and_cleanup(p);
                return 1;
            }
        }
        std::free(gamma_buf);

        p->cal_stat0 = 0;
        if (p->opt_height <= 0) {
            pie2_stop_and_cleanup(p);
            return 1;
        }

        uint8_t* gwtl_buf = static_cast<uint8_t*>(std::malloc(p->opt_height));
        if (!gwtl_buf) {
            pie2_stop_and_cleanup(p);
            return 1;
        }

        uint8_t cdb_18[6] = {
            0x18,
            0,
            static_cast<uint8_t>((p->opt_height >> 16) & 0xff),
            static_cast<uint8_t>((p->opt_height >> 8) & 0xff),
            static_cast<uint8_t>(p->opt_height & 0xff),
            0
        };
        p->cmd = 0x18;
        if (pie2_scsi(p, cdb_18, gwtl_buf, p->opt_height) != 0) {
            std::free(gwtl_buf);
            pie2_stop_and_cleanup(p);
            return 1;
        }

        int lut_idx = 0;
        for (int i = 0; i < p->opt_height; ++i) {
            if (gwtl_buf[i] != 0x70) {
                p->cal_lut[lut_idx++] = static_cast<uint16_t>(i);
            }
        }
        p->cal_stat0 = 1;

        if (feeder == 4) {
            p->cal_stat1 = 0;
            p->cal_stat2 = p->opt_height - 1;
            uint16_t half_white = p->cal_white[0] / 2;
            uint32_t last_val = 0xffff;

            for (int i = 0; i < p->opt_height; ++i) {
                uint16_t mapped_idx = p->cal_lut[i];
                uint16_t sample = p->cal_line_buf[0][mapped_idx];
                if (last_val <= half_white) {
                    if (half_white < sample) {
                        p->cal_stat1 = i;
                    }
                } else {
                    if (half_white >= sample && p->cal_stat1 > 0) {
                        p->cal_stat2 = i;
                    }
                }
                last_val = sample;
            }
        }
        std::free(gwtl_buf);
    }

    // ------------------------------------------------------------------------
    // Phase 9: Main Scan Acquisition (pie2_gdim / pie2_rlin, lines 3179..3228)
    // ------------------------------------------------------------------------
    if (!cb1 || !name1) {
        pie2_stop(p);
        if (p->model_id == 0x24 || p->model_id == 0x26 || p->model_id == 0x27) {
            uint8_t cdb_home[6] = { 0xd2, 0, 0, 0, 4, 0 };
            uint32_t buf = 2;
            p->cmd = 0xd2;
            pie2_scsi(p, cdb_home, reinterpret_cast<uint8_t*>(&buf), 4);
        }
        return 0;
    }

    uint8_t cdb_gdim[6] = { 0x0f, 0, 0, 0, 0x12, 0 };
    uint8_t gdim_buf[18];
    p->cmd = 0x0f;
    if (pie2_scsi(p, cdb_gdim, gdim_buf, 0x12) != 0) {
        pie2_stop_and_cleanup(p);
        return 1;
    }

    int final_w = static_cast<int>(gdim_buf[0]) | (static_cast<int>(gdim_buf[1]) << 8);
    int final_h = static_cast<int>(gdim_buf[2]) | (static_cast<int>(gdim_buf[3]) << 8);

    if (p->model_id == 0x24 || p->model_id == 0x26 || p->model_id == 0x27) {
        if (local_off_r > 1) {
            final_h /= local_off_r;
        }
    }

    {
        int t = user_time();
        for (;;) {
            uint8_t cdb_tur[6] = { 0, 0, 0, 0, 0, 0 };
            p->cmd = 0;
            int r = pie2_scsi(p, cdb_tur, nullptr, 0);
            if (r == static_cast<int>(0x80000004)) {
                if (user_time() - t > 59) break;
                user_wait(500);
                continue;
            }
            break;
        }
    }

    int eff_res_y = res_y;
    if (eff_res_y == 0) {
        eff_res_y = (scan_dpi + 15) / 16;
    }

    int status = 0;
    int rlin_main = pie2_rlin(
        p,
        scan_type,
        ctx2,
        cb2,
        name2,
        y_start,
        flags,
        off_g,
        0,
        0,
        eff_res_y,
        final_w,
        final_h,
        p->opt_y_start,
        channels,
        bits
    );

    if (rlin_main != 0) {
        status = 1;
        uint8_t cdb_stop[6] = { 0x1b, 0, 0, 0, 0, 0 };
        p->cmd = 0x1b;
        pie2_scsi(p, cdb_stop, nullptr, 0);

        if (p->model_id == 0x24 || p->model_id == 0x26 || p->model_id == 0x27) {
            uint8_t cdb_home[6] = { 0xd2, 0, 0, 0, 4, 0 };
            uint32_t buf = 2;
            p->cmd = 0xd2;
            pie2_scsi(p, cdb_home, reinterpret_cast<uint8_t*>(&buf), 4);
        }
    }

    if (feeder == 1) {
        pie2_stop(p);
        status = 0;
    }

    return status;
}

// ============================================================================
// Optional 1800i 3600 DPI Software Upsampling Mod
// ============================================================================
#ifdef ENABLE_1800I_3600DPI_MOD

struct UpsampleContext {
    void *orig_ctx;
    pie2_scan_cb orig_cb;
    unsigned short *prev_line;
    unsigned short *interp_line;
    int line_bytes;
    int current_y;
};

static int upsample_vertical_cb(void *ctx, int y, int width, int bits, int channels, unsigned short *buf) {
    (void)y;
    UpsampleContext *uc = reinterpret_cast<UpsampleContext*>(ctx);
    if (!uc || !uc->orig_cb) return -1;

    int pixels = width * channels;

    if (uc->prev_line && uc->current_y > 0) {
        for (int i = 0; i < pixels; ++i) {
            uc->interp_line[i] = static_cast<unsigned short>((static_cast<int>(uc->prev_line[i]) + static_cast<int>(buf[i])) >> 1);
        }
        int res = uc->orig_cb(uc->orig_ctx, uc->current_y++, width, bits, channels, uc->interp_line);
        if (res != 0) return res;
    }

    int res = uc->orig_cb(uc->orig_ctx, uc->current_y++, width, bits, channels, buf);
    if (res != 0) return res;

    if (uc->prev_line) {
        std::memcpy(uc->prev_line, buf, pixels * sizeof(unsigned short));
    }

    return 0;
}

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
    const char *name1,
    void *ctx2,
    pie2_scan_cb cb2,
    const char *name2,
    int scan_type
) {
    PIE2_T *p = reinterpret_cast<PIE2_T*>(vp);
    if (!p) return -1;

    bool needs_upsampling = (p->ccd_dpi > 0 && scan_dpi > p->ccd_dpi && p->ccd_dpi == 1800);
    int hw_res_x = needs_upsampling ? p->ccd_dpi : res_x;
    int hw_res_y = needs_upsampling ? p->ccd_dpi : res_y;
    int hw_width = needs_upsampling ? (width / 2) : width;
    int hw_height = needs_upsampling ? (height / 2) : height;

    p->scan_dpi = scan_dpi;

    UpsampleContext uc;
    std::memset(&uc, 0, sizeof(uc));
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

    int ret = pie2_lsca(
        p,
        mode,
        bits,
        channels,
        scan_dpi,
        x_start,
        y_start,
        hw_width,
        hw_height,
        hw_res_x,
        hw_res_y,
        exp_r,
        exp_g,
        exp_b,
        exp_i,
        off_r,
        off_g,
        off_b,
        off_i,
        flags,
        effective_ctx,
        effective_cb,
        name1,
        ctx2,
        cb2,
        name2,
        scan_type
    );

    if (needs_upsampling) {
        if (uc.prev_line) std::free(uc.prev_line);
        if (uc.interp_line) std::free(uc.interp_line);
    }

    return ret;
}

#endif // ENABLE_1800I_3600DPI_MOD
