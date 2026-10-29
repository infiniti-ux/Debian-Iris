# =============================================================================
# Iris — developer entry points
#
#   make check        static validation of theme/config/scripts (no desktop needed)
#   make preview      web preview rendered from the theme's own CSS (PORT=8080)
#   make selectors    regenerate the Cinnamon selector allowlist (needs a
#                     Cinnamon checkout in ../cinnamon, or $CINNAMON_SRC)
#   make deb          build the .deb (needs devscripts + debhelper)
#   make test-install install + uninstall round-trip as root, in dry-run
#   make iso          build a live image with live-build (config/ is its layout)
# =============================================================================
PYTHON ?= python3
VERSION := $(shell sed -n '1{s/.*(//;s/).*//;p}' debian/changelog 2>/dev/null || echo 0.2.0)

.PHONY: check check-strict preview selectors deb iso test-install clean help

help:
	@sed -n '2,13p' Makefile | sed 's/^# \{0,1\}//'

check:
	@$(PYTHON) tools/check-theme.py --root .

lint-sh:
	@shellcheck -x -P SCRIPTDIR --format=gcc scripts/*.sh scripts/lib/*.sh

check-strict:
	@$(PYTHON) tools/check-theme.py --root . --strict

# Nothing is copied into the preview: tools/preview.py parses theme/Iris/**.css and
# config/gsettings/iris.gsettings on every request, so editing the theme and
# reloading shows the change. PORT=9000 make preview to move it.
preview:
	@$(PYTHON) tools/preview.py --host 0.0.0.0 --port $${PORT:-8080}

selectors:
	@$(PYTHON) tools/gen-selectors.py --out tools/upstream-selectors.txt

deb: check
	@dpkg-buildpackage -us -uc -b

test-install: check
	@echo "== install (dry-run) =="
	@sudo -E env IRIS_DRY_RUN=1 bash scripts/install.sh --with-session --with-lightdm --force --yes
	@echo
	@echo "== uninstall (dry-run) =="
	@sudo -E env IRIS_DRY_RUN=1 bash scripts/uninstall.sh --yes

iso:
	@command -v lb >/dev/null || { echo "live-build not installed: apt install live-build"; exit 1; }
	@sudo lb build

clean:
	@rm -rf debian/.debhelper debian/iris-theme debian/files debian/*.substvars debian/*.debhelper.log
