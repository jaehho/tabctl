# tabctl

List, focus, open and group Firefox tabs from the command line, and sort tabs into tab groups by rules.

A Firefox extension keeps a connection open to a small native host, and the `tabctl` command reaches the host over a Unix socket. The extension carries out each request with Firefox's `tabs` and `tabGroups` APIs, so it works on the Firefox you have open, with its real tab groups.

## Install

Needs Firefox 140 or later and Python 3.11 or later, with nothing beyond the standard library.

```sh
make install   # tabctl and tabctl-native-host in ~/.local/bin, and Firefox's native host manifest
make xpi       # the extension, as dist/tabctl.xpi
```

Then, once, in Firefox: open about:addons, choose Install Add-on From File… in the gear menu and pick `dist/tabctl.xpi`. The XPI is not signed, so this works only where Firefox takes unsigned add-ons: Developer Edition, Nightly or ESR, with `xpinstall.signatures.required` set to false in about:config. `make install` writes `~/.mozilla/native-messaging-hosts/dev.jaeho.tabctl.json`, which tells Firefox where `tabctl-native-host` is; Firefox reads it from there even when its profiles live under `~/.config/mozilla`.

`tabctl` runs this checkout as it is, so a `git pull` or a merge takes effect at the next call. `TABCTL_SRC` points it at another tree.

## Usage

```sh
tabctl ls                                  # windows, groups and tabs, with tab and group ids
tabctl open URL                            # bring forward the tab showing URL, or open it in a new tab
tabctl open URL --match-param file         # ... matching on origin, path and the `file` query parameter
tabctl group 12 14 --title docs --color green
tabctl group 15 --into 1795208833552005    # into an existing group
tabctl ungroup 12 14
tabctl edit-group 1795208833552005 --collapsed
tabctl apply --dry-run                     # what the rules file would change
tabctl apply
```

Colors are blue, cyan, grey, green, orange, pink, purple, red and yellow. Every command takes `--json` and prints Firefox's own records: tabs have `id`, `windowId`, `index`, `groupId` (-1 when in no group), `url`, `title`, `active` and `pinned`; groups have `id`, `windowId`, `title`, `color` and `collapsed`. For example, to group every GitHub tab:

```sh
tabctl ls --json | jq '.tabs[] | select(.url | startswith("https://github.com/")) | .id' | xargs tabctl group --title github --color purple
```

`open` without `--match-param` matches a tab on its whole address, less any `#fragment`. With it, a page that rewrites the rest of its address is still found: a marimo notebook is the same notebook whatever its other query parameters.

### Rules

`tabctl apply` reads `$XDG_CONFIG_HOME/tabctl/groups.toml` (or the file `--rules` names):

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

`urls` are shell-style patterns (`*`, `?`, `[...]`) matched against a tab's whole address, and a tab goes to the first rule it matches. In each window, `apply` puts the ungrouped, unpinned tabs a rule matches into that window's group of the rule's title, making the group when there is none, and gives an existing group the rule's color. A tab already in a group, or pinned, stays where it is.

## How it works

When the extension starts it connects to the native host `dev.jaeho.tabctl` (`tabctl native-host`, `src/tabctl/host.py`), which Firefox starts and keeps while the connection is open, and reconnects with a growing delay if it closes. The host listens on `$XDG_RUNTIME_DIR/tabctl/host.sock`, readable by this user only. Each `tabctl` call sends one JSON request line there; the host passes it to the extension (`extension/background.js`) with an id and returns the extension's reply. Replies wait up to 4 s, and the command up to 6 s.

Only one host runs per user: a second Firefox profile with the extension gets no host of its own.

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
