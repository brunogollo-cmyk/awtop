PREFIX ?= /usr/local

# Prefer a local virtualenv when one exists, so `make test` works without
# installing pytest into the system interpreter.
PYTHON := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

.PHONY: help test lint check install uninstall

help:
	@echo "awtop - Allwinner top-like monitor"
	@echo
	@echo "  make test       run the test suite (no root required)"
	@echo "  make lint       run pyflakes"
	@echo "  make check      test + lint"
	@echo "  make install    install to \$$PREFIX (needs root)"
	@echo "  make uninstall  remove from \$$PREFIX (needs root)"
	@echo
	@echo "  Override the prefix: make install PREFIX=~/.local"

test:
	$(PYTHON) -m pytest tests/ -q

lint:
	$(PYTHON) -m pyflakes awtop/ awtop.py tests/

check: test lint

install:
	PREFIX=$(PREFIX) sh install.sh

uninstall:
	PREFIX=$(PREFIX) sh install.sh --uninstall
