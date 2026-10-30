#include "sane-pie1800u.h"
#include "../libpie1800u/pie1800u.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define BACKEND_NAME "pie1800u"

enum {
    OPT_NUM_OPTS = 0,
    OPT_MODE_GROUP,
    OPT_MODE,
    OPT_RESOLUTION,
    OPT_PREVIEW,
    OPT_GEOMETRY_GROUP,
    OPT_TL_X,
    OPT_TL_Y,
    OPT_BR_X,
    OPT_BR_Y,
    NUM_OPTIONS
};

static const SANE_Device s_device = {
    .name = "pie1800u:libusb:05e3:0120",
    .vendor = "Pacific Image Electronics",
    .model = "PrimeFilm 1800u / 1800i",
    .type = "film scanner"
};

static const SANE_Device *s_device_list[2] = {
    &s_device,
    NULL
};

typedef struct {
    pie1800_device_t *hw;
    SANE_Parameters params;
    SANE_Option_Descriptor opt[NUM_OPTIONS];
    SANE_Word val[NUM_OPTIONS];

    bool scanning;
    int current_line;
    int total_lines;
    int offset_steps;

    uint16_t *line_buf;
    uint8_t *converted_line;
    int line_bytes_remaining;
    int line_offset;
} pie1800_session_t;

static const SANE_String_Const s_scan_modes[] = {
    "Color",
    "Color Negative",
    NULL
};

static const SANE_Word s_resolutions[] = {
    2,    // Count of elements
    1800, // Native 1800 DPI
    900   // Sub-sampled
};

static void init_options(pie1800_session_t *s) {
    memset(s->opt, 0, sizeof(s->opt));

    s->opt[OPT_NUM_OPTS].name = SANE_NAME_NUM_OPTIONS;
    s->opt[OPT_NUM_OPTS].title = "Number of options";
    s->opt[OPT_NUM_OPTS].desc = "Read-only option count";
    s->opt[OPT_NUM_OPTS].type = SANE_TYPE_INT;
    s->opt[OPT_NUM_OPTS].size = sizeof(SANE_Word);
    s->opt[OPT_NUM_OPTS].cap = SANE_CAP_SOFT_DETECT;
    s->val[OPT_NUM_OPTS] = NUM_OPTIONS;

    // Mode Group
    s->opt[OPT_MODE_GROUP].title = "Scan Mode Options";
    s->opt[OPT_MODE_GROUP].type = SANE_TYPE_GROUP;

    s->opt[OPT_MODE].name = SANE_NAME_SCAN_MODE;
    s->opt[OPT_MODE].title = "Scan mode";
    s->opt[OPT_MODE].desc = "Select color positive or negative film";
    s->opt[OPT_MODE].type = SANE_TYPE_STRING;
    s->opt[OPT_MODE].size = 32;
    s->opt[OPT_MODE].cap = SANE_CAP_SOFT_SELECT | SANE_CAP_SOFT_DETECT;
    s->opt[OPT_MODE].constraint_type = SANE_CONSTRAINT_STRING_LIST;
    s->opt[OPT_MODE].constraint.string_list = s_scan_modes;
    s->val[OPT_MODE] = 0; // "Color"

    s->opt[OPT_RESOLUTION].name = SANE_NAME_SCAN_RESOLUTION;
    s->opt[OPT_RESOLUTION].title = "Scan resolution";
    s->opt[OPT_RESOLUTION].desc = "Optical resolution in DPI";
    s->opt[OPT_RESOLUTION].type = SANE_TYPE_INT;
    s->opt[OPT_RESOLUTION].unit = SANE_UNIT_DPI;
    s->opt[OPT_RESOLUTION].size = sizeof(SANE_Word);
    s->opt[OPT_RESOLUTION].cap = SANE_CAP_SOFT_SELECT | SANE_CAP_SOFT_DETECT;
    s->opt[OPT_RESOLUTION].constraint_type = SANE_CONSTRAINT_WORD_LIST;
    s->opt[OPT_RESOLUTION].constraint.word_list = s_resolutions;
    s->val[OPT_RESOLUTION] = 1800;
}

SANE_Status sane_pie1800u_init(SANE_Int *version_code, SANE_Auth_Callback authorize) {
    (void)authorize;
    if (version_code) {
        *version_code = SANE_VERSION_CODE(SANE_CURRENT_MAJOR, SANE_CURRENT_MINOR, 0);
    }
    return SANE_STATUS_GOOD;
}

void sane_pie1800u_exit(void) {}

SANE_Status sane_pie1800u_get_devices(const SANE_Device ***device_list, SANE_Bool local_only) {
    (void)local_only;
    if (!device_list) return SANE_STATUS_INVAL;

    // Probe USB device
    pie1800_device_t *dev = NULL;
    int ret = pie1800_open(&dev, NULL);
    if (ret < 0) {
        static const SANE_Device *empty_list[1] = {NULL};
        *device_list = empty_list;
        return SANE_STATUS_GOOD;
    }
    pie1800_close(dev);

    *device_list = s_device_list;
    return SANE_STATUS_GOOD;
}

