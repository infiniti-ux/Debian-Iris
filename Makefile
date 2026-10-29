# =============================================================================
# Iris — developer entry points
#
#   make check        static validation of theme/config/scripts (no desktop needed)
#   make preview      web preview rendered from the theme's own CSS (PORT=8080)
#   make preview-check  fail if a theme rule reaches no mock element
#   make gsettings    regenerate the gsettings key allowlist from installed schemas
#   make rice         apply the skin to YOUR session (no root, no .deb, no ISO)
#   make unrice       restore the settings `make rice` changed
#   make selectors    regenerate the Cinnamon selector allowlist (needs a
#                     Cinnamon checkout in ../cinnamon, or $CINNAMON_SRC)
#   make deb          build the .deb (needs devscripts + debhelper)
#   make test-install install + uninstall round-trip as root, in dry-run
#   make iso          build a live image with live-build (config/ is its layout)
# =============================================================================
PYTHON ?= python3
VERSION := $(shell sed -n '1{s/.*(//;s/).*//;p}' debian/changelog 2>/dev/null || echo 0.2.0)

.PHONY: check check-strict preview preview-check gsettings rice unrice selectors deb iso test-install clean help

help:
	@sed -n '2,14p' Makefile | sed 's/^# \{0,1\}//'

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

# The mock is only worth looking at if every rule lands on something: a rule that
# matches no element makes that part of the desktop fall back to unstyled
# scaffolding, which reads as "the theme is broken" rather than "the mock is
# incomplete". --max-demo additionally fails when rules stop reaching the
# hand-built widgets and pile up as generic demo boxes.
preview-check:
	@$(PYTHON) tools/preview.py --print audit --max-demo 60

gsettings:
	@$(PYTHON) tools/gen-gsettings.py --out tools/upstream-gsettings.txt

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

# -----------------------------------------------------------------------------
# make rice — the whole point, without the packaging story.
#
# The panel look is a St stylesheet and the panel geometry, applets and animations
# are all gsettings, so none of this needs root, a .deb, a session file or an ISO:
# the theme is symlinked into ~/.themes and the profile is written to the *running*
# session, after every touched key's current value has been saved. `make unrice`
# puts them back.
#
# Applying takes effect live (Cinnamon watches org.cinnamon::*/changed::); after
# editing cinnamon.css, restart the shell with Alt+F2 -> r on X11 (on Wayland: log
# out and in).
rice:
	@mkdir -p "$$HOME/.themes"
	@ln -sfn "$$PWD/theme/Iris" "$$HOME/.themes/Iris"
	@echo "theme   -> $$HOME/.themes/Iris (symlink into this checkout)"
	@bash scripts/apply-settings.sh config/gsettings/iris.gsettings --yes \
	  || { echo "settings failed, removing the symlink again"; rm -f "$$HOME/.themes/Iris"; exit 1; }
	@echo "revert  -> make unrice"

unrice:
	@b="$$(ls -1t "$$HOME/.local/share/iris/settings-backup"/*-pre-iris.gsettings 2>/dev/null | head -1)"; \
	  if [ -n "$$b" ]; then \
	    echo "restoring $$b"; bash scripts/apply-settings.sh --restore "$$b" --yes; \
	  else \
	    echo "no backup from 'make rice' found — nothing to restore"; \
	  fi
	@rm -f "$$HOME/.themes/Iris"
