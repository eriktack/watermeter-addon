// Live page: capture on demand, and refresh the page every capture interval (task B3).
(function () {
  "use strict";

  var live = document.querySelector(".live");
  var button = document.getElementById("capture");
  var status = document.getElementById("status");
  var seconds = Number(live && live.dataset.interval) || 60;

  if (button) {
    button.addEventListener("click", function () {
      button.disabled = true;
      status.textContent = "Capturing…";
      fetch("api/capture", { method: "POST" })
        .then(function (response) {
          if (response.ok) { setTimeout(function () { location.reload(); }, 3000); return; }
          // the server says why (e.g. "no camera address: set esphome_host ..."); show that, not just the status
          return response.json().catch(function () { return {}; }).then(function (body) {
            throw new Error(body.error || "HTTP " + response.status);
          });
        })
        .catch(function (error) {
          status.textContent = "Capture failed: " + error.message;
          button.disabled = false;
        });
    });
  }

  var setButton = document.getElementById("set-value-button");
  var setStatus = document.getElementById("set-status");
  if (setButton) {
    setButton.addEventListener("click", function () {
      var value = document.getElementById("set-value").value.trim();
      if (!value || !confirm("Set the current volume to " + value + " m³?")) return;
      fetch("api/set_value", { method: "POST", headers: { "Content-Type": "application/json" },
                               body: JSON.stringify({ value: value }) })
        .then(function (response) {
          return response.json().catch(function () { return {}; }).then(function (body) {
            if (!response.ok) throw new Error(body.error || "HTTP " + response.status);
            location.reload();
          });
        })
        .catch(function (error) { setStatus.textContent = "Not set: " + error.message; setStatus.className = "bad"; });
    });
  }

  setTimeout(function () { location.reload(); }, seconds * 1000);
})();
