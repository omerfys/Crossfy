#!/usr/bin/env bash
# The X11 back ends against a real X server (tools/x11_proof.py says what is proved). Starts
# Xorg with the dummy driver (or Xvfb) on a free display, so it runs headless and never touches
# the desktop it is started from.
# Needs Python 3 and win_app/requirements-linux.txt; PYTHON picks the interpreter.
# Exit status: 0 when every check passes.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
python="${PYTHON:-python3}"

for number in $(seq 90 120); do
    [ -e "/tmp/.X11-unix/X$number" ] || [ -e "/tmp/.X$number-lock" ] || break
done

xorg_bin=""
for candidate in /usr/libexec/Xorg /usr/bin/Xorg Xorg; do
    if command -v "$candidate" >/dev/null 2>&1; then
        for drv in /usr/lib64/xorg/modules/drivers/dummy_drv.so /usr/lib/xorg/modules/drivers/dummy_drv.so; do
            if [ -f "$drv" ]; then
                xorg_bin="$candidate"
                break 2
            fi
        done
    fi
done

if [ -n "$xorg_bin" ]; then
    conf="$(mktemp -t xorg-dummy-XXXXXX.conf)"
    log="$(mktemp -t xorg-dummy-XXXXXX.log)"
    cat << "EOF" > "$conf"
Section "ServerFlags"
    Option "AutoAddDevices" "false"
    Option "AutoEnableDevices" "false"
EndSection

Section "Device"
    Identifier "DummyDevice"
    Driver "dummy"
    VideoRam 256000
EndSection

Section "Monitor"
    Identifier "DummyMonitor0"
    HorizSync 30.0-130.0
    VertRefresh 50.0-150.0
EndSection

Section "Screen"
    Identifier "DummyScreen"
    Device "DummyDevice"
    Monitor "DummyMonitor0"
    DefaultDepth 24
    SubSection "Display"
        Viewport 0 0
        Depth 24
        Modes "1920x1080"
    EndSubSection
EndSection

Section "InputDevice"
    Identifier "DummyPointer"
    Driver "inputtest"
EndSection

Section "InputDevice"
    Identifier "DummyKeyboard"
    Driver "inputtest"
EndSection

Section "ServerLayout"
    Identifier "DummyLayout"
    Screen 0 "DummyScreen"
    InputDevice "DummyPointer" "CorePointer"
    InputDevice "DummyKeyboard" "CoreKeyboard"
EndSection
EOF
    "$xorg_bin" ":$number" -config "$conf" -logfile "$log" -noreset >/dev/null 2>&1 &
    server=$!
    trap 'kill "$server" 2>/dev/null || true; rm -f "$conf" "$log" 2>/dev/null || true' EXIT
    for _ in $(seq 50); do
        [ -e "/tmp/.X11-unix/X$number" ] && break
        sleep 0.1
    done
    # Two RandR outputs with 960x1080 resolution side by side
    DISPLAY=":$number" xrandr --newmode "960x1080" 86.94 960 1024 1128 1296 1080 1081 1084 1118 -HSync +Vsync >/dev/null 2>&1 || true
    DISPLAY=":$number" xrandr --addmode DUMMY0 960x1080 >/dev/null 2>&1 || true
    DISPLAY=":$number" xrandr --addmode DUMMY1 960x1080 >/dev/null 2>&1 || true
    DISPLAY=":$number" xrandr --output DUMMY0 --mode 960x1080 --pos 0x0 --output DUMMY1 --mode 960x1080 --pos 960x0 >/dev/null 2>&1 || true
else
    command -v Xvfb >/dev/null || { echo "Neither Xorg with dummy driver nor Xvfb is installed" >&2; exit 2; }
    Xvfb ":$number" -screen 0 1920x1080x24 -nolisten tcp >/dev/null 2>&1 &
    server=$!
    trap 'kill "$server" 2>/dev/null || true' EXIT
    for _ in $(seq 50); do
        [ -e "/tmp/.X11-unix/X$number" ] && break
        sleep 0.1
    done
    # RandR 1.5 monitor objects give the seam proof two logical displays on one X screen.
    DISPLAY=":$number" xrandr --setmonitor A 960/254x1080/286+0+0 none >/dev/null 2>&1 || true
    DISPLAY=":$number" xrandr --setmonitor B 960/254x1080/286+960+0 none >/dev/null 2>&1 || true
fi

unset WAYLAND_DISPLAY
DISPLAY=":$number" XDG_SESSION_TYPE=x11 "$python" "$here/x11_proof.py"
