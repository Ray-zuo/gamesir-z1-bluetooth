# Observed Z1 firmware 3216 keyboard transport

Measured on one physical Z1. This document covers the observed keyboard frames.

- Device: GameSir Z1, model CJ007-GZ1.
- Service: 00000000-0000-1000-8000-00805f9b34fb.
- Notify characteristic: 0000ffe2-0000-1000-8000-00805f9b34fb.
- No initialization command was required beyond subscribing to notifications.
- Each observed keyboard snapshot is 18 bytes.

| Offset | Meaning |
| --- | --- |
| 0 | 0xA5 frame marker |
| 1 | 0x12 total length |
| 2 | 0x01 observed input frame type |
| 3–8 | Not decoded; zero in keyboard-only samples |
| 9 | Standard USB HID keyboard modifier bitfield |
| 10–15 | Up to six standard USB HID keyboard usages; zero means empty |
| 16 | Not decoded; zero in all samples |
| 17 | Low 8 bits of the sum of bytes 0–16 |

Observed usages: Q=0x14, W=0x1A, E=0x08, R=0x15, Space=0x2C.
Observed modifier masks: Left Ctrl=0x01, Left Shift=0x02, Left Alt=0x04.
Shift+Q and Q+W snapshots were captured, including each release transition.
Unknown frames, invalid checksums and HID error/rollover snapshots are ignored.
Only the selected Z1 is accessed. The firmware-update service is never used.

Windows scan codes follow Microsoft's Keyboard Input Overview:
https://learn.microsoft.com/en-us/windows/win32/inputdev/about-keyboard-input

Input output uses SendInput, subject to Windows UIPI and application restrictions:
https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput
