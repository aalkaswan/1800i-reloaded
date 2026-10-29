// Decompiled from vuescan (vues/pied.cpp)
// Diagnostic and descriptor tables for Pacific Image Electronics (PIE) film scanners

#include <cstdint>
#include <cstdio>
#include <cstring>

// Bitmask strings for register flag decoding (0x01eff180)
static const char* _ZL6bitmsk[8] __attribute__((unused)) = {
    ".......1",
    "......1.",
    ".....1..",
    "....1...",
    "...1....",
    "..1.....",
    ".1......",
    "1......."
};

struct PIES_T {
    int sense_key;
    int asc;
    int ascq;
    const char* sense_key_str;
    const char* asc_str;
};

// SCSI Sense code descriptor table (0x01eff1a0, 69 entries)
static const PIES_T _ZL4pies[69] = {
    { 0x00, 0x00, 0x00, "No sense", "" },
    { 0x02, 0x04, 0x01, "Not Ready", "Warming Up" },
    { 0x02, 0x04, 0x02, "Not Ready", "No holder" },
    { 0x02, 0x04, 0x83, "Not Ready", "Need manual service" },
    { 0x02, 0x08, 0x81, "Not Ready", "Communication Time out" },
    { 0x03, 0x53, 0x00, "Media load or eject failed", "Feed or eject paper failure" },
    { 0x03, 0x3a, 0x00, "Media not present", "Paper out" },
    { 0x03, 0x3a, 0x80, "Media not present", "ADF Paper out" },
    { 0x03, 0x3b, 0x05, "Paper Jam", "Paper Jammed" },
    { 0x04, 0x40, 0x81, "RAM failure", "CPU private RAM failure" },
    { 0x04, 0x40, 0x82, "RAM failure", "Scanning system RAM failure" },
    { 0x04, 0x40, 0x83, "RAM failure", "Image Buffer failure" },
    { 0x04, 0x40, 0x84, "RAM failure", "EEPROM failure" },
    { 0x04, 0x04, 0x03, "LUN not ready", "Manual intervention required" },
    { 0x04, 0x62, 0x00, "Scan head position error", "" },
    { 0x04, 0x60, 0x00, "Lamp failure", "Lamp or CCD circuit failure" },
    { 0x04, 0x60, 0x81, "Lamp failure", "Transparency lamp failure" },
    { 0x04, 0x81, 0x80, "Optical system failure", "DC offset or black level calibration failure" },
    { 0x04, 0x81, 0x81, "Optical system failure", "Integration time adjustment failure (too light)" },
    { 0x04, 0x81, 0x82, "Optical system failure", "Integration time adjustment failure (too dark)" },
    { 0x04, 0x81, 0x83, "Optical system failure", "Shading curve adjustment failure" },
    { 0x04, 0x81, 0x84, "Optical system failure", "Gain adjustment failure" },
    { 0x04, 0x81, 0x85, "Optical system failure", "Optical alignment failure" },
    { 0x04, 0x81, 0x86, "Optical system failure", "Optical locating failure" },
    { 0x04, 0x81, 0x87, "Optical system failure", "Scanned pixel mapping to the scanner less than 5100 pixels" },
    { 0x04, 0x47, 0x00, "Parity Error", "Parity error on SCSI bus" },
    { 0x04, 0x4b, 0x00, "Data phase error", "" },
    { 0x05, 0x1a, 0x00, "Parameter list length error", "" },
    { 0x05, 0x2c, 0x01, "Too many windows specified", "" },
    { 0x05, 0x2c, 0x02, "Invalid combination of windows", "" },
    { 0x05, 0x2c, 0x81, "Illegal scanning frame", "" },
    { 0x05, 0x24, 0x00, "Invalid Field in CDB", "Parameter in CDB improper" },
    { 0x05, 0x24, 0x81, "Invalid Field in CDB", "Request too many lines data" },
    { 0x05, 0x20, 0x00, "Invalid Command OP Code", "Not supported SCSI command" },
    { 0x05, 0x25, 0x01, "LUN not supported", "LUN not supported or not connected" },
    { 0x05, 0x26, 0x01, "Parameter not supported", "" },
    { 0x05, 0x26, 0x02, "Parameter value invalid", "Not specified" },
    { 0x05, 0x26, 0x03, "Parameter value invalid", "Invalid Threshold" },
    { 0x05, 0x26, 0x80, "Parameter value invalid", "Invalid Command Sequence Error" },
    { 0x05, 0x26, 0x81, "Parameter value invalid", "Grain setting (half-toning Pattern)" },
    { 0x05, 0x26, 0x82, "Parameter value invalid", "Illegal resolution setting" },
    { 0x05, 0x26, 0x83, "Parameter value invalid", "Invalid filter assignment" },
    { 0x05, 0x26, 0x84, "Parameter value invalid", "Illegal gamma adjustment setting(look-up table)" },
    { 0x05, 0x26, 0x85, "Parameter value invalid", "Illegal offset setting (digital brightness)" },
    { 0x05, 0x26, 0x86, "Parameter value invalid", "Illegal bits per pixel setting" },
    { 0x05, 0x26, 0x87, "Parameter value invalid", "Illegal contrast setting" },
    { 0x05, 0x26, 0x88, "Parameter value invalid", "Illegal paper length setting" },
    { 0x05, 0x26, 0x89, "Parameter value invalid", "Illegal highlight/shadow setting" },
    { 0x05, 0x26, 0x8a, "Parameter value invalid", "Illegal exposure time setting (analog brightness)" },
    { 0x05, 0x26, 0x8b, "Parameter value invalid", "Invalid device select or device not exist" },
    { 0x05, 0x26, 0x8c, "Parameter value invalid", "Illegal color packing" },
    { 0x05, 0x3d, 0x00, "Invalid Bit in Identify Field", "" },
    { 0x05, 0x49, 0x00, "Invalid Message", "" },
    { 0x05, 0x81, 0x01, "MMU Message", "Not enough memory for color packing" },
    { 0x06, 0x29, 0x00, "Unit Attention", "Target has been reset" },
    { 0x06, 0x82, 0x00, "Unit Attention", "Calibration disable not granted" },
    { 0x06, 0x83, 0x00, "Unit Attention", "Calibration will be ignored" },
    { 0x0b, 0x00, 0x06, "I/O process terminated", "Received ABORT message from Initiator" },
    { 0x0b, 0x48, 0x00, "I/O process terminated", "Initiator Detected Error Message Received" },
    { 0x0b, 0x43, 0x00, "I/O process terminated", "Message Error" },
    { 0x0b, 0x45, 0x00, "I/O process terminated", "Select or Re-select error" },
    { 0x09, 0x80, 0x80, "One touch scan", "User pushed a button to make a scan" },
    { 0x09, 0x80, 0x81, "One touch scan", "User pushed a button to cancel a scan" },
    { 0x09, 0x80, 0x82, "Film Loader", "Last film" },
    { 0x09, 0x80, 0x83, "Film Loader", "Film jam" },
    { 0x09, 0x80, 0x84, "Film Loader", "Film in sensor not detected" },
    { 0x09, 0x80, 0x85, "Film Loader", "Tray cover sensor not detected" },
    { 0x09, 0x80, 0x86, "Film Loader", "Film scan sensor not detected" },
    { 0x09, 0x80, 0x87, "Film Loader", "Film isn't in scanner" },
};

