// Every page: times are stored in UTC; show them in the browser's local time as "YYYY-MM-DD HH:MM:SS".
(function () {
  "use strict";
  var pad = function (n) { return String(n).padStart(2, "0"); };
  document.querySelectorAll("time[datetime]").forEach(function (el) {
    var d = new Date(el.getAttribute("datetime"));
    if (isNaN(d)) return;
    el.textContent = d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + " " +
      pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
    el.title = el.getAttribute("datetime");
  });
})();
