import os
import sys
import queue
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# The portable build bundles Chromium inside PyInstaller's extraction directory.
# Existing builds still use the browser installed in the Windows user cache.
if sys.platform == 'win32' and getattr(sys, 'frozen', False):
    bundled_browsers = (Path(sys._MEIPASS) / 'playwright' / 'driver' /
                        'package' / '.local-browsers')
    if bundled_browsers.is_dir():
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(bundled_browsers)
    elif os.environ.get('LOCALAPPDATA'):
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(
            Path(os.environ['LOCALAPPDATA']) / 'ms-playwright'
        )

from excel_reader import load_jobs, validate_run_dates
from notehrm_adapter import NoteHrmAutomation

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("NOTE HRM – Tự động đăng ký kế hoạch công việc")
        self.root.geometry("1180x720")
        self.root.minsize(980, 620)

        self.rows = []
        self.passwords = {}
        self.stop_event = threading.Event()
        self.worker = None
        self.log_queue = queue.Queue()

        self.visible_browser = tk.BooleanVar(value=True)
        self.plan_name = tk.StringVar(value="Kế hoạch công việc quý 3")
        self.content = tk.StringVar(value="Kế hoạch công việc quý 3")
        self.form_start = tk.StringVar(value="01/07/2026")
        self.form_end = tk.StringVar(value="30/09/2026")
        self.all_deadline = tk.StringVar(value="30/09/2026")

        self._build()

        self.root.after(150, self._drain_logs)

    def _build(self):
        pad = {"padx": 8, "pady": 6}

        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)

        ttk.Label(top, text="Tên kế hoạch:").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.plan_name, width=35).grid(row=0, column=1, sticky="ew")
        ttk.Label(top, text="Nội dung:").grid(row=0, column=2, sticky="w")
        ttk.Entry(top, textvariable=self.content, width=35).grid(row=0, column=3, sticky="ew")
        top.columnconfigure(1, weight=1)
        top.columnconfigure(3, weight=1)

        dates = ttk.Frame(self.root)
        dates.pack(fill="x", **pad)
        for index, (label, variable) in enumerate((
            ("Ngày bắt đầu phiếu:", self.form_start),
            ("Ngày kết thúc phiếu:", self.form_end),
            ("Hạn hoàn thành mọi dòng:", self.all_deadline),
        )):
            ttk.Label(dates, text=label).grid(row=0, column=index * 2, padx=(0, 5))
            ttk.Entry(dates, textvariable=variable, width=14).grid(
                row=0, column=index * 2 + 1, padx=(0, 18)
            )
        ttk.Label(dates, text="DD/MM/YYYY").grid(row=0, column=6, sticky="w")

        controls = ttk.Frame(self.root)
        controls.pack(fill="x", **pad)
        ttk.Button(controls, text="+ Thêm tài khoản", command=self.add_row).pack(side="left", padx=4)
        ttk.Button(controls, text="Xóa dòng", command=self.remove_selected).pack(side="left", padx=4)
        ttk.Button(controls, text="Kiểm tra Excel", command=self.validate_selected).pack(side="left", padx=4)
        ttk.Checkbutton(
            controls,
            text="Hiện trình duyệt khi chạy",
            variable=self.visible_browser,
        ).pack(side="left", padx=12)
        ttk.Button(controls, text="RUN", command=self.start).pack(side="right", padx=4)
        ttk.Button(controls, text="DỪNG", command=self.stop).pack(side="right", padx=4)

        table_frame = ttk.Frame(self.root)
        table_frame.pack(fill="both", expand=True, padx=8, pady=6)

        columns = ("stt", "username", "password", "file", "status")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=10)
        self.tree.heading("stt", text="#")
        self.tree.heading("username", text="Tài khoản")
        self.tree.heading("password", text="Mật khẩu")
        self.tree.heading("file", text="File Excel")
        self.tree.heading("status", text="Trạng thái")
        self.tree.column("stt", width=45, anchor="center")
        self.tree.column("username", width=210)
        self.tree.column("password", width=180)
        self.tree.column("file", width=440)
        self.tree.column("status", width=220)

        vs = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", self._edit_cell)

        hint = ttk.Label(
            self.root,
            text="Double-click ô để sửa. Cột File Excel: double-click để chọn file.",
        )
        hint.pack(fill="x", padx=8)

        log_frame = ttk.LabelFrame(self.root, text="Nhật ký chạy")
        log_frame.pack(fill="both", expand=True, padx=8, pady=8)
        self.log_text = tk.Text(log_frame, height=12, wrap="word")
        self.log_text.pack(fill="both", expand=True)

        self.add_row()

    def add_row(self):
        idx = len(self.rows) + 1
        item = self.tree.insert("", "end", values=(idx, "", "", "", "Chưa chạy"))
        self.rows.append(item)
        self.tree.selection_set(item)

    def remove_selected(self):
        for item in self.tree.selection():
            self.passwords.pop(item, None)
            if item in self.rows:
                self.rows.remove(item)
            self.tree.delete(item)
        self._renumber()

    def _renumber(self):
        for idx, item in enumerate(self.rows, start=1):
            vals = list(self.tree.item(item, "values"))
            if vals:
                vals[0] = idx
                self.tree.item(item, values=vals)

    def _edit_cell(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        item = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not item:
            return
        col_index = int(col[1:]) - 1
        if col_index == 0 or col_index == 4:
            return

        vals = list(self.tree.item(item, "values"))
        bbox = self.tree.bbox(item, col)
        if not bbox:
            return
        x, y, w, h = bbox

        if col_index == 3:
            path = filedialog.askopenfilename(
                title="Chọn file Excel",
                filetypes=[("Excel", "*.xlsx"), ("All files", "*.*")]
            )
            if path:
                vals[3] = path
                self.tree.item(item, values=vals)
            return

        entry = ttk.Entry(self.tree, show='*' if col_index == 2 else '')
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, self.passwords.get(item, '') if col_index == 2
                     else vals[col_index])
        entry.focus_set()

        def save_edit(_=None):
            if not entry.winfo_exists():
                return
            value = entry.get().strip()
            if col_index == 2:
                self.passwords[item] = value
                vals[col_index] = '*' * len(value)
            else:
                vals[col_index] = value
            self.tree.item(item, values=vals)
            entry.destroy()

        entry.bind("<Return>", save_edit)
        entry.bind("<FocusOut>", save_edit)

    def validate_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Kiểm tra", "Chọn một dòng trước.")
            return
        vals = self.tree.item(sel[0], "values")
        path = vals[3]
        if not path:
            messagebox.showwarning("Kiểm tra", "Dòng này chưa có file Excel.")
            return
        try:
            jobs = load_jobs(path)
            validate_run_dates(
                self.form_start.get(), self.form_end.get(),
                self.all_deadline.get(), [(path, jobs)],
            )
            messagebox.showinfo("Excel hợp lệ", f"Tìm thấy {len(jobs)} dòng công việc hợp lệ.")
            self._log(f"[OK] {path}: {len(jobs)} dòng hợp lệ.")
        except Exception as e:
            messagebox.showerror("Excel không hợp lệ", str(e))
            self._log(f"[LỖI] {path}: {e}")

    def _log(self, msg):
        self.log_queue.put(msg)

    def _drain_logs(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                if isinstance(msg, tuple) and msg[0] == "status":
                    self._set_status(msg[1], msg[2])
                else:
                    self.log_text.insert("end", msg + "\n")
                    self.log_text.see("end")
        except queue.Empty:
            pass
        self.root.after(150, self._drain_logs)

    def _set_status(self, item, status):
        vals = list(self.tree.item(item, "values"))
        vals[4] = status
        self.tree.item(item, values=vals)

    def start(self):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("Đang chạy", "Tool đang chạy.")
            return

        jobs = []
        for item in self.rows:
            vals = self.tree.item(item, "values")
            username, password, excel = vals[1], self.passwords.get(item), vals[3]
            if not username or not password or not excel:
                messagebox.showerror(
                    "Thiếu dữ liệu",
                    "Mỗi dòng phải có Tài khoản + Mật khẩu + File Excel."
                )
                return
            jobs.append((item, username, password, excel))

        # Snapshot UI values on the UI thread before starting a worker.
        config = {
            'start_date': self.form_start.get().strip(),
            'end_date': self.form_end.get().strip(),
            'deadline_date': self.all_deadline.get().strip(),
            'plan_name': self.plan_name.get().strip(),
            'content': self.content.get().strip(),
            'visible': self.visible_browser.get(),
        }
        if not config['plan_name'] or not config['content']:
            messagebox.showerror("Thiếu dữ liệu", "Nhập Tên kế hoạch và Nội dung.")
            return

        # Pre-validate all files and dates before opening browser/login.
        checked = []
        for item, username, password, excel in jobs:
            try:
                checked.append((excel, load_jobs(excel)))
            except Exception as e:
                self._set_status(item, "LỖI Excel – chưa chạy")
                messagebox.showerror(
                    "Dữ liệu Excel không hợp lệ",
                    f"Tài khoản: {username}\n\n{e}\n\nTool chưa đăng nhập tài khoản nào."
                )
                return
        try:
            (config['start_date'], config['end_date'],
             config['deadline_date']) = validate_run_dates(
                config['start_date'], config['end_date'],
                config['deadline_date'], checked,
            )
        except ValueError as e:
            messagebox.showerror("Ngày không hợp lệ", str(e))
            return

        self.stop_event.clear()
        self.worker = threading.Thread(target=self._run_queue, args=(jobs, config), daemon=True)
        self.worker.start()

    def stop(self):
        self.stop_event.set()
        self._log("[DỪNG] Đã gửi yêu cầu dừng. Tool sẽ dừng ở bước an toàn gần nhất.")

    def _run_queue(self, jobs, config):
        for item, username, password, excel in jobs:
            if self.stop_event.is_set():
                self.log_queue.put(("status", item, "Đã dừng"))
                break

            self.log_queue.put(("status", item, "Đang chạy..."))
            self._log(f"\n=== BẮT ĐẦU: {username} ===")
            try:
                automation = NoteHrmAutomation(
                    visible=config['visible'],
                    log=self._log,
                    stop_event=self.stop_event,
                )
                automation.run_account(
                    username=username,
                    password=password,
                    excel_path=excel,
                    plan_name=config['plan_name'],
                    content=config['content'],
                    start_date=config['start_date'],
                    end_date=config['end_date'],
                    deadline_date=config['deadline_date'],
                )
                self.log_queue.put(("status", item, "THÀNH CÔNG"))
                self._log(f"[OK] {username}: hoàn tất.")
            except Exception as e:
                self.log_queue.put(("status", item, f"LỖI: {e}"))
                self._log(f"[LỖI] {username}: {e}")
                self._log("[DỪNG QUEUE] Một tài khoản lỗi → dừng toàn bộ tài khoản còn lại.")
                break

        self._log("\n=== KẾT THÚC HÀNG ĐỢI ===")
        self._log("Nếu cần chạy lại, xử lý dòng lỗi rồi nhấn RUN.")

if __name__ == "__main__":
    root = tk.Tk()
    try:
        style = ttk.Style()
        style.theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()