// SCSI Command names table (0x01efed80, 256 entries)
static const char* _ZL6cmdnam[256] = {
    "TEST UNIT READY", // 0x00
    "COMMAND 01", // 0x01
    "COMMAND 02", // 0x02
    "REQUEST SENSE", // 0x03
    "COMMAND 04", // 0x04
    "COMMAND 05", // 0x05
    "COMMAND 06", // 0x06
    "COMMAND 07", // 0x07
    "READ", // 0x08
    "COMMAND 09", // 0x09
    "WRITE", // 0x0a
    "COMMAND 0B", // 0x0b
    "COMMAND 0C", // 0x0c
    "COMMAND 0D", // 0x0d
    "COMMAND 0E", // 0x0e
    "PARAM", // 0x0f
    "COMMAND 10", // 0x10
    "COMMAND 11", // 0x11
    "INQUIRY", // 0x12
    "COMMAND 13", // 0x13
    "COMMAND 14", // 0x14
    "MODE SELECT", // 0x15
    "RESERVE", // 0x16
    "RELEASE", // 0x17
    "COPY", // 0x18
    "COMMAND 19", // 0x19
    "MODE SENSE", // 0x1a
    "SCAN", // 0x1b
    "RECEIVE DIAGNOSTIC RESULTS", // 0x1c
    "SEND DIAGNOSTIC", // 0x1d
    "COMMAND 1E", // 0x1e
    "COMMAND 1F", // 0x1f
    "COMMAND 20", // 0x20
    "COMMAND 21", // 0x21
    "COMMAND 22", // 0x22
    "COMMAND 23", // 0x23
    "SET WINDOW", // 0x24
    "GET WINDOW", // 0x25
    "COMMAND 26", // 0x26
    "COMMAND 27", // 0x27
    "READ", // 0x28
    "COMMAND 29", // 0x29
    "SEND", // 0x2a
    "COMMAND 2B", // 0x2b
    "COMMAND 2C", // 0x2c
    "COMMAND 2D", // 0x2d
    "COMMAND 2E", // 0x2e
    "COMMAND 2F", // 0x2f
    "COMMAND 30", // 0x30
    "OBJECT POSITION", // 0x31
    "COMMAND 32", // 0x32
    "COMMAND 33", // 0x33
    "GET DATA BUFFER STATUS", // 0x34
    "COMMAND 35", // 0x35
    "COMMAND 36", // 0x36
    "COMMAND 37", // 0x37
    "COMMAND 38", // 0x38
    "COMPARE", // 0x39
    "COPY AND VERIFY", // 0x3a
    "WRITE BUFFER", // 0x3b
    "READ BUFFER", // 0x3c
    "COMMAND 3D", // 0x3d
    "COMMAND 3E", // 0x3e
    "COMMAND 3F", // 0x3f
    "CHANGE DEFINITION", // 0x40
    "COMMAND 41", // 0x41
    "COMMAND 42", // 0x42
    "COMMAND 43", // 0x43
    "COMMAND 44", // 0x44
    "COMMAND 45", // 0x45
    "COMMAND 46", // 0x46
    "COMMAND 47", // 0x47
    "COMMAND 48", // 0x48
    "COMMAND 49", // 0x49
    "COMMAND 4A", // 0x4a
    "COMMAND 4B", // 0x4b
    "LOG SELECT", // 0x4c
    "LOG SENSE", // 0x4d
    "COMMAND 4E", // 0x4e
    "COMMAND 4F", // 0x4f
    "COMMAND 50", // 0x50
    "COMMAND 51", // 0x51
    "COMMAND 52", // 0x52
    "COMMAND 53", // 0x53
    "COMMAND 54", // 0x54
    "MODE SELECT", // 0x55
    "COMMAND 56", // 0x56
    "COMMAND 57", // 0x57
    "COMMAND 58", // 0x58
    "COMMAND 59", // 0x59
    "MODE SENSE", // 0x5a
    "COMMAND 5B", // 0x5b
    "COMMAND 5C", // 0x5c
    "COMMAND 5D", // 0x5d
    "COMMAND 5E", // 0x5e
    "COMMAND 5F", // 0x5f
    "COMMAND 60", // 0x60
    "COMMAND 61", // 0x61
    "COMMAND 62", // 0x62
    "COMMAND 63", // 0x63
    "COMMAND 64", // 0x64
    "COMMAND 65", // 0x65
    "COMMAND 66", // 0x66
    "COMMAND 67", // 0x67
    "COMMAND 68", // 0x68
    "COMMAND 69", // 0x69
    "COMMAND 6A", // 0x6a
    "COMMAND 6B", // 0x6b
    "COMMAND 6C", // 0x6c
    "COMMAND 6D", // 0x6d
    "COMMAND 6E", // 0x6e
    "COMMAND 6F", // 0x6f
    "COMMAND 70", // 0x70
    "COMMAND 71", // 0x71
    "COMMAND 72", // 0x72
    "COMMAND 73", // 0x73
    "COMMAND 74", // 0x74
    "COMMAND 75", // 0x75
    "COMMAND 76", // 0x76
    "COMMAND 77", // 0x77
    "COMMAND 78", // 0x78
    "COMMAND 79", // 0x79
    "COMMAND 7A", // 0x7a
    "COMMAND 7B", // 0x7b
    "COMMAND 7C", // 0x7c
    "COMMAND 7D", // 0x7d
    "COMMAND 7E", // 0x7e
    "COMMAND 7F", // 0x7f
    "COMMAND 80", // 0x80
    "COMMAND 81", // 0x81
    "COMMAND 82", // 0x82
    "COMMAND 83", // 0x83
    "COMMAND 84", // 0x84
    "COMMAND 85", // 0x85
    "COMMAND 86", // 0x86
    "COMMAND 87", // 0x87
    "COMMAND 88", // 0x88
    "COMMAND 89", // 0x89
    "COMMAND 8A", // 0x8a
    "COMMAND 8B", // 0x8b
    "COMMAND 8C", // 0x8c
    "COMMAND 8D", // 0x8d
    "COMMAND 8E", // 0x8e
    "COMMAND 8F", // 0x8f
    "COMMAND 90", // 0x90
    "COMMAND 91", // 0x91
    "COMMAND 92", // 0x92
    "COMMAND 93", // 0x93
    "COMMAND 94", // 0x94
    "COMMAND 95", // 0x95
    "COMMAND 96", // 0x96
    "COMMAND 97", // 0x97
    "COMMAND 98", // 0x98
    "COMMAND 99", // 0x99
    "COMMAND 9A", // 0x9a
    "COMMAND 9B", // 0x9b
    "COMMAND 9C", // 0x9c
    "COMMAND 9D", // 0x9d
    "COMMAND 9E", // 0x9e
    "COMMAND 9F", // 0x9f
    "COMMAND A0", // 0xa0
    "COMMAND A1", // 0xa1
    "COMMAND A2", // 0xa2
    "COMMAND A3", // 0xa3
    "COMMAND A4", // 0xa4
    "COMMAND A5", // 0xa5
    "COMMAND A6", // 0xa6
    "COMMAND A7", // 0xa7
    "COMMAND A8", // 0xa8
    "COMMAND A9", // 0xa9
    "COMMAND AA", // 0xaa
    "COMMAND AB", // 0xab
    "COMMAND AC", // 0xac
    "COMMAND AD", // 0xad
    "COMMAND AE", // 0xae
    "COMMAND AF", // 0xaf
    "COMMAND B0", // 0xb0
    "COMMAND B1", // 0xb1
    "COMMAND B2", // 0xb2
    "COMMAND B3", // 0xb3
    "COMMAND B4", // 0xb4
    "COMMAND B5", // 0xb5
    "COMMAND B6", // 0xb6
    "COMMAND B7", // 0xb7
    "COMMAND B8", // 0xb8
    "COMMAND B9", // 0xb9
    "COMMAND BA", // 0xba
    "COMMAND BB", // 0xbb
    "COMMAND BC", // 0xbc
    "COMMAND BD", // 0xbd
    "COMMAND BE", // 0xbe
    "COMMAND BF", // 0xbf
    "SABORT", // 0xc0
    "COMMAND C1", // 0xc1
    "GET HW STATUS", // 0xc2
    "COMMAND C3", // 0xc3
    "COMMAND C4", // 0xc4
    "COMMAND C5", // 0xc5
    "COMMAND C6", // 0xc6
    "COMMAND C7", // 0xc7
    "COMMAND C8", // 0xc8
    "COMMAND C9", // 0xc9
    "COMMAND CA", // 0xca
    "COMMAND CB", // 0xcb
    "COMMAND CC", // 0xcc
    "COMMAND CD", // 0xcd
    "COMMAND CE", // 0xce
    "COMMAND CF", // 0xcf
    "GET FILM STATUS", // 0xd0
    "FILM DRIVE", // 0xd1
    "OPTICAL SYSTEM DRIVE", // 0xd2
    "COMMAND D3", // 0xd3
    "COMMAND D4", // 0xd4
    "COMMAND D5", // 0xd5
    "COMMAND D6", // 0xd6
    "READ CALIBRATION STATUS", // 0xd7
    "COMMAND D8", // 0xd8
    "COMMAND D9", // 0xd9
    "COMMAND DA", // 0xda
    "COMMAND DB", // 0xdb
    "SET SCANNING PARAMETER", // 0xdc
    "GET SCANNER STATUS", // 0xdd
    "COMMAND DE", // 0xde
    "COMMAND DF", // 0xdf
    "COMMAND E0", // 0xe0
    "COMMAND E1", // 0xe1
    "COMMAND E2", // 0xe2
    "COMMAND E3", // 0xe3
    "COMMAND E4", // 0xe4
    "UPDATE FLASH ROM", // 0xe5
    "COMMAND E6", // 0xe6
    "GET SCAN COUNTER", // 0xe7
    "COMMAND E8", // 0xe8
    "COMMAND E9", // 0xe9
    "COMMAND EA", // 0xea
    "COMMAND EB", // 0xeb
    "COMMAND EC", // 0xec
    "COMMAND ED", // 0xed
    "COMMAND EE", // 0xee
    "COMMAND EF", // 0xef
    "COMMAND F0", // 0xf0
    "SCANNER CONTROL", // 0xf1
    "COMMAND F2", // 0xf2
    "COMMAND F3", // 0xf3
    "COMMAND F4", // 0xf4
    "COMMAND F5", // 0xf5
    "COMMAND F6", // 0xf6
    "SET PARAMETER", // 0xf7
    "COMMAND F8", // 0xf8
    "COMMAND F9", // 0xf9
    "COMMAND FA", // 0xfa
    "COMMAND FB", // 0xfb
    "COMMAND FC", // 0xfc
    "COMMAND FD", // 0xfd
    "COMMAND FE", // 0xfe
    "COMMAND FF", // 0xff
};

