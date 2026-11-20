[app]

# 应用名称与包名（package.name 必须全小写、无空格）
title = 远程开关灯
package.name = remotelight
package.domain = org.example

source.dir = .
source.include_exts = py

version = 1.0

# 依赖：kivy(界面) + paho-mqtt(MQTT) + pyjnius(蓝牙) + android(权限)
requirements = python3,kivy,paho-mqtt,pyjnius,android

orientation = portrait
fullscreen = 0

# 蓝牙 + 网络权限（Android 12+ 需要 BLUETOOTH_SCAN / BLUETOOTH_CONNECT）
android.permissions = INTERNET, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE, BLUETOOTH, BLUETOOTH_ADMIN, BLUETOOTH_SCAN, BLUETOOTH_CONNECT, ACCESS_FINE_LOCATION

# 架构：优先 arm64，兼容老设备可加 armeabi-v7a
android.archs = arm64-v8a, armeabi-v7a
android.api = 34
android.minapi = 21
android.accept_sdk_license = True

# 让蓝牙扫描能发现设备
android.allow_backup = True

[buildozer]

log_level = 2
warn_on_root = 1
