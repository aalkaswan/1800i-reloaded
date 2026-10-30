# Top-level Makefile for PrimeFilm 1800u / 1800i Reloaded Suite

.PHONY: all clean lib sane bin

all: bin lib sane

bin:
	mkdir -p bin
	gcc -O3 -fopenmp scripts/pie1800_lca_deconv.c -o bin/pie1800_lca_deconv -lm
	gcc -O3 -fopenmp -fPIC -shared scripts/pie1800_lca_deconv.c -o bin/libpie1800_lca_deconv.so -lm
	gcc -O3 -fopenmp scripts/pie1800_chroma_denoise.c -o bin/pie1800_chroma_denoise -lm
	gcc -O3 -fopenmp -fPIC -shared scripts/pie1800_chroma_denoise.c -o bin/libpie1800_chroma_denoise.so -lm
	gcc -O3 -fopenmp scripts/pie1800_superres.c -o bin/pie1800_superres -lm
	gcc -O3 scripts/pie1800_deconv.c -o bin/pie1800_deconv -lm

lib:
	$(MAKE) -C libpie1800u

sane:
	$(MAKE) -C sane-backend

clean:
	$(MAKE) -C libpie1800u clean
	$(MAKE) -C sane-backend clean
	rm -f bin/pie1800_lca_deconv bin/libpie1800_lca_deconv.so bin/pie1800_chroma_denoise bin/libpie1800_chroma_denoise.so bin/pie1800_superres bin/pie1800_deconv