SANE_Status sane_pie1800u_open(SANE_String_Const devicename, SANE_Handle *handle) {
    if (!handle) return SANE_STATUS_INVAL;
    (void)devicename;

    pie1800_session_t *s = (pie1800_session_t *)calloc(1, sizeof(pie1800_session_t));
    if (!s) return SANE_STATUS_NO_MEM;

    int ret = pie1800_open(&s->hw, NULL);
    if (ret < 0) {
        free(s);
        return SANE_STATUS_IO_ERROR;
    }

    ret = pie1800_init(s->hw);
    if (ret < 0) {
        pie1800_close(s->hw);
        free(s);
        return SANE_STATUS_IO_ERROR;
    }

    init_options(s);

    s->line_buf = (uint16_t *)malloc(PIE1800_LINE_BYTES);
    s->converted_line = (uint8_t *)malloc(PIE1800_LINE_PIXELS * 3);
    s->offset_steps = 1380; // Calibrated film aperture offset (~19.5 mm)

    *handle = (SANE_Handle)s;
    return SANE_STATUS_GOOD;
}

void sane_pie1800u_close(SANE_Handle handle) {
    pie1800_session_t *s = (pie1800_session_t *)handle;
    if (!s) return;

    if (s->scanning) {
        sane_pie1800u_cancel(handle);
    }

    if (s->hw) {
        pie1800_close(s->hw);
        s->hw = NULL;
    }
    free(s->line_buf);
    free(s->converted_line);
    free(s);
}

const SANE_Option_Descriptor *sane_pie1800u_get_option_descriptor(SANE_Handle handle, SANE_Int option) {
    pie1800_session_t *s = (pie1800_session_t *)handle;
    if (!s || option < 0 || option >= NUM_OPTIONS) return NULL;
    return &s->opt[option];
}

SANE_Status sane_pie1800u_control_option(SANE_Handle handle, SANE_Int option, SANE_Action action,
                                         void *value, SANE_Int *info) {
    pie1800_session_t *s = (pie1800_session_t *)handle;
    if (!s) return SANE_STATUS_INVAL;

    if (info) *info = 0;

    if (action == SANE_ACTION_GET_VALUE) {
        if (!value) return SANE_STATUS_INVAL;
        if (option == OPT_MODE) {
            strcpy((char *)value, s_scan_modes[s->val[OPT_MODE]]);
        } else if (option < NUM_OPTIONS) {
            *(SANE_Word *)value = s->val[option];
        }
        return SANE_STATUS_GOOD;
    }

    if (action == SANE_ACTION_SET_VALUE) {
        if (!value) return SANE_STATUS_INVAL;
        if (option == OPT_RESOLUTION) {
            s->val[OPT_RESOLUTION] = *(SANE_Word *)value;
            if (info) *info |= SANE_INFO_RELOAD_PARAMS;
            return SANE_STATUS_GOOD;
        } else if (option == OPT_MODE) {
            const char *str = (const char *)value;
            if (strcmp(str, "Color Negative") == 0) s->val[OPT_MODE] = 1;
            else s->val[OPT_MODE] = 0;
            return SANE_STATUS_GOOD;
        }
    }

    return SANE_STATUS_GOOD;
}

SANE_Status sane_pie1800u_get_parameters(SANE_Handle handle, SANE_Parameters *params) {
    pie1800_session_t *s = (pie1800_session_t *)handle;
    if (!s || !params) return SANE_STATUS_INVAL;

    params->format = SANE_FRAME_RGB;
    params->last_frame = SANE_TRUE;
    params->pixels_per_line = PIE1800_LINE_PIXELS;
    params->lines = 875; // Verified physical frame length (875 steps from offset 1380 = 2255 max)
    params->depth = 8;
    params->bytes_per_line = PIE1800_LINE_PIXELS * 3;

    s->params = *params;
    return SANE_STATUS_GOOD;
}

SANE_Status sane_pie1800u_start(SANE_Handle handle) {
    pie1800_session_t *s = (pie1800_session_t *)handle;
    if (!s || !s->hw) return SANE_STATUS_INVAL;

    pie1800_set_lamp(s->hw, true);
    usleep(1500000); // 1.5s warm-up

    if (s->offset_steps > 0) {
        pie1800_move(s->hw, PIE1800_DIR_FORWARD, s->offset_steps);
    }

    s->scanning = true;
    s->current_line = 0;
    s->total_lines = s->params.lines > 0 ? s->params.lines : 1800;
    s->line_bytes_remaining = 0;
    s->line_offset = 0;

    return SANE_STATUS_GOOD;
}