struct PIEM_T {
    int id;
    int opt0;
    int opt1;
    int opt2;
    int opt3;
    int opt4;
    int opt5;
    const char* name1;
    const char* name2;
};

// Model descriptors table (0x01eff720, 40 entries of 36 bytes)
static const PIEM_T _ZL4piem[40] = {
    { 34, 0, 0, 1, 0, 0, 3, "PrimeFilm 1800U", "iScan 1800" }, // [ 0]
    { 37, 0, 2, 0, 0, 0, 3, "PrimeFilm 1800 AFL", nullptr }, // [ 1]
    { 40, 0, 0, 1, 0, 0, 3, "PrimeFilm 2700", "CrystalScan 2700" }, // [ 2]
    { 42, 0, 0, 1, 0, 0, 3, "PrimeFilm 3600U", "iScan 3600" }, // [ 3]
    { 46, 0, 0, 1, 0, 0, 3, "PrimeFilm 3650U", "CrystalScan 3600" }, // [ 4]
    { 48, 0, 0, 1, 0, 0, 3, "PrimeFilm 7250U", "CrystalScan 7200" }, // [ 5]
    { 84, 0, 0, 1, 0, 0, 3, "NatureScan", nullptr }, // [ 6]
    { 98, 0, 0, 1, 0, 0, 3, "PrimeFilm 7250 Plus", nullptr }, // [ 7]
    { 54, 0, 0, 1, 0, 0, 3, "ColorScan 3600", "ProScan 7200" }, // [ 8]
    { 65, 0, 0, 1, 0, 0, 3, "PrimeFilm 7200", nullptr }, // [ 9]
    { 70, 0, 0, 1, 1, 1, 3, "PrimeFilm X", nullptr }, // [10]
    { 71, 0, 0, 1, 1, 1, 3, "PrimeFilm XE", "ProScan 10T" }, // [11]
    { 77, 0, 0, 1, 1, 1, 3, "PrimeHisto XE", nullptr }, // [12]
    { 90, 0, 0, 1, 1, 1, 3, "PrimeFilm XEs", nullptr }, // [13]
    { 94, 0, 0, 1, 1, 1, 3, "PrimeFilm XE Plus", nullptr }, // [14]
    { 43, 1, 1, 1, 0, 0, 1, "PowerSlide 3600", "DigitDia 3600" }, // [15]
    { 47, 1, 1, 1, 0, 0, 1, "PowerSlide 3650", "DigitDia 4000" }, // [16]
    { 58, 0, 1, 1, 1, 1, 0, "PowerSlide 5000", "DigitDia 6000" }, // [17]
    { 85, 0, 1, 1, 1, 1, 0, nullptr, "DigitDia 7000" }, // [18]
    { 89, 0, 1, 1, 1, 1, 0, "PowerSlide X", nullptr }, // [19]
    { 95, 0, 1, 1, 1, 1, 0, "PowerSlide X Plus", nullptr }, // [20]
    { 99, 0, 1, 1, 1, 1, 0, nullptr, "DigitDia 8000" }, // [21]
    { 36, 1, 2, 1, 0, 0, 3, "RFS 3600", "RPS 3600" }, // [22]
    { 45, 1, 2, 1, 1, 1, 3, "PrimeFilm 3650 LAB", nullptr }, // [23]
    { 49, 1, 2, 1, 0, 0, 3, "PrimeFilm 7250 Pro3", "RPS 7200" }, // [24]
    { 50, 0, 2, 1, 1, 1, 3, "PrimeFilm 3610 AFL", nullptr }, // [25]
    { 72, 0, 2, 1, 1, 1, 3, "PrimeFilm XA", "RPS 10M" }, // [26]
    { 91, 0, 2, 1, 1, 1, 3, "PrimeFilm XAs", nullptr }, // [27]
    { 93, 0, 2, 1, 1, 1, 3, "PrimeFilm XA Plus", nullptr }, // [28]
    { 38, 1, 2, 0, 0, 0, 3, "PrimeFilm 1800 LAB", nullptr }, // [29]
    { 39, 1, 2, 0, 0, 0, 3, "PrimeFilm 3600 Pro", "ProScan 3600" }, // [30]
    { 44, 1, 2, 0, 0, 0, 3, "PrimeFilm 3650 Pro3", "ProScan 4000" }, // [31]
    { 60, 0, 3, 1, 0, 0, 2, nullptr, "MF 5000" }, // [32]
    { 61, 0, 3, 1, 0, 0, 2, "PrimeFilm 120", nullptr }, // [33]
    { 64, 0, 3, 1, 0, 0, 2, "FS120ICE", nullptr }, // [34]
    { 66, 0, 3, 1, 0, 0, 2, "PrimeFilm 120 Pro", nullptr }, // [35]
    { 67, 0, 3, 1, 0, 0, 2, "FilmScan 120", nullptr }, // [36]
    { 97, 0, 3, 1, 0, 0, 2, "PF120 Pro Plus", nullptr }, // [37]
    { 87, 0, 4, 0, 1, 1, 1, "PowerFilm", nullptr }, // [38]
    { 96, 0, 4, 0, 1, 1, 1, "PowerFilm Plus", nullptr }  // [39]
};

