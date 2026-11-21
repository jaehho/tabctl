# tabctl - list, focus, open and group Firefox tabs from the command line.

.PHONY: help run test check-firefox lint fmt xpi release install uninstall package clean

PREFIX       ?= $(HOME)/.local
# Firefox reads a user's native messaging hosts only from here, though
# its profiles now live under ~/.config/mozilla.
NATIVE_HOSTS ?= $(HOME)/.mozilla/native-messaging-hosts
PY_FILES     := src tests scripts/check-firefox scripts/release

help:            ## this list
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*## /\t/' | expand -t16

run:             ## the CLI from this tree: make run ARGS=ls
	scripts/tabctl-live $(ARGS)

test:            ## rules, the host's protocol and the launcher, on scratch sockets
	uv run python -m unittest discover -s tests -t . -v

check-firefox:   ## end to end in a headless Firefox with a scratch profile and HOME (~40 s)
	scripts/check-firefox

lint:            ## ruff
	uv run ruff check $(PY_FILES)
	uv run ruff format --check $(PY_FILES)

fmt:             ## ruff format
	uv run ruff format $(PY_FILES)

xpi:             ## the extension unsigned -> dist/tabctl.xpi, for Firefox that takes unsigned add-ons
	mkdir -p dist
	rm -f dist/tabctl.xpi
	cd extension && zip -q -r -X ../dist/tabctl.xpi . -x '.*'

release: test lint  ## sign through AMO and publish on GitHub: make release VERSION=X.Y.Z (README, Releasing)
	@test -n "$(VERSION)" || { echo "give VERSION=X.Y.Z" >&2; exit 2; }
	scripts/release $(VERSION)

install:         ## tabctl and Firefox's native host in ~/.local (no sudo); the extension is installed in Firefox by hand
	# One script, two names. @ROOT@ becomes the checkout that installed it.
	install -d $(PREFIX)/bin
	sed 's|^DEFAULT_ROOT="@ROOT@"|DEFAULT_ROOT="$(CURDIR)"|' scripts/tabctl-live > $(PREFIX)/bin/tabctl
	chmod 755 $(PREFIX)/bin/tabctl
	ln -sf tabctl $(PREFIX)/bin/tabctl-native-host
	install -d $(NATIVE_HOSTS)
	sed 's#"path": "tabctl-native-host"#"path": "$(abspath $(PREFIX))/bin/tabctl-native-host"#' packaging/dev.jaeho.tabctl.json > $(NATIVE_HOSTS)/dev.jaeho.tabctl.json

uninstall:       ## remove the launchers and the native host manifest (rules stay)
	rm -f $(PREFIX)/bin/tabctl $(PREFIX)/bin/tabctl-native-host $(NATIVE_HOSTS)/dev.jaeho.tabctl.json

package:         ## not yet: there is no packaging/PKGBUILD
	@echo "no PKGBUILD yet" >&2; exit 1

clean:
	rm -rf dist .venv
