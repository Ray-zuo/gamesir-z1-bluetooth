# GameSir Z1 Bluetooth

Windows 上的 GameSir Z1 蓝牙键盘转换器。程序从已配对的 Z1 读取 BLE 通知，解码按键和修饰键，再通过 Windows `SendInput` 输出按键。面向 Windows x64 和 GameSir Z1，协议在固件 3216 上验证过。

Windows Bluetooth keyboard bridge for the GameSir Z1 keypad. It reads BLE notifications and translates physical key presses into Windows scan code events.

## 使用

1. 将 Z1 切到 **Mobile** 模式，在 Windows 蓝牙设置中与它配对。程序会查找名为 `Gamesir-Z1` 或 `Gamesir-Z1_…` 的已配对设备。
2. 运行程序，等状态显示蓝牙已连接。在窗口的输入框里试打 `qwer` 或 `Shift + Q`。
3. 保持窗口打开即可在其他应用中输入。需要停用时，点「暂停转换」或关闭窗口。

只支持同时使用一把已配对的 Z1。程序支持常见键盘键与组合键。Windows 权限或应用的输入处理方式可能限制 `SendInput`。当前未验证游戏兼容性。

## 从源码运行

安装 64 位 Python 3.12（包含 Tkinter），然后在仓库目录运行以下命令。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe z1_bridge.py
```

## 测试和构建

```powershell
.\.venv\Scripts\python.exe -m unittest -v
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller --onefile --windowed --noupx --collect-all winrt --name GameSirZ1Bluetooth z1_bridge.py
```

构建产物位于 `dist/GameSirZ1Bluetooth.exe`。测试重放脱敏的按键报文，检查解码和按键状态管理。

## 协议与许可

BLE 通道和按键报文见 [PROTOCOL.md](PROTOCOL.md)。项目源码按 [MIT](LICENSE) 许可发布。
