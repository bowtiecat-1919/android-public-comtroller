# 远程开关灯 —— 安卓版

Kivy 编写的安卓 App，功能与电脑端一致：

1. **MQTT 远程控制**：开关灯、查看设备在线状态。
2. **蓝牙配网**：手机连 ESP32 的 BLE，下发 WiFi/MQTT 配置。

## 项目文件

| 文件 | 作用 |
| - | - |
| `main.py` | Kivy 主程序（界面 + MQTT + 配网流程） |
| `ble_android.py` | 安卓蓝牙（pyjnius 实现） |
| `buildozer.spec` | 打包配置 |
| `.github/workflows/build-apk.yml` | GitHub Actions 云端编译 |

## 一、用 GitHub Actions 编译 APK（推荐，本机无需装 Linux）

1. 注册 [GitHub](https://github.com)，点右上角 **+ → New repository**，仓库名随意（如 `remote-light`），设为 **Public**。
2. 把这个 `android` 文件夹里的**全部内容**（`main.py`、`ble_android.py`、`buildozer.spec`、`.github/`、`README_ANDROID.md`）作为仓库根目录上传（可用 GitHub 网页「uploading an existing file」直接拖拽上传）。
3. 上传后自动触发 **Actions**（或点仓库顶部 **Actions → Build Android APK → Run workflow**）。
4. 等约 10–20 分钟（首次要下载 Android SDK/NDK）。
5. 编译完成后，在 **Actions 运行详情页底部** 下载 **Artifacts 里的 `remotelight-apk`**，解压得到 `remotelight-1.0-debug.apk`。
6. 把 APK 发到手机（微信/数据线），**开启「允许安装未知来源」**，点击安装。

## 二、手机上的使用步骤

1. 打开 App，点 **「🔧 蓝牙配网」**。
2. 点 **「扫描设备」**，选择 `ESP32-Light`。
3. 填 WiFi 名称/密码、MQTT 服务器/端口/话题。
4. 点 **「发送并应用」**，看到 `mqtt_ok` 后返回主界面。
5. 主界面显示「设备在线」后，点「开灯/关灯」即可远程控制。

> 前提：ESP32 已烧录 [esp32_ble_provisioning.ino](../esp32_ble_provisioning.ino)。

## 三、蓝牙协议（与 ESP32 固件、电脑端一致）

| 项目 | 值 |
| - | - |
| 设备名 | `ESP32-Light` |
| 服务 UUID | `4fafc201-1fb5-459e-8fcc-c5c9c331914b` |
| CONFIG（写） | `beb5483e-36e1-4688-b7f5-ea07361b26a8` |
| COMMIT（写） | `beb5483e-36e1-4688-b7f5-ea07361b26a9`（写 `1`） |
| STATUS（通知） | `beb5483e-36e1-4688-b7f5-ea07361b26aa` |

配置字符串（换行分隔 6 段）：`ssid\npassword\nbroker\nport\ncontrol_topic\nstatus_topic`

## 四、本地测试 MQTT（可选，不装也能直接用云编译）

电脑上装 kivy 后可跑 MQTT 控制部分（蓝牙配网在电脑上不可用）：

```bash
pip install kivy paho-mqtt
python main.py
```

## ⚠️ 重要说明

- **蓝牙配网（`ble_android.py`）**：用 `pyjnius` 调安卓原生 BLE，**无法在电脑上验证，需真机调试**。若报 `NoSuchMethodError`/`AbstractMethodError` 类错误，通常是 JNI 方法签名需按你的安卓版本微调（集中在 `_ScanCallback` / `_GattCallback` 的 `@java_method` 签名）。
- 手机必须开启**蓝牙**和**定位**（安卓 12+ 蓝牙扫描需要定位权限）。
