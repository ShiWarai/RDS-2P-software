#!/usr/bin/env bash
#
# Переподключение Bluetooth-джойстика PS4 (DualShock 4).
# МЕТОДИКА ПРОВЕРЕННАЯ (как на OrangePi 5 Pro): каждый запуск — полное
# перепаривание с удалением старого сопряжения. DS4 (054C:09CC) после
# disconnect/ребута сам НЕ переподключается стабильно (bluez#488:
# "Connection refused - security block" -> "Authentication Failure"),
# поэтому полагаемся только на свежую пару, а не на авто-реконнект.
#
# Режимы (авто-детект):
#  • classic — ядро с рабочим HIDP (OrangePi 5 Pro и т.п.): pair -> trust ->
#    connect, HID цепляет ядро; успех = ServicesResolved + живой /dev/input/js0.
#  • ds4drv  — ядро без HIDP-сокетов (RepkaPi/H6 и др.): HID забирает демон
#    ds4drv (L2CAP+uinput -> js0). Нюанс: с выключенным плагином input bluez
#    НЕ пишет [LinkKey] на диск, поэтому на время ПАРЫ плагин включается
#    (ключ сохраняется), затем снова выключается (иначе bluez рвёт ACL неудачным
#    HIDP), а ds4drv подхватывает геймпад по ACL. MAC пишется в /etc/default/ds4drv.
#
# Запуск из программы: stdin не читает; sudo не интерактивный (-n); вывод в лог;
# все вызовы под timeout; flock от параллельных запусков.
# Коды: 0 успех (живой js0); 1 не поднялось; 2 окружение; 3 уже запущен.
# Надпись "Сканируем" = пора жать PS+Share (быстрые двойные вспышки).
#
# Использование: ./ps4_bt_reconnect.sh [MAC]
set -uo pipefail

JOYSTICK_MAC="${1:-70:20:84:5E:7C:F8}"
SCAN_SECONDS="${SCAN_SECONDS:-60}"
UNIT=/etc/systemd/system/bluetooth.service.d/noplugin-input.conf
LOCK=/run/lock/ps4_bt_reconnect.lock

LOG_FILE="${LOG_FILE:-/var/log/ps4_bt_reconnect.log}"
touch "$LOG_FILE" 2>/dev/null || LOG_FILE=/tmp/ps4_bt_reconnect.log
exec > >(tee -a "$LOG_FILE") 2>&1
echo ""
echo "########## $(date '+%F %T') запуск, MAC=$JOYSTICK_MAC ##########"

exec 9>"$LOCK" 2>/dev/null || true
if ! flock -n 9 2>/dev/null; then echo "Другой экземпляр уже работает — выход."; exit 3; fi

if [ "$(id -u)" -ne 0 ]; then
  command -v sudo >/dev/null || { echo "Нужен root."; exit 2; }
  exec sudo -n "$0" "$@" 2>/dev/null || { echo "Нужен root (или sudo NOPASSWD)."; exit 2; }
fi
command -v bluetoothctl >/dev/null || { echo "ОШИБКА: нет bluez (apt-get install -y bluez)."; exit 2; }

banner() { echo ""; echo "=========================================="; echo "$@"; echo "=========================================="; }
st() { timeout 8 bluetoothctl -- info "$JOYSTICK_MAC" 2>/dev/null | grep -E "^[[:space:]]*$1:" | awk '{print $2}'; }

hidp_socket_ok() {
  python3 -c "
import socket
try:
    s=socket.socket(31,5,6); s.close(); exit(0)
except OSError:
    exit(1)" 2>/dev/null
}

# идемпотентно: рестарт bluetooth ТОЛЬКО если состояние реально меняется
input_plugin_off() {
  [ -f "$UNIT" ] && return 0
  mkdir -p "$(dirname "$UNIT")"
  printf '[Service]\nExecStart=\nExecStart=/usr/libexec/bluetooth/bluetoothd -p input\n' > "$UNIT"
  systemctl daemon-reload; systemctl restart bluetooth; sleep 2
  timeout 8 bluetoothctl -- power on >/dev/null 2>&1
}
input_plugin_on() {
  [ -f "$UNIT" ] || return 0
  rm -f "$UNIT"
  systemctl daemon-reload; systemctl restart bluetooth; sleep 2
  timeout 8 bluetoothctl -- power on >/dev/null 2>&1
}

