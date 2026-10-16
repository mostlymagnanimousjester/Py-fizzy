(function () {
  const token = document.querySelector('meta[name="csrf-token"]');
  const csrf = token ? token.getAttribute("content") : "";
  const slug = document.body.dataset.slug || "";
  const desktopQuery = window.matchMedia("(min-width: 640px)");

  function typing(event) {
    const target = event.target;
    if (!target || !target.closest) return false;
    return !!target.closest("input, textarea, select, [contenteditable]");
  }

  function boardRoot() {
    return document.querySelector(".card-columns");
  }

  function columns() {
    const root = boardRoot();
    return root ? Array.from(root.querySelectorAll("section.cards")) : [];
  }

  function isDesktop() {
    return desktopQuery.matches;
  }

  function storageKey(column) {
    const root = boardRoot();
    return "expand-" + (root ? root.dataset.board : "") + "-" + column.id;
  }

  function setExpanded(column, on) {
    if (column.id === "maybe" && isDesktop()) on = true;
    column.classList.toggle("is-expanded", on);
    column.classList.toggle("is-collapsed", !on);
    const button = column.querySelector(".cards__expander");
    if (button) {
      button.setAttribute("aria-expanded", on ? "true" : "false");
      button.disabled = column.id === "maybe" && isDesktop();
    }
  }

  function remember(column, on) {
    if (!column.id || column.id === "maybe") return;
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
    // The card outline is drawn only inside a column that is itself selected.
    const column = card.closest("section.cards");
    document.querySelectorAll("section.cards[aria-selected='true']").forEach(function (item) {
      if (item !== column) item.removeAttribute("aria-selected");
    });
    if (column) column.setAttribute("aria-selected", "true");
    card.setAttribute("aria-selected", "true");
    const active = document.activeElement;
    const field = active && active.closest && active.closest("input, textarea, select, [contenteditable]");
    if (!field && active !== card) card.focus({ preventScroll: true });
    card.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  function selectFirstMaybe() {
    const cards = visibleCards(document.getElementById("maybe"));
    if (cards.length) selectCard(cards[0]);
  }

  function selectedCard() {
    const card = document.querySelector('article.card[aria-selected="true"]');
    if (!card || (card.closest("section.cards") && card.closest("section.cards").classList.contains("is-collapsed"))) return null;
    return card;
  }

  function showColumn(column, options) {
    if (!column) return;
    const choose = !options || options.select !== false;
    if (isDesktop()) {
      columns().forEach(function (item) {
        if (item.id === "maybe") setExpanded(item, true);
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
    if (!choose) return;
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
      const maybe = document.getElementById("maybe");
      const cards = visibleCards(maybe);
      if (cards.length) selectCard(cards[0]);
    }
  }

  function restoreColumns() {
    const root = boardRoot();
    if (!root) return;
    const saved = columns().filter(function (column) {
      return column.id !== "maybe" && localStorage.getItem(storageKey(column));
    });
    columns().forEach(function (column) {
      setExpanded(column, column.id === "maybe");
    });
    if (isDesktop()) {
      const last = saved[saved.length - 1];
      // A remembered column stays open, but keys start on the first Maybe card.
      if (last) showColumn(last, { select: false });
      selectFirstMaybe();
      return;
    }
    if (saved.length) showColumn(saved[saved.length - 1]);
    else {
      const maybe = document.getElementById("maybe");
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

  function gridElement() {
    if (boardRoot()) return null;
    return document.querySelector(".cards-grid, .card-grid, .cards--grid");
  }

  function listedCards() {
    if (boardRoot()) return visibleCards(activeColumn());
    const grid = gridElement();
    return grid ? Array.from(grid.querySelectorAll("article.card")) : [];
  }

  function moveColumn(direction) {
    const list = columns();
    if (!list.length) return false;
    const sign = direction < 0 ? -1 : 1;
    const steps = Math.max(1, Math.abs(direction));
    const current = activeColumn() || list[0];
    const from = visibleCards(current);
    const selected = selectedCard();
    let cardIndex = from.indexOf(selected);
    if (cardIndex < 0) cardIndex = 0;
    const index = Math.max(0, list.indexOf(current));
    const destIndex = Math.max(0, Math.min(list.length - 1, index + sign * steps));
    if (destIndex === index) return false;
    const dest = list[destIndex];
    if (dest.classList.contains("is-collapsed")) showColumn(dest, { select: false });
    const cards = visibleCards(dest);
    if (cards.length) selectCard(cards[Math.min(cardIndex, cards.length - 1)]);
    else {
      selectCard(null);
      dest.focus();
    }
    return true;
  }

  function moveCard(direction) {
    const cards = listedCards();
    if (!cards.length) return false;
    const sign = direction < 0 ? -1 : 1;
    const steps = Math.max(1, Math.abs(direction));
    const current = selectedCard();
    let index = cards.indexOf(current);
    if (index < 0) index = sign > 0 ? -1 : cards.length;
    const dest = Math.max(0, Math.min(cards.length - 1, index + sign * steps));
    if (cards[dest] === current) return false;
    selectCard(cards[dest]);
    return true;
  }

  function moveGrid(direction) {
    return moveCard(direction);
  }

  function recount(column) {
    if (!column) return;
    const count = column.querySelectorAll(".cards__list article.card").length;
    column.style.setProperty("--card-count", String(Math.min(count, 15)));
    column.dataset.cardCount = String(count);
    const badge = column.querySelector(".cards__expander-count");
    if (badge) badge.textContent = count > 99 ? "99+" : String(count);
  }

  function escapeHtml(value) {
    return String(value || "").replace(/[&<>"']/g, function (char) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char];
    });
  }

  function utcDay(date) {
    return Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate());
  }

  function dayDiff(from, to) {
    return Math.round((utcDay(to) - utcDay(from)) / 86400000);
  }

  function paintBubble(bubble) {
    if (!bubble) return;
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
    if (!top) {
      bubble.hidden = true;
      return;
    }
    bubble.querySelectorAll("[data-bubble]").forEach(function (node) {
      const slot = node.getAttribute("data-bubble");
      node.textContent = slot === "top" ? top : slot === "center" ? center : bottom;
    });
    const turns = [-8, 6, -4, 11, -12, 3, 9];
    const index = Number((bubble.closest("article") || {}).dataset.number || 0);
    bubble.style.setProperty("--bubble-rotate", turns[index % turns.length] + "deg");
    bubble.hidden = false;
  }

  function paintBubbles(root) {
    (root || document).querySelectorAll(".bubble").forEach(paintBubble);
  }

  let holdSelection = false;

  function laneColumn(lane) {
    if (!lane) return null;
    return document.getElementById("column-" + lane)
      || document.getElementById("lane-" + lane)
      || document.querySelector('section.cards[data-lane="' + lane + '"]');
  }

  function placeCard(payload) {
    const template = document.createElement("template");
    template.innerHTML = (payload.html || "").trim();
    const fresh = template.content.querySelector("article.card");
    if (!fresh) return;
    const current = document.querySelector('article.card[data-number="' + payload.number + '"]');
    const sourceColumn = current && current.closest("section.cards");
    let neighbor = null;
    if (current) {
      neighbor = current.nextElementSibling && current.nextElementSibling.matches("article.card")
        ? current.nextElementSibling
        : current.previousElementSibling;
      if (neighbor && !neighbor.matches("article.card")) neighbor = null;
      current.replaceWith(fresh);
    }
    const target = laneColumn(payload.lane);
    const list = target && target.querySelector(".cards__list");
    if (list && !list.contains(fresh)) {
      if (fresh.classList.contains("golden-effect")) list.prepend(fresh);
      else list.appendChild(fresh);
    }
    recount(sourceColumn);
    recount(target);
    paintBubble(fresh.querySelector(".bubble"));
    if (holdSelection) return;
    if (payload.stay) {
      selectCard(fresh);
      return;
    }
    const home = neighbor && neighbor.closest("section.cards");
    if (neighbor && neighbor.isConnected && home && visibleCards(home).indexOf(neighbor) >= 0) selectCard(neighbor);
    else if (neighbor && neighbor.isConnected && neighbor.closest(".cards-grid, .card-grid, .cards--grid")) selectCard(neighbor);
    else chooseFallback();
  }

  function chooseFallback() {
    if (boardRoot()) {
      selectFirstMaybe();
      return;
    }
    const cards = listedCards();
    if (cards.length) selectCard(cards[0]);
    else selectCard(null);
  }

  function post(url, fields) {
    const body = new FormData();
    body.append("csrf_token", csrf);
    if (fields) {
      Object.keys(fields).forEach(function (key) {
        body.append(key, fields[key]);
      });
    }
    const headers = {};
    if (boardRoot() || document.querySelector(".cards-grid, .card-grid, .cards--grid")) headers["X-Fizzy-Fragment"] = "card";
    return fetch(url, { method: "POST", body: body, credentials: "same-origin", headers: headers }).then(function (response) {
      if (!response.ok) {
        window.alert("Could not update that card.");
        return;
      }
      const type = response.headers.get("content-type") || "";
      if (type.indexOf("application/json") >= 0) {
        return response.json().then(function (payload) {
          if (payload && payload.html) placeCard(payload);
        });
      }
      window.location.reload();
    });
  }

  function formOf(node) {
    return node.closest("form");
  }

  function hiddenFor(form, name, value) {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = name.endsWith("[]") ? name : name + "[]";
    input.value = value;
    input.setAttribute("data-filter-hidden", name.replace(/\[\]$/, ""));
    input.setAttribute("data-filter-value", value);
    return input;
  }

  function submitFilter(form) {
    const typed = form.querySelector(".filter__terms");
    if (typed && !typed.value.trim()) typed.disabled = true;
    if (form.requestSubmit) form.requestSubmit();
    else form.submit();
  }

  function applyFilterClick(event) {
    const expand = event.target.closest("[data-filter-toggle-expand]");
    if (expand) {
      event.preventDefault();
      const filters = expand.closest(".filters");
      if (filters) {
        const expanded = filters.classList.toggle("filters--expanded");
        expand.classList.toggle("filter-toggle", !expanded);
        expand.classList.toggle("btn--reversed", expanded);
        if (expanded) expand.setAttribute("aria-selected", "true");
        else expand.removeAttribute("aria-selected");
      }
      return true;
    }
    const opener = event.target.closest("[data-filter-open]");
    if (opener) {
      event.preventDefault();
      const dialog = opener.parentElement.querySelector("dialog");
      if (!dialog) return true;
      const willOpen = !dialog.open;
      document.querySelectorAll("dialog[open]").forEach(function (open) { open.close(); });
      if (willOpen) dialog.show();
      return true;
    }
    const remove = event.target.closest("[data-filter-remove]");
    if (remove) {
      event.preventDefault();
      const form = formOf(remove);
      form.querySelectorAll('[data-filter-hidden="' + remove.dataset.filterRemove + '"]').forEach(function (input) {
        if (input.dataset.filterValue === remove.dataset.filterValue) input.remove();
      });
      submitFilter(form);
      return true;
    }
    const set = event.target.closest("[data-filter-set]");
    if (set) {
      event.preventDefault();
      const form = formOf(set);
      const field = form.querySelector('[name="' + set.dataset.filterSet + '"]');
      if (field) field.value = set.dataset.filterValue;
      if (set.dataset.filterClear) {
        form.querySelectorAll('[data-filter-hidden="' + set.dataset.filterClear + '"]').forEach(function (input) {
          input.remove();
        });
        const cleared = form.querySelector('[name="' + set.dataset.filterClear + '"]');
        if (cleared) cleared.value = "";
      }
      submitFilter(form);
      return true;
    }
    const toggle = event.target.closest("[data-filter-toggle]");
    if (toggle) {
      event.preventDefault();
      const form = formOf(toggle);
      const name = toggle.dataset.filterToggle;
      const value = toggle.dataset.filterValue;
      const existing = Array.from(form.querySelectorAll('[data-filter-hidden="' + name + '"]')).find(function (input) {
        return input.value === value;
      });
      if (existing) existing.remove();
      else form.appendChild(hiddenFor(form, name, value));
      if (toggle.dataset.filterClear) {
        const cleared = form.querySelector('[name="' + toggle.dataset.filterClear + '"]');
        if (cleared) cleared.value = "";
      }
      submitFilter(form);
      return true;
    }
    return false;
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

  function movableLinks(root) {
    return Array.from(root.querySelectorAll("a")).filter(function (link) {
      return !link.hidden && !link.classList.contains("tray__more") && link.offsetParent !== null;
    });
  }

  function moveLinks(root, direction) {
    const links = movableLinks(root);
    if (!links.length) return;
    const current = links.findIndex(function (link) {
      return link.getAttribute("aria-selected") === "true";
    });
    const nextIndex = current < 0 ? (direction > 0 ? 0 : links.length - 1) : Math.min(links.length - 1, Math.max(0, current + direction));
    links.forEach(function (link) {
      link.removeAttribute("aria-selected");
    });
    links[nextIndex].setAttribute("aria-selected", "true");
    links[nextIndex].focus();
  }

  paintBubbles(document);

  document.addEventListener("mouseover", function (event) {
    if (event.buttons || document.querySelector("dialog[open]")) return;
    const card = event.target.closest && event.target.closest("article.card");
    if (!card || !card.closest("#board-stage, .card-columns")) return;
    if (event.relatedTarget && card.contains(event.relatedTarget)) return;
    const column = card.closest("section.cards");
    if (column && column.classList.contains("is-collapsed")) return;
    if (card.getAttribute("aria-selected") === "true") return;
    selectCard(card);
  });

  if (boardRoot()) {
    restoreColumns();
    desktopQuery.addEventListener("change", restoreColumns);
  } else {
    chooseFallback();
  }

  function setCardEditing(on) {
    const display = document.querySelector("[data-card-display]");
    const editor = document.querySelector("[data-card-editor]");
    if (!editor || !display) return false;
    display.hidden = on;
    editor.hidden = !on;
    const actions = document.querySelector("[data-card-actions]");
    const save = document.querySelector("[data-card-save]");
    if (actions) actions.hidden = on;
    if (save) save.hidden = !on;
    if (on) {
      const title = editor.querySelector("[name='card[title]']");
      if (title) {
        title.focus();
        if (title.select) title.select();
      }
    }
    return true;
  }

  function closeReactionForm(form) {
    form.hidden = true;
    form.classList.remove("expanded");
    const reactions = form.closest(".reactions");
    const trigger = reactions && reactions.querySelector("[data-reaction-open]");
    if (trigger) trigger.hidden = false;
    const field = form.querySelector("input");
    if (field) field.value = "";
  }

  function openReactionForm(trigger) {
    const reactions = trigger.closest(".reactions");
    const form = reactions && reactions.querySelector("[data-reaction-form]");
    if (!form) return;
    trigger.hidden = true;
    form.hidden = false;
    form.classList.add("expanded");
    const field = form.querySelector("input");
    if (field) field.focus();
  }

  document.addEventListener("click", function (event) {
    const jumpButton = event.target.closest("[data-hotkey='jump']");
    if (jumpButton) {
      event.preventDefault();
      toggleDialog("jump", true);
      if (jumpFilter) jumpFilter.focus();
      return;
    }
    const trayToggle = event.target.closest(".tray__toggle");
    if (trayToggle) {
      event.preventDefault();
      toggleDialog(trayToggle.getAttribute("aria-controls"), false);
      return;
    }
    const searchButton = event.target.closest(".bar__placeholder [data-hotkey='k']");
    if (searchButton) {
      event.preventDefault();
      openSearch();
      return;
    }
    const dialogClose = event.target.closest("[data-dialog-close]");
    if (dialogClose) {
      const dialog = dialogClose.closest("dialog");
      if (dialog) dialog.close();
      return;
    }
    const emoji = event.target.closest("[data-emoji]");
    if (emoji) {
      event.preventDefault();
      const dialog = emoji.closest("dialog");
      const form = dialog && dialog.closest("form");
      const field = form && form.querySelector("input");
      if (field) {
        field.value = (field.value + emoji.dataset.emoji).slice(0, 16);
        field.focus();
      }
      if (dialog) dialog.close();
      return;
    }
    const reactionOpen = event.target.closest("[data-reaction-open]");
    if (reactionOpen) {
      event.preventDefault();
      openReactionForm(reactionOpen);
      return;
    }
    const reactionCancel = event.target.closest("[data-reaction-cancel]");
    if (reactionCancel) {
      event.preventDefault();
      const form = reactionCancel.closest("[data-reaction-form]");
      if (form) closeReactionForm(form);
      return;
    }
    const reactionReveal = event.target.closest("[data-reaction-reveal]");
    if (reactionReveal) {
      const reaction = reactionReveal.closest(".reaction");
      if (reaction) reaction.classList.toggle("expanded");
      return;
    }
    const history = event.target.closest("[data-history-toggle]");
    if (history) {
      const comments = history.closest(".comments");
      if (comments) comments.classList.toggle("comments--system-expanded");
      return;
    }
    const cardEdit = event.target.closest("[data-card-edit]");
    if (cardEdit) {
      event.preventDefault();
      setCardEditing(true);
      return;
    }
    const editColumn = event.target.closest("[data-column-edit]");
    if (editColumn) {
      event.preventDefault();
      const menu = editColumn.closest(".cards__menu");
      if (menu) {
        menu.querySelectorAll("dialog").forEach(function (open) { open.close(); });
        const formDialog = menu.querySelector("[data-column-form]");
        if (formDialog) {
          formDialog.show();
          const input = formDialog.querySelector("input[name='column[name]']");
          if (input) input.focus();
        }
      }
      return;
    }
    const menuButton = event.target.closest(".cards__menu > button, .cards__new-column > button");
    if (menuButton) {
      const dialog = menuButton.parentElement.querySelector("dialog");
      if (dialog) {
        event.preventDefault();
        if (dialog.open) dialog.close();
        else {
          document.querySelectorAll("dialog[open]").forEach(function (open) { open.close(); });
          dialog.show();
        }
      }
      return;
    }
    const maximize = event.target.closest(".cards__maximize-button");
    if (maximize) {
      event.preventDefault();
      showColumn(maximize.closest("section.cards"));
      return;
    }
    const dialogButton = event.target.closest("[data-dialog-open]");
    if (dialogButton) {
      event.preventDefault();
      const dialog = dialogButton.parentElement.querySelector("dialog");
      if (dialog) {
        if (dialog.open) dialog.close();
        else {
          document.querySelectorAll("dialog[open]").forEach(function (open) { open.close(); });
          if (dialogButton.closest("[data-dialog-modal]")) dialog.showModal();
          else dialog.show();
          const field = dialog.querySelector("input, textarea, select");
          if (field) field.focus();
        }
      }
      return;
    }
    if (applyFilterClick(event)) return;
    const expander = event.target.closest(".cards__expander");
    if (expander) {
      const column = expander.closest("section.cards");
      if (!column || (column.id === "maybe" && isDesktop())) return;
      if (column.classList.contains("is-expanded") && column.id !== "maybe") collapseSide(column);
      else showColumn(column);
      return;
    }
    const card = event.target.closest("article.card");
    if (!card || !card.closest(".cards, .cards-grid, .card-grid")) return;
    if (event.target.closest("a, button, input, textarea, select, summary, form")) return;
    const link = card.querySelector(".card__link");
    if (link) window.location.href = link.href;
  });

  document.addEventListener("dragstart", function (event) {
    const card = event.target.closest && event.target.closest("article.card");
    if (!card || card.getAttribute("draggable") !== "true") return;
    event.dataTransfer.setData("text/plain", card.dataset.number);
    event.dataTransfer.effectAllowed = "move";
    card.classList.add("drag-and-drop__dragged-item");
  });

  document.addEventListener("dragend", function () {
    document.querySelectorAll("article.card.drag-and-drop__dragged-item, section.cards.drag-and-drop__hover-container").forEach(function (node) {
      node.classList.remove("drag-and-drop__dragged-item", "drag-and-drop__hover-container");
    });
  });

  document.addEventListener("dragover", function (event) {
    const column = event.target.closest && event.target.closest("section.cards");
    if (!column || (!column.dataset.columnId && !column.dataset.lane)) return;
    event.preventDefault();
    column.classList.add("drag-and-drop__hover-container");
  });

  document.addEventListener("drop", function (event) {
    const column = event.target.closest && event.target.closest("section.cards");
    if (!column || (!column.dataset.columnId && !column.dataset.lane)) return;
    event.preventDefault();
    column.classList.remove("drag-and-drop__hover-container");
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

  const bar = document.querySelector(".bar");
  const barField = document.querySelector(".bar__input");
  const barInput = barField ? barField.querySelector("input") : null;
  const barResults = document.querySelector(".bar__results");
  const barModal = document.getElementById("bar-modal");
  const barPlaceholder = document.querySelector(".bar__placeholder");

  function openSearch() {
    if (!barField || !barInput) return;
    if (barPlaceholder) barPlaceholder.hidden = true;
    barField.hidden = false;
    barInput.focus();
    if (barInput.value) barInput.select();
  }

  function closeSearch() {
    if (barPlaceholder) barPlaceholder.hidden = false;
    if (barField) barField.hidden = true;
    if (barModal && barModal.open) barModal.close();
    if (barResults) barResults.innerHTML = "";
    if (barInput) barInput.blur();
  }

  if (barInput && barInput.value) openSearch();

  let searchGeneration = 0;
  let lastSearchCards = null;
  function renderSearch(cards) {
    lastSearchCards = cards || [];
    if (!barResults) return;
    if (!cards.length) {
      barResults.innerHTML = '<p class="blank-slate">No matches.</p>';
    } else {
      barResults.innerHTML = "<ul>" + cards.map(function (card) {
        const boardName = card.board && card.board.name ? card.board.name : "";
        return '<li><a class="search__result" href="' + escapeHtml(card.url) + '"><h3 class="search__title">#' + escapeHtml(card.number) + " " + escapeHtml(card.title || "Untitled") + "</h3><div class=\"search__excerpt\">" + escapeHtml((card.description || "").slice(0, 180)) + "</div><div class=\"overflow-ellipsis translucent\">" + escapeHtml(boardName) + "</div></a></li>";
      }).join("") + "</ul>";
    }
    if (barModal && !barModal.open) barModal.show();
  }

  if (barInput) {
    barInput.addEventListener("input", function () {
      const query = barInput.value.trim();
      const generation = ++searchGeneration;
      if (!query || !slug) {
        if (barModal && barModal.open) barModal.close();
        if (barResults) barResults.innerHTML = "";
        return;
      }
      window.setTimeout(function () {
        if (generation !== searchGeneration) return;
        fetch(slug + "/search?q=" + encodeURIComponent(query), {
          headers: { Accept: "application/json" },
          credentials: "same-origin",
        }).then(function (response) {
          return response.json();
        }).then(function (payload) {
          if (generation !== searchGeneration) return;
          renderSearch((payload && payload.cards) || []);
        });
      }, 180);
    });
  }

  const jumpFilter = document.querySelector("[data-jump-filter]");
  if (jumpFilter) {
    jumpFilter.addEventListener("input", function () {
      const query = jumpFilter.value.trim().toLowerCase();
      document.querySelectorAll("[data-jump-list] a").forEach(function (link) {
        link.hidden = !!query && !link.textContent.toLowerCase().includes(query);
      });
    });
  }

  const filterForm = document.querySelector(".board-filters");
  let filterGeneration = 0;
  function refreshBoard() {
    if (!filterForm) return;
    const generation = ++filterGeneration;
    const params = new URLSearchParams(new FormData(filterForm));
    fetch(filterForm.action + "?" + params.toString(), {
      headers: { "X-Fizzy-Fragment": "board", Accept: "text/html" },
      credentials: "same-origin",
    }).then(function (response) {
      return response.text();
    }).then(function (html) {
      if (generation !== filterGeneration) return;
      const stage = document.getElementById("board-stage");
      if (!stage) return;
      stage.innerHTML = html;
      if (boardRoot()) restoreColumns();
      else chooseFallback();
      paintBubbles(stage);
    });
  }
  if (filterForm) {
    filterForm.addEventListener("input", function (event) {
      if (event.target && event.target.name === "q") refreshBoard();
    });
    filterForm.addEventListener("change", function (event) {
      if (event.target && event.target.type === "checkbox") refreshBoard();
    });
  }

  function descriptionChanged(desc) {
    const plain = desc.innerText.replace(/\s+/g, " ").trim();
    const html = desc.innerHTML.trim();
    return plain !== (desc.dataset.originalPlain || "") || html !== (desc.dataset.originalHtml || "");
  }

  function rememberDescription(root) {
    (root || document).querySelectorAll(".card__description").forEach(function (desc) {
      desc.dataset.originalHtml = desc.innerHTML.trim();
      desc.dataset.originalPlain = desc.innerText.replace(/\s+/g, " ").trim();
    });
  }

  function saveCardFields(editForm) {
    const titleInput = editForm.querySelector("[name='card[title]']");
    const desc = editForm.querySelector(".card__description");
    const body = new FormData();
    body.append("csrf_token", csrf);
    body.append("_method", "put");
    let dirty = false;
    if (titleInput && titleInput.value !== titleInput.defaultValue) {
      body.append("card[title]", titleInput.value);
      dirty = true;
    }
    if (desc && descriptionChanged(desc)) {
      body.append("card[description]", desc.innerHTML);
      dirty = true;
    }
    if (!dirty) return Promise.resolve(true);
    return fetch(editForm.action, { method: "POST", body: body, credentials: "same-origin" }).then(function (response) {
      if (!response.ok) return false;
      if (titleInput) {
        titleInput.defaultValue = titleInput.value;
        document.title = (titleInput.value || "Card") + " · Fizzy";
      }
      if (desc) {
        desc.dataset.originalHtml = desc.innerHTML.trim();
        desc.dataset.originalPlain = desc.innerText.replace(/\s+/g, " ").trim();
      }
      return true;
    });
  }

  function applyCardSheet(payload) {
    const sheet = document.getElementById("card-sheet");
    if (!sheet || !payload || !payload.html) return;
    const scroll = window.scrollY;
    sheet.innerHTML = payload.html;
    rememberDescription(sheet);
    paintBubbles(sheet);
    if (payload.title) document.title = payload.title;
    const back = document.querySelector("[data-back]");
    if (back && payload.boardUrl) {
      back.setAttribute("href", payload.boardUrl);
      const label = back.querySelector("strong");
      const name = payload.boardName || "";
      if (label) label.textContent = name ? "Back to " + name : label.textContent;
      else if (name) back.textContent = name;
    }
    const tray = document.getElementById("pins-tray");
    if (tray && payload.pins) {
      tray.innerHTML = payload.pins.map(function (pin) {
        return '<div class="tray__item tray__item--pin"><a class="card" href="' + slug + "/cards/" + pin.number + '" style="--card-color: var(--color-card-2)"><div class="card__body"><h3 class="card__title">' + escapeHtml(pin.title) + "</h3></div></a></div>";
      }).join("");
    }
    if (payload.anchor) {
      const node = document.getElementById(String(payload.anchor).replace("#", ""));
      if (node) node.scrollIntoView({ block: "nearest" });
      return;
    }
    window.scrollTo(0, scroll);
  }

  function refreshBoardStage(html) {
    const stage = document.getElementById("board-stage");
    if (!stage) return;
    stage.innerHTML = html;
    if (boardRoot()) restoreColumns();
    else chooseFallback();
    paintBubbles(stage);
  }

  function postForm(form, submitter, headers) {
    const body = new FormData(form);
    if (submitter && submitter.name) {
      body.delete(submitter.name);
      body.set(submitter.name, submitter.value);
    }
    const action = (submitter && submitter.getAttribute("formaction")) || form.action;
    return fetch(action, { method: "POST", body: body, credentials: "same-origin", headers: headers || {} });
  }

  rememberDescription(document);

  document.addEventListener("change", function (event) {
    const box = event.target.closest && event.target.closest(".step .checkbox");
    if (!box || box.disabled || !box.form) return;
    if (box.form.requestSubmit) box.form.requestSubmit();
    else box.form.submit();
  });

  document.addEventListener("input", function (event) {
    const field = event.target.closest && event.target.closest("[data-popup-filter]");
    if (!field) return;
    const dialog = field.closest("dialog");
    if (!dialog) return;
    const query = field.value.trim().toLowerCase();
    dialog.querySelectorAll(".popup__item").forEach(function (item) {
      const text = (item.textContent || "").toLowerCase();
      item.hidden = !item.hasAttribute("data-popup-keep") && !!query && text.indexOf(query) === -1;
    });
  });

  document.addEventListener("focusout", function (event) {
    const form = event.target.closest && event.target.closest("form.card__edit");
    if (!form) return;
    if (event.target.matches("[name='card[title]'], .card__description")) saveCardFields(form);
  });

  document.addEventListener("submit", function (event) {
    const form = event.target;
    if (!form || form.classList.contains("danger") || form.hasAttribute("data-native-submit") || (form.getAttribute("method") || "").toLowerCase() === "dialog") return;
    const sheet = form.closest("#card-sheet");
    const adding = form.classList.contains("add-card");
    const columnForm = form.closest(".cards__menu, .cards__new, .cards__new-column");
    if (!sheet && !adding && !columnForm) return;
    event.preventDefault();
    event.stopPropagation();
    const submitter = event.submitter;
    if (adding) {
      postForm(form, submitter, { "X-Fizzy-Fragment": "card" }).then(function (response) {
        if (!response.ok) {
          window.alert("Could not add that card.");
          return null;
        }
        return response.json();
      }).then(function (payload) {
        if (!payload || !payload.html) return;
        const column = form.closest("section.cards");
        const list = column && column.querySelector(".cards__list");
        if (!list) return;
        const empty = list.querySelector(".empty");
        if (empty) empty.remove();
        const template = document.createElement("template");
        template.innerHTML = payload.html.trim();
        const card = template.content.querySelector("article.card");
        if (!card) return;
        list.prepend(card);
        recount(column);
        paintBubble(card.querySelector(".bubble"));
        selectCard(card);
        const input = form.querySelector("[name='card[title]']");
        if (input) {
          input.value = "";
          input.focus();
        }
      });
      return;
    }
    if (columnForm) {
      postForm(form, submitter, { "X-Fizzy-Fragment": "board", Accept: "text/html" }).then(function (response) {
        if (!response.ok) {
          window.alert("Could not update that column.");
          return;
        }
        return response.text().then(refreshBoardStage);
      });
      return;
    }
    const edit = sheet.querySelector("form.card__edit");
    const pending = edit && form !== edit && (
      (edit.querySelector("[name='card[title]']") && edit.querySelector("[name='card[title]']").value !== edit.querySelector("[name='card[title]']").defaultValue)
      || (edit.querySelector(".card__description") && descriptionChanged(edit.querySelector(".card__description")))
    );
    const send = function () {
      if (form.classList.contains("card__edit")) {
        const desc = form.querySelector(".card__description");
        const hidden = form.querySelector("[name='card[description]']");
        if (hidden && desc) {
          if (descriptionChanged(desc)) {
            hidden.disabled = false;
            hidden.value = desc.innerHTML;
          } else {
            hidden.disabled = true;
          }
        }
      }
      postForm(form, submitter, { "X-Fizzy-Fragment": "page" }).then(function (response) {
        if (!response.ok) {
          window.alert("Could not update that card.");
          return null;
        }
        return response.json();
      }).then(function (payload) {
        if (payload) applyCardSheet(payload);
      });
    };
    if (pending) {
      saveCardFields(edit).then(function (ok) {
        if (!ok) {
          window.alert("Could not save the card before that change.");
          return;
        }
        send();
      });
      return;
    }
    send();
  }, true);

  document.addEventListener("focusout", function (event) {
    const input = event.target.closest && event.target.closest(".step__content");
    if (!input || input.value === input.defaultValue || !input.dataset.url) return;
    const body = new FormData();
    body.append("csrf_token", csrf);
    body.append("_method", "put");
    body.append("step[content]", input.value);
    fetch(input.dataset.url, {
      method: "POST",
      body: body,
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    }).then(function (response) {
      if (response.ok) input.defaultValue = input.value;
    });
  });

  const KEYMAP = [
    ["h j k l", "Previous column, next card, previous card, next column. Arrows do the same."],
    ["gg", "First card in this column."],
    ["G", "Last card. 3G is the third card."],
    ["Enter", "Open the selected card."],
    ["f char", "Next card whose title starts with that letter, or contains it."],
    ["F char", "Same search, upward."],
    ["; ,", "Repeat the last f or F forward or backward."],
    ["dd", "Done. 3dd closes this card and the two below it."],
    ["dn", "Not now. Same count as dd."],
    [".", "Repeat the last dd or dn on the selected card."],
    ["o", "Add a card in Maybe."],
    ["i", "Edit the title. From a board, open the card first."],
    ["/", "Search."],
    ["n N", "Next or previous search hit."],
    ["Space Space", "Jump menu. Then 1 Home, 2 Assigned to me, 3 Added by me."],
    ["Space p", "Pins."],
    ["Space P", "Pin or unpin the selected card."],
    ["Space n", "Notifications."],
    ["Space f", "Filter."],
    ["Space m", "Assign to me."],
    ["Space g", "Toggle golden."],
    ["Space w", "Toggle watch."],
    ["Space t", "Tags on the open card."],
    ["Space a", "Assignees on the open card."],
    ["?", "This list."]
  ];

  let pending = null;
  let count = 0;
  let lastFind = null;
  let lastChange = null;

  function fillKeymap() {
    const host = document.querySelector("[data-keymap]");
    if (!host || host.dataset.filled) return;
    host.dataset.filled = "1";
    host.innerHTML = KEYMAP.map(function (row) {
      return '<p class="txt-small"><kbd>' + escapeHtml(row[0]) + "</kbd> " + escapeHtml(row[1]) + "</p>";
    }).join("");
  }

  function showKeymap() {
    fillKeymap();
    const dialog = dialogById("keymap");
    if (!dialog) return;
    if (dialog.open) {
      dialog.close();
      return;
    }
    document.querySelectorAll("dialog[open]").forEach(function (open) { open.close(); });
    dialog.showModal();
  }

  function takeCount() {
    const steps = count || 1;
    count = 0;
    return steps;
  }

  function dropCount() {
    count = 0;
  }

  function onCardPage() {
    return !!document.getElementById("card-sheet") && !columns().length;
  }

  function goBack() {
    const back = document.querySelector("[data-back]");
    if (back) back.click();
  }

  function cardTitle(card) {
    const node = card.querySelector(".card__title");
    return (node ? node.textContent : "").trim().toLowerCase();
  }

  function findCard(char, direction) {
    const cards = listedCards();
    if (!cards.length || !char) return;
    const needle = String(char).toLowerCase();
    const current = selectedCard();
    let start = cards.indexOf(current);
    if (start < 0) start = direction > 0 ? -1 : cards.length;
    const step = direction > 0 ? 1 : -1;
    function scan(test) {
      for (let index = start + step; index >= 0 && index < cards.length; index += step) {
        if (test(cardTitle(cards[index]))) {
          selectCard(cards[index]);
          return true;
        }
      }
      return false;
    }
    scan(function (title) { return title.charAt(0) === needle; })
      || scan(function (title) { return title.indexOf(needle) !== -1; });
  }

  function goEnds(which) {
    const cards = listedCards();
    if (!cards.length) return;
    if (which === "first") {
      selectCard(cards[0]);
      return;
    }
    if (count) {
      const index = Math.min(cards.length, count) - 1;
      dropCount();
      selectCard(cards[Math.max(0, index)]);
      return;
    }
    selectCard(cards[cards.length - 1]);
  }

  function runLineAction(kind, times) {
    lastChange = kind;
    if (onCardPage()) {
      clickHotkey(kind === "done" ? "done" : "postpone");
      return;
    }
    const cards = listedCards();
    const current = selectedCard();
    const index = cards.indexOf(current);
    if (index < 0) return;
    const take = Math.max(1, times || 1);
    const slice = cards.slice(index, index + take);
    const successor = cards[index + take] || cards[index - 1] || null;
    const jobs = [];
    slice.forEach(function (card) {
      const url = kind === "done" ? card.dataset.closureUrl : card.dataset.notNowUrl;
      if (url) jobs.push(url);
    });
    if (!jobs.length) return;
    holdSelection = true;
    let chain = Promise.resolve();
    jobs.forEach(function (url) {
      chain = chain.then(function () { return post(url); });
    });
    chain.then(function () {
      holdSelection = false;
      const column = successor && successor.closest("section.cards");
      if (successor && successor.isConnected && (!column || !column.classList.contains("is-collapsed"))) selectCard(successor);
      else chooseFallback();
    }, function () {
      holdSelection = false;
      chooseFallback();
    });
  }

  function toggleFlag(hotkey, urlKey, flag) {
    if (document.getElementById("card-sheet") && clickHotkey(hotkey)) return;
    const card = selectedCard();
    if (!card) return;
    const url = card.dataset[urlKey];
    if (!url) return;
    post(url, card.hasAttribute("data-" + flag) ? { _method: "delete" } : null);
  }

  function assignMe() {
    if (document.getElementById("card-sheet") && clickHotkey("me")) return;
    const card = selectedCard();
    if (card && card.dataset.assignUrl) post(card.dataset.assignUrl);
  }

  function openField(name) {
    const field = document.querySelector('[data-hotkey-target="' + name + '"]');
    if (!field) return;
    const dialog = field.closest("dialog");
    if (dialog && !dialog.open) dialog.show();
    field.focus();
  }

  function openJump() {
    toggleDialog("jump", true);
    const jump = dialogById("jump");
    if (jump && jump.open && jumpFilter) jumpFilter.focus();
  }

  function openComposer() {
    const composer = document.querySelector(".cards--maybe [data-add-card]");
    if (composer && composer.requestSubmit) composer.requestSubmit();
  }

  function editTitle() {
    if (document.getElementById("card-sheet")) {
      const edit = document.querySelector("[data-hotkey-target='edit']");
      if (edit && !edit.closest("[hidden]")) {
        edit.focus();
        if (edit.select) edit.select();
        return;
      }
      setCardEditing(true);
      return;
    }
    const card = selectedCard();
    const link = card && card.querySelector(".card__link");
    if (link) window.location.href = link.href.split("#")[0] + "#edit";
  }

  function showSearchHit(direction) {
    if (!lastSearchCards || !lastSearchCards.length || !barResults) return;
    if (!barResults.querySelector(".search__result")) {
      if (barField && barField.hidden) openSearch();
      renderSearch(lastSearchCards);
    } else if (barModal && !barModal.open) barModal.show();
    moveLinks(barResults, direction);
  }

  function spaceCommand(key) {
    if (key === " ") openJump();
    else if (key === "p") toggleDialog("pins-tray", false);
    else if (key === "P") toggleFlag("pin", "pinUrl", "pinned");
    else if (key === "n") toggleDialog("notes-tray", false);
    else if (key === "f") openField("filter");
    else if (key === "m") assignMe();
    else if (key === "g") toggleFlag("gold", "goldUrl", "gold");
    else if (key === "w") toggleFlag("watch", "watchUrl", "watching");
    else if (key === "t") openField("tag");
    else if (key === "a") openField("assign");
  }

  function handlePending(event) {
    const key = event.key;
    const kind = pending;
    pending = null;
    event.preventDefault();
    if (key === "Escape") {
      dropCount();
      return;
    }
    if (kind === "d") {
      if (key === "d") runLineAction("done", takeCount());
      else if (key === "n") runLineAction("notnow", takeCount());
      else dropCount();
      return;
    }
    if (kind === "g") {
      dropCount();
      if (key === "g") goEnds("first");
      return;
    }
    if (kind === "f" || kind === "F") {
      dropCount();
      if (key.length === 1 && key !== " ") {
        const direction = kind === "F" ? -1 : 1;
        lastFind = { char: key, direction: direction };
        findCard(key, direction);
      }
      return;
    }
    if (kind === "space") {
      dropCount();
      spaceCommand(key);
    }
  }

  function moveMotion(key, steps) {
    if (key === "j" || key === "ArrowDown") {
      if (!onCardPage()) moveCard(steps);
      return;
    }
    if (key === "k" || key === "ArrowUp") {
      if (!onCardPage()) moveCard(-steps);
      return;
    }
    if (key === "h" || key === "ArrowLeft") {
      if (columns().length) moveColumn(-steps);
      else if (steps === 1) goBack();
      return;
    }
    if (key === "l" || key === "ArrowRight") {
      if (columns().length) moveColumn(steps);
    }
  }

  document.addEventListener("keydown", function (event) {
    const key = event.key;
    const meta = event.metaKey || event.ctrlKey;
    const plain = !meta && !event.altKey && !event.shiftKey;
    const jump = dialogById("jump");

    if (event.target.matches && event.target.matches("[name='card[title]']") && key === "Enter" && plain) {
      event.preventDefault();
      event.target.blur();
      return;
    }

    if (key === "Escape") {
      if (pending || count) {
        pending = null;
        count = 0;
        event.preventDefault();
        return;
      }
      const open = document.querySelector("dialog[open]");
      if (open) {
        open.close();
        event.preventDefault();
        return;
      }
      const reactionForm = event.target.closest && event.target.closest("[data-reaction-form]");
      if (reactionForm && !reactionForm.hidden) {
        closeReactionForm(reactionForm);
        event.preventDefault();
        return;
      }
      const editor = document.querySelector("[data-card-editor]");
      if (editor && !editor.hidden && document.querySelector("[data-card-display]")) {
        setCardEditing(false);
        event.preventDefault();
        return;
      }
      if (barField && !barField.hidden) {
        closeSearch();
        event.preventDefault();
        return;
      }
      if (!typing(event)) goBack();
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

    if (pending) {
      if (typing(event) || event.repeat) {
        if (!event.repeat) {
          pending = null;
          count = 0;
        } else event.preventDefault();
        if (event.repeat) return;
      } else {
        handlePending(event);
        return;
      }
    }

    if (barField && !barField.hidden && (event.target === barInput || (event.target.closest && event.target.closest(".bar__results")))) {
      if (!meta && !event.altKey && (key === "ArrowDown" || key === "ArrowUp") && barResults) {
        event.preventDefault();
        moveLinks(barResults, key === "ArrowDown" ? 1 : -1);
        return;
      }
      if (key === "Enter") {
        const chosen = barResults && barResults.querySelector(".search__result[aria-selected='true']");
        if (chosen) {
          event.preventDefault();
          window.location.href = chosen.href;
          return;
        }
      }
    }

    if (jump && jump.open && plain && (key === "1" || key === "2" || key === "3")) {
      if (!(jumpFilter && event.target === jumpFilter && jumpFilter.value)) {
        const link = document.querySelector('a[data-menu-key="' + key + '"]');
        if (link) {
          event.preventDefault();
          link.click();
          return;
        }
      }
    }

    const openDialog = document.querySelector("dialog[open]");
    if (openDialog && !typing(event) && !meta && !event.altKey) {
      if ((key === "n" || key === "N") && openDialog === barModal) {
        event.preventDefault();
        showSearchHit(key === "N" ? -1 : 1);
        return;
      }
      if (key === "j" || key === "ArrowDown") {
        event.preventDefault();
        moveLinks(openDialog, 1);
        return;
      }
      if (key === "k" || key === "ArrowUp") {
        event.preventDefault();
        moveLinks(openDialog, -1);
        return;
      }
      if (key === "Enter") {
        const chosen = openDialog.querySelector("[aria-selected='true']");
        if (chosen) {
          event.preventDefault();
          chosen.click();
        }
        return;
      }
      return;
    }

    if (typing(event)) return;

    if (!meta && !event.altKey && key.length === 1 && key >= "0" && key <= "9" && !(key === "0" && !count)) {
      count = Math.min(999, count * 10 + Number(key));
      event.preventDefault();
      return;
    }

    if (plain && (key === "j" || key === "k" || key === "h" || key === "l" || key === "ArrowLeft" || key === "ArrowRight" || key === "ArrowUp" || key === "ArrowDown")) {
      event.preventDefault();
      moveMotion(key, takeCount());
      return;
    }
    if (!meta && !event.altKey && key === "G") {
      event.preventDefault();
      goEnds("last");
      return;
    }
    if (plain && key === "g") {
      if (event.repeat) return;
      event.preventDefault();
      pending = "g";
      return;
    }
    if (plain && key === "d") {
      if (event.repeat) return;
      event.preventDefault();
      pending = "d";
      return;
    }
    if (!meta && !event.altKey && key === "f" && !event.shiftKey) {
      if (event.repeat) return;
      event.preventDefault();
      pending = "f";
      return;
    }
    if (!meta && !event.altKey && key === "F") {
      if (event.repeat) return;
      event.preventDefault();
      pending = "F";
      return;
    }
    if (plain && key === ";") {
      event.preventDefault();
      dropCount();
      if (lastFind) findCard(lastFind.char, lastFind.direction);
      return;
    }
    if (plain && key === ",") {
      event.preventDefault();
      dropCount();
      if (lastFind) findCard(lastFind.char, -lastFind.direction);
      return;
    }
    if (plain && key === ".") {
      event.preventDefault();
      dropCount();
      if (lastChange) runLineAction(lastChange, 1);
      return;
    }
    if (plain && key === "o") {
      event.preventDefault();
      dropCount();
      openComposer();
      return;
    }
    if (plain && key === "i") {
      event.preventDefault();
      dropCount();
      editTitle();
      return;
    }
    if (plain && key === "/") {
      event.preventDefault();
      dropCount();
      openSearch();
      return;
    }
    if (!meta && !event.altKey && (key === "n" || key === "N") && lastSearchCards) {
      event.preventDefault();
      dropCount();
      showSearchHit(key === "N" ? -1 : 1);
      return;
    }
    if (!meta && !event.altKey && key === "?") {
      event.preventDefault();
      dropCount();
      showKeymap();
      return;
    }
    if (!meta && !event.altKey && key === " ") {
      if (event.repeat) return;
      event.preventDefault();
      pending = "space";
    }
  });

  document.querySelectorAll("form.danger").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      const label = (form.querySelector("button") || {}).textContent || "this";
      if (!window.confirm("Continue and " + label.trim().toLowerCase() + "?")) event.preventDefault();
    });
  });

  if (window.location.hash === "#edit") setCardEditing(true);

  document.documentElement.dataset.fizzyReady = "1";
})();
