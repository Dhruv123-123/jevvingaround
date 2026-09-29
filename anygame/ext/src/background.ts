// The action button opens the side panel for the current tab; everything else lives in the panel page.
chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
});
chrome.action.onClicked.addListener((tab) => {
  if (tab.id !== undefined) chrome.sidePanel.open({ tabId: tab.id }).catch(() => {});
});
