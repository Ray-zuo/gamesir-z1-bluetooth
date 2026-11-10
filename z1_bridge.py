"""GameSir Z1 BLE keyboard bridge, validated with firmware 3216.

Reads FFE2 notifications and translates physical Z1 key actions into Windows
scan codes. No firmware/configuration writes, startup entries, or key logs.
"""
from __future__ import annotations
import asyncio
import ctypes
from ctypes import wintypes
import queue
import threading
import time

SERVICE_UUID = "00000000-0000-1000-8000-00805f9b34fb"
INPUT_UUID = "0000ffe2-0000-1000-8000-00805f9b34fb"

# USB HID usage -> Windows Scan Code Set 1 (Microsoft Keyboard Input Overview).
SCANS = dict(zip(range(4, 30), [
    0x1E,0x30,0x2E,0x20,0x12,0x21,0x22,0x23,0x17,0x24,0x25,0x26,0x32,
    0x31,0x18,0x19,0x10,0x13,0x1F,0x14,0x16,0x2F,0x11,0x2D,0x15,0x2C]))
SCANS.update(dict(zip(range(0x1E,0x28),range(0x02,0x0C))))
SCANS.update({0x28:0x1C,0x29:0x01,0x2A:0x0E,0x2B:0x0F,0x2C:0x39,
    0x2D:0x0C,0x2E:0x0D,0x2F:0x1A,0x30:0x1B,0x31:0x2B,0x32:0x2B,
    0x33:0x27,0x34:0x28,0x35:0x29,0x36:0x33,0x37:0x34,0x38:0x35,0x39:0x3A,
    0x44:0x57,0x45:0x58,0x46:0xE037,0x47:0x46,
    0x49:0xE052,0x4A:0xE047,0x4B:0xE049,0x4C:0xE053,0x4D:0xE04F,
    0x4E:0xE051,0x4F:0xE04D,0x50:0xE04B,0x51:0xE050,0x52:0xE048,
    0x53:0x45,0x54:0xE035,0x55:0x37,0x56:0x4A,0x57:0x4E,0x58:0xE01C,
    0x59:0x4F,0x5A:0x50,0x5B:0x51,0x5C:0x4B,0x5D:0x4C,0x5E:0x4D,
    0x5F:0x47,0x60:0x48,0x61:0x49,0x62:0x52,0x63:0x53,0x64:0x56,
    0x65:0xE05D,0xE0:0x1D,0xE1:0x2A,0xE2:0x38,0xE3:0xE05B,
    0xE4:0xE01D,0xE5:0x36,0xE6:0xE038,0xE7:0xE05C})
SCANS.update(dict(zip(range(0x3A,0x44),range(0x3B,0x45))))
MODIFIERS = set(range(0xE0,0xE8))
NO_REPEAT = MODIFIERS | {0x39,0x46,0x47,0x53,0x65}


def decode_packet(packet: bytes) -> frozenset[int] | None:
    """Observed A5/18-byte/input-01 frame; ignore other/invalid reports."""
    if len(packet) != 18 or packet[:3] != b"\xa5\x12\x01":
        return None
    if sum(packet[:-1]) & 255 != packet[-1]:
        return None
    codes = packet[10:16]
    if any(code in (1,2,3) for code in codes):  # HID rollover/error: no new state
        return None
    keys = {code for code in codes if code in SCANS}
    keys.update(0xE0+bit for bit in range(8) if packet[9] & (1 << bit))
    return frozenset(keys)


