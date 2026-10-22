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

  let boardNode = null;
  let boardFresh = false;
  let gridNode = null;
  let gridFresh = false;
  let columnList = null;
  let columnRoot = null;
  let listGeneration = 0;
  const cardCache = new WeakMap();
  const watchedLists = new WeakSet();
  const watchedFilters = new WeakSet();
  const parked = new WeakMap();
  let geomStamp = 0;
  const geomCache = new WeakMap();
  let interactionStamp = 0;

  document.addEventListener("keydown", function () {
    interactionStamp += 1;
  }, true);
  document.addEventListener("pointerdown", function () {
    interactionStamp += 1;
  }, { capture: true, passive: true });
  document.addEventListener("scroll", function () {
    bumpGeom();
  }, { capture: true, passive: true });
  document.addEventListener("touchmove", function () {
    bumpGeom();
  }, { capture: true, passive: true });

  function bumpGeom() {
    geomStamp += 1;
  }

  function boxOf(node) {
    const hit = geomCache.get(node);
    if (hit && hit.stamp === geomStamp) return hit.box;
    const box = node.getBoundingClientRect();
    geomCache.set(node, { stamp: geomStamp, box: box });
    return box;
  }

  function invalidateLists() {
    listGeneration += 1;
    boardFresh = false;
    gridFresh = false;
    columnList = null;
    columnRoot = null;
    bumpGeom();
  }

  function boardRoot() {
    if (boardFresh && boardNode && boardNode.isConnected) return boardNode;
    if (boardFresh && !boardNode) return null;
    boardNode = document.querySelector(".card-columns");
    boardFresh = true;
    return boardNode;
  }

  function columns() {
    const root = boardRoot();
    if (!root) return [];
    if (columnList && columnRoot === root) return columnList;
    const nodes = root.querySelectorAll("section.cards");
    columnList = [];
    for (let index = 0; index < nodes.length; index += 1) columnList.push(nodes[index]);
    columnRoot = root;
    return columnList;
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

  function collectCards(root) {
    if (!root) return [];
    const section = root.tagName === "SECTION";
    if (section) {
      const hit = cardCache.get(root);
      if (hit && hit.generation === listGeneration) return hit.cards;
    }
    const list = root.classList.contains("cards__list") || root.classList.contains("card-grid")
      ? root
      : root.querySelector(".cards__list, .card-grid");
    if (!list) return [];
    const cards = [];
    const nodes = list.children;
    for (let index = 0; index < nodes.length; index += 1) {
      if (nodes[index].tagName === "ARTICLE") cards.push(nodes[index]);
    }
    if (section) cardCache.set(root, { generation: listGeneration, cards: cards });
    return cards;
  }

  function visibleCards(column) {
    if (!column || column.classList.contains("is-collapsed")) return [];
    return collectCards(column);
  }

  let cardIndexMemory = 0;
  let selectedNode = null;
  let selectedColumn = null;
  let selectionEpoch = 0;
  let revealFrame = 0;
  let revealTarget = null;

  function cancelReveal() {
    if (!revealFrame) return;
    cancelAnimationFrame(revealFrame);
    revealFrame = 0;
    revealTarget = null;
  }

  function inside(box, frame) {
    return box.top >= frame.top - 1 && box.bottom <= frame.bottom + 1 && box.left >= frame.left - 1 && box.right <= frame.right + 1;
  }

  function cardInView(card) {
    const box = boxOf(card);
    if (box.width === 0 || box.height === 0) return false;
    const list = card.closest(".cards__list, .card-grid");
    if (list && !inside(box, boxOf(list))) return false;
    const band = card.closest(".card-columns");
    if (band && !inside(box, boxOf(band))) return false;
    return box.top >= 0 && box.left >= 0 && box.bottom <= window.innerHeight && box.right <= window.innerWidth;
  }

  function revealCard(card) {
    if (!card || !card.isConnected) return;
    const active = document.activeElement;
    const field = active && active.closest && active.closest("input, textarea, select, [contenteditable]");
    if (!field && active !== card) card.focus({ preventScroll: true });
    bumpGeom();
    if (!cardInView(card)) card.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  function scheduleReveal(card) {
    revealTarget = card;
    if (revealFrame) return;
    revealFrame = requestAnimationFrame(function () {
      revealFrame = 0;
      const target = revealTarget;
      revealTarget = null;
      revealCard(target);
    });
  }

  function selectCard(card, index, coarse) {
    selectionEpoch += 1;
    if (selectedNode && selectedNode !== card) {
      if (selectedNode.isConnected) selectedNode.removeAttribute("aria-selected");
      else {
        const stale = document.querySelector('article.card[aria-selected="true"]');
        if (stale && stale !== card) stale.removeAttribute("aria-selected");
      }
    }
    if (!card) {
      selectedNode = null;
      cancelReveal();
      return;
    }
    const column = card.closest("section.cards");
    if (typeof index === "number" && index >= 0) cardIndexMemory = index;
    else if (column) {
      const siblings = collectCards(column);
      for (let cursor = 0; cursor < siblings.length; cursor += 1) {
        if (siblings[cursor] === card) {
          cardIndexMemory = cursor;
          break;
        }
      }
    }
    // The card outline is drawn only inside a column that is itself selected.
    if (selectedColumn && selectedColumn !== column) {
      if (selectedColumn.isConnected) selectedColumn.removeAttribute("aria-selected");
      else {
        document.querySelectorAll("section.cards[aria-selected='true']").forEach(function (item) {
          if (item !== column) item.removeAttribute("aria-selected");
        });
      }
    }
    if (column) {
      column.setAttribute("aria-selected", "true");
      selectedColumn = column;
    }
    card.setAttribute("aria-selected", "true");
    selectedNode = card;
    const link = card.querySelector(".card__link");
    if (link) schedulePrefetch(link.getAttribute("href"));
    if (coarse) scheduleReveal(card);
    else {
      cancelReveal();
      revealCard(card);
    }
  }

  function selectFirstMaybe() {
    const cards = visibleCards(document.getElementById("maybe"));
    if (cards.length) selectCard(cards[0]);
  }

  function selectedCard() {
    if (!selectedNode || !selectedNode.isConnected) {
      selectedNode = document.querySelector('article.card[aria-selected="true"]');
    }
    if (!selectedNode) return null;
    const column = selectedNode.closest("section.cards");
    if (column && column.classList.contains("is-collapsed")) return null;
    return selectedNode;
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
    if (boardRoot()) {
      gridNode = null;
      gridFresh = true;
      return null;
    }
    if (gridFresh && gridNode && gridNode.isConnected) return gridNode;
    if (gridFresh && !gridNode) return null;
    gridNode = document.querySelector(".cards-grid, .card-grid, .cards--grid");
    gridFresh = true;
    return gridNode;
  }

  function listedCards() {
    if (boardRoot()) return visibleCards(activeColumn());
    return collectCards(gridElement());
  }

  function moveColumn(direction, coarse) {
    const list = columns();
    if (!list.length) return false;
    const sign = direction < 0 ? -1 : 1;
    const steps = Math.max(1, Math.abs(direction));
    const current = activeColumn() || list[0];
    const from = visibleCards(current);
    const selected = selectedCard();
    const found = from.indexOf(selected);
    if (found >= 0) cardIndexMemory = found;
    const cardIndex = cardIndexMemory;
    const index = Math.max(0, list.indexOf(current));
    const destIndex = Math.max(0, Math.min(list.length - 1, index + sign * steps));
    if (destIndex === index) return false;
    const dest = list[destIndex];
    if (dest.classList.contains("is-collapsed")) showColumn(dest, { select: false });
    const cards = visibleCards(dest);
    if (cards.length) selectCard(cards[Math.min(cardIndex, cards.length - 1)], Math.min(cardIndex, cards.length - 1), coarse);
    else {
      selectCard(null);
      dest.focus();
    }
    return true;
  }

  function moveCard(direction, coarse) {
    const cards = listedCards();
    if (!cards.length) return false;
    const sign = direction < 0 ? -1 : 1;
    const steps = Math.max(1, Math.abs(direction));
    const current = selectedCard();
    let index = current && cards[cardIndexMemory] === current ? cardIndexMemory : cards.indexOf(current);
    if (index < 0) index = sign > 0 ? -1 : cards.length;
    const dest = Math.max(0, Math.min(cards.length - 1, index + sign * steps));
    if (cards[dest] === current) return false;
    selectCard(cards[dest], dest, coarse);
    return true;
  }

  function moveGrid(direction) {
    return moveCard(direction);
  }

  function recount(column) {
    if (!column) return;
    const count = collectCards(column).length;
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
  let holdDepth = 0;
  const moveEpoch = new Map();

  function pushHold() {
    holdDepth += 1;
    holdSelection = true;
  }

  function popHold() {
    holdDepth = Math.max(0, holdDepth - 1);
    holdSelection = holdDepth > 0;
  }

  function beginMove(number) {
    const key = String(number);
    const epoch = (moveEpoch.get(key) || 0) + 1;
    moveEpoch.set(key, epoch);
    return epoch;
  }

  function moveIsCurrent(number, epoch) {
    return moveEpoch.get(String(number)) === epoch;
  }

  function parkNeighbor(card) {
    if (parked.has(card)) return;
    const next = card.nextElementSibling;
    if (next && next.tagName === "ARTICLE") {
      parked.set(card, next);
      return;
    }
    const prev = card.previousElementSibling;
    if (prev && prev.tagName === "ARTICLE") {
      parked.set(card, prev);
      return;
    }
    parked.set(card, null);
  }

  function boardUrl() {
    const back = document.querySelector("[data-back]");
    if (back && back.getAttribute("href")) return back.getAttribute("href");
    const root = boardRoot();
    if (root && root.dataset.board) return slug + "/boards/" + root.dataset.board;
    return null;
  }

  function relocateCard(card, column) {
    const list = column && column.querySelector(".cards__list");
    if (!card || !list || list.contains(card)) return null;
    parkNeighbor(card);
    const parent = card.parentNode;
    const next = card.nextSibling;
    const source = card.closest("section.cards");
    const home = boardUrl();
    invalidateLists();
    if (card.classList.contains("golden-effect")) list.prepend(card);
    else list.appendChild(card);
    recount(source);
    recount(column);
    return {
      boardUrl: home,
      undo: function () {
        parked.delete(card);
        if (!card.isConnected || !parent || !parent.isConnected) return;
        invalidateLists();
        if (next && next.parentNode === parent) parent.insertBefore(card, next);
        else parent.appendChild(card);
        recount(source);
        recount(column);
      },
    };
  }

  function detachCard(card) {
    if (!card || !card.parentNode) return null;
    parkNeighbor(card);
    const parent = card.parentNode;
    const next = card.nextSibling;
    const source = card.closest("section.cards");
    const home = boardUrl();
    invalidateLists();
    card.remove();
    recount(source);
    return {
      boardUrl: home,
      undo: function () {
        parked.delete(card);
        if (card.isConnected || !parent || !parent.isConnected) return;
        invalidateLists();
        if (next && next.parentNode === parent) parent.insertBefore(card, next);
        else parent.appendChild(card);
        recount(source);
      },
    };
  }

  function laneColumn(lane) {
    if (!lane) return null;
    return document.getElementById("column-" + lane)
      || document.getElementById("lane-" + lane)
      || document.querySelector('section.cards[data-lane="' + lane + '"]');
  }

  function columnMoveFields(column, number) {
    if (!column || !number || !slug) return null;
    let url = slug + "/cards/" + number + "/triage";
    const fields = {};
    if (column.dataset.columnId) fields.column_id = column.dataset.columnId;
    else if (column.dataset.lane === "maybe") fields._method = "delete";
    else if (column.dataset.lane === "not_now") url = slug + "/cards/" + number + "/not_now";
    else if (column.dataset.lane === "closed") url = slug + "/cards/" + number + "/closure";
    else return null;
    return { url: url, fields: fields };
  }

  function placeCard(payload) {
    invalidateLists();
    const template = document.createElement("template");
    template.innerHTML = (payload.html || "").trim();
    const fresh = template.content.querySelector("article.card");
    if (!fresh) return;
    const current = document.querySelector('article.card[data-number="' + payload.number + '"]');
    const sourceColumn = current && current.closest("section.cards");
    let neighbor = null;
    if (current && parked.has(current)) {
      neighbor = parked.get(current);
      parked.delete(current);
    } else if (current) {
      neighbor = current.nextElementSibling && current.nextElementSibling.matches("article.card")
        ? current.nextElementSibling
        : current.previousElementSibling;
      if (neighbor && !neighbor.matches("article.card")) neighbor = null;
    }
    if (current) current.replaceWith(fresh);
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

  function post(url, fields, move) {
    const body = new FormData();
    body.append("csrf_token", csrf);
    if (fields) {
      Object.keys(fields).forEach(function (key) {
        body.append(key, fields[key]);
      });
    }
    const headers = {};
    if (boardRoot() || gridElement()) headers["X-Fizzy-Fragment"] = "card";
    return fetch(url, { method: "POST", body: body, credentials: "same-origin", headers: headers }).then(function (response) {
      if (!response.ok) {
        window.alert("Could not update that card.");
        return null;
      }
      const type = response.headers.get("content-type") || "";
      if (type.indexOf("application/json") >= 0) {
        return response.json().then(function (payload) {
          const current = !move || moveIsCurrent(move.number, move.epoch);
          if (current && payload && payload.html) placeCard(payload);
          if (current && payload) noteMutation((payload && payload.number) || (move && move.number));
          return payload;
        });
      }
      window.location.reload();
      return null;
    });
  }

  let navToken = 0;
  let composeAfterBoard = false;
  let skipNextCapture = false;

  function surfaceUrl(url) {
    let parsed;
    try { parsed = new URL(url, window.location.href); }
    catch (error) { return false; }
    if (parsed.origin !== window.location.origin || !slug) return false;
    let path = parsed.pathname;
    if (path.length > 1 && path.charAt(path.length - 1) === "/") path = path.slice(0, -1);
    if (path.indexOf("/public/") !== -1) return false;
    const cards = slug + "/cards/";
    const boards = slug + "/boards/";
    if (path.indexOf(cards) === 0) return /^\d+$/.test(path.slice(cards.length));
    if (path.indexOf(boards) === 0) {
      const rest = path.slice(boards.length);
      return !!rest && rest.indexOf("/") === -1 && rest !== "new";
    }
    return false;
  }

  function pathOf(url) {
    const parsed = new URL(url, window.location.href);
    let path = parsed.pathname;
    if (path.length > 1 && path.charAt(path.length - 1) === "/") path = path.slice(0, -1);
    return path;
  }

  function rememberBoardCard() {
    if (!history.state || !history.state.fizzy || !boardRoot()) return;
    const card = selectedCard();
    const number = card && card.dataset.number ? Number(card.dataset.number) : null;
    if (history.state.card === number) return;
    history.replaceState(Object.assign({}, history.state, { card: number }), "", window.location.href);
  }

  function bootSurface(selectNumber, hash) {
    const compose = composeAfterBoard;
    composeAfterBoard = false;
    watchCardLists(document.getElementById("board-stage"));
    watchCardLists(document.getElementById("cards_container"));
    bindSurfaceFilters();
    const back = document.querySelector("[data-back]");
    if (back) schedulePrefetch(back.getAttribute("href"));
    const root = document.getElementById("main");
    paintBubbles(root);
    rememberDescription(root);
    if (boardRoot()) {
      restoreColumns();
      if (selectNumber) {
        const card = document.querySelector('article.card[data-number="' + selectNumber + '"]');
        if (card) {
          const column = card.closest("section.cards");
          if (column && column.classList.contains("is-collapsed")) showColumn(column, { select: false });
          selectCard(card);
        }
      }
      if (compose) openComposer();
      return;
    }
    if (hash === "#edit") {
      setCardEditing(true);
      return;
    }
    const editor = document.querySelector("[data-card-editor]");
    if (editor && !editor.hidden) {
      setCardEditing(true);
      return;
    }
    chooseFallback();
  }

  const surfaceCache = new Map();
  const SURFACE_LIMIT = 8;
  const inflightHtml = new Map();
  const SLOT_SELECTORS = [".header__actions--start", ".header__title", ".header__actions--end"];
  let currentKey = "";
  let boardPreview = false;
  let prefetchTimer = 0;
  let prefetchHref = "";

  function cacheKey(url) {
    const parsed = new URL(url, window.location.href);
    let path = parsed.pathname;
    if (path.length > 1 && path.charAt(path.length - 1) === "/") path = path.slice(0, -1);
    return path + parsed.search;
  }

  function rememberSnap(key, snap) {
    if (!key || !snap) return;
    surfaceCache.delete(key);
    surfaceCache.set(key, snap);
    while (surfaceCache.size > SURFACE_LIMIT) {
      const oldest = surfaceCache.keys().next().value;
      surfaceCache.delete(oldest);
    }
  }

  function takeSnapshot() {
    const main = document.getElementById("main");
    if (!main) return null;
    const header = document.getElementById("header");
    const slots = {};
    for (let index = 0; index < SLOT_SELECTORS.length; index += 1) {
      const selector = SLOT_SELECTORS[index];
      const node = document.querySelector(selector);
      slots[selector] = node ? node.innerHTML : "";
    }
    return {
      main: main.cloneNode(true),
      title: document.title,
      bodyClass: document.body.className,
      headerClass: header ? header.className : "",
      slots: slots,
      flash: null,
      slug: document.body.dataset.slug || "",
      dirty: false,
      live: true,
    };
  }

  function snapshotFromHtml(html) {
    const doc = new DOMParser().parseFromString(html, "text/html");
    const nextMain = doc.getElementById("main");
    if (!nextMain || !doc.body || doc.body.dataset.slug !== slug) return null;
    const slots = {};
    for (let index = 0; index < SLOT_SELECTORS.length; index += 1) {
      const selector = SLOT_SELECTORS[index];
      const src = doc.querySelector(selector);
      slots[selector] = src ? src.innerHTML : "";
    }
    const nextHeader = doc.getElementById("header");
    const nextFlash = doc.querySelector("#global-container > .flash");
    return {
      main: document.importNode(nextMain, true),
      title: doc.title,
      bodyClass: doc.body.className,
      headerClass: nextHeader ? nextHeader.className : "",
      slots: slots,
      flash: nextFlash ? document.importNode(nextFlash, true) : null,
      slug: doc.body.dataset.slug,
      dirty: false,
      live: false,
    };
  }

  function captureSurface() {
    if (skipNextCapture) {
      skipNextCapture = false;
      return;
    }
    if (boardPreview) return;
    if (!currentKey || !surfaceUrl(window.location.href)) return;
    const snap = takeSnapshot();
    if (!snap) return;
    rememberSnap(currentKey, snap);
  }

  function markDirtyUrl(url) {
    if (!url || !surfaceUrl(url)) return;
    const key = cacheKey(url);
    const hit = surfaceCache.get(key);
    if (hit) hit.dirty = true;
  }

  function noteMutation(number) {
    if (number) markDirtyUrl(slug + "/cards/" + number);
    const home = boardUrl();
    if (home) markDirtyUrl(home);
    if (boardPreview) {
      const hit = currentKey && surfaceCache.get(currentKey);
      if (hit) hit.dirty = true;
      return;
    }
    captureSurface();
  }

  function fetchHtml(url, options) {
    options = options || {};
    const key = cacheKey(url);
    if (!options.fresh) {
      const pending = inflightHtml.get(key);
      if (pending) return pending;
    }
    const job = fetch(new URL(url, window.location.href).href, {
      headers: { Accept: "text/html" },
      credentials: "same-origin",
      cache: options.fresh ? "no-store" : "default",
    }).then(function (response) {
      if (!response.ok) {
        const error = new Error("fetch");
        error.status = response.status;
        error.href = response.url || url;
        throw error;
      }
      return response.text().then(function (html) {
        return { html: html, url: response.url || url };
      });
    }).finally(function () {
      if (!options.fresh) inflightHtml.delete(key);
    });
    if (!options.fresh) inflightHtml.set(key, job);
    return job;
  }

  function warmSurface(url, key) {
    if (key === currentKey) return;
    const existing = surfaceCache.get(key);
    if (existing && !existing.dirty) return;
    fetchHtml(url).then(function (result) {
      if (!result || key === currentKey) return;
      const latest = surfaceCache.get(key);
      if (latest && !latest.dirty && latest.live) return;
      const snap = snapshotFromHtml(result.html);
      if (!snap) return;
      const again = surfaceCache.get(key);
      if (again && !again.dirty && again.live) return;
      rememberSnap(key, snap);
    }).catch(function () {});
  }

  function schedulePrefetch(url) {
    if (!url || !surfaceUrl(url)) return;
    let key = "";
    try { key = cacheKey(url); }
    catch (error) { return; }
    if (key === currentKey) return;
    const hit = surfaceCache.get(key);
    if (hit && !hit.dirty) return;
    if (url === prefetchHref) return;
    prefetchHref = url;
    window.clearTimeout(prefetchTimer);
    prefetchTimer = window.setTimeout(function () {
      prefetchTimer = 0;
      const href = prefetchHref;
      prefetchHref = "";
      if (!href) return;
      let nextKey = "";
      try { nextKey = cacheKey(href); }
      catch (error) { return; }
      warmSurface(href, nextKey);
    }, 110);
  }

  function applySnapshot(snap, url, options) {
    options = options || {};
    const main = document.getElementById("main");
    if (!snap || !snap.main || !main || snap.slug !== slug) return false;
    let nextKey = currentKey;
    try { nextKey = cacheKey(url); }
    catch (error) { nextKey = currentKey; }
    document.querySelectorAll("dialog[open]").forEach(function (dialog) { dialog.close(); });
    if (nextKey !== currentKey) captureSurface();
    boardPreview = false;
    if (filterAbort) filterAbort.abort();
    filterGeneration += 1;
    const flash = document.querySelector("#global-container > .flash");
    if (flash) flash.remove();
    if (snap.flash && main.parentNode) main.parentNode.insertBefore(snap.flash.cloneNode(true), main);
    main.replaceWith(snap.main.cloneNode(true));
    const header = document.getElementById("header");
    if (header) header.className = snap.headerClass;
    for (let index = 0; index < SLOT_SELECTORS.length; index += 1) {
      const selector = SLOT_SELECTORS[index];
      const dest = document.querySelector(selector);
      if (dest) dest.innerHTML = snap.slots[selector] || "";
    }
    document.body.className = snap.bodyClass;
    if (snap.title) document.title = snap.title;
    invalidateLists();
    selectedNode = null;
    selectedColumn = null;
    dialogOpen = !!document.querySelector("dialog[open]");
    let hash = "";
    try { hash = new URL(url, window.location.href).hash; } catch (error) { hash = ""; }
    if (options.push !== false) {
      const prev = history.state && history.state.fizzy ? history.state : { fizzy: true, depth: 0 };
      history.pushState({
        fizzy: true,
        depth: (prev.depth || 0) + 1,
        returnTo: window.location.pathname + window.location.search,
        card: options.restoreCard || null,
      }, "", url);
    }
    currentKey = nextKey;
    bootSurface(options.restoreCard, hash);
    window.scrollTo(0, 0);
    return true;
  }

  function applyDocument(html, url, options) {
    const snap = snapshotFromHtml(html);
    if (!snap) return false;
    let key = "";
    try { key = cacheKey(url); }
    catch (error) { key = ""; }
    if (key) rememberSnap(key, snap);
    return applySnapshot(snap, url, options);
  }

  function showPage(url, options) {
    options = options || {};
    const token = ++navToken;
    let requested;
    try { requested = new URL(url, window.location.href); }
    catch (error) {
      window.location.assign(url);
      return Promise.resolve(null);
    }
    const key = cacheKey(requested.href);
    const display = requested.pathname + requested.search + requested.hash;
    const preferFresh = !!(options.fresh || composeAfterBoard);
    const cached = preferFresh ? null : surfaceCache.get(key);
    let painted = false;
    let paintOptions = options;
    if (cached && cached.main) {
      const stamp = interactionStamp;
      if (!applySnapshot(cached, display, options)) {
        window.location.assign(requested.href);
        return Promise.resolve(null);
      }
      painted = true;
      if (!cached.dirty) return Promise.resolve(true);
      paintOptions = Object.assign({}, options, { push: false, revalidateStamp: stamp });
    }
    return fetchHtml(requested.href, { fresh: preferFresh }).then(function (result) {
      if (token !== navToken || !result) return null;
      const snap = snapshotFromHtml(result.html);
      const finalUrl = new URL(result.url || requested.href, window.location.href);
      if (requested.hash) finalUrl.hash = requested.hash;
      const finalKey = cacheKey(finalUrl.href);
      const finalDisplay = finalUrl.pathname + finalUrl.search + finalUrl.hash;
      if (!snap) {
        if (!painted) window.location.assign(finalUrl.href);
        return null;
      }
      if (painted && paintOptions.revalidateStamp !== undefined && interactionStamp !== paintOptions.revalidateStamp) {
        snap.dirty = true;
        rememberSnap(finalKey, snap);
        return true;
      }
      rememberSnap(finalKey, snap);
      if (!applySnapshot(snap, finalDisplay, paintOptions) && !painted) window.location.assign(finalUrl.href);
      return true;
    }).catch(function () {
      composeAfterBoard = false;
      if (token === navToken && !painted) window.location.assign(requested.href);
    });
  }

  function openSurface(url, options) {
    options = options || {};
    const target = new URL(url, window.location.href);
    const state = history.state;
    // Returning to the board we just left should pop, so the stack stays board then card.
    if (!options.force && state && state.fizzy && state.depth > 0 && state.returnTo && pathOf(state.returnTo) === pathOf(target.href) && pathOf(target.href) !== pathOf(window.location.href)) {
      history.back();
      return Promise.resolve(true);
    }
    if (boardRoot()) rememberBoardCard();
    return showPage(target.pathname + target.search + target.hash, options);
  }

  document.addEventListener("click", function (event) {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = event.target && event.target.closest && event.target.closest("a[href]");
    if (!link || link.hasAttribute("download")) return;
    if (link.target && link.target !== "_self") return;
    if (!surfaceUrl(link.href)) return;
    const next = new URL(link.href, window.location.href);
    if (next.pathname === window.location.pathname && next.search === window.location.search && next.hash === window.location.hash) {
      event.preventDefault();
      document.querySelectorAll("dialog[open]").forEach(function (dialog) { dialog.close(); });
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const number = (window.location.pathname.match(/\/cards\/(\d+)\/?$/) || [])[1];
    const back = link.hasAttribute("data-back");
    openSurface(link.href, back && number ? { restoreCard: number } : null);
  }, true);

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

  let dialogOpen = false;
  document.addEventListener("toggle", function (event) {
    const dialog = event.target;
    if (!dialog || dialog.tagName !== "DIALOG") return;
    dialogOpen = dialog.open || !!document.querySelector("dialog[open]");
  }, true);

  document.addEventListener("mouseover", function (event) {
    if (event.buttons || dialogOpen) return;
    const target = event.target;
    if (!target || !target.closest) return;
    if (selectedNode && selectedNode.isConnected && (target === selectedNode || selectedNode.contains(target))) return;
    const card = target.closest("article.card");
    if (!card || card === selectedNode || !card.closest("#board-stage, .card-columns")) return;
    if (event.relatedTarget && card.contains(event.relatedTarget)) return;
    const column = card.closest("section.cards");
    if (column && column.classList.contains("is-collapsed")) return;
    selectCard(card, undefined, true);
  });

  function watchCardLists(root) {
    if (!root || watchedLists.has(root)) return;
    watchedLists.add(root);
    new MutationObserver(invalidateLists).observe(root, { childList: true, subtree: true });
  }

  desktopQuery.addEventListener("change", function () {
    if (boardRoot()) restoreColumns();
  });

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
    } else {
      const active = document.activeElement;
      if (active && editor.contains(active) && active.blur) active.blur();
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
          else if (dialog.closest(".delete-card")) {
            const confirm = dialog.querySelector("button[type='submit']");
            if (confirm) confirm.focus();
          }
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
    if (link) link.click();
  });

  let dropHover = null;

  document.addEventListener("dragstart", function (event) {
    const card = event.target.closest && event.target.closest("article.card");
    if (!card || card.getAttribute("draggable") !== "true") return;
    event.dataTransfer.setData("text/plain", card.dataset.number);
    event.dataTransfer.effectAllowed = "move";
    card.classList.add("drag-and-drop__dragged-item");
  });

  document.addEventListener("dragend", function () {
    dropHover = null;
    const nodes = document.querySelectorAll("article.card.drag-and-drop__dragged-item, section.cards.drag-and-drop__hover-container");
    for (let index = 0; index < nodes.length; index += 1) {
      nodes[index].classList.remove("drag-and-drop__dragged-item", "drag-and-drop__hover-container");
    }
  });

  document.addEventListener("dragover", function (event) {
    const column = event.target.closest && event.target.closest("section.cards");
    if (!column || (!column.dataset.columnId && !column.dataset.lane)) return;
    event.preventDefault();
    if (dropHover === column) return;
    if (dropHover && dropHover.isConnected) dropHover.classList.remove("drag-and-drop__hover-container");
    column.classList.add("drag-and-drop__hover-container");
    dropHover = column;
  });

  document.addEventListener("drop", function (event) {
    const column = event.target.closest && event.target.closest("section.cards");
    if (!column || (!column.dataset.columnId && !column.dataset.lane)) return;
    event.preventDefault();
    if (dropHover && dropHover.isConnected) dropHover.classList.remove("drag-and-drop__hover-container");
    dropHover = null;
    column.classList.remove("drag-and-drop__hover-container");
    const number = event.dataTransfer.getData("text/plain");
    const card = number && document.querySelector('article.card[data-number="' + number + '"]');
    const move = columnMoveFields(column, number);
    if (!move || !card) return;
    const epoch = beginMove(number);
    const relocated = relocateCard(card, column);
    post(move.url, move.fields, { epoch: epoch, number: number }).then(function (payload) {
      if (!moveIsCurrent(number, epoch)) return;
      if (!payload && relocated) {
        relocated.undo();
        if (relocated.boardUrl) markDirtyUrl(relocated.boardUrl);
      }
    }, function () {
      if (!moveIsCurrent(number, epoch)) return;
      if (relocated) relocated.undo();
      window.alert("Could not update that card.");
    });
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
  let searchAbort = null;
  let searchPaint = 0;
  let lastSearchCards = null;

  function paintSearch(cards) {
    if (!barResults) return;
    if (!cards.length) {
      barResults.innerHTML = '<p class="blank-slate">No matches.</p>';
    } else {
      let html = "<ul>";
      for (let index = 0; index < cards.length; index += 1) {
        const card = cards[index];
        const boardName = card.board && card.board.name ? card.board.name : "";
        html += '<li><a class="search__result" href="' + escapeHtml(card.url) + '"><h3 class="search__title">#' + escapeHtml(card.number) + " " + escapeHtml(card.title || "Untitled") + "</h3><div class=\"search__excerpt\">" + escapeHtml((card.description || "").slice(0, 180)) + "</div><div class=\"overflow-ellipsis translucent\">" + escapeHtml(boardName) + "</div></a></li>";
      }
      html += "</ul>";
      barResults.innerHTML = html;
    }
    if (barModal && !barModal.open) barModal.show();
  }

  function renderSearch(cards, sync) {
    lastSearchCards = cards || [];
    if (sync) {
      if (searchPaint) {
        cancelAnimationFrame(searchPaint);
        searchPaint = 0;
      }
      paintSearch(lastSearchCards);
      return;
    }
    if (searchPaint) return;
    searchPaint = requestAnimationFrame(function () {
      searchPaint = 0;
      paintSearch(lastSearchCards);
    });
  }

  if (barInput) {
    barInput.addEventListener("input", function () {
      const query = barInput.value.trim();
      const generation = ++searchGeneration;
      window.clearTimeout(barInput.searchTimer);
      if (searchAbort) searchAbort.abort();
      if (!query || !slug) {
        if (barModal && barModal.open) barModal.close();
        if (barResults) barResults.innerHTML = "";
        lastSearchCards = null;
        return;
      }
      barInput.searchTimer = window.setTimeout(function () {
        if (generation !== searchGeneration) return;
        const controller = new AbortController();
        searchAbort = controller;
        fetch(slug + "/search?q=" + encodeURIComponent(query), {
          headers: { Accept: "application/json" },
          credentials: "same-origin",
          signal: controller.signal,
        }).then(function (response) {
          return response.json();
        }).then(function (payload) {
          if (generation !== searchGeneration) return;
          renderSearch((payload && payload.cards) || []);
        }).catch(function (error) {
          if (error && error.name === "AbortError") return;
        });
      }, 160);
    });
  }

  const jumpFilter = document.querySelector("[data-jump-filter]");
  let jumpPaint = 0;
  if (jumpFilter) {
    jumpFilter.addEventListener("input", function () {
      const query = jumpFilter.value.trim().toLowerCase();
      if (jumpPaint) cancelAnimationFrame(jumpPaint);
      jumpPaint = requestAnimationFrame(function () {
        jumpPaint = 0;
        const links = document.querySelectorAll("[data-jump-list] a");
        for (let index = 0; index < links.length; index += 1) {
          const link = links[index];
          const text = link.textContent ? link.textContent.toLowerCase() : "";
          link.hidden = !!query && text.indexOf(query) === -1;
        }
      });
    });
  }

  let filterGeneration = 0;
  let filterAbort = null;
  let filterTimer = 0;
  let popupPaint = 0;

  function activeFilterForm() {
    return document.querySelector("aside.filters form");
  }

  function filterParams(form) {
    const params = new URLSearchParams(new FormData(form));
    const terms = params.getAll("terms[]");
    params.delete("terms[]");
    for (let index = 0; index < terms.length; index += 1) {
      if (terms[index].trim()) params.append("terms[]", terms[index]);
    }
    return params;
  }

  function previewIsActive(params, typed) {
    if (typed && typed.value.trim()) return true;
    if ((params.get("indexed_by") || "all") !== "all") return true;
    if ((params.get("sorted_by") || "latest") !== "latest") return true;
    if (params.get("assignment_status")) return true;
    if (params.get("creation") || params.get("closure") || params.get("q")) return true;
    const lists = ["assignee_ids[]", "creator_ids[]", "closer_ids[]", "tag_ids[]", "column_ids[]"];
    for (let index = 0; index < lists.length; index += 1) {
      if (params.getAll(lists[index]).length) return true;
    }
    return false;
  }

  function runFilterPreview(form) {
    const stage = document.getElementById("board-stage");
    if (!form || !stage || !form.isConnected) return;
    if (filterAbort) filterAbort.abort();
    const controller = new AbortController();
    filterAbort = controller;
    const generation = ++filterGeneration;
    const params = filterParams(form);
    const typed = form.querySelector(".filter__terms");
    const action = form.getAttribute("action") || form.action;
    fetch(action + "?" + params.toString(), {
      headers: { "X-Fizzy-Fragment": "board", Accept: "text/html" },
      credentials: "same-origin",
      signal: controller.signal,
    }).then(function (response) {
      if (!response.ok) return "";
      return response.text();
    }).then(function (html) {
      if (!html) return;
      if (generation !== filterGeneration) return;
      requestAnimationFrame(function () {
        if (generation !== filterGeneration) return;
        const current = document.getElementById("board-stage");
        if (!current || !form.isConnected) return;
        current.innerHTML = html;
        boardPreview = previewIsActive(params, typed);
        invalidateLists();
        if (boardRoot()) restoreColumns();
        else chooseFallback();
        paintBubbles(current);
        if (!boardPreview) captureSurface();
      });
    }).catch(function (error) {
      if (error && error.name === "AbortError") return;
    });
  }

  function scheduleFilterPreview(form) {
    window.clearTimeout(filterTimer);
    filterTimer = window.setTimeout(function () {
      filterTimer = 0;
      runFilterPreview(form);
    }, 150);
  }

  function bindSurfaceFilters() {
    const form = activeFilterForm();
    if (!form || watchedFilters.has(form)) return;
    watchedFilters.add(form);
    form.addEventListener("input", function (event) {
      if (!event.target || !event.target.classList.contains("filter__terms")) return;
      scheduleFilterPreview(form);
    });
    form.addEventListener("change", function (event) {
      if (event.target && event.target.type === "checkbox") scheduleFilterPreview(form);
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
      const number = (window.location.pathname.match(/\/cards\/(\d+)\/?$/) || [])[1];
      noteMutation(number);
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
    const number = (window.location.pathname.match(/\/cards\/(\d+)\/?$/) || [])[1];
    noteMutation(payload.number || number);
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
    invalidateLists();
    if (boardRoot()) restoreColumns();
    else chooseFallback();
    paintBubbles(stage);
    noteMutation(null);
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
    if (popupPaint) cancelAnimationFrame(popupPaint);
    popupPaint = requestAnimationFrame(function () {
      popupPaint = 0;
      const items = dialog.querySelectorAll(".popup__item");
      for (let index = 0; index < items.length; index += 1) {
        const item = items[index];
        const text = (item.textContent || "").toLowerCase();
        item.hidden = !item.hasAttribute("data-popup-keep") && !!query && text.indexOf(query) === -1;
      }
    });
  });

  document.addEventListener("focusout", function (event) {
    const form = event.target.closest && event.target.closest("form.card__edit");
    if (!form) return;
    if (event.target.matches("[name='card[title]'], .card__description")) saveCardFields(form);
  });

  function optimisticStage(form, submitter) {
    const stages = document.querySelector("#card-sheet .card__stages");
    if (!stages || !form) return null;
    const action = form.getAttribute("action") || "";
    if (action.indexOf("/closure") === -1 && action.indexOf("/not_now") === -1 && action.indexOf("/triage") === -1) return null;
    let button = submitter && stages.contains(submitter) ? submitter : null;
    if (!button) {
      const method = form.querySelector("[name='_method']");
      const deleting = method && method.value === "delete";
      if (action.indexOf("/not_now") !== -1) button = stages.querySelector("[data-hotkey='postpone']");
      else if (action.indexOf("/closure") !== -1 && !deleting) button = stages.querySelector("[data-hotkey='done']");
      else if (action.indexOf("/triage") !== -1 && deleting) button = stages.querySelector(".card__column-name--stream");
      else if (action.indexOf("/triage") !== -1 && submitter && submitter.name === "column_id") {
        const buttons = stages.querySelectorAll("button[name='column_id']");
        for (let index = 0; index < buttons.length; index += 1) {
          if (buttons[index].value === submitter.value) {
            button = buttons[index];
            break;
          }
        }
      }
    }
    if (!button || !stages.contains(button)) return null;
    const previous = [];
    const names = stages.querySelectorAll(".card__column-name");
    for (let index = 0; index < names.length; index += 1) {
      previous.push({
        node: names[index],
        current: names[index].classList.contains("card__column-name--current"),
        disabled: names[index].disabled,
      });
    }
    for (let index = 0; index < previous.length; index += 1) {
      const on = previous[index].node === button;
      previous[index].node.classList.toggle("card__column-name--current", on);
      if (previous[index].node.tagName === "BUTTON") previous[index].node.disabled = on;
    }
    return function () {
      for (let index = 0; index < previous.length; index += 1) {
        previous[index].node.classList.toggle("card__column-name--current", previous[index].current);
        if (previous[index].node.tagName === "BUTTON") previous[index].node.disabled = previous[index].disabled;
      }
    };
  }

  document.addEventListener("submit", function (event) {
    const form = event.target;
    if (!form || form.hasAttribute("data-native-submit") || (form.getAttribute("method") || "").toLowerCase() === "dialog") return;
    if (form.classList.contains("danger")) {
      const label = (form.querySelector("button") || {}).textContent || "this";
      if (!window.confirm("Continue and " + label.trim().toLowerCase() + "?")) event.preventDefault();
      return;
    }
    if (form.querySelector(".filter__terms") && surfaceUrl(form.action)) {
      event.preventDefault();
      event.stopPropagation();
      const typed = form.querySelector(".filter__terms");
      const params = filterParams(form);
      if (typed && typed.disabled) typed.disabled = false;
      const action = form.getAttribute("action") || form.action;
      openSurface(action + "?" + params.toString(), { force: true });
      return;
    }
    if (form.hasAttribute("data-add-card")) {
      event.preventDefault();
      event.stopPropagation();
      const token = ++navToken;
      if (boardRoot()) rememberBoardCard();
      postForm(form, event.submitter, { Accept: "text/html" }).then(function (response) {
        if (token !== navToken) return null;
        if (!response.ok) {
          window.alert("Could not add that card.");
          return null;
        }
        return response.text().then(function (html) {
          if (token !== navToken) return;
          const finalUrl = response.url || form.action;
          if (!applyDocument(html, finalUrl)) window.location.assign(finalUrl);
        });
      }).catch(function () {
        if (token === navToken) window.alert("Could not add that card.");
      });
      return;
    }
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
        invalidateLists();
        recount(column);
        paintBubble(card.querySelector(".bubble"));
        selectCard(card);
        noteMutation(card.dataset.number);
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
    const undoStage = optimisticStage(form, submitter);
    const releaseSubmit = function () {
      if (form.dataset.submitting) delete form.dataset.submitting;
    };
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
        if (form.dataset.saveNext === "1") {
          delete form.dataset.saveNext;
          if (payload) reopenComposer();
          else if (undoStage) undoStage();
          return;
        }
        if (payload) applyCardSheet(payload);
        else if (undoStage) undoStage();
      }, function () {
        delete form.dataset.saveNext;
        if (undoStage) undoStage();
        window.alert("Could not update that card.");
      }).then(releaseSubmit, releaseSubmit);
    };
    if (pending) {
      saveCardFields(edit).then(function (ok) {
        if (!ok) {
          delete form.dataset.saveNext;
          window.alert("Could not save the card before that change.");
          releaseSubmit();
          return;
        }
        send();
      }, function () {
        delete form.dataset.saveNext;
        releaseSubmit();
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
    ["> <", "Move the selected card to the next or previous list. The next card in this list stays selected. 3> jumps three lists."],
    ["gg", "First card in this column."],
    ["G", "Last card. 3G is the third card."],
    ["Enter", "Open the selected card."],
    ["f char", "Next card whose title starts with that letter, or contains it."],
    ["F char", "Same search, upward."],
    ["; ,", "Repeat the last f or F forward or backward."],
    ["dd", "Done. 3dd closes this card and the two below it."],
    ["dn", "Not now. Same count as dd."],
    ["dx", "Delete the selected card."],
    [".", "Repeat the last dd or dn on the selected card."],
    ["o", "Add a card in Maybe."],
    ["Enter", "Create the new card from its title."],
    ["Ctrl/Cmd Enter", "Save and next. Create the card and open another new card in this column."],
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
    const source = current.closest("section.cards");
    const jobs = [];
    slice.forEach(function (card) {
      const url = kind === "done" ? card.dataset.closureUrl : card.dataset.notNowUrl;
      if (url) jobs.push({ url: url, card: card });
    });
    if (!jobs.length) return;
    const target = laneColumn(kind === "done" ? "closed" : "not_now");
    const undos = [];
    jobs.forEach(function (job) {
      const moved = target ? relocateCard(job.card, target) : detachCard(job.card);
      if (moved) undos.push(moved);
    });
    pushHold();
    selectAfterMove(source, successor);
    const selectionMark = selectionEpoch;
    let chain = Promise.resolve();
    let failed = false;
    jobs.forEach(function (job) {
      chain = chain.then(function () {
        if (failed) return null;
        const number = job.card.dataset.number;
        const epoch = beginMove(number);
        return post(job.url, null, { epoch: epoch, number: number }).then(function (payload) {
          if (!moveIsCurrent(number, epoch)) return payload;
          if (!payload) {
            failed = true;
            undos.forEach(function (item) { item.undo(); });
          }
          return payload;
        });
      });
    });
    chain.then(function () {
      popHold();
      if (selectionEpoch === selectionMark) selectAfterMove(source, successor);
    }, function () {
      popHold();
      undos.forEach(function (item) { item.undo(); });
      window.alert("Could not update that card.");
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

  function submitNewCard(field, next) {
    const title = (field.value || "").trim();
    if (!title) return;
    const create = document.querySelector(".card-perma__notch-new-card-buttons form");
    if (!create || create.dataset.submitting === "1") return;
    create.dataset.submitting = "1";
    if (next) create.dataset.saveNext = "1";
    else delete create.dataset.saveNext;
    if (create.requestSubmit) create.requestSubmit();
    else create.submit();
  }

  function reopenComposer() {
    const home = boardUrl();
    if (!home) return;
    const number = (window.location.pathname.match(/\/cards\/(\d+)\/?$/) || [])[1];
    if (number) markDirtyUrl(slug + "/cards/" + number);
    markDirtyUrl(home);
    composeAfterBoard = true;
    skipNextCapture = true;
    openSurface(home);
  }

  function deleteSelected() {
    if (onCardPage()) {
      const opener = document.querySelector(".delete-card [data-dialog-open]");
      if (opener) opener.click();
      return;
    }
    const card = selectedCard();
    if (!card || !card.dataset.number || !slug) return;
    const number = card.dataset.number;
    const source = card.closest("section.cards");
    const siblings = source ? visibleCards(source) : [];
    const index = siblings.indexOf(card);
    const successor = index >= 0 ? (siblings[index + 1] || siblings[index - 1] || null) : null;
    const removed = detachCard(card);
    selectAfterMove(source, successor);
    const selectionMark = selectionEpoch;
    const body = new FormData();
    body.append("csrf_token", csrf);
    body.append("_method", "delete");
    fetch(slug + "/cards/" + number, {
      method: "POST",
      body: body,
      credentials: "same-origin",
    }).then(function (response) {
      if (!response.ok) {
        if (removed) removed.undo();
        window.alert("Could not delete that card.");
        if (selectionEpoch === selectionMark) chooseFallback();
        return;
      }
      noteMutation(number);
      if (selectionEpoch === selectionMark) selectAfterMove(source, successor);
    }, function () {
      if (removed) removed.undo();
      window.alert("Could not delete that card.");
      if (selectionEpoch === selectionMark) chooseFallback();
    });
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
    if (link) openSurface(link.href.split("#")[0] + "#edit");
  }

  function selectAfterMove(source, successor) {
    if (successor && successor.isConnected && source && source.contains(successor) && !source.classList.contains("is-collapsed")) {
      selectCard(successor);
      return;
    }
    if (source && source.isConnected) {
      selectCard(null);
      source.focus();
      return;
    }
    chooseFallback();
  }

  function moveLists() {
    return columns().filter(function (column) {
      return column.dataset.columnId || column.dataset.lane;
    });
  }

  function moveSelectedTo(direction) {
    const steps = Math.max(1, takeCount());
    const sign = direction < 0 ? -1 : 1;
    if (onCardPage()) {
      const buttons = Array.from(document.querySelectorAll("#card-sheet .card__stages button"));
      if (!buttons.length) return;
      let index = buttons.findIndex(function (button) {
        return button.disabled || button.classList.contains("card__column-name--current");
      });
      if (index < 0) index = 0;
      const dest = Math.max(0, Math.min(buttons.length - 1, index + sign * steps));
      if (dest === index) return;
      const button = buttons[dest];
      if (button.form && button.form.requestSubmit) button.form.requestSubmit(button);
      else button.click();
      return;
    }
    const list = moveLists();
    const card = selectedCard();
    if (!list.length || !card) return;
    const current = card.closest("section.cards");
    const index = list.indexOf(current);
    if (index < 0) return;
    const destIndex = Math.max(0, Math.min(list.length - 1, index + sign * steps));
    if (destIndex === index) return;
    const move = columnMoveFields(list[destIndex], card.dataset.number);
    if (!move) return;
    const cards = visibleCards(current);
    const cardIndex = cards.indexOf(card);
    const successor = cards[cardIndex + 1] || cards[cardIndex - 1] || null;
    const number = card.dataset.number;
    const epoch = beginMove(number);
    const relocated = relocateCard(card, list[destIndex]);
    pushHold();
    selectAfterMove(current, successor);
    const selectionMark = selectionEpoch;
    post(move.url, move.fields, { epoch: epoch, number: number }).then(function (payload) {
      popHold();
      if (!moveIsCurrent(number, epoch)) return;
      if (!payload && relocated) {
        relocated.undo();
        if (relocated.boardUrl) markDirtyUrl(relocated.boardUrl);
      }
      if (selectionEpoch === selectionMark) selectAfterMove(current, successor);
    }, function () {
      popHold();
      if (!moveIsCurrent(number, epoch)) return;
      if (relocated) relocated.undo();
      window.alert("Could not update that card.");
      chooseFallback();
    });
  }

  function showSearchHit(direction) {
    if (!lastSearchCards || !lastSearchCards.length || !barResults) return;
    if (!barResults.querySelector(".search__result")) {
      if (barField && barField.hidden) openSearch();
      renderSearch(lastSearchCards, true);
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
      else if (key === "x" && !event.metaKey && !event.ctrlKey && !event.altKey) {
        dropCount();
        deleteSelected();
      }
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

  function moveMotion(key, steps, coarse) {
    if (key === "j" || key === "ArrowDown") {
      if (!onCardPage()) moveCard(steps, coarse);
      return;
    }
    if (key === "k" || key === "ArrowUp") {
      if (!onCardPage()) moveCard(-steps, coarse);
      return;
    }
    if (key === "h" || key === "ArrowLeft") {
      if (columns().length) moveColumn(-steps, coarse);
      else if (steps === 1) goBack();
      return;
    }
    if (key === "l" || key === "ArrowRight") {
      if (columns().length) moveColumn(steps, coarse);
    }
  }

  document.addEventListener("keydown", function (event) {
    const key = event.key;
    const meta = event.metaKey || event.ctrlKey;
    const plain = !meta && !event.altKey && !event.shiftKey;
    if (event.repeat && plain && !pending && !dialogOpen && !typing(event) && (
      key === "j" || key === "k" || key === "h" || key === "l" ||
      key === "ArrowDown" || key === "ArrowUp" || key === "ArrowLeft" || key === "ArrowRight"
    )) {
      event.preventDefault();
      moveMotion(key, 1, true);
      return;
    }
    const jump = dialogById("jump");

    if (event.target.matches && event.target.matches("[name='card[title]']") && key === "Enter" && plain) {
      if (event.target.hasAttribute("data-new-card-title")) {
        if (event.isComposing) return;
        event.preventDefault();
        if (!event.repeat) submitNewCard(event.target);
        return;
      }
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
      if (typing(event)) {
        if (event.target && event.target.blur) event.target.blur();
        event.preventDefault();
        return;
      }
      goBack();
      return;
    }

    if (meta && key === "Enter") {
      if (event.target.matches && event.target.matches("[data-new-card-title]")) {
        event.preventDefault();
        if (!event.repeat && !event.isComposing) submitNewCard(event.target, true);
        return;
      }
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
          chosen.click();
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

    const deleteDialog = document.querySelector(".delete-card dialog[open]");
    if (deleteDialog && key === "Enter" && !typing(event) && !meta && !event.altKey) {
      const form = deleteDialog.querySelector("form[data-native-submit]");
      if (form) {
        event.preventDefault();
        if (form.requestSubmit) form.requestSubmit();
        else form.submit();
        return;
      }
    }

    const openDialog = dialogOpen ? document.querySelector("dialog[open]") : null;
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
    if (plain && key === "Enter" && (boardRoot() || gridElement())) {
      const card = selectedCard();
      const link = card && card.querySelector(".card__link");
      if (link) {
        event.preventDefault();
        dropCount();
        link.click();
      }
      return;
    }
    if (!meta && !event.altKey && (key === ">" || key === "<")) {
      event.preventDefault();
      if (event.repeat) {
        dropCount();
        return;
      }
      moveSelectedTo(key === ">" ? 1 : -1);
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

  if ("scrollRestoration" in history) history.scrollRestoration = "manual";
  if (!history.state || !history.state.fizzy) {
    history.replaceState({ fizzy: true, depth: 0 }, "", window.location.href);
  }
  try { currentKey = cacheKey(window.location.href); }
  catch (error) { currentKey = ""; }
  window.addEventListener("popstate", function (event) {
    const state = event.state;
    if (!state || !state.fizzy) return;
    showPage(window.location.pathname + window.location.search + window.location.hash, {
      push: false,
      restoreCard: state.card || null,
    });
  });
  bootSurface(history.state && history.state.card, window.location.hash);
  captureSurface();

  document.documentElement.dataset.fizzyReady = "1";
})();
