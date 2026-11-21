# Micro Spec: визуальный размер окна глубины

**Type:** Minor UI Update
**Effort:** < 1 дня
**Date:** 2026-11-18
**Статус:** реализовано и проверено, PASS.

## Intent (What + Why)
**What:** Добавить уменьшение и увеличение окна карты за нижний правый угол.
**Why:** Компактно размещать карту рядом с симулятором.

## Boundaries (Files + Out-of-scope)
**Files:** `src/vision/depth-map.js`, `src/vision/depth-map.css`, `index.html` — ручка изменения размера и ограничения; `README.md` — инструкция; `tools/check_depth_browser.py` — приёмка. Родительская спека `.kiro/specs/depth-map/` — каскад требований и evidence.
**Out-of-scope:** разрешение измерения 320×240, ракурс и диапазон камеры, новые зависимости, публикация изменений.

## How
Ширина окна задаётся pointer-перетаскиванием угла, высота содержимого автоматическая, карта остаётся 4:3. Минимум 260 px (или доступная ширина узкого экрана), максимум 640 px и viewport минус 24 px. Клавиши стрелок на ручке изменяют ширину шагом 20 px. Текущее положение ограничивается экраном; размер сохраняется между открытиями. Pointer capture освобождается при отмене, закрытии и dispose.

## Acceptance
1. Мышь и касание на угловой ручке уменьшают/увеличивают окно; arrows доступны с клавиатуры.
2. Canvas остаётся 4:3 и измеряет 320×240; изображение и легенда продолжают обновляться.
3. Минимум/максимум ширины и границы экрана соблюдаются при resize, перемещении, смене viewport и reopen.
4. Close/cancel/lost capture/dispose завершают resize; drag заголовка и закрытие работают как раньше.
5. Браузерная/GPU проверка карты, syntax, micro-spec validator и git diff --check PASS.

## Upgrade-гейт
При появлении новых компонентов или зависимостей пересмотреть тип спеки до реализации.

## Verification
`python tools/check_depth_browser.py`: 43 browser + 20 GPU PASS. Включены мышь, касание, клавиатура без управления роботом, min/max, 4:3 при неизменных 320×240, reopen, close/cancel, узкий viewport и доступность ручки при прокрутке содержимого. Read-only ревью без новых actionable ошибок. Протокол: `.kiro/specs/depth-map/resize-evidence.json`. Syntax, micro-spec validator и git diff --check PASS.
