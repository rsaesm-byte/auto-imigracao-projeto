(function () {
  "use strict";

  var POLL_INTERVAL_MS = 5000;
  var CYCLE_INTERVAL_MS = 700;
  var VARIANTS = ["color", "green", "brown", "black", "red"];

  var widget = document.getElementById("notif-widget");
  if (!widget) return; // widget not present on this page (shouldn't happen on staff pages)

  // Pedido do usuário 2026-08-06: este mesmo script agora atende tanto o
  // widget da equipe quanto o do cliente -- as URLs vêm de data-attributes
  // (ver _notification_widget.html), com fallback pras rotas da equipe
  // (comportamento original, caso algum include antigo não passe nada).
  var POLL_URL = widget.dataset.pollUrl || "/staff/notifications/poll";
  var MARK_READ_URL = widget.dataset.markReadUrl || "/staff/notifications/marcar-lidas";

  var iconBtn = document.getElementById("notif-icon-btn");
  var countEl = document.getElementById("notif-count");
  var panel = document.getElementById("notif-panel");
  var panelList = document.getElementById("notif-panel-list");
  var panelEmpty = document.getElementById("notif-panel-empty");
  var markReadBtn = document.getElementById("notif-mark-read-btn");
  var sound = document.getElementById("notif-sound");
  var imgs = {};
  widget.querySelectorAll(".notif-symbol-img").forEach(function (img) {
    imgs[img.dataset.variant] = img;
  });

  var lastSeenId = 0;
  var firstPollDone = false;
  var unreadCount = 0;
  var cycleTimer = null;
  var cycleIndex = 0;
  var panelOpen = false;

  function setActiveVariant(variant) {
    VARIANTS.forEach(function (v) {
      imgs[v].classList.toggle("active", v === variant);
    });
  }

  function startCycling() {
    if (cycleTimer) return;
    iconBtn.classList.add("cycling");
    cycleTimer = setInterval(function () {
      cycleIndex = (cycleIndex + 1) % VARIANTS.length;
      setActiveVariant(VARIANTS[cycleIndex]);
    }, CYCLE_INTERVAL_MS);
  }

  function stopCycling() {
    if (cycleTimer) {
      clearInterval(cycleTimer);
      cycleTimer = null;
    }
    iconBtn.classList.remove("cycling");
    setActiveVariant("color");
  }

  function updateCount(unread) {
    unreadCount = unread;
    if (unread > 0) {
      countEl.textContent = unread > 99 ? "99+" : String(unread);
      countEl.style.display = "";
      startCycling();
    } else {
      countEl.style.display = "none";
      stopCycling();
    }
  }

  function timeAgo(iso) {
    var diffMs = Date.now() - new Date(iso + "Z").getTime();
    var mins = Math.floor(diffMs / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return mins + "m ago";
    var hours = Math.floor(mins / 60);
    if (hours < 24) return hours + "h ago";
    return Math.floor(hours / 24) + "d ago";
  }

  function renderPanel(notifications) {
    panelList.innerHTML = "";
    if (!notifications.length) {
      panelEmpty.style.display = "";
      panelList.appendChild(panelEmpty);
      return;
    }
    panelEmpty.style.display = "none";
    notifications.slice().reverse().forEach(function (n) {
      var a = document.createElement("a");
      a.className = "notif-panel-item" + (n.read ? "" : " unread");
      a.href = n.url || "#";
      var title = document.createElement("p");
      title.className = "notif-panel-item-title";
      title.textContent = n.title;
      var body = document.createElement("p");
      body.className = "notif-panel-item-body";
      body.textContent = n.body || "";
      var time = document.createElement("span");
      time.className = "notif-panel-item-time";
      time.textContent = timeAgo(n.created_at);
      a.appendChild(title);
      if (n.body) a.appendChild(body);
      a.appendChild(time);
      panelList.appendChild(a);
    });
  }

  function loadPanel() {
    fetch(POLL_URL + "?limit=20", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (data) renderPanel(data.notifications || []);
      })
      .catch(function () { /* silencioso */ });
  }

  iconBtn.addEventListener("click", function () {
    panelOpen = !panelOpen;
    panel.hidden = !panelOpen;
    iconBtn.setAttribute("aria-expanded", String(panelOpen));
    if (panelOpen) loadPanel();
  });

  document.addEventListener("click", function (evt) {
    if (panelOpen && !widget.contains(evt.target)) {
      panelOpen = false;
      panel.hidden = true;
      iconBtn.setAttribute("aria-expanded", "false");
    }
  });

  markReadBtn.addEventListener("click", function (evt) {
    evt.preventDefault();
    fetch(MARK_READ_URL, { method: "POST", credentials: "same-origin" })
      .then(function () {
        updateCount(0);
        loadPanel();
      })
      .catch(function () { /* silencioso */ });
  });

  function poll() {
    var url = POLL_URL + "?since_id=" + lastSeenId;
    fetch(url, { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        if (firstPollDone && data.notifications && data.notifications.length) {
          try { sound.currentTime = 0; sound.play().catch(function () {}); } catch (e) { /* ignore */ }
          if (panelOpen) loadPanel();
        }
        updateCount(data.unread_count);
        lastSeenId = data.latest_id || lastSeenId;
        firstPollDone = true;
      })
      .catch(function () { /* tenta de novo no próximo poll */ });
  }

  poll();
  setInterval(poll, POLL_INTERVAL_MS);
})();
