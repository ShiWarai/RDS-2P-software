#!/usr/bin/env bash
#
# Одноразовая установка userspace-стека DS4 (ds4drv) для плат, где в ядре
# НЕТ рабочего HIDP (RepkaPi/Allwinner H6 и т.п.: socket(AF_BLUETOOTH,HIDP)
# -> ESOCKTNOSUPPORT). На таких ядрах kernel-HID не поднимается, поэтому HID
# геймпада ведёт userspace-демон ds4drv (L2CAP PSM 17/19 + uinput -> /dev/input/js0),
# а bluez занимается только сопряжением/ACL (с выключенным плагином input,
# иначе он рвёт ACL неудачным HIDP-подключением).
#
# Тачпад на таких ядрах работает через DSU-поток: ds4drv запускается с --udp
# (127.0.0.1:26760), а ps4_touchpad_node.py читает его UDP-fallback'ом
# (hidraw-путь недоступен без kernel-HID).
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

echo "== 4c. патч read_report: чтение обоих сокетов + приём 0x01 + запрос 0x11 (RepkaPi) =="
python3 - "$DS4PKG/backends/bluetooth.py" <<'PY'
import sys, py_compile
p=sys.argv[1]; s=open(p).read()
if "RDS-2P trio" in s:
    print("  уже применён"); sys.exit(0)
if "zero_copy_slice" not in s.split("def ")[0]:
    s=s.replace("from ..device import DS4Device",
                "from ..device import DS4Device\nfrom ..utils import zero_copy_slice",1)
lines=s.splitlines(keepends=True)
st=next(i for i,l in enumerate(lines) if l.startswith("    def read_report(self):"))
en=st+1
while en<len(lines) and (not lines[en].strip() or lines[en].startswith("        ")):
    en+=1
new_fn=r'''    def read_report(self):
        # RDS-2P trio: читаем оба сокета (геймпад на этом стеке шлёт в PSM-17/ctl);
        # 0x01 (basic) отображаем в расширенный layout и параллельно просим pad
        # перейти в 0x11 (GET feature 0x02/0x05, как это делает ядро Linux).
        import time as _time
        if getattr(self, "ctl_sock", None) is not None and self.ctl_sock.gettimeout() is None:
            try:
                self.ctl_sock.setblocking(False)
            except OSError:
                pass
        for sock in (self.int_sock, self.ctl_sock):
            try:
                ret = sock.recv_into(self.buf)
            except (IOError, OSError):
                continue
            if ret == 0:
                return
            if ret >= REPORT_SIZE and self.buf[1] == REPORT_ID:
                buf = zero_copy_slice(self.buf, 3)
                return self.parse_report(buf)
            if ret >= 11 and self.buf[0] == 0xA1 and self.buf[1] == 0x01:
                now = _time.time()
                if now - getattr(self, "_last01req", 0.0) > 2.0:
                    self._last01req = now
                    try:
                        self.ctl_sock.sendall(b"\x43\x02")
                        self.ctl_sock.sendall(b"\x43\x05")
                    except OSError:
                        pass
                synth = bytearray(76)
                synth[1] = self.buf[2]
                synth[2] = self.buf[3]
                synth[3] = self.buf[4]
                synth[4] = self.buf[5]
                synth[5] = self.buf[6]
                synth[6] = self.buf[7]
                synth[7] = self.buf[8]
                synth[35] = 0x80
                synth[39] = 0x80
                return self.parse_report(synth)
        return False
'''
lines[st:en]=[new_fn]
open(p,"w").write("".join(lines))
py_compile.compile(p, doraise=True)
print("  applied")
PY

echo "== 4d. патч __main__: ctl-watcher + слив на setup + таймер-пинки геймпада (RepkaPi) =="
python3 - "$DS4PKG/__main__.py" <<'PY'
import sys, py_compile
p=sys.argv[1]; s=open(p).read()
changed=False
anchor="        self.loop.add_watcher(device.report_fd, self.read_report)"
if "ctl_sock.fileno()" not in s:
    assert anchor in s, "не найден якорь watcher в __main__.py"
    s=s.replace(anchor, anchor+'''
        if getattr(device, "ctl_sock", None) is not None:
            self.loop.add_watcher(device.ctl_sock.fileno(), self.read_report)''',1)
    changed=True
