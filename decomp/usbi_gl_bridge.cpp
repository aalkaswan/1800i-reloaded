// Decompiled from vuescan (vues/usbi.cpp, vues/pies.cpp, vues/scsi.cpp)
// Genesys Logic 0x05e3 (GL646 / GL841) USB-to-SCSI Bridge Transport
// Used by PIE film scanners (e.g. 05e3:0120 PF2700, 05e3:0129 PF1800U, etc.)

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <algorithm>

// USB Request Constants for Genesys Logic GL646 / GL841 Bridge
#define GL_REQ_REG_READ        0x0c   // Read bridge register
#define GL_REQ_REG_WRITE       0x0c   // Write bridge register
#define GL_REQ_DMA_SETUP       0x04   // Setup DMA / bulk transfer count

#define GL_REG_STATUS          0x84   // Status / response register (IN)
#define GL_REG_DATA            0x85   // Data register / CDB byte (OUT)
#define GL_REG_CONTROL         0x87   // Control register
#define GL_REG_HANDSHAKE       0x88   // IEEE 1284.4 handshake register

#define GL_STATUS_GOOD         0x00   // Command completed, no data
#define GL_STATUS_DATA_IN      0x01   // Device ready to transmit data to host
#define GL_STATUS_CHECK_COND   0x02   // SCSI check condition
#define GL_STATUS_BUSY         0x03   // Device busy / retry

#define USB_DIR_OUT            0x00   // Host to Device
#define USB_DIR_IN             0x80   // Device to Host
#define USB_TYPE_VENDOR        (0x02 << 5)
#define USB_RECIP_DEVICE       0x00

#define USB_CTRL_OUT           (USB_DIR_OUT | USB_TYPE_VENDOR | USB_RECIP_DEVICE) // 0x40
#define USB_CTRL_IN            (USB_DIR_IN  | USB_TYPE_VENDOR | USB_RECIP_DEVICE) // 0xc0

// Forward declaration of internal VueScan structures
struct PROB_T;

struct USBI_DEVICE_T {
    void* usb_handle;                 // OS usb device handle (libusb_device_handle*)
    int vid;                          // Vendor ID (e.g. 0x05e3)
    int pid;                          // Product ID (e.g. 0x0120)
    int ep_in;                        // Bulk IN endpoint address (e.g. 0x81)
    int ep_out;                       // Bulk OUT endpoint address (e.g. 0x02)
    int ep_int;                       // Interrupt endpoint
    int max_packet_size;              // Max bulk transfer size (0xfe00 or 0x100000)
    int timeout_ms;                   // Timeout in milliseconds
    int status;                       // Last bridge status
};

struct USBI_T {
    int num_devices;
    USBI_DEVICE_T devices[8];
    void* private_data;
};

// Low-level simulated USB primitives matching VueScan's runtime
extern "C" {
    int usb_control_msg(void* dev, int requesttype, int request,
                        int value, int index, char* bytes, int size, int timeout);
    int usb_bulk_read(void* dev, int ep, char* bytes, int size, int timeout);
    int usb_bulk_write(void* dev, int ep, char* bytes, int size, int timeout);
    int usb_clear_halt(void* dev, int ep);
    int usb_resetep(void* dev, int ep);
    void user_wait(int milliseconds);
}

// ---------------------------------------------------------------------------
// 1. usbi_ireq: Send USB vendor control request to the bridge
// ---------------------------------------------------------------------------
int usbi_ireq(USBI_T* usbi, int dev_idx, uint8_t req_type, uint8_t req,
              uint16_t value, uint16_t index, void* data, uint16_t len, int timeout) {
    if (!usbi || dev_idx < 0 || dev_idx >= usbi->num_devices) {
        return -1;
    }
    USBI_DEVICE_T* dev = &usbi->devices[dev_idx];
    if (!dev->usb_handle) {
        return -1;
    }
    return usb_control_msg(dev->usb_handle,
                           req_type,
                           req,
                           value,
                           index,
                           static_cast<char*>(data),
                           len,
                           timeout > 0 ? timeout : dev->timeout_ms);
}

// Helper: Write 1 byte to GL bridge register
static inline int usbi_write_reg(USBI_T* usbi, int dev_idx, uint8_t reg, uint8_t val) {
    uint8_t byte_val = val;
    return usbi_ireq(usbi, dev_idx, USB_CTRL_OUT, GL_REQ_REG_WRITE, reg, 0, &byte_val, 1, 1000);
}

// Helper: Read 1 byte from GL bridge register
static inline int usbi_read_reg(USBI_T* usbi, int dev_idx, uint8_t reg, uint8_t* out_val) {
    uint8_t byte_val = 0;
    int ret = usbi_ireq(usbi, dev_idx, USB_CTRL_IN, GL_REQ_REG_READ, reg, 0, &byte_val, 1, 1000);
    if (ret >= 0 && out_val) {
        *out_val = byte_val;
    }
    return ret;
}

