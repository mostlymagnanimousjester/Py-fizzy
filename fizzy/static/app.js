(function () {
  const token = document.querySelector('meta[name="csrf-token"]');
  const csrf = token ? token.getAttribute("content") : "";
  const slug = document.body.dataset.slug || "";

  document.querySelectorAll("article.bubble[draggable='true']").forEach(function (card) {
    card.addEventListener("dragstart", function (event) {
      event.dataTransfer.setData("text/plain", card.dataset.number);
      event.dataTransfer.effectAllowed = "move";
      card.classList.add("dragging");
    });
    card.addEventListener("dragend", function () {
      card.classList.remove("dragging");
    });
  });

  document.querySelectorAll("section.column").forEach(function (column) {
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
      const body = new FormData();
      body.append("csrf_token", csrf);
      let url = slug + "/cards/" + number + "/triage";
      if (column.dataset.columnId) {
        body.append("column_id", column.dataset.columnId);
      } else if (column.dataset.lane === "maybe") {
        body.append("_method", "delete");
      } else if (column.dataset.lane === "not_now") {
        url = slug + "/cards/" + number + "/not_now";
      } else if (column.dataset.lane === "closed") {
        url = slug + "/cards/" + number + "/closure";
      } else {
        return;
      }
      fetch(url, { method: "POST", body: body, credentials: "same-origin" }).then(function (response) {
        if (response.ok) window.location.reload();
        else window.alert("Could not move that card.");
      });
    });
  });

  document.querySelectorAll("form.danger").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      const label = (form.querySelector("button") || {}).textContent || "this";
      if (!window.confirm("Continue and " + label.trim().toLowerCase() + "?")) {
        event.preventDefault();
      }
    });
  });
})();
