#!/usr/bin/env bash
# Переподключение PS4-джойстика (DualShock 4) по Bluetooth — запускать НА ХОСТЕ робота,
# ДО старта robot-контейнера. Контейнеру нужны только /dev/input/js0 и /dev/hidrawX
# (run_robot.sh --privileged их пробрасывает); стек bluez живёт на хосте, поэтому
# ключи пары/trust/автопереподключение переживают пересборку образа.
#
# Найденное на RepkaPi (Debian 12, bluez 5.66), всё учтено ниже:
#  - ядро не грузит hidp автоматически -> без него HID-профиль не биндится,
#    джойстик "подключается", но /dev/input/js* не появляется;
#  - bluetoothd определяет поддержку hidp при старте -> после загрузки модуля
#    демон нужно перезапустить;
#  - DS4 (HID Just Works) сопрягается прямой командой "bluetoothctl -- pair" —
#    пайпы/expect с агентом только создают гонку.
#
# Использование (от root): ./ps4_bt_reconnect.sh [MAC]
set -uo pipefail

JOYSTICK_MAC="${1:-70:20:84:5E:7C:F8}"

[ "$(id -u)" -eq 0 ] || { echo "Запусти от root."; exit 1; }
command -v bluetoothctl >/dev/null || { echo "Нужен bluez: apt-get install -y bluez"; exit 1; }

st() { bluetoothctl -- info "$JOYSTICK_MAC" 2>/dev/null | grep -E "^\s*$1:" | awk '{print $2}'; }

echo "=== PS4 джойстик $JOYSTICK_MAC ==="

systemctl is-active --quiet bluetooth || systemctl enable --now bluetooth
bluetoothctl -- power on >/dev/null 2>&1; sleep 1

# --- 1. hidp-модуль: загрузить, закрепить в автостарте, перезапустить демон если грузили ---
if ! lsmod | grep -q "^hidp"; then
  echo "Загружаем ядро HID over Bluetooth (hidp)..."
  modprobe hidp || { echo "ОШИБКА: modprobe hidp не прошёл (модуля нет в этом ядре)."; exit 1; }
  echo "hidp" > /etc/modules-load.d/rds2p-bt-hid.conf
  echo "Перезапускаем bluetoothd (он проверяет hidp на старте)..."
  systemctl restart bluetooth; sleep 3
  bluetoothctl -- power on >/dev/null 2>&1; sleep 1
fi

# --- 2. уже подключён? ---
if [ "$(st Connected)" = "yes" ] && [ "$(st ServicesResolved)" = "yes" ]; then
  echo "Уже подключен и HID активен."
else
  # --- 3. чистый цикл: remove -> scan -> pair -> trust -> connect ---
  echo "Готовим чистое сопряжение (джойстик: зажми PS + Share ~5 сек, быстрые двойные вспышки)..."
  bluetoothctl -- remove "$JOYSTICK_MAC" >/dev/null 2>&1
  sleep 1

  timeout 35 bluetoothctl -- scan on >/dev/null 2>&1 &
  SCAN=$!
  found=0
  for i in $(seq 1 30); do
    sleep 1
    bluetoothctl -- devices 2>/dev/null | grep -qi "$JOYSTICK_MAC" && { found=1; break; }
    [ $((i % 5)) -eq 0 ] && echo "  ждём... ($i/30)"
  done
  kill $SCAN 2>/dev/null
  bluetoothctl -- scan off >/dev/null 2>&1
  sleep 1
  [ $found -eq 1 ] || { echo "ОШИБКА: джойстик не найден за 30 сек — проверь режим сопряжения."; exit 1; }

  echo "pair/trust/connect в ОДНОЙ сессии bluetoothctl (агент зарегистрирован на всю операцию)..."
  # Критично: DS4 требует, чтобы host-агент (NoInputNoOutput) принимал SSP-подтверждения
  # в момент pair. Отдельные `bluetoothctl -- pair` запускают агента в мёртвом процессе ->
  # pairing "успешен", но link key не сохраняется -> Bonded: no -> ядро отклоняет HIDP
  # ("Rejected connection from !bonded device"), /dev/input/js* не появляется.
  FIFO=$(mktemp -u); mkfifo "$FIFO"
  bluetoothctl < "$FIFO" > /tmp/ps4_bt_out.$$ 2>&1 &
  BTC=$!
  exec 7>"$FIFO"
  printf 'agent NoInputNoOutput\n' >&7; sleep 1
  printf 'default-agent\n'         >&7; sleep 1
  printf 'pair %s\n' "$JOYSTICK_MAC" >&7
  for i in $(seq 1 30); do sleep 1; grep -qiE "successful|failed" /tmp/ps4_bt_out.$$ && break; done
  grep -iE "pairing (successful|failed)" /tmp/ps4_bt_out.$$ | sed 's/^/  /'
  printf 'trust %s\n' "$JOYSTICK_MAC" >&7; sleep 1
  printf 'connect %s\n' "$JOYSTICK_MAC" >&7
  for i in $(seq 1 20); do sleep 1; grep -qiE "Connection (successful|failed)|org.bluez.Error" /tmp/ps4_bt_out.$$ && break; done
  grep -iE "connection successful|failed to connect|org.bluez.Error" /tmp/ps4_bt_out.$$ | sed 's/^/  /'
  printf 'quit\n' >&7
  exec 7>&-; wait $BTC 2>/dev/null; rm -f "$FIFO" /tmp/ps4_bt_out.$$
  sleep 2

  [ "$(st Bonded)" = "yes" ] || echo "⚠️  Bonded=$(st Bonded) — без ключа пары HIDP не пустит; перепусти скрипт при включённом в режим сопряжения джойстике."
fi

echo "Статус: Paired=$(st Paired) Bonded=$(st Bonded) Connected=$(st Connected) Trusted=$(st Trusted) ServicesResolved=$(st ServicesResolved)"

# --- 4. устройства ввода для контейнера ---
if ls /dev/input/js* >/dev/null 2>&1 || ls /dev/hidraw* >/dev/null 2>&1; then
  ls -l /dev/input/js* /dev/hidraw* 2>/dev/null | sed 's/^/  /'
  echo "=== Готово. Внутри контейнера: ros2 launch rds_2p_joystick ps4_joystick.launch.py ==="
  exit 0
fi

# HID не резолвится обычно из-за занятого другим хостом геймпада или неаккуратного бонда.
echo "⚠️  /dev/input/js* нет — HID-профиль не поднялся. Частые причины:"
echo "   1) джойстик тянет к себе другой хост (ноутбук) — выключи BT там, затем:"
echo "      bluetoothctl -- disconnect $JOYSTICK_MAC; sleep 1; bluetoothctl -- connect $JOYSTICK_MAC"
echo "   2) бонд битый — перезапусти этот скрипт (он делает полный remove->pair)."
exit 1