class KeyboardState:
    def __init__(self, sink, delay=.5, interval=.04):
        self.sink = sink
        self.down = set()
        self.order = []
        self.delay, self.interval = delay, interval
        self.repeat_key = None
        self.repeat_at = 0.0

    def update(self, keys, now=None):
        now = time.monotonic() if now is None else now
        # Release ordinary keys before modifiers; press modifiers before keys.
        removed = self.down - set(keys)
        added = set(keys) - self.down
        for key in sorted(removed, key=lambda k: (k in MODIFIERS,k)):
            self.sink(key, False)
            self.down.discard(key)
            if key in self.order:
                self.order.remove(key)
        for key in sorted(added, key=lambda k: (k not in MODIFIERS,k)):
            self.sink(key, True)
            self.down.add(key)
            if key not in NO_REPEAT:
                self.order.append(key)
        latest = self.order[-1] if self.order else None
        if latest != self.repeat_key:
            self.repeat_key = latest
            self.repeat_at = now + self.delay

    def repeat(self, now=None):
        now = time.monotonic() if now is None else now
        if self.repeat_key is not None and now >= self.repeat_at:
            self.sink(self.repeat_key, True)
            self.repeat_at = now + self.interval

    def release_all(self):
        error = None
        for key in sorted(self.down.copy(), key=lambda k: (k in MODIFIERS,k)):
            try:
                self.sink(key, False)
                self.down.discard(key)
            except Exception as exc:
                error = exc
        self.order = []
        self.repeat_key = None
        if error:
            raise error


class InputBlocked(OSError):
    pass


class WindowsInput:
    """Output for this physical keyboard; does not read any other keyboard."""
    def __init__(self):
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk",wintypes.WORD),("wScan",wintypes.WORD),
                ("dwFlags",wintypes.DWORD),("time",wintypes.DWORD),
                ("dwExtraInfo",ctypes.c_size_t)]
        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx",wintypes.LONG),("dy",wintypes.LONG),
                ("mouseData",wintypes.DWORD),("dwFlags",wintypes.DWORD),
                ("time",wintypes.DWORD),("dwExtraInfo",ctypes.c_size_t)]
        class PAYLOAD(ctypes.Union):
            _fields_ = [("ki",KEYBDINPUT),("mi",MOUSEINPUT)]
        class INPUT(ctypes.Structure):
            _anonymous_ = ("payload",)
            _fields_ = [("type",wintypes.DWORD),("payload",PAYLOAD)]
        self.INPUT, self.KEYBDINPUT = INPUT, KEYBDINPUT
        self.user32 = ctypes.WinDLL("user32",use_last_error=True)
        self.user32.SendInput.argtypes = [wintypes.UINT,ctypes.POINTER(INPUT),ctypes.c_int]
        self.user32.SendInput.restype = wintypes.UINT
        assert ctypes.sizeof(INPUT) == (40 if ctypes.sizeof(ctypes.c_void_p)==8 else 28)

    def __call__(self, usage, pressed):
        scan = SCANS[usage]
        flags = 0x0008 | (0x0001 if scan & 0xE000 else 0) | (0 if pressed else 0x0002)
        event = self.INPUT(type=1)
        event.ki = self.KEYBDINPUT(0,scan & 0xFF,flags,0,0)
        if self.user32.SendInput(1,ctypes.byref(event),ctypes.sizeof(event)) != 1:
            raise InputBlocked(ctypes.get_last_error(), "Windows input was blocked; conversion has stopped")

    def repeat_settings(self):
        speed, delay = wintypes.UINT(20), wintypes.UINT(1)
        self.user32.SystemParametersInfoW(0x000A,0,ctypes.byref(speed),0)
        self.user32.SystemParametersInfoW(0x0016,0,ctypes.byref(delay),0)
        return .25*(1+min(delay.value,3)), 1/(2.5+27.5*min(speed.value,31)/31)


async def open_paired_z1():
    """Find the single GameSir Z1 already paired in Windows Settings."""
    from winrt.windows.devices.bluetooth import BluetoothLEDevice
    from winrt.windows.devices.enumeration import DeviceInformation

    selector = BluetoothLEDevice.get_device_selector_from_pairing_state(True)
    devices = await asyncio.wait_for(
        DeviceInformation.find_all_async_aqs_filter(selector), 8
    )
    matches = [
        device for device in devices
        if device.name.casefold() == "gamesir-z1"
        or device.name.casefold().startswith("gamesir-z1_")
    ]
    if not matches:
        raise RuntimeError("未找到已配对的 Z1。请切到 Mobile 模式并在 Windows 蓝牙设置里配对。")
    if len(matches) > 1:
        raise RuntimeError("检测到多把已配对的 Z1。请在 Windows 蓝牙设置中只保留要用的一把。")
    return await asyncio.wait_for(BluetoothLEDevice.from_id_async(matches[0].id), 12)


