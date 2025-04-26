import cv2
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from ttkbootstrap import Style
from ttkbootstrap.constants import SUCCESS, INFO
from PIL import Image, ImageTk
import os
import numpy as np
import tifffile
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

class MicroscopeApp:
    def __init__(self, root):
        self.root = root
        root.title("Mikroskop GUI")
        self.style = Style(theme="darkly")

        # Fenstergröße und Spaltengewichtung
        root.geometry('2000x1150')
        root.grid_columnconfigure(0, weight=1)
        root.grid_columnconfigure(1, weight=1)

        # Reiter für Vergrößerung und Hauptansicht
        self.notebook = ttk.Notebook(root)
        self.notebook.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.mag_frame = ttk.Frame(self.notebook)
        self.main_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.mag_frame, text='Vergrößerung')
        self.notebook.add(self.main_frame, text='Live & Einstellungen')

        # Auswahl der Vergrößerung
        ttk.Label(self.mag_frame, text="Vergrößerung wählen:").grid(row=0, column=0, padx=5, pady=5)
        self.mag_var = tk.IntVar(value=1)
        for i, mag in enumerate([1,2,4]):
            ttk.Radiobutton(
                self.mag_frame,
                text=f"{mag}x",
                variable=self.mag_var,
                value=mag,
                command=self.update_calibration
            ).grid(row=1, column=i, padx=5, pady=5)

        # Kalibrierungs-Variablen (µm/px und Skalenlänge)
        self.um_per_px_var = tk.DoubleVar(value=4.65)
        self.scale_length_var = tk.DoubleVar(value=1000.0)

        # --- Haupt-Frame Aufbau ---
        mf = self.main_frame

        # Kamera initialisieren
        cams = self.get_available_cameras()
        if not cams:
            messagebox.showerror("Kamera nicht gefunden", "Keine Kamera erkannt.")
            root.destroy()
            return
        self.cam_index = tk.IntVar(value=cams[0])
        self.cap = cv2.VideoCapture(self.cam_index.get())
        self.set_max_resolution()

        # Live-Histogramm links
        self.fig = Figure(figsize=(3,2), dpi=80)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_title('Histogramm (Grau)')
        self.ax.set_xlim(0,256)
        self.canvas = FigureCanvasTkAgg(self.fig, master=mf)
        self.canvas.get_tk_widget().grid(row=0, column=0, padx=5, pady=5)

        # Live-Video rechts
        self.video_frame = ttk.Label(mf)
        self.video_frame.grid(row=0, column=1, padx=5, pady=5)

        # Steuer-Widgets
        ttk.Label(mf, text="Kamera:").grid(row=1, column=0, sticky=tk.W, padx=5)
        self.cam_select = ttk.Combobox(
            mf,
            values=cams,
            textvariable=self.cam_index,
            state="readonly",
            width=5
        )
        self.cam_select.grid(row=1, column=1, sticky=tk.W)
        self.cam_select.bind("<<ComboboxSelected>>", self.change_camera)
        self.resolution_label = ttk.Label(mf, text="Auflösung: -- x --")
        self.resolution_label.grid(row=1, column=2, sticky=tk.W, padx=5)

        ttk.Label(mf, text="Ordner:").grid(row=2, column=0, sticky=tk.W, padx=5)
        ttk.Button(mf, text="Wählen", command=self.select_folder, bootstyle=INFO).grid(row=2, column=1)
        ttk.Label(mf, text="Basisname:").grid(row=3, column=0, sticky=tk.W, padx=5)
        self.basename_var = tk.StringVar(value="bild")
        ttk.Entry(mf, textvariable=self.basename_var, width=20).grid(row=3, column=1)

        self.show_scale_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            mf,
            text="Skalenleiste anzeigen",
            variable=self.show_scale_var
        ).grid(row=2, column=2, sticky=tk.W, padx=5)

        ttk.Label(mf, text="um/px:").grid(row=2, column=3, sticky=tk.W)
        ttk.Entry(mf, textvariable=self.um_per_px_var, width=10).grid(row=2, column=4)
        ttk.Label(mf, text="Skalenlänge um:").grid(row=3, column=3, sticky=tk.W)
        ttk.Entry(mf, textvariable=self.scale_length_var, width=10).grid(row=3, column=4)

        ttk.Button(
            mf,
            text="Bild aufnehmen",
            bootstyle=SUCCESS,
            command=self.capture_image
        ).grid(row=4, column=0, pady=5)
        ttk.Label(mf, text="Stack-Bilder:").grid(row=4, column=1)
        self.stack_count_var = tk.IntVar(value=10)
        ttk.Combobox(
            mf,
            textvariable=self.stack_count_var,
            values=[3,5,10,15,20,30],
            width=5,
            state="readonly"
        ).grid(row=4, column=2)
        ttk.Button(
            mf,
            text="Stack-Foto aufnehmen",
            bootstyle=INFO,
            command=self.capture_stack_image
        ).grid(row=4, column=3)

        # Slider für Kameraeinstellungen
        controls = [
            ("Belichtung", cv2.CAP_PROP_EXPOSURE, -13, -1, True, cv2.CAP_PROP_AUTO_EXPOSURE),
            ("Gain", cv2.CAP_PROP_GAIN, 0, 255, False, None),
            ("Kontrast", cv2.CAP_PROP_CONTRAST, -100, 100, False, None),
            ("Helligkeit", cv2.CAP_PROP_BRIGHTNESS, 0, 255, False, None),
            ("Weißabgleich", cv2.CAP_PROP_WHITE_BALANCE_BLUE_U, 2800, 6500, True, cv2.CAP_PROP_AUTO_WB),
        ]
        for idx, (label, pid, mn, mx, auto, auto_pid) in enumerate(controls, start=5):
            self.add_slider(label, pid, mn, mx, auto, auto_pid, frame=mf, row=idx)

        # Start Live-Update
        self.update_frame()

    def update_calibration(self):
        mag = self.mag_var.get()
        base_um_per_px = 4.65
        self.um_per_px_var.set(base_um_per_px / mag)
        self.scale_length_var.set(1000.0)

    def get_available_cameras(self, max_tested=5):
        cams = []
        for i in range(max_tested):
            cap = cv2.VideoCapture(i)
            if cap.read()[0]:
                cams.append(i)
            cap.release()
        return cams

    def change_camera(self, event=None):
        self.cap.release()
        self.cap = cv2.VideoCapture(self.cam_index.get())
        self.set_max_resolution()

    def set_max_resolution(self):
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        self.root.after(500, self.update_resolution_label)

    def update_resolution_label(self):
        w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.resolution_label.config(text=f"Auflösung: {w} x {h}")

    def add_slider(self, text, prop_id, frm, to, auto_ctrl, auto_pid, frame, row):
        ttk.Label(frame, text=text).grid(row=row, column=0, sticky=tk.W, padx=5)
        slider = ttk.Scale(
            frame,
            from_=frm,
            to=to,
            orient=tk.HORIZONTAL,
            command=lambda v, p=prop_id: self.update_property(p, float(v))
        )
        slider.set(self.cap.get(prop_id))
        slider.grid(row=row, column=1, columnspan=3, sticky=tk.EW, padx=5)
        if auto_ctrl and auto_pid is not None:
            ttk.Button(
                frame,
                text="Auto",
                command=lambda p=auto_pid: self.set_auto(p)
            ).grid(row=row, column=4, padx=5)

    def set_auto(self, pid):
        self.cap.set(pid, 0.75 if pid == cv2.CAP_PROP_AUTO_EXPOSURE else 1)

    def update_property(self, pid, val):
        if pid == cv2.CAP_PROP_EXPOSURE:
            self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
        if pid == cv2.CAP_PROP_WHITE_BALANCE_BLUE_U:
            self.cap.set(cv2.CAP_PROP_AUTO_WB, 0)
        self.cap.set(pid, val)

    def select_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.capture_folder = folder
            self.image_counter = 1

    def draw_scale_bar(self, img):
        if not self.show_scale_var.get():
            return img
        try:
            upx = float(self.um_per_px_var.get())
            length_um = float(self.scale_length_var.get())
        except (tk.TclError, ValueError):
            return img
        if upx <= 0 or length_um <= 0:
            return img
        h, w, _ = img.shape
        length_px = int(length_um / upx)
        y0 = h - 20
        x0 = 10
        x1 = x0 + length_px
        cv2.rectangle(img, (x0, y0), (x1, y0+5), (255,255,255), -1)
        cv2.putText(
            img,
            f"{int(length_um)} um",
            (x0, y0-5),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255,255,255),
            1
        )
        return img

    def capture_image(self):
        if not getattr(self, 'capture_folder', None):
            messagebox.showwarning("Kein Speicherordner", "Bitte zuerst einen Speicherordner wählen.")
            return
        ret, frame = self.cap.read()
        if ret:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb = self.draw_scale_bar(rgb)
            name = f"{self.basename_var.get()}_{self.image_counter:04}.tif"
            tifffile.imwrite(os.path.join(self.capture_folder, name), rgb)
            self.image_counter += 1

    def capture_stack_image(self):
        if not getattr(self, 'capture_folder', None):
            messagebox.showwarning("Kein Speicherordner", "Bitte zuerst einen Speicherordner wählen.")
            return
        count = self.stack_count_var.get()
        frames = []
        for _ in range(count):
            ret, frame = self.cap.read()
            if ret:
                frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).astype(np.float32))
            self.root.after(50)
        if frames:
            avg = np.mean(frames, axis=0).astype(np.uint8)
            avg = self.draw_scale_bar(avg)
            name = f"{self.basename_var.get()}_{self.image_counter:04}_stack.tif"
            tifffile.imwrite(os.path.join(self.capture_folder, name), avg)
            self.image_counter += 1

    def update_frame(self):
        ret, frame = self.cap.read()
        if ret:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            hist = cv2.calcHist([gray], [0], None, [256], [0,256])
            self.ax.clear()
            self.ax.plot(hist)
            self.ax.set_xlim(0,256)
            self.ax.set_title('Histogramm (Grau)')
            self.canvas.draw()

            disp_full = self.draw_scale_bar(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).copy())
            disp_resized = cv2.resize(disp_full, (1280, 720), interpolation=cv2.INTER_AREA)
            img = ImageTk.PhotoImage(Image.fromarray(disp_resized))
            self.video_frame.imgtk = img
            self.video_frame.config(image=img)

        self.root.after(100, self.update_frame)

if __name__ == "__main__":
    root = tk.Tk()
    MicroscopeApp(root)
    root.mainloop()