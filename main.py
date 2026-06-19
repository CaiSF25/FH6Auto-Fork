import sys
import os
# ====== 【修復 OMP 衝突的核心代碼】 ======
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
# =======================================
import json
import re
import time
import shutil
import ctypes
import subprocess
import webbrowser
import traceback
# ====== 【新增】：啟動前置環境檢測 (防閃退機制) ======
def check_windows_dependencies():
    if sys.platform != "win32":
        return
    missing_dlls = []
    # OpenCV(cv2) 等圖像識別庫強依賴微軟 VC++ 2015-2022 運行庫
    required_dlls = ["vcruntime140.dll", "msvcp140.dll", "vcruntime140_1.dll"]
    
    for dll in required_dlls:
        try:
            # 嘗試靜默載入該運行庫，如果系統裡沒有，就會觸發 OSError
            ctypes.WinDLL(dll)
        except OSError:
            missing_dlls.append(dll)
            
    if missing_dlls:
        msg = (
            f"警告：系統缺失以下關鍵運行庫，大概率會導致程式閃退或圖像識別失敗：\n\n"
            f"{', '.join(missing_dlls)}\n\n"
            f"這是因為您的電腦缺少微軟 C++ 運行環境。\n"
            f"請搜索下載【微軟常用運行庫合集】或【VC++ 2015-2022】安裝後重試。\n\n"
            f"點擊“確定”強行繼續運行（如果閃退請安裝運行庫）。"
        )
        # 0x30 = MB_ICONWARNING (黃色警告圖示), 0x0 = MB_OK (只有確定按鈕)
        ctypes.windll.user32.MessageBoxW(0, msg, "缺少運行庫攔截提示", 0x30 | 0x0)
# 在導入耗性能的大型模組前，第一時間執行攔截檢測
check_windows_dependencies()
# ===================================================
# 【極其關鍵】：必須在任何 UI 庫導入之前設置 DPI 感知
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Win 8.1+
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()  # Win Vista+
    except Exception:
        pass

import customtkinter as ctk
ctk.deactivate_automatic_dpi_awareness()
ctk.set_widget_scaling(1.0)
ctk.set_window_scaling(1.0)
import cv2
import numpy as np
import pyautogui
import pydirectinput
import requests
import tkinter as tk
from pynput import keyboard
from PIL import Image, ImageGrab
import win32gui
import pickle
import threading



# ==========================================
# --- 路徑與資源策略 ---
# assets: 唯讀內置，禁止本地覆蓋
# images: 打包進 exe，啟動時若外部無 images 則自動釋放；識圖優先讀外部 images
# ==========================================
def get_app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_internal_dir():
    if hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return get_app_dir()


APP_DIR = get_app_dir()
INTERNAL_DIR = get_internal_dir()
# 【新增 config 目錄路徑】
CONFIG_DIR = os.path.join(APP_DIR, "config")
USER_CONFIG_FILE = os.path.join(APP_DIR, "config.json")      # <--- 全面替換為 config.json
LOG_FILE = os.path.join(APP_DIR, "bot_log.txt")
CACHE_DIR = os.path.join(APP_DIR, "cache")
DEBUG_DIR = os.path.join(APP_DIR, "debug")
DEBUG_LOG_DIR = os.path.join(DEBUG_DIR, "logs")
TEMPLATE_CACHE_FILE = os.path.join(CACHE_DIR, "template_cache.pkl")
TEMPLATE_META_FILE = os.path.join(CACHE_DIR, "template_meta.json")
LOCAL_VERSION_FILE = os.path.join(APP_DIR, "version.json")
OCR_MODELS_DIR = os.path.join(APP_DIR, "ocr_models")
DEFAULT_CURRENT_VERSION = "1.2.4"
APP_DISPLAY_NAME = "FH6Auto Fork"
APP_ATTRIBUTION = "Based on YOUSTHEONE/FH6Auto"
DEFAULT_UPSTREAM_REPO_URL = "https://github.com/YOUSTHEONE/FH6Auto"
DEFAULT_PROJECT_REPO_URL = "https://github.com/CaiSF25/FH6Auto-Fork"
DEFAULT_UPDATE_MANIFEST_URL = "https://raw.githubusercontent.com/CaiSF25/FH6Auto-Fork/refs/heads/main/version.json"


def load_local_version_meta():
    defaults = {
        "version": DEFAULT_CURRENT_VERSION,
        "project_url": DEFAULT_PROJECT_REPO_URL,
        "upstream_url": DEFAULT_UPSTREAM_REPO_URL,
        "manifest_url": DEFAULT_UPDATE_MANIFEST_URL,
    }
    try:
        if os.path.exists(LOCAL_VERSION_FILE):
            with open(LOCAL_VERSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                defaults.update({k: v for k, v in data.items() if v})
    except Exception:
        pass
    return defaults


LOCAL_VERSION_META = load_local_version_meta()
CURRENT_VERSION = str(LOCAL_VERSION_META.get("version", DEFAULT_CURRENT_VERSION))
UPSTREAM_REPO_URL = str(LOCAL_VERSION_META.get("upstream_url", DEFAULT_UPSTREAM_REPO_URL))
PROJECT_REPO_URL = str(LOCAL_VERSION_META.get("project_url", DEFAULT_PROJECT_REPO_URL))
UPDATE_MANIFEST_URL = str(LOCAL_VERSION_META.get("manifest_url", DEFAULT_UPDATE_MANIFEST_URL))
def auto_extract_configs():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    
    # 向下相容，自動重命名並遷移老版本 bot_config
    old_configs = [
        os.path.join(APP_DIR, "bot_config.json"),
        os.path.join(APP_DIR, "bot-config.json"),
        os.path.join(CONFIG_DIR, "bot-config.json"),
        os.path.join(CONFIG_DIR, "bot_config.json"),
        os.path.join(CONFIG_DIR, "config.json")
    ]
    for old_path in old_configs:
        if os.path.exists(old_path):
            try:
                if not os.path.exists(USER_CONFIG_FILE):
                    shutil.move(old_path, USER_CONFIG_FILE)
                else:
                    os.remove(old_path)
            except Exception:
                pass
def auto_extract_images(folder_name="images"):
    internal_dir = os.path.join(INTERNAL_DIR, folder_name)
    external_dir = os.path.join(APP_DIR, folder_name)

    if not os.path.isdir(internal_dir):
        print(f"[auto_extract_images] 內置目錄不存在: {internal_dir}")
        return

    try:
        os.makedirs(external_dir, exist_ok=True)

        for root, dirs, files in os.walk(internal_dir):
            rel_path = os.path.relpath(root, internal_dir)
            target_root = external_dir if rel_path == "." else os.path.join(external_dir, rel_path)
            os.makedirs(target_root, exist_ok=True)

            for file in files:
                src_file = os.path.join(root, file)
                dst_file = os.path.join(target_root, file)

                # 只在外部不存在時釋放，保留用戶自訂替換
                if not os.path.exists(dst_file):
                    shutil.copy2(src_file, dst_file)

    except Exception as e:
        print(f"[auto_extract_images] 釋放 images 失敗: {e}")


def get_img_path(filename):
    basename = os.path.basename(filename)

    # 優先讀取程式目錄外部 images（允許使用者替換）
    ext_path = os.path.join(APP_DIR, "images", basename)
    if os.path.exists(ext_path):
        return ext_path

    # 外部沒有則讀取內置 images
    int_path = os.path.join(INTERNAL_DIR, "images", basename)
    if os.path.exists(int_path):
        return int_path

    return filename


def get_asset_path(*parts):
    """
    assets 只允許讀取內置資源：
    - 打包後：_MEIPASS/assets
    - 開發環境：專案目錄/assets
    """
    asset_path = os.path.join(INTERNAL_DIR, "assets", *parts)
    if os.path.exists(asset_path):
        return asset_path

    dev_asset_path = os.path.join(get_app_dir(), "assets", *parts)
    if os.path.exists(dev_asset_path):
        return dev_asset_path

    return None


def parse_version(v):
    try:
        parts = re.findall(r"\d+", str(v))
        if not parts:
            return (0, 0, 0)
        nums = tuple(int(x) for x in parts[:4])
        return nums + (0,) * (3 - len(nums)) if len(nums) < 3 else nums
    except Exception:
        return (0, 0, 0)


def build_latest_release_api_url(repo_url):
    m = re.match(r"^https://github\.com/([^/]+)/([^/]+?)/?$", str(repo_url).strip())
    if not m:
        return ""
    owner, repo = m.groups()
    return f"https://api.github.com/repos/{owner}/{repo}/releases/latest"

# ==========================================
# --- Ctypes 硬體級鍵盤類比結構體定義 ---
# ==========================================
SendInput = ctypes.windll.user32.SendInput
PUL = ctypes.POINTER(ctypes.c_ulong)


class KeyBdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL),
    ]


class HardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_short),
        ("wParamH", ctypes.c_ushort),
    ]


class MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL),
    ]


class Input_I(ctypes.Union):
    _fields_ = [
        ("ki", KeyBdInput),
        ("mi", MouseInput),
        ("hi", HardwareInput),
    ]


class Input(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("ii", Input_I),
    ]


# --- 硬體掃描碼 (Scan Codes) 包含數位 0-9 ---
DIK_CODES = {
    # control
    "esc": (0x01, False),
    "enter": (0x1C, False),
    "space": (0x39, False),
    "backspace": (0x0E, False),
    "tab": (0x0F, False),
    "lshift": (0x2A, False),
    "rshift": (0x36, False),
    "lctrl": (0x1D, False),
    "rctrl": (0x1D, True),
    "lalt": (0x38, False),
    "ralt": (0x38, True),
    "capslock": (0x3A, False),

    # letters
    "a": (0x1E, False),
    "b": (0x30, False),
    "c": (0x2E, False),
    "d": (0x20, False),
    "e": (0x12, False),
    "f": (0x21, False),
    "g": (0x22, False),
    "h": (0x23, False),
    "i": (0x17, False),
    "j": (0x24, False),
    "k": (0x25, False),
    "l": (0x26, False),
    "m": (0x32, False),
    "n": (0x31, False),
    "o": (0x18, False),
    "p": (0x19, False),
    "q": (0x10, False),
    "r": (0x13, False),
    "s": (0x1F, False),
    "t": (0x14, False),
    "u": (0x16, False),
    "v": (0x2F, False),
    "w": (0x11, False),
    "x": (0x2D, False),
    "y": (0x15, False),
    "z": (0x2C, False),

    # number row
    "1": (0x02, False),
    "2": (0x03, False),
    "3": (0x04, False),
    "4": (0x05, False),
    "5": (0x06, False),
    "6": (0x07, False),
    "7": (0x08, False),
    "8": (0x09, False),
    "9": (0x0A, False),
    "0": (0x0B, False),

    # arrows / navigation
    "up": (0xC8, True),
    "down": (0xD0, True),
    "left": (0xCB, True),
    "right": (0xCD, True),
    "pageup": (0xC9, True),
    "pagedown": (0xD1, True),
    "home": (0xC7, True),
    "end": (0xCF, True),
    "insert": (0xD2, True),
    "delete": (0xD3, True),

    # function keys
    "f1": (0x3B, False),
    "f2": (0x3C, False),
    "f3": (0x3D, False),
    "f4": (0x3E, False),
    "f5": (0x3F, False),
    "f6": (0x40, False),
    "f7": (0x41, False),
    "f8": (0x42, False),
    "f9": (0x43, False),
    "f10": (0x44, False),
    "f11": (0x57, False),
    "f12": (0x58, False),
}

# --- 全域配置 ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")
MATCH_THRESHOLD = 0.8
pyautogui.FAILSAFE = False

LOG_LEVEL_LABELS = {
    "DEBUG": "調試",
    "INFO": "信息",
    "WARNING": "警告",
    "ERROR": "錯誤",
}

STEP_LABELS = {
    "idle": "空閒",
    "system": "系統",
    "race": "跑圖",
    "buy": "買車",
    "cj": "超級抽獎",
    "sell": "刪車",
    "boot": "自動開機測試",
    "recovery": "中斷點恢復",
}


