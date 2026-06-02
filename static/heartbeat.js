// Tells the server this tab is still open. When the tab closes, the pings stop
// and the server drops the user from the active list after ACTIVE_TIMEOUT.
(function () {
  function ping() {
    fetch("/heartbeat", { method: "POST", keepalive: true }).catch(function () {});
  }
  ping();
  setInterval(ping, 5000);
})();
