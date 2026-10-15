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
    const root = boardRoot();
    if (!root) return;
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
    if (!cards.length) {
      moveGrid(direction);
      return;
    }
    const current = selectedCard();
    let index = cards.indexOf(current);
    if (index < 0) index = direction > 0 ? -1 : cards.length;
    const next = cards[index + direction];
    if (next) selectCard(next);
  }

  function moveGrid(direction) {
    const grid = document.querySelector(".cards-grid, .card-grid");
    if (!grid) return;
    const cards = Array.from(grid.querySelectorAll("article.card"));
    if (!cards.length) return;
    const current = selectedCard();
    let index = cards.indexOf(current);
    if (index < 0) index = direction > 0 ? -1 : cards.length;
    const next = cards[index + direction];
    if (next) selectCard(next);
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
    const target = document.getElementById("lane-" + payload.lane) || document.getElementById("column-" + payload.lane);
    const list = target && target.querySelector(".cards__list");
    if (list && !list.contains(fresh)) {
      if (fresh.classList.contains("golden-effect")) list.prepend(fresh);
      else list.appendChild(fresh);
    }
    recount(sourceColumn);
    recount(target);
    paintBubble(fresh.querySelector(".bubble"));
    if (payload.stay) {
      selectCard(fresh);
      return;
    }
    const home = neighbor && neighbor.closest("section.cards");
    if (neighbor && neighbor.isConnected && home && visibleCards(home).indexOf(neighbor) >= 0) selectCard(neighbor);
    else if (neighbor && neighbor.isConnected && neighbor.closest(".cards-grid, .card-grid")) selectCard(neighbor);
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
    if (boardRoot() || document.querySelector(".cards-grid")) headers["X-Fizzy-Fragment"] = "card";
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

  if (boardRoot()) {
    restoreColumns();
    desktopQuery.addEventListener("change", restoreColumns);
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
    const menuButton = event.target.closest(".cards__menu > button, .cards__new-toggle");
    if (menuButton) {
      const dialog = menuButton.parentElement.querySelector("dialog");
      if (dialog) {
        event.preventDefault();
        if (dialog.open) dialog.close();
        else dialog.show();
        const input = dialog.querySelector("input[name='column[name]']");
        if (input) input.focus();
      }
      return;
    }
    const expander = event.target.closest(".cards__expander");
    if (expander) {
      const column = expander.closest("section.cards");
      if (!column || (column.id === "lane-maybe" && isDesktop())) return;
      if (column.classList.contains("is-expanded") && column.id !== "lane-maybe") collapseSide(column);
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
  function renderSearch(cards) {
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
      back.textContent = payload.boardName || back.textContent;
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

  document.addEventListener("focusout", function (event) {
    const form = event.target.closest && event.target.closest("form.card__edit");
    if (!form) return;
    if (event.target.matches("[name='card[title]'], .card__description")) saveCardFields(form);
  });

  document.addEventListener("submit", function (event) {
    const form = event.target;
    if (!form || form.classList.contains("danger") || (form.getAttribute("method") || "").toLowerCase() === "dialog") return;
    const sheet = form.closest("#card-sheet");
    const adding = form.classList.contains("add-card");
    const columnForm = form.closest(".cards__menu, .cards__new");
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
      const open = document.querySelector("dialog[open]");
      if (open) {
        open.close();
        event.preventDefault();
        return;
      }
      if (barField && !barField.hidden) {
        closeSearch();
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

    if (barField && !barField.hidden && (event.target === barInput || (event.target.closest && event.target.closest(".bar__results")))) {
      if (plain && (key === "ArrowDown" || key === "ArrowUp") && barResults) {
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

    const openDialog = document.querySelector("dialog[open]");
    if (openDialog && plain && (key === "ArrowDown" || key === "ArrowUp" || key === "Enter")) {
      if (key === "Enter") {
        const chosen = openDialog.querySelector("[aria-selected='true']");
        if (chosen) {
          event.preventDefault();
          chosen.click();
        }
        return;
      }
      event.preventDefault();
      moveLinks(openDialog, key === "ArrowDown" ? 1 : -1);
      return;
    }

    if (typing(event)) return;
    const trayKey = plain && (key === "p" || key === "P" || key === "n" || key === "N" || key === "k" || key === "K");
    if (document.querySelector("dialog[open]") && !trayKey) return;

    if (plain && (key === "k" || key === "K")) {
      if (!barInput) return;
      event.preventDefault();
      openSearch();
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
    if (plain && (key === "c" || key === "C")) {
      const composer = document.querySelector(".cards--maybe [data-add-card]");
      if (composer) {
        event.preventDefault();
        composer.requestSubmit();
      }
      return;
    }
    if (plain && (key === "ArrowLeft" || key === "ArrowRight" || key === "ArrowUp" || key === "ArrowDown")) {
      if (columns().length) {
        event.preventDefault();
        if (key === "ArrowRight") moveColumn(1);
        else if (key === "ArrowLeft") moveColumn(-1);
        else if (key === "ArrowDown") moveCard(1);
        else moveCard(-1);
        return;
      }
      if (document.querySelector(".cards-grid, .card-grid") && (key === "ArrowDown" || key === "ArrowUp")) {
        event.preventDefault();
        moveGrid(key === "ArrowDown" ? 1 : -1);
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
    if (plain && key === "Enter" && (boardRoot() || document.querySelector(".cards-grid, .card-grid"))) {
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
      const card = (boardRoot() || document.querySelector(".cards-grid")) ? selectedCard() : null;
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

  document.documentElement.dataset.fizzyReady = "1";
})();
