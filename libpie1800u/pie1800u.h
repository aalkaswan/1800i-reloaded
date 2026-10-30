#ifndef PIE1800U_H
#define PIE1800U_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <libusb-1.0/libusb.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PIE1800_VID              0x05e3
#define PIE1800_PID              0x0120
#define PIE1800_EP_IN            0x81

#define PIE1800_OPTICAL_DPI      1800
#define PIE1800_LINE_PIXELS      2700
#define PIE1800_CHANNELS         3
#define PIE1800_BYTES_PER_SAMPLE 2
#define PIE1800_LINE_BYTES       (PIE1800_LINE_PIXELS * PIE1800_CHANNELS * PIE1800_BYTES_PER_SAMPLE) // 16,200 bytes

#define PIE1800_DIR_FORWARD      0x16  // Advance into scanner bay
#define PIE1800_DIR_BACKWARD     0x14  // Retract toward home stop

#define PIE1800_MAX_TRAVEL_STEPS 2260  // Verified physical rail limit (~31.9 mm travel from home stop)

typedef struct {
    libusb_context *ctx;
    libusb_device_handle *handle;
    bool own_context;
    int current_position; // Estimated motor steps from home
    bool lamp_on;
} pie1800_device_t;

/**
 * Open scanner device and claim interface.
 */
int pie1800_open(pie1800_device_t **dev_out, libusb_context *ctx);

/**
 * Initialize GL640USB bridge transceiver and 3-stage IEEE 1284.4 handshake.
 */
int pie1800_init(pie1800_device_t *dev);

/**
 * Low-level register access.
 */
int pie1800_reg_write(pie1800_device_t *dev, uint8_t reg, uint8_t val);
int pie1800_reg_read(pie1800_device_t *dev, uint8_t reg, uint8_t *val_out);
int pie1800_wait_idle(pie1800_device_t *dev, int timeout_ms);

/**
 * Hardware configuration and calibration registers.
 */
int pie1800_configure_hardware(pie1800_device_t *dev);
int pie1800_set_exposure(pie1800_device_t *dev, uint16_t red, uint16_t green, uint16_t blue);
int pie1800_set_gain(pie1800_device_t *dev, uint8_t red, uint8_t green, uint8_t blue);
int pie1800_set_offset(pie1800_device_t *dev, uint8_t red, uint8_t green, uint8_t blue);

/**
 * Lamp on/off control.
 */
int pie1800_set_lamp(pie1800_device_t *dev, bool enable);

/**
 * Carriage stepper motor control.
 * Steps are in 1/1800 inch increments (14.1 um).
 */
int pie1800_move(pie1800_device_t *dev, uint8_t direction, int steps);
int pie1800_home(pie1800_device_t *dev);
bool pie1800_is_home(pie1800_device_t *dev);

/**
 * Acquire one complete optical line (16,200 bytes / 8,100 uint16_t RGB samples).
 * buffer must be at least PIE1800_LINE_BYTES bytes (8,100 uint16_t words).
 */
int pie1800_scan_line(pie1800_device_t *dev, uint16_t *buffer);

/**
 * Close scanner, turn lamp off, and release USB interface.
 */
void pie1800_close(pie1800_device_t *dev);

#ifdef __cplusplus
}
#endif

#endif /* PIE1800U_H */
