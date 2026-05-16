#!/bin/sh
xset -dpms
xset s off
xset s noblank

openbox-session &
xrandr --output HDMI-2 --rotate left &
xinput set-prop "wch.cn USB2IIC_CTP_CONTROL" "Coordinate Transformation Matrix" 0 -1 1 1 0 0 0 0 1
exec chromium --kiosk --no-first-run --disable-infobars http://127.0.0.1:8000
