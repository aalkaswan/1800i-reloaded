// ============================================================================
// pie2_rlin.cpp - High-Fidelity Decompilation of Core PIE2 Scanline Engine
//
// Decompiled from /tmp/vuescan/vuescan ELF32 binary (lines 783–2981):
// 1. pie2_rlin (0x0065afc0..0x0065be7f) - Main scanline acquisition engine
// 2. pie2_fdri (0x0065be80..0x0065c08f) - Film drive & mechanical transport
// 3. pie2_gsst (0x0065c090..0x0065c24f) - Get scanner status & button events
// 4. pie2_poll (0x0065c250..0x0065c54f) - Periodic polling thread callback
// ============================================================================

#if __has_include("pie2_common.h")
#include "pie2_common.h"
#elif __has_include("/tmp/vuescan/decomp/pie2_common.h")
#include "/tmp/vuescan/decomp/pie2_common.h"
#endif

// ----------------------------------------------------------------------------
// Internal inlined helper functions for pie2_rlin
// ----------------------------------------------------------------------------

// Wait until scanner finishes command or reaches idle state (inlined pie2_wait)
static int pie2_wait_inline(PIE2_T* p, int timeout_sec) {
    if (!p) return 1;
    if (p->command_code == 0) return 0;

    int start = user_time();
    while (p->command_code != 0) {
        if (user_time() - start > timeout_sec) {
            return 1;
        }
        user_wait(500);
        if (p->command_code == 0) break;

        uint8_t cdb[6] = {0};
        p->command_code = 0;
        int status = pie2_scsi(p, cdb, nullptr, 0);
        if (status == static_cast<int>(0x80000004)) {
            continue;
        }
        if (status != 0) {
            return 1;
        }
        break;
    }
    return 0;
}

// Inlined shading calibration correction (pie2_asha: lines 2439..2483)
// Implements the 4 calls to 64-bit integer division (__divdi3) and floating-point math
static void pie2_asha_inline(PIE2_T* p, unsigned short* line_buf, int width, int channels) {
    if (p->line_count_total <= 0 || channels <= 0 || width <= 0) {
        return;
    }

    uint16_t base0 = p->cal_base[0];
    uint16_t base1 = (channels > 1) ? p->cal_base[1] : 0;
    uint16_t base2 = (channels > 2) ? p->cal_base[2] : 0;
    uint16_t base3 = (channels > 3) ? p->cal_base[3] : 0;

    uint32_t max_base = base0;
    if (base1 > max_base) max_base = base1;
    if (base2 > max_base) max_base = base2;

    int32_t cal_c4 = p->cal_c4;

    uint16_t* cal_lut = p->cal_lut;
    uint16_t* tab0 = p->shading_tab0;
    uint16_t* tab1 = p->shading_tab1;
    uint16_t* tab2 = p->shading_tab2;
    uint16_t* tab3 = p->shading_tab3;

    for (int x = 0; x < width; ++x) {
        uint16_t lut_idx = cal_lut[x];

        // Channel 0 (Red)
        if (channels > 0) {
            uint16_t cal_val = tab0[lut_idx];
            if (cal_val != 0) {
                int64_t num = static_cast<int64_t>(line_buf[x * 4 + 0]) * max_base;
                int64_t res = num / cal_val;
                if (res < 0) res = 0;
                else if (res > 0xffff) res = 0xffff;
                line_buf[x * 4 + 0] = static_cast<uint16_t>(res);
            }
        }

        // Channel 1 (Green)
        if (channels > 1) {
            uint16_t cal_val = tab1[lut_idx];
            if (cal_val != 0) {
                int64_t num = static_cast<int64_t>(line_buf[x * 4 + 1]) * max_base;
                int64_t res = num / cal_val;
                if (cal_c4 != 0) {
                    // Floating-point math at 0x0065b98a: fild, fmul 2.5f, fistp with truncation
                    res = static_cast<int64_t>(static_cast<double>(res) * 2.5);
                }
                if (res < 0) res = 0;
                else if (res > 0xffff) res = 0xffff;
                line_buf[x * 4 + 1] = static_cast<uint16_t>(res);
            }
        }

        // Channel 2 (Blue)
        if (channels > 2) {
            uint16_t cal_val = tab2[lut_idx];
            if (cal_val != 0) {
                int64_t num = static_cast<int64_t>(line_buf[x * 4 + 2]) * max_base;
                int64_t res = num / cal_val;
                if (cal_c4 != 0) {
                    // Floating-point math at 0x0065ba62: fild, fmul 3.5f, fistp with truncation
                    res = static_cast<int64_t>(static_cast<double>(res) * 3.5);
                }
                if (res < 0) res = 0;
                else if (res > 0xffff) res = 0xffff;
                line_buf[x * 4 + 2] = static_cast<uint16_t>(res);
            }
        }

        // Channel 3 (Infrared)
        if (channels > 3) {
            uint16_t cal_val = tab3[lut_idx];
            if (cal_val != 0) {
                int64_t num = static_cast<int64_t>(line_buf[x * 4 + 3]) * base3;
                int64_t res = num / cal_val;
                if (res < 0) res = 0;
                else if (res > 0xffff) res = 0xffff;
                line_buf[x * 4 + 3] = static_cast<uint16_t>(res);
            }
        }
    }
}

