CC ?= gcc
CFLAGS ?= -O2 -Wall -Wextra -pthread -fPIC -I../libpie1800u $(shell pkg-config --cflags libusb-1.0)
LDFLAGS ?= -pthread $(shell pkg-config --libs libusb-1.0)

all: libsane-pie1800u.so.1

libsane-pie1800u.so.1: sane-pie1800u.o ../libpie1800u/libpie1800u.a
	$(CC) -shared -Wl,-soname,$@ -o $@ sane-pie1800u.o ../libpie1800u/libpie1800u.a $(LDFLAGS)

sane-pie1800u.o: sane-pie1800u.c sane-pie1800u.h
	$(CC) $(CFLAGS) -c $< -o $@

../libpie1800u/libpie1800u.a:
	$(MAKE) -C ../libpie1800u libpie1800u.a

clean:
	rm -f *.o *.so*

install: libsane-pie1800u.so.1
	install -d /usr/lib/sane /etc/sane.d
	install -m 755 libsane-pie1800u.so.1 /usr/lib/sane/
	ln -sf libsane-pie1800u.so.1 /usr/lib/sane/libsane-pie1800u.so
	@if [ -d /usr/lib/x86_64-linux-gnu/sane ]; then \
		install -m 755 libsane-pie1800u.so.1 /usr/lib/x86_64-linux-gnu/sane/; \
		ln -sf libsane-pie1800u.so.1 /usr/lib/x86_64-linux-gnu/sane/libsane-pie1800u.so; \
	fi
	install -m 644 pie1800u.conf /etc/sane.d/
	@echo "Installed sane-pie1800u to /usr/lib/sane/."

.PHONY: all clean install