// Alias _ZL4pied pointing to the model table (40 entries of 36 bytes)
static const PIEM_T* _ZL4pied __attribute__((unused)) = _ZL4piem;

// Low-level big-endian unpack helpers
inline uint8_t pied_gbyt(const uint8_t* p) {
    return p ? *p : 0;
}

inline uint16_t pied_gsho(const uint8_t* p) {
    if (!p) return 0;
    return (static_cast<uint16_t>(p[0]) << 8) | p[1];
}

inline uint32_t pied_gint(const uint8_t* p) {
    if (!p) return 0;
    return (static_cast<uint32_t>(p[0]) << 24) |
           (static_cast<uint32_t>(p[1]) << 16) |
           (static_cast<uint32_t>(p[2]) << 8)  |
           p[3];
}

// Formatted line dumper (0x0065f6e0)
static void pied_dstr(void (*print_fn)(const char*), int line, const char* prefix, const char* str) {
    if (!print_fn) return;
    char buf[256];
    std::snprintf(buf, sizeof(buf), "     %3d ", line);
    if (prefix) {
        std::strncat(buf, prefix, sizeof(buf) - std::strlen(buf) - 1);
    }
    int len = static_cast<int>(std::strlen(buf));
    while (len <= 41 && len < static_cast<int>(sizeof(buf) - 3)) {
        buf[len++] = ' ';
        buf[len] = '\0';
    }
    buf[len++] = ':';
    buf[len++] = ' ';
    buf[len] = '\0';
    if (str) {
        std::strncat(buf, str, sizeof(buf) - std::strlen(buf) - 1);
    }
    print_fn(buf);
}