class FH_UltimateBot(ctk.CTk):
    def __init__(self):
        super().__init__()
        #窗口相關
        self.title(f"{APP_DISPLAY_NAME} v{CURRENT_VERSION}")
        self.geometry("1800x800")
        #self.minsize(980, 560)
        self.attributes("-topmost", False)
        self.attributes("-alpha", 0.98)
        self.resizable(False, False)

        try:
            icon_path = get_asset_path("icon.ico")
            if icon_path:
                self.iconbitmap(icon_path)
        except Exception:
            pass

        self.is_running = False
        self.current_thread = None
        self.is_paused = False  # <--- 【新增】全域暫停狀態

        self.race_counter = 0
        self.car_counter = 0
        self.cj_counter = 0
        self.sc_count = 0
        self.global_loop_current = 0
        self.global_loop_total = 0
        self.memory_car_page = 0
        self.current_step_name = "idle"
        self.current_phase_name = "初始化"
        self.current_targets = {"race": 0, "buy": 0, "cj": 0, "sell": 0}
        self.log_session_id = None
        self.log_file_path = None
        self.log_file_lock = threading.Lock()

        self.template_cache = {}
        self.scaled_template_cache = {}
        self.file_template_cache = {}
        self.last_positions = {}
        self.support_win = None
        self.edge_template_cache = {}
        self.scaled_edge_template_cache = {}

        self.init_regions()
        
        # 【優化載入速度】：將IO提取與圖像緩存的載入/生成放到後臺執行緒，避免阻塞主介面啟動
        # 增加模型釋放步驟
        def background_init():
            auto_extract_images()
            
            self.prepare_template_cache()
            #self.use_ocr = self.config.get("use_ocr", True)
            #if self.use_ocr:
            #    self.init_ocr_engine()
        threading.Thread(target=background_init, daemon=True).start()
        
        #載入設定檔
        auto_extract_configs()  
        self.load_config()

        self.setup_ui()
        self.start_hotkey_listener()
        self.update_skill_grid()
        self.center_window()
        
        self.log("免責聲明：本腳本僅供 Python 自動化技術交流與學習使用。請勿用於商業盈利或破壞遊戲平衡，因使用本腳本造成的帳號封禁等損失，由使用者自行承擔。")
        self.log("工具運行目錄不要有中文")
        self.log("默認刷圖車輛：【SUBARUImpreza 22B-STi Version】【調校S2  834】【保持默認塗裝】【收藏車輛】")
        self.log("啟動前先將鍵盤設置為【英文鍵盤】")
        self.log("遊戲設置為【自動轉向】【自動擋】，遊戲語言設置為【繁體中文】")
        self.log("大部分以圖像識別作為引導，減少機器盲目操作的風險，但仍無法完全避免，使用前請做好準備")

    # ==========================================
    # --- UI 安全調度 ---
    # ==========================================
    def ui_call(self, func, *args, **kwargs):
        try:
            self.after(0, lambda: func(*args, **kwargs))
        except Exception:
            pass

    def center_window(self):
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        gx, gy, gw, gh = self.regions["全螢幕"]
        x = gx + (gw - w) // 2
        y = gy + (gh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
    def sync_buy_to_sell(self, event=None):
        try:
            val = "".join(c for c in self.entry_car.get() if c.isdigit())
            if val == "":
                val = "0"
            self.entry_cj.delete(0, "end")
            self.entry_cj.insert(0, val)
            self.entry_sc.delete(0, "end")
            self.entry_sc.insert(0, val)
        except Exception:
            pass

    def normalize_step_entry(self, entry_widget, default_value):
        try:
            v = "".join(c for c in entry_widget.get() if c.isdigit())
            if v == "":
                v = str(default_value)
            iv = int(v)
            if iv < 1:
                iv = 1
            if iv > 4:
                iv = 4
            entry_widget.delete(0, "end")
            entry_widget.insert(0, str(iv))
        except Exception:
            entry_widget.delete(0, "end")
            entry_widget.insert(0, str(default_value))

    def should_reset_cj_memory_on_new_loop(self):
        try:
            next_after_cj = int(self.entry_next3.get())
        except Exception:
            next_after_cj = int(self.config.get("next_3", 4))
        return next_after_cj == 4

    def format_delay_text(self, value):
        return f"{float(value):.2f}s"

    def get_ui_delay_scale(self):
        try:
            if hasattr(self, "slider_ui_delay"):
                return max(0.5, float(self.slider_ui_delay.get()))
        except Exception:
            pass
        return max(0.5, float(self.config.get("ui_delay_scale", 1.0)))

    def get_post_get_in_car_delay(self):
        try:
            if hasattr(self, "slider_post_get_in_car"):
                return max(0.3, float(self.slider_post_get_in_car.get()))
        except Exception:
            pass
        return max(0.3, float(self.config.get("post_get_in_car_delay", 0.5)))

    def sleep_ui(self, base_seconds):
        time.sleep(max(0.05, float(base_seconds) * self.get_ui_delay_scale()))

    def sleep_post_get_in_car(self):
        time.sleep(self.get_post_get_in_car_delay())

    def wait_for_share_code_input_ready(self):
        is_xbox_platform = False
        try:
            if hasattr(self, "var_xbox_platform"):
                is_xbox_platform = bool(self.var_xbox_platform.get())
            else:
                is_xbox_platform = bool(self.config.get("is_xbox_platform", False))
        except Exception:
            is_xbox_platform = bool(self.config.get("is_xbox_platform", False))

        if not is_xbox_platform:
            self.log("當前為普通平臺模式，按 Enter 後固定等待 0.8s 再輸入藍圖代碼。")
            time.sleep(0.8)
            return True

        self.log("已啟用 Xbox 平臺模式，按 Enter 後先緩衝 2.5s，再等待“共用代碼”輸入框出現...")
        time.sleep(2.5)

        template_path = get_img_path("xboxsharecode.png")
        if not os.path.exists(template_path):
            self.log("未找到 xboxsharecode.png，改為 Xbox 兜底固定等待 6.0s 後繼續輸入藍圖代碼。")
            time.sleep(6.0)
            return True

        center_region = self.regions.get("中間", self.regions.get("全螢幕"))
        full_region = self.regions.get("全螢幕")

        pos_ready = self.wait_for_image_gray(
            "xboxsharecode.png",
            region=center_region,
            threshold=0.72,
            timeout=18,
            interval=0.25,
            fast_mode=True
        )
        if not pos_ready:
            self.log("中間區域暫未識別到 Xbox 分享代碼輸入框，擴大到全螢幕繼續等待...")
            pos_ready = self.wait_for_image_gray(
                "xboxsharecode.png",
                region=full_region,
                threshold=0.72,
                timeout=12,
                interval=0.25,
                fast_mode=True
            )
        if not pos_ready:
            self.log("等待 Xbox 分享代碼輸入框超時（總計約 32.5s），改為兜底固定等待 6.0s 後繼續輸入藍圖代碼。")
            time.sleep(6.0)
            return True

        self.log("已識別到 Xbox 分享代碼輸入框，開始輸入藍圖代碼。")
        time.sleep(0.2)
        return True
    # ==========================================
    # --- 初始化全域 Region ---
    # ==========================================
    def init_regions(self):
        sw, sh = pyautogui.size()
        self.update_regions_by_window(0, 0, sw, sh)

    def update_regions_by_window(self, x, y, w, h):
        self.regions = {
            "全螢幕": (x, y, w, h),
            "左上": (x, y, w // 2, h // 2),
            "右上": (x + w // 2, y, w // 2, h // 2),
            "左下": (x, y + h // 2, w // 2, h // 2),
            "右下": (x + w // 2, y + h // 2, w // 2, h // 2),
            "上": (x, y, w, h // 2),
            "下": (x, y + h // 2, w, h // 2),
            "左": (x, y, w // 2, h),
            "右": (x + w // 2, y, w // 2, h),
            "中間": (x + w // 4, y + h // 4, w // 2, h // 2),
        }

    # ==========================================
    # --- 配置管理 ---
    # ==========================================
    def load_config(self):
        # 1. 直接使用內置字典作為“絕對底本”（最安全，無視打包丟文件問題）
        self.config = {
            "race_count": 99,
            "buy_count": 30, 
            "cj_count": 30, 
            "sc_count": 30,
            "chk_1": True, 
            "chk_2": True, 
            "chk_3": True, 
            "chk_4": True,
            "next_1": 2, 
            "next_2": 3, 
            "next_3": 4, 
            "next_4": 1,
            "global_loops": 10, 
            "skill_dirs": ["right", "up", "up", "up", "left"],
            "share_code": "179383666",
            "is_xbox_platform": False,
            "is_winter_season": False,
            "auto_restart": False,
            "restart_cmd": "start steam://run/2483190", 
            "sell_mode": 1,
            "ui_delay_scale": 1.0,
            "post_get_in_car_delay": 0.5
        }
        ext_path = USER_CONFIG_FILE
        # 2. 讀取用戶的 config.json，並與底本合併（自動補全缺失項）
        if os.path.exists(ext_path):
            try:
                with open(ext_path, "r", encoding="utf-8") as f:
                    user_config = json.load(f)
                    self.config.update(user_config) 
            except Exception as e:
                self.log(f"用戶 config.json 損壞，已自動恢復預設配置。")
                
        # 3. 將最新、最完整的配置重新寫回外置檔
        try:
            with open(ext_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception:
            pass
    

    def save_config(self):
        try:
            self.config["race_count"] = int(self.entry_race.get())
            self.config["buy_count"] = int(self.entry_car.get())
            self.config["cj_count"] = int(self.entry_cj.get())
            self.config["sc_count"] = int(self.entry_sc.get())
            self.config["global_loops"] = int(self.entry_global_loop.get())
            self.config["share_code"] = "".join(c for c in self.entry_share.get() if c.isdigit())
            #self.config["base_width"] = int(self.entry_base_w.get())
            self.config["next_1"] = int(self.entry_next1.get())
            self.config["next_2"] = int(self.entry_next2.get())
            self.config["next_3"] = int(self.entry_next3.get())
            self.config["next_4"] = int(self.entry_next4.get())
            if hasattr(self, "opt_sell_mode"):
                val = self.opt_sell_mode.get()
                if "模式1" in val:
                    self.config["sell_mode"] = 1
                else:
                    self.config["sell_mode"] = 2
        except Exception:
            pass

        self.config["chk_1"] = self.var_chk1.get()
        self.config["chk_2"] = self.var_chk2.get()
        self.config["chk_3"] = self.var_chk3.get()
        self.config["chk_4"] = self.var_chk4.get()
        if hasattr(self, "var_xbox_platform"):
            self.config["is_xbox_platform"] = self.var_xbox_platform.get()
        if hasattr(self, "var_winter_season"):
            self.config["is_winter_season"] = self.var_winter_season.get()
        self.config["auto_restart"] = self.var_auto_restart.get()
        self.config["restart_cmd"] = self.le_restart_cmd.get().strip()
        try:
            if hasattr(self, "slider_ui_delay"):
                self.config["ui_delay_scale"] = round(float(self.slider_ui_delay.get()), 2)
            if hasattr(self, "slider_post_get_in_car"):
                self.config["post_get_in_car_delay"] = round(float(self.slider_post_get_in_car.get()), 2)
        except Exception:
            pass
        try:
            if hasattr(self, "entry_calc_a"):
                self.config["calc_a"] = self.entry_calc_a.get().strip()
                self.config["calc_b"] = self.entry_calc_b.get().strip()
                self.config["calc_c"] = self.entry_calc_c.get().strip()
        except Exception:
            pass
        try:
            with open(USER_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.log(f"保存配置失敗: {e}")

    def auto_calculate_pipeline(self):
        val_a = self.entry_calc_a.get().strip()
        if not val_a:
            self.log("未輸入CR，無需計算。")
            return
            
        try:
            target_cr = int(val_a)
            val_b = self.entry_calc_b.get().strip()
            cost_per_car = int(val_b) if val_b else 86000
            
            val_c = self.entry_calc_c.get().strip()
            sp_per_car = int(val_c) if val_c else 30
        except Exception:
            self.log("輸入格式有誤，請確保只輸入數位！")
            return

        if cost_per_car <= 0 or sp_per_car <= 0:
            self.log("單車成本或技能點不能為 0！")
            return

# 1. 基础转换（总车数 & 总跑图数）
        total_cars = target_cr // cost_per_car
        total_races = (total_cars * sp_per_car) // 50

        if total_races <= 0:
            self.log(f"目标金额不足(只够买{total_cars}辆车)，无法产生有效跑图！")
            return

        # 2. 核心分配逻辑
        if total_races <= 20:
            final_loops = 1
            final_races_per_loop = total_races
        else:
            import math
            loops = math.ceil(total_races / 20)
            avg_races = total_races // loops

            # 如果平均下来大于等于20次，就采用均分策略
            if avg_races >= 20:
                final_loops = loops
                final_races_per_loop = avg_races
            # 小于20次，直接拉满每个20，舍弃最后不够塞满一轮的余数
            else:
                final_races_per_loop = 20
                final_loops = total_races // 20 

        # 3. 反推每一轮买车、抽奖、卖车的具体数量
        cars_per_loop = (final_races_per_loop * 50) // sp_per_car
        
        # 强制限制其他操作最多 33 次
        if cars_per_loop > 33:
            cars_per_loop = 33

        # 4. 自動填寫到介面
        self.entry_race.delete(0, "end")
        self.entry_race.insert(0, str(final_races_per_loop))
        
        self.entry_car.delete(0, "end")
        self.entry_car.insert(0, str(cars_per_loop))
        
        self.entry_cj.delete(0, "end")
        self.entry_cj.insert(0, str(cars_per_loop))
        
        self.entry_sc.delete(0, "end")
        self.entry_sc.insert(0, str(cars_per_loop))
        
        self.entry_global_loop.delete(0, "end")
        self.entry_global_loop.insert(0, str(final_loops))

        self.log(f"✅計算完成: 總計需{total_cars}車, 共跑圖{total_races}次。分配為: {final_loops} 個大循環, 每輪跑圖 {final_races_per_loop} 次, 動作 {cars_per_loop} 輛。")
        self.save_config()

    # ==========================================
    # --- UI 佈局設計 ---
    # ==========================================
    def setup_ui(self):
        self.top_container = ctk.CTkFrame(self, fg_color="transparent")
        self.top_container.pack(fill="x", padx=18, pady=(18, 10))

        self.config_frame = ctk.CTkFrame(self.top_container, fg_color="transparent")
        self.config_frame.pack(fill="x")

        def create_box(parent, title, btn_text, btn_cmd, btn_color, def_val):
            frame = ctk.CTkFrame(
                parent,
                width=210,
                height=300,
                corner_radius=12,
                border_width=1,
                border_color="#2B2B2B",
            )
            frame.pack_propagate(False)
            frame.pack(side="left", padx=8)

            ctk.CTkLabel(
                frame,
                text=title,
                font=ctk.CTkFont(weight="bold", size=20),
            ).pack(pady=(14, 10))

            btn = ctk.CTkButton(
                frame,
                text=btn_text,
                fg_color=btn_color,
                hover_color=btn_color,
                command=btn_cmd,
                width=140,
                height=38,
                corner_radius=10,
            )
            btn.pack(pady=8, padx=10)

            entry = ctk.CTkEntry(frame, width=95, height=34, justify="center", corner_radius=8)
            entry.insert(0, str(def_val))
            entry.pack(pady=8)

            lbl = ctk.CTkLabel(
                frame,
                text=f"執行: 0 / {def_val}",
                text_color="#A0A0A0",
                font=ctk.CTkFont(size=16),
            )
            lbl.pack(pady=8)
            return frame, btn, entry, lbl

        def create_next_step(parent, var_checked, def_step, box_h=300):
            frame = ctk.CTkFrame(parent, width=120, height=box_h, corner_radius=12, border_width=1, border_color="#2B2B2B")
            frame.pack(side="left", padx=4)
            frame.pack_propagate(False)

            ctk.CTkLabel(
                frame,
                text="下一步驟",
                font=ctk.CTkFont(size=18, weight="bold"),
                text_color="#5DADE2",
            ).pack(pady=(55, 10))

            entry = ctk.CTkEntry(frame, width=60, height=34, justify="center", corner_radius=8)
            entry.insert(0, str(def_step))
            entry.pack(pady=6)

            chk = ctk.CTkCheckBox(frame, text="繼續", variable=var_checked, width=60)
            chk.pack(pady=8)

            return frame, entry, chk

        self.var_chk1 = ctk.BooleanVar(value=self.config["chk_1"])
        self.var_chk2 = ctk.BooleanVar(value=self.config["chk_2"])
        self.var_chk3 = ctk.BooleanVar(value=self.config["chk_3"])
        self.var_chk4 = ctk.BooleanVar(value=self.config.get("chk_4", True))
        self.var_xbox_platform = ctk.BooleanVar(value=self.config.get("is_xbox_platform", False))
        self.var_winter_season = ctk.BooleanVar(value=self.config.get("is_winter_season", False))

        box_race, self.btn_race, self.entry_race, self.lbl_race = create_box(
            self.config_frame,
            "1. 迴圈跑圖",
            "開始",
            lambda: self.start_pipeline("race"),
            "#1F6AA5",
            self.config.get("race_count", 99),
        )
        self.entry_share = ctk.CTkEntry(box_race, width=130, justify="center", placeholder_text="藍圖數字代碼")
        self.entry_share.insert(0, self.config.get("share_code", "890169683"))
        self.entry_share.pack(pady=4)
        self.cb_xbox_platform = ctk.CTkCheckBox(box_race, text="Xbox 平臺", variable=self.var_xbox_platform, width=130)
        self.cb_xbox_platform.pack(pady=(0, 4))
        self.btn_replace_skillcar = ctk.CTkButton(
            box_race,
            text="替換跑圖車圖",
            width=130,
            height=30,
            corner_radius=8,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            command=self.capture_skillcar_template
        )
        self.btn_replace_skillcar.pack(pady=(2, 4))
        self.btn_replace_brand = ctk.CTkButton(
            box_race,
            text="替換品牌圖",
            width=130,
            height=30,
            corner_radius=8,
            fg_color="#0F766E",
            hover_color="#115E59",
            command=self.capture_ccbrand_template
        )
        self.btn_replace_brand.pack(pady=(0, 4))

        self.next_frame1, self.entry_next1, self.chk1 = create_next_step(
            self.config_frame, self.var_chk1, self.config.get("next_1", 2)
        )

        box_car, self.btn_car, self.entry_car, self.lbl_car = create_box(
            self.config_frame,
            "2. 批量買車",
            "開始",
            lambda: self.start_pipeline("buy"),
            "#2EA043",
            self.config.get("buy_count", 30),
        )
        self.entry_car.bind("<KeyRelease>", self.sync_buy_to_sell)

        self.next_frame2, self.entry_next2, self.chk2 = create_next_step(
            self.config_frame, self.var_chk2, self.config.get("next_2", 3)
        )

        self.box_cj = ctk.CTkFrame(
            self.config_frame,
            width=360,
            height=300,
            corner_radius=12,
            border_width=1,
            border_color="#2B2B2B",
        )
        self.box_cj.pack_propagate(False)
        self.box_cj.pack(side="left", padx=8)

        top_cj = ctk.CTkFrame(self.box_cj, fg_color="transparent")
        top_cj.pack(fill="x", pady=10)

        left_cj = ctk.CTkFrame(top_cj, fg_color="transparent")
        left_cj.pack(side="left", padx=10)

        ctk.CTkLabel(left_cj, text="3. 超級抽獎", font=ctk.CTkFont(weight="bold", size=20)).pack(pady=(0, 8))

        self.btn_cj = ctk.CTkButton(
            left_cj,
            text="開始",
            width=120,
            height=38,
            corner_radius=10,
            fg_color="#8E44AD",
            hover_color="#8E44AD",
            command=lambda: self.start_pipeline("cj"),
        )
        self.btn_cj.pack(pady=5)

        self.entry_cj = ctk.CTkEntry(left_cj, width=95, height=34, justify="center", corner_radius=8)
        self.entry_cj.insert(0, str(self.config.get("cj_count", 30)))
        self.entry_cj.pack(pady=5)

        self.lbl_cj = ctk.CTkLabel(
            left_cj,
            text=f"執行: 0 / {self.config.get('cj_count', 30)}",
            text_color="#A0A0A0",
            font=ctk.CTkFont(size=14),
        )
        self.lbl_cj.pack(pady=(2, 8))

        dir_frame = ctk.CTkFrame(left_cj, fg_color="transparent")
        dir_frame.pack(pady=4)

        for text, val in [("↑", "up"), ("↓", "down"), ("←", "left"), ("→", "right")]:
            ctk.CTkButton(
                dir_frame,
                text=text,
                width=30,
                height=28,
                corner_radius=8,
                command=lambda x=val: self.add_skill_dir(x),
            ).pack(side="left", padx=2)

        ctk.CTkButton(
            left_cj,
            text="清除矩陣",
            width=90,
            height=28,
            corner_radius=8,
            fg_color="#C0392B",
            hover_color="#A93226",
            command=self.clear_skill_dir,
        ).pack(pady=8)

        self.grid_frame = ctk.CTkFrame(top_cj, fg_color="transparent")
        self.grid_frame.pack(side="right", padx=12)

        self.grid_labels = [[None] * 4 for _ in range(4)]
        for r in range(4):
            for c in range(4):
                lbl = ctk.CTkLabel(
                    self.grid_frame,
                    text="",
                    width=28,
                    height=28,
                    corner_radius=5,
                    fg_color="#444444",
                )
                lbl.grid(row=r, column=c, padx=4, pady=4)
                self.grid_labels[r][c] = lbl
        ctk.CTkLabel(
            self.grid_frame,
            text="技能樹",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#A0A0A0",
        ).grid(row=4, column=0, columnspan=4, pady=(8, 0))

        self.next_frame3, self.entry_next3, self.chk3 = create_next_step(
            self.config_frame, self.var_chk3, self.config.get("next_3", 4)
        )

        box_sc, self.btn_sc, self.entry_sc, self.lbl_sc = create_box(
            self.config_frame,
            "4. 移除車輛",
            "！！開始！！",
            lambda: self.start_pipeline("sell"),
            "#D97706",
            self.config.get("sc_count", 30),
        )
        # ====== 【新增】：移除車輛模式下拉選擇 ======
        self.opt_sell_mode = ctk.CTkOptionMenu(
            box_sc,
            values=["模式1: 識圖移除模式", "模式2: 移除最近添加"],
            width=180,
            height=28,
            corner_radius=6,
            font=ctk.CTkFont(size=12),
            fg_color="#D97706",
            button_color="#B96705",
            button_hover_color="#995704"
        )
        # 讀取配置，預設選模式1
        saved_mode = self.config.get("sell_mode", 1)
        if str(saved_mode) == "1" or "模式1" in str(saved_mode):
            self.opt_sell_mode.set("模式1: 識圖移除模式")
        else:
            self.opt_sell_mode.set("模式2: 移除最近添加")
            
        self.opt_sell_mode.pack(pady=4)
        self.cb_winter_season = ctk.CTkCheckBox(
            box_sc,
            text="是否為冬季",
            variable=self.var_winter_season,
            width=180
        )
        self.cb_winter_season.pack(pady=(0, 4))
        # ==========================================
        self.next_frame4, self.entry_next4, self.chk4 = create_next_step(
        self.config_frame, self.var_chk4, self.config.get("next_4", 1)
        )
        # ====== 抽離到底部的全域設置欄 (放在上方) ======
        # 【修改1】把 self.top_container 改成了 self
        self.global_settings_frame = ctk.CTkFrame(self, fg_color="#2B2B2B", height=45, corner_radius=10)
        # 【修改2】加上了 padx=18，讓它和上下邊緣對齊
        self.global_settings_frame.pack(fill="x", padx=18, pady=(15, 0))
        self.global_settings_frame.pack_propagate(False)
        ctk.CTkLabel(
            self.global_settings_frame, 
            text="⚙️ 迴圈與守護設置", 
            font=ctk.CTkFont(weight="bold", size=15), 
            text_color="#F1C40F"
        ).pack(side="left", padx=(15, 20))
        ctk.CTkLabel(self.global_settings_frame, text="大循環次數:").pack(side="left", padx=(10, 5))
        self.entry_global_loop = ctk.CTkEntry(self.global_settings_frame, width=70, height=28, justify="center")
        self.entry_global_loop.insert(0, str(self.config.get("global_loops", 10)))
        self.entry_global_loop.pack(side="left", padx=(0, 20))
        self.var_auto_restart = ctk.BooleanVar(value=self.config.get("auto_restart", True))
        self.cb_auto_restart = ctk.CTkCheckBox(self.global_settings_frame, text="遊戲閃退（爆顯存）自動重啟", variable=self.var_auto_restart)
        self.cb_auto_restart.pack(side="left", padx=(10, 20))
        ctk.CTkLabel(self.global_settings_frame, text="啟動命令(CMD):").pack(side="left", padx=(10, 5))
        self.le_restart_cmd = ctk.CTkEntry(self.global_settings_frame, width=250, height=28)
        self.le_restart_cmd.insert(0, self.config.get("restart_cmd", "start steam://run/2483190"))
        self.le_restart_cmd.pack(side="left", padx=(0, 20))
        # ====== 【新增】：測試自動開機流程按鈕 ======
        self.btn_test_boot = ctk.CTkButton(
            self.global_settings_frame, 
            text="測試啟動流程", 
            fg_color="#8E44AD", 
            hover_color="#7D3C98", 
            width=110, 
            height=28, 
            command=self.start_test_boot
        )
        #self.btn_test_boot.pack(side="left", padx=(0, 20))
        
        # =================================

        self.delay_settings_frame = ctk.CTkFrame(self, fg_color="#2B2B2B", height=58, corner_radius=10)
        self.delay_settings_frame.pack(fill="x", padx=18, pady=(10, 0))
        self.delay_settings_frame.pack_propagate(False)

        ctk.CTkLabel(
            self.delay_settings_frame,
            text="關鍵時序設置",
            font=ctk.CTkFont(weight="bold", size=15),
            text_color="#60A5FA"
        ).pack(side="left", padx=(15, 18))

        ctk.CTkLabel(self.delay_settings_frame, text="升級與調教動畫時間:").pack(side="left", padx=(0, 6))
        self.lbl_post_get_in_car_value = ctk.CTkLabel(
            self.delay_settings_frame,
            text=self.format_delay_text(self.config.get("post_get_in_car_delay", 0.5)),
            width=46
        )
        self.lbl_post_get_in_car_value.pack(side="left", padx=(0, 6))
        self.slider_post_get_in_car = ctk.CTkSlider(
            self.delay_settings_frame,
            from_=0.3,
            to=1.5,
            number_of_steps=12,
            width=150,
            command=lambda v: self.lbl_post_get_in_car_value.configure(text=self.format_delay_text(v))
        )
        self.slider_post_get_in_car.set(float(self.config.get("post_get_in_car_delay", 0.5)))
        self.slider_post_get_in_car.pack(side="left", padx=(0, 18))

        ctk.CTkLabel(self.delay_settings_frame, text="介面等待倍率:").pack(side="left", padx=(0, 6))
        self.lbl_ui_delay_value = ctk.CTkLabel(
            self.delay_settings_frame,
            text=f"{float(self.config.get('ui_delay_scale', 1.0)):.1f}x",
            width=40
        )
        self.lbl_ui_delay_value.pack(side="left", padx=(0, 6))
        self.slider_ui_delay = ctk.CTkSlider(
            self.delay_settings_frame,
            from_=0.5,
            to=2.0,
            number_of_steps=15,
            width=150,
            command=lambda v: self.lbl_ui_delay_value.configure(text=f"{float(v):.1f}x")
        )
        self.slider_ui_delay.set(float(self.config.get("ui_delay_scale", 1.0)))
        self.slider_ui_delay.pack(side="left", padx=(0, 10))


        # ====== 新增：智慧計算分配工具列 (放在下方) ======
        # 【修改1】把 self.top_container 改成了 self
        self.calc_frame = ctk.CTkFrame(self, fg_color="#2B2B2B", height=45, corner_radius=10)
        # 【修改2】加上了 padx=18，讓它和上下邊緣對齊
        self.calc_frame.pack(fill="x", padx=18, pady=(10, 0))
        self.calc_frame.pack_propagate(False)
        ctk.CTkLabel(
            self.calc_frame, 
            text="次數計算器", 
            font=ctk.CTkFont(weight="bold", size=15), 
            text_color="#2EA043"
        ).pack(side="left", padx=(15, 20))
        ctk.CTkLabel(self.calc_frame, text="CR:").pack(side="left", padx=(0, 5))
        self.entry_calc_a = ctk.CTkEntry(self.calc_frame, width=110, height=28, placeholder_text="留空不計算")
        self.entry_calc_a.insert(0, self.config.get("calc_a", ""))
        self.entry_calc_a.pack(side="left", padx=(0, 15))
        ctk.CTkLabel(self.calc_frame, text="單車成本(CR):").pack(side="left", padx=(0, 5))
        self.entry_calc_b = ctk.CTkEntry(self.calc_frame, width=70, height=28)
        self.entry_calc_b.insert(0, self.config.get("calc_b", "81700"))
        self.entry_calc_b.pack(side="left", padx=(0, 15))
        ctk.CTkLabel(self.calc_frame, text="單車技能點:").pack(side="left", padx=(0, 5))
        self.entry_calc_c = ctk.CTkEntry(self.calc_frame, width=50, height=28)
        self.entry_calc_c.insert(0, self.config.get("calc_c", "30"))
        self.entry_calc_c.pack(side="left", padx=(0, 15))
        ctk.CTkButton(
            self.calc_frame,
            text="計算並應用",
            width=90,
            height=28,
            fg_color="#D35400",
            hover_color="#A04000",
            command=self.auto_calculate_pipeline
        ).pack(side="left", padx=(0, 15))
        
        # 動態限制輸入框長度（只允許數字並截斷）
        def limit_len(evt, widget, max_l):
            val = "".join(c for c in widget.get() if c.isdigit())
            if len(val) > max_l:
                val = val[:max_l]
            if widget.get() != val:
                widget.delete(0, "end")
                widget.insert(0, val)
        self.entry_calc_a.bind("<KeyRelease>", lambda e: limit_len(e, self.entry_calc_a, 10))
        self.entry_calc_b.bind("<KeyRelease>", lambda e: limit_len(e, self.entry_calc_b, 7))
        self.entry_calc_c.bind("<KeyRelease>", lambda e: limit_len(e, self.entry_calc_c, 2))
        # ==========================================
        #ctk.CTkLabel(self.global_settings_frame, text="圖片原寬（不要修改）:").pack(side="left", padx=(10, 5))
        #self.entry_base_w = ctk.CTkEntry(self.global_settings_frame, width=70, height=28, justify="center")
        #self.entry_base_w.insert(0, str(self.config.get("base_width", 2560)))
        #self.entry_base_w.pack(side="left", padx=(0, 20))

        self.entry_next1.bind("<FocusOut>", lambda e: self.normalize_step_entry(self.entry_next1, 2))
        self.entry_next2.bind("<FocusOut>", lambda e: self.normalize_step_entry(self.entry_next2, 3))
        self.entry_next3.bind("<FocusOut>", lambda e: self.normalize_step_entry(self.entry_next3, 4))
        self.entry_next4.bind("<FocusOut>", lambda e: self.normalize_step_entry(self.entry_next4, 1))

        if not self.entry_sc.get().strip():
            self.entry_sc.insert(0, "30")

        # === 全新的橫向迷你UI設計 ===
        self.mini_frame = ctk.CTkFrame(self, fg_color="#1E1E1E", corner_radius=10)

        # 1. 日誌區 (最左側，佔據主要伸縮空間)
        self.mini_log_box = ctk.CTkTextbox(self.mini_frame, state="disabled", wrap="word", font=ctk.CTkFont(size=13), fg_color="#2B2B2B")
        self.mini_log_box.pack(side="left", fill="both", expand=True, padx=(10, 5), pady=10)

        # 2. 資訊區 (垂直排列任務狀態和耗時)
        self.mini_info_frame = ctk.CTkFrame(self.mini_frame, fg_color="transparent")
        self.mini_info_frame.pack(side="left", fill="y", padx=5, pady=10)

        self.lbl_mini_task = ctk.CTkLabel(self.mini_info_frame, text="當前任務: 等待中", font=ctk.CTkFont(size=14, weight="bold"), text_color="#3498DB")
        self.lbl_mini_task.pack(pady=(5, 2), anchor="w")

        self.lbl_mini_prog = ctk.CTkLabel(self.mini_info_frame, text="任務進度: 0 / 0", font=ctk.CTkFont(size=13))
        self.lbl_mini_prog.pack(pady=2, anchor="w")

        self.lbl_mini_loop = ctk.CTkLabel(self.mini_info_frame, text="大循環: 0 / 0", font=ctk.CTkFont(size=13))
        self.lbl_mini_loop.pack(pady=2, anchor="w")

        self.lbl_mini_time = ctk.CTkLabel(self.mini_info_frame, text="總耗時: 00:00:00", font=ctk.CTkFont(size=13))
        self.lbl_mini_time.pack(pady=2, anchor="w")
        # 3. 按鈕區 (靠右排列)
        self.btn_mini_stop = ctk.CTkButton(self.mini_frame, text="⏸ 停止 (F8)", fg_color="#DA3633", hover_color="#B02A37", width=90, font=ctk.CTkFont(weight="bold"), command=self.stop_all)
        self.btn_mini_stop.pack(side="left", fill="y", padx=5, pady=10)

        # ====== 【新增】迷你面板上的暫停按鈕 ======
        self.btn_mini_pause = ctk.CTkButton(self.mini_frame, text="⏸ 暫停 (F9)", fg_color="#F1C40F", hover_color="#D4AC0D", width=90, font=ctk.CTkFont(weight="bold"), command=self.toggle_pause)
        self.btn_mini_pause.pack(side="left", fill="y", padx=5, pady=10)

        self.btn_mini_support = ctk.CTkButton(self.mini_frame, text="關於", fg_color="#F97316", hover_color="#EA580C", width=60, font=ctk.CTkFont(weight="bold"), command=self.open_support_window)
        self.btn_mini_support.pack(side="left", fill="y", padx=(5, 10), pady=10)


        self.bottom_frame = ctk.CTkFrame(self, fg_color="transparent", height=200)
        self.bottom_frame.pack(fill="both", expand=True, padx=18, pady=(6, 12))

        self.btn_stop = ctk.CTkButton(
            self.bottom_frame,
            text="⏸ 等待指令 (F8)",
            fg_color="#3A3A3A",
            hover_color="#4A4A4A",
            width=180,
            height=60,
            corner_radius=12,
            font=ctk.CTkFont(size=16, weight="bold"),
            command=self.stop_all,
        )
        self.btn_stop.pack(side="left", padx=6)

        self.log_box = ctk.CTkTextbox(
            self.bottom_frame,
            state="disabled",
            wrap="word",
            corner_radius=12,
            height=120,
            font=ctk.CTkFont(size=18),
        )
        self.log_box.pack(side="left", fill="both", expand=True, padx=8)

        self.btn_support = ctk.CTkButton(
            self,
            text="關於此版本 / 檢查更新",
            fg_color="#F97316",
            hover_color="#EA580C",
            height=42,
            corner_radius=12,
            font=ctk.CTkFont(weight="bold", size=15),
            command=self.open_support_window,
        )
        self.btn_support.pack(fill="x", padx=18, pady=(6, 12))
        self.sync_buy_to_sell()

        #ocr載入 
    
    def open_support_window(self):
        if self.support_win is not None and self.support_win.winfo_exists():
            self.support_win.focus()
            return

        self.support_win = ctk.CTkToplevel(self)
        self.support_win.title("關於此版本")
        self.support_win.geometry("380x420")
        self.support_win.attributes("-topmost", True)
        self.support_win.resizable(False, False)

        try:
            icon_path = get_asset_path("icon.ico")
            if icon_path:
                self.support_win.iconbitmap(icon_path)
        except Exception:
            pass

        self.support_win.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 380) // 2
        y = self.winfo_y() + (self.winfo_height() - 420) // 2
        self.support_win.geometry(f"+{x}+{y}")

        ctk.CTkLabel(
            self.support_win,
            text=APP_DISPLAY_NAME,
            font=ctk.CTkFont(weight="bold", size=18),
            text_color="#F97316",
        ).pack(pady=(20, 6))

        ctk.CTkLabel(
            self.support_win,
            text=f"v{CURRENT_VERSION}",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(pady=4)

        ctk.CTkLabel(
            self.support_win,
            text=APP_ATTRIBUTION,
            text_color="#A0A0A0",
            font=ctk.CTkFont(size=12),
        ).pack(pady=(2, 10))

        about_box = ctk.CTkTextbox(self.support_win, height=120, width=320, corner_radius=10)
        about_box.pack(padx=20, pady=8, fill="x")
        about_box.insert("end", "這是一個基於上游項目修改的 fork 版本。\n\n")
        about_box.insert("end", "當前介面標題、流程邏輯和範本替換功能已按本地修改版本調整。\n")
        about_box.insert("end", "發佈到你自己的 GitHub 時，建議同時保留對上游專案的引用說明。")
        about_box.configure(state="disabled")

        ctk.CTkFrame(self.support_win, height=2, fg_color="#333333").pack(fill="x", padx=20, pady=10)

        self.lbl_version = ctk.CTkLabel(
            self.support_win,
            text=f"當前版本: v{CURRENT_VERSION}",
            text_color="gray",
            font=ctk.CTkFont(size=12),
        )
        self.lbl_version.pack()

        def check_update_logic():
            self.ui_call(self.lbl_version.configure, text="正在連接 Github...", text_color="#3498DB")
            try:
                remote_ver = "0.0.0"
                remote_url = ""

                # Prefer the lightweight manifest, but fall back to GitHub's
                # latest release API so a forgotten version.json update does
                # not silently hide a newer release.
                manifest_url = UPDATE_MANIFEST_URL
                resp = requests.get(manifest_url, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    remote_ver = str(data.get("version", "0.0.0"))
                    remote_url = str(data.get("url", ""))

                release_api_url = build_latest_release_api_url(PROJECT_REPO_URL)
                if release_api_url:
                    api_resp = requests.get(
                        release_api_url,
                        timeout=5,
                        headers={"Accept": "application/vnd.github+json"},
                    )
                    if api_resp.status_code == 200:
                        release_data = api_resp.json()
                        api_ver = str(release_data.get("tag_name", "")).strip()
                        api_url = str(release_data.get("html_url", "")).strip()
                        if parse_version(api_ver) > parse_version(remote_ver):
                            remote_ver = api_ver
                            remote_url = api_url

                if parse_version(remote_ver) > parse_version(CURRENT_VERSION):
                    if remote_url.startswith("https://github.com/"):
                        self.ui_call(
                            self.lbl_version.configure,
                            text=f"發現新版本 v{remote_ver}，已打開流覽器！",
                            text_color="#2EA043",
                        )
                        webbrowser.open(remote_url)
                    else:
                        self.ui_call(
                            self.lbl_version.configure,
                            text="發現更新，但連結不可信，已攔截",
                            text_color="#DA3633",
                        )
                else:
                    self.ui_call(
                        self.lbl_version.configure,
                        text=f"當前已是最新版本 (v{CURRENT_VERSION})",
                        text_color="gray",
                    )
            except Exception:
                self.ui_call(
                    self.lbl_version.configure,
                    text="檢查更新失敗 (網路超時或無法訪問)",
                    text_color="#DA3633",
                )

        btn_frame = ctk.CTkFrame(self.support_win, fg_color="transparent")
        btn_frame.pack(pady=6)

        ctk.CTkButton(
            btn_frame,
            text="檢查更新",
            width=100,
            height=30,
            fg_color="#444444",
            hover_color="#555555",
            command=lambda: threading.Thread(target=check_update_logic, daemon=True).start(),
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            btn_frame,
            text="當前項目",
            width=100,
            height=30,
            fg_color="#2EA043",
            hover_color="#238636",
            command=lambda: webbrowser.open(PROJECT_REPO_URL),
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            btn_frame,
            text="上游項目",
            width=100,
            height=30,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            command=lambda: webbrowser.open(UPSTREAM_REPO_URL),
        ).pack(side="left", padx=5)
    def update_timer(self):
        if not self.is_running:
            return
        elapsed = int(time.time() - self.start_time)
        hrs = elapsed // 3600
        mins = (elapsed % 3600) // 60
        secs = elapsed % 60
        time_str = f"總耗時: {hrs:02d}:{mins:02d}:{secs:02d}"
        try:
            self.lbl_mini_time.configure(text=time_str)
        except Exception: pass
        
        if self.is_running:
            self.after(1000, self.update_timer)

    def update_running_ui(self, task_name="", current_val=0, max_val=0):
        try:
            if task_name:
                self.ui_call(self.lbl_mini_task.configure, text=f"當前任務: {task_name}")
            if max_val > 0:
                self.ui_call(self.lbl_mini_prog.configure, text=f"執行進度: {current_val} / {max_val}")
        except Exception:
            pass

    # ==========================================
    # --- 核心操作與流程控制 ---
    # ==========================================
    def hw_key_down(self, key):
        if key not in DIK_CODES:
            return
        scan_code, extended = DIK_CODES[key]
        flags = 0x0008 | (0x0001 if extended else 0)
        extra = ctypes.c_ulong(0)
        ii_ = Input_I()
        ii_.ki = KeyBdInput(0, scan_code, flags, 0, ctypes.pointer(extra))
        x = Input(ctypes.c_ulong(1), ii_)
        SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))

    def hw_key_up(self, key):
        if key not in DIK_CODES:
            return
        scan_code, extended = DIK_CODES[key]
        flags = 0x000A | (0x0001 if extended else 0)
        extra = ctypes.c_ulong(0)
        ii_ = Input_I()
        ii_.ki = KeyBdInput(0, scan_code, flags, 0, ctypes.pointer(extra))
        x = Input(ctypes.c_ulong(1), ii_)
        SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))

    def hw_press(self, key, delay=0.08):
        self.check_pause()  # <--- 【新增】如果正在暫停，腳本會在此處無限等待直到恢復
        if not self.is_running:
            return
        self.hw_key_down(key)
        time.sleep(delay)
        self.hw_key_up(key)
    #副屏支持
    def hw_mouse_move(self, x, y):
        # 獲取多顯示器組成的整個“虛擬桌面”座標和尺寸
        SM_XVIRTUALSCREEN = 76
        SM_YVIRTUALSCREEN = 77
        SM_CXVIRTUALSCREEN = 78
        SM_CYVIRTUALSCREEN = 79
        left = ctypes.windll.user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        top = ctypes.windll.user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        width = ctypes.windll.user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        height = ctypes.windll.user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        if width == 0 or height == 0:
            return
        # 映射到 0~65535 的絕對虛擬坐標系統
        calc_x = int((x - left) * 65535 / width)
        calc_y = int((y - top) * 65535 / height)
        # MOUSEEVENTF_MOVE = 0x0001, MOUSEEVENTF_ABSOLUTE = 0x8000, MOUSEEVENTF_VIRTUALDESK = 0x4000
        flags = 0x0001 | 0x8000 | 0x4000 
        extra = ctypes.c_ulong(0)
        ii_ = Input_I()
        ii_.mi = MouseInput(calc_x, calc_y, 0, flags, 0, ctypes.pointer(extra))
        cmd = Input(ctypes.c_ulong(0), ii_)
        SendInput(1, ctypes.pointer(cmd), ctypes.sizeof(cmd))
    def game_click(self, pos, double=False):
        self.check_pause()  # <--- 【新增】攔截滑鼠點擊
        if not self.is_running or not pos:
            return
        x, y = int(pos[0]), int(pos[1])
        
        # 使用多屏相容的硬體級移動
        self.hw_mouse_move(x, y)
        time.sleep(0.2)
        for _ in range(2 if double else 1):
            pydirectinput.mouseDown()
            time.sleep(0.1)
            pydirectinput.mouseUp()
            time.sleep(0.1)
        time.sleep(0.1)
        # 移開滑鼠 10 圖元，防止遊戲裡的懸浮提示框遮擋下一次截圖
        try:
            gx, gy, gw, gh = self.regions["全螢幕"]
            # 移動到遊戲左上角向內偏移 5 個圖元，確保在遊戲內但絕對不會擋住任何中間UI
            self.hw_mouse_move(gx + 5, gy + 5)
        except Exception:
            # 兜底：如果獲取不到視窗座標，移到絕對螢幕左上角
            self.hw_mouse_move(5, 5)
        time.sleep(0.2)

    def is_current_car_slot_position(self, pos):
        if not pos:
            return False

        full_region = self.regions.get("全螢幕")
        if not full_region:
            return False

        x, y, w, h = full_region
        px, py = pos
        rel_x = (px - x) / max(w, 1)
        rel_y = (py - y) / max(h, 1)

        # 當前選中車輛卡片通常位於螢幕偏左中部，右側下一張車卡不應落入這個範圍
        return 0.22 <= rel_x <= 0.40 and 0.20 <= rel_y <= 0.52

    def move_to_game_coord(self, x, y):
        """
        將滑鼠移動到以【遊戲視窗左上角】為起點的 (x, y) 座標。
        例如傳入 (5, 5)，就會移動到遊戲內左上角 5 圖元的安全位置。
        """
        try:
            gx, gy, gw, gh = self.regions["全螢幕"]
            abs_x = gx + x
            abs_y = gy + y
            self.hw_mouse_move(abs_x, abs_y)
        except Exception:
            # 兜底：如果獲取不到視窗座標，就直接當絕對座標移動
            self.hw_mouse_move(x, y)
    
    def add_skill_dir(self, direction):
        self.config["skill_dirs"].append(direction)
        self.update_skill_grid()
        self.save_config()

    def clear_skill_dir(self):
        self.config["skill_dirs"].clear()
        self.update_skill_grid()
        self.save_config()

    def update_skill_grid(self):
        for r in range(4):
            for c in range(4):
                self.grid_labels[r][c].configure(fg_color="#333333")

        curr_r, curr_c = 3, 0
        self.grid_labels[curr_r][curr_c].configure(fg_color="#3498DB")
        valid_dirs = []

        for d in self.config["skill_dirs"]:
            if d == "up":
                curr_r -= 1
            elif d == "down":
                curr_r += 1
            elif d == "left":
                curr_c -= 1
            elif d == "right":
                curr_c += 1

            if 0 <= curr_r < 4 and 0 <= curr_c < 4:
                self.grid_labels[curr_r][curr_c].configure(fg_color="#3498DB")
                valid_dirs.append(d)
            else:
                break

        self.config["skill_dirs"] = valid_dirs

    def get_module_label(self, step_name=None):
        return STEP_LABELS.get(step_name or self.current_step_name, "系統")

    def normalize_log_step(self, text):
        if not text:
            return ""

        cleaned = str(text).strip()
        cleaned = cleaned.strip(".。!！?？~ ")
        cleaned = re.sub(r"^\[[^\]]+\]\s*", "", cleaned)
        cleaned = re.sub(r"^[▶>]+", "", cleaned).strip()
        if not cleaned:
            return ""

        parts = re.split(r"[：:（(，,。!！?？]", cleaned, maxsplit=1)
        cleaned = parts[0].strip() if parts else cleaned
        return cleaned[:24]

    def infer_log_level(self, message, level=None):
        if level:
            return str(level).upper()

        debug_markers = (
            "[ImageMatch]",
            "[GrayMatch]",
            "[GrayMatchAny]",
            "[ComboMatch]",
            "[StableMatch]",
            "[FastMatch]",
            "[AlphaMatch]",
            "[AlphaMatchAny]",
            "[排他攔截]",
            "[終極安全-通過]",
            "[輪廓黑科技]",
        )
        if any(marker in message for marker in debug_markers):
            return "DEBUG"

        error_markers = ("異常", "致命錯誤", "嚴重警告", "Traceback")
        if any(marker in message for marker in error_markers):
            return "ERROR"

        warning_markers = ("未找到", "未識別到", "超時", "失敗", "警告", "重試")
        if any(marker in message for marker in warning_markers):
            return "WARNING"

        return "INFO"

    def refresh_run_targets(self):
        def safe_int(entry_widget, fallback=0):
            try:
                return int(entry_widget.get())
            except Exception:
                return fallback

        self.current_targets = {
            "race": safe_int(self.entry_race, self.config.get("race_count", 0)),
            "buy": safe_int(self.entry_car, self.config.get("buy_count", 0)),
            "cj": safe_int(self.entry_cj, self.config.get("cj_count", 0)),
            "sell": safe_int(self.entry_sc, self.config.get("sc_count", 0)),
        }

    def get_small_loop_progress(self):
        counter_map = {
            "race": self.race_counter,
            "buy": self.car_counter,
            "cj": self.cj_counter,
            "sell": self.sc_count,
        }
        current = counter_map.get(self.current_step_name)
        total = self.current_targets.get(self.current_step_name, 0)
        if current is None or total <= 0:
            return None
        return current, total

    def set_log_context(self, step_name=None, phase=None, total_loops=None):
        if step_name:
            self.current_step_name = step_name
        if phase:
            self.current_phase_name = self.normalize_log_step(phase) or str(phase)
        if total_loops is not None:
            self.global_loop_total = max(0, int(total_loops))

    def ensure_debug_log_dir(self):
        try:
            os.makedirs(DEBUG_LOG_DIR, exist_ok=True)
        except Exception:
            pass

    def start_run_log(self, entry_name):
        self.ensure_debug_log_dir()
        self.log_session_id = time.strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", entry_name or "run")
        self.log_file_path = os.path.join(DEBUG_LOG_DIR, f"run-{self.log_session_id}-{safe_name}.log")

        header_lines = [
            "=" * 90,
            f"會話開始時間: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"入口模組: {self.get_module_label(entry_name)}",
            f"日誌檔: {self.log_file_path}",
            f"應用目錄: {APP_DIR}",
            f"Python版本: {sys.version.split()[0]}",
            "=" * 90,
        ]
        for line in header_lines:
            self._append_log_file_line(line)

    def _append_log_file_line(self, line):
        if not self.log_file_path:
            return
        try:
            with self.log_file_lock:
                with open(self.log_file_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception:
            pass

    def log(self, message, level=None, step=None, module=None):
        level_name = self.infer_log_level(message, level)

        if step:
            self.current_phase_name = self.normalize_log_step(step) or str(step)
        elif level_name != "DEBUG":
            inferred_step = self.normalize_log_step(message)
            if inferred_step:
                self.current_phase_name = inferred_step

        module_label = self.get_module_label(module or self.current_step_name)
        step_label = self.normalize_log_step(step) if step else self.current_phase_name or "未命名步驟"
        level_label = LOG_LEVEL_LABELS.get(level_name, level_name)
        curr_time = time.strftime("%H:%M:%S")
        full_time = time.strftime("%Y-%m-%d %H:%M:%S")

        loop_parts = []
        if self.global_loop_current > 0 and self.global_loop_total > 0:
            loop_parts.append(f"大循環 {self.global_loop_current}/{self.global_loop_total}")
        small_loop = self.get_small_loop_progress()
        if small_loop:
            loop_parts.append(f"小迴圈 {small_loop[0]}/{small_loop[1]}")

        ui_prefix_parts = [f"[{curr_time}]", f"[{module_label}]", f"[{step_label}]"]
        if loop_parts:
            ui_prefix_parts.append(f"[{' | '.join(loop_parts)}]")
        ui_msg = " ".join(ui_prefix_parts) + f" {message}"

        file_prefix_parts = [
            f"[{full_time}]",
            f"[{level_name}]",
            f"[模組:{module_label}]",
            f"[步驟:{step_label}]",
        ]
        if self.global_loop_current > 0 and self.global_loop_total > 0:
            file_prefix_parts.append(f"[大循環:{self.global_loop_current}/{self.global_loop_total}]")
        if small_loop:
            file_prefix_parts.append(f"[小迴圈:{small_loop[0]}/{small_loop[1]}]")
        file_msg = " ".join(file_prefix_parts) + f" {message}"
        self._append_log_file_line(file_msg)

        def write_ui():
            try:
                if level_name == "DEBUG":
                    return
                self.log_box.configure(state="normal")
                self.log_box.insert("end", ui_msg + "\n")
                self.log_box.see("end")
                self.log_box.configure(state="disabled")
                if hasattr(self, "mini_log_box"):
                    self.mini_log_box.configure(state="normal")
                    self.mini_log_box.insert("end", ui_msg + "\n")
                    self.mini_log_box.see("end")
                    self.mini_log_box.configure(state="disabled")
            except Exception:
                pass
        self.ui_call(write_ui)

    def refresh_template_cache_for(self, template_name):
        actual_path = get_img_path(template_name)

        self.template_cache.pop(actual_path, None)
        if hasattr(self, "template_gray_cache"):
            self.template_gray_cache.pop(("gray", actual_path), None)

        stale_scaled_keys = [k for k in self.scaled_template_cache.keys() if k[0] == actual_path]
        for key in stale_scaled_keys:
            self.scaled_template_cache.pop(key, None)

        if hasattr(self, "scaled_edge_template_cache"):
            stale_edge_keys = [k for k in self.scaled_edge_template_cache.keys() if k[0] == actual_path]
            for key in stale_edge_keys:
                self.scaled_edge_template_cache.pop(key, None)

        if hasattr(self, "edge_template_cache"):
            self.edge_template_cache.pop(actual_path, None)

        self.file_template_cache = {}

        try:
            if os.path.exists(TEMPLATE_CACHE_FILE):
                os.remove(TEMPLATE_CACHE_FILE)
            if os.path.exists(TEMPLATE_META_FILE):
                os.remove(TEMPLATE_META_FILE)
        except Exception:
            pass

    def capture_skillcar_template(self):
        self.start_template_capture("skillcar.png", "跑圖車輛圖")

    def capture_ccbrand_template(self):
        self.start_template_capture("CCbrand.png", "品牌圖")

    def start_template_capture(self, template_name, display_name):
        if self.is_running:
            self.log(f"請先停止當前任務，再替換{display_name}。")
            return

        self.log(f"準備替換{display_name}：將自動切回遊戲，並開啟框選截圖。")
        if not self.check_and_focus_game():
            self.log("未檢測到遊戲視窗，無法開始框選截圖。")
            return

        self.after(250, lambda: self.begin_template_capture_overlay(template_name, display_name))

    def begin_template_capture_overlay(self, template_name, display_name):
        try:
            self.attributes("-topmost", False)
            self.withdraw()
            self.update_idletasks()
        except Exception:
            pass

        vx = ctypes.windll.user32.GetSystemMetrics(76)
        vy = ctypes.windll.user32.GetSystemMetrics(77)
        vw = ctypes.windll.user32.GetSystemMetrics(78)
        vh = ctypes.windll.user32.GetSystemMetrics(79)

        overlay = tk.Toplevel(self)
        overlay.title("截取跑圖車輛圖片")
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        overlay.attributes("-alpha", 0.28)
        overlay.configure(bg="black")
        overlay.geometry(f"{vw}x{vh}+{vx}+{vy}")

        canvas = tk.Canvas(overlay, bg="black", highlightthickness=0, cursor="crosshair")
        canvas.pack(fill="both", expand=True)

        hint_text = canvas.create_text(
            40,
            30,
            anchor="w",
            text=f"按住左鍵框選{display_name}區域，鬆開後預覽確認；右鍵或 Esc 取消。",
            fill="white",
            font=("Microsoft YaHei UI", 13, "bold")
        )

        state = {"start_x": None, "start_y": None, "rect": None}

        def cleanup(show_main=True):
            try:
                overlay.destroy()
            except Exception:
                pass

            if show_main:
                try:
                    self.deiconify()
                    self.lift()
                    self.attributes("-topmost", False)
                    self.center_window()
                except Exception:
                    pass

        def cancel_capture(event=None):
            self.log("已取消跑圖車輛圖片替換。")
            cleanup(show_main=True)

        def on_press(event):
            state["start_x"] = event.x_root
            state["start_y"] = event.y_root
            if state["rect"] is not None:
                canvas.delete(state["rect"])
            state["rect"] = canvas.create_rectangle(
                event.x_root - vx,
                event.y_root - vy,
                event.x_root - vx,
                event.y_root - vy,
                outline="#4ADE80",
                width=2
            )

        def on_drag(event):
            if state["rect"] is None:
                return
            canvas.coords(
                state["rect"],
                state["start_x"] - vx,
                state["start_y"] - vy,
                event.x_root - vx,
                event.y_root - vy
            )

        def on_release(event):
            if state["start_x"] is None or state["start_y"] is None:
                cancel_capture()
                return

            x1 = min(state["start_x"], event.x_root)
            y1 = min(state["start_y"], event.y_root)
            x2 = max(state["start_x"], event.x_root)
            y2 = max(state["start_y"], event.y_root)

            if x2 - x1 < 20 or y2 - y1 < 20:
                self.log("截圖區域過小，已取消本次替換。")
                cleanup(show_main=True)
                return

            try:
                img = ImageGrab.grab(bbox=(int(x1), int(y1), int(x2), int(y2)), all_screens=True)
                cleanup(show_main=True)
                self.show_template_preview_dialog(template_name, display_name, img)
            except Exception as e:
                self.log(f"截取{display_name}失敗: {e}")
                cleanup(show_main=True)

        overlay.bind("<Escape>", cancel_capture)
        overlay.bind("<Button-3>", cancel_capture)
        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)

        overlay.focus_force()

    def show_template_preview_dialog(self, template_name, display_name, image):
        preview_win = ctk.CTkToplevel(self)
        preview_win.title(f"確認替換{display_name}")
        preview_win.geometry("420x420")
        preview_win.attributes("-topmost", True)
        preview_win.resizable(False, False)

        try:
            icon_path = get_asset_path("icon.ico")
            if icon_path:
                preview_win.iconbitmap(icon_path)
        except Exception:
            pass

        ctk.CTkLabel(
            preview_win,
            text=f"預覽{display_name}",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(pady=(16, 8))

        preview_size = (320, 220)
        try:
            preview_img = image.copy()
            preview_img.thumbnail(preview_size)
            ctk_img = ctk.CTkImage(light_image=preview_img, size=preview_img.size)
            lbl_preview = ctk.CTkLabel(preview_win, text="", image=ctk_img)
            lbl_preview.image = ctk_img
            lbl_preview.pack(pady=8)
        except Exception:
            ctk.CTkLabel(preview_win, text="預覽載入失敗，但仍可選擇保存。", text_color="gray").pack(pady=18)

        ctk.CTkLabel(
            preview_win,
            text=f"將覆蓋 images/{template_name}",
            text_color="#A0A0A0"
        ).pack(pady=(4, 12))

        btn_frame = ctk.CTkFrame(preview_win, fg_color="transparent")
        btn_frame.pack(pady=10)

        def save_capture():
            try:
                save_path = os.path.join(APP_DIR, "images", template_name)
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                image.save(save_path)
                self.refresh_template_cache_for(template_name)
                threading.Thread(target=self.prepare_template_cache, daemon=True).start()
                self.log(f"{display_name}已更新: {save_path}")
            except Exception as e:
                self.log(f"保存{display_name}失敗: {e}")
            finally:
                try:
                    preview_win.destroy()
                except Exception:
                    pass

        def cancel_preview():
            self.log(f"已取消替換{display_name}。")
            try:
                preview_win.destroy()
            except Exception:
                pass

        ctk.CTkButton(
            btn_frame,
            text="保存替換",
            width=120,
            fg_color="#16A34A",
            hover_color="#15803D",
            command=save_capture
        ).pack(side="left", padx=8)

        ctk.CTkButton(
            btn_frame,
            text="取消",
            width=120,
            fg_color="#4B5563",
            hover_color="#374151",
            command=cancel_preview
        ).pack(side="left", padx=8)

        preview_win.focus_force()

    def start_pipeline(self, start_step):
        if self.is_running:
            return

        self.is_running = True
        self.save_config()

        # 隱藏大窗的所有元素
        self.config_frame.pack_forget()
        self.global_settings_frame.pack_forget()
        self.calc_frame.pack_forget()
        self.top_container.pack_forget()
        if hasattr(self, "bottom_frame"):
            self.bottom_frame.pack_forget()
        self.btn_support.pack_forget()

        # 顯示新的迷你橫向 UI
        self.mini_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # ====== 計算 15% 高度 40% 寬度 ======
        last_x, last_y, last_w, last_h = self.regions["全螢幕"]
        if last_w <= 0: last_w = self.winfo_screenwidth()
        if last_h <= 0: last_h = self.winfo_screenheight()

        calc_w = int(last_w * 0.40)
        calc_h = int(last_h * 0.15)
        # 設置一個兜底最小值，防止解析度過低時文字擠壓導致崩潰
        calc_w = max(calc_w, 650)
        calc_h = max(calc_h, 150)

        pos_x = last_x + last_w - calc_w - 20
        pos_y = last_y + 20

        self.attributes("-topmost", True)
        self.geometry(f"{calc_w}x{calc_h}+{pos_x}+{pos_y}")
        
        # 啟動計時器
        self.start_time = time.time()
        self.update_timer()

        
        self.update_running_ui("初始化中...")
        self.race_counter = 0
        self.car_counter = 0
        self.cj_counter = 0
        self.sc_count = 0
        self.global_loop_current = 0
        self.global_loop_total = 0
        self.current_phase_name = "啟動任務"
        self.current_step_name = start_step
        self.refresh_run_targets()
        self.start_run_log(start_step)
        self.log(f"本次詳細日誌檔: {self.log_file_path}", step="日誌初始化", module="system")

        def runner():
            if not self.check_and_focus_game():
                self.stop_all()
                return

            steps = ["race", "buy", "cj", "sell"]
            curr_idx = steps.index(start_step)

            try:
                total_loops = int(self.entry_global_loop.get())
            except Exception:
                total_loops = self.config.get("global_loops", 10)
            self.set_log_context(step_name=start_step, phase="任務啟動", total_loops=total_loops)
            self.global_loop_current = 1
            if hasattr(self, "lbl_mini_loop"):
                self.ui_call(self.lbl_mini_loop.configure, text=f"大循環: {self.global_loop_current} / {total_loops}")
            self.log(f"任務啟動，入口模組: {self.get_module_label(start_step)}，計畫大循環: {total_loops}", step="任務啟動")

            # 【新增】：全域連續失敗計數器
            continuous_failures = 0 
            # 【你可以修改這裡】：設置全域允許的最大連續恢復次數（比如 3 次）
            MAX_RECOVERIES = 10 

            while self.is_running:
                step_name = steps[curr_idx]
                success = False
                self.set_log_context(step_name=step_name, phase="模組開始")
                self.log(f"開始執行{self.get_module_label(step_name)}模組", step="模組開始")

                try:
                    if step_name == "race":
                        success = self.logic_race(int(self.entry_race.get()))
                    elif step_name == "buy":
                        success = self.logic_buy_car(int(self.entry_car.get()))
                    elif step_name == "cj":
                        success = self.logic_super_wheelspin_v2(int(self.entry_cj.get()))
                    elif step_name == "sell":
                        # ====== 【新增】：判斷下拉清單的模式 ======
                        sell_mode = self.opt_sell_mode.get()
                        if "模式1" in sell_mode:
                            success = self.find_and_remove_consumable_car(int(self.entry_sc.get()))
                        else:
                            success = self.sell_consumable_car(int(self.entry_sc.get()))
                        # =========================================
                except Exception as e:
                    self.log(f"執行模組 {step_name} 時異常: {e}")
                    self._append_log_file_line(traceback.format_exc().rstrip())
                    success = False

                if not self.is_running:
                    break

                if not success:
                    continuous_failures += 1
                    
                    # 檢查是否超過最大容忍次數
                    if continuous_failures > MAX_RECOVERIES:
                        self.log(f"!!! 警告：連續 {continuous_failures} 次觸發中斷點恢復仍未能解決問題！")
                        self.log("為防止遊戲陷入閉環，強制終止當前所有任務，請人工檢查遊戲狀態。")
                        break # 直接跳出 while，停止腳本
                        
                    self.log(f"正在進行全域恢復 (第 {continuous_failures}/{MAX_RECOVERIES} 次允許的重試)...")
                    
                    if self.attempt_recovery_v2():
                        continue # 恢復成功，回到 while 頂部再次嘗試這個任務
                    else:
                        self.log("致命錯誤：連退回菜單/重啟也失敗了，徹底停止。")
                        break
                else:
                    # 只要這一個大步驟成功跑完了，就把連續失敗次數清零，獎勵它繼續跑！
                    continuous_failures = 0
                    self.log(f"{self.get_module_label(step_name)}模組執行完成", step="模組完成")
                #v1.0.1
                # ====== 核心流轉與無限迴圈邏輯 ======
                next_idx = curr_idx + 1 # 默認前往下一步
                if curr_idx == 0:
                    if self.var_chk1.get():
                        try: next_idx = max(0, min(3, int(self.entry_next1.get()) - 1))
                        except Exception: next_idx = 1
                    else: break
                elif curr_idx == 1:
                    if self.var_chk2.get():
                        try: next_idx = max(0, min(3, int(self.entry_next2.get()) - 1))
                        except Exception: next_idx = 2
                    else: break
                elif curr_idx == 2:
                    if self.var_chk3.get():
                        try: next_idx = max(0, min(3, int(self.entry_next3.get()) - 1))
                        except Exception: next_idx = 3
                    else: break
                elif curr_idx == 3:
                    if self.var_chk4.get():
                        try: next_idx = max(0, min(3, int(self.entry_next4.get()) - 1))
                        except Exception: next_idx = 0
                    else: break

                if next_idx <= curr_idx:
                    self.global_loop_current += 1
                    
                    if self.global_loop_current > total_loops:
                        self.log("達到設定的總迴圈次數，任務圓滿結束。")
                        break
                        
                    self.log(f"開啟新一輪大循環 ({self.global_loop_current}/{total_loops})")
                    
                    if hasattr(self, "lbl_mini_loop"):
                        self.ui_call(self.lbl_mini_loop.configure, text=f"大循環: {self.global_loop_current} / {total_loops}")

                    self.race_counter = 0
                    self.car_counter = 0
                    self.cj_counter = 0
                    self.sc_count = 0

                    if self.should_reset_cj_memory_on_new_loop():
                        self.memory_car_page = 0
                        self.log("已進入新一輪大循環，且超級抽獎下一步為刪車，翻頁記憶已清空。")
                    else:
                        self.log("已進入新一輪大循環，超級抽獎未接刪車，保留翻頁記憶繼續搜索。")
                
                curr_idx = next_idx

            self.stop_all()

        self.current_thread = threading.Thread(target=runner, daemon=True)
        self.current_thread.start()

    def stop_all(self):
        if not self.is_running:
            return

        self.is_running = False
        self.current_step_name = "system"
        self.current_phase_name = "停止任務"
        self.is_paused = False  # <--- 【新增】徹底停止時必須解除暫停鎖

        for key in DIK_CODES.keys():
            self.hw_key_up(key)

        for key in ["w", "e", "y", "enter", "esc", "up", "down", "left", "right", "space", "backspace"]:
            self.hw_key_up(key)

        try:
            pydirectinput.mouseUp()
        except Exception:
            pass

        def restore_ui():
            if hasattr(self, "mini_frame"):
                self.mini_frame.pack_forget()
                
            # 【核心修復】：先讓大容器裡的東西全部解綁，洗牌重來
            self.config_frame.pack_forget()
            self.global_settings_frame.pack_forget()
            self.calc_frame.pack_forget()
            
            # 1. 鋪設最外層大容器
            self.top_container.pack(fill="x", padx=18, pady=(18, 10))
            
            # 2. 依次按順序塞入三個模組，完美保證從上到下的順序！
            self.config_frame.pack(fill="x")
            self.global_settings_frame.pack(fill="x", pady=(15, 0))
            self.calc_frame.pack(fill="x", pady=(10, 0))
            
            # 3. 鋪設底部的日誌和按鈕
            if hasattr(self, "bottom_frame"):
                self.bottom_frame.pack(fill="both", expand=True, padx=18, pady=(6, 12))
            self.btn_support.pack(fill="x", padx=18, pady=(6, 12))
            
            # 恢復視窗原本的狀態
            self.btn_stop.configure(text="等待指令 (F8)", fg_color="#3A3A3A", hover_color="#4A4A4A")
            self.attributes("-topmost", False)
            self.geometry("1800x800")
            self.center_window()

        self.ui_call(restore_ui)
        self.log("!!! 任務已停止，所有物理按鍵狀態已強制重置")
    def start_test_boot(self):
        """獨立運行的測試開機流程"""
        if self.is_running:
            self.log("已有任務正在運行，請先點擊停止後再測試啟動流程！")
            return
            
        self.is_running = True
        self.save_config()
        
        # ==========================================
        # 【新增修復】：隱藏大窗的所有元素，進入迷你模式
        # ==========================================
        self.config_frame.pack_forget()
        self.global_settings_frame.pack_forget()
        self.calc_frame.pack_forget()
        self.top_container.pack_forget()
        if hasattr(self, "bottom_frame"):
            self.bottom_frame.pack_forget()
        self.btn_support.pack_forget()

        # 顯示新的迷你橫向 UI
        self.mini_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # 啟動計時器與狀態文字更新
        self.update_running_ui("測試啟動流程...")
        self.start_time = time.time()
        self.update_timer()
        # ==========================================
        self.global_loop_current = 1
        self.global_loop_total = 1
        self.current_step_name = "boot"
        self.current_phase_name = "自動開機測試"
        self.refresh_run_targets()
        self.start_run_log("boot")

        self.log("====== 開始獨立測試自動開機與識別流程 ======", step="任務啟動")
        self.log(f"本次詳細日誌檔: {self.log_file_path}", step="日誌初始化", module="system")
        
        def test_runner():
            success = self.restart_game_and_boot(force_test=True)
            if success:
                self.log("✅ 測試結束：自動開機、A/B/C狀態機識別並到達功能表完美跑通！")
            else:
                self.log("❌ 測試結束：自動開機流程失敗，請檢查截圖或日誌。")
            self.stop_all() # 測試完畢自動停止腳本，自動恢復回大視窗狀態
            
        self.current_thread = threading.Thread(target=test_runner, daemon=True)
        self.current_thread.start()
    # ==========================================
    # --- 【新增】暫停與恢復邏輯 ---
    # ==========================================
    def toggle_pause(self):
        if not self.is_running:
            return
            
        self.is_paused = not self.is_paused
        
        if self.is_paused:
            self.log("⏸ 任務已暫停 (按 F9 或點擊按鈕恢復)")
            # 強制鬆開所有可能按住的按鍵，防止車自己開走或UI亂跳
            for key in ["w", "e", "y", "enter", "esc", "up", "down", "left", "right", "space", "backspace"]:
                self.hw_key_up(key)
            try:
                pydirectinput.mouseUp()
            except Exception:
                pass
            # 改變按鈕UI
            if hasattr(self, "btn_mini_pause"):
                self.ui_call(self.btn_mini_pause.configure, text="▶ 繼續 (F9)", fg_color="#2EA043", hover_color="#238636")
        else:
            self.log("▶ 任務已恢復")
            if hasattr(self, "btn_mini_pause"):
                self.ui_call(self.btn_mini_pause.configure, text="⏸ 暫停 (F9)", fg_color="#F1C40F", hover_color="#D4AC0D")

    def check_pause(self):
        """核心阻塞器：任何動作前調用此方法，如果是暫停狀態，將在此無限等待"""
        while self.is_paused and self.is_running:
            time.sleep(0.1)

    
    def pause_for_manual_recovery(self, reason=""):
        if not self.is_running:
            return False

        if reason:
            self.log(reason, level="WARNING")
        self.log("已自動暫停任務，請手動調整遊戲狀態；處理完成後點擊繼續(F9)以重新開始當前流程。", level="WARNING", step="等待人工處理")

        if not self.is_paused:
            self.toggle_pause()

        while self.is_running and self.is_paused:
            time.sleep(0.2)

        if not self.is_running:
            return False

        self.log("檢測到已點擊繼續，準備重新檢查遊戲狀態並重試當前流程...", step="恢復重試")
        if not self.check_and_focus_game():
            self.log("繼續後仍未能聚焦到遊戲，請檢查遊戲是否仍在運行。", level="ERROR")
            return False
        return True

    def start_hotkey_listener(self):
        def hotkey_thread():
            def on_press(k):
                if k == keyboard.Key.f8:
                    self.stop_all()
                elif k == keyboard.Key.f9:  # <--- 【新增】F9 快速鍵
                    self.toggle_pause()

            with keyboard.Listener(on_press=on_press) as listener:
                listener.join()

        threading.Thread(target=hotkey_thread, daemon=True).start()

   
    # ==========================================
    # --- 邏輯保障 ---
    # ==========================================
    # 【新增】：強制切換英文鍵盤與關閉中文狀態
    def set_english_input(self):
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return
            # 策略1：嘗試切美式鍵盤
            hkl = ctypes.windll.user32.LoadKeyboardLayoutW("00000409", 1)
            ctypes.windll.user32.PostMessageW(hwnd, 0x0050, 0, hkl) 
            # 策略2：底層強制關閉當前中文輸入法的中文狀態(絕殺)
            WM_IME_CONTROL = 0x0283
            IMC_SETOPENSTATUS = 0x0006
            ctypes.windll.user32.SendMessageW(hwnd, WM_IME_CONTROL, IMC_SETOPENSTATUS, 0)
            
            self.log("已自動切換英文鍵盤/關閉中文輸入法狀態。")
        except Exception as e:
            self.log(f"自動防中文輸入設置失敗: {e}")
    def check_and_focus_game(self):
        self.log("檢查遊戲進程 (forzahorizon6.exe)...")
        try:
            CREATE_NO_WINDOW = 0x08000000
            cmd = 'tasklist /FI "IMAGENAME eq forzahorizon6.exe" /NH /FO CSV'
            output = subprocess.check_output(cmd, shell=True, text=True, creationflags=CREATE_NO_WINDOW)

            if "forzahorizon6.exe" not in output.lower():
                self.log("未發現 forzahorizon6.exe 進程！(請確保遊戲已運行)")
                return False

            target_pid = None
            for line in output.strip().split("\n"):
                parts = line.split('","')
                if len(parts) >= 2 and "forzahorizon6.exe" in parts[0].lower():
                    target_pid = int(parts[1].replace('"', ""))
                    break

            if not target_pid:
                self.log("找到進程但無法解析PID！")
                return False

            hwnds = []

            def foreach_window(hwnd, lParam):
                if ctypes.windll.user32.IsWindowVisible(hwnd):
                    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        window_pid = ctypes.c_ulong()
                        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
                        if window_pid.value == target_pid:
                            hwnds.append(hwnd)
                return True

            EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            ctypes.windll.user32.EnumWindows(EnumWindowsProc(foreach_window), 0)

            if hwnds:
                hwnd = hwnds[0]
                if ctypes.windll.user32.IsIconic(hwnd):
                    ctypes.windll.user32.ShowWindow(hwnd, 9)
                else:
                    ctypes.windll.user32.ShowWindow(hwnd, 5)
                    
                ctypes.windll.user32.SetForegroundWindow(hwnd)
                time.sleep(0.5)
                # ====== 【新增】：強制關閉中文輸入法 ======
                self.set_english_input()
                # ==========================================
                try:
                    # 1. 更新識圖區域為遊戲實際視窗區域（識圖必須在遊戲窗口內）
                    client_rect = win32gui.GetClientRect(hwnd)
                    pt = win32gui.ClientToScreen(hwnd, (0, 0))
                    gx, gy = pt[0], pt[1]
                    gw, gh = client_rect[2], client_rect[3]
                    # ====== 【核心修復】：攔截啟動小窗/防作弊閃屏 ======
                    # 如果視窗寬度和高度太小，說明絕對不是正常的遊戲主畫面
                    if gw < 1000 or gh < 600:
                        self.log(f"攔截到過小視窗 ({gw}x{gh})，判定為啟動閃屏，等待主視窗載入...")
                        return False 
                    # ====================================================
                    self.update_regions_by_window(gx, gy, gw, gh)

                    # 2. 獲取該視窗所在的物理顯示器邊界
                    MONITOR_DEFAULTTONEAREST = 2
                    hMonitor = ctypes.windll.user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
                    class RECT(ctypes.Structure):
                        _fields_ = [
                            ("left", ctypes.c_long), 
                            ("top", ctypes.c_long), 
                            ("right", ctypes.c_long), 
                            ("bottom", ctypes.c_long)
                        ]
                    class MONITORINFO(ctypes.Structure):
                        _fields_ = [
                            ("cbSize", ctypes.c_ulong), 
                            ("rcMonitor", RECT), 
                            ("rcWork", RECT), 
                            ("dwFlags", ctypes.c_ulong)
                        ]
                    mi = MONITORINFO()
                    mi.cbSize = ctypes.sizeof(MONITORINFO)
                    
                    if ctypes.windll.user32.GetMonitorInfoW(hMonitor, ctypes.byref(mi)):
                        mx = mi.rcMonitor.left
                        my = mi.rcMonitor.top
                        mw = mi.rcMonitor.right - mi.rcMonitor.left
                        mh = mi.rcMonitor.bottom - mi.rcMonitor.top
                    else:
                        # 兜底：如果獲取不到螢幕邊界，就用遊戲視窗邊界
                        mx, my, mw, mh = gx, gy, gw, gh

                    # ====== 【修改】：小視窗精准吸附所在顯示器的右上角 ======
                    def snap_to_game():
                        if self.is_running:
                            calc_w = int(mw * 0.40)
                            calc_h = int(mh * 0.15)
                            calc_w = max(calc_w, 650)
                            calc_h = max(calc_h, 150)
                            
                            # 放置在當前顯示器的右上角（預留20圖元邊距）
                            pos_x = mx + mw - calc_w - 20
                            pos_y = my + 20
                            self.geometry(f"{calc_w}x{calc_h}+{pos_x}+{pos_y}")
                    self.ui_call(snap_to_game)
                    # ==========================================
                except Exception as e:
                    self.log(f"獲取窗口座標失敗: {e}")

                time.sleep(1.0)
                return True

        except Exception as e:
            self.log(f"檢查進程異常: {e}")
            return False

        return False

    def restart_game_and_boot(self, force_test=False):
        # 除非點擊了測試按鈕(force_test)，否則檢查設置裡是否允許自動重啟
        if not force_test:
            auto_restart = getattr(self, "var_auto_restart", None)
            if auto_restart is None or not auto_restart.get():
                self.log("未開啟自動重啟，任務結束。")
                return False

        self.log("觸發啟動機制！正在拉起遊戲...")
        try:
            cmd_widget = getattr(self, "le_restart_cmd", None)
            cmd_str = cmd_widget.get() if cmd_widget else self.config.get("restart_cmd", "start steam://run/2483190")
            os.system(cmd_str)
        except Exception as e:
            self.log(f"執行啟動命令失敗: {e}")
            return False

        self.log("等待遊戲進程出現 (最多60秒)...")
        process_found = False
        for _ in range(120):
            if hasattr(self, "check_pause"): self.check_pause()
            if not self.is_running: return False
            if self.check_and_focus_game():
                process_found = True
                break
            time.sleep(1)
            
        if not process_found:
            self.log("未檢測到遊戲進程，啟動失敗。")
            return False

        self.log("遊戲進程已啟動，進入動態識別階段 (限制5分鐘)...")
        start_time = time.time()
        
        passed_screen_1 = False      # 記錄是否已經按過畫面1的回車
        last_continue_time = 0       # 記錄最後一次看到/點擊“繼續按鈕”的時間戳記

        while self.is_running and time.time() - start_time < 300:
            if hasattr(self, "check_pause"): self.check_pause()

            # ==============================
            # 畫面1：尋找左下角 horizon6.png -> 按回車
            # ==============================
            if not passed_screen_1:
                pos_h6 = None
                
                # 策略A：透明圖識別
                pos_h6 = self.find_image_transparent("horizon6.png", region=self.regions["全螢幕"], threshold=0.60, fast_mode=False)
                
                # 策略B：邊緣輪廓識別兜底！
                if not pos_h6:
                    try:
                        screen_bgr = self.capture_region(self.regions["全螢幕"])
                        tpl_bgr, _ = self.load_template("horizon6.png")
                        if tpl_bgr is not None:
                            screen_edge = self.to_edge_image(screen_bgr)
                            tpl_edge = self.to_edge_image(tpl_bgr)
                            
                            for scale in self.get_scales_to_try(fast_mode=False):
                                t_e = tpl_edge if scale == 1.0 else cv2.resize(tpl_edge, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                                h, w = t_e.shape[:2]
                                if h > screen_edge.shape[0] or w > screen_edge.shape[1] or h < 5 or w < 5: continue
                                
                                res = cv2.matchTemplate(screen_edge, t_e, cv2.TM_CCOEFF_NORMED)
                                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                                
                                if max_val >= 0.40: 
                                    self.log(f"[輪廓黑科技] 無視背景命中！得分: {max_val:.2f} 縮放: {scale:.2f}")
                                    pos_h6 = (max_loc[0] + w//2 + self.regions["全螢幕"][0], max_loc[1] + h//2 + self.regions["全螢幕"][1])
                                    break
                    except Exception:
                        pass
                
                if pos_h6:
                    self.log("✅ 成功識別到 畫面1 (horizon6.png)，按下【回車鍵】...")
                    time.sleep(1)
                    for _ in range(2):
                        self.hw_press("enter")
                        time.sleep(1)
                    passed_screen_1 = True
                    # 啟動畫面2的倒計時機制，如果在後續的尋找中一直沒看到畫面2，也會在30秒後嘗試進菜單
                    last_continue_time = time.time() 
                    self.log("已確認畫面1，強制等待 10 秒等待畫面2載入...")
                    time.sleep(10) # 等待10秒
                    continue
                else:
                    self.log("未找到畫面1。正在使用全比例深度掃描...")

            # ==============================
            # 畫面2：尋找右下角 continue-b 或 continue-w -> 死磕點擊
            # ==============================
            # 只有在通過了畫面1的前提下，才去尋找畫面2
            if passed_screen_1:
                pos_continue = self.find_any_image_gray(["continue-b.png", "continue-w.png"], threshold=0.75)
                if pos_continue:
                    self.log("識別到 畫面2 (繼續按鈕)，進行點擊...")
                    self.game_click(pos_continue)
                    
                    # 【核心邏輯】：只要點擊了，就刷新時間戳記！
                    last_continue_time = time.time() 
                    
                    time.sleep(3.0) # 點擊後過3秒再試，只要有就繼續點
                    continue

                # ==============================
                # 狀態轉化：進入漫遊與菜單呼出
                # ==============================
                # 如果當前時間 距離【最後一次點擊畫面2的時間】已經超過了 30秒，且期間再也沒找到過
                time_since_last_seen = time.time() - last_continue_time
                if time_since_last_seen >= 30.0:
                    self.log("✅ 已經連續 30 秒未再發現繼續按鈕，判定為漫遊載入完畢！開始嘗試進入菜單...")
                    
                    if getattr(self, "enter_menu")(): 
                        self.log("🎉 驗證成功：已成功進入遊戲主菜單！啟動流程完美結束。")
                        return True
                    else:
                        self.log("普通進入菜單失敗(可能還在黑屏或有新彈窗)，重置 30秒倒計時，繼續觀察...")
                        # 如果沒進成功，重置時間戳記，腳本會繼續找畫面2，或者再等30秒重試進菜單
                        last_continue_time = time.time()
            
            time.sleep(1.0) # 每次總迴圈休息1秒，防止CPU佔用過高

        self.log("自動啟動超時(5分鐘)，放棄搶救。")
        return False


    def attempt_recovery(self):
        self.log("任務執行異常中斷，準備執行中斷點恢復流程...")
        if not self.check_and_focus_game():
            # 遊戲沒開或者進程沒了，直接走重啟流程
            if not self.restart_game_and_boot():
                return False
        else:
            # 進程還在，使用【高級狀態機】嘗試動態退回
            if not self.advanced_enter_menu():
                self.log("高級動態退回失敗(可能遊戲卡死或致命報錯)，準備強殺進程並重啟...")
                try:
                    os.system('taskkill /F /IM forzahorizon6.exe /T')
                    time.sleep(4)
                except Exception: pass
                
                # 殺進程後重新拉起
                if not self.restart_game_and_boot():
                    return False
        self.log("環境重置成功！即將從中斷處繼續剩餘任務。")
        return True

    def attempt_recovery_v2(self):
        self.log("任務執行異常中斷，準備執行中斷點恢復流程...")
        if not self.check_and_focus_game():
            if not self.restart_game_and_boot():
                return False
        else:
            if not self.advanced_enter_menu():
                return self.pause_for_manual_recovery("高級動態退回失敗，已改為自動暫停，不再強殺遊戲。請手動調整遊戲狀態後點擊繼續。")

        self.log("環境重置成功！即將從中斷處繼續剩餘任務。")
        return True

    def wait_for_freeroam(self):
        self.log("驗證漫遊狀態...")
        for i in range(100):
            if not self.is_running:
                return False

            if self.find_image("anna.png", region=self.regions["左下"], threshold=0.5):
                self.log("驗證成功：已確認處於遊戲漫遊介面。")
                return True

            self.log(f"重試返回漫遊介面({i + 1}/100)")
            self.hw_press("esc")

            for _ in range(20):
                if not self.is_running:
                    return False
                time.sleep(0.1)

        self.log("多次嘗試驗證漫遊介面失敗，嘗試進入功能表。")
        return True

    def recover_to_menu(self):
        self.log("開始嘗試退回主菜單 (強制ESC兜底)...")
        return self.enter_menu()

    def is_in_menu(self):    
        return self.find_image_gray(
            "collectionjournal.png",
            region=self.regions["左"],
            threshold=0.70,
            fast_mode=True
        )
    def enter_menu(self):
        self.log("正在嘗試進入主菜單 (按ESC驗證)...")
  
        # 連續嘗試 60 次，大概花費 40~60 秒
        for i in range(60):
            if not self.is_running:
                return False
                

            pos_menu = self.find_image_gray("collectionjournal.png", region=self.regions["左"], threshold=0.70, fast_mode=True)
            
            if pos_menu:
                self.log(f"成功定位到菜單錨點！({i + 1}/60)")
                time.sleep(0.5)
                return True
                
            self.log(f"未在主菜單，按下 ESC... ({i + 1}/60)")
            self.hw_press("esc")
            # 給遊戲一點動畫載入時間
            time.sleep(1.0)
            
        self.log("60 次 ESC 嘗試均未進入功能表，請檢查遊戲狀態。")
        return False
    def advanced_enter_menu(self):
        """
        高級狀態機退回：專門用於故障恢復。
        能夠識別中途的特定彈窗、中間過渡畫面，並執行點擊，沒找到目標才按 ESC。
        """
        self.log("正在使用【高級復原模式】嘗試退回主功能表...")
        
        # ==========================================
        # 動態讀取 images/obstacles/ 裡的所有圖片
        # ==========================================
        obstacles_dir = os.path.join("images", "obstacles")
        dynamic_obstacles = []
        
        # 檢查資料夾是否存在
        if os.path.exists(obstacles_dir):
            for file in os.listdir(obstacles_dir):
                # 只要是 png 或 jpg 格式的圖片，統統加進來
                if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                    # 拼成 "obstacles/檔案名.png"，這樣 find_any_image_gray 就能正確找到路徑
                    dynamic_obstacles.append(f"obstacles/{file}")
        
        if not dynamic_obstacles:
            self.log("提示：images/obstacles/ 資料夾為空或不存在，將只使用 ESC 退回。")
        # 連續嘗試 80 次，處理較長的隨機過程
        for i in range(80):
            if hasattr(self, "check_pause"): self.check_pause() # 相容暫停功能
            if not self.is_running:
                return False
                
            # 1. 終極判斷：是不是已經在菜單了？
            if self.is_in_menu():
                self.log(f"成功定位到菜單錨點！(嘗試次數: {i + 1})")
                time.sleep(0.5)
                return True

            # 2. 致命錯誤排查 (檢測到顯存不足，強制休息 10 分鐘)
            if self.find_image_gray("VRAMNE.png", region=self.regions["全螢幕"], threshold=0.75, fast_mode=True):
                self.log("!!! 嚴重警告: 檢測到顯存不足 (VRAMNE.png) 報錯！")
                self.log("為保護硬體並恢復顯存，強制機器冷卻 10 分鐘 (600秒)...")
                
                # 安全的 10 分鐘休眠，期間允許隨時點擊停止(F8)
                for _ in range(600):
                    if hasattr(self, "check_pause"): self.check_pause()
                    if not self.is_running: return False
                    time.sleep(1)
                    
                self.log("10 分鐘冷卻完畢！準備強殺進程並重啟遊戲...")
                return False

            # 3. 動態掃描所有可能的彈窗 / 需要點擊的中間圖片
            pos_obs = self.find_any_image_gray(dynamic_obstacles, region=self.regions["全螢幕"], threshold=0.75, fast_mode=True)
            if pos_obs:
                self.log(f"退回途中檢測到已知圖片/彈窗，點擊推進... ({i+1}/80)")
                self.game_click(pos_obs)
                time.sleep(1.5) # 給畫面跳轉留出動畫時間
                continue # 點擊後，跳過本輪，不要按 ESC
                
# 4. 遇到死胡同，按 ESC 退回，並定期按 Enter 盲解強制彈窗
            if (i + 1) % 10 == 0:
                self.log(f"已連續嘗試 {i + 1} 次仍卡住，嘗試按下 Enter 解除強制確認彈窗...")
                self.hw_press("enter")
                time.sleep(1.5)
            else:
                self.log(f"未在主功能表且無已知特定圖片，按下 ESC... ({i + 1}/80)")
                self.hw_press("esc")
                time.sleep(1.2) # 給遊戲一點動畫載入時間
            
        self.log("80 次動態嘗試均未進入功能表，高級退回失敗。")
        return False
    # ==========================================
    # --- 圖像尋找 ---
    # ==========================================
    def load_template(self, template_path):
        actual_path = get_img_path(template_path)
        cache_key = actual_path

        if cache_key in self.template_cache:
            return self.template_cache[cache_key], actual_path

        tpl = cv2.imread(actual_path, cv2.IMREAD_COLOR)
        if tpl is not None:
            self.template_cache[cache_key] = tpl
        return tpl, actual_path
    def load_template_gray(self, template_path):
        actual_path = get_img_path(template_path)
        cache_key = ("gray", actual_path)
        if not hasattr(self, "template_gray_cache"):
            self.template_gray_cache = {}
        if cache_key in self.template_gray_cache:
            return self.template_gray_cache[cache_key]
        tpl = cv2.imread(actual_path, cv2.IMREAD_GRAYSCALE)
        if tpl is not None:
            self.template_gray_cache[cache_key] = tpl
        return tpl
    def get_images_root_dir(self):
        ext_dir = os.path.join(APP_DIR, "images")
        if os.path.isdir(ext_dir):
            return ext_dir

        int_dir = os.path.join(INTERNAL_DIR, "images")
        if os.path.isdir(int_dir):
            return int_dir

        return None

    def get_template_meta(self):
        images_dir = self.get_images_root_dir()
        meta_data = {}
        if not images_dir:
            return meta_data

        for root, _, files in os.walk(images_dir):
            for file in files:
                if not file.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):
                    continue

                path = os.path.join(root, file)
                rel_path = os.path.relpath(path, images_dir).replace("\\", "/")

                try:
                    stat = os.stat(path)
                    meta_data[rel_path] = {
                        "mtime": stat.st_mtime,
                        "size": stat.st_size,
                    }
                except Exception:
                    pass

        return meta_data

    def is_template_cache_valid(self):
        if not os.path.exists(TEMPLATE_CACHE_FILE) or not os.path.exists(TEMPLATE_META_FILE):
            return False

        try:
            with open(TEMPLATE_META_FILE, "r", encoding="utf-8") as f:
                old_meta = json.load(f)
        except Exception:
            return False

        new_meta = self.get_template_meta()
        return old_meta == new_meta

    def build_template_file_cache(self):
        self.log("開始構建範本快取檔案...")
        os.makedirs(CACHE_DIR, exist_ok=True)

        images_dir = self.get_images_root_dir()
        if not images_dir:
            self.log("未找到 images 目錄，無法構建範本緩存。")
            return False

        cache_data = {}
        meta_data = self.get_template_meta()

        scales = self.get_scales_to_try(fast_mode=False)

        for rel_path in meta_data.keys():
            img_path = os.path.join(images_dir, rel_path)
            tpl = cv2.imread(img_path, cv2.IMREAD_COLOR)
            if tpl is None:
                continue

            cache_data[rel_path] = {}
            for scale in scales:
                try:
                    if scale == 1.0:
                        scaled = tpl.copy()
                    else:
                        scaled = cv2.resize(tpl, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

                    cache_data[rel_path][str(round(scale, 3))] = scaled
                except Exception:
                    continue

        try:
            with open(TEMPLATE_CACHE_FILE, "wb") as f:
                pickle.dump(cache_data, f, protocol=pickle.HIGHEST_PROTOCOL)

            with open(TEMPLATE_META_FILE, "w", encoding="utf-8") as f:
                json.dump(meta_data, f, ensure_ascii=False, indent=2)

            self.log("範本快取檔案構建完成。")
            return True
        except Exception as e:
            self.log(f"寫入範本緩存失敗: {e}")
            return False

    def load_template_file_cache(self):
        try:
            with open(TEMPLATE_CACHE_FILE, "rb") as f:
                self.file_template_cache = pickle.load(f)
            self.log("範本快取檔案載入成功。")
            return True
        except Exception as e:
            self.log(f"載入範本緩存失敗: {e}")
            self.file_template_cache = {}
            return False

    def prepare_template_cache(self):
        os.makedirs(CACHE_DIR, exist_ok=True)

        if self.is_template_cache_valid():
            if self.load_template_file_cache():
                return

        self.log("範本緩存不存在或已失效，開始後臺重建（這可能需要幾秒鐘）...")
        if self.build_template_file_cache():
            self.template_cache.clear()
            self.scaled_template_cache.clear()
            self.load_template_file_cache()

    def capture_region(self, region=None):
        try:
            if region:
                x, y, w, h = region
                # 將浮點數轉換為整數，並計算右下角邊界
                bbox = (int(x), int(y), int(x + w), int(y + h))
                # all_screens=True 允許跨越所有顯示器截圖
                screen = ImageGrab.grab(bbox=bbox, all_screens=True)
            else:
                screen = ImageGrab.grab(all_screens=True)
        except Exception:
            # 相容老版本 Pillow 的降級方案
            screen = pyautogui.screenshot(region=region)
            
        return cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2BGR)

    def get_scales_to_try(self, fast_mode=True):
        full_region = self.regions.get("全螢幕")
        curr_w = full_region[2] if full_region else pyautogui.size()[0]
        # 你的圖主要是按 2560 截的，就優先圍繞 2560 計算
        primary_base = 2560
        primary_scale = curr_w / primary_base
        scales = []
        def add_scale(s):
            s = round(float(s), 3)
            if 0.45 <= s <= 1.8 and s not in scales:
                scales.append(s)
        # 先加“最可能正確”的比例及其微調
        add_scale(primary_scale)
        add_scale(primary_scale * 0.98)
        add_scale(primary_scale * 1.02)
        add_scale(primary_scale * 0.95)
        add_scale(primary_scale * 1.05)
        add_scale(primary_scale * 0.92)
        add_scale(primary_scale * 1.08)
        # 再相容其它來源
        for bw in [1920, 1600]:
            s = curr_w / bw
            add_scale(s)
            add_scale(s * 0.98)
            add_scale(s * 1.02)
        # 最後兜底常用比例
        for s in [1.0, 0.95, 1.05, 0.9, 1.1, 0.85, 1.15, 0.8, 0.75, 0.7]:
            add_scale(s)
        if fast_mode:
            return scales[:8]
        return scales

    def get_scaled_template(self, template_path, scale):
        actual_path = get_img_path(template_path)
        images_dir = self.get_images_root_dir()

        if images_dir and os.path.exists(actual_path):
            try:
                rel_key = os.path.relpath(actual_path, images_dir).replace("\\", "/")
            except Exception:
                rel_key = os.path.basename(actual_path)
        else:
            rel_key = os.path.basename(actual_path)

        mem_key = (actual_path, round(scale, 3))
        if mem_key in self.scaled_template_cache:
            return self.scaled_template_cache[mem_key], actual_path

        scale_key = str(round(scale, 3))
        if rel_key in self.file_template_cache:
            tpl = self.file_template_cache[rel_key].get(scale_key)
            if tpl is not None:
                self.scaled_template_cache[mem_key] = tpl
                return tpl, actual_path

        template_orig, actual_path = self.load_template(template_path)
        if template_orig is None:
            return None, actual_path

        try:
            if scale == 1.0:
                tpl = template_orig.copy()
            else:
                tpl = cv2.resize(template_orig, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

            self.scaled_template_cache[mem_key] = tpl
            return tpl, actual_path
        except Exception:
            return None, actual_path

    def find_image_in_screen(self, screen_bgr, template_path, region=None, threshold=0.75, fast_mode=True):
        try:
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)

            for scale in scales_to_try:
                tpl_c, actual_path = self.get_scaled_template(template_path, scale)
                if tpl_c is None:
                    continue

                h, w = tpl_c.shape[:2]
                if h < 5 or w < 5:
                    continue
                if h > screen_bgr.shape[0] or w > screen_bgr.shape[1]:
                    continue

                res = cv2.matchTemplate(screen_bgr, tpl_c, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)

                if max_val >= threshold:
                    pos = (
                        max_loc[0] + w // 2 + (region[0] if region else 0),
                        max_loc[1] + h // 2 + (region[1] if region else 0),
                    )
                    self.last_positions[template_path] = pos
                    # 【新增】：在基礎圖像查找中增加詳細日誌返回
                    self.log(f"[ImageMatch] 命中: {template_path} | 得分: {max_val:.3f} (閾值 {threshold}) | 縮放比: {scale:.3f}")
                    return pos

            return None

        except Exception as e:
            self.log(f"find_image_in_screen 異常: {e}")
            return None

    def find_image(self, template_path, region=None, threshold=0.75, fast_mode=True):
        if not self.is_running:
            return None

        try:
            screen_bgr = self.capture_region(region)
            return self.find_image_in_screen(
                screen_bgr,
                template_path,
                region=region,
                threshold=threshold,
                fast_mode=fast_mode
            )
        except Exception as e:
            self.log(f"查找圖片時發生異常: {e}")
            return None

    def find_any_image(self, image_list, region=None, threshold=MATCH_THRESHOLD, fast_mode=True):
        if not self.is_running:
            return None

        try:
            screen_bgr = self.capture_region(region)
            for img_path in image_list:
                pos = self.find_image_in_screen(
                    screen_bgr,
                    img_path,
                    region=region,
                    threshold=threshold,
                    fast_mode=fast_mode
                )
                if pos:
                    return pos
            return None
        except Exception as e:
            self.log(f"find_any_image 異常: {e}")
            return None

    def find_image_with_element(self, main_path, sub_path, region=None, threshold=0.85, fast_mode=True):
        if not self.is_running:
            return None
        try:
            screen_bgr = self.capture_region(region)
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)
            for scale in scales_to_try:
                # 1. 結合新架構緩存直接讀取縮放好的圖像
                main_tpl_c, _ = self.get_scaled_template(main_path, scale)
                sub_tpl_c, _ = self.get_scaled_template(sub_path, scale)
                if main_tpl_c is None or sub_tpl_c is None:
                    continue
                h_m, w_m = main_tpl_c.shape[:2]
                if h_m < 5 or w_m < 5 or h_m > screen_bgr.shape[0] or w_m > screen_bgr.shape[1]:
                    continue
                # 2. 一階匹配：尋找全屏符合的主目標
                res_main = cv2.matchTemplate(screen_bgr, main_tpl_c, cv2.TM_CCOEFF_NORMED)
                loc = np.where(res_main >= threshold)
                checked = set() # 【關鍵優化】：座標去重，解決幾十萬次無效迴圈造成的卡頓
                for pt in zip(*loc[::-1]):
                    x, y = pt
                    # 過濾相鄰 10 個圖元內的重複識別點
                    key = (x // 10, y // 10)
                    if key in checked:
                        continue
                    checked.add(key)
                    # 3. 舊代碼的核心精髓：在主圖區域四周略微擴大 5 圖元的範圍內找元素
                    sub_roi = screen_bgr[
                        max(0, y - 5):min(screen_bgr.shape[0], y + h_m + 5),
                        max(0, x - 5):min(screen_bgr.shape[1], x + w_m + 5),
                    ]
                    if sub_tpl_c.shape[0] > sub_roi.shape[0] or sub_tpl_c.shape[1] > sub_roi.shape[1]:
                        continue
                                        # 4. 二階匹配：驗證提取範圍內是否包含子元素
                    res_sub = cv2.matchTemplate(sub_roi, sub_tpl_c, cv2.TM_CCOEFF_NORMED)
                    sub_score = cv2.minMaxLoc(res_sub)[1]
                    if sub_score >= threshold:
                        # 【新增】：在組合圖像查找中增加詳細日誌返回
                        main_score = res_main[y, x]
                        self.log(f"[ComboMatch] 命中: {main_path}+{sub_path} | 主圖得分: {main_score:.3f} | 元素得分: {sub_score:.3f} (閾值 {threshold}) | 縮放比: {scale:.3f}")
                        return (
                            x + w_m // 2 + (region[0] if region else 0),
                            y + h_m // 2 + (region[1] if region else 0),
                        )
            return None
        except Exception as e:
            self.log(f"find_image_with_element 異常: {e}")
            return None
    def find_image_with_element_stable(
        self,
        main_path,
        sub_path,
        region=None,
        main_threshold=0.60,
        verify_threshold=0.72,
        sub_threshold=0.70,
        max_candidates=15
    ):
        if not self.is_running:
            return None

        try:
            screen = pyautogui.screenshot(region=region)
            screen_gray = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2GRAY)

            main_tpl = self.load_template_gray(main_path)
            sub_tpl = self.load_template_gray(sub_path)

            if main_tpl is None or sub_tpl is None:
                return None

            h_m, w_m = main_tpl.shape[:2]
            h_s, w_s = sub_tpl.shape[:2]

            if h_m > screen_gray.shape[0] or w_m > screen_gray.shape[1]:
                return None

            res_main = cv2.matchTemplate(screen_gray, main_tpl, cv2.TM_CCOEFF_NORMED)
            ys, xs = np.where(res_main >= main_threshold)

            if len(xs) == 0:
                return None

            candidates = [(float(res_main[y, x]), x, y) for x, y in zip(xs, ys)]
            candidates.sort(key=lambda t: t[0], reverse=True)

            checked = set()
            checked_count = 0

            for main_score, x, y in candidates:
                key = (x // 8, y // 8)
                if key in checked:
                    continue
                checked.add(key)

                checked_count += 1
                if checked_count > max_candidates:
                    break

                pad = 8
                x1 = max(0, x - pad)
                y1 = max(0, y - pad)
                x2 = min(screen_gray.shape[1], x + w_m + pad)
                y2 = min(screen_gray.shape[0], y + h_m + pad)

                sub_roi = screen_gray[y1:y2, x1:x2]
                if sub_roi.shape[0] < h_s or sub_roi.shape[1] < w_s:
                    continue

                res_sub = cv2.matchTemplate(sub_roi, sub_tpl, cv2.TM_CCOEFF_NORMED)
                sub_score = cv2.minMaxLoc(res_sub)[1]

                if main_score >= verify_threshold and sub_score >= sub_threshold:
                    cx = x + w_m // 2
                    cy = y + h_m // 2
                    if region:
                        cx += region[0]
                        cy += region[1]
                    # 【新增】：列印穩定版組合匹配的詳細得分
                    self.log(f"[StableMatch] 命中: {main_path}+{sub_path} | 主圖: {main_score:.3f} (需>{verify_threshold}) | 元素: {sub_score:.3f} (需>{sub_threshold})")
                    return (cx, cy)

            return None

        except Exception as e:
            self.log(f"find_image_with_element_stable 識別報錯: {e}")
            return None
    def find_image_with_element_multi(self, main_path, sub_path, region=None, fast_mode=True,
        main_threshold=0.60, like_threshold=0.75, final_threshold=0.72):
        if not self.is_running:
            return None

        try:
            screen_bgr = self.capture_region(region)
            screen_gray = self.to_gray_image(screen_bgr)
            screen_edge = self.to_edge_image(screen_bgr)

            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)

            for scale in scales_to_try:
                main_tpl_c, _ = self.get_scaled_template(main_path, scale)
                sub_tpl_c, _ = self.get_scaled_template(sub_path, scale)

                if main_tpl_c is None or sub_tpl_c is None:
                    continue

                main_tpl_gray = self.to_gray_image(main_tpl_c)
                main_tpl_edge = self.to_edge_image(main_tpl_c)

                h_m, w_m = main_tpl_c.shape[:2]
                if h_m < 5 or w_m < 5:
                    continue
                if h_m > screen_bgr.shape[0] or w_m > screen_bgr.shape[1]:
                    continue

                # 用彩色主範本先找候選，門檻放低
                res_main = cv2.matchTemplate(screen_bgr, main_tpl_c, cv2.TM_CCOEFF_NORMED)
                loc = np.where(res_main >= main_threshold)

                # ==========================================
                # 【核心魔法】：強制從左到右、從上到下排序！
                # 保證在有多個相同目標時，絕對按順序點擊！
                # ==========================================
                points = list(zip(*loc[::-1]))
                points.sort(key=lambda p: (p[0] // 50, p[1])) 

                checked_points = set()

                for pt in points:
                    x, y = pt

                    # 去重，避免同一輛車計算多次
                    key = (x // 10, y // 10)
                    if key in checked_points:
                        continue
                    checked_points.add(key)

                    roi_bgr = screen_bgr[y:y + h_m, x:x + w_m]
                    roi_gray = screen_gray[y:y + h_m, x:x + w_m]
                    roi_edge = screen_edge[y:y + h_m, x:x + w_m]

                    if roi_bgr.shape[:2] != main_tpl_c.shape[:2]:
                        continue

                    # 四維打分系統 (抗 HDR 核心)
                    color_score = self.match_template_score(roi_bgr, main_tpl_c)
                    gray_score = self.match_template_score(roi_gray, main_tpl_gray)
                    edge_score = self.match_template_score(roi_edge, main_tpl_edge)

                    roi_center = self.crop_center_ratio(roi_bgr, ratio=0.6)
                    tpl_center = self.crop_center_ratio(main_tpl_c, ratio=0.6)
                    center_score = self.match_template_score(roi_center, tpl_center)

                    # 標籤匹配 (NEW 標籤或作者點贊標籤)
                    pad = 5
                    sub_roi = screen_bgr[
                        max(0, y - pad):min(screen_bgr.shape[0], y + h_m + pad),
                        max(0, x - pad):min(screen_bgr.shape[1], x + w_m + pad),
                    ]
                    like_score = self.match_template_score(sub_roi, sub_tpl_c)

                    if like_score < like_threshold:
                        continue

                    # 綜合計算總分
                    final_score = (
                        color_score * 0.30 +
                        gray_score * 0.20 +
                        edge_score * 0.20 +
                        center_score * 0.15 +
                        like_score * 0.15
                    )

                    curr_pos = (
                        x + w_m // 2 + (region[0] if region else 0),
                        y + h_m // 2 + (region[1] if region else 0),
                    )

                    # 只要及格，立刻返回（因為已經排過序了，第一個及格的一定是左上角的第一個目標）
                    if final_score >= final_threshold:
                        self.log(
                            f"[MultiMatch] 鎖定目標: {main_path}+{sub_path} | "
                            f"綜合: {final_score:.3f} | 彩色: {color_score:.3f} | "
                            f"灰度: {gray_score:.3f} | 邊緣: {edge_score:.3f} | "
                            f"中心: {center_score:.3f} | 標籤: {like_score:.3f}"
                        )
                        return curr_pos

            return None

        except Exception as e:
            self.log(f"find_image_with_element_multi 異常: {e}")
            return None
    
    def find_image_with_element_fast(self, main_path, sub_path, region=None, threshold=0.70, sub_threshold=0.70):
        if not self.is_running:
            return None

        try:
            screen = pyautogui.screenshot(region=region)
            screen_gray = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2GRAY)

            main_tpl = self.load_template_gray(main_path)
            sub_tpl = self.load_template_gray(sub_path)

            if main_tpl is None or sub_tpl is None:
                return None

            h_m, w_m = main_tpl.shape[:2]
            h_s, w_s = sub_tpl.shape[:2]

            if h_m > screen_gray.shape[0] or w_m > screen_gray.shape[1]:
                return None

            res_main = cv2.matchTemplate(screen_gray, main_tpl, cv2.TM_CCOEFF_NORMED)
            loc = np.where(res_main >= threshold)

            checked = set()

            for pt in zip(*loc[::-1]):
                x, y = pt

                # 去重，避免相鄰重複點太多
                key = (x // 10, y // 10)
                if key in checked:
                    continue
                checked.add(key)

                x1 = max(0, x - 5)
                y1 = max(0, y - 5)
                x2 = min(screen_gray.shape[1], x + w_m + 5)
                y2 = min(screen_gray.shape[0], y + h_m + 5)

                sub_roi = screen_gray[y1:y2, x1:x2]

                if sub_roi.shape[0] < h_s or sub_roi.shape[1] < w_s:
                    continue

                res_sub = cv2.matchTemplate(sub_roi, sub_tpl, cv2.TM_CCOEFF_NORMED)
                _, max_val_sub, _, _ = cv2.minMaxLoc(res_sub)

                if max_val_sub >= sub_threshold:
                    cx = x + w_m // 2
                    cy = y + h_m // 2
                    if region:
                        cx += region[0]
                        cy += region[1]
                    # 【新增】：列印快速匹配模式得分
                    main_score = res_main[y, x]
                    self.log(f"[FastMatch] 命中: {main_path}+{sub_path} | 主圖: {main_score:.3f} (需>{threshold}) | 元素: {max_val_sub:.3f} (需>{sub_threshold})")
                    return (cx, cy)

            return None

        except Exception as e:
            self.log(f"find_image_with_element_fast 異常: {e}")
            return None

    def wait_for_image_with_element_multi(self, main_path, sub_path, region=None, fast_mode=True,
        main_threshold=0.60, like_threshold=0.75,
        final_threshold=0.72, timeout=30, interval=0.4):
        start = time.time()

        while self.is_running and time.time() - start < timeout:
            pos = self.find_image_with_element_multi(
                main_path=main_path,
                sub_path=sub_path,
                region=region,
                fast_mode=fast_mode,
                main_threshold=main_threshold,
                like_threshold=like_threshold,
                final_threshold=final_threshold
            )
            if pos:
                return pos

            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                time.sleep(0.05)

        return None

    def load_template_transparent(self, template_path):
        """專門載入帶有 Alpha 透明通道的圖片"""
        actual_path = get_img_path(template_path)
        cache_key = ("transparent", actual_path)
        if not hasattr(self, "template_transparent_cache"):
            self.template_transparent_cache = {}
        if cache_key in self.template_transparent_cache:
            return self.template_transparent_cache[cache_key]
            
        # 注意這裡的 cv2.IMREAD_UNCHANGED，它會保留透明通道 (BGRA)
        tpl = cv2.imread(actual_path, cv2.IMREAD_UNCHANGED)
        if tpl is not None:
            self.template_transparent_cache[cache_key] = tpl
        return tpl
    def find_image_transparent(self, template_path, region=None, threshold=0.70, fast_mode=True):
        """帶透明通道的匹配：徹底無視透明背景，只匹配圖像主體"""
        if not self.is_running:
            return None
        try:
            screen_bgr = self.capture_region(region)
            tpl_bgra = self.load_template_transparent(template_path)
            
            if tpl_bgra is None:
                return None
            # 如果圖片沒有透明通道(不是4通道)，降級為普通匹配
            if tpl_bgra.shape[2] != 4:
                return self.find_image_in_screen(screen_bgr, template_path, region, threshold, fast_mode)
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)
            for scale in scales_to_try:
                # 對帶有透明通道的原圖進行縮放
                if scale == 1.0:
                    tpl_scaled = tpl_bgra.copy()
                else:
                    tpl_scaled = cv2.resize(tpl_bgra, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                h, w = tpl_scaled.shape[:2]
                if h < 5 or w < 5 or h > screen_bgr.shape[0] or w > screen_bgr.shape[1]:
                    continue
                # 分離出 BGR 色彩層 和 Alpha 透明遮罩層
                tpl_bgr = tpl_scaled[:, :, :3]
                alpha_mask = tpl_scaled[:, :, 3]
                                # 核心魔法：帶 mask 的匹配！透明區域不參與算分！
                res = cv2.matchTemplate(screen_bgr, tpl_bgr, cv2.TM_CCOEFF_NORMED, mask=alpha_mask)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val >= threshold:
                    # 【新增】：帶透明通道的匹配日誌
                    self.log(f"[AlphaMatch] 命中(無視背景): {template_path} | 得分: {max_val:.3f} (閾值 {threshold}) | 縮放比: {scale:.3f}")
                    return (
                        max_loc[0] + w // 2 + (region[0] if region else 0),
                        max_loc[1] + h // 2 + (region[1] if region else 0),
                    )
            return None
        except Exception as e:
            self.log(f"find_image_transparent 異常: {e}")
            return None
    def wait_for_image_transparent(self, template_path, region=None, threshold=0.70, timeout=30, interval=0.4, fast_mode=True):
        """等待帶有透明背景的圖片"""
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_image_transparent(template_path, region, threshold, fast_mode)
            if pos:
                return pos
            time.sleep(interval)
        return None
    def wait_for_image_with_element_stable(
        self,
        main_path,
        sub_path,
        region=None,
        main_threshold=0.60,
        verify_threshold=0.72,
        sub_threshold=0.70,
        max_candidates=15,
        timeout=3,
        interval=0.2
    ):
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_image_with_element_stable(
                main_path=main_path,
                sub_path=sub_path,
                region=region,
                main_threshold=main_threshold,
                verify_threshold=verify_threshold,
                sub_threshold=sub_threshold,
                max_candidates=max_candidates
            )
            if pos:
                return pos
            time.sleep(interval)
        return None
    def wait_for_image_with_element_fast(
        self,
        main_path,
        sub_path,
        region=None,
        threshold=0.70,
        sub_threshold=0.70,
        timeout=4,
        interval=0.25
    ):
        start = time.time()

        while self.is_running and time.time() - start < timeout:
            pos = self.find_image_with_element_fast(
                main_path=main_path,
                sub_path=sub_path,
                region=region,
                threshold=threshold,
                sub_threshold=sub_threshold
            )
            if pos:
                return pos

            time.sleep(interval)

        return None

    # ==========================================
    # --- 【終極安全鎖 V5.1】：排他 + 右下角調校精准狙擊 + 強制從左到右 ---
    # ==========================================
    def find_image_ultimate_safe(self, main_path, anti_path, region=None, main_threshold=0.80, anti_threshold=0.65):
        if not self.is_running: return None
        try:
            screen_bgr = self.capture_region(region)
            screen_gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)

            scales_to_try = self.get_scales_to_try(fast_mode=True)

            for scale in scales_to_try:
                main_tpl_bgr, _ = self.get_scaled_template(main_path, scale)
                anti_tpl_bgr, _ = self.get_scaled_template(anti_path, scale)

                if main_tpl_bgr is None or anti_tpl_bgr is None: continue
                
                main_tpl_gray = cv2.cvtColor(main_tpl_bgr, cv2.COLOR_BGR2GRAY)
                h_m, w_m = main_tpl_bgr.shape[:2]
                h_a, w_a = anti_tpl_bgr.shape[:2]

                if h_m < 10 or w_m < 10 or h_m > screen_bgr.shape[0] or w_m > screen_bgr.shape[1]:
                    continue

                # 1. 基礎彩色初篩
                res_main = cv2.matchTemplate(screen_bgr, main_tpl_bgr, cv2.TM_CCOEFF_NORMED)
                loc = np.where(res_main >= main_threshold)

                
                points = list(zip(*loc[::-1]))
                # 強制按 X 座標（從左到右）優先排序，無視上下排
                points.sort(key=lambda p: (p[0] // 50, p[1]))

                checked = set()
                for pt in points:
                    x, y = pt
                    if (x // 10, y // 10) in checked: continue
                    checked.add((x // 10, y // 10))

                    base_score = res_main[y, x]
                    
                    roi_bgr = screen_bgr[y:y+h_m, x:x+w_m]
                    roi_gray = screen_gray[y:y+h_m, x:x+w_m]
                    if roi_bgr.shape[:2] != main_tpl_bgr.shape[:2]: continue

                    # ==================================
                    # 防線 1: 排他校驗
                    # ==================================
                    pad_anti = 10
                    roi_y1, roi_y2 = max(0, y - pad_anti), min(screen_bgr.shape[0], y + h_m + pad_anti)
                    roi_x1, roi_x2 = max(0, x - pad_anti), min(screen_bgr.shape[1], x + w_m + pad_anti)
                    anti_roi = screen_bgr[roi_y1:roi_y2, roi_x1:roi_x2]

                    if anti_roi.shape[0] >= h_a and anti_roi.shape[1] >= w_a:
                        res_anti = cv2.matchTemplate(anti_roi, anti_tpl_bgr, cv2.TM_CCOEFF_NORMED)
                        _, anti_score, _, _ = cv2.minMaxLoc(res_anti)
                        if anti_score >= anti_threshold:
                            self.log(f"[排他攔截]: 發現 NEW 標籤 ({anti_score:.2f})，放棄該目標。")
                            continue

                    # ==================================
                    # 防線 2: 頂部文字
                    # ==================================
                    top_h = int(h_m * 0.25)
                    tpl_top = main_tpl_gray[:top_h, :]
                    
                    score_top = 0.0
                    pad_slide = 5 
                    if top_h > pad_slide*2 and w_m > pad_slide*2:
                        tpl_top_core = tpl_top[pad_slide:-pad_slide, pad_slide:-pad_slide]
                        search_top = roi_gray[:int(h_m * 0.35), :]
                        if search_top.shape[0] >= tpl_top_core.shape[0] and search_top.shape[1] >= tpl_top_core.shape[1]:
                            res_top = cv2.matchTemplate(search_top, tpl_top_core, cv2.TM_CCOEFF_NORMED)
                            _, score_top, _, _ = cv2.minMaxLoc(res_top)

                    # ==================================
                    # 防線 3: 【右下角】
                    # ==================================
                    bottom_h = int(h_m * 0.25)
                    right_w = int(w_m * 0.35)
                    tpl_pi_box = main_tpl_bgr[h_m - bottom_h:, w_m - right_w:]

                    score_bot = 0.0
                    if bottom_h > pad_slide*2 and right_w > pad_slide*2:
                        tpl_pi_core = tpl_pi_box[pad_slide:-pad_slide, pad_slide:-pad_slide]
                        search_y1 = h_m - int(h_m * 0.35)
                        search_x1 = w_m - int(w_m * 0.45)
                        search_bot = roi_bgr[search_y1:, search_x1:]
                        
                        if search_bot.shape[0] >= tpl_pi_core.shape[0] and search_bot.shape[1] >= tpl_pi_core.shape[1]:
                            res_bot = cv2.matchTemplate(search_bot, tpl_pi_core, cv2.TM_CCOEFF_NORMED)
                            _, score_bot, _, _ = cv2.minMaxLoc(res_bot)

                    if base_score >= 0.76 and score_top >= 0.75 and score_bot >= 0.85:
                        self.log(f"[終極安全-通過]: 鎖定目標！總分:{base_score:.3f} | 頂部車名:{score_top:.2f} | 右下調校:{score_bot:.2f}")
                        return (x + w_m // 2 + (region[0] if region else 0), y + h_m // 2 + (region[1] if region else 0))
                    else:
                        pass # 靜默攔截，繼續尋找下一個座標

            return None
        except Exception as e:
            self.log(f"ultimate_safe 異常: {e}")
            return None
    def wait_for_image_ultimate_safe(self, main_path, anti_path, region=None, main_threshold=0.80, anti_threshold=0.65, timeout=3, interval=0.2):
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_image_ultimate_safe(main_path, anti_path, region, main_threshold, anti_threshold)
            if pos: return pos
            time.sleep(interval)
        return None
    def find_image_smart(self, template_path, primary_region=None, fallback_region=None, threshold=0.75, fast_mode=True):
        if primary_region:
            pos = self.find_image(template_path, region=primary_region, threshold=threshold, fast_mode=fast_mode)
            if pos:
                return pos

        if fallback_region:
            return self.find_image(template_path, region=fallback_region, threshold=threshold, fast_mode=fast_mode)

        return None
    def to_gray_image(self, img):
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    def to_edge_image(self, img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        edge = cv2.Canny(blur, 50, 150)
        return edge
    def crop_center_ratio(self, img, ratio=0.6):
        h, w = img.shape[:2]
        ch = int(h * ratio)
        cw = int(w * ratio)
        y1 = max(0, (h - ch) // 2)
        x1 = max(0, (w - cw) // 2)
        return img[y1:y1 + ch, x1:x1 + cw]
    def find_image_gray(self, template_path, region=None, threshold=0.75, fast_mode=True):
        """純灰度UI查找，支持多解析度縮放"""
        if not self.is_running:
            return None
        try:
            screen_bgr = self.capture_region(region)
            screen_gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)
            for scale in scales_to_try:
                tpl_gray = self.load_template_gray(template_path)
                if tpl_gray is None:
                    continue
                if scale != 1.0:
                    tpl_gray = cv2.resize(tpl_gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                h, w = tpl_gray.shape[:2]
                if h < 5 or w < 5 or h > screen_gray.shape[0] or w > screen_gray.shape[1]:
                    continue
                res = cv2.matchTemplate(screen_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val >= threshold:
                    # 【新增】：灰度圖匹配的得分日誌
                    self.log(f"[GrayMatch] 命中: {template_path} | 灰度得分: {max_val:.3f} (閾值 {threshold}) | 縮放比: {scale:.3f}")
                    return (
                        max_loc[0] + w // 2 + (region[0] if region else 0),
                        max_loc[1] + h // 2 + (region[1] if region else 0),
                    )
            return None
        except Exception as e:
            self.log(f"find_image_gray 異常: {e}")
            return None
    def find_any_image_gray(self, image_list, region=None, threshold=0.75, fast_mode=True):
        """純灰度多圖查找，支持多解析度縮放"""
        if not self.is_running:
            return None
        try:
            screen_bgr = self.capture_region(region)
            screen_gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)
            
            for img_path in image_list:
                for scale in scales_to_try:
                    tpl_gray = self.load_template_gray(img_path)
                    if tpl_gray is None:
                        continue
                    if scale != 1.0:
                        tpl_gray = cv2.resize(tpl_gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                    h, w = tpl_gray.shape[:2]
                    if h < 5 or w < 5 or h > screen_gray.shape[0] or w > screen_gray.shape[1]:
                        continue
                    res = cv2.matchTemplate(screen_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, max_loc = cv2.minMaxLoc(res)
                    if max_val >= threshold:
                        # 【新增】：多張灰度圖匹配的得分日誌
                        self.log(f"[GrayMatchAny] 命中: {img_path} | 灰度得分: {max_val:.3f} (閾值 {threshold}) | 縮放比: {scale:.3f}")
                        return (
                            max_loc[0] + w // 2 + (region[0] if region else 0),
                            max_loc[1] + h // 2 + (region[1] if region else 0),
                        )
            return None
        except Exception as e:
            self.log(f"find_any_image_gray 異常: {e}")
            return None

    def wait_for_any_image_gray(self, image_list, region=None, threshold=0.75, timeout=30, interval=0.3, fast_mode=True):
        """等待多張灰度圖中的任意一張出現（已補全 fast_mode 參數）"""
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_any_image_gray(image_list, region=region, threshold=threshold, fast_mode=fast_mode)
            if pos:
                return pos
            
            # 安全等待機制，防止卡死
            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                time.sleep(0.05)
        return None
    def wait_for_image_gray(self, template_path, region=None, threshold=0.75, timeout=30, interval=0.3, fast_mode=True):
        """等待單張灰度圖出現（已補全 fast_mode 參數）"""
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_image_gray(template_path, region=region, threshold=threshold, fast_mode=fast_mode)
            if pos:
                return pos
            
            # 安全等待機制
            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                time.sleep(0.05)
        return None

    def find_any_image_transparent(self, image_list, region=None, threshold=0.70, fast_mode=True):
        """查找多張帶透明通道的圖片中的任意一張"""
        if not self.is_running:
            return None
        try:
            screen_bgr = self.capture_region(region)
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)

            for template_path in image_list:
                tpl_bgra = self.load_template_transparent(template_path)
                if tpl_bgra is None:
                    continue
                
                # 如果圖片沒有透明通道，降級為普通匹配
                if tpl_bgra.shape[2] != 4:
                    pos = self.find_image_in_screen(screen_bgr, template_path, region, threshold, fast_mode)
                    if pos: return pos
                    continue

                for scale in scales_to_try:
                    if scale == 1.0:
                        tpl_scaled = tpl_bgra.copy()
                    else:
                        tpl_scaled = cv2.resize(tpl_bgra, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

                    h, w = tpl_scaled.shape[:2]
                    if h < 5 or w < 5 or h > screen_bgr.shape[0] or w > screen_bgr.shape[1]:
                        continue

                    tpl_bgr = tpl_scaled[:, :, :3]
                    alpha_mask = tpl_scaled[:, :, 3]

                    res = cv2.matchTemplate(screen_bgr, tpl_bgr, cv2.TM_CCOEFF_NORMED, mask=alpha_mask)
                    _, max_val, _, max_loc = cv2.minMaxLoc(res)

                    if max_val >= threshold:
                        # 【新增】：多張帶透明通道的匹配日誌
                        self.log(f"[AlphaMatchAny] 命中(無視背景): {template_path} | 得分: {max_val:.3f} (閾值 {threshold}) | 縮放比: {scale:.3f}")
                        return (
                            max_loc[0] + w // 2 + (region[0] if region else 0),
                            max_loc[1] + h // 2 + (region[1] if region else 0),
                        )
            return None
        except Exception as e:
            self.log(f"find_any_image_transparent 異常: {e}")
            return None

    def wait_for_any_image_transparent(self, image_list, region=None, threshold=0.70, timeout=30, interval=0.4, fast_mode=True):
        """等待帶有透明背景的多張圖片中的任意一張出現"""
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_any_image_transparent(image_list, region, threshold, fast_mode)
            if pos:
                return pos
            
            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                time.sleep(0.05)
        return None
    def wait_for_any_image(self, image_list, region=None, threshold=0.75, timeout=30, interval=0.4, fast_mode=True, log_text=None):
        start = time.time()

        while self.is_running and time.time() - start < timeout:
            try:
                screen_bgr = self.capture_region(region)
                for img_path in image_list:
                    pos = self.find_image_in_screen(
                        screen_bgr,
                        img_path,
                        region=region,
                        threshold=threshold,
                        fast_mode=fast_mode
                    )
                    if pos:
                        return pos
            except Exception as e:
                self.log(f"wait_for_any_image 異常: {e}")

            if log_text:
                self.log(log_text)

            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                time.sleep(0.05)

        return None

    def wait_for_image(self, template_path, region=None, threshold=0.75, timeout=30, interval=0.4, fast_mode=True, log_text=None):
        return self.wait_for_any_image(
            [template_path],
            region=region,
            threshold=threshold,
            timeout=timeout,
            interval=interval,
            fast_mode=fast_mode,
            log_text=log_text
        )

    def wait_for_image_with_element(self, main_path, sub_path, region=None, threshold=0.85, timeout=30, interval=0.4, fast_mode=True):
        start = time.time()

        while self.is_running and time.time() - start < timeout:
            pos = self.find_image_with_element(
                main_path,
                sub_path,
                region=region,
                threshold=threshold,
                fast_mode=fast_mode
            )
            if pos:
                return pos

            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                time.sleep(0.05)

        return None

    def wait_for_region_stable(self, region=None, timeout=2.0, interval=0.15, diff_threshold=1.5, stable_hits=2):
        """
        Wait until a region stops visibly changing.
        Used after horizontal paging so matching starts only after the
        car list animation settles down.
        """
        start = time.time()
        prev_gray = None
        stable_count = 0

        while self.is_running and time.time() - start < timeout:
            try:
                screen_bgr = self.capture_region(region)
                curr_gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
            except Exception:
                time.sleep(interval)
                continue

            if prev_gray is not None and prev_gray.shape == curr_gray.shape:
                diff = cv2.absdiff(prev_gray, curr_gray)
                mean_diff = float(np.mean(diff))

                if mean_diff <= diff_threshold:
                    stable_count += 1
                    if stable_count >= stable_hits:
                        return True
                else:
                    stable_count = 0

            prev_gray = curr_gray

            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                time.sleep(0.05)

        return False

    def fast_advance_car_pages(self, page_count, region=None):
        """
        Fast-forward to the remembered page with lighter waits than the
        normal page-by-page search loop. We only use this for skipping
        pages already confirmed empty in the same big loop.
        """
        for idx in range(page_count):
            if not self.is_running:
                return False

            self.hw_press("right", delay=0.06)
            time.sleep(0.18)

            # Only do a short settle every few pages (and on the final hop)
            if ((idx + 1) % 4 == 0) or (idx == page_count - 1):
                self.wait_for_region_stable(
                    region=region,
                    timeout=1.0,
                    interval=0.10,
                    diff_threshold=1.8,
                    stable_hits=1
                )

        return True

    def find_race_skillcar_with_recheck(self, check_times=2, settle_delay=0.18):
        """
        Recheck the current visible car page a few times before deciding
        it does not contain the target race car.
        """
        pos_target = None
        for check_idx in range(max(1, int(check_times))):
            if not self.is_running:
                return None

            pos_target = self.wait_for_image_with_element_multi(
                "skillcar.png",
                "liketag.png",
                region=self.regions["全螢幕"],
                main_threshold=0.75,
                like_threshold=0.7,
                final_threshold=0.7,
                timeout=1.2,
                interval=0.2,
                fast_mode=True
            )
            if pos_target:
                return pos_target

            if check_idx < max(1, int(check_times)) - 1:
                time.sleep(settle_delay)

        return None

    def apply_race_favorites_filter(self):
        """
        In My Cars, open the Y filter menu and enable the first option:
        Favorites. This narrows the race-car search space a lot.
        """
        self.log("進入我的車輛後，先按 Y 篩選【收藏】車輛...")
        self.hw_press("y")
        self.sleep_ui(0.8)
        self.hw_press("enter")
        self.sleep_ui(0.8)
        self.hw_press("esc")
        self.sleep_ui(1.0)

    def find_race_skillcar_in_favorites(self, page_idx):
        """
        Search the current Favorites page for the race car.
        In Favorites we prioritize speed first: try the car template directly,
        then fall back to the stricter car+liketag check if needed.
        """
        if not self.is_running:
            return None

        direct_checks = 2 if page_idx == 0 else 1
        for check_idx in range(direct_checks):
            pos_target = self.find_image(
                "skillcar.png",
                region=self.regions["全螢幕"],
                threshold=0.74,
                fast_mode=True
            )
            if pos_target:
                return pos_target
            if check_idx < direct_checks - 1:
                time.sleep(0.15)

        return self.find_race_skillcar_with_recheck(
            check_times=1,
            settle_delay=0.12
        )

    def match_template_score(self, src, tpl):
        try:
            if tpl is None or src is None:
                return 0.0
            th, tw = tpl.shape[:2]
            sh, sw = src.shape[:2]
            if th < 5 or tw < 5 or th > sh or tw > sw:
                return 0.0
            res = cv2.matchTemplate(src, tpl, cv2.TM_CCOEFF_NORMED)
            return cv2.minMaxLoc(res)[1]
        except Exception:
            return 0.0
    # ==========================================
    # --- 模組：跑圖前置與迴圈跑圖 ---
    # ==========================================
    def logic_race(self, target_count):
        if self.race_counter >= target_count:
            return True

        self.update_running_ui("迴圈跑圖", self.race_counter, target_count)

        self.log("準備驗證/進入菜單...")
        if not self.enter_menu():
            return False

        self.log("切換到創意中心...")
        for _ in range(4):
            self.hw_press("pagedown", delay=0.15)
            time.sleep(0.3)

        time.sleep(0.8)


        pos_el = self.wait_for_image_gray(
            "eventlab.png",
            region=self.regions["全螢幕"],
            threshold=0.7,
            timeout=5,
            interval=0.25,
            fast_mode=True
        )
    
        if not pos_el:
            self.log("未找到 eventlab")
            return False

        self.game_click(pos_el)
        time.sleep(1.2)

        pos_yg = self.wait_for_image_gray(
            "playenent.png",
            region=self.regions["中間"],
            threshold=0.75,
            timeout=40,
            interval=0.3,
            fast_mode=True
        )
        if not pos_yg:
            self.log("未找到遊玩賽事")
            return False

        self.game_click(pos_yg)
        time.sleep(1.5)

        self.hw_press("backspace")
        time.sleep(0.8)
        self.hw_press("up")
        time.sleep(0.4)
        self.hw_press("enter")
        if not self.wait_for_share_code_input_ready():
            return False

        code_text = "".join(c for c in self.entry_share.get() if c.isdigit())
        for char in code_text:
            if not self.is_running:
                return False
            if char in DIK_CODES:
                self.hw_press(char, delay=0.05)
                time.sleep(0.05)

        time.sleep(0.4)
        self.hw_press("enter")
        time.sleep(0.8)
        self.hw_press("down")
        time.sleep(0.3)
        self.hw_press("enter")
        time.sleep(1.5)

        pos_ck = self.wait_for_image_gray(
            "VEI.png",
            region=self.regions["下"],
            threshold=0.75,
            timeout=20,
            interval=1.0,
            fast_mode=True
        )
        if not pos_ck:
            self.log("連結超時")
            return False

        self.hw_press("enter")
        time.sleep(2.0)
        self.hw_press("enter")
        time.sleep(2.0)

        self.apply_race_favorites_filter()
        pos_target = self.wait_for_image_with_element_multi(
            "skillcar.png",
            "liketag.png",
            region=self.regions["全螢幕"],
            fast_mode=True,
            main_threshold=0.75,
            like_threshold=0.7,
            final_threshold=0.7,
            timeout=2,
            interval=0.25
        )

        if not pos_target:
            self.log("未找到帶 liketag 的目標車輛，重新選品牌...")
            self.hw_press("backspace")
            time.sleep(1.2)

            found_brand = False
            for _ in range(3):
                if not self.is_running:
                    return False

                pos_brand = self.wait_for_image_gray("skillcarbrand.png", region=self.regions["全螢幕"], threshold=0.8, timeout=1.2, interval=0.2, fast_mode=True)
                if pos_brand:
                    self.game_click(pos_brand)
                    time.sleep(1.2)
                    found_brand = True
                    break

                self.hw_press("up")
                time.sleep(0.4)

            if not found_brand:
                self.log("三次嘗試未找到刷圖車輛品牌。")
                return False

            for _ in range(20):
                if not self.is_running:
                    return False

                pos_target = self.wait_for_image_with_element_multi(
                    "skillcar.png",
                    "liketag.png",
                    region=self.regions["全螢幕"],
                    main_threshold=0.75,
                    like_threshold=0.7,
                    final_threshold=0.7,
                    timeout=2,
                    interval=0.25,
                    fast_mode=True
                )
                if pos_target:
                    break

                for _ in range(4):
                    self.hw_press("right", delay=0.08)
                    time.sleep(0.08)
                time.sleep(0.4)

        if not pos_target:
            self.log("翻頁未能找到帶有 liketag 的刷圖車輛！")
            return False

        self.game_click(pos_target)
        time.sleep(0.5)
        self.hw_press("enter")
        time.sleep(4.0)

        self.log("前置完成，開始迴圈跑圖！")

        while self.race_counter < target_count:
            if not self.is_running:
                return False

            self.log(f"跑圖 {self.race_counter + 1}/{target_count}: 找賽事起點...")

            pos = None
            for _ in range(120):
                if not self.is_running:
                    return False

                pos = self.wait_for_any_image_gray(
                    ["start.png", "startw.png"],
                    region=self.regions["左下"],
                    threshold=0.75,
                    timeout=0.7,
                    interval=0.2,
                    fast_mode=True
                )
                if pos:
                    break

                self.hw_press("down")
                time.sleep(0.25)

            if not pos:
                self.log("找不到賽事起點，退出跑圖。")
                return False

            self.game_click(pos)
            time.sleep(4.0)
            self.hw_key_down("w")
            self.hw_key_down("up") 
            
            # 初始化各類計時器
            race_start_time = time.time()  # 新增：記錄跑圖發車時間
            last_like_chk = time.time()
            last_chk = 0
            finished = False
            timeout_triggered = False      # 新增：標記是否觸發了120秒超時

            driving_keys_held = True # <--- 【新增】標記油門狀態

            while self.is_running:
                # ====== 【新增】跑圖專用暫停處理邏輯 ======
                if self.is_paused:
                    if driving_keys_held: # 剛進入暫停，鬆開油門
                        self.hw_key_up("w")
                        self.hw_key_up("up")
                        driving_keys_held = False
                    self.check_pause() # 阻塞在此處
                    # 從暫停中恢復，如果還沒跑完，重新按下油門
                    if self.is_running:
                        self.hw_key_down("w")
                        self.hw_key_down("up")
                        driving_keys_held = True
                        
                    # 避免恢復瞬間觸發超時，重置計時器
                    race_start_time = time.time() 
                    last_like_chk = time.time()
                    last_chk = time.time()
                    continue 
                # =========================================
                now = time.time()
                
                # 【新增邏輯】：120秒超時防卡死檢測
                if now - race_start_time > 120.0:
                    self.log("跑圖超時(已超過120秒)！觸發強制重開賽事邏輯...")
                    timeout_triggered = True
                    break
                
                # 【原生邏輯】：每隔3秒識別一次 likeauthor.png
                if now - last_like_chk >= 3.0:
                    pos_like = self.find_any_image_gray(["likeauthor.png", "dislikeauthor.png"], region=self.regions["中間"], threshold=0.70)
                    if pos_like:
                        self.log("識別到點贊作介面，執行回車確認！")
                        self.hw_press("enter")
                    last_like_chk = now
                    
                # 【原生邏輯】：每1秒檢測一次重新開始(正常完賽)
                if now - last_chk >= 1.0:
                    found_restart = self.find_image_gray("restart.png", region=self.regions["下"], threshold=0.75, fast_mode=True)
                    if found_restart:
                        finished = True
                        break
                    last_chk = now
                    
                time.sleep(0.3)
                
            # 無論正常結束還是超時，都必須先鬆開油門和方向
            self.hw_key_up("w")
            self.hw_key_up("up")

            if not self.is_running:
                return False

            # ====== 【新增】：執行超時重置操作 ======
            if timeout_triggered:
                time.sleep(0.5)
                self.hw_press("esc")
                time.sleep(1.5)  # 等待菜單動畫載入
                
                # 尋找並點擊 restarta.png
                pos_restarta = self.wait_for_image_gray("restarta.png", region=self.regions["全螢幕"], threshold=0.70, timeout=4.0, interval=0.3, fast_mode=True)
                if pos_restarta:
                    self.log("找到 restarta.png，點擊重開賽事...")
                    self.game_click(pos_restarta)
                    time.sleep(1.0)
                    self.hw_press("enter")  # 地平線重開賽事通常有確認彈窗，按一次回車確認
                    time.sleep(4.0)         # 等待黑屏重載入動畫
                else:
                    self.log("未找到 restarta.png，嘗試直接繼續...")
                    
                # 【關鍵】：直接跳過下方的結算流程，回到最外層 while 重新找 start.png（並且本次不計入 race_counter）
                continue
            # ========================================

            if not finished:
                return False

            if self.race_counter == target_count - 1:
                self.hw_press("enter")
                time.sleep(2.0)
            else:
                self.hw_press("x")
                time.sleep(0.8)
                self.hw_press("enter")
                time.sleep(2.0)

            self.race_counter += 1
            self.update_running_ui("迴圈跑圖", self.race_counter, target_count)

        return True

    # ==========================================
    # --- 模組：買車 ---
    # ==========================================
    def logic_buy_car(self, target_count):
        if self.car_counter >= target_count:
            return True

        self.update_running_ui("批量買車", self.car_counter, target_count)

        self.log("準備驗證/進入菜單...")
        if not self.enter_menu():
            return False

        pos_collectionjournal = self.wait_for_image_transparent(
            "collectionjournal.png",
            region=self.regions["左"],
            threshold=0.7,
            timeout=30,
            interval=0.4,
            fast_mode=True
        )
        if not pos_collectionjournal:
            self.log("未找到收集簿")
            return False

        self.game_click(pos_collectionjournal, double=True)
        time.sleep(1.0)


        pos_masterexplorer = self.wait_for_image(
            "masterexplorer.png",
            region=self.regions["全螢幕"],
            threshold=0.75,
            timeout=30,
            interval=0.4,
            fast_mode=True
        )
        if not pos_masterexplorer:
            self.log("未找到探索")
            return False

        self.game_click(pos_masterexplorer, double=True)
        time.sleep(0.6)

        pos_carcollection = self.wait_for_image_transparent(
            "carcollection.png",
            region=self.regions["全螢幕"],
            threshold=0.75,
            timeout=30,
            interval=0.3,
            fast_mode=True
        )
        if not pos_carcollection:
            self.log("未找到車輛收集")
            return False

        self.game_click(pos_carcollection, double=True)
        time.sleep(1.0)

        self.hw_press("backspace")
        time.sleep(0.5)
        self.wait_for_region_stable(
            region=self.regions["全螢幕"],
            timeout=1.8,
            interval=0.12,
            diff_threshold=2.0,
            stable_hits=2
        )
        self.hw_press("up")
        time.sleep(0.5)
        self.wait_for_region_stable(
            region=self.regions["全螢幕"],
            timeout=1.2,
            interval=0.10,
            diff_threshold=2.0,
            stable_hits=2
        )

        brand_pos = None
        if not self.is_running:
            return False

        brand_pos = self.wait_for_any_image_gray(
            ["CCbrand.png"],
            region=self.regions["全螢幕"],
            threshold=0.75,
            timeout=0.8,
            interval=0.2,
            fast_mode=True
        )

        if brand_pos:
            self.game_click(brand_pos)
            time.sleep(0.9)
        else:
            self.log("未識別到SUBARU範本，改用固定按鍵兜底：2次UP + 3次RIGHT")
            self.wait_for_region_stable(
                region=self.regions["全螢幕"],
                timeout=1.2,
                interval=0.10,
                diff_threshold=2.0,
                stable_hits=2
            )
            for _ in range(2):
                if not self.is_running:
                    return False
                self.hw_press("up")
                time.sleep(0.5)
                self.wait_for_region_stable(
                    region=self.regions["全螢幕"],
                    timeout=1.0,
                    interval=0.10,
                    diff_threshold=2.0,
                    stable_hits=2
                )
            for _ in range(3):
                if not self.is_running:
                    return False
                self.hw_press("right")
                time.sleep(0.5)
                self.wait_for_region_stable(
                    region=self.regions["全螢幕"],
                    timeout=1.0,
                    interval=0.10,
                    diff_threshold=2.0,
                    stable_hits=2
                )
            self.hw_press("enter")
            time.sleep(0.9)

        self.hw_press("down")
        time.sleep(0.5)

        pos_22b = self.wait_for_image(
            "consumablecar.png",
            region=self.regions["全螢幕"],
            threshold=0.90,
            timeout=8,
            interval=0.3,
            fast_mode=False
        )
        if not pos_22b:
            self.log("未找到消耗品車輛")
            return False

        self.game_click(pos_22b, double=True)
        time.sleep(1.0)

        while self.car_counter < target_count:
            if not self.is_running:
                return False
            
            self.hw_press("space")
            time.sleep(0.6)
            self.move_to_game_coord(5, 5)
            self.hw_press("down")
            time.sleep(0.2)
            self.move_to_game_coord(5, 5)
            self.hw_press("enter")
            time.sleep(0.6)
            self.move_to_game_coord(5, 5)
            self.hw_press("enter")
            time.sleep(0.6)
            self.move_to_game_coord(5, 5)
            self.hw_press("enter")
            time.sleep(0.7)

            self.car_counter += 1
            self.update_running_ui("批量買車", self.car_counter, target_count)

        for _ in range(5):
            if not self.is_running:
                return False
            self.hw_press("esc")
            time.sleep(0.8)

        return True
    # ==========================================
    # --- 模組：抽獎 ---
    # ==========================================
    def logic_super_wheelspin(self, target_count):
        if self.cj_counter >= target_count:
            return True

        self.update_running_ui("超級抽獎", self.cj_counter, target_count)
        # 【新增】：初始化記憶頁碼
        if not hasattr(self, 'memory_car_page'):
            self.memory_car_page = 0
        self.log("準備驗證/進入菜單...")
        if not self.enter_menu():
            return False

        self.log("進入車輛與收藏...")
        self.hw_press("pagedown", delay=0.15)
        time.sleep(1.0)

        pos_buycar = self.wait_for_image(
            "BNandUC.png",
            region=self.regions["左"],
            threshold=0.70,
            timeout=15,
            interval=0.3,
            fast_mode=True
        )
        if not pos_buycar:
            self.log("未識別到 購買新車與二手車")
            return False

        self.game_click(pos_buycar)
        time.sleep(0.8)
        self.hw_press("enter")
        time.sleep(5)


        pos_bs = self.wait_for_any_image_gray(
            ["buyandsell-w.png", "buyandsell-b.png"],
            region=self.regions["左"],
            threshold=0.75,
            timeout=60,
            interval=0.5,
            fast_mode=True
        )
        if not pos_bs:
            self.log("未找到購買與出售")
            return False

        self.game_click(pos_bs)
        time.sleep(0.2)
        self.hw_press("pagedown", delay=0.15)
        self.log("進入車輛介面...")
        time.sleep(0.5)

        while self.cj_counter < target_count:
            if not self.is_running:
                return False

            pos_ds = self.wait_for_any_image_gray(
                ["DandS-w.png", "DandS-b.png"],
                region=self.regions["全螢幕"],
                threshold=0.75,
                timeout=20,
                interval=0.3,
                fast_mode=True
            )
            if not pos_ds:
                self.log("未找到下載與分享入口")
                return False
            self.game_click(pos_ds)
            time.sleep(1.0)

            pos_choosecar = self.wait_for_any_image_gray(
                ["choosecar.png", "choosecar-b.png"],
                region=self.regions["全螢幕"],
                threshold=0.75,
                timeout=20,
                interval=0.3,
                fast_mode=True
            )
            if not pos_choosecar:
                self.log("未找到選擇車輛入口")
                return False
            self.game_click(pos_choosecar)
            time.sleep(2.0)
            self.hw_press("backspace")
            time.sleep(1.0)

            brand_pos = None
            for _ in range(30):
                if not self.is_running:
                    return False

                brand_pos = self.wait_for_any_image_gray(
                    ["CCCbrand.png", "CCCbrand-b.png"],
                    region=self.regions["全螢幕"],
                    threshold=0.75,
                    timeout=0.8,
                    interval=0.2,
                    fast_mode=True
                )
                if brand_pos:
                    break

                self.hw_press("up")
                time.sleep(0.25)

            if not brand_pos:
                self.log("選品牌失敗")
                return False

            self.game_click(brand_pos)
            time.sleep(1.0)
            pos_target = None
            found_car = False
            start_page = max(0, min(84, int(getattr(self, "memory_car_page", 0))))

            if start_page > 0:
                self.log(f"沿用本輪記憶：直接從第 {start_page + 1} 頁開始找車...")
                if not self.fast_advance_car_pages(start_page, region=self.regions["全螢幕"]):
                    return False

            # 一頁一停、一頁一判，確認當前可見頁沒有目標車後再翻到下一頁。
            for page_idx in range(start_page, 85):
                if not self.is_running:
                    return False

                if page_idx > start_page:
                    self.log(f"第 {page_idx + 1} 頁搜索前，等待翻頁動畫穩定...")
                    self.wait_for_region_stable(
                        region=self.regions["全螢幕"],
                        timeout=2.0,
                        interval=0.15,
                        diff_threshold=1.5,
                        stable_hits=2
                    )

                for confirm_idx in range(2):
                    if not self.is_running:
                        return False

                    pos_target = self.wait_for_image_with_element_multi(
                        "newCC.png",
                        "newcartag.png",
                        region=self.regions["全螢幕"],
                        main_threshold=0.75,   # 防HDR核心：第一道門檻放低
                        like_threshold=0.75,
                        final_threshold=0.70,
                        timeout=1.0,
                        interval=0.2,
                        fast_mode=True
                    )

                    if pos_target:
                        self.game_click(pos_target)
                        found_car = True
                        self.memory_car_page = page_idx
                        self.log(f"鎖定目標車輛！當前可見頁: {page_idx + 1}")
                        break

                    if confirm_idx < 1:
                        self.log(f"第 {page_idx + 1} 頁第 {confirm_idx + 1} 次識別未命中，繼續複查當前頁...")
                        time.sleep(0.25)

                if found_car:
                    break

                if page_idx >= 84:
                    break

                self.log(f"第 {page_idx + 1} 頁確認無目標車，翻到下一頁繼續搜索...")
                self.hw_press("right", delay=0.08)
                time.sleep(0.35)

            if not found_car:
                self.log("清單中未找到目標車輛，重置記憶頁碼。")
                self.memory_car_page = 0 # 沒找到說明車刷完了，清零記憶
                return False
            self.sleep_ui(1.2)
            self.log("嘗試尋找'上車'按鈕...")

            pos_rc = None
            pos_rc = self.wait_for_image_gray("rc.png", region=self.regions["全螢幕"], threshold=0.70, timeout=0.5, interval=0.1, fast_mode=True)
            
            if pos_rc:
                self.log("點擊上車")
                self.game_click(pos_rc)
                self.sleep_ui(2.0)  # 點擊後等待上車載入
            else:
                self.log("回車上車")
                self.hw_press("enter")
                self.sleep_ui(1.0)
                self.hw_press("enter")
                self.sleep_ui(1.0)

            self.log(f"上車動畫後額外等待 {self.get_post_get_in_car_delay():.2f}s，再查找升級與調教...")
            self.sleep_post_get_in_car()

            pos_sjy = None
            for _ in range(20):
                if not self.is_running:
                    return False

                pos_sjy = self.find_any_image_gray(["UandT-w.png", "UandT-b.png"], region=self.regions["左下"], threshold=0.70)
                if pos_sjy:
                    break

                self.hw_press("esc")
                self.sleep_ui(0.5)

            if not pos_sjy:
                self.log("找不到升級頁面")
                return False

            self.game_click(pos_sjy)
            self.sleep_ui(0.5)

            pos_cls = self.wait_for_any_image_gray(
                ["clsldcnw.png", "clsldcnb.png"],
                region=self.regions["左下"],
                threshold=0.70,
                timeout=20
            )
            if not pos_cls:
                self.log("未找到車輛熟練度")
                return False
            self.game_click(pos_cls)
            time.sleep(1.5)

            pos_exp = self.wait_for_any_image(
                ["EXPwU.png"],
                region=self.regions["左"],
                threshold=0.75,
                timeout=1.5,
                interval=0.3,
                fast_mode=True
            )

            if pos_exp:
                self.log("該車輛技能已點過，跳過計數")
            else:
                time.sleep(1.0)
                self.hw_press("enter")
                time.sleep(1.5)

                for dk in self.config["skill_dirs"]:
                    if not self.is_running:
                        return False
                    self.hw_press(dk)
                    time.sleep(0.2)
                    self.hw_press("enter")
                    time.sleep(1.2)

                spne_found = self.find_image_gray("SPNE.png", region=self.regions["全螢幕"], threshold=0.70)
                
                if spne_found:
                    self.log("已無技能點或技能已點完，提前結束抽獎！")
                    time.sleep(1.0)
                    self.hw_press("enter")
                    time.sleep(0.8)
                    self.hw_press("esc")
                    time.sleep(1.0)
                    self.hw_press("esc")
                    time.sleep(1.0)
                    self.hw_press("esc")
                    time.sleep(1.0)
                    return True
                self.cj_counter += 1
                self.update_running_ui("超級抽獎", self.cj_counter, target_count)

            self.hw_press("esc")
            time.sleep(1.2)
            self.hw_press("esc")
            time.sleep(0.8)
            self.hw_press("up", delay=0.15)
            time.sleep(0.8)
        self.hw_press("esc")
        time.sleep(1.2)
        self.hw_press("esc")
        time.sleep(1.2)
        return True
    def logic_super_wheelspin_v2(self, target_count):
        if self.cj_counter >= target_count:
            return True

        self.update_running_ui("超級抽獎", self.cj_counter, target_count)
        if not hasattr(self, "memory_car_page"):
            self.memory_car_page = 0

        self.log("準備驗證/進入菜單...")
        if not self.enter_menu():
            return False

        self.log("進入車輛與收藏...")
        self.hw_press("pagedown", delay=0.15)
        time.sleep(1.0)

        pos_buycar = self.wait_for_image(
            "BNandUC.png",
            region=self.regions["左"],
            threshold=0.70,
            timeout=15,
            interval=0.3,
            fast_mode=True
        )
        if not pos_buycar:
            self.log("未識別到 購買新車與二手車")
            return False

        self.game_click(pos_buycar)
        time.sleep(0.8)
        self.hw_press("enter")
        time.sleep(5)

        pos_bs = self.wait_for_any_image_gray(
            ["buyandsell-w.png", "buyandsell-b.png"],
            region=self.regions["左"],
            threshold=0.75,
            timeout=60,
            interval=0.5,
            fast_mode=True
        )
        if not pos_bs:
            self.log("未找到購買與出售")
            return False

        self.game_click(pos_bs)
        time.sleep(0.2)
        self.hw_press("pagedown", delay=0.15)
        self.log("進入車輛介面...")
        time.sleep(0.5)
        self.hw_press("down", delay=0.08)
        time.sleep(0.3)
        self.hw_press("down", delay=0.08)
        time.sleep(0.5)

        while self.cj_counter < target_count:
            if not self.is_running:
                return False

            self.log("進入設計與噴漆...")
            self.hw_press("enter")
            time.sleep(1.0)

            pos_choosecar = self.wait_for_any_image_gray(
                ["choosecar.png", "choosecar-b.png"],
                region=self.regions["全螢幕"],
                threshold=0.72,
                timeout=12,
                interval=0.25,
                fast_mode=True
            )
            if not pos_choosecar:
                self.log("灰度未找到選擇車輛入口，切換彩色匹配繼續嘗試...")
                pos_choosecar = self.wait_for_any_image(
                    ["choosecar.png", "choosecar-b.png"],
                    region=self.regions["全螢幕"],
                    threshold=0.70,
                    timeout=8,
                    interval=0.25,
                    fast_mode=True
                )
            if not pos_choosecar:
                self.log("未找到選擇車輛入口")
                return False
            self.game_click(pos_choosecar)
            time.sleep(2.0)

            # === 修改後的程式碼 ===
            self.hw_press("backspace")
            time.sleep(0.8)

            # --- 新增：按一次 UP 到底端並穩定畫面 ---
            self.log("按一次 UP 到清單底端並穩定畫面...")
            self.hw_press("up")
            self.wait_for_region_stable(
                region=self.regions["全螢幕"],
                timeout=1.5,
                interval=0.10,
                diff_threshold=2.0,
                stable_hits=2
            )

            # --- 新增：嘗試識別品牌一次 ---
            self.log("嘗試識別品牌一次...")
            brand_pos = None
            if self.is_running:
                brand_pos = self.wait_for_any_image_gray(
                    ["CCCbrand.png", "CCCbrand-b.png"],
                    region=self.regions["全螢幕"],
                    threshold=0.75,
                    timeout=1.5,
                    interval=0.2,
                    fast_mode=True
                )

            if brand_pos:
                self.log("識別品牌成功，執行點擊。")
                self.game_click(brand_pos)
                time.sleep(1.0)
            else:
                self.log("選品牌失敗：未能識別到 CCCbrand，流程中止以防閉環。")
                return False

            pos_target = None
            found_car = False
            start_page = max(0, min(84, int(getattr(self, "memory_car_page", 0))))

            if start_page > 0:
                self.log(f"沿用本輪記憶：直接從第 {start_page + 1} 頁開始找車...")
                if not self.fast_advance_car_pages(start_page, region=self.regions["全螢幕"]):
                    return False

            for page_idx in range(start_page, 85):
                if not self.is_running:
                    return False

                if page_idx > start_page:
                    self.log(f"第 {page_idx + 1} 頁搜索前，等待翻頁動畫穩定...")
                    self.wait_for_region_stable(
                        region=self.regions["全螢幕"],
                        timeout=2.0,
                        interval=0.15,
                        diff_threshold=1.5,
                        stable_hits=2
                    )

                for confirm_idx in range(2):
                    if not self.is_running:
                        return False

                    pos_target = self.wait_for_image_with_element_multi(
                        "newCC.png",
                        "newcartag.png",
                        region=self.regions["全螢幕"],
                        main_threshold=0.75,
                        like_threshold=0.75,
                        final_threshold=0.70,
                        timeout=1.0,
                        interval=0.2,
                        fast_mode=True
                    )

                    if pos_target:
                        self.game_click(pos_target)
                        found_car = True
                        self.memory_car_page = page_idx
                        self.log(f"鎖定目標車輛！當前可見頁: {page_idx + 1}")
                        break

                    if confirm_idx < 1:
                        self.log(f"第 {page_idx + 1} 頁第 {confirm_idx + 1} 次識別未命中，繼續複查當前頁...")
                        time.sleep(0.25)

                if found_car:
                    break

                if page_idx >= 84:
                    break

                self.log(f"第 {page_idx + 1} 頁確認無目標車，翻到下一頁繼續搜索...")
                self.hw_press("right", delay=0.08)
                time.sleep(0.35)

            if not found_car:
                self.log("清單中未找到目標車輛，重置記憶頁碼。")
                self.memory_car_page = 0
                return False

            self.hw_press("enter")
            time.sleep(0.2)
            self.hw_press("esc")
            self.log(f"退出車輛選擇後額外等待 {self.get_post_get_in_car_delay():.2f}s，再查找升級與調教...")
            self.sleep_post_get_in_car()

            pos_sjy = None
            for _ in range(20):
                if not self.is_running:
                    return False

                pos_sjy = self.find_any_image_gray(
                    ["UandT-w.png", "UandT-b.png"],
                    region=self.regions["左下"],
                    threshold=0.70
                )
                if pos_sjy:
                    break

                self.hw_press("esc")
                self.sleep_ui(0.5)

            if not pos_sjy:
                self.log("找不到升級與調整")
                return False

            self.game_click(pos_sjy)
            self.sleep_ui(0.5)

            pos_cls = self.wait_for_any_image_gray(
                ["clsldcnw.png", "clsldcnb.png"],
                region=self.regions["左下"],
                threshold=0.70,
                timeout=20
            )
            if not pos_cls:
                self.log("未找到車輛熟練度")
                return False
            self.game_click(pos_cls)
            time.sleep(1.5)

            pos_exp = self.wait_for_any_image(
                ["EXPwU.png"],
                region=self.regions["左"],
                threshold=0.75,
                timeout=1.5,
                interval=0.3,
                fast_mode=True
            )

            if pos_exp:
                self.log("該車輛技能已點過，跳過計數")
            else:
                time.sleep(1.0)
                self.hw_press("enter")
                time.sleep(1.5)

                for dk in self.config["skill_dirs"]:
                    if not self.is_running:
                        return False
                    self.hw_press(dk)
                    time.sleep(0.2)
                    self.hw_press("enter")
                    time.sleep(1.2)

                spne_found = self.find_image_gray("SPNE.png", region=self.regions["全螢幕"], threshold=0.70)

                if spne_found:
                    self.log("已無技能點或技能已點完，提前結束抽獎！")
                    time.sleep(1.0)
                    self.hw_press("enter")
                    time.sleep(0.8)
                    self.hw_press("esc")
                    time.sleep(1.0)
                    self.hw_press("esc")
                    time.sleep(1.0)
                    self.hw_press("esc")
                    time.sleep(1.0)
                    return True

                self.cj_counter += 1
                self.update_running_ui("超級抽獎", self.cj_counter, target_count)

            self.hw_press("esc")
            time.sleep(1.2)
            self.hw_press("esc")
            time.sleep(0.8)
            self.hw_press("down", delay=0.08)
            time.sleep(0.8)

        self.hw_press("esc")
        time.sleep(1.2)
        self.hw_press("esc")
        time.sleep(1.2)
        return True

    # ==========================================
    # --- 模組：移除車輛 ---
    # ==========================================
    def sell_consumable_car(self, target_count):
        if self.sc_count >= target_count:
            return True

        self.update_running_ui("移除車輛", self.sc_count, target_count)

        self.log("準備驗證/進入菜單！！！使用前請人工核驗到正常移除車輛再進行自動化移除處理")
        if not self.enter_menu():
            return False

        self.log("進入車輛與收藏！！！使用前請人工核驗到正常移除車輛再進行自動化移除處理")
        self.hw_press("pagedown", delay=0.15)
        time.sleep(1.0)

        pos_buycar = self.wait_for_image("BNandUC.png", region=self.regions["左"], threshold=0.70, timeout=12, interval=0.3, fast_mode=True)
        if not pos_buycar:
            self.log("未識別到 購買新車與二手車")
            return False

        self.game_click(pos_buycar)
        time.sleep(0.8)
        self.hw_press("enter")
        time.sleep(5)

        pos_bs = self.wait_for_any_image(["buyandsell-w.png", "buyandsell-b.png"], region=self.regions["上"], threshold=0.75, timeout=40, interval=0.5, fast_mode=True)
        if not pos_bs:
            self.log("未找到購買與出售")
            return False

        self.game_click(pos_bs)
        time.sleep(1.0)

        self.hw_press("pagedown", delay=0.15)
        time.sleep(1.0)

        self.hw_press("enter")  # 進入我的車輛
        time.sleep(2.0)
        #選擇一輛收藏
        self.hw_press("y") 
        time.sleep(1.0)
        self.hw_press("enter")
        time.sleep(0.8)
        self.hw_press("esc") 
        time.sleep(1.5)
        #駕駛收藏的車
        self.hw_press("enter")
        time.sleep(0.8)
        self.move_to_game_coord(5, 5)
        time.sleep(0.2)

        pos = self.wait_for_image("rc.png", region=self.regions["全螢幕"], threshold=0.65, timeout=5, interval=0.2, fast_mode=True)
        if pos:
            self.log("找到上車，執行點擊")
            self.game_click(pos) # 【重要修復】：之前寫的是 self.safe_click 導致直接報錯崩潰，現已修正
            time.sleep(2.0)
        else:
            self.log("該車輛已經駕駛，或未找到圖片，執行兩次ESC")
            self.hw_press("esc")
            time.sleep(1.5)
            self.hw_press("esc")
        time.sleep(2.0)

        found = False
        for i in range(60):
            if not self.is_running:
                return False

            pos = self.wait_for_any_image(["buyandsell-b.png", "buyandsell-w.png"], region=self.regions["上"], threshold=0.70, timeout=0.8, interval=0.2, fast_mode=True)
            if pos:
                self.log(f"第 {i + 1} 次檢測到購買與出售，進入車輛介面")
                self.hw_press("enter")
                found = True
                break
            self.log(f"第 {i + 1} 次未檢測到購買與出售，等待後重試")
            time.sleep(1.0)
        if not found:
            self.log("60次內未找到購買與出售")
            return False
        
        time.sleep(1.5)
        # 切換排序：最近獲得
        self.hw_press("x")
        time.sleep(0.5)
        #滑鼠重定
        self.move_to_game_coord(5, 5)
        #選擇最近獲得
        self.log("切換到 最近獲得 的排序...")
        for _ in range(6):
            if not self.is_running:
                return False
            self.hw_press("down")
            time.sleep(0.25)
        time.sleep(0.2)
        self.hw_press("enter")
        time.sleep(1.2)
        self.log("回到最近獲得的前面")
        # 回到列表首項
        self.hw_press("backspace")
        time.sleep(0.8)
        self.hw_press("enter")
        time.sleep(1.5)

        self.log("開始刪除最近獲得的車輛！！！請人工確認是否移除")

        while self.sc_count < target_count:
            self.log(f"is_running = {self.is_running}")
            if not self.is_running:
                return False
            # 進入當前車輛
            self.hw_press("enter")
            time.sleep(1.2)
            #跳到從車庫移除
            for _ in range(6):
                if not self.is_running:
                    return False
                self.hw_press("down")
                time.sleep(0.2)
            self.hw_press("enter")
            time.sleep(0.5)
            #向下選擇“嗯”
            self.hw_press("down")
            time.sleep(0.3)
            #確認“嗯”
            self.hw_press("enter")
            time.sleep(0.8)
            self.sc_count += 1
            self.log(f"已嘗試刪除車輛 {self.sc_count}/{target_count}")

        for _ in range(3):
            if not self.is_running:
                return False
            self.hw_press("esc")
            time.sleep(1.0)

        return True
    
    def find_and_remove_consumable_car(self, target_count):
        if self.sc_count >= target_count:
            return True
        
        self.update_running_ui("移除車輛", self.sc_count, target_count)

        self.log("準備驗證/進入菜單！！！使用前請人工核驗到正常移除車輛再進行自動化移除處理")
        if not self.enter_menu():
            return False

        self.log("進入車輛與收藏！！！使用前請人工核驗到正常移除車輛再進行自動化移除處理")
        self.hw_press("pagedown", delay=0.15)
        time.sleep(1.0)

        pos_buycar = self.wait_for_image("BNandUC.png", region=self.regions["左"], threshold=0.70, timeout=12, interval=0.3, fast_mode=True)
        if not pos_buycar:
            self.log("未識別到 購買新車與二手車")
            return False

        self.game_click(pos_buycar)
        time.sleep(0.8)
        self.hw_press("enter")
        time.sleep(5)

        pos_bs = self.wait_for_any_image(["buyandsell-w.png", "buyandsell-b.png"], region=self.regions["上"], threshold=0.75, timeout=40, interval=0.5, fast_mode=True)
        if not pos_bs:
            self.log("未找到購買與出售")
            return False

        self.game_click(pos_bs)
        time.sleep(1.0)

        self.hw_press("pagedown", delay=0.15)
        time.sleep(1.0)

        self.hw_press("enter")  # 篩選已收藏車
        time.sleep(2.0)
        #??????
        self.hw_press("y") 
        time.sleep(1.0)
        self.hw_press("enter")
        time.sleep(0.8)
        self.hw_press("esc") 
        time.sleep(1.5)
        pos_skillcar = self.wait_for_image(
            "skillcar-rm.png",
            region=self.regions["全螢幕"],
            threshold=0.75,
            timeout=5,
            interval=0.2,
            fast_mode=True
        )
        if not pos_skillcar:
            self.log("首次未找到 skillcar-rm，返回品牌列表重新定位 CCCbrand 後再試一次...")
            self.hw_press("backspace")
            time.sleep(0.6)

            brand_pos_retry = None
            for i in range(5):
                if not self.is_running:
                    return False

                brand_pos_retry = self.wait_for_any_image_gray(
                    ["CCCbrand.png", "CCCbrand-b.png"],
                    region=self.regions["全螢幕"],
                    threshold=0.72,
                    timeout=0.8,
                    interval=0.2,
                    fast_mode=True
                )
                if brand_pos_retry:
                    break

                self.log(f"第 {i + 1} 次未識別到品牌，按 Up 後繼續嘗試...")
                self.hw_press("up")
                time.sleep(0.25)

            if brand_pos_retry:
                self.log("已重新定位到 CCCbrand，點擊後執行 Enter -> Enter -> Esc，再繼續查找 skillcar-rm...")
                self.game_click(brand_pos_retry)
                time.sleep(0.8)
                self.hw_press("enter")
                time.sleep(0.8)
                self.hw_press("enter")
                time.sleep(0.8)
                self.hw_press("esc")
                time.sleep(1.0)
                pos_skillcar = self.wait_for_image(
                    "skillcar-rm.png",
                    region=self.regions["全螢幕"],
                    threshold=0.75,
                    timeout=5,
                    interval=0.2,
                    fast_mode=True
                )
            else:
                self.log("兜底流程中未找到 CCCbrand。")

        if pos_skillcar:
            self.log("找到消耗品車輛，執行點擊")
            is_current_skillcar = self.is_current_car_slot_position(pos_skillcar)
            self.log(f"skillcar-rm 命中座標: {pos_skillcar} | {'當前乘坐車位' if is_current_skillcar else '非當前乘坐車位'}")
            if is_current_skillcar:
                self.log("命中當前乘坐的 skillcar-rm，點擊後直接識別 rc.png")
                self.game_click(pos_skillcar)  # 執行點擊
                time.sleep(0.8)
                
                # 開始尋找 rc.png (上車圖示)，設定 timeout 為 12 秒以增加容錯率
                pos = self.wait_for_image("rc.png", region=self.regions["全螢幕"], threshold=0.55, timeout=12, interval=0.2, fast_mode=True)
                if pos:
                    self.log("找到上車，執行Enter")
                    self.hw_press("enter")
                    time.sleep(2.0)
                else:
                    self.log("未找到上車，執行兩次ESC")
                    self.hw_press("esc")
                    time.sleep(1.5)
                    self.hw_press("esc")
                    time.sleep(2.0)
            else:
                self.game_click(pos_skillcar)
                time.sleep(0.6)
                self.log("命中非當前乘坐的 skillcar-rm，補一次 Enter 進入菜單")
                self.hw_press("enter")
                time.sleep(0.8)
                pos = self.wait_for_image("rc.png", region=self.regions["全螢幕"], threshold=0.65, timeout=5, interval=0.2, fast_mode=True)
                if pos:
                    self.log("找到上車，執行Enter")
                    self.hw_press("enter")
                    time.sleep(2.0)
                else:
                    self.log("未找到上車，執行兩次ESC")
                    self.hw_press("esc")
                    time.sleep(1.5)
                    self.hw_press("esc")
                    time.sleep(2.0)
        else:
            self.log("未找到消耗品車輛")

        found = False
        for i in range(30):
            if not self.is_running:
                return False

            pos = self.wait_for_any_image(["buyandsell-b.png", "buyandsell-w.png"], region=self.regions["上"], threshold=0.70, timeout=0.8, interval=0.2, fast_mode=True)
            if pos:
                self.log(f"第 {i + 1} 次檢測到購買與出售，進入車輛介面")
                self.hw_press("enter")  #進入我的車輛
                time.sleep(1.5)
                found = True
                break
            self.log(f"第 {i + 1} 次未檢測到購買與出售，等待後重試")
            time.sleep(1.0)
        if not found:
            self.log("30次內未找到購買與出售")
            return False
        #篩選
        self.hw_press("y")
        time.sleep(1.0)
        is_winter_season = self.var_winter_season.get() if hasattr(self, "var_winter_season") else self.config.get("is_winter_season", False)
        filter_down_count = 4 if is_winter_season else 2
        self.log(f"當前刪車篩選模式: {'冬季' if filter_down_count == 4 else '非冬季'}，向下選擇 {filter_down_count} 次。")
        for _ in range(filter_down_count):
            self.hw_press("down", delay=0.06)
            time.sleep(0.2)
        time.sleep(0.5)
        self.hw_press("enter")
        time.sleep(1.0)
        self.hw_press("esc")
        time.sleep(1.0)


        #切換到消耗品品牌
        self.log("切換到消耗品品牌...")
        self.hw_press("backspace")
        time.sleep(1.2)
        self.log("已進入製造商列表，直接按 Enter 確認當前品牌。")
        self.hw_press("enter")
        time.sleep(0.8)
        
        self.log("開始刪除最近獲得的車輛！！！請人工確認是否移除")
        
        not_found_pages = 0  
        while self.sc_count < target_count:
            if not self.is_running:
                return False
            self.log(f"正在使用 3模式 嚴格掃描當前頁面... (連續未找到: {not_found_pages}/5)")
            
            # 【使用終極安全鎖】：2張圖，4道防線，絕不亂刪
            pos_target = self.wait_for_image_ultimate_safe(
                main_path="removecarobject.png",  # 你要刪的車的截圖
                anti_path="newcartag.png",        # NEW標籤截圖
                region=self.regions["全螢幕"],
                main_threshold=0.77,              # 極高的基礎相似度要求
                anti_threshold=0.65,              # 極度敏感的 NEW 標籤排斥
                timeout=3.0,
                interval=0.2
            )
            
            if not pos_target:
                not_found_pages += 1
                if not_found_pages >= 8:
                    self.log("=連續翻找 2 頁仍未搜索到目標車輛！視為車輛已全部清理完畢。")
                    self.log("主動結束清理任務，準備進入下一步驟...")
                    break  # 直接跳出迴圈，結束當前任務
                    
                self.log(f"當前頁面未找到，向右翻頁尋找... (第 {not_found_pages} 次翻頁)")
                for _ in range(4):
                    self.hw_press("right", delay=0.06)
                    time.sleep(0.1)
                time.sleep(0.4)
                continue
            # ====== 找到了目標車輛，重置翻頁計數器 ======
            not_found_pages = 0
            
            self.log("精准鎖定目標車輛，執行點擊...")
            self.game_click(pos_target)
            time.sleep(1.2) # 等待點擊後的反應
            
            # ==========================================
            # 核心邏輯：尋找 removecar.png (從車庫移除)
            # ==========================================
            self.log("尋找 '從車庫移除' 按鈕...")
            pos_remove = self.find_image_gray("removecar.png", region=self.regions["全螢幕"], threshold=0.75, fast_mode=True)
            
            if pos_remove:
                self.log("直接找到移除按鈕，點擊...")
                self.game_click(pos_remove)
            else:
                self.log("未直接找到移除按鈕，按下 Enter 呼出菜單...")
                self.hw_press("enter")
                time.sleep(0.8) # 等待菜單彈出動畫
                
                # 再次尋找
                pos_remove = self.find_image_gray("removecar.png", region=self.regions["全螢幕"], threshold=0.75, fast_mode=True)
                if pos_remove:
                    self.log("呼出功能表後找到移除按鈕，點擊...")
                    self.game_click(pos_remove)
                else:
                    self.log("仍未找到移除按鈕，可能點錯了/該車無法移除，按 ESC 放棄該車...")
                    self.hw_press("esc")
                    time.sleep(1.0)
                    self.hw_press("right") # 往右挪一格，防止閉環一直點這輛假車
                    time.sleep(1.2)
                    continue
                    
            time.sleep(0.8) # 等待“你確定要移除嗎”的確認彈窗
            
            # 確認移除操作 (按向下選"嗯"，然後回車)
            self.log("確認移除...")
            self.hw_press("down")
            time.sleep(0.3)
            self.hw_press("enter")
            time.sleep(1.2)

            
            self.sc_count += 1
            self.update_running_ui("移除車輛", self.sc_count, target_count)
            self.log(f"成功移除車輛！當前進度: {self.sc_count}/{target_count}")

        # 迴圈結束，退回上一級
        for _ in range(3):
            if not self.is_running:
                return False
            self.hw_press("esc")
            time.sleep(1.0)

        return True
 
    #===============================
    #---自動超級抽獎-----
    #===============================
if __name__ == "__main__":
    app = FH_UltimateBot()
    app.mainloop()