class Bridge:
    def __init__(self, updates):
        self.updates = updates
        self.stop = threading.Event()
        self.paused = threading.Event()
        self.total = 0

    def post(self, status):
        self.updates.put((status,self.total))

    async def run(self):
        from winrt.windows.devices.bluetooth import BluetoothCacheMode, BluetoothConnectionStatus
        from winrt.windows.devices.bluetooth.genericattributeprofile import GattCommunicationStatus, GattClientCharacteristicConfigurationDescriptorValue as CCC
        from winrt.windows.storage.streams import DataReader
        sink = WindowsInput()
        state = KeyboardState(sink,*sink.repeat_settings())
        loop = asyncio.get_running_loop()
        while not self.stop.is_set():
            device, services, characteristic, token = None, [], None, None
            input_failure = None
            connection_lost = asyncio.Event()
            connection_token = None
            receiving = True
            try:
                self.post("正在连接 Z1 蓝牙…")
                device = await open_paired_z1()
                if device is None:
                    raise RuntimeError("找不到已配对的 Z1")
                result = await asyncio.wait_for(device.get_gatt_services_async(BluetoothCacheMode.UNCACHED),15)
                if result.status != GattCommunicationStatus.SUCCESS:
                    raise RuntimeError("Z1 暂时不可达，请确认已开机并处于 Mobile 模式")
                services = list(result.services)
                service = next((s for s in services if str(s.uuid)==SERVICE_UUID),None)
                if service is None:
                    raise RuntimeError("未找到已验证的 Z1 蓝牙通道")
                result = await asyncio.wait_for(service.get_characteristics_async(BluetoothCacheMode.CACHED),8)
                if result.status != GattCommunicationStatus.SUCCESS:
                    raise RuntimeError("无法读取 Z1 数据通道")
                characteristic = next((c for c in result.characteristics if str(c.uuid)==INPUT_UUID),None)
                if characteristic is None:
                    raise RuntimeError("未找到 FFE2 按键通知")

                def accept(packet):
                    nonlocal input_failure
                    if not receiving or self.stop.is_set() or input_failure:
                        return
                    keys = decode_packet(packet)
                    if keys is None:
                        return
                    self.total += 1
                    if not self.paused.is_set():
                        try:
                            state.update(keys)
                        except Exception as exc:
                            input_failure = exc
                    self.post("已暂停" if self.paused.is_set() else "蓝牙已连接 · 按键转换已开启")

                def changed(sender,event):
                    reader = DataReader.from_buffer(event.characteristic_value)
                    try:
                        packet = bytes(reader.read_byte() for _ in range(event.characteristic_value.length))
                    finally:
                        reader.close()
                    loop.call_soon_threadsafe(accept,packet)

                def connection_changed(sender,args):
                    if sender.connection_status != BluetoothConnectionStatus.CONNECTED:
                        loop.call_soon_threadsafe(connection_lost.set)

                connection_token = device.add_connection_status_changed(connection_changed)
                token = characteristic.add_value_changed(changed)
                status = await asyncio.wait_for(characteristic.write_client_characteristic_configuration_descriptor_async(CCC.NOTIFY),5)
                if status != GattCommunicationStatus.SUCCESS:
                    raise RuntimeError("Z1 拒绝启用按键通知")
                self.post("蓝牙已连接 · 按键转换已开启")
                was_paused = self.paused.is_set()
                while not self.stop.is_set():
                    if input_failure:
                        raise input_failure
                    if connection_lost.is_set() or device.connection_status != BluetoothConnectionStatus.CONNECTED:
                        raise RuntimeError("蓝牙连接已断开，正在重连…")
                    is_paused = self.paused.is_set()
                    if is_paused:
                        if not was_paused:
                            state.release_all()
                            self.post("已暂停")
                    else:
                        if was_paused:
                            self.post("蓝牙已连接 · 按键转换已开启")
                        state.repeat()
                    was_paused = is_paused
                    await asyncio.sleep(.015)
            except InputBlocked:
                self.post("输入被 Windows 阻止，转换已停止")
                self.stop.set()
            except Exception as exc:
                self.post(str(exc))
            finally:
                receiving = False
                # Release injected keys before waiting for Bluetooth cleanup.
                try:
                    state.release_all()
                except Exception:
                    self.post("Windows 未接受按键释放，请松开键盘上的全部按键")
                if characteristic is not None and token is not None:
                    characteristic.remove_value_changed(token)
                    try:
                        await asyncio.wait_for(characteristic.write_client_characteristic_configuration_descriptor_async(CCC.NONE),2)
                    except Exception:
                        pass
                if device is not None and connection_token is not None:
                    device.remove_connection_status_changed(connection_token)
                for service in services:
                    service.close()
                if device is not None:
                    device.close()
            for _ in range(30):
                if self.stop.is_set():
                    break
                await asyncio.sleep(.1)
        self.post("转换已停止")


