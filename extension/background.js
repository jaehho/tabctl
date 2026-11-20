// tabctl's background: holds a port to the native host (`tabctl
// native-host`, src/tabctl/host.py) and answers each request it relays
// from the command line with one reply, {id, ok, result | error}.
"use strict";

const HOST = "dev.jaeho.tabctl";
const RETRY_MS = { first: 1000, max: 60000 };

let retryMs = RETRY_MS.first;

function connect() {
  const port = browser.runtime.connectNative(HOST);
  port.onMessage.addListener((message) => receive(port, message));
  port.onDisconnect.addListener((gone) => {
    console.warn("tabctl: host gone:", gone.error?.message ?? "closed");
    setTimeout(connect, retryMs);
    retryMs = Math.min(retryMs * 2, RETRY_MS.max);
  });
}

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
// address (or adds a #fragment) is still found; without, on the whole
// address less its fragment.
async function openUrl({ url, matchParams = [] }) {
  const want = new URL(url);
  const same = (address) => {
    let have;
    try {
      have = new URL(address);
    } catch {
      return false;
    }
    if (matchParams.length === 0) {
      have.hash = "";
      const bare = new URL(want);
      bare.hash = "";
      return have.href === bare.href;
    }
    return (
      have.origin === want.origin &&
      have.pathname === want.pathname &&
      matchParams.every(
        (key) => have.searchParams.get(key) === want.searchParams.get(key),
      )
    );
  };
  const found = (await browser.tabs.query({})).find((tab) => same(tab.url));
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

// Into groupId, or a new group in windowId with these properties.
async function groupTabs({ tabIds, groupId, windowId, ...properties }) {
  const options =
    groupId === undefined
      ? { tabIds, createProperties: defined({ windowId }) }
      : { tabIds, groupId };
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

function defined(object) {
  return Object.fromEntries(
    Object.entries(object).filter(([, value]) => value != null),
  );
}

connect();
