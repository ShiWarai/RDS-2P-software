#!/usr/bin/env bash
#
# Одноразовая установка userspace-стека DS4 (ds4drv) для плат, где в ядре
# НЕТ рабочего HIDP (RepkaPi/Allwinner H6 и т.п.: socket(AF_BLUETOOTH,HIDP)
# -> ESOCKTNOSUPPORT). На таких ядрах kernel-HID не поднимается, поэтому HID
# геймпада ведёт userspace-демон ds4drv (L2CAP PSM 17/19 + uinput -> /dev/input/js0),
# а bluez занимается только сопряжением/ACL (с выключенным плагином input,
# иначе он рвёт ACL неудачным HIDP-подключением).
#
# Для плат с рабочим kernel-HIDP (OrangePi 5 Pro) этот скрипт НЕ нужен —
# там достаточно ps4_bt_reconnect.sh (режим classic).
#
# Идемпотентен: можно запускать повторно. После установки:
#   ./ps4_bt_reconnect.sh <MAC>   # сопряжение (держать PS+Share)
#
# Запуск: sudo ./ps4_ds4drv_setup.sh
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Нужен root."; exit 2; }

PYBLUEZ_GIT="git+https://github.com/pybluez/pybluez.git"
DS4DRV_GIT="git+https://github.com/TheDrHax/ds4drv-cemuhook.git"
UNIT=/etc/systemd/system/ds4drv.service
DROPIN=/etc/systemd/system/bluetooth.service.d/noplugin-input.conf

echo "== 1. системные пакеты =="
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-pip libbluetooth-dev git bluez-tools >/dev/null

echo "== 2. PyBluez + ds4drv (python3) =="
python3 -c "import bluetooth" 2>/dev/null || pip3 install --break-system-packages "$PYBLUEZ_GIT" >/dev/null
command -v ds4drv >/dev/null || pip3 install --break-system-packages "$DS4DRV_GIT" >/dev/null

DS4PKG=$(python3 -c "import ds4drv,os;print(os.path.dirname(ds4drv.__file__))")

echo "== 3. патч evdev2 (fn->fd) в $DS4PKG/actions/input.py =="
if grep -q "device.device.fn" "$DS4PKG/actions/input.py"; then
  sed -i "s/device.device.fn/device.device.fd/" "$DS4PKG/actions/input.py"
  echo "  applied"
else
  echo "  уже применён или не требуется"
fi

echo "== 4. патч fast-path (подхват уже установленного ACL) в $DS4PKG/backends/bluetooth.py =="
python3 - "$DS4PKG/backends/bluetooth.py" <<'PY'
import sys
p=sys.argv[1]; s=open(p).read()
if "DS4_MACS" in s:
    print("  уже применён"); sys.exit(0)
anchor='''    def find_device(self):
        """Scan for bluetooth devices and return a DS4 device if found."""
'''
assert anchor in s, "не найден find_device — версия ds4drv отличается"
patch=anchor+'''        # fast-path: геймпад уже подключён (ACL от bluez/по ключу) — не ждём inquiry,
        # а сразу открываем HIDP-каналы. Список MAC — из DS4_MACS (/etc/default/ds4drv).
        # Анти-спам: MAC, уже принятый в работу, не пытаемся подключать повторно
        # (иначе лог забивается ENOTCONN, т.к. DS4 держит одну HID-сессию).
        import os as _os
        _macs = _os.environ.get("DS4_MACS", "").replace(",", " ").split()
        if _macs:
            try:
                _con = subprocess.check_output(["hcitool", "con"]).decode("utf-8", "ignore")
            except Exception:
                _con = ""
            _live = {m for m in _macs if m in _con}
            _ATTACHED = getattr(self.__class__, "_ATTACHED", set())
            _ATTACHED &= _live          # забыть отвалившиеся, чтобы переподхватить
            self.__class__._ATTACHED = _ATTACHED
            for _m in _macs:
                if _m in _live and _m not in _ATTACHED:
                    _ATTACHED.add(_m)
                    self.logger.info("fast-path: уже на связи {0}", _m)
                    return BluetoothDS4Device.connect(_m)
'''
open(p,"w").write(s.replace(anchor, patch))
print("  applied")
PY

