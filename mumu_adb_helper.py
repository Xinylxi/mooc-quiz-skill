# -*- coding: utf-8 -*-
"""MuMu ADB 元素定位助手（2026-10-15 实测打通）

用途：通过 uiautomator dump 读取 MuMu 内 Android UI 层级，按文本/resource-id/content-desc
定位元素，把 Android 像素坐标映射为 Windows 屏幕 0-1000 归一化坐标，供 computer_use_tool(plane="cu")
精确点击 —— 彻底摆脱"人眼估坐标 + OCR"。

已实测：
- adb 位置: D:\\app\\MuMu模拟器\\MuMuPlayer\\nx_device\\15.0\\shell\\adb.exe
- 连接: adb connect 127.0.0.1:16384（MuMu 12 默认；7555 亦通）
- dump 可读 WebView 内全部选项文本/字母标签/按钮 bounds
- 映射公式与 OCR 实测吻合（"上一题/下一题"按钮 误差≈0）
- 点击闭环：dump→解析→映射→cu.click 成功跳转页面

用法（在 computer_use_tool plane="cu" 的代码里）：
    import sys; sys.path.insert(0, r"C:\\Users\\19929\\Doubao\\chats\\2026-10-15\\new-chat-1")
    from mumu_adb_helper import MuMuAdb
    import seed_computer_use as cu
    m = MuMuAdb()
    hits = m.find(text="下一题")          # 精确匹配
    hits = m.find(contains="Robots")      # 子串匹配选项文本
    nx, ny = m.to_norm(hits[0][0])        # bounds -> 屏幕归一化
    cu.click(nx, ny)

注意事项：
- 每次 dump 约 1-2 秒；页面变化后需重新 dump（find 内部自动 dump）
- 选中状态（绿勾/橙叉）不在 dump 中，仍须截图颜色确认
- 若 MuMu 窗口位置/缩放变化，需重新标定 X_OFF/Y_OFF/SCALE（见文件末尾标定说明）
"""
import subprocess
import re
import time
import os

ADB = r"D:\app\MuMu模拟器\MuMuPlayer\nx_device\15.0\shell\adb.exe"
DEVICE = "127.0.0.1:16384"

# 映射参数（标定于 2026-10-15，MuMu 已 win+up 最大化，屏幕 1920x1080）
# Android 设备分辨率 1080x1920（竖屏）；画面区在屏幕像素 x≈694-1226, y≈88-1035
X_OFF, Y_OFF, SCALE = 694.0, 88.0, 0.493
SW, SH = 1920.0, 1080.0