// Inlined horizontal mirror swap (pie2_amir: lines 2530..2541)
static void pie2_amir_inline(PIE2_T* p, unsigned short* src, int width) {
    if (width <= 0) return;
    uint16_t* dst = reinterpret_cast<uint16_t*>(p->mirror_buf);
    for (int i = 0; i < width; ++i) {
        int src_idx = (width - 1 - i) * 4;
        int dst_idx = i * 4;
        dst[dst_idx + 0] = src[src_idx + 0];
        dst[dst_idx + 1] = src[src_idx + 1];
        dst[dst_idx + 2] = src[src_idx + 2];
        dst[dst_idx + 3] = src[src_idx + 3];
    }
}

// Inlined 2x horizontal resolution interpolation (pie2_adbl: lines 2556..2580)
// Matches assembly 0x0065bcf0..0x0065bd75: computes intermediate pixels across all 4 channels
static int pie2_adbl_inline(PIE2_T* p, unsigned short* src, int width) {
    if (width <= 0) return width;
    uint16_t* dst = reinterpret_cast<uint16_t*>(p->line_buf2);

    // Pass 1: Spread pixels across even indices
    for (int i = 0; i < width; ++i) {
        int dst_idx = i * 8; // 2 * i * 4 shorts
        int src_idx = i * 4;
        dst[dst_idx + 0] = src[src_idx + 0];
        dst[dst_idx + 1] = src[src_idx + 1];
        dst[dst_idx + 2] = src[src_idx + 2];
        dst[dst_idx + 3] = src[src_idx + 3];
    }

    // Pass 2: Interpolate intermediate pixels (0x0065bcf0..0x0065bd6c)
    int total_width = width * 2;
    for (int x = 2; x < total_width + 2; x += 2) {
        int right_idx = (x < total_width) ? x : (x - 2);
        int p0 = (x - 2) * 4;
        int p1 = (x - 1) * 4;
        int p2 = right_idx * 4;

        dst[p1 + 0] = static_cast<uint16_t>((static_cast<int16_t>(dst[p0 + 0]) + static_cast<int16_t>(dst[p2 + 0])) >> 1);
        dst[p1 + 1] = static_cast<uint16_t>((static_cast<int16_t>(dst[p0 + 1]) + static_cast<int16_t>(dst[p2 + 1])) >> 1);
        dst[p1 + 2] = static_cast<uint16_t>((static_cast<int16_t>(dst[p0 + 2]) + static_cast<int16_t>(dst[p2 + 2])) >> 1);
        dst[p1 + 3] = static_cast<uint16_t>((static_cast<int16_t>(dst[p0 + 3]) + static_cast<int16_t>(dst[p2 + 3])) >> 1);
    }

    return total_width;
}

// Inlined gamma / grayscale LUT lookup (pie2_agra: lines 2506..2516)
static void pie2_agra_inline(unsigned short* line_buf, int width) {
    for (int i = 0; i < width; ++i) {
        int idx = i * 4;
        uint32_t r = line_buf[idx + 0];
        uint32_t g = line_buf[idx + 1];
        uint32_t b = line_buf[idx + 2];
        uint16_t gray = static_cast<uint16_t>((r + g + b) / 3);
        line_buf[idx + 0] = gray;
        line_buf[idx + 1] = gray;
        line_buf[idx + 2] = gray;
    }
}

// ============================================================================
// 1. pie2_rlin (0x0065afc0..0x0065be7f)
// Reads scanlines via SCSI READ(6) (0x08), multi-channel circular buffer
// unpacking, shading correction, horizontal mirror swap, 2x resolution
// interpolation, and delivery via scanline callback.
// ============================================================================