echo "== 4b. патч connect(): честный raise + ретраи L2CAP (лечит ENOTCONN на входящем реконнекте) =="
python3 - "$DS4PKG/backends/bluetooth.py" <<'PY'
import sys
p=sys.argv[1]; s=open(p).read()
old='''        try:
            ctl_socket.connect((addr, L2CAP_PSM_HIDP_CTRL))
            int_socket.connect((addr, L2CAP_PSM_HIDP_INTR))
            int_socket.setblocking(False)
        except socket.error as err:
            DeviceError("Failed to connect: {0}".format(err))

        return cls(addr, ctl_socket, int_socket)'''
new='''        import time
        last_err = None
        for _attempt in range(12):
            ctl_socket = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET,
                                       socket.BTPROTO_L2CAP)
            int_socket = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET,
                                       socket.BTPROTO_L2CAP)
            try:
                ctl_socket.settimeout(5)
                ctl_socket.connect((addr, L2CAP_PSM_HIDP_CTRL))
                int_socket.settimeout(5)
                int_socket.connect((addr, L2CAP_PSM_HIDP_INTR))
                int_socket.setblocking(False)
                ctl_socket.settimeout(None)
                return cls(addr, ctl_socket, int_socket)
            except socket.error as err:
                last_err = err
                for sk in (ctl_socket, int_socket):
                    try:
                        sk.close()
                    except Exception:
                        pass
                time.sleep(1.0)
        raise DeviceError("Failed to connect: {0}".format(last_err))'''
if "for _attempt in range(12)" in s:
    print("  уже применён"); sys.exit(0)
assert old in s, "не найден блок connect() — версия ds4drv отличается"
open(p,"w").write(s.replace(old,new))
print("  applied")
PY

echo "== 5. bluez: адаптер вверх при старте (AutoEnable) =="
grep -q "^AutoEnable=true" /etc/bluetooth/main.conf 2>/dev/null || \
  sed -i "s/^#\?AutoEnable=.*/AutoEnable=true/" /etc/bluetooth/main.conf
grep -q "^AutoEnable=true" /etc/bluetooth/main.conf || printf "\n[General]\nAutoEnable=true\n" >> /etc/bluetooth/main.conf

echo "== 6. bluez: выключить input-плагин (HID забирает ds4drv) =="
mkdir -p "$(dirname "$DROPIN")"
printf '[Service]\nExecStart=\nExecStart=/usr/libexec/bluetooth/bluetoothd -p input\n' > "$DROPIN"

echo "== 7. /etc/default/ds4drv (список MAC для fast-path) =="
mkdir -p /etc/default
[ -f /etc/default/ds4drv ] || echo "DS4_MACS=" > /etc/default/ds4drv
echo "  $(cat /etc/default/ds4drv)"

echo "== 8. systemd-юнит ds4drv =="
cat > "$UNIT" <<'U'
[Unit]
Description=DS4 userspace Bluetooth joystick driver (bluez pair + L2CAP HIDP + uinput)
Documentation=file:/etc/default/ds4drv (MAC-список ведёт ps4_bt_reconnect.sh)
After=bluetooth.service
Wants=bluetooth.service

[Service]
ExecStartPre=-/usr/bin/hciconfig hci0 up
EnvironmentFile=-/etc/default/ds4drv
ExecStart=/usr/local/bin/ds4drv
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
U

systemctl daemon-reload
systemctl restart bluetooth
systemctl enable --now ds4drv
sleep 2
echo "== готово =="
echo "  bluetooth: $(systemctl is-active bluetooth)  ds4drv: $(systemctl is-active ds4drv)"
echo "Дальше: ./ps4_bt_reconnect.sh <MAC геймпада>  (держать PS+Share до вспышек)"