def main():
    import tkinter as tk
    from tkinter import ttk
    kernel32 = ctypes.WinDLL("kernel32",use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    mutex = kernel32.CreateMutexW(None,False,"Local\\GameSirZ1Bluetooth")
    if ctypes.get_last_error()==183:
        ctypes.windll.user32.MessageBoxW(None,"Z1 蓝牙转换器已经在运行。","GameSir Z1",0x40)
        return
    root = tk.Tk()
    root.title("GameSir Z1 蓝牙键盘")
    root.geometry("570x320")
    root.minsize(510,300)
    root.configure(bg="#f5f7fa")
    frame = ttk.Frame(root,padding=24)
    frame.pack(fill="both",expand=True)
    ttk.Label(frame,text="GameSir Z1 蓝牙键盘",font=("Microsoft YaHei UI",17,"bold")).pack(anchor="w")
    status = tk.StringVar(value="正在连接 Z1 蓝牙…")
    ttk.Label(frame,textvariable=status,wraplength=500,font=("Microsoft YaHei UI",10)).pack(anchor="w",pady=(14,5))
    count = tk.StringVar(value="已接收 0 个有效按键数据包")
    ttk.Label(frame,textvariable=count,foreground="#64748b").pack(anchor="w")
    ttk.Label(frame,text="点下面的空白框，即可测试输入：").pack(anchor="w",pady=(18,6))
    entry = ttk.Entry(frame,font=("Consolas",15))
    entry.pack(fill="x",ipady=7)
    updates = queue.Queue()
    bridge = Bridge(updates)
    row = ttk.Frame(frame)
    row.pack(fill="x",pady=(18,0))
    def toggle():
        if bridge.paused.is_set():
            bridge.paused.clear()
            button.configure(text="暂停转换")
        else:
            bridge.paused.set()
            button.configure(text="恢复转换")
    button = ttk.Button(row,text="暂停转换",command=toggle)
    button.pack(side="left")
    ttk.Label(row,text="保持 Mobile 模式；关闭窗口即可停止。",foreground="#64748b").pack(side="right")
    def worker():
        try:
            asyncio.run(bridge.run())
        except Exception as exc:
            bridge.post("程序错误："+str(exc))
    thread = threading.Thread(target=worker,name="Z1-BLE",daemon=False)
    thread.start()
    closing = False
    def drain():
        while True:
            try:
                message,total = updates.get_nowait()
            except queue.Empty:
                break
            status.set(message)
            count.set(f"已接收 {total} 个有效按键数据包")
        if not closing:
            root.after(100,drain)
    def close():
        nonlocal closing
        closing = True
        bridge.stop.set()
        button.configure(state="disabled")
        status.set("正在释放按键并关闭…")
        def wait_closed():
            if thread.is_alive():
                root.after(100,wait_closed)
            else:
                root.destroy()
        wait_closed()
    root.protocol("WM_DELETE_WINDOW",close)
    root.after(100,drain)
    entry.focus_set()
    root.mainloop()
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    main()
