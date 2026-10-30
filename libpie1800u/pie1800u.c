#include "pie1800u.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>

#define USB_TIMEOUT_MS 2000

static int wctl(pie1800_device_t *dev, uint16_t reg, const uint8_t *data, uint16_t len) {
    if (!dev || !dev->handle) return -EINVAL;
    int ret = libusb_control_transfer(dev->handle, 0x40, 0x0c, reg, 0, (unsigned char *)data, len, USB_TIMEOUT_MS);
    return (ret < 0) ? ret : 0;
}

static int wctl_byte(pie1800_device_t *dev, uint16_t reg, uint8_t byte) {
    return wctl(dev, reg, &byte, 1);
}

static int rctl_byte(pie1800_device_t *dev, uint16_t reg, uint8_t *byte_out) {
    if (!dev || !dev->handle || !byte_out) return -EINVAL;
    unsigned char buf[1] = {0};
    int ret = libusb_control_transfer(dev->handle, 0xc0, 0x0c, reg, 0, buf, 1, USB_TIMEOUT_MS);
    if (ret < 0) return ret;
    *byte_out = buf[0];
    return 0;
}

static int ieee_handshake_stage(pie1800_device_t *dev, uint8_t mode) {
    static const uint8_t sync_pattern[] = {0xff, 0xaa, 0x55, 0x00, 0xff, 0x87, 0x78};

    wctl_byte(dev, 0x87, 0x04);
    wctl_byte(dev, 0x87, 0x04);

    for (size_t i = 0; i < sizeof(sync_pattern); i++) {
        wctl_byte(dev, 0x88, sync_pattern[i]);
        wctl_byte(dev, 0x88, sync_pattern[i]);
    }

    wctl_byte(dev, 0x88, mode);
    wctl_byte(dev, 0x88, mode);

    wctl_byte(dev, 0x87, 0x05);
    wctl_byte(dev, 0x87, 0x05);

    wctl_byte(dev, 0x87, 0x04);
    wctl_byte(dev, 0x87, 0x04);

    wctl_byte(dev, 0x88, 0xff);
    wctl_byte(dev, 0x88, 0xff);

    return 0;
}

int pie1800_reg_write(pie1800_device_t *dev, uint8_t reg, uint8_t val) {
    int ret = wctl_byte(dev, 0x83, reg);
    if (ret < 0) return ret;
    return wctl_byte(dev, 0x85, val);
}

int pie1800_reg_read(pie1800_device_t *dev, uint8_t reg, uint8_t *val_out) {
    int ret = wctl_byte(dev, 0x83, reg);
    if (ret < 0) return ret;
    return rctl_byte(dev, 0x84, val_out);
}

int pie1800_wait_idle(pie1800_device_t *dev, int timeout_ms) {
    int waited = 0;
    while (waited < timeout_ms) {
        uint8_t val = 0;
        int ret = pie1800_reg_read(dev, 0x84, &val);
        if (ret == 0 && (val & 0x1e) == 0) {
            return 0; // ASIC idle
        }
        usleep(2000); // 2ms
        waited += 2;
    }
    return -ETIMEDOUT;
}

int pie1800_configure_hardware(pie1800_device_t *dev) {
    static const struct { uint8_t reg; uint8_t val; } init_seq[] = {
        {0xc4, 0x00},
        {0xab, 0xaa},
        {0xac, 0xca},
        {0xad, 0x4b},
        {0xae, 0x05},
        {0xc1, 0x07},
        {0xc2, 0x04},
        {0xc3, 0x12},
        {0xc5, 0x12},
        {0xe1, 0x00},
        {0xe5, 0x00},
        {0xe9, 0x00},
        {0x86, 0x10}
    };

    for (size_t i = 0; i < sizeof(init_seq)/sizeof(init_seq[0]); i++) {
        int ret = pie1800_reg_write(dev, init_seq[i].reg, init_seq[i].val);
        if (ret < 0) return ret;
    }
    return 0;
}

int pie1800_set_exposure(pie1800_device_t *dev, uint16_t red, uint16_t green, uint16_t blue) {
    pie1800_reg_write(dev, 0x9c, red & 0xff);
    pie1800_reg_write(dev, 0x9d, (red >> 8) & 0xff);

    pie1800_reg_write(dev, 0x9e, green & 0xff);
    pie1800_reg_write(dev, 0x9f, (green >> 8) & 0xff);

    pie1800_reg_write(dev, 0xa0, blue & 0xff);
    pie1800_reg_write(dev, 0xa1, (blue >> 8) & 0xff);
    return 0;
}

