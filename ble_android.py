# -*- coding: utf-8 -*-
"""
安卓蓝牙配网（pyjnius 实现，仅 Android 可用）。

通过 Android 原生 BLE GATT API 连接 ESP32，下发 WiFi/MQTT 配置。
协议与电脑端 remote_light_switch.py 完全一致：

    服务 UUID   : 4fafc201-1fb5-459e-8fcc-c5c9c331914b
    CONFIG UUID : beb5483e-36e1-4688-b7f5-ea07361b26a8   (写，分块累计)
    COMMIT UUID : beb5483e-36e1-4688-b7f5-ea07361b26a9   (写 b"1" 表示应用)
    STATUS UUID : beb5483e-36e1-4688-b7f5-ea07361b26aa   (通知，上报进度)

    配置格式（换行分隔 6 段）：
        ssid\\npassword\\nbroker\\nport\\ncontrol_topic\\nstatus_topic

⚠️ 依赖 pyjnius（buildozer 的 requirements 里已加）。
⚠️ 本模块在 Windows 上无法运行/验证，需在安卓真机调试；
   若 JNI 方法签名报错（NoSuchMethodError / AbstractMethodError），按需微调。
"""

import threading

from jnius import autoclass, cast, PythonJavaClass, java_method, jarray

SERVICE_UUID = "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
CONFIG_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
COMMIT_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a9"
STATUS_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26aa"
CCCD_UUID = "00002902-0000-1000-8000-00805f9b34fb"

GATT_SUCCESS = 0
STATE_CONNECTED = 2
STATE_DISCONNECTED = 0

BluetoothManager = autoclass('android.bluetooth.BluetoothManager')
BluetoothGatt = autoclass('android.bluetooth.BluetoothGatt')
BluetoothGattCharacteristic = autoclass('android.bluetooth.BluetoothGattCharacteristic')
BluetoothGattDescriptor = autoclass('android.bluetooth.BluetoothGattDescriptor')
UUID = autoclass('java.util.UUID')
PythonActivity = autoclass('org.kivy.android.PythonActivity')

CHUNK_SIZE = 20


def _to_byte_array(data: bytes):
    """Python bytes -> Java byte[]"""
    return jarray('b')(list(data))


def _from_java_bytes(data):
    """Java byte[]/bytes -> Python bytes"""
    if data is None:
        return b""
    if isinstance(data, bytes):
        return data
    return bytes(bytearray(list(data)))


class _ScanCallback(PythonJavaClass):
    """BLE 扫描回调。"""
    __javainterfaces__ = ['android/bluetooth/le/ScanCallback']

    def __init__(self, on_found, on_failed):
        super().__init__()
        self._on_found = on_found
        self._on_failed = on_failed

    @java_method('(ILandroid/bluetooth/le/ScanResult;)V')
    def onScanResult(self, callbackType, result):
        device = result.getDevice()
        name = device.getName()
        address = device.getAddress()
        if self._on_found:
            self._on_found(name, address, device)

    @java_method('(I)V')
    def onScanFailed(self, errorCode):
        if self._on_failed:
            self._on_failed(errorCode)


class _GattCallback(PythonJavaClass):
    """GATT 客户端回调，转发给 BleManager。"""
    __javainterfaces__ = ['android/bluetooth/BluetoothGattCallback']

    def __init__(self, manager):
        super().__init__()
        self.manager = manager

    @java_method('(Landroid/bluetooth/BluetoothGatt;II)V')
    def onConnectionStateChange(self, gatt, status, newState):
        self.manager.on_connection_state(gatt, status, newState)

    @java_method('(Landroid/bluetooth/BluetoothGatt;I)V')
    def onServicesDiscovered(self, gatt, status):
        self.manager.on_services_discovered(gatt, status)

    @java_method('(Landroid/bluetooth/BluetoothGatt;Landroid/bluetooth/BluetoothGattCharacteristic;I)V')
    def onCharacteristicWrite(self, gatt, characteristic, status):
        self.manager.on_characteristic_write(gatt, characteristic, status)

    @java_method('(Landroid/bluetooth/BluetoothGatt;Landroid/bluetooth/BluetoothGattCharacteristic;)V')
    def onCharacteristicChanged(self, gatt, characteristic):
        self.manager.on_characteristic_changed(gatt, characteristic)


