chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.url && tab.url && tab.url.includes("youtube.com/watch")) {
    chrome.tabs.sendMessage(tabId, { type: "URL_CHANGED", url: tab.url });
  }
});