int pie1800_set_gain(pie1800_device_t *dev, uint8_t red, uint8_t green, uint8_t blue) {
    pie1800_reg_write(dev, 0xe0, red);
    pie1800_reg_write(dev, 0xe4, green);
    pie1800_reg_write(dev, 0xe8, blue);
    return 0;
}

int pie1800_set_offset(pie1800_device_t *dev, uint8_t red, uint8_t green, uint8_t blue) {
    pie1800_reg_write(dev, 0xe2, red);
    pie1800_reg_write(dev, 0xe6, green);
    pie1800_reg_write(dev, 0xea, blue);
    return 0;
}

int pie1800_set_lamp(pie1800_device_t *dev, bool enable) {
    if (!dev) return -EINVAL;
    if (enable) {
        pie1800_reg_write(dev, 0xad, 0x0b);
        pie1800_reg_write(dev, 0x85, 0x30);
        dev->lamp_on = true;
    } else {
        pie1800_reg_write(dev, 0xad, 0x4b);
        pie1800_reg_write(dev, 0x85, 0x10);
        dev->lamp_on = false;
    }
    return 0;
}

int pie1800_move(pie1800_device_t *dev, uint8_t direction, int steps) {
    if (!dev || steps <= 0) return 0;

    // Safety: enforce travel ceiling in forward direction
    if (direction == PIE1800_DIR_FORWARD) {
        if (dev->current_position >= PIE1800_MAX_TRAVEL_STEPS) {
            return 0; // Already at or past mechanical ceiling
        }
        if (dev->current_position + steps > PIE1800_MAX_TRAVEL_STEPS) {
            steps = PIE1800_MAX_TRAVEL_STEPS - dev->current_position;
        }
    }

    pie1800_reg_write(dev, 0x85, direction);
    int remaining = steps;

    while (remaining > 0) {
        uint8_t chunk = (remaining > 200) ? 200 : (uint8_t)remaining;
        pie1800_reg_write(dev, 0x81, chunk);
        pie1800_reg_write(dev, 0x83, 0x01);
        int ret = pie1800_wait_idle(dev, 5000);
        if (ret < 0) return ret;

        remaining -= chunk;
        if (direction == PIE1800_DIR_FORWARD) {
            dev->current_position += chunk;
        } else {
            dev->current_position -= chunk;
            if (dev->current_position < 0) dev->current_position = 0;
        }
        usleep(4000); // 4ms inter-chunk delay
    }
    // Disarm motor driver / enter standby mode
    pie1800_reg_write(dev, 0x85, 0x10);
    return 0;
}

int pie1800_home(pie1800_device_t *dev) {
    if (!dev) return -EINVAL;
    // Retract carriage back to dock (up to 2800 steps to guarantee mechanical dock if position was lost)
    int steps_to_home = (dev->current_position > 0) ? dev->current_position : 2800;
    int ret = pie1800_move(dev, PIE1800_DIR_BACKWARD, steps_to_home);
    dev->current_position = 0;
    return ret;
}

int pie1800_scan_line(pie1800_device_t *dev, uint16_t *buffer) {
    if (!dev || !buffer) return -EINVAL;

    // Trigger optical exposure integration
    pie1800_reg_write(dev, 0x85, 0x12);
    pie1800_reg_write(dev, 0x81, 0x00);
    int ret = pie1800_wait_idle(dev, 5000);
    if (ret < 0) return ret;

    // Reset window end & read pointer
    pie1800_reg_write(dev, 0x90, 0x00);
    pie1800_reg_write(dev, 0x91, 0x00);
    pie1800_reg_write(dev, 0x92, 0x00);
    pie1800_reg_write(dev, 0x93, 0x00);
    pie1800_reg_write(dev, 0x94, 0x00);
    pie1800_reg_write(dev, 0x95, 0x00);
    pie1800_wait_idle(dev, 2000);

    // Arm DMA transfer for 16,200 bytes on register 0x82
    wctl_byte(dev, 0x83, 0x80);
    uint8_t desc[8] = {0x00, 0x00, 0x00, 0x00,
                       (uint8_t)(PIE1800_LINE_BYTES & 0xff),
                       (uint8_t)((PIE1800_LINE_BYTES >> 8) & 0xff),
                       (uint8_t)((PIE1800_LINE_BYTES >> 16) & 0xff),
                       (uint8_t)((PIE1800_LINE_BYTES >> 24) & 0xff)};
    ret = wctl(dev, 0x82, desc, sizeof(desc));
    if (ret < 0) return ret;

    // Read bulk data from Bulk IN Endpoint 0x81
    int transferred = 0;
    ret = libusb_bulk_transfer(dev->handle, PIE1800_EP_IN, (unsigned char *)buffer,
                               PIE1800_LINE_BYTES, &transferred, 4000);
    if (ret < 0) return ret;
    if (transferred != PIE1800_LINE_BYTES) return -EIO;

    return 0;
}