// ---------------------------------------------------------------------------
// 2. pies_ieee: IEEE 1284.4 / EPP Handshake initialization (0x00669030)
// ---------------------------------------------------------------------------
int pies_ieee(USBI_T* usbi, int dev_idx, uint8_t mode) {
    // Magic 1284 handshake pattern
    static const uint8_t magic[7] = { 0xff, 0xaa, 0x55, 0x00, 0xff, 0x87, 0x78 };
    for (int i = 0; i < 7; i++) {
        if (usbi_write_reg(usbi, dev_idx, GL_REG_HANDSHAKE, magic[i]) < 0) {
            return -1;
        }
    }

    // Set negotiation mode (e.g. 0x30 or 0xe0)
    if (usbi_write_reg(usbi, dev_idx, GL_REG_HANDSHAKE, mode) < 0) {
        return -1;
    }

    // Brief stabilization delay (20ms in VueScan)
    // usbi_write_reg control pulses
    if (usbi_write_reg(usbi, dev_idx, GL_REG_CONTROL, 0x05) < 0) return -1;
    if (usbi_write_reg(usbi, dev_idx, GL_REG_CONTROL, 0x04) < 0) return -1;
    if (usbi_write_reg(usbi, dev_idx, GL_REG_HANDSHAKE, 0xff) < 0) return -1;

    user_wait(20);

    return 0;
}

// ---------------------------------------------------------------------------
// 3. usbi_icmd: Issue SCSI Command Descriptor Block (CDB) to bridge
// ---------------------------------------------------------------------------
int usbi_icmd(USBI_T* usbi, int dev_idx, const uint8_t* cdb, int cdb_len) {
    if (!cdb || cdb_len <= 0) return -1;

    // The GL646 accepts SCSI CDB bytes written sequentially to register 0x85
    for (int i = 0; i < cdb_len; i++) {
        int ret = usbi_write_reg(usbi, dev_idx, GL_REG_DATA, cdb[i]);
        if (ret < 0) {
            return ret;
        }
    }
    return 0;
}

// ---------------------------------------------------------------------------
// 4. usbi_irsp: Read bridge status / response byte
// ---------------------------------------------------------------------------
int usbi_irsp(USBI_T* usbi, int dev_idx, uint8_t* status) {
    if (!status) return -1;
    uint8_t st = 0;
    int ret = usbi_read_reg(usbi, dev_idx, GL_REG_STATUS, &st);
    if (ret >= 0) {
        *status = st;
        if (dev_idx >= 0 && dev_idx < usbi->num_devices) {
            usbi->devices[dev_idx].status = st;
        }
    }
    return ret;
}

// ---------------------------------------------------------------------------
// 5. usbi_irda: Read data from scanner (DMA Bulk IN)
// ---------------------------------------------------------------------------
int usbi_irda(USBI_T* usbi, int dev_idx, uint8_t* data, int len) {
    if (!data || len <= 0) return 0;
    USBI_DEVICE_T* dev = &usbi->devices[dev_idx];

    // Determine max transfer packet size based on chip architecture
    int max_chunk = 0xfe00; // Standard GL646: 64KB - 512 bytes
    if ((dev->pid & 0xfff0) == 0x0140) {
        max_chunk = 0x100000; // GL841 / newer high-speed bridge: 1MB
    }

    int bytes_transferred = 0;
    while (bytes_transferred < len) {
        int chunk = std::min(len - bytes_transferred, max_chunk);

        // Setup DMA transfer descriptor (8 bytes)
        uint8_t dma_desc[8];
        std::memset(dma_desc, 0, sizeof(dma_desc));
        dma_desc[0] = static_cast<uint8_t>(chunk & 0xff);
        dma_desc[1] = static_cast<uint8_t>((chunk >> 8) & 0xff);
        dma_desc[2] = static_cast<uint8_t>((chunk >> 16) & 0xff);
        dma_desc[3] = 0x01; // Direction: IN

        int ret = usbi_ireq(usbi, dev_idx, USB_CTRL_OUT, GL_REQ_DMA_SETUP,
                            0x0082, 0x0008, dma_desc, 8, dev->timeout_ms);
        if (ret < 0) {
            return ret;
        }

        // Perform bulk read on Bulk IN endpoint
        int read_bytes = usb_bulk_read(dev->usb_handle,
                                       dev->ep_in ? dev->ep_in : 0x81,
                                       reinterpret_cast<char*>(data + bytes_transferred),
                                       chunk,
                                       dev->timeout_ms);
        if (read_bytes < 0) {
            usb_clear_halt(dev->usb_handle, dev->ep_in);
            usb_resetep(dev->usb_handle, dev->ep_in);
            return read_bytes;
        }
        bytes_transferred += read_bytes;
        if (read_bytes < chunk) {
            break; // Short packet received
        }
    }
    return bytes_transferred;
}

