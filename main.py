# -*- coding: utf-8 -*-
"""
远程开关灯 —— 安卓版（Kivy）

功能：
  1. MQTT 远程控制：开关灯、查看设备在线状态（与电脑端/ESP32 协议一致）。
  2. 蓝牙配网：手机连 ESP32 的 BLE，下发「WiFi 名称/密码 + MQTT 服务器/端口/话题」。

MQTT 协议默认：
    服务器 : broker.hivemq.com:1883
    命令话题 : lightdemo/control   (发布 on / off)
    状态话题 : lightdemo/status    (订阅 online / offline)

⚠️ BLE 部分依赖 pyjnius（仅安卓），在电脑上运行本 App 时蓝牙配网不可用，
   MQTT 控制仍可在电脑上（装 kivy 后）测试。
"""

import threading

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen, ScreenManager
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.utils import get_color_from_hex

import paho.mqtt.client as mqtt

# 尝试导入安卓 BLE（仅安卓可用）
try:
    from ble_android import BleManager
    HAS_BLE = True
except Exception:  # noqa: BLE001
    HAS_BLE = False
    BleManager = None

# ==================== 默认配置 ====================
DEFAULT_BROKER = "broker.hivemq.com"
DEFAULT_PORT = 1883
DEFAULT_TOPIC_CONTROL = "lightdemo/control"
DEFAULT_TOPIC_STATUS = "lightdemo/status"

C_GREEN = (0.13, 0.77, 0.37, 1)
C_RED = (0.94, 0.27, 0.27, 1)
C_AMBER = (0.96, 0.62, 0.04, 1)
C_GRAY = (0.61, 0.64, 0.69, 1)
C_BLUE = (0.23, 0.51, 0.96, 1)
C_BULB_ON = (1.0, 0.79, 0.24, 1)
C_BULB_OFF = (0.84, 0.85, 0.88, 1)