// Command name lookup (0x00668ef0)
const char* pied_gcmd(uint8_t cmd) {
    return _ZL6cmdnam[cmd];
}

// Vendor name lookup (0x00668f10)
const char* pied_gvnd(int model_id, int alt_vendor) {
    if (model_id == 0x40) return "Uniscan";
    if (model_id == 0x43) return "Braun";
    if (model_id == 0x22) { // Model 34 (PrimeFilm 1800U)
        if (!_ZL4piem[0].name1 && !_ZL4piem[0].name2) return nullptr;
        return alt_vendor ? "Reflecta" : "PIE";
    }
    for (int i = 1; i < 40; i++) {
        if (_ZL4piem[i].id == model_id) {
            if (!_ZL4piem[i].name2 && !_ZL4piem[i].name1) return nullptr;
            return alt_vendor ? "Reflecta" : "PIE";
        }
    }
    return alt_vendor ? "Reflecta" : "PIE";
}

// Model name lookup (0x00668fb0)
const char* pied_gmdl(int model_id, int alt_model) {
    if (model_id == 0x22) { // Model 34
        const char* name1 = "PrimeFilm 1800U";
        const char* name2 = "iScan 1800";
        if (!name2) return name1;
        if (alt_model) return name2;
        if (!name1) return name2;
        return name1;
    }
    for (int i = 1; i < 40; i++) {
        if (_ZL4piem[i].id == model_id) {
            const char* name1 = _ZL4piem[i].name1;
            const char* name2 = _ZL4piem[i].name2;
            if (!name2) return name1;
            if (alt_model) return name2;
            if (!name1) return name2;
            return name1;
        }
    }
    return "Film Scanner";
}

