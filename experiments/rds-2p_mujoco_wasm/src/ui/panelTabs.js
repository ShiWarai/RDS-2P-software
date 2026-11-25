/** Переключение вкладок левой панели. onSwitch(id) вызывается при каждой смене. */
export function initPanelTabs({ onSwitch } = {}) {
  const buttons = Array.from(document.querySelectorAll("#panel-tabs [data-tab]"));
  const panels = new Map(
    buttons.map((b) => [b.dataset.tab, document.getElementById(`tab-${b.dataset.tab}`)])
  );

  function activate(id) {
    for (const btn of buttons) {
      const on = btn.dataset.tab === id;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    }
    for (const [key, node] of panels) {
      if (node) node.classList.toggle("hidden", key !== id);
    }
    onSwitch?.(id);
  }

  for (const btn of buttons) {
    btn.addEventListener("click", () => activate(btn.dataset.tab));
  }

  const initial = document.querySelector("#panel-tabs [data-tab].active")?.dataset.tab
    || buttons[0]?.dataset.tab;
  if (initial) { activate(initial); }

  return { activate };
}
