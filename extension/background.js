// tabctl's background: holds a port to the native host (`tabctl
// native-host`, src/tabctl/host.py) and answers each request it relays
// from the command line with one reply, {id, ok, result | error}. It
// also tells the host when a tab's address changes, {event: "url",
// tabId}, so the host can put the tab in its rule's group.
"use strict";

const HOST = "dev.jaeho.tabctl";
const RETRY_MS = { first: 1000, max: 60000 };

let retryMs = RETRY_MS.first;
let port = null;

function connect() {
  const native = browser.runtime.connectNative(HOST);
  port = native;
  native.onMessage.addListener((message) => receive(native, message));
  native.onDisconnect.addListener((gone) => {
    console.warn("tabctl: host gone:", gone.error?.message ?? "closed");
    if (port === native) {
      port = null;
    }
    setTimeout(connect, retryMs);
    retryMs = Math.min(retryMs * 2, RETRY_MS.max);
  });
}

browser.tabs.onUpdated.addListener(
  (tabId) => {
    try {
      port?.postMessage({ event: "url", tabId });
    } catch (error) {
      console.warn("tabctl: cannot tell the host:", error.message);
    }
  },
  { properties: ["url"] },
);

async function receive(port, message) {
  if (message.hello !== undefined) {
    retryMs = RETRY_MS.first;
    return;
  }
  const { id, cmd, args } = message;
  try {
    const handler = HANDLERS[cmd];
    if (!handler) {
      throw new Error(`unknown command: ${cmd}`);
    }
    port.postMessage({ id, ok: true, result: await handler(args ?? {}) });
  } catch (error) {
    port.postMessage({ id, ok: false, error: String(error.message ?? error) });
  }
}

const HANDLERS = {
  list: listAll,
  open: openUrl,
  group: groupTabs,
  ungroup: ({ tabIds }) => browser.tabs.ungroup(tabIds).then(() => null),
  close: ({ tabIds }) => browser.tabs.remove(tabIds).then(() => null),
  "edit-group": ({ groupId, ...properties }) =>
    browser.tabGroups.update(groupId, defined(properties)).then(describeGroup),
};

async function listAll() {
  const [windows, groups, tabs] = await Promise.all([
    browser.windows.getAll({ windowTypes: ["normal"] }),
    browser.tabGroups.query({}),
    browser.tabs.query({}),
  ]);
  return {
    windows: windows.map((w) => ({
      id: w.id,
      focused: w.focused,
      incognito: w.incognito,
    })),
    groups: groups.map(describeGroup),
    tabs: tabs.map(describeTab),
  };
}

// The tab showing url, brought forward, or a new one in the window
// focused last. With matchParams, a tab matches on the origin, the path
// and those query parameters, so a page that rewrites the rest of its
// address is still found; without, on the whole address. Either way the
// #fragment does not count, and localhost is 127.0.0.1. newTab skips
// the search.
async function openUrl({ url, matchParams = [], newTab = false }) {
  const want = samePage(url);
  const same = (address) => {
    const have = samePage(address);
    if (have === null) {
      return false;
    }
    if (matchParams.length === 0) {
      return have.href === want.href;
    }
    return (
      have.origin === want.origin &&
      have.pathname === want.pathname &&
      matchParams.every(
        (key) => have.searchParams.get(key) === want.searchParams.get(key),
      )
    );
  };
  const found = newTab
    ? undefined
    : (await browser.tabs.query({})).find((tab) => same(tab.url));
  if (found) {
    await browser.tabs.update(found.id, { active: true });
    await browser.windows.update(found.windowId, { focused: true });
    return { tab: describeTab(found), created: false };
  }
  const windows = await browser.windows.getAll({ windowTypes: ["normal"] });
  if (windows.length === 0) {
    const made = await browser.windows.create({ url });
    return { tab: describeTab(made.tabs[0]), created: true };
  }
  const last = await browser.windows.getLastFocused({
    windowTypes: ["normal"],
  });
  const tab = await browser.tabs.create({ url, windowId: last.id });
  await browser.windows.update(last.id, { focused: true });
  return { tab: describeTab(tab), created: true };
}

// Into groupId, or a new group with these properties in windowId, by
// default the first tab's window (Firefox's default is the window
// focused last, which would carry the tabs off to it).
async function groupTabs({ tabIds, groupId, windowId, ...properties }) {
  const ids = [tabIds].flat();
  const options =
    groupId === undefined
      ? {
          tabIds: ids,
          createProperties: {
            windowId: windowId ?? (await browser.tabs.get(ids[0])).windowId,
          },
        }
      : { tabIds: ids, groupId };
  const id = await browser.tabs.group(options);
  const looks = defined(properties);
  const group =
    Object.keys(looks).length > 0
      ? await browser.tabGroups.update(id, looks)
      : await browser.tabGroups.get(id);
  return describeGroup(group);
}

function describeTab(t) {
  return {
    id: t.id,
    windowId: t.windowId,
    index: t.index,
    groupId: t.groupId ?? -1,
    url: t.url ?? "",
    title: t.title ?? "",
    active: t.active,
    pinned: t.pinned,
    lastAccessed: t.lastAccessed ?? 0,
  };
}

function describeGroup(g) {
  return {
    id: g.id,
    windowId: g.windowId,
    title: g.title ?? "",
    color: g.color,
    collapsed: g.collapsed,
  };
}

const LOOPBACK = new Set(["localhost", "127.0.0.1"]);

// address as a URL less its #fragment, with a loopback host written
// 127.0.0.1; null when it is no URL.
function samePage(address) {
  let url;
  try {
    url = new URL(address);
  } catch {
    return null;
  }
  if (LOOPBACK.has(url.hostname)) {
    url.hostname = "127.0.0.1";
  }
  url.hash = "";
  return url;
}

function defined(object) {
  return Object.fromEntries(
    Object.entries(object).filter(([, value]) => value != null),
  );
}

connect();