int pie1800_init(pie1800_device_t *dev) {
    if (!dev) return -EINVAL;

    // Enable GL640USB transceiver
    wctl_byte(dev, 0x8b, 0x00);
    usleep(50000);
    wctl_byte(dev, 0x8b, 0x40);
    usleep(50000);

    // 3-Stage IEEE 1284.4 Handshake
    ieee_handshake_stage(dev, 0x30);
    usleep(20000);
    ieee_handshake_stage(dev, 0x00);
    usleep(20000);
    ieee_handshake_stage(dev, 0x80); // EPP Data Mode
    usleep(20000);

    // Basic ASIC register setup
    int ret = pie1800_configure_hardware(dev);
    if (ret < 0) return ret;

    // Default exposure (2900 clocks = 0x0b54)
    pie1800_set_exposure(dev, 2900, 2900, 2900);

    // Default gains (0x1f = max gain) and offsets
    pie1800_set_gain(dev, 0x1f, 0x1f, 0x1f);
    pie1800_set_offset(dev, 0x02, 0x02, 0x02);

    // Exposure limits (0xa2..0xaa = 0xff)
    uint8_t dummy = 0;
    pie1800_reg_read(dev, 0x87, &dummy);
    for (uint8_t r = 0xa2; r <= 0xaa; r++) {
        pie1800_reg_write(dev, r, 0xff);
    }

    // CCD Sampling Gate & Clock Generator (0x10003e72)
    pie1800_reg_write(dev, 0x98, 0x01);
    pie1800_reg_write(dev, 0x99, 0x00);
    pie1800_reg_write(dev, 0x9a, 0x8d);
    pie1800_reg_write(dev, 0x9b, 0x2a);

    // Initial homing to calibrate physical position 0
    pie1800_home(dev);

    return 0;
}

int pie1800_open(pie1800_device_t **dev_out, libusb_context *ctx) {
    if (!dev_out) return -EINVAL;

    pie1800_device_t *dev = (pie1800_device_t *)calloc(1, sizeof(pie1800_device_t));
    if (!dev) return -ENOMEM;

    if (!ctx) {
        if (libusb_init(&dev->ctx) < 0) {
            free(dev);
            return -EIO;
        }
        dev->own_context = true;
    } else {
        dev->ctx = ctx;
        dev->own_context = false;
    }

    dev->handle = libusb_open_device_with_vid_pid(dev->ctx, PIE1800_VID, PIE1800_PID);
    if (!dev->handle) {
        if (dev->own_context) libusb_exit(dev->ctx);
        free(dev);
        return -ENODEV;
    }

    // Detach kernel driver if active
    if (libusb_kernel_driver_active(dev->handle, 0) == 1) {
        libusb_detach_kernel_driver(dev->handle, 0);
    }

    // Claim interface 0
    libusb_claim_interface(dev->handle, 0);

    *dev_out = dev;
    return 0;
}

void pie1800_close(pie1800_device_t *dev) {
    if (!dev) return;

    // Safely return home and shut off lamp
    if (dev->current_position > 0) {
        pie1800_home(dev);
    }
    if (dev->lamp_on) {
        pie1800_set_lamp(dev, false);
    }

    if (dev->handle) {
        libusb_release_interface(dev->handle, 0);
        libusb_close(dev->handle);
        dev->handle = NULL;
    }

    if (dev->own_context && dev->ctx) {
        libusb_exit(dev->ctx);
        dev->ctx = NULL;
    }

    free(dev);
}