int pie2_rlin(
    PIE2_T *p,                                           // eax / param 1
    int pass,                                            // edx / param 2
    void *context,                                       // ecx / param 3
    int (*cb)(void*, int, int, int, int, unsigned short*), // [esp+0x100] / param 4
    char const *name,                                    // [esp+0x104] / param 5
    int y_start,                                         // [esp+0x108] / param 6
    int flags,                                           // [esp+0x10c] / param 7
    int lines_to_read,                                   // [esp+0x110] / param 8
    int y_step,                                          // [esp+0x114] / param 9
    int shading_mode,                                    // [esp+0x118] / param 10
    int preview_flag,                                    // [esp+0x11c] / param 11
    int width,                                           // [esp+0x120] / param 12
    int interleave,                                      // [esp+0x124] / param 13
    int channels,                                        // [esp+0x128] / param 14
    int bits_per_sample,                                 // [esp+0x12c] / param 15
    int mirror                                           // [esp+0x130] / param 16
) {
    if (!p) return 1;

    // Line 2608: Initial wait loop for scanner ready state
    if (pie2_wait_inline(p, 59) != 0) {
        return 1;
    }

    // Lines 2613..2615: Reset channel line tracking counters and status table
    p->chan_line_count[0] = 0;
    p->chan_line_count[1] = 0;
    p->chan_line_count[2] = 0;
    p->chan_line_count[3] = 0;
    p->status_a0108 = 0;
    p->status_a010c = 0;
    std::memset(reinterpret_cast<char*>(p) + 0xa0108, 0, 128);

    // Line 2623: Multi-exposure factor / stride parameter
    int param_24 = 3;
    if (name == nullptr) {
        param_24 = y_start;
    }

    // Line 2632: Bytes per line per channel calculation
    int bytes_per_sample = (bits_per_sample > 8) ? 2 : 1;
    int bytes_per_line_channel = width * bytes_per_sample;
    int param_14 = 1;

    if (channels > 1) {
        bytes_per_line_channel += 2; // 2-byte packet channel header
        param_14 = 1;
    } else {
        if ((flags & 1) != 0 || channels != 1) {
            param_14 = 1;
        } else {
            bytes_per_line_channel *= 3;
            param_14 = 3;
        }
    }

    // Line 2644: Lines per chunk factor
    int lines_per_chunk_factor = 3 * param_24;
    if (channels > 3) {
        lines_per_chunk_factor += 1;
    }

    int total_lines_to_read = lines_to_read * interleave;

    // Line 2656: Determine transfer packet size for SCSI READ(6)
    int chunk_size = 0x40000; // 256 KB default
    if (p->is_usb != 0) {
        if (p->model_id == 0x31) {
            // PrimeFilm 7200: check 7200 DPI (0x1c20 at 0x0065bdbd)
            if (p->scan_dpi == 0x1c20) {
                chunk_size = 0x400000; // 4 MB chunk
            } else {
                chunk_size = 0x100000; // 1 MB chunk
            }
        } else {
            chunk_size = 0x100000; // 1 MB chunk
        }
    }

    if (total_lines_to_read <= 0) {
        return 0;
    }

    // Line 2693: Buffer sizing limits and HDR blending weights
    bool has_name_or_ystart = (name != nullptr) || (y_start > 1);
    int factor_16 = lines_per_chunk_factor << 4; // 16 * lines_per_chunk_factor

    int clamped_factor = lines_per_chunk_factor * y_step;
    if (clamped_factor > 255) {
        clamped_factor = 255;
    }
    int max_lines_per_read = chunk_size / bytes_per_line_channel;
    if (max_lines_per_read > clamped_factor) {
        max_lines_per_read = clamped_factor;
    }

    // Line 2827: HDR / multi-exposure blending weights calculation
    int div_5c = 0;
    int div_80 = 0;
    int ecx_64 = 0;
    int div_60 = 0;
    if (name != nullptr) {
        intptr_t name_val = reinterpret_cast<intptr_t>(name);
        int edx = static_cast<int>(name_val) - 1;
        int eax = (edx < 0) ? (edx + 1) / 2 : edx / 2;
        div_5c = eax + 2;
        div_80 = eax + 1;
        ecx_64 = static_cast<int>(name_val) - eax + 1;
        div_60 = ecx_64 + div_5c;
    }

    uint8_t pass_mask = static_cast<uint8_t>(1 << (pass & 0x1f));
    bool do_mirror = false;
    if (p->piem_index >= 0 && p->piem_index < 40) {
        if (_ZL4piem[p->piem_index].flags & pass_mask) {
            do_mirror = true;
        }
    }
    if (mirror != 0) {
        do_mirror = !do_mirror;
    }

    int lines_remaining = total_lines_to_read;
    int sub_line_idx[4] = {0, 0, 0, 0};
    int current_y = 0;

    while (lines_remaining > 0) {
        int chunk_lines = lines_remaining;
        if (has_name_or_ystart) {
            if (chunk_lines > factor_16) {
                chunk_lines = factor_16;
            }
        }
        if (chunk_lines > max_lines_per_read) {
            chunk_lines = max_lines_per_read;
        }
        // Round to multiple of lines_per_chunk_factor
        chunk_lines = (chunk_lines / lines_per_chunk_factor) * lines_per_chunk_factor;
        if (chunk_lines <= 0) {
            chunk_lines = 1;
        }

        int read_bytes = chunk_lines * bytes_per_line_channel;
        uint8_t* read_buf = static_cast<uint8_t*>(std::malloc(read_bytes));
        if (!read_buf) {
            lines_remaining -= chunk_lines;
            if (lines_to_read != 0 && sema_canc()) {
                return lines_to_read;
            }
            continue;
        }

        // Send SCSI READ(6) (opcode 0x08)
        uint8_t cdb[6] = {
            0x08,
            0x00,
            static_cast<uint8_t>((chunk_lines >> 16) & 0xff),
            static_cast<uint8_t>((chunk_lines >> 8) & 0xff),
            static_cast<uint8_t>(chunk_lines & 0xff),
            0x00
        };
        p->command_code = 0x08;
        int status = pie2_scsi(p, cdb, read_buf, read_bytes);
        if (status != 0) {
            std::free(read_buf);
            return 1;
        }

        // Unpack multi-channel circular buffers (+0x10820c / +0xa0188)
        uint8_t* ptr = read_buf;
        uint8_t* chan_base = reinterpret_cast<uint8_t*>(p) + 0xa0188;

        for (int line_idx = 0; line_idx < chunk_lines; ++line_idx) {
            int channel = 0;
            bool channel_tag_found = false;

            if (channels > 1) {
                uint8_t tag = *ptr;
                ptr += 2; // skip 2-byte channel header tag
                if (tag == 'R' || tag == '@') {
                    channel = 0;
                    channel_tag_found = true;
                } else if (tag == 'G' || tag == 'P') {
                    channel = 1;
                    channel_tag_found = true;
                } else if (tag == 'B') {
                    channel = 2;
                    channel_tag_found = true;
                } else if (tag == '`') {
                    channel = 3;
                    channel_tag_found = true;
                }
            } else {
                channel = 0;
            }

            int slot = p->chan_line_count[channel] & 0x7f;
            uint16_t* slot_buf = reinterpret_cast<uint16_t*>(chan_base + slot * width * 8);

            int sub_pass = sub_line_idx[channel];

            for (int x = 0; x < width; ++x) {
                uint16_t sample = 0;
                if (bits_per_sample <= 8) {
                    uint8_t raw = *ptr;
                    if (p->model_id == 0x24 || p->model_id == 0x26 || p->model_id == 0x27) {
                        sample = p->lut_10a8194[raw];
                    } else {
                        sample = static_cast<uint16_t>(raw << (p->bits_per_pixel - 8));
                    }
                    ptr += param_14;
                } else {
                    sample = *reinterpret_cast<uint16_t*>(ptr);
                    ptr += param_14 * 2;
                }

                if (channel == 3) {
                    // Infrared stored directly
                    slot_buf[x * 4 + 3] = sample;
                } else if (name != nullptr) {
                    // Weighted HDR blending
                    if (sub_pass == 0) {
                        slot_buf[x * 4 + channel] = sample;
                    } else if (sub_pass == 1) {
                        if (sample <= 0xefff) {
                            uint32_t val = (sample / div_80) * div_80;
                            slot_buf[x * 4 + channel] = static_cast<uint16_t>((slot_buf[x * 4 + channel] + val) / div_5c);
                        }
                    } else {
                        if (sample <= 0xefff) {
                            uint32_t val = (sample / ecx_64) * ecx_64;
                            slot_buf[x * 4 + channel] = static_cast<uint16_t>((slot_buf[x * 4 + channel] * div_5c + val) / div_60);
                        }
                    }
                } else {
                    // Multi-exposure averaging
                    if (param_24 > 1) {
                        sample = sample / param_24;
                    }
                    if (sub_pass == 0) {
                        slot_buf[x * 4 + channel] = sample;
                    } else {
                        slot_buf[x * 4 + channel] += sample;
                    }
                }
            }

            sub_pass++;
            if (sub_pass < param_24 && !channel_tag_found) {
                sub_line_idx[channel] = sub_pass;
            } else {
                sub_line_idx[channel] = 0;
                uint8_t* ready_slot = reinterpret_cast<uint8_t*>(p) + 0xa0108 + slot;
                *ready_slot |= static_cast<uint8_t>(1 << channel);
                p->chan_line_count[channel]++;

                uint8_t required_mask = 1;
                if (channels != 1) {
                    required_mask = (channels != 3) ? 15 : 7;
                }

                if (*ready_slot == required_mask) {
                    *ready_slot = 0;

                    // Complete scanline assembled in slot_buf
                    uint16_t* cur_line = slot_buf;
                    int cur_width = width;

                    // 1. Shading calibration
                    if (shading_mode != 0) {
                        pie2_asha_inline(p, cur_line, cur_width, channels);
                    }

                    // 2. Horizontal mirror
                    if (do_mirror) {
                        pie2_amir_inline(p, cur_line, cur_width);
                        cur_line = reinterpret_cast<uint16_t*>(p->mirror_buf);
                    }

                    // 3. 2x horizontal resolution interpolation (p->ccd_dpi < p->scan_dpi)
                    if (p->ccd_dpi < p->scan_dpi) {
                        cur_width = pie2_adbl_inline(p, cur_line, cur_width);
                        cur_line = reinterpret_cast<uint16_t*>(p->line_buf2);
                    }

                    // 4. Gamma LUT / Grayscale conversion
                    if (preview_flag != 0) {
                        pie2_agra_inline(cur_line, cur_width);
                    }

                    // 5. Scanline callback
                    if (cb != nullptr) {
                        int ret = cb(context, current_y, cur_width, p->bits_per_pixel, (preview_flag != 0 ? preview_flag : channels), cur_line);
                        (void)ret;
                    }
                    current_y++;
                }
            }
        }

        std::free(read_buf);
        lines_remaining -= chunk_lines;

        if (lines_to_read != 0 && sema_canc()) {
            return lines_to_read;
        }
    }

    return 0;
}