// ---------------------------------------------------------------------------
// 6. usbi_iwda: Write data to scanner (Control or DMA Bulk OUT)
// ---------------------------------------------------------------------------
int usbi_iwda(USBI_T* usbi, int dev_idx, const uint8_t* data, int len) {
    if (!data || len <= 0) return 0;
    USBI_DEVICE_T* dev = &usbi->devices[dev_idx];

    // For short payloads (<= 511 bytes), VueScan writes byte-by-byte via control register 0x85
    if (len <= 0x1ff) {
        for (int i = 0; i < len; i++) {
            if (usbi_write_reg(usbi, dev_idx, GL_REG_DATA, data[i]) < 0) {
                return -1;
            }
        }
        return len;
    }

    // For larger transfers, use DMA Bulk OUT
    int max_chunk = 0xfe00;
    if ((dev->pid & 0xfff0) == 0x0140) {
        max_chunk = 0x100000;
    }

    int bytes_transferred = 0;
    while (bytes_transferred < len) {
        int chunk = std::min(len - bytes_transferred, max_chunk);

        // Setup DMA transfer descriptor
        uint8_t dma_desc[8];
        std::memset(dma_desc, 0, sizeof(dma_desc));
        dma_desc[0] = static_cast<uint8_t>(chunk & 0xff);
        dma_desc[1] = static_cast<uint8_t>((chunk >> 8) & 0xff);
        dma_desc[2] = static_cast<uint8_t>((chunk >> 16) & 0xff);
        dma_desc[3] = 0x00; // Direction: OUT

        int ret = usbi_ireq(usbi, dev_idx, USB_CTRL_OUT, GL_REQ_DMA_SETUP,
                            0x0082, 0x0008, dma_desc, 8, dev->timeout_ms);
        if (ret < 0) {
            return ret;
        }

        // Perform bulk write on Bulk OUT endpoint
        int written = usb_bulk_write(dev->usb_handle,
                                     dev->ep_out ? dev->ep_out : 0x02,
                                     reinterpret_cast<char*>(const_cast<uint8_t*>(data + bytes_transferred)),
                                     chunk,
                                     dev->timeout_ms);
        if (written < 0) {
            usb_clear_halt(dev->usb_handle, dev->ep_out);
            usb_resetep(dev->usb_handle, dev->ep_out);
            return written;
        }
        bytes_transferred += written;
    }
    return bytes_transferred;
}

// ---------------------------------------------------------------------------
// 7. usbi_irsi: Issue REQUEST SENSE and read sense buffer
// ---------------------------------------------------------------------------
int usbi_irsi(USBI_T* usbi, int dev_idx, uint8_t* sense_data, int sense_len) {
    if (!sense_data || sense_len <= 0) return -1;
    std::memset(sense_data, 0, sense_len);

    // Standard 6-byte SCSI REQUEST SENSE command
    uint8_t cdb[6] = { 0x03, 0x00, 0x00, 0x00, static_cast<uint8_t>(sense_len & 0xff), 0x00 };

    if (usbi_icmd(usbi, dev_idx, cdb, 6) < 0) {
        return -1;
    }

    uint8_t status = 0;
    if (usbi_irsp(usbi, dev_idx, &status) < 0) {
        return -1;
    }

    if (status == GL_STATUS_DATA_IN) {
        int read = usbi_irda(usbi, dev_idx, sense_data, sense_len);
        // Read trailing completion status byte
        usbi_irsp(usbi, dev_idx, &status);
        return read;
    }
    return -1;
}

// ---------------------------------------------------------------------------
// 8. scsi_usbi: Top-level SCSI CDB dispatcher to 05e3:0120 (0x00669230)
// ---------------------------------------------------------------------------
int scsi_usbi(USBI_T* usbi, int dev_idx, const uint8_t* cdb, int cdb_len,
              uint8_t* data, int data_len, int direction) {
    if (!usbi || !cdb || cdb_len < 6) {
        return -1;
    }

    // Step 1: Ensure bridge is in negotiated IEEE 1284.4/EPP transfer mode
    if (pies_ieee(usbi, dev_idx, 0xe0) < 0) {
        return 0xff; // Bridge communication error
    }

    // Step 2: Send SCSI CDB (6 bytes)
    if (usbi_icmd(usbi, dev_idx, cdb, cdb_len) < 0) {
        return 0xff;
    }

    // Step 3: Query bridge execution status
    uint8_t status = 0;
    if (usbi_irsp(usbi, dev_idx, &status) < 0) {
        return 0xff;
    }

    // Step 4: Data phase
    if (data && data_len > 0) {
        if (status == GL_STATUS_DATA_IN || direction == 1) {
            // Read data from device
            int r = usbi_irda(usbi, dev_idx, data, data_len);
            if (r < 0) return 0xff;
        } else if (direction == 0) {
            // Write data to device
            int w = usbi_iwda(usbi, dev_idx, data, data_len);
            if (w < 0) return 0xff;
        }
    }

    // Step 5: Read final status byte
    if (usbi_irsp(usbi, dev_idx, &status) < 0) {
        return 0xff;
    }

    // Step 6: Handle check condition if status == 0x02
    if (status == GL_STATUS_CHECK_COND) {
        uint8_t sense[18];
        usbi_irsi(usbi, dev_idx, sense, sizeof(sense));
        return 0x02; // SCSI CHECK CONDITION
    }

    return status; // 0 = SUCCESS (GOOD)
}
