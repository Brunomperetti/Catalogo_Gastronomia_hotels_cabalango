(() => {
  const grid = document.querySelector("[data-admin-gallery-sort]");
  if (!grid) return;

  const status = grid.parentElement.querySelector("[data-gallery-sort-status]");
  let dragged = null;
  let snapshot = [];
  let saving = false;
  const items = () => Array.from(grid.querySelectorAll(".admin-gallery-item"));

  function refresh() {
    items().forEach((item, index, all) => {
      item.dataset.galleryOriginalIndex = String(index);
      const input = item.querySelector('input[name="foto_indice"]');
      if (input) input.value = String(index);
      const left = item.querySelector('[data-gallery-move="left"]');
      const right = item.querySelector('[data-gallery-move="right"]');
      left.hidden = index === 0;
      right.hidden = index === all.length - 1;
      left.setAttribute("aria-label", `Mover foto ${index + 1} hacia la izquierda`);
      right.setAttribute("aria-label", `Mover foto ${index + 1} hacia la derecha`);
    });
  }

  async function save(previousOrder) {
    if (saving) return false;
    saving = true;
    status.textContent = "Guardando…";
    const order = items().map(item => item.dataset.galleryOriginalIndex).join(",");
    try {
      const body = new URLSearchParams({ orden: order });
      const response = await fetch(grid.dataset.reorderUrl, {
        method: "POST", body, credentials: "same-origin",
        headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" }
      });
      const result = response.redirected ? null : await response.json().catch(() => null);
      if (!response.ok || !result || result.ok !== true) throw new Error("reorder failed");
      refresh();
      status.textContent = "✓ Orden guardado";
      return true;
    } catch (error) {
      previousOrder.forEach(item => grid.appendChild(item));
      refresh();
      status.textContent = "No se pudo guardar el orden";
      return false;
    } finally {
      saving = false;
    }
  }

  grid.addEventListener("dragstart", event => {
    dragged = event.target.closest(".admin-gallery-item");
    if (!dragged || saving) { event.preventDefault(); return; }
    snapshot = items();
    dragged.classList.add("is-dragging");
    event.dataTransfer.effectAllowed = "move";
  });
  grid.addEventListener("dragover", event => {
    const target = event.target.closest(".admin-gallery-item");
    if (!dragged || !target || target === dragged) return;
    event.preventDefault();
    items().forEach(item => item.classList.remove("is-drag-over"));
    target.classList.add("is-drag-over");
    const bounds = target.getBoundingClientRect();
    const before = event.clientY < bounds.top + bounds.height * .25 ||
      (event.clientY <= bounds.top + bounds.height * .75 && event.clientX < bounds.left + bounds.width / 2);
    grid.insertBefore(dragged, before ? target : target.nextSibling);
  });
  grid.addEventListener("drop", event => event.preventDefault());
  grid.addEventListener("dragend", () => {
    if (!dragged) return;
    items().forEach(item => item.classList.remove("is-dragging", "is-drag-over"));
    const changed = snapshot.some((item, index) => items()[index] !== item);
    dragged = null;
    if (changed) save(snapshot);
  });
  grid.addEventListener("click", event => {
    const button = event.target.closest("[data-gallery-move]");
    if (!button || saving) return;
    const item = button.closest(".admin-gallery-item");
    const previousOrder = items();
    if (button.dataset.galleryMove === "left" && item.previousElementSibling) {
      grid.insertBefore(item, item.previousElementSibling);
    } else if (button.dataset.galleryMove === "right" && item.nextElementSibling) {
      grid.insertBefore(item.nextElementSibling, item);
    } else return;
    save(previousOrder);
  });
})();