// ============================================================================
// 2. pie2_fdri (0x0065be80..0x0065c08f)
// Film drive and motorized transport control command (SCSI opcode 0xd1).
// ============================================================================

int pie2_fdri(PIE2_T* pie2, int action, int steps) {
    if (!pie2) return 1;

    if (pie2->piem_index >= 0 && pie2->piem_index < 40) {
        if (_ZL4piem[pie2->piem_index].field_10 == 2 && action != 0x10) {
            pie2->field_98 = 0;
        }
    }

    if (action & 0x86) {
        pie2->field_84 = 0;
    }

    int start_time = user_time();
    uint8_t cdb[6] = {0};

    // If scanner has an active command pending, wait until unit is ready
    if (pie2->command_code != 0) {
        while (true) {
            if (user_time() - start_time > 59) {
                return 1;
            }
            user_wait(500);
            if (pie2->command_code == 0) break;

            std::memset(cdb, 0, sizeof(cdb));
            pie2->command_code = 0;
            int status = pie2_scsi(pie2, cdb, nullptr, 0);
            if (status == static_cast<int>(0x80000004)) continue;
            if (status == 0) break;
            return 1;
        }
    }

    // Execute Film Drive command (0xd1)
    uint8_t buf[4] = {
        static_cast<uint8_t>(action & 0xff),
        static_cast<uint8_t>(steps & 0xff),
        static_cast<uint8_t>((steps >> 8) & 0xff),
        0
    };
    cdb[0] = 0xd1;
    cdb[1] = 0; cdb[2] = 0; cdb[3] = 0;
    cdb[4] = 4;
    cdb[5] = 0;
    pie2->command_code = 0xd1;

    int status = pie2_scsi(pie2, cdb, buf, 4);
    if (status != 0) {
        return 1;
    }

    // Wait for mechanical movement to complete
    if (pie2->command_code != 0) {
        int wait_start = user_time();
        while (true) {
            if (user_time() - wait_start > 59) {
                return 1;
            }
            user_wait(500);
            if (pie2->command_code == 0) break;

            std::memset(cdb, 0, sizeof(cdb));
            pie2->command_code = 0;
            status = pie2_scsi(pie2, cdb, nullptr, 0);
            if (status == static_cast<int>(0x80000004)) continue;
            if (status != 0) return 1;
            break;
        }
    }

    if (action == 8) {
        return 0;
    }
    return (pie2_gsst(pie2) != 0) ? 1 : 0;
}