register_ds4_mac() {
  [ -f /etc/systemd/system/ds4drv.service ] || return 0
  local f=/etc/default/ds4drv line cur
  mkdir -p /etc/default 2>/dev/null; touch "$f" 2>/dev/null || return 0
  line=$(grep '^DS4_MACS=' "$f" | tail -1); cur=$(printf '%s' "${line#DS4_MACS=}" | tr -d '"')
  case " $cur " in *" $JOYSTICK_MAC "*) return 0;; esac
  cur="${cur:+$cur }$JOYSTICK_MAC"
  grep -q '^DS4_MACS=' "$f" && sed -i "s/^DS4_MACS=.*/DS4_MACS=$cur/" "$f" || echo "DS4_MACS=$cur" >> "$f"
  echo "MAC зарегистрирован в $f."
}

js_live() { # $1 = секунд; живые (не-init) события на js0
  python3 -c "
import os,struct,time,select
try: fd=os.open('/dev/input/js0',os.O_RDONLY|os.O_NONBLOCK)
except OSError: exit(1)
t0=time.time(); n=0
while time.time()-t0<${1:-5}:
    r,_,_=select.select([fd],[],[],0.3)
    if not r: continue
    try: d=os.read(fd,8)
    except BlockingIOError: continue
    if len(d)==8:
        v,e,num=struct.unpack('<IhBB',d)[1:]
        if not e&0x80: n+=1
exit(0 if n>30 else 1)" 2>/dev/null
}

# --- окружение ---
banner "Переподключение джойстика $JOYSTICK_MAC"
if ! systemctl is-active --quiet bluetooth; then
  echo "Запускаем Bluetooth сервис..."; systemctl enable --now bluetooth; sleep 2
fi
timeout 8 bluetoothctl -- power on >/dev/null 2>&1; sleep 1
timeout 8 bluetoothctl -- show >/dev/null 2>&1 || { echo "ОШИБКА: BT-адаптер не отвечает."; exit 2; }

if hidp_socket_ok || { modprobe hidp 2>/dev/null && hidp_socket_ok; }; then
  MODE=classic
  [ -f /etc/modules-load.d/rds2p-bt-hid.conf ] || echo hidp > /etc/modules-load.d/rds2p-bt-hid.conf
  echo "Режим: kernel HIDP (классический)"
else
  MODE=ds4drv
  echo "Режим: userspace ds4drv (kernel HIDP недоступен)"
  command -v ds4drv >/dev/null || echo "⚠️  ds4drv не установлен — см. docker/host/ds4drv.service"
fi

# --- для ds4drv: на время ПАРЫ включить input-плагин, чтобы bluez сохранил ключ ---
[ "$MODE" = ds4drv ] && input_plugin_on

# --- ритуал: power off -> remove -> power on со сканом -> pair -> trust -> connect ---
# Окно гонки закрыто: адаптер тушат ПЕРЕД remove (входящие звонки геймпада не успевают
# пересоздать объект), скан держат включённым до конца пары (мигающий DS4 входящие
# страницы не шлёт — pair идёт только исходящим).
echo "Гасим адаптер, удаляем старое сопряжение..."
timeout 8 bluetoothctl -- power off >/dev/null 2>&1
sleep 1
timeout 8 bluetoothctl -- remove "$JOYSTICK_MAC" >/dev/null 2>&1
sleep 1
timeout 8 bluetoothctl -- power on >/dev/null 2>&1; sleep 1

echo "Сканируем (до ${SCAN_SECONDS}с)... ЗАЖМИТЕ PS+Share (быстрые двойные вспышки) и держите мигающим до 'Pairing successful'."
timeout $((SCAN_SECONDS + 90)) bluetoothctl -- scan on >/dev/null 2>&1 &
SCAN=$!
DEVICE_FOUND=0
for i in $(seq 1 "$SCAN_SECONDS"); do
  sleep 1
  timeout 8 bluetoothctl -- devices 2>/dev/null | grep -qi "$JOYSTICK_MAC" && { DEVICE_FOUND=1; echo "Устройство обнаружено!"; break; }
  [ $((i % 10)) -eq 0 ] && echo "  Ожидание... ($i/$SCAN_SECONDS)"
done
if [ "$DEVICE_FOUND" -eq 0 ]; then
  kill $SCAN 2>/dev/null; timeout 8 bluetoothctl -- scan off >/dev/null 2>&1
  [ "$MODE" = ds4drv ] && input_plugin_off
  banner "ОШИБКА: устройство не найдено за ${SCAN_SECONDS} секунд."
  echo "1. Геймпад был ВЫКЛЮЧЕН на старте, теперь в режиме сопряжения (PS+Share)"
  echo "2. Геймпад рядом с платой"
  exit 1
fi

