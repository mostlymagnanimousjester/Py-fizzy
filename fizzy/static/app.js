(function () {
  const token = document.querySelector('meta[name="csrf-token"]');
  const csrf = token ? token.getAttribute("content") : "";
  const slug = document.body.dataset.slug || "";
  const board = document.querySelector(".card-columns");
  const desktopQuery = window.matchMedia("(min-width: 640px)");

  function typing(event) {
    const target = event.target;
    if (!target || !target.closest) return false;
    return !!target.closest("input, textarea, select, [contenteditable]");
  }

  function columns() {
    return board ? Array.from(board.querySelectorAll("section.cards")) : [];
  }

  function isDesktop() {
    return desktopQuery.matches;
  }

  function storageKey(column) {
    return "expand-" + (board ? board.dataset.board : "") + "-" + column.id;
  }

  function setExpanded(column, on) {
    if (column.id === "lane-maybe" && isDesktop()) on = true;
    column.classList.toggle("is-expanded", on);
    column.classList.toggle("is-collapsed", !on);
    const button = column.querySelector(".cards__expander");
    if (button) {
      button.setAttribute("aria-expanded", on ? "true" : "false");
      button.disabled = column.id === "lane-maybe" && isDesktop();
    }
  }

  function remember(column, on) {
    if (!column.id || column.id === "lane-maybe") return;
    if (on) localStorage.setItem(storageKey(column), "true");
    else localStorage.removeItem(storageKey(column));
  }

  function visibleCards(column) {
    if (!column || column.classList.contains("is-collapsed")) return [];
    return Array.from(column.querySelectorAll(".cards__list article.card"));
  }

  function selectCard(card) {
    document.querySelectorAll('article.card[aria-selected="true"]').forEach(function (item) {
      item.removeAttribute("aria-selected");
    });
    if (!card) return;
    card.setAttribute("aria-selected", "true");
    if (document.activeElement !== card) card.focus({ preventScroll: true });
    card.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  function selectedCard() {
    const card = document.querySelector('article.card[aria-selected="true"]');
    if (!card || (card.closest("section.cards") && card.closest("section.cards").classList.contains("is-collapsed"))) return null;
    return card;
  }

  function showColumn(column) {
    if (!column) return;
    if (isDesktop()) {
      columns().forEach(function (item) {
        if (item.id === "lane-maybe") setExpanded(item, true);
        else if (item !== column) {
          setExpanded(item, false);
          remember(item, false);
        }
      });
      setExpanded(column, true);
      remember(column, true);
    } else {
      columns().forEach(function (item) {
        const on = item === column;
        setExpanded(item, on);
        remember(item, on);
      });
      column.scrollIntoView({ behavior: "smooth", inline: "center" });
    }
    const cards = visibleCards(column);
    if (cards.length) selectCard(cards[0]);
    else {
      selectCard(null);
      column.focus();
    }
  }

  function collapseSide(column) {
    setExpanded(column, false);
    remember(column, false);
    const current = selectedCard();
    if (current && column.contains(current)) {
      const maybe = document.getElementById("lane-maybe");
      const cards = visibleCards(maybe);
      if (cards.length) selectCard(cards[0]);
    }
  }

  function restoreColumns() {
    if (!board) return;
    const saved = columns().filter(function (column) {
      return column.id !== "lane-maybe" && localStorage.getItem(storageKey(column));
    });
    columns().forEach(function (column) {
      setExpanded(column, column.id === "lane-maybe");
    });
    if (isDesktop()) {
      const last = saved[saved.length - 1];
      if (last) showColumn(last);
      else {
        const maybe = document.getElementById("lane-maybe");
        const cards = visibleCards(maybe);
        if (cards.length) selectCard(cards[0]);
      }
      return;
    }
    if (saved.length) showColumn(saved[saved.length - 1]);
    else {
      const maybe = document.getElementById("lane-maybe");
      if (maybe) showColumn(maybe);
    }
  }

  function activeColumn() {
    const selected = selectedCard();
    if (selected) {
      const column = selected.closest("section.cards");
      if (column) return column;
    }
    const focused = document.activeElement && document.activeElement.closest
      ? document.activeElement.closest("section.cards")
      : null;
    if (focused) return focused;
    return document.querySelector("section.cards.is-expanded");
  }

  function moveColumn(direction) {
    const list = columns();
    if (!list.length) return;
    const current = activeColumn() || list[0];
    const index = Math.max(0, list.indexOf(current));
    const next = list[index + direction];
    if (!next) return;
    if (next.classList.contains("is-collapsed")) showColumn(next);
    else {
      const cards = visibleCards(next);
      if (cards.length) selectCard(cards[0]);
      else {
        selectCard(null);
        next.focus();
      }
    }
  }

  function moveCard(direction) {
    const column = activeColumn();
    const cards = visibleCards(column);
    if (!cards.length) return;
    const current = selectedCard();
    let index = cards.indexOf(current);
    if (index < 0) index = direction > 0 ? -1 : cards.length;
    const next = cards[index + direction];
    if (next) selectCard(next);
  }

  function post(url, fields) {
    const body = new FormData();
    body.append("csrf_token", csrf);
    if (fields) {
      Object.keys(fields).forEach(function (key) {
        body.append(key, fields[key]);
      });
    }
    return fetch(url, { method: "POST", body: body, credentials: "same-origin" }).then(function (response) {
      if (response.ok) window.location.reload();
      else window.alert("Could not update that card.");
    });
  }

  function clickHotkey(name) {
    const button = document.querySelector('[data-hotkey="' + name + '"]');
    if (button) button.click();
    return !!button;
  }

  function dialogById(id) {
    return document.getElementById(id);
  }

  function toggleDialog(id, modal) {
    const dialog = dialogById(id);
    if (!dialog) return;
    if (dialog.open) {
      dialog.close();
      return;
    }
    document.querySelectorAll("dialog[open]").forEach(function (open) {
      open.close();
    });
    if (modal) dialog.showModal();
    else dialog.show();
  }

  function utcDay(date) {
    return Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate());
  }

  function dayDiff(from, to) {
    return Math.round((utcDay(to) - utcDay(from)) / 86400000);
  }

  document.querySelectorAll(".bubble").forEach(function (bubble, index) {
    const closes = bubble.dataset.closesAt;
    const reminder = Number(bubble.dataset.reminderDays || "0");
    const stalled = bubble.dataset.stalledAt;
    let top = "";
    let center = "";
    let bottom = "";
    if (closes) {
      const days = dayDiff(new Date(), new Date(closes));
      if (days < reminder) {
        if (days < 1) {
          top = "Closes";
          center = "!";
          bottom = "Today";
        } else {
          top = "Closes in";
          center = String(days);
          bottom = days === 1 ? "day" : "days";
        }
      }
    }
    if (!top && stalled) {
      const days = Math.max(dayDiff(new Date(stalled), new Date()), 0);
      top = "Stalled for";
      center = String(days);
      bottom = "days";
    }
    if (!top) return;
    bubble.querySelectorAll("[data-bubble]").forEach(function (node) {
      const slot = node.getAttribute("data-bubble");
      node.textContent = slot === "top" ? top : slot === "center" ? center : bottom;
    });
    const turns = [-8, 6, -4, 11, -12, 3, 9];
    bubble.style.setProperty("--bubble-rotate", turns[index % turns.length] + "deg");
    bubble.hidden = false;
  });

  if (board) {
    restoreColumns();
    board.querySelectorAll(".cards__expander").forEach(function (button) {
      button.addEventListener("click", function () {
        const column = button.closest("section.cards");
        if (!column || (column.id === "lane-maybe" && isDesktop())) return;
        if (column.classList.contains("is-expanded") && column.id !== "lane-maybe") collapseSide(column);
        else showColumn(column);
      });
    });
    desktopQuery.addEventListener("change", restoreColumns);
  }

  document.querySelectorAll(".add-card__toggle").forEach(function (button) {
    button.addEventListener("click", function () {
      const fields = button.parentElement.querySelector(".add-card__fields");
      if (!fields) return;
      fields.hidden = false;
      button.hidden = true;
      const input = fields.querySelector("input");
      if (input) input.focus();
    });
  });

  document.querySelectorAll("article.card").forEach(function (card) {
    if (card.getAttribute("draggable") === "true") {
      card.addEventListener("dragstart", function (event) {
        event.dataTransfer.setData("text/plain", card.dataset.number);
        event.dataTransfer.effectAllowed = "move";
        card.classList.add("dragging");
      });
      card.addEventListener("dragend", function () {
        card.classList.remove("dragging");
      });
    }
    card.addEventListener("click", function (event) {
      if (event.target.closest("a, button, input, textarea, select, summary, form")) return;
      const link = card.querySelector(".card__link");
      if (link) window.location.href = link.href;
    });
  });

  document.querySelectorAll("section.cards").forEach(function (column) {
    if (!column.dataset.columnId && !column.dataset.lane) return;
    column.addEventListener("dragover", function (event) {
      event.preventDefault();
      column.classList.add("over");
    });
    column.addEventListener("dragleave", function () {
      column.classList.remove("over");
    });
    column.addEventListener("drop", function (event) {
      event.preventDefault();
      column.classList.remove("over");
      const number = event.dataTransfer.getData("text/plain");
      if (!number || !slug) return;
      let url = slug + "/cards/" + number + "/triage";
      const fields = {};
      if (column.dataset.columnId) fields.column_id = column.dataset.columnId;
      else if (column.dataset.lane === "maybe") fields._method = "delete";
      else if (column.dataset.lane === "not_now") url = slug + "/cards/" + number + "/not_now";
      else if (column.dataset.lane === "closed") url = slug + "/cards/" + number + "/closure";
      else return;
      post(url, fields);
    });
  });

  const bar = document.querySelector(".bar");
  const barInput = document.querySelector(".bar__input");
  if (bar && barInput && barInput.value) bar.classList.add("is-open");

  const jumpFilter = document.querySelector("[data-jump-filter]");
  if (jumpFilter) {
    jumpFilter.addEventListener("input", function () {
      const query = jumpFilter.value.trim().toLowerCase();
      document.querySelectorAll("[data-jump-list] a").forEach(function (link) {
        link.hidden = !!query && !link.textContent.toLowerCase().includes(query);
      });
    });
  }

  document.addEventListener("keydown", function (event) {
    const key = event.key;
    const meta = event.metaKey || event.ctrlKey;
    const plain = !meta && !event.altKey && !event.shiftKey;
    const jump = dialogById("jump");

    if (key === "Escape") {
      const open = document.querySelector("dialog[open]");
      if (open) {
        open.close();
        event.preventDefault();
        return;
      }
      if (bar && bar.classList.contains("is-open") && event.target === barInput) {
        bar.classList.remove("is-open");
        barInput.blur();
        event.preventDefault();
        return;
      }
      if (!typing(event)) {
        const back = document.querySelector("[data-back]");
        if (back) {
          event.preventDefault();
          back.click();
        }
      }
      return;
    }

    if (meta && key === "Enter") {
      const form = event.target.closest && event.target.closest("form");
      if (form) {
        event.preventDefault();
        if (form.requestSubmit) form.requestSubmit();
        else form.submit();
      }
      return;
    }

    if ((key === "j" || key === "J") && (plain || (meta && !event.shiftKey && !event.altKey)) && !typing(event)) {
      event.preventDefault();
      toggleDialog("jump", true);
      if (jump && jump.open && jumpFilter) jumpFilter.focus();
      return;
    }

    if (jump && jump.open && plain && (key === "1" || key === "2" || key === "3")) {
      if (event.target === jumpFilter && jumpFilter.value) return;
      const link = document.querySelector('a[data-menu-key="' + key + '"]');
      if (link) {
        event.preventDefault();
        link.click();
      }
      return;
    }

    if (typing(event)) return;
    const trayKey = plain && (key === "p" || key === "P" || key === "n" || key === "N" || key === "k" || key === "K");
    if (document.querySelector("dialog[open]") && !trayKey) return;

    if (plain && (key === "k" || key === "K")) {
      if (!bar || !barInput) return;
      event.preventDefault();
      bar.classList.add("is-open");
      barInput.focus();
      barInput.select();
      return;
    }
    if (event.shiftKey && !meta && !event.altKey && key === "P") {
      if (clickHotkey("pin")) event.preventDefault();
      return;
    }
    if (plain && (key === "p" || key === "P")) {
      event.preventDefault();
      toggleDialog("pins-tray", false);
      return;
    }
    if (event.shiftKey && !meta && !event.altKey && key === "N") {
      if (clickHotkey("watch")) event.preventDefault();
      return;
    }
    if (plain && (key === "n" || key === "N")) {
      event.preventDefault();
      toggleDialog("notes-tray", false);
      return;
    }
    if (plain && (key === "f" || key === "F")) {
      const filter = document.querySelector('[data-hotkey-target="filter"]');
      if (filter) {
        event.preventDefault();
        filter.focus();
      }
      return;
    }
    if (plain && (key === "ArrowLeft" || key === "ArrowRight" || key === "ArrowUp" || key === "ArrowDown")) {
      if (board && columns().length) {
        event.preventDefault();
        if (key === "ArrowRight") moveColumn(1);
        else if (key === "ArrowLeft") moveColumn(-1);
        else if (key === "ArrowDown") moveCard(1);
        else moveCard(-1);
        return;
      }
      if (key === "ArrowLeft") {
        const back = document.querySelector("[data-back]");
        if (back) {
          event.preventDefault();
          back.click();
        }
      }
      return;
    }
    if (plain && key === "Enter" && board) {
      const card = selectedCard();
      const link = card && card.querySelector(".card__link");
      if (link) {
        event.preventDefault();
        window.location.href = link.href;
      }
      return;
    }
    if (plain && key === "[") {
      const card = selectedCard();
      if (card && card.dataset.notNowUrl) {
        event.preventDefault();
        post(card.dataset.notNowUrl);
        return;
      }
      if (clickHotkey("postpone")) event.preventDefault();
      return;
    }
    if (plain && key === "]") {
      const card = selectedCard();
      if (card && card.dataset.closureUrl) {
        event.preventDefault();
        post(card.dataset.closureUrl);
        return;
      }
      if (clickHotkey("done")) event.preventDefault();
      return;
    }
    if (plain && (key === "m" || key === "M")) {
      const card = board ? selectedCard() : null;
      if (card && card.dataset.assignUrl) {
        event.preventDefault();
        post(card.dataset.assignUrl);
        return;
      }
      if (clickHotkey("me")) event.preventDefault();
      return;
    }
    if (event.shiftKey && !meta && !event.altKey && key === "G") {
      if (clickHotkey("gold")) event.preventDefault();
      return;
    }
    if (plain && (key === "d" || key === "D")) {
      if (clickHotkey("done")) event.preventDefault();
      return;
    }
    if (plain && (key === "e" || key === "E")) {
      const edit = document.querySelector('[data-hotkey-target="edit"]');
      if (edit) {
        event.preventDefault();
        edit.focus();
        if (edit.select) edit.select();
        return;
      }
      if (clickHotkey("edit")) event.preventDefault();
      return;
    }
    if (plain && (key === "t" || key === "T")) {
      const tag = document.querySelector('[data-hotkey-target="tag"]');
      if (tag) {
        event.preventDefault();
        tag.focus();
      }
      return;
    }
    if (plain && (key === "a" || key === "A")) {
      const assign = document.querySelector('[data-hotkey-target="assign"]');
      if (assign) {
        event.preventDefault();
        assign.focus();
      }
    }
  });

  document.querySelectorAll("form.danger").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      const label = (form.querySelector("button") || {}).textContent || "this";
      if (!window.confirm("Continue and " + label.trim().toLowerCase() + "?")) event.preventDefault();
    });
  });

  const editForm = document.querySelector("form.card__edit");
  if (editForm) {
    const titleInput = editForm.querySelector("[name='card[title]']");
    const descriptionInput = editForm.querySelector("[name='card[description]']");
    document.querySelectorAll("form").forEach(function (form) {
      if (form === editForm) return;
      form.addEventListener("submit", function (event) {
        if (event.defaultPrevented || !titleInput || !descriptionInput) return;
        if (titleInput.value === titleInput.defaultValue && descriptionInput.value === descriptionInput.defaultValue) return;
        event.preventDefault();
        fetch(editForm.action, { method: "POST", body: new FormData(editForm), credentials: "same-origin" }).then(function (response) {
          if (!response.ok) {
            window.alert("Could not save the card before that change.");
            return;
          }
          titleInput.defaultValue = titleInput.value;
          descriptionInput.defaultValue = descriptionInput.value;
          form.submit();
        });
      });
    });
  }
  document.documentElement.dataset.fizzyReady = "1";
})();
