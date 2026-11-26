(function () {
  "use strict";

  function fmt(n) {
    n = Number(n) || 0;
    if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, "") + "K";
    return String(n);
  }

  var player = document.getElementById("player");
  if (player) {
    var id = location.pathname.split("/").pop();
    var counted = false;
    try { counted = sessionStorage.getItem("viewed:" + id) === "1"; } catch (e) {}
    player.addEventListener("play", function () {
      if (counted) return;
      counted = true;
      try { sessionStorage.setItem("viewed:" + id, "1"); } catch (e) {}
      fetch("/api/view/" + id, { method: "POST" }).then(function () {
        var el = document.querySelector("[data-views]");
        if (el) {
          var n = Number(el.getAttribute("data-views")) + 1;
          el.setAttribute("data-views", n);
          el.textContent = fmt(n) + " views";
        }
      }).catch(function () {});
    });
  }

  document.querySelectorAll(".like-btn").forEach(function (btn) {
    var vid = btn.getAttribute("data-id");
    var key = "liked:" + vid;
    var count = btn.querySelector(".like-count");
    var liked = false;
    try { liked = localStorage.getItem(key) === "1"; } catch (e) {}
    if (liked) btn.classList.add("liked");

    btn.addEventListener("click", function () {
      var on = btn.classList.toggle("liked");
      try { localStorage.setItem(key, on ? "1" : "0"); } catch (e) {}
      fetch("/api/like/" + vid, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ delta: on ? 1 : -1 })
      })
        .then(function (r) { return r.json(); })
        .then(function (data) { if (data && count) count.textContent = fmt(data.likes); })
        .catch(function () {});
    });
  });

  document.querySelectorAll(".copy-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var url = location.origin + btn.getAttribute("data-path");
      var done = function () {
        var old = btn.textContent;
        btn.textContent = "Copied";
        setTimeout(function () { btn.textContent = old; }, 1500);
      };
      if (navigator.clipboard) {
        navigator.clipboard.writeText(url).then(done).catch(function () {});
      } else {
        window.prompt("Copy this link:", url);
      }
    });
  });
})();


