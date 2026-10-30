#ifndef SANE_PIE1800U_H
#define SANE_PIE1800U_H

#if __has_include(<sane/sane.h>)
#include <sane/sane.h>
#include <sane/saneopts.h>
#else
#include <stdint.h>

typedef uint8_t  SANE_Byte;
typedef int32_t  SANE_Int;
typedef uint32_t SANE_Word;
typedef SANE_Int SANE_Bool;
typedef char     SANE_Char;
typedef const SANE_Char *SANE_String_Const;
typedef SANE_Char *SANE_String;
typedef void *SANE_Handle;

typedef enum {
    SANE_STATUS_GOOD = 0,
    SANE_STATUS_UNSUPPORTED,
    SANE_STATUS_CANCELLED,
    SANE_STATUS_DEVICE_BUSY,
    SANE_STATUS_INVAL,
    SANE_STATUS_EOF,
    SANE_STATUS_JAMMED,
    SANE_STATUS_NO_DOCS,
    SANE_STATUS_COVER_OPEN,
    SANE_STATUS_IO_ERROR,
    SANE_STATUS_NO_MEM,
    SANE_STATUS_ACCESS_DENIED
} SANE_Status;

typedef enum {
    SANE_TYPE_BOOL = 0,
    SANE_TYPE_INT,
    SANE_TYPE_FIXED,
    SANE_TYPE_STRING,
    SANE_TYPE_BUTTON,
    SANE_TYPE_GROUP
} SANE_Value_Type;

typedef enum {
    SANE_UNIT_NONE = 0,
    SANE_UNIT_PIXEL,
    SANE_UNIT_BIT,
    SANE_UNIT_MM,
    SANE_UNIT_DPI,
    SANE_UNIT_PERCENT,
    SANE_UNIT_MICROSECOND
} SANE_Unit;

typedef enum {
    SANE_CONSTRAINT_NONE = 0,
    SANE_CONSTRAINT_RANGE,
    SANE_CONSTRAINT_WORD_LIST,
    SANE_CONSTRAINT_STRING_LIST
} SANE_Constraint_Type;

typedef struct {
    SANE_String_Const name;
    SANE_String_Const vendor;
    SANE_String_Const model;
    SANE_String_Const type;
} SANE_Device;

typedef struct {
    SANE_Word min;
    SANE_Word max;
    SANE_Word quant;
} SANE_Range;

typedef struct {
    SANE_String_Const name;
    SANE_String_Const title;
    SANE_String_Const desc;
    SANE_Value_Type type;
    SANE_Unit unit;
    SANE_Int size;
    SANE_Int cap;
    SANE_Constraint_Type constraint_type;
    union {
        const SANE_String_Const *string_list;
        const SANE_Word *word_list;
        const SANE_Range *range;
    } constraint;
} SANE_Option_Descriptor;

typedef enum {
    SANE_ACTION_GET_VALUE = 0,
    SANE_ACTION_SET_VALUE,
    SANE_ACTION_SET_AUTO
} SANE_Action;

typedef enum {
    SANE_FRAME_GRAY = 0,
    SANE_FRAME_RGB,
    SANE_FRAME_RED,
    SANE_FRAME_GREEN,
    SANE_FRAME_BLUE
} SANE_Frame;

typedef struct {
    SANE_Frame format;
    SANE_Bool last_frame;
    SANE_Int bytes_per_line;
    SANE_Int pixels_per_line;
    SANE_Int lines;
    SANE_Int depth;
} SANE_Parameters;

typedef void (*SANE_Auth_Callback)(SANE_String_Const resource,
                                   SANE_Char *username,
                                   SANE_Char *password);

#define SANE_CURRENT_MAJOR 1
#define SANE_CURRENT_MINOR 0
#define SANE_VERSION_CODE(major, minor, build) \
  ((((SANE_Word) (major) & 0xff) << 24) | \
   (((SANE_Word) (minor) & 0xff) << 16) | \
   (((SANE_Word) (build) & 0xffff) << 0))

#define SANE_CAP_SOFT_SELECT        (1 << 0)
#define SANE_CAP_HARD_SELECT        (1 << 1)
#define SANE_CAP_SOFT_DETECT        (1 << 2)
#define SANE_CAP_EMULATED           (1 << 3)
#define SANE_CAP_AUTOMATIC          (1 << 4)
#define SANE_CAP_INACTIVE           (1 << 5)
#define SANE_CAP_ADVANCED           (1 << 6)

#define SANE_INFO_INEXACT           (1 << 0)
#define SANE_INFO_RELOAD_OPTIONS    (1 << 1)
#define SANE_INFO_RELOAD_PARAMS     (1 << 2)

#define SANE_FALSE 0
#define SANE_TRUE  1

#define SANE_NAME_NUM_OPTIONS       ""
#define SANE_NAME_SCAN_MODE         "mode"
#define SANE_NAME_SCAN_RESOLUTION   "resolution"
#define SANE_NAME_PREVIEW           "preview"
#define SANE_NAME_SCAN_TL_X         "tl-x"
#define SANE_NAME_SCAN_TL_Y         "tl-y"
#define SANE_NAME_SCAN_BR_X         "br-x"
#define SANE_NAME_SCAN_BR_Y         "br-y"
#endif

// SANE Backend Declarations for pie1800u
SANE_Status sane_pie1800u_init(SANE_Int *version_code, SANE_Auth_Callback authorize);
void        sane_pie1800u_exit(void);
SANE_Status sane_pie1800u_get_devices(const SANE_Device ***device_list, SANE_Bool local_only);
SANE_Status sane_pie1800u_open(SANE_String_Const devicename, SANE_Handle *handle);
void        sane_pie1800u_close(SANE_Handle handle);
const SANE_Option_Descriptor *sane_pie1800u_get_option_descriptor(SANE_Handle handle, SANE_Int option);
SANE_Status sane_pie1800u_control_option(SANE_Handle handle, SANE_Int option, SANE_Action action, void *value, SANE_Int *info);
SANE_Status sane_pie1800u_get_parameters(SANE_Handle handle, SANE_Parameters *params);
SANE_Status sane_pie1800u_start(SANE_Handle handle);
SANE_Status sane_pie1800u_read(SANE_Handle handle, SANE_Byte *data, SANE_Int max_length, SANE_Int *length);
void        sane_pie1800u_cancel(SANE_Handle handle);
SANE_Status sane_pie1800u_set_io_mode(SANE_Handle handle, SANE_Bool non_blocking);
SANE_Status sane_pie1800u_get_select_fd(SANE_Handle handle, SANE_Int *fd);

#endif /* SANE_PIE1800U_H */