class MuMuAdb:
    def __init__(self, adb=ADB, device=DEVICE):
        self.adb = adb
        self.device = device

    def dump(self):
        """uiautomator dump 当前 UI 层级，返回 XML 字符串。"""
        subprocess.run(
            [self.adb, "-s", self.device, "shell", "uiautomator", "dump", "/sdcard/ui_dump.xml"],
            capture_output=True, text=True, timeout=30)
        out = subprocess.run(
            [self.adb, "-s", self.device, "shell", "cat", "/sdcard/ui_dump.xml"],
            capture_output=True, text=True, timeout=30).stdout
        if "<hierarchy" not in out:
            raise RuntimeError("dump 失败，输出: " + out[:200])
        return out

    def find(self, text=None, resource_id=None, content_desc=None,
             class_name=None, contains=None, _out=None):
        """按属性定位元素，返回 [(bounds, attrs), ...]。
        text/resource_id/content_desc 精确匹配；contains 对 text 子串匹配。"""
        out = _out if _out is not None else self.dump()
        results = []
        for node in re.finditer(r"<node\b[^>]*>", out):
            attrs = dict(re.findall(r'(\w+)="([^"]*)"', node.group(0)))
            if text is not None and attrs.get("text") != text:
                continue
            if resource_id is not None and attrs.get("resource-id") != resource_id:
                continue
            if content_desc is not None and attrs.get("content-desc") != content_desc:
                continue
            if class_name is not None and attrs.get("class") != class_name:
                continue
            if contains is not None and contains not in attrs.get("text", ""):
                continue
            if "bounds" in attrs:
                results.append((attrs.get("bounds"), attrs))
        return results

    def to_norm(self, bounds):
        """Android bounds 字符串 '[x1,y1][x2,y2]' -> (归一化x, 归一化y)。"""
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
        if not m:
            return None
        x1, y1, x2, y2 = map(int, m.groups())
        ax, ay = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        return (X_OFF + ax * SCALE) / SW * 1000.0, (Y_OFF + ay * SCALE) / SH * 1000.0

    def center(self, bounds):
        """bounds -> Android 像素中心 (ax, ay)。"""
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
        x1, y1, x2, y2 = map(int, m.groups())
        return (x1 + x2) / 2.0, (y1 + y2) / 2.0

    # ---- 2026-10-15 新增：Android 层直接注入（脱离桌面 GUI，终极通道）----
    # input tap 用 Android 坐标直接点击，不经过桌面鼠标：
    #   无映射误差、不误触其他窗口、与 Windows 缩放无关、无需窗口固定
    def tap(self, x, y, wait=2.0):
        """Android 坐标直接点击（adb shell input tap）。"""
        r = subprocess.run(
            [self.adb, "-s", self.device, "shell", "input", "tap",
             str(int(round(x))), str(int(round(y)))],
            capture_output=True, text=True, timeout=30)
        if wait:
            time.sleep(wait)
        return r.returncode

    def click_text(self, text, wait=2.0):
        """按 text 精确定位并直接点击（dump + input tap 一体化）。"""
        hits = self.find(text=text)
        if not hits:
            return False
        cx, cy = self.center(hits[0][0])
        self.tap(cx, cy, wait)
        return True

    def click_contains(self, text, wait=2.0):
        """按 text 子串定位并直接点击（选项点击用，如 click_contains('Robots')）。"""
        hits = self.find(contains=text)
        if not hits:
            return False
        cx, cy = self.center(hits[0][0])
        self.tap(cx, cy, wait)
        return True

    def click_center_of(self, bounds, wait=2.0):
        """按 bounds 中心直接点击。"""
        cx, cy = self.center(bounds)
        self.tap(cx, cy, wait)
        return True

    def screencap(self, path):
        """干净截图（仅 Android 画面，无桌面干扰），保存 PNG，返回字节数。"""
        png = subprocess.run(
            [self.adb, "-s", self.device, "exec-out", "screencap", "-p"],
            capture_output=True, timeout=30).stdout
        with open(path, "wb") as f:
            f.write(png)
        return len(png)

    # ---- 2026-10-15 新增：答卷标记自动判读（绿勾/橙叉/无标记）----
    # 原理：dump 得选项文本 bounds（宽>300、y>400 的文本节点）-> screencap 干净截图
    #       -> 选项左侧区域颜色检测（绿勾=绿像素、橙叉=红像素、无标记=无彩色像素）
    # 实测：Q4 四绿勾、Q5 选中错项橙叉+未选项无标记，均判读正确
    def analyze_marks(self, png=None, dump_out=None):
        """自动判读当前单题页各选项标记。
        返回 [(选项文本, 标记), ...]，标记 ∈ {绿勾, 橙叉, 无标记}。
        判断题选项文本为图标字符（如 \\ue618），展示时可映射为 ✓/×。
        """
        from PIL import Image
        out = dump_out if dump_out is not None else self.dump()
        opts = []
        for node in re.finditer(r"<node\b[^>]*>", out):
            attrs = dict(re.findall(r'(\w+)="([^"]*)"', node.group(0)))
            t = attrs.get("text", "")
            b = attrs.get("bounds", "")
            m2 = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b)
            if not m2 or not t:
                continue
            x1, y1, x2, y2 = map(int, m2.groups())
            if (x2 - x1) >= 300 and y1 > 400:
                opts.append((t, b))
        if not opts:
            return []
        if png is None:
            tmp = os.path.join(os.environ.get("TEMP", "."), "mumu_marks.png")
            self.screencap(tmp)
            png = tmp
        img = Image.open(png).convert("RGB")
        px = img.load()
        results = []
        for t, b in opts:
            nums = list(map(int, re.findall(r"\d+", b)))
            x1, y1, x2, y2 = nums[0], nums[1], nums[2], nums[3]
            g = r = 0
            for y in range(y1, y2 + 1):
                for x in range(max(0, x1 - 160), max(0, x1 - 10)):
                    R, G, B = px[x, y]
                    if G > R + 40 and G > B + 40 and G > 120:
                        g += 1
                    elif R > G + 40 and R > B + 40 and R > 120:
                        r += 1
            mark = "橙叉" if r > 15 else ("绿勾" if g > 15 else "无标记")
            results.append((t, mark))
        return results


def calibrate(screen_w, screen_h, android_points, screen_points):
    """重新标定映射（可选）。
    android_points: [(ax, ay), ...]；screen_points: [(归一化x, 归一化y), ...]
    取两个点线性求解 scale 与 offset。
    """
    (ax1, ay1), (ax2, ay2) = android_points[0], android_points[1]
    (sx1, sy1), (sx2, sy2) = screen_points[0], screen_points[1]
    global X_OFF, Y_OFF, SCALE, SW, SH
    SW, SH = float(screen_w), float(screen_h)
    SCALE = ((sx2 - sx1) * SW / 1000.0) / (ax2 - ax1)
    X_OFF = (sx1 * SW / 1000.0) - ax1 * SCALE
    Y_OFF = (sy1 * SH / 1000.0) - ay1 * SCALE


if __name__ == "__main__":
    m = MuMuAdb()
    out = m.dump()
    print("dump OK, len:", len(out))
    for label, kwargs in [("下一题", dict(text="下一题")),
                          ("Robots选项", dict(contains="Robots")),
                          ("返回按钮", dict(content_desc="返回"))]:
        hits = m.find(_out=out, **kwargs)
        for b, a in hits[:3]:
            print(label, "->", a.get("text", "")[:30], b, "norm:", m.to_norm(b))
