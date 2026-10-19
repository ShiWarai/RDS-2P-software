import { JOINT_ICONS, JOINT_NAMES, LEG_NAMES, LEG_ORDER } from "../sim/poseManager.js";


/** 12 слайдеров: сетка 2×2 «лап», в каждой 3 сустава (↔ ⤵ ↕). */
export function buildSliderPanel(container, { onChange }) {
  const inputs = [];
  container.replaceChildren();
  for (let leg = 0; leg < 4; leg++) {
    const block = document.createElement("div");
    block.className = "leg-block";
    const head = document.createElement("div");
    head.className = "leg-title";
    head.textContent = `🐾 ${LEG_ORDER[leg]}`;
    head.title = LEG_NAMES[leg];
    block.appendChild(head);
    for (let j = 0; j < 3; j++) {
      const i = leg * 3 + j;
      const row = document.createElement("div");
      row.className = "s-row";
      const ic = document.createElement("span");
      ic.className = "ic";
      ic.textContent = JOINT_ICONS[j];
      const input = document.createElement("input");
      input.type = "range";
      input.min = "0";
      input.max = "1";
      input.step = "0.02";
      input.value = "0.5";
      input.title = `мотор ${i + 1}: ${LEG_NAMES[leg]}, ${JOINT_NAMES[j]}`;
      input.addEventListener("input", () => onChange?.(getValues()));
      row.append(ic, input);
      block.appendChild(row);
      inputs.push(input);
    }
    container.appendChild(block);
  }

  function getValues() {
    return inputs.map((x) => Number(x.value));
  }

  function setValues(arr) {
    inputs.forEach((x, i) => {
      x.value = String(Math.min(1, Math.max(0, Number(arr?.[i] ?? 0.5))));
    });
  }

  setValues(new Array(12).fill(0.5));
  return { getValues, setValues };
}

export function toast(html, { kind = "", timeout = 4200 } = {}) {
  const holder = document.getElementById("toasts");
  const el = document.createElement("div");
  el.className = `toast${kind ? ` ${kind}` : ""}`;
  el.innerHTML = html;
  holder.appendChild(el);
  setTimeout(() => {
    el.style.transition = "opacity .3s";
    el.style.opacity = "0";
    setTimeout(() => el.remove(), 320);
  }, timeout);
}

export function buildCommandButtons(container, commands, onClick) {
  container.replaceChildren();
  for (const c of commands) {
    const b = document.createElement("button");
    b.className = "btn";
    b.textContent = c.text;
    b.title = `Панда выполнит: ${c.text.replace("*", "")}`;
    b.onclick = () => onClick(c.id);
    container.appendChild(b);
  }
}