// ============================================================================
// 3. pie2_gsst (0x0065c090..0x0065c24f)
// Gets scanner mechanical status and button events (SCSI opcode 0xdd).
// ============================================================================

int pie2_gsst(PIE2_T* pie2) {
    if (!pie2) return 1;

    pie2->command_code = 0xdd;
    uint8_t cdb[6] = { 0xdd, 0, 0, 0, 0, 0 };

    int model_f10   = 0;
    int feeder_type = 0;
    int has_button  = 0;

    if (pie2->piem_index >= 0 && pie2->piem_index < 40) {
        model_f10   = _ZL4piem[pie2->piem_index].field_10;
        feeder_type = _ZL4piem[pie2->piem_index].feeder_type;
        has_button  = _ZL4piem[pie2->piem_index].field_c;
    }

    // Command length is 8 or 11 bytes depending on model family
    int len = 8;
    int diff = model_f10 - 3;
    if (diff < 2) {
        len = 11;
    }
    cdb[4] = static_cast<uint8_t>(len);

    int status = pie2_scsi(pie2, cdb, pie2->status_buf, len);
    if (status != 0) {
        pie2->status_buf[5] = 1; // Mark hardware error flag
        return 1;
    }

    if (feeder_type == 1) {
        if (pie2->status_buf[5] == 0) {
            int frame_count = pie2->status_buf[2] + 1;
            if (pie2->field_84 != 0 && frame_count != pie2->field_84) {
                pie2->field_80 += (frame_count - pie2->field_84);
            }
            if (pie2->field_80 < 0) pie2->field_80 = 0;
            pie2->field_84 = frame_count;
        }
    } else if (feeder_type == 2) {
        if (pie2->status_buf[5] == 0) {
            int st = pie2->status_buf[6] & 7;
            if (st == 5) {
                int frame_count = pie2->status_buf[2] + 1;
                if (pie2->field_84 != 0 && frame_count != pie2->field_84) {
                    pie2->field_80 += (frame_count - pie2->field_84);
                }
                if (pie2->field_80 < 0) pie2->field_80 = 0;
                pie2->field_84 = frame_count;
            } else {
                pie2->field_84 = 0;
                pie2->curr_frame = 0;
                pie2->max_frames = 50;
            }
        }
    }

    if (has_button != 0) {
        if (pie2->status_buf[0] & 1) {
            pie2->button_pressed |= 1;
        }
    }

    if (feeder_type == 2) {
        if (pie2->status_buf[6] & 0x40) {
            pie2_fdri(pie2, 8, 1);
        }
    }

    return 0;
}

