# Micro Spec: перетаскивание окна карты глубины

**Type:** Minor UI Update
**Effort:** < 1 дня
**Date:** 2026-11-18
**Статус:** реализовано и проверено, PASS.

## Intent (What + Why)
**What:** Пользователь уточнил: перетаскивать окно карты по экрану, а не менять ракурс камеры.
**Why:** Размещать карту в удобном месте, освобождая нужную часть симулятора.

## Boundaries (Files + Out-of-scope)
**Files:**
- `src/vision/depth-map.js` — pointer drag за заголовок, ограничение экраном, очистка, resize/open.
- `src/vision/depth-map.css` — курсор и touch-action заголовка.
- `index.html`, `README.md` — подсказка способа перемещения.
- `tools/check_depth_browser.py` — браузерная проверка drag, границ и resize.
- `.kiro/specs/depth-map/requirements.md`, `.kiro/specs/depth-map/design.md`, `.kiro/specs/depth-map/tasks.md`, `.kiro/specs/depth-map/evidence.md` — каскад уточнения и факт.
**Out-of-scope:** ракурс и положение камеры в сцене, формулы/диапазон глубины, новые зависимости, сохранение положения после перезагрузки страницы.

## How
Захватить основной указатель левой кнопкой на заголовке (кроме интерактивных элементов), двигать fixed-окно через left/top без скачка, использовать pointer capture. Clamp с отступом 12 px, resize и повторное открытие возвращают окно в экран. Позиция сохраняется между открытиями текущего контроллера. Pointerup/cancel/lostcapture, close/dispose завершают drag; слушатели используют существующий AbortController.

## Acceptance
1. Drag мышью за заголовок перемещает окно; камера и изображение сохраняют ракурс.
2. Pointer drag с touch работает; выделение текста и прокрутка не мешают захвату.
3. Окно остаётся в viewport после drag к любому краю, resize и повторного открытия.
4. Кнопка закрытия не запускает drag; Escape, закрытие и возобновление обновлений работают.
5. Pointercancel/lostcapture/close/dispose прекращают drag. Существующая браузерная и GPU-проверка карты, `node --check` и `git diff --check` PASS.

## Upgrade-гейт
Если изменение потребует новой архитектуры или зависимостей, повысить тип спеки до дальнейшей реализации.

## Verification
`python tools/check_depth_browser.py`: 32 браузерные проверки и 20 GPU-проверок PASS. Проверены реальные mouse/touch drag, все края, отмена и потеря захвата указателя, закрытие во время drag, сохранение позиции, resize и пересоздание контроллера после pagehide/pageshow. Ракурс камеры не меняется. JS/Python syntax, micro-spec validator и git diff --check PASS. Подробный JSON: `.kiro/specs/depth-map/drag-evidence.json`.