class Bulb(Widget):
    """灯泡指示（圆 + 底座）。"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.on = False
        self.size_hint_y = None
        self.height = dp(170)
        self.bind(size=self._redraw, pos=self._redraw)
        self._redraw()

    def set_on(self, on):
        self.on = bool(on)
        self._redraw()

    def _redraw(self, *args):
        self.canvas.clear()
        cx, cy = self.center_x, self.center_y
        r = min(self.width, self.height) * 0.32
        with self.canvas:
            # 灯泡
            Color(*(C_BULB_ON if self.on else C_BULB_OFF))
            Ellipse(pos=(cx - r, cy - r * 0.3), size=(2 * r, 2 * r))
            # 底座
            Color(0.60, 0.63, 0.68, 1)
            Rectangle(pos=(cx - r * 0.32, cy - r * 0.9), size=(r * 0.64, r * 0.5))


class ControlScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.app = None

        root = BoxLayout(orientation="vertical", padding=dp(20), spacing=dp(10))

        # 标题
        root.add_widget(Label(text="远程开关灯", font_size=dp(26), bold=True,
                              size_hint_y=None, height=dp(44), color=(0.12, 0.16, 0.22, 1)))

        # 灯泡
        self.bulb = Bulb()
        root.add_widget(self.bulb)

        # 状态文字
        self.state_label = Label(text="当前：未知", font_size=dp(18),
                                 color=C_GRAY, size_hint_y=None, height=dp(30))
        root.add_widget(self.state_label)

        # 开关按钮
        self.toggle_btn = Button(text="开 灯", font_size=dp(20), bold=True,
                                 background_normal="", background_color=C_GREEN,
                                 size_hint_y=None, height=dp(60))
        self.toggle_btn.bind(on_release=self.on_toggle)
        root.add_widget(self.toggle_btn)

        # 状态行
        self.dev_label = Label(text="设备：未知", font_size=dp(15), color=C_GRAY,
                               size_hint_y=None, height=dp(26))
        self.srv_label = Label(text="服务器：连接中…", font_size=dp(15), color=C_AMBER,
                               size_hint_y=None, height=dp(26))
        root.add_widget(self.dev_label)
        root.add_widget(self.srv_label)

        # 蓝牙配网按钮
        self.provision_btn = Button(text="🔧 蓝牙配网（设置 WiFi / MQTT）", font_size=dp(15),
                                    background_normal="", background_color=C_BLUE,
                                    size_hint_y=None, height=dp(52))
        self.provision_btn.bind(on_release=self.open_provision)
        root.add_widget(self.provision_btn)

        self.add_widget(root)

    def on_enter(self, *args):
        self.app = App.get_running_app()

    def open_provision(self, *args):
        App.get_running_app().sm.current = "provision"

    def on_toggle(self, *args):
        app = App.get_running_app()
        app.toggle_light()


class ProvisionScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        root = BoxLayout(orientation="vertical", padding=dp(20), spacing=dp(8))

        # 顶部：返回 + 扫描
        top = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(52), spacing=dp(10))
        back = Button(text="‹ 返回", size_hint_x=0.4, background_normal="", background_color=C_GRAY)
        back.bind(on_release=lambda *a: setattr(App.get_running_app().sm, "current", "control"))
        self.scan_btn = Button(text="扫描设备", size_hint_x=0.6, background_normal="",
                               background_color=C_BLUE)
        self.scan_btn.bind(on_release=self.do_scan)
        top.add_widget(back)
        top.add_widget(self.scan_btn)
        root.add_widget(top)

        # 设备选择
        self.device_spinner = Spinner(text="选择 ESP32 设备", values=[], size_hint_y=None,
                                      height=dp(48))
        root.add_widget(self.device_spinner)

        # 配置字段
        self.fields = {}
        for key, hint, pwd in [
            ("ssid", "WiFi 名称 (SSID)", False),
            ("password", "WiFi 密码", True),
            ("broker", "MQTT 服务器", False),
            ("port", "MQTT 端口", False),
            ("control", "命令话题", False),
            ("status", "状态话题", False),
        ]:
            ti = TextInput(hint_text=hint, multiline=False, password=pwd, size_hint_y=None,
                           height=dp(44), font_size=dp(15))
            self.fields[key] = ti
            root.add_widget(ti)
        self.fields["broker"].text = DEFAULT_BROKER
        self.fields["port"].text = str(DEFAULT_PORT)
        self.fields["control"].text = DEFAULT_TOPIC_CONTROL
        self.fields["status"].text = DEFAULT_TOPIC_STATUS

        # 发送按钮
        self.send_btn = Button(text="发送并应用", font_size=dp(17), bold=True,
                               background_normal="", background_color=C_GREEN,
                               size_hint_y=None, height=dp(56))
        self.send_btn.bind(on_release=self.do_send)
        root.add_widget(self.send_btn)

        # 状态
        self.status_label = Label(text="请先扫描并选择设备", font_size=dp(13), color=C_GRAY,
                                  size_hint_y=None, height=dp(60), text_size=(None, None))
        root.add_widget(self.status_label)

        self.add_widget(root)
        self.scan_results = []  # [(name, address, device)]

    def set_status(self, text):
        self.status_label.text = text

    def do_scan(self, *args):
        app = App.get_running_app()
        if not HAS_BLE:
            self.set_status("本机不支持蓝牙配网（需在安卓真机上运行）")
            return
        self.scan_btn.disabled = True
        self.set_status("正在扫描…")
        app.ble_scan(self._on_found, self._on_scan_done)

    def _on_found(self, name, address, device):
        Clock.schedule_once(lambda dt: self._add_device(name, address, device), 0)

    def _add_device(self, name, address, device):
        self.scan_results.append((name, address, device))
        self.device_spinner.values = ["%s (%s)" % (n, a) for n, a, d in self.scan_results]
        if len(self.scan_results) == 1:
            self.device_spinner.text = "%s (%s)" % (name, address)

    def _on_scan_done(self):
        Clock.schedule_once(lambda dt: self._finish_scan(), 0)

    def _finish_scan(self):
        self.scan_btn.disabled = False
        if not self.scan_results:
            self.set_status("未发现设备，请确认 ESP32 已上电、蓝牙已开启")
        else:
            self.set_status("发现 %d 个设备，请选择后填写配置" % len(self.scan_results))

    def do_send(self, *args):
        app = App.get_running_app()
        if not HAS_BLE:
            self.set_status("本机不支持蓝牙配网（需在安卓真机上运行）")
            return
        if not self.scan_results:
            self.set_status("请先扫描并选择设备")
            return
        # 解析当前选中的设备
        sel = self.device_spinner.text
        device = None
        for n, a, d in self.scan_results:
            if "%s (%s)" % (n, a) == sel:
                device = d
                break
        if device is None:
            self.set_status("请选择设备")
            return

        ssid = self.fields["ssid"].text.strip()
        pwd = self.fields["password"].text
        broker = self.fields["broker"].text.strip()
        port = self.fields["port"].text.strip()
        ctl = self.fields["control"].text.strip()
        st = self.fields["status"].text.strip()
        if not ssid or not broker or not ctl or not st:
            self.set_status("请填写完整配置")
            return
        try:
            port_int = int(port or "1883")
        except ValueError:
            self.set_status("端口必须是数字")
            return

        config = "\n".join([ssid, pwd, broker, str(port_int), ctl, st])
        self.send_btn.disabled = True
        self.set_status("正在连接并下发配置…")
        app.ble_send(device, config, self._on_status, self._on_send_done,
                     broker, port_int, ctl, st)

    def _on_status(self, text):
        Clock.schedule_once(lambda dt: self.set_status("ESP32：%s" % text), 0)

    def _on_send_done(self, ok, broker, port, ctl, st):
        Clock.schedule_once(lambda dt: self._finish_send(ok, broker, port, ctl, st), 0)

    def _finish_send(self, ok, broker, port, ctl, st):
        self.send_btn.disabled = False
        if ok:
            self.set_status("配置已发送，等待 ESP32 连接 WiFi/MQTT…")
            App.get_running_app().reconfigure_mqtt(broker, port, ctl, st)
        else:
            self.set_status("发送失败，请重试")


class LightApp(App):
    title = "远程开关灯"

    def build(self):
        self.broker = DEFAULT_BROKER
        self.port = DEFAULT_PORT
        self.topic_control = DEFAULT_TOPIC_CONTROL
        self.topic_status = DEFAULT_TOPIC_STATUS
        self.light_state = "unknown"
        self.device_state = "unknown"

        self._request_permissions()
        self._setup_ble()

        self.sm = ScreenManager()
        self.control = ControlScreen(name="control")
        self.provision = ProvisionScreen(name="provision")
        self.sm.add_widget(self.control)
        self.sm.add_widget(self.provision)

        self._init_mqtt()
        return self.sm

    # ------------------------------------------------------------------
    # 权限 / BLE
    # ------------------------------------------------------------------
    def _request_permissions(self):
        try:
            from android.permissions import request_permissions, Permission
            request_permissions([
                Permission.BLUETOOTH_SCAN,
                Permission.BLUETOOTH_CONNECT,
                Permission.ACCESS_FINE_LOCATION,
            ])
        except Exception:  # noqa: BLE001
            pass

    def _setup_ble(self):
        self.ble = None
        if HAS_BLE:
            try:
                self.ble = BleManager(log_cb=lambda m: None)
            except Exception:  # noqa: BLE001
                self.ble = None

    def ble_scan(self, on_found, on_done):
        if self.ble:
            self.ble.start_scan(on_found, on_done, timeout=10.0)
        else:
            on_done()

    def ble_send(self, device, config, on_status, on_done, broker, port, ctl, st):
        if self.ble:
            self.ble.send_config(device, config, on_status,
                                 lambda ok: on_done(ok, broker, port, ctl, st))
        else:
            on_done(False, broker, port, ctl, st)

    # ------------------------------------------------------------------
    # MQTT
    # ------------------------------------------------------------------
    def _init_mqtt(self):
        import uuid
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  client_id="phone-light-" + uuid.uuid4().hex[:8],
                                  protocol=mqtt.MQTTv311)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self._set_srv("连接中…", C_AMBER)
        try:
            self.client.connect(self.broker, self.port, keepalive=30)
        except Exception as exc:  # noqa: BLE001
            self._set_srv("连接失败", C_RED)
            return
        self.client.loop_start()

    def reconfigure_mqtt(self, broker, port, ctl, st):
        self.broker = broker
        self.port = int(port)
        self.topic_control = ctl
        self.topic_status = st
        try:
            self.client.disconnect()
            self.client.loop_stop()
        except Exception:  # noqa: BLE001
            pass
        self._reset_device()
        self._init_mqtt()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            Clock.schedule_once(lambda dt: self._set_srv("已连接", C_GREEN), 0)
            client.subscribe(self.topic_status, qos=1)
        else:
            Clock.schedule_once(lambda dt: self._set_srv("连接失败", C_RED), 0)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        Clock.schedule_once(lambda dt: self._set_srv("已断开，重连中…", C_AMBER), 0)

    def _on_message(self, client, userdata, msg):
        payload = (msg.payload or b"").decode("utf-8", errors="ignore").strip()
        Clock.schedule_once(lambda dt: self._handle_status(payload), 0)

    # ------------------------------------------------------------------
    # 界面更新
    # ------------------------------------------------------------------
    def _set_srv(self, text, color):
        self.control.srv_label.text = "服务器：" + text
        self.control.srv_label.color = color

    def _set_dev(self, text, color):
        self.control.dev_label.text = "设备：" + text
        self.control.dev_label.color = color

    def _reset_device(self):
        self.device_state = "unknown"
        self._set_dev("未知", C_GRAY)
        self._apply_light("unknown")

    def _handle_status(self, payload):
        if payload == "online":
            self.device_state = "online"
            self._set_dev("在线", C_GREEN)
        elif payload == "offline":
            self.device_state = "offline"
            self._set_dev("离线", C_RED)

    def _apply_light(self, state):
        self.light_state = state
        if state == "on":
            self.control.bulb.set_on(True)
            self.control.state_label.text = "当前：已开灯"
            self.control.state_label.color = C_BULB_ON
            self.control.toggle_btn.text = "关 灯"
            self.control.toggle_btn.background_color = C_RED
        else:
            self.control.bulb.set_on(False)
            if state == "off":
                self.control.state_label.text = "当前：已关灯"
                self.control.state_label.color = C_GRAY
            else:
                self.control.state_label.text = "当前：未知"
                self.control.state_label.color = C_GRAY
            self.control.toggle_btn.text = "开 灯"
            self.control.toggle_btn.background_color = C_GREEN

    def toggle_light(self):
        if not self.client.is_connected():
            self._set_srv("未连接服务器", C_RED)
            return
        new = "on" if self.light_state != "on" else "off"
        self.client.publish(self.topic_control, new, qos=1)
        self._apply_light(new)


if __name__ == "__main__":
    LightApp().run()
