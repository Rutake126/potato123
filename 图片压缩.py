import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image
import os

#2026.7.5
class ImageCompressorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("图片压缩工具 - GUI版")
        self.root.geometry("700x500")
        self.root.resizable(True, True)

        self.input_files = []  # 选择的图片文件
        self.output_dir = ""  # 保存目录

        self.create_widgets()

    def create_widgets(self):
        # ==================== 标题 ====================
        title = ttk.Label(self.root, text="图片批量压缩工具", font=("微软雅黑", 16, "bold"))
        title.pack(pady=10)

        # ==================== 选择图片 ====================
        frame1 = ttk.LabelFrame(self.root, text="1. 选择图片", padding=10)
        frame1.pack(fill="x", padx=20, pady=8)

        ttk.Button(frame1, text="📁 选择图片（可多选）", command=self.select_files).pack(pady=5)

        self.file_listbox = tk.Listbox(frame1, height=6, width=80)
        self.file_listbox.pack(pady=5, fill="x")

        ttk.Button(frame1, text="清除列表", command=self.clear_files).pack()

        # ==================== 保存设置 ====================
        frame2 = ttk.LabelFrame(self.root, text="2. 保存设置", padding=10)
        frame2.pack(fill="x", padx=20, pady=8)

        # 保存路径
        path_frame = ttk.Frame(frame2)
        path_frame.pack(fill="x", pady=5)

        ttk.Label(path_frame, text="保存到：").pack(side="left")
        self.path_var = tk.StringVar()
        ttk.Entry(path_frame, textvariable=self.path_var, width=60).pack(side="left", padx=5, fill="x", expand=True)
        ttk.Button(path_frame, text="浏览...", command=self.select_output_dir).pack(side="left")

        # 命名规则
        name_frame = ttk.Frame(frame2)
        name_frame.pack(fill="x", pady=5)

        ttk.Label(name_frame, text="命名规则：").pack(side="left")
        self.name_var = tk.StringVar(value="compressed_{n}")
        ttk.Entry(name_frame, textvariable=self.name_var, width=30).pack(side="left", padx=5)
        ttk.Label(name_frame, text=".jpg （{n} 会自动替换为序号）").pack(side="left")

        # ==================== 压缩参数 ====================
        frame3 = ttk.LabelFrame(self.root, text="3. 压缩参数", padding=10)
        frame3.pack(fill="x", padx=20, pady=8)

        param_frame = ttk.Frame(frame3)
        param_frame.pack()

        ttk.Label(param_frame, text="目标大小 (MB):").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.target_size = tk.DoubleVar(value=1.0)
        ttk.Spinbox(param_frame, from_=0.1, to=10, increment=0.1, textvariable=self.target_size, width=10).grid(row=0,
                                                                                                                column=1,
                                                                                                                padx=5)

        ttk.Label(param_frame, text="起始质量:").grid(row=0, column=2, padx=5, pady=5, sticky="w")
        self.quality = tk.IntVar(value=85)
        ttk.Spinbox(param_frame, from_=10, to=95, increment=5, textvariable=self.quality, width=10).grid(row=0,
                                                                                                         column=3,
                                                                                                         padx=5)

        # ==================== 开始压缩 ====================
        compress_btn = ttk.Button(self.root, text="🚀 开始批量压缩", command=self.start_compression)
        compress_btn.pack(pady=20)

        # 状态栏
        self.status = tk.StringVar(value="就绪")
        status_bar = ttk.Label(self.root, textvariable=self.status, relief="sunken", anchor="w")
        status_bar.pack(side="bottom", fill="x", padx=10, pady=5)

    def select_files(self):
        files = filedialog.askopenfilenames(
            title="选择图片",
            filetypes=[("图片文件", "*.jpg *.jpeg *.png *.bmp *.webp")]
        )
        if files:
            self.input_files.extend(files)
            self.update_file_list()

    def update_file_list(self):
        self.file_listbox.delete(0, tk.END)
        for f in self.input_files:
            self.file_listbox.insert(tk.END, os.path.basename(f))

    def clear_files(self):
        self.input_files.clear()
        self.file_listbox.delete(0, tk.END)

    def select_output_dir(self):
        dir_path = filedialog.askdirectory(title="选择保存文件夹")
        if dir_path:
            self.output_dir = dir_path
            self.path_var.set(dir_path)

    def compress_single(self, input_path, output_path, target_mb):
        try:
            img = Image.open(input_path).convert("RGB")
            original_size = os.path.getsize(input_path) / (1024 * 1024)

            quality = self.quality.get()
            min_quality = 20

            while quality >= min_quality:
                img.save(output_path, "JPEG", quality=quality, optimize=True)
                current_size = os.path.getsize(output_path) / (1024 * 1024)

                if current_size <= target_mb:
                    return True, current_size
                quality -= 5

            # 如果质量压缩不够，缩小尺寸
            width, height = img.size
            scale = 0.95
            while scale > 0.4:
                new_img = img.resize((int(width * scale), int(height * scale)), Image.LANCZOS)
                new_img.save(output_path, "JPEG", quality=quality, optimize=True)
                current_size = os.path.getsize(output_path) / (1024 * 1024)
                if current_size <= target_mb:
                    return True, current_size
                scale -= 0.05

            return False, current_size

        except Exception as e:
            print(f"压缩失败 {input_path}: {e}")
            return False, 0

    def start_compression(self):
        if not self.input_files:
            messagebox.showwarning("警告", "请先选择图片！")
            return
        if not self.output_dir:
            messagebox.showwarning("警告", "请选择保存位置！")
            return

        target_mb = self.target_size.get()
        name_pattern = self.name_var.get()

        success_count = 0
        self.status.set("正在压缩...")

        for i, file_path in enumerate(self.input_files, 1):
            filename = f"{name_pattern.replace('{n}', str(i))}.jpg"
            output_path = os.path.join(self.output_dir, filename)

            # 避免文件名重复
            counter = 1
            while os.path.exists(output_path):
                filename = f"{name_pattern.replace('{n}', str(i))}_{counter}.jpg"
                output_path = os.path.join(self.output_dir, filename)
                counter += 1

            self.status.set(f"正在处理: {os.path.basename(file_path)}")
            self.root.update()

            success, final_size = self.compress_single(file_path, output_path, target_mb)
            if success:
                success_count += 1

        messagebox.showinfo("完成",
                            f"压缩完成！\n成功处理 {success_count}/{len(self.input_files)} 张图片\n\n保存位置：{self.output_dir}")
        self.status.set("压缩完成！")


# ====================== 运行程序 ======================
if __name__ == "__main__":
    root = tk.Tk()
    app = ImageCompressorApp(root)
    root.mainloop()
