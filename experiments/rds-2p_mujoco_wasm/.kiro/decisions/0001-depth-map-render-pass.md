# 0001. Depth Map Render Pass

## Status
accepted

## Context
Нужна цветная карта глубины 0–2 м в существующем Three.js симуляторе. Визуальный декор отсутствует в MuJoCo, RGB-камера одна. Альтернативы: полный raycast по пикселям, DepthTexture с GPU-постобработкой, настоящее стереосопоставление.

## Decision
Техническое предложение: центральная независимая камера по CAMERA_CONFIG, MeshDepthMaterial с RGBADepthPacking, RGBA8 target 320x240, чтение пикселей и перевод перспективной глубины в метры на CPU. Окно внутри страницы, отдельный lifecycle от YOLO. Design требует отдельного одобрения пользователя.

## Consequences
Плюс: повторное использование визуальной сцены и renderer без новых зависимостей. Минус: синхронный readback может задерживать кадр; нужны замеры и лимит 15 Гц. Восстановление состояния renderer и scene в finally обязательно. Синтетическая глубина не моделирует ошибки физической стереокамеры. Принятие ADR фиксирует технический выбор для review, а не разрешает реализацию.

## Links
- .kiro/specs/depth-map/requirements.md
- .kiro/specs/depth-map/design.md
- https://threejs.org/docs/pages/MeshDepthMaterial.html
