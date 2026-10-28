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

  setTimeout(function () { location.reload(); }, seconds * 1000);
})();