// ============================================================================
// 4. pie2_poll (0x0065c250..0x0065c54f)
// Periodic polling worker invoked by background thread to monitor buttons.
// ============================================================================

int pie2_poll(void* handle, int* status_out) {
    PIE2_T* pie2 = static_cast<PIE2_T*>(handle);
    if (!pie2) return 0;

    pie2_gsst(pie2);

    int model_f10 = 0;
    int has_button = 0;
    if (pie2->piem_index >= 0 && pie2->piem_index < 40) {
        model_f10  = _ZL4piem[pie2->piem_index].field_10;
        has_button = _ZL4piem[pie2->piem_index].field_c;
    }

    if (has_button != 0) {
        if (status_out) {
            *status_out = pie2->button_pressed;
        }
        pie2->button_pressed = 0;
    }

    if (model_f10 <= 1) {
        return (pie2->status_buf[5] == 0) ? 1 : 0;
    } else if (model_f10 == 2) {
        if (pie2->status_buf[5] == 0 && (pie2->status_buf[6] & 3) == 1) {
            return 1;
        }
        pie2->field_98 = 0;
        return 0;
    } else if (model_f10 == 3) {
        if (pie2->status_buf[5] != 0) {
            return 0;
        }
        return (pie2->status_buf[9] & 7) != 0 ? 1 : 0;
    } else if (model_f10 == 4) {
        if (pie2->status_buf[5] != 0) {
            return 1;
        }
        return (pie2->status_buf[9] & 3) == 0 ? 1 : 0;
    }

    return 1;
}
