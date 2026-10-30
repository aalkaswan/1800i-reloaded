CC ?= gcc
CFLAGS ?= -O2 -Wall -Wextra -fPIC $(shell pkg-config --cflags libusb-1.0)
LDFLAGS ?= $(shell pkg-config --libs libusb-1.0)

all: libpie1800u.so libpie1800u.a pie1800_cli

libpie1800u.so: pie1800u.o
	$(CC) -shared -o $@ $^ $(LDFLAGS)

libpie1800u.a: pie1800u.o
	ar rcs $@ $^

pie1800u.o: pie1800u.c pie1800u.h
	$(CC) $(CFLAGS) -c $< -o $@

pie1800_cli: pie1800_cli.c libpie1800u.a
	$(CC) $(CFLAGS) pie1800_cli.c libpie1800u.a $(LDFLAGS) -Wl,-rpath,'$$ORIGIN' -o $@

clean:
	rm -f *.o *.so *.a pie1800_cli

.PHONY: all clean
