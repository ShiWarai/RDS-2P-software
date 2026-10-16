# MuJoCo Web Simulator для RDS-2P

Веб-приложение для симуляции робота RDS-2P в браузере с использованием MuJoCo WebAssembly.

## Установка

Убедитесь, что `npm` установлен и запустите:

```bash
npm install
```

Это установит three.js и официальные WASM биндинги MuJoCo.

## Запуск

**Важно:** Запускайте сервер из директории `web/`!

### Вариант 1: Python (рекомендуется, самый надежный)

```bash
cd web
python3 -m http.server 8000
```

Затем откройте в браузере: `http://localhost:8000`

Для остановки сервера нажмите `Ctrl+C` в терминале.

### Вариант 2: Node.js http-server

```bash
cd web
npx http-server -p 8000
```

**Остановка сервера:**
- Если сервер запущен в терминале: нажмите `Ctrl+C`
- Если сервер запущен в фоне: `kill $(lsof -t -i:8000)` или `pkill -f "python3 -m http.server"`

## JavaScript API

```javascript
import load_mujoco from "./dist/mujoco_wasm.js";

// Загрузить модуль MuJoCo
const mujoco = await load_mujoco();

// Настроить виртуальную файловую систему Emscripten
mujoco.FS.mkdir('/working');
mujoco.FS.mount(mujoco.MEMFS, { root: '.' }, '/working');
mujoco.FS.writeFile("/working/humanoid.xml", await (await fetch("./assets/scenes/humanoid.xml")).text());

// Загрузить модель и создать данные
let model = mujoco.MjModel.loadFromXML("/working/humanoid.xml");
let data  = new mujoco.MjData(model);

// Доступ к свойствам модели напрямую
let timestep = model.opt.timestep;
let nbody = model.nbody;

// Доступ к буферам данных (типизированные массивы)
let qpos = data.qpos;  // Позиции джойнтов
let qvel = data.qvel;  // Скорости джойнтов
let ctrl = data.ctrl;  // Входные сигналы управления
let xpos = data.xpos;  // Позиции тел

// Шаг симуляции
mujoco.mj_step(model, data);

// Выполнить прямую кинематику
mujoco.mj_forward(model, data);

// Сбросить симуляцию
mujoco.mj_resetData(model, data);

// Применить силы (сила, момент, точка, тело, qfrc_target)
mujoco.mj_applyFT(model, data, [fx, fy, fz], [tx, ty, tz], [px, py, pz], bodyId, data.qfrc_applied);

// Очистка
data.delete();
model.delete();
```

## Модель робота RDS-2P

Этот проект включает модель робота RDS-2P Feetonly, адаптированную для MuJoCo WebAssembly.

### Добавленная модель

**RDS-2P Feetonly** (`rds2p_feetonly_scene.xml`)
   - Упрощенная модель с фокусом на конфигурацию только ног
   - Файл сцены: `web/assets/scenes/rds2p_feetonly_scene.xml`
   - Модель робота: `web/assets/scenes/rds-2p_feetonly.mjcf`
   - Меши: `web/assets/scenes/meshes/`

### Минимальные изменения для совместимости с WASM

Для обеспечения совместимости с MuJoCo WebAssembly были внесены следующие минимальные изменения в оригинальную модель:

1. **Параметры рендеринга**: Упрощены теги `<visual>` и `<option>` для соответствия примеру humanoid:
   - Заменены сложные опции `<compiler>` (`usethread`, `inertiagrouprange`) на стандартные настройки
   - Изменен `<option>` с `integrator="Euler"` и сложными флагами на простой параметр `timestep`
   - Обновлен `<visual>` для использования тега `<map>` вместо `<headlight>`
   - Добавлены `offwidth` и `offheight` в тег `<global>`

2. **Структура файлов**: 
   - Меши находятся в папке `meshes/`
   - Обновлены пути `<include>` для работы с виртуальной файловой системой

3. **Файл сцены**:
   - `rds2p_feetonly_scene.xml`: Использует `timestep="0.004"` (сохранено из оригинала)

Все остальные параметры модели (джойнты, актуаторы, сенсоры, keyframes) остались без изменений от оригинальной модели.

### Дополнительные возможности

- **Управление актуаторами**: Добавлен чекбокс "Use Actuators" в панели Simulation. Когда отключен (по умолчанию), робот использует значения управления из keyframes. Когда включен, доступно ручное управление через слайдеры актуаторов.
