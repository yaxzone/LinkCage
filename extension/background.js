/*
 * Copyright 2026 Luis Yax
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

const NATIVE_HOST = "com.linkcage.host";

// Firefox's notifications API ignores the "buttons" property (Chrome-only).
// When buttons aren't supported we fall back to button-less notifications that
// perform their primary action when the notification body is clicked.
const SUPPORTS_NOTIFICATION_BUTTONS =
  typeof navigator === "undefined" || !/\bFirefox\//.test(navigator.userAgent);

// Properties of chrome.notifications.create() that Chrome accepts but Firefox
// rejects — Firefox's schema is strict and throws TypeError on unknown options.
const CHROME_ONLY_NOTIFICATION_PROPS = [
  "priority", "requireInteraction", "buttons", "eventTime",
  "isClickable", "contextMessage",
];

// Thin wrapper around chrome.notifications.create that strips Chrome-only
// fields on Firefox so the call doesn't throw. Mirrors both call signatures
// (with or without an explicit notification id; optional callback).
function safeNotificationCreate(idOrOptions, optionsOrCallback, maybeCallback) {
  let id = null, options, cb;
  if (typeof idOrOptions === "string") {
    id = idOrOptions; options = optionsOrCallback; cb = maybeCallback;
  } else {
    options = idOrOptions; cb = optionsOrCallback;
  }
  if (!SUPPORTS_NOTIFICATION_BUTTONS) {
    const cleaned = {};
    for (const k of Object.keys(options || {})) {
      if (!CHROME_ONLY_NOTIFICATION_PROPS.includes(k)) cleaned[k] = options[k];
    }
    options = cleaned;
  }
  if (id !== null) {
    return cb ? chrome.notifications.create(id, options, cb)
              : chrome.notifications.create(id, options);
  }
  return cb ? chrome.notifications.create(options, cb)
            : chrome.notifications.create(options);
}

// Where to send users when the native host isn't installed yet.
const SETUP_URL = "https://github.com/yaxzone/LinkCage#quick-start";

const BADGE_CONFIG = {
  SAFE:       { text: "OK", color: "#2E7D32" },
  UNKNOWN:    { text: "?",  color: "#616161" },
  SUSPICIOUS: { text: "!",  color: "#F57C00" },
  MALICIOUS:  { text: "X",  color: "#C62828" },
};

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "linkcage-open-link",
    title: "LinkCage: Open in Sandbox",
    contexts: ["link"],
  });

  chrome.contextMenus.create({
    id: "linkcage-open-page",
    title: "LinkCage: Open This Page in Sandbox",
    contexts: ["page"],
  });

  chrome.contextMenus.create({
    id: "linkcage-close-sandbox",
    title: "Close Sandbox Browser",
    contexts: ["all"],
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "linkcage-close-sandbox") {
    sendStopToNativeHost();
    return;
  }

  let url = null;

  if (info.menuItemId === "linkcage-open-link") {
    url = info.linkUrl;
  } else if (info.menuItemId === "linkcage-open-page") {
    url = info.pageUrl;
  }

  if (url) {
    sendToNativeHost(url, false);
  }
});

// Track pending bypass prompts so the notification click handler knows
// which URL the user just approved.
const pendingBypass = new Map();

// Track "setup needed" notifications so their button opens the setup guide.
const setupNotifications = new Set();

chrome.notifications.onButtonClicked.addListener((notificationId, buttonIndex) => {
  if (setupNotifications.has(notificationId)) {
    setupNotifications.delete(notificationId);
    chrome.notifications.clear(notificationId);
    if (buttonIndex === 0) {
      chrome.tabs.create({ url: SETUP_URL });
    }
    return;
  }

  const entry = pendingBypass.get(notificationId);
  if (!entry) return;
  pendingBypass.delete(notificationId);
  chrome.notifications.clear(notificationId);
  if (buttonIndex === 0) {
    // Open anyway — re-send with bypass flag set
    sendToNativeHost(entry.url, true);
  }
  // buttonIndex 1 (Cancel) => do nothing
});

// Button-less fallback (Firefox): clicking the notification body performs the
// primary action, mirroring buttonIndex 0 on the Chrome button handlers.
chrome.notifications.onClicked.addListener((notificationId) => {
  if (setupNotifications.has(notificationId)) {
    setupNotifications.delete(notificationId);
    chrome.notifications.clear(notificationId);
    chrome.tabs.create({ url: SETUP_URL });
    return;
  }

  const entry = pendingBypass.get(notificationId);
  if (!entry) return;
  pendingBypass.delete(notificationId);
  chrome.notifications.clear(notificationId);
  sendToNativeHost(entry.url, true);
});

chrome.notifications.onClosed.addListener((notificationId) => {
  pendingBypass.delete(notificationId);
  setupNotifications.delete(notificationId);
});

// The native host isn't installed/registered (or its allowed_origins doesn't
// list this extension's ID). Chrome reports these as "host not found" /
// "forbidden" / "host has exited" errors.
function isHostMissingError(message) {
  const m = (message || "").toLowerCase();
  return (
    m.includes("not found") ||
    m.includes("forbidden") ||
    m.includes("not been installed") ||
    m.includes("host has exited")
  );
}

function showSetupNotification() {
  const notifId = `linkcage-setup-${Date.now()}`;
  setupNotifications.add(notifId);
  const options = {
    type: "basic",
    iconUrl: "icons/icon128.png",
    title: "LinkCage: setup needed",
    message:
      "The LinkCage helper isn't installed yet. LinkCage needs its companion " +
      "host and Docker sandbox to open links. Open the setup guide to finish " +
      "installation.",
    priority: 2,
    requireInteraction: true,
  };
  if (SUPPORTS_NOTIFICATION_BUTTONS) {
    options.buttons = [{ title: "Open setup guide" }, { title: "Dismiss" }];
  } else {
    // No buttons available: tell the user clicking opens the guide.
    options.message += "\n\nClick this notification to open the setup guide.";
  }
  safeNotificationCreate(notifId, options);
}

function truncateUrl(url, max = 80) {
  if (!url) return "";
  return url.length > max ? url.slice(0, max - 1) + "\u2026" : url;
}

function setBadgeForVerdict(level) {
  const cfg = BADGE_CONFIG[level];
  if (!cfg) {
    chrome.action.setBadgeText({ text: "" });
    return;
  }
  chrome.action.setBadgeText({ text: cfg.text });
  chrome.action.setBadgeBackgroundColor({ color: cfg.color });
}

function showVerdictNotification(url, verdict) {
  const level = (verdict && verdict.level) || "UNKNOWN";

  let title;
  let priority;
  switch (level) {
    case "SAFE":
      title = "LinkCage: SAFE";
      priority = 0;
      break;
    case "SUSPICIOUS":
      title = "LinkCage: SUSPICIOUS";
      priority = 1;
      break;
    case "MALICIOUS":
      title = "LinkCage: MALICIOUS";
      priority = 2;
      break;
    case "UNKNOWN":
    default:
      title = "LinkCage: UNKNOWN";
      priority = 0;
      break;
  }

  const lines = [truncateUrl(url)];
  if (verdict && verdict.reason && verdict.source) {
    lines.push(`${verdict.reason} (${verdict.source})`);
  } else {
    lines.push(level);
  }

  safeNotificationCreate({
    type: "basic",
    iconUrl: "icons/icon128.png",
    title: title,
    message: lines.join("\n"),
    priority: priority,
    requireInteraction: level === "MALICIOUS",
  });
}

function showStopNotification(ok, errorMsg) {
  const iconUrl = "icons/icon128.png";
  const title = ok ? "LinkCage: Sandbox stopped" : "LinkCage: Stop failed";
  const message = ok
    ? "The sandbox container has been shut down."
    : (errorMsg || "Unable to stop the sandbox container.");
  const notifId = `linkcage-stop-${Date.now()}`;
  try {
    safeNotificationCreate(notifId, {
      type: "basic",
      iconUrl: iconUrl,
      title: title,
      message: message,
      priority: 1,
    }, () => {
      if (chrome.runtime.lastError) {
        console.warn("[LinkCage] notification error:", chrome.runtime.lastError.message);
      }
    });
    // Auto-clear success notifications after 3 seconds
    if (ok) {
      setTimeout(() => {
        chrome.notifications.clear(notifId);
      }, 3000);
    }
  } catch (e) {
    console.warn("[LinkCage] showStopNotification failed:", e);
  }
}

function promptBypassMalicious(url, verdict) {
  const reason = (verdict && verdict.reason) || "URL flagged as MALICIOUS";
  const source = (verdict && verdict.source) || "verdict";
  const notificationId = `linkcage-mal-${Date.now()}`;
  pendingBypass.set(notificationId, { url, verdict });
  const options = {
    type: "basic",
    iconUrl: "icons/icon128.png",
    title: "LinkCage: MALICIOUS link blocked",
    message: `${reason}\nSource: ${source}\n${truncateUrl(url)}\n\nSandbox isolates the page, but opening is discouraged.`,
    priority: 2,
    requireInteraction: true,
  };
  if (SUPPORTS_NOTIFICATION_BUTTONS) {
    options.buttons = [
      { title: "Open anyway in sandbox" },
      { title: "Cancel" },
    ];
  } else {
    // No buttons available: clicking the notification opens it anyway;
    // dismissing it cancels.
    options.message +=
      "\n\nClick this notification to open anyway, or dismiss it to cancel.";
  }
  safeNotificationCreate(notificationId, options);
}

function sendStopToNativeHost() {
  const payload = { action: "stop" };
  chrome.runtime.sendNativeMessage(NATIVE_HOST, payload, (response) => {
    if (chrome.runtime.lastError) {
      const m = chrome.runtime.lastError.message || "";
      console.error("[LinkCage] stop native error:", m);
      if (isHostMissingError(m)) {
        showSetupNotification();
        return;
      }
      showStopNotification(false, m);
      return;
    }
    if (!response || response.status !== "ok") {
      const msg = (response && response.error) || "Unknown error stopping sandbox";
      console.error("[LinkCage] stop failed:", msg);
      showStopNotification(false, msg);
      return;
    }
    // Success: clear badge, show success notification
    chrome.action.setBadgeText({ text: "" });
    showStopNotification(true, null);
  });
}

function sendToNativeHost(url, bypassVerdict) {
  const payload = { action: "open", url: url };
  if (bypassVerdict) {
    payload.bypass_verdict = true;
  }
  chrome.runtime.sendNativeMessage(NATIVE_HOST, payload, (response) => {
    if (chrome.runtime.lastError) {
      const m = chrome.runtime.lastError.message || "";
      console.error("LinkCage error:", m);
      if (isHostMissingError(m)) {
        showSetupNotification();
      }
      return;
    }
    if (!response) {
      console.error("LinkCage: empty response from native host");
      return;
    }

    if (response.status === "blocked") {
      const blockedVerdict = response.verdict || { level: "MALICIOUS" };
      console.warn("LinkCage: blocked by verdict", blockedVerdict);
      setBadgeForVerdict("MALICIOUS");
      promptBypassMalicious(url, blockedVerdict);
      return;
    }

    if (response.status === "error") {
      console.error("LinkCage error:", response.error);
      return;
    }

    // ok or partial
    const verdict = response.verdict || {
      level: "UNKNOWN",
      source: "no-provider",
      reason: "No verdict returned",
    };
    setBadgeForVerdict(verdict.level);
    showVerdictNotification(url, verdict);

    if (response.status === "partial") {
      console.warn("LinkCage partial:", response.warning);
    }
    console.log("LinkCage: URL sent to sandbox:", url);
  });
}
