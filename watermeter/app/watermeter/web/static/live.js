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
          if (!response.ok) throw new Error("HTTP " + response.status);
          setTimeout(function () { location.reload(); }, 3000);
        })
        .catch(function (error) {
          status.textContent = "Capture failed: " + error.message;
          button.disabled = false;
        });
    });
  }

  setTimeout(function () { location.reload(); }, seconds * 1000);
})();