class BleManager:
    """封装安卓 BLE 扫描与配置下发。所有回调在 Java/Binder 线程触发。"""

    def __init__(self, log_cb=None):
        self.log_cb = log_cb
        self.activity = PythonActivity.mActivity
        self.adapter = self._get_adapter()

        self.scanner = None
        self.scan_callback = None
        self.gatt = None
        self.gatt_callback = None

        # 配置写入状态
        self.config_chunks = []
        self.chunk_index = 0
        self.on_status_cb = None
        self.on_finished_cb = None

    def _log(self, msg):
        if self.log_cb:
            self.log_cb(msg)

    def _get_adapter(self):
        manager = cast(BluetoothManager,
                       self.activity.getSystemService(self.activity.BLUETOOTH_SERVICE))
        return manager.getAdapter()

    # ------------------------------------------------------------------
    # 扫描
    # ------------------------------------------------------------------
    def start_scan(self, on_found, on_finished, timeout=10.0):
        """开始扫描。on_found(name, address, device)，超时后 on_finished()。"""
        self._on_found = on_found
        self._on_finished_scan = on_finished
        self.scan_callback = _ScanCallback(self._handle_found, lambda code: self._log("扫描失败 code=" + str(code)))
        try:
            self.scanner = self.adapter.getBluetoothLeScanner()
            self.scanner.startScan(self.scan_callback)
        except Exception as exc:  # noqa: BLE001
            self._log("无法开始扫描：" + str(exc))
            on_finished()
            return
        threading.Timer(timeout, self.stop_scan).start()

    def _handle_found(self, name, address, device):
        if name and ("esp" in name.lower() or "light" in name.lower()):
            self._on_found(name, address, device)

    def stop_scan(self):
        try:
            if self.scanner and self.scan_callback:
                self.scanner.stopScan(self.scan_callback)
        except Exception:  # noqa: BLE001
            pass
        if self._on_finished_scan:
            self._on_finished_scan()

    # ------------------------------------------------------------------
    # 连接 + 下发配置
    # ------------------------------------------------------------------
    def send_config(self, device, config_str, on_status, on_finished):
        self.on_status_cb = on_status
        self.on_finished_cb = on_finished
        self.config_chunks = [config_str[i:i + CHUNK_SIZE].encode("utf-8")
                              for i in range(0, len(config_str.encode("utf-8")), CHUNK_SIZE)]
        self.chunk_index = 0
        self._log("正在连接 ESP32…")
        self.gatt_callback = _GattCallback(self)
        try:
            self.gatt = device.connectGatt(self.activity, False, self.gatt_callback)
        except Exception as exc:  # noqa: BLE001
            self._log("连接失败：" + str(exc))
            self.on_finished_cb(False)
            return

    # ---- GATT 回调（Java 线程）----
    def on_connection_state(self, gatt, status, newState):
        if newState == STATE_CONNECTED:
            self._log("已连接，正在发现服务…")
            gatt.discoverServices()
        elif newState == STATE_DISCONNECTED:
            self._log("蓝牙已断开")

    def on_services_discovered(self, gatt, status):
        if status != GATT_SUCCESS:
            self._log("服务发现失败 status=" + str(status))
            self.on_finished_cb(False)
            return
        service = gatt.getService(UUID.fromString(SERVICE_UUID))
        if not service:
            self._log("未找到目标服务，请确认 ESP32 已开启配网")
            self.on_finished_cb(False)
            return

        self.config_char = service.getCharacteristic(UUID.fromString(CONFIG_UUID))
        self.commit_char = service.getCharacteristic(UUID.fromString(COMMIT_UUID))
        self.status_char = service.getCharacteristic(UUID.fromString(STATUS_UUID))

        # 开启状态通知
        try:
            gatt.setCharacteristicNotification(self.status_char, True)
            desc = self.status_char.getDescriptor(UUID.fromString(CCCD_UUID))
            if desc is not None:
                desc.setValue(BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE)
                gatt.writeDescriptor(desc)
        except Exception:  # noqa: BLE001
            pass

        self._write_next_chunk()

    def _write_next_chunk(self):
        if self.chunk_index < len(self.config_chunks):
            self.config_char.setValue(_to_byte_array(self.config_chunks[self.chunk_index]))
            self.gatt.writeCharacteristic(self.config_char)
        else:
            self._log("配置写入完成，提交中…")
            self.commit_char.setValue(_to_byte_array(b"1"))
            self.gatt.writeCharacteristic(self.commit_char)

    def on_characteristic_write(self, gatt, characteristic, status):
        if status != GATT_SUCCESS:
            self._log("写入失败 status=" + str(status))
            self.on_finished_cb(False)
            return
        uuid_str = characteristic.getUuid().toString()
        if uuid_str == CONFIG_UUID:
            self.chunk_index += 1
            self._write_next_chunk()
        elif uuid_str == COMMIT_UUID:
            self._log("配置已提交，等待 ESP32 连接 WiFi/MQTT…")
            # 提交成功即视为完成（后续状态经 on_characteristic_changed 上报）
            self.on_finished_cb(True)

    def on_characteristic_changed(self, gatt, characteristic):
        text = _from_java_bytes(characteristic.getValue()).decode("utf-8", errors="ignore").strip()
        if text and self.on_status_cb:
            self.on_status_cb(text)

    def disconnect(self):
        try:
            if self.gatt:
                self.gatt.close()
        except Exception:  # noqa: BLE001
            pass
        self.gatt = None
