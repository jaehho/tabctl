# tabctl

List, focus, open, close and group Firefox tabs from the command line, sort tabs into tab groups by rules, and close duplicate tabs.

A Firefox extension keeps a connection open to a small native host, and the `tabctl` command reaches the host over a Unix socket. The extension carries out each request with Firefox's `tabs` and `tabGroups` APIs, so it works on the Firefox you have open, with its real tab groups.

## Install

Needs Firefox 140 or later and Python 3.11 or later, with nothing beyond the standard library.

```sh
make install   # tabctl and tabctl-native-host in ~/.local/bin, and Firefox's native host manifest
```

Then, once, install the extension: download `tabctl-X.Y.Z.xpi` from the [latest release](https://github.com/jaehho/tabctl/releases/latest), open about:addons in Firefox, choose Install Add-on From File… in the gear menu and pick it. Mozilla signs it, so any Firefox takes it, and Firefox updates it by itself from then on: it checks `updates.json` in this repository once a day (about:addons, gear menu, Check for Updates does it now). `make install` writes `~/.mozilla/native-messaging-hosts/dev.jaeho.tabctl.json`, which tells Firefox where `tabctl-native-host` is; Firefox reads it from there even when its profiles live under `~/.config/mozilla`.

`tabctl` runs this checkout as it is, so a `git pull` or a merge takes effect at the next call. `TABCTL_SRC` points it at another tree.

## Usage

```sh
tabctl ls                                  # windows, groups and tabs, with tab and group ids
tabctl open URL                            # bring forward the tab showing URL, or open it in a new tab
tabctl open URL --match-param file         # ... matching on origin, path and the `file` query parameter
tabctl open URL --new                      # always a new tab
tabctl group 12 14 --title docs --color green
tabctl group 15 --into 1795208833552005    # into an existing group
tabctl ungroup 12 14
tabctl edit-group 1795208833552005 --collapsed
tabctl close 12 14
tabctl dedupe --dry-run                    # which duplicate tabs it would close
tabctl dedupe
tabctl apply --dry-run                     # what the rules file would change
tabctl apply
```

Colors are blue, cyan, grey, green, orange, pink, purple, red and yellow. Every command takes `--json` and prints Firefox's own records: tabs have `id`, `windowId`, `index`, `groupId` (-1 when in no group), `url`, `title`, `active`, `pinned` and `lastAccessed` (ms since the epoch); groups have `id`, `windowId`, `title`, `color` and `collapsed`. For example, to group every GitHub tab:

```sh
tabctl ls --json | jq '.tabs[] | select(.url | startswith("https://github.com/")) | .id' | xargs tabctl group --title github --color purple
```

`open` without `--match-param` matches a tab on its whole address. With it, a page that rewrites the rest of its address is still found: a marimo notebook is the same notebook whatever its other query parameters. Either way the `#fragment` does not count, and `localhost` and `127.0.0.1` are the same host.

`dedupe` closes every tab that shows the same page as another (the same address less its `#fragment`, `localhost` taken as `127.0.0.1`, private and normal windows apart). Of each set it keeps a pinned tab, else the active one, else one in a group, else the one used last, and it never closes a pinned tab. Closed tabs come back from History, Recently Closed Tabs.

### Rules

Tabs sort themselves into groups by the rules in `$XDG_CONFIG_HOME/tabctl/groups.toml`:

```toml
[[group]]
title = "marimo"
color = "blue"
urls = ["http://127.0.0.1:*/?file=*", "http://localhost:*/?file=*"]

[[group]]
title = "docs"
color = "green"
collapsed = true          # only when the group is made
urls = ["https://docs.*", "https://*.readthedocs.io/*"]
```

`urls` are shell-style patterns (`*`, `?`, `[...]`) matched against a tab's whole address, and a tab goes to the first rule it matches. Whenever a tab's address changes (it opens, you follow a link, a page rewrites its address), a tab that is in no group and not pinned goes into its window's group of the rule's title, made when there is none. A tab already in a group, or pinned, stays where it is, so a tab you take out of a group stays out until its address changes again. The file is read each time, so an edit counts from the next change.

`tabctl apply` does the same for every tab open, such as those open before you wrote a rule (`--rules FILE` reads another file), and also gives each existing group its rule's color, which the automatic sorting leaves alone.

## How it works

When the extension starts it connects to the native host `dev.jaeho.tabctl` (`tabctl native-host`, `src/tabctl/host.py`), which Firefox starts and keeps while the connection is open, and reconnects with a growing delay if it closes. The host listens on `$XDG_RUNTIME_DIR/tabctl/host.sock`, readable by this user only. Each `tabctl` call sends one JSON request line there; the host passes it to the extension (`extension/background.js`) with an id and returns the extension's reply. Replies wait up to 4 s, and the command up to 6 s.

The extension also tells the host each time a tab's address changes. The host reads the rules, asks the extension for the tabs and groups, and asks it to group the tabs that moved, one batch at a time, so tabs that open together for a group that is not there yet make one group. If the rules file is broken, the host writes why to Firefox's standard error and leaves the tabs be; `tabctl apply` shows the same error.

Only one host runs per user: a second Firefox profile with the extension gets no host of its own.

## Releasing

Mozilla signs each version for self-distribution (AMO's unlisted channel), and the release on GitHub carries the signed XPI. The AMO API credentials, made at <https://addons.mozilla.org/developers/addon/api/key/>, live in the Secret Service; store them once from a terminal (each command prompts for the value):

```sh
secret-tool store --label='tabctl AMO JWT issuer' service tabctl-amo key jwt-issuer
secret-tool store --label='tabctl AMO JWT secret' service tabctl-amo key jwt-secret
```

Then, from a clean `main` that matches GitHub:

```sh
make release VERSION=0.3.1
```

It runs the tests and lint, writes the version into `extension/manifest.json`, `pyproject.toml` and the package, has AMO sign the extension (it waits up to 15 minutes; Mozilla says signing can take up to 24 hours), adds the signed XPI to `updates.json` with its SHA-256, commits and tags `v0.3.1`, publishes the GitHub release, and pushes `main` last, so `updates.json` never names an XPI that is not up yet. If signing fails the version files go back as they were. If AMO took the upload but signing outlasted the wait, download the signed XPI from AMO's developer hub once it is ready and run `scripts/release 0.3.1 --signed-xpi PATH`.

`make xpi` builds the extension unsigned, as `dist/tabctl.xpi`, for trying a change in a Firefox that takes unsigned add-ons (Developer Edition, Nightly or ESR, with `xpinstall.signatures.required` set to false).

## Development

```sh
make test            # rules, the host's protocol and the launcher, on scratch sockets
make check-firefox   # end to end in a headless Firefox (~40 s)
make lint
```

`make check-firefox` runs Firefox headless with its own HOME, profile and runtime directory, loads the extension unpacked from `extension/`, and drives every command through the launcher, including that the host stays connected after Firefox's idle timeout for backgrounds has passed. It never touches your Firefox, its profile or the host you installed.

Not checked yet: whether `open` raises the Firefox window on Wayland. It activates the tab and asks Firefox to focus its window; whether that window comes to the front is up to the compositor.

## License

MIT
