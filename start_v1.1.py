import cv2
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
import threading
import queue
import time
import datetime
import os
import sys
import platform

class VideoRecorderApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"WebCam Recorder Pro v7.0 ({platform.system()})")
        self.root.geometry("920x760")
        
        # --- Определение ОС ---
        self.is_windows = sys.platform.startswith('win')
        self.is_mac = sys.platform == 'darwin'
        self.is_linux = sys.platform.startswith('linux')

        # Стилизация (попытка включить нативный вид)
        style = ttk.Style()
        try: style.theme_use('clam')
        except: pass

        # --- Инициализация переменных ---
        self.msg_queue = queue.Queue()
        self.frame_queue = queue.Queue(maxsize=2)
        self.lock = threading.Lock()
        self.stop_thread = False
        self.is_recording = False
        
        self.last_record_time = time.time()
        self.last_preview_time = time.time()
        self.start_time = 0
        self.out = None
        self.output_file = ""

        # --- Выбор бэкенда камеры ---
        if self.is_windows:
            self.video_backend = cv2.CAP_DSHOW
        elif self.is_mac:
            self.video_backend = cv2.CAP_AVFOUNDATION
        elif self.is_linux:
            self.video_backend = cv2.CAP_V4L2
        else:
            self.video_backend = cv2.CAP_ANY

        # --- Поиск камер ---
        self.available_cameras = self.detect_cameras()
        if not self.available_cameras:
            messagebox.showerror("Ошибка", "Камеры не обнаружены!\nПодключите устройство и перезапустите программу.")
            self.root.destroy()
            return

        self.resolutions = [
            (640, 480),
            (1280, 720),
            (1920, 1080),
            (2560, 1440)
        ]
        
        self.codecs = [
            ('H.264 (MP4) - Best', 'avc1', 'mp4'),
            ('H.264 (MP4) - Alt', 'H264', 'mp4'),
            ('MPEG-4 (MP4)', 'mp4v', 'mp4'),
            ('MJPG (AVI) - Stable', 'MJPG', 'avi'),
            ('XVID (AVI)', 'XVID', 'avi')
        ]
        
        self.quality_multipliers = {'Низкое': 0.5, 'Среднее': 1.0, 'Высокое': 2.0, 'Ультра': 4.0}
        self.base_bitrates = {
            (640, 480): 1500, (1280, 720): 4000, 
            (1920, 1080): 8000, (2560, 1440): 15000
        }

        # --- Дефолтные настройки ---
        self.current_cam_idx = self.available_cameras[0]['index']
        self.current_res = self.resolutions[1] if len(self.resolutions) > 1 else self.resolutions[0]
        self.record_fps = 30.0
        self.frame_interval = 1.0 / self.record_fps
        
        # АВТО-ВЫБОР КОДЕКА: Windows -> H.264, Mac/Linux -> MJPG
        # Это гарантирует, что программа заработает "из коробки" везде
        default_codec_idx = 3 if (self.is_mac or self.is_linux) else 0
        
        self.current_codec = self.codecs[default_codec_idx]
        self.current_quality = 'Среднее'
        
        self.preview_size = self.calculate_preview_size(self.current_res)

        # UI и запуск
        self.create_widgets()
        self.codec_combo.current(default_codec_idx) # Синхронизация UI
        
        self.video_thread = threading.Thread(target=self.video_loop, daemon=True)
        self.video_thread.start()
        
        self.update_gui_loop()

    def detect_cameras(self):
        cameras = []
        for i in range(5):
            try:
                cap = cv2.VideoCapture(i, self.video_backend)
                if cap.isOpened():
                    ret, _ = cap.read()
                    if ret:
                        name = f"Камера #{i}"
                        if self.is_mac: name += " (AVFoundation)"
                        elif self.is_windows: name += " (DShow)"
                        elif self.is_linux: name += " (V4L2)"
                        cameras.append({'index': i, 'name': name})
                    cap.release()
            except: pass
        return cameras

    def calculate_preview_size(self, resolution):
        max_w = 720
        w, h = resolution
        if h == 0: return (640, 480)
        ratio = w / h
        new_w = min(w, max_w)
        return (new_w, int(new_w / ratio))

    def create_widgets(self):
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        ctrl_frame = ttk.LabelFrame(main_frame, text="Параметры")
        ctrl_frame.pack(fill=tk.X, pady=5)
        
        grid_opts = {'padx': 5, 'pady': 5, 'sticky': tk.W}
        
        ttk.Label(ctrl_frame, text="Источник:").grid(row=0, column=0, **grid_opts)
        self.cam_combo = ttk.Combobox(ctrl_frame, values=[c['name'] for c in self.available_cameras], state="readonly", width=22)
        self.cam_combo.current(0)
        self.cam_combo.bind("<<ComboboxSelected>>", self.update_settings)
        self.cam_combo.grid(row=0, column=1, **grid_opts)
        
        ttk.Label(ctrl_frame, text="Размер:").grid(row=0, column=2, **grid_opts)
        self.res_combo = ttk.Combobox(ctrl_frame, values=[f"{w}x{h}" for w,h in self.resolutions], state="readonly", width=12)
        self.res_combo.current(1)
        self.res_combo.bind("<<ComboboxSelected>>", self.update_settings)
        self.res_combo.grid(row=0, column=3, **grid_opts)
        
        ttk.Label(ctrl_frame, text="FPS:").grid(row=0, column=4, **grid_opts)
        self.fps_combo = ttk.Combobox(ctrl_frame, values=["15", "24", "30", "60"], state="readonly", width=5)
        self.fps_combo.current(2)
        self.fps_combo.bind("<<ComboboxSelected>>", self.update_settings)
        self.fps_combo.grid(row=0, column=5, **grid_opts)

        ttk.Label(ctrl_frame, text="Кодек:").grid(row=1, column=0, **grid_opts)
        self.codec_combo = ttk.Combobox(ctrl_frame, values=[c[0] for c in self.codecs], state="readonly", width=25)
        self.codec_combo.current(0)
        self.codec_combo.bind("<<ComboboxSelected>>", self.update_settings)
        self.codec_combo.grid(row=1, column=1, columnspan=2, **grid_opts)

        ttk.Label(ctrl_frame, text="Качество:").grid(row=1, column=3, **grid_opts)
        self.qual_combo = ttk.Combobox(ctrl_frame, values=list(self.quality_multipliers.keys()), state="readonly", width=10)
        self.qual_combo.current(1)
        self.qual_combo.bind("<<ComboboxSelected>>", self.update_settings)
        self.qual_combo.grid(row=1, column=4, columnspan=2, **grid_opts)

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(pady=5)
        
        self.rec_btn = ttk.Button(btn_frame, text="🔴 НАЧАТЬ ЗАПИСЬ", command=self.toggle_recording)
        self.rec_btn.pack(side=tk.LEFT, padx=10)
        
        ttk.Button(btn_frame, text="Выход", command=self.safe_exit).pack(side=tk.LEFT, padx=10)
        
        self.video_label = tk.Label(main_frame, bg="black")
        self.video_label.pack(fill=tk.BOTH, expand=True)
        
        self.status_var = tk.StringVar(value=f"Система готова ({platform.system()})")
        self.status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def update_settings(self, event=None):
        with self.lock:
            self.current_cam_idx = self.available_cameras[self.cam_combo.current()]['index']
            w, h = self.resolutions[self.res_combo.current()]
            self.current_res = (w, h)
            self.preview_size = self.calculate_preview_size((w, h))
            self.record_fps = float(self.fps_combo.get())
            self.frame_interval = 1.0 / self.record_fps
            self.current_codec = self.codecs[self.codec_combo.current()]
            self.current_quality = self.qual_combo.get()

    def start_recording(self):
        save_dir = filedialog.askdirectory()
        if not save_dir: return
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        priority_codecs = [self.current_codec] + [c for c in self.codecs if c != self.current_codec]

        for name, fourcc_str, ext in priority_codecs:
            filename = os.path.join(save_dir, f"Video_{timestamp}.{ext}")
            fourcc = cv2.VideoWriter_fourcc(*fourcc_str)

            try:
                if self.is_windows and fourcc_str in ['avc1', 'H264']:
                    self.out = cv2.VideoWriter(filename, fourcc, self.record_fps, self.current_res, apiPreference=cv2.CAP_FFMPEG)
                else:
                    self.out = cv2.VideoWriter(filename, fourcc, self.record_fps, self.current_res)

                if self.out and self.out.isOpened():
                    self.output_file = filename
                    self.is_recording = True
                    self.start_time = time.time()
                    self.last_record_time = time.time()
                    
                    self.rec_btn.config(text="⏹ ОСТАНОВИТЬ ЗАПИСЬ")
                    self.disable_controls(True)
                    self.status_var.set(f"ЗАПИСЬ → {name}")
                    self.update_timer()
                    return
            except Exception:
                continue

        messagebox.showerror("Ошибка", "Не удалось запустить запись.\nПопробуйте кодек MJPG.")

    def stop_recording(self):
        self.is_recording = False
        time.sleep(0.5) 
        
        if self.out:
            self.out.release()
            self.out = None

        self.rec_btn.config(text="🔴 НАЧАТЬ ЗАПИСЬ")
        self.disable_controls(False)
        
        if os.path.exists(self.output_file) and os.path.getsize(self.output_file) > 1024:
            size_mb = os.path.getsize(self.output_file) / (1024*1024)
            messagebox.showinfo("Успех", f"Файл сохранен:\n{os.path.basename(self.output_file)}\nРазмер: {size_mb:.2f} MB")
        else:
            messagebox.showerror("Ошибка", "Файл пустой или не создан.")
        self.status_var.set("Готов к работе")

    def toggle_recording(self):
        if self.is_recording:
            self.stop_recording()
        else:
            self.start_recording()

    def video_loop(self):
        cap = None
        current_params = None
        
        while not self.stop_thread:
            try:
                with self.lock:
                    tgt_idx = self.current_cam_idx
                    tgt_res = self.current_res
                    tgt_fps = self.record_fps

                new_params = (tgt_idx, tgt_res, tgt_fps)
                if current_params != new_params:
                    if cap: cap.release()
                    cap = cv2.VideoCapture(tgt_idx, self.video_backend)
                    
                    try: cap.set(cv2.CAP_PROP_FRAME_WIDTH, tgt_res[0])
                    except: pass
                    try: cap.set(cv2.CAP_PROP_FRAME_HEIGHT, tgt_res[1])
                    except: pass
                    try: cap.set(cv2.CAP_PROP_FPS, tgt_fps)
                    except: pass
                    
                    # Буфер=1 только на Win/Linux
                    if not self.is_mac:
                        try: cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                        except: pass
                    
                    current_params = new_params
                    time.sleep(0.5)

                if not cap or not cap.isOpened():
                    time.sleep(1)
                    continue

                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.01)
                    continue

                now = time.time()

                if self.is_recording and self.out:
                    if now - self.last_record_time >= self.frame_interval:
                        if (frame.shape[1], frame.shape[0]) != tgt_res:
                            write_frame = cv2.resize(frame, tgt_res)
                        else:
                            write_frame = frame
                        try:
                            self.out.write(write_frame)
                            self.last_record_time = now
                        except: pass

                if now - self.last_preview_time >= 0.030:
                    small = cv2.resize(frame, self.preview_size)
                    rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
                    img = ImageTk.PhotoImage(Image.fromarray(rgb))
                    
                    while not self.frame_queue.empty():
                        try: self.frame_queue.get_nowait()
                        except queue.Empty: pass
                    
                    self.frame_queue.put(img)
                    self.last_preview_time = now

            except Exception:
                time.sleep(1)
        
        if cap: cap.release()
        if self.out: self.out.release()

    def update_gui_loop(self):
        try:
            img = self.frame_queue.get_nowait()
            self.video_label.config(image=img)
            self.video_label.image = img
        except queue.Empty:
            pass
        if not self.stop_thread:
            self.root.after(15, self.update_gui_loop)

    def update_timer(self):
        if self.is_recording:
            elapsed = int(time.time() - self.start_time)
            m, s = divmod(elapsed, 60)
            sz = "0KB"
            if os.path.exists(self.output_file):
                sz = f"{os.path.getsize(self.output_file)/1024:.0f}KB"
            self.status_var.set(f"REC ● {m:02d}:{s:02d} | {sz}")
            self.root.after(1000, self.update_timer)

    def disable_controls(self, val):
        state = "disabled" if val else "readonly"
        for w in [self.cam_combo, self.res_combo, self.fps_combo, self.codec_combo, self.qual_combo]:
            w.config(state=state)

    def safe_exit(self):
        self.stop_thread = True
        if self.is_recording:
            self.is_recording = False
            if self.out: self.out.release()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = VideoRecorderApp(root)
    root.protocol("WM_DELETE_WINDOW", app.safe_exit)
    root.mainloop()