a2='''        if getattr(device, "ctl_sock", None) is not None:
            self.loop.add_watcher(device.ctl_sock.fileno(), self.read_report)'''
if "RDS-2P: слить" not in s:
    s=s.replace(a2, a2+'''
        self.read_report()  # RDS-2P: слить уже накопленное в сокетах до регистрации''',1)
    changed=True
a3='''        self.read_report()  # RDS-2P: слить уже накопленное в сокетах до регистрации'''
if "RDS-2P: пинок" not in s:
    poke=r'''
        if getattr(device, "ctl_sock", None) is not None:
            def _rds_poke():
                # RDS-2P: пинок HID-стека геймпада (как делает ядро Linux):
                # REPORT-протокол + GET feature 0x02/0x05 + idle -> переход
                # в расширенный поток 0x11; set_led — хост-активность и индикация.
                for _msg in (b"\x71", b"\x43\x02", b"\x43\x05", b"\x20\x00\x00"):
                    try:
                        device.ctl_sock.sendall(_msg)
                    except OSError:
                        pass
                try:
                    device.set_led(0, 0, 255)
                except Exception:
                    pass
                return True
            self.loop.create_timer(4, _rds_poke).start()'''
    s=s.replace(a3, a3+poke,1)
    changed=True
if changed:
    open(p,"w").write(s)
    py_compile.compile(p, doraise=True)
    print("  applied")
else:
    print("  уже применён")
PY

echo "== 4e. патч стойкости: cleanup снимает ctl-watcher + терпимый epoll.unregister =="
python3 - "$DS4PKG/__main__.py" "$DS4PKG/eventloop.py" <<'PY'
import sys, py_compile
main_p, loop_p = sys.argv[1], sys.argv[2]
s = open(main_p).read()
main_old = '        self.loop.remove_watcher(self.device.report_fd)'
main_new = '''        self.loop.remove_watcher(self.device.report_fd)
        if getattr(self.device, "ctl_sock", None) is not None:
            self.loop.remove_watcher(self.device.ctl_sock.fileno())'''
if main_new in s:
    print("  __main__: уже применён")
else:
    assert main_old in s, "не найден remove_watcher(report_fd) в cleanup_device"
    open(main_p, "w").write(s.replace(main_old, main_new, 1))
    print("  __main__: applied")
e = open(loop_p).read()
loop_old = '''        self.callbacks.pop(fd, None)
        self.epoll.unregister(fd)'''
loop_new = '''        self.callbacks.pop(fd, None)
        try:
            self.epoll.unregister(fd)
        except OSError:
            pass'''
if "except OSError:" in e.split("def remove_watcher")[1].split("def ")[0]:
    print("  eventloop: уже применён")
else:
    assert loop_old in e, "не найден unregister в remove_watcher"
    open(loop_p, "w").write(e.replace(loop_old, loop_new, 1))
    print("  eventloop: applied")
py_compile.compile(main_p, doraise=True)
py_compile.compile(loop_p, doraise=True)
print("  compile OK")
PY

echo "== 5. bluez: адаптер вверх при старте (AutoEnable) =="
grep -q "^AutoEnable=true" /etc/bluetooth/main.conf 2>/dev/null || \
  sed -i "s/^#\?AutoEnable=.*/AutoEnable=true/" /etc/bluetooth/main.conf
grep -q "^AutoEnable=true" /etc/bluetooth/main.conf || printf "\n[General]\nAutoEnable=true\n" >> /etc/bluetooth/main.conf

echo "== 6. bluez: выключить input-плагин (HID забирает ds4drv) =="
mkdir -p "$(dirname "$DROPIN")"
# -P input (noplugin!) — именно выключение; с -p bluez наоборот ЗАГРУЖАЕТ
# input-плагин, слушает PSM 17/19 и после ребута платы перехватывает HID геймпада.
printf '[Service]\nExecStart=\nExecStart=/usr/libexec/bluetooth/bluetoothd -P input\n' > "$DROPIN"

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
# --udp: DSU-сервер (127.0.0.1:26760) — ps4_touchpad_node читает из него тачпад
# (fallback, когда на ядре без HIDP нет /dev/hidraw)
ExecStart=/usr/local/bin/ds4drv --udp
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