echo "Агент + pair -> trust -> connect в одной сессии bluetoothctl..."
FIFO=$(mktemp -u); mkfifo "$FIFO"
timeout $((SCAN_SECONDS + 90)) bluetoothctl < "$FIFO" > "/tmp/ps4_pair.$$" 2>&1 &
BTC=$!
exec 7>"$FIFO"
printf 'agent NoInputNoOutput\n' >&7; sleep 1
printf 'default-agent\n'         >&7; sleep 1

# гонка с авто-звонком геймпада: pair может вернуться AlreadyExists (синьий уже
# начал сопряжение по ВХОДЯЩЕМУ соединению) — снимаем объект и повторяем.
PAIR_OK=0
for attempt in 1 2 3 4; do
  off=$(stat -c%s "/tmp/ps4_pair.$$" 2>/dev/null || echo 0)
  printf 'pair %s\n' "$JOYSTICK_MAC" >&7
  res=""
  for i in $(seq 1 20); do
    sleep 1
    res=$(tail -c +$((off+1)) "/tmp/ps4_pair.$$" | grep -iaE "pairing successful|failed to pair" | tail -1)
    [ -n "$res" ] && break
  done
  case "$res" in
    *successful*) echo "  Pairing successful (попытка $attempt)"; PAIR_OK=1; break;;
    *AlreadyExists*) echo "  AlreadyExists — снимаю объект, жду 4с, пара заново ($attempt)"
      printf 'remove %s\n' "$JOYSTICK_MAC" >&7; sleep 4;;
    *failed*) echo "  ${res}"; sleep 2;;
    *) echo "  pair без ответа ($attempt) — снимаю объект и жду 4с"
      printf 'remove %s\n' "$JOYSTICK_MAC" >&7; sleep 4;;
  esac
done

printf 'trust %s\n' "$JOYSTICK_MAC" >&7; sleep 1
# connect: при InProgress/busy (сессия ещё крутится) — просто подождать и повторять
CONN_OK=0
for attempt in 1 2 3 4 5; do
  off=$(stat -c%s "/tmp/ps4_pair.$$" 2>/dev/null || echo 0)
  printf 'connect %s\n' "$JOYSTICK_MAC" >&7
  for i in $(seq 1 12); do
    sleep 1
    line=$(tail -c +$((off+1)) "/tmp/ps4_pair.$$" | grep -iaE "connection successful|failed to connect" | tail -1)
    case "$line" in
      *successful*) echo "  Connection successful"; CONN_OK=1; break 2;;
      *"failed to connect"*) break;;
    esac
  done
  echo "  connect не удалось (busy/timeout), жду 6с и повторяю ($attempt)"; sleep 6
done
printf 'quit\n' >&7
exec 7>&-; wait $BTC 2>/dev/null; rm -f "$FIFO" "/tmp/ps4_pair.$$"
kill $SCAN 2>/dev/null; timeout 8 bluetoothctl -- scan off >/dev/null 2>&1
sleep 2
[ "$PAIR_OK" = 1 ] || echo "⚠️  явного Pairing successful не было — смотрю Bonded/поток ниже"

# --- ds4drv: вернуть плагин input в off, зарегистрировать MAC, перезапустить демон ---
if [ "$MODE" = ds4drv ]; then
  if grep -q "^\[LinkKey\]" /var/lib/bluetooth/*/"$JOYSTICK_MAC"/info 2>/dev/null; then
    echo "Ключ сохранён на диск ✓"
  else
    echo "⚠️  Bonded=$(st Bonded) — ключ НЕ на диске (для разовой сессии ок, после ребута снова пара)"
  fi
  register_ds4_mac
  input_plugin_off
  [ "$(st Connected)" = "yes" ] || { timeout 15 bluetoothctl -- connect "$JOYSTICK_MAC" >/dev/null 2>&1 || true; sleep 3; }
  systemctl restart ds4drv 2>/dev/null
else
  for i in $(seq 1 10); do [ "$(st ServicesResolved)" = "yes" ] && break; sleep 1; done
fi

echo ""
echo "Статус устройства:"
echo "  Paired:    $(st Paired)"; echo "  Bonded:    $(st Bonded)"
echo "  Connected: $(st Connected)"; echo "  Trusted:   $(st Trusted)"
[ "$MODE" = classic ] && echo "  ServicesResolved: $(st ServicesResolved)"

# даём ds4drv/ядру время подцепить HID после всех переключений
for i in 1 2 3 4 5 6; do
  js_live 5 && { banner "Успешно! Джойстик подключен и готов к использованию."; echo "В контейнере: ros2 launch rds_2p_joystick ps4_joystick.launch.py"; exit 0; }
  sleep 3
done
banner "ВНИМАНИЕ: спарено, но поток с джойстика не поднялся за ~30с."
echo "Джойстик должен гореть ровно; повторите запуск (PS+Share на скане)."
exit 1