// Diagnostic decoder and SCSI buffer dumper (0x0065f7e0)
void pied_dump(void (*print_fn)(const char*), int model_id, uint8_t cmd, uint8_t* buf, int len) {
    if (!print_fn) return;
    char text[256];
    const char* cmd_name = pied_gcmd(cmd);
    std::snprintf(text, sizeof(text), "CMD 0x%02X (%s), len=%d, model=%d",
                  cmd, cmd_name ? cmd_name : "UNKNOWN", len, model_id);
    print_fn(text);

    if (!buf || len <= 0) return;

    // Decode known command responses
    switch (cmd) {
        case 0x03: { // REQUEST SENSE
            if (len >= 14) {
                int sk = buf[2] & 0x0f;
                int asc = buf[12];
                int ascq = buf[13];
                const char* sk_str = "Unknown Sense";
                const char* asc_str = "Unknown ASC";
                for (int i = 0; i < 69; i++) {
                    if (_ZL4pies[i].sense_key == sk &&
                        _ZL4pies[i].asc == asc &&
                        _ZL4pies[i].ascq == ascq) {
                        sk_str = _ZL4pies[i].sense_key_str;
                        asc_str = _ZL4pies[i].asc_str;
                        break;
                    }
                }
                std::snprintf(text, sizeof(text), "Sense: [0x%02x] %s, ASC/ASCQ: [0x%02x/0x%02x] %s",
                              sk, sk_str, asc, ascq, asc_str);
                pied_dstr(print_fn, 0, "Sense Key", text);
            }
            break;
        }
        case 0x12: { // INQUIRY
            if (len >= 36) {
                char vid[9], pid[17], rev[5];
                std::memcpy(vid, buf + 8, 8); vid[8] = '\0';
                std::memcpy(pid, buf + 16, 16); pid[16] = '\0';
                std::memcpy(rev, buf + 32, 4); rev[4] = '\0';
                std::snprintf(text, sizeof(text), "VID: %s, PID: %s, Rev: %s", vid, pid, rev);
                pied_dstr(print_fn, 0, "Inquiry", text);
            }
            break;
        }
        case 0xc2: { // GET HW STATUS
            if (len >= 1) {
                std::snprintf(text, sizeof(text), "Status Byte: 0x%02X", buf[0]);
                pied_dstr(print_fn, 0, "HW Status", text);
            }
            break;
        }
        case 0xd0: { // GET FILM STATUS
            if (len >= 1) {
                std::snprintf(text, sizeof(text), "Film Status: 0x%02X", buf[0]);
                pied_dstr(print_fn, 0, "Film Status", text);
            }
            break;
        }
        default: {
            // General hex / ascii line dump
            for (int i = 0; i < len; i += 16) {
                char hex_str[64] = {0};
                char asc_str[32] = {0};
                int line_len = (len - i > 16) ? 16 : (len - i);
                for (int j = 0; j < line_len; j++) {
                    char h[4];
                    std::snprintf(h, sizeof(h), "%02X ", buf[i + j]);
                    std::strcat(hex_str, h);
                    asc_str[j] = (buf[i + j] >= 32 && buf[i + j] <= 126) ? static_cast<char>(buf[i + j]) : '.';
                }
                asc_str[line_len] = '\0';
                std::snprintf(text, sizeof(text), "%-48s  |%s|", hex_str, asc_str);
                pied_dstr(print_fn, i, "DATA", text);
            }
            break;
        }
    }
}