SANE_Status sane_pie1800u_read(SANE_Handle handle, SANE_Byte *data, SANE_Int max_length, SANE_Int *length) {
    pie1800_session_t *s = (pie1800_session_t *)handle;
    if (!s || !data || !length) return SANE_STATUS_INVAL;
    *length = 0;

    if (!s->scanning) return SANE_STATUS_CANCELLED;
    if (s->current_line >= s->total_lines && s->line_bytes_remaining == 0) {
        return SANE_STATUS_EOF;
    }

    int bytes_copied = 0;

    while (bytes_copied < max_length) {
        if (s->line_bytes_remaining == 0) {
            if (s->current_line >= s->total_lines) {
                break;
            }

            int ret = pie1800_scan_line(s->hw, s->line_buf);
            if (ret < 0) return SANE_STATUS_IO_ERROR;

            // Deplanarize 14-bit ADC samples (Planar R, G, B) to 8-bit Interleaved RGB
            bool is_negative = (s->val[OPT_MODE] == 1);
            for (int x = 0; x < PIE1800_LINE_PIXELS; x++) {
                int r_s = s->line_buf[x] >> 2;
                int g_s = s->line_buf[PIE1800_LINE_PIXELS + x] >> 2;
                int b_s = s->line_buf[PIE1800_LINE_PIXELS * 2 + x] >> 2;

                int vr = (r_s * 255) / 4095;
                int vg = (g_s * 255) / 4095;
                int vb = (b_s * 255) / 4095;

                vr = (vr > 255) ? 255 : (vr < 0 ? 0 : vr);
                vg = (vg > 255) ? 255 : (vg < 0 ? 0 : vg);
                vb = (vb > 255) ? 255 : (vb < 0 ? 0 : vb);

                if (is_negative) {
                    vr = 255 - vr;
                    vg = 255 - vg;
                    vb = 255 - vb;
                }

                s->converted_line[x * 3 + 0] = (uint8_t)vr;
                s->converted_line[x * 3 + 1] = (uint8_t)vg;
                s->converted_line[x * 3 + 2] = (uint8_t)vb;
            }

            pie1800_move(s->hw, PIE1800_DIR_FORWARD, 1);
            s->current_line++;
            s->line_bytes_remaining = PIE1800_LINE_PIXELS * 3;
            s->line_offset = 0;
        }

        int chunk = max_length - bytes_copied;
        if (chunk > s->line_bytes_remaining) {
            chunk = s->line_bytes_remaining;
        }

        memcpy(data + bytes_copied, s->converted_line + s->line_offset, chunk);
        bytes_copied += chunk;
        s->line_offset += chunk;
        s->line_bytes_remaining -= chunk;
    }

    *length = bytes_copied;
    return SANE_STATUS_GOOD;
}

void sane_pie1800u_cancel(SANE_Handle handle) {
    pie1800_session_t *s = (pie1800_session_t *)handle;
    if (!s || !s->hw) return;

    s->scanning = false;
    pie1800_home(s->hw);
    pie1800_set_lamp(s->hw, false);
}

SANE_Status sane_pie1800u_set_io_mode(SANE_Handle handle, SANE_Bool non_blocking) {
    (void)handle;
    if (non_blocking) return SANE_STATUS_UNSUPPORTED;
    return SANE_STATUS_GOOD;
}

SANE_Status sane_pie1800u_get_select_fd(SANE_Handle handle, SANE_Int *fd) {
    (void)handle;
    (void)fd;
    return SANE_STATUS_UNSUPPORTED;
}

/* ======================================================================
   Standard SANE API Forwarding Wrappers
   Ensures compatibility whether SANE accesses symbols with or without prefix
   ====================================================================== */

SANE_Status sane_init(SANE_Int *version_code, SANE_Auth_Callback authorize) {
    return sane_pie1800u_init(version_code, authorize);
}

void sane_exit(void) {
    sane_pie1800u_exit();
}

SANE_Status sane_get_devices(const SANE_Device ***device_list, SANE_Bool local_only) {
    return sane_pie1800u_get_devices(device_list, local_only);
}

SANE_Status sane_open(SANE_String_Const devicename, SANE_Handle *handle) {
    return sane_pie1800u_open(devicename, handle);
}

void sane_close(SANE_Handle handle) {
    sane_pie1800u_close(handle);
}

const SANE_Option_Descriptor *sane_get_option_descriptor(SANE_Handle handle, SANE_Int option) {
    return sane_pie1800u_get_option_descriptor(handle, option);
}

SANE_Status sane_control_option(SANE_Handle handle, SANE_Int option, SANE_Action action,
                                void *value, SANE_Int *info) {
    return sane_pie1800u_control_option(handle, option, action, value, info);
}

SANE_Status sane_get_parameters(SANE_Handle handle, SANE_Parameters *params) {
    return sane_pie1800u_get_parameters(handle, params);
}

SANE_Status sane_start(SANE_Handle handle) {
    return sane_pie1800u_start(handle);
}

SANE_Status sane_read(SANE_Handle handle, SANE_Byte *data, SANE_Int max_length, SANE_Int *length) {
    return sane_pie1800u_read(handle, data, max_length, length);
}

void sane_cancel(SANE_Handle handle) {
    sane_pie1800u_cancel(handle);
}

SANE_Status sane_set_io_mode(SANE_Handle handle, SANE_Bool non_blocking) {
    return sane_pie1800u_set_io_mode(handle, non_blocking);
}

SANE_Status sane_get_select_fd(SANE_Handle handle, SANE_Int *fd) {
    return sane_pie1800u_get_select_fd(handle, fd);
}

