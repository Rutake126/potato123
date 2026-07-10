import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import img2pdf


class JfifToPdfApp:
    def __init__(self, root):
        self.root = root
        self.root.title("JFIF 转 PDF")
        self.root.geometry("720x460")
        self.files = []
        self.save_path = None
        self.drag_index = None

        self._build_ui()

    def _build_ui(self):
        top_frame = tk.Frame(self.root, padx=12, pady=12)
        top_frame.pack(fill=tk.X)

        tk.Button(top_frame, text="选择图片", command=self.choose_files).pack(side=tk.LEFT)
        tk.Button(top_frame, text="清空列表", command=self.clear_files).pack(side=tk.LEFT, padx=(8, 0))

        list_frame = tk.Frame(self.root, padx=12)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.listbox = tk.Listbox(list_frame, selectmode=tk.SINGLE)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(list_frame, command=self.listbox.yview)
        scrollbar.pack(side=tk.LEFT, fill=tk.Y)
        self.listbox.config(yscrollcommand=scrollbar.set)

        self.listbox.bind("<ButtonPress-1>", self.start_drag)
        self.listbox.bind("<B1-Motion>", self.drag_item)
        self.listbox.bind("<ButtonRelease-1>", self.end_drag)
        self.listbox.bind("<Button-3>", self.show_context_menu)

        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="删除", command=self.remove_selected)

        save_frame = tk.Frame(self.root, padx=12, pady=12)
        save_frame.pack(fill=tk.X)

        tk.Button(save_frame, text="选择保存地址", command=self.choose_save_path).pack(side=tk.LEFT)

        self.save_label = tk.Label(
            save_frame,
            text="请选择 PDF 保存位置和文件名",
            anchor="w",
        )
        self.save_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))

        bottom_frame = tk.Frame(self.root, padx=12)
        bottom_frame.pack(fill=tk.X, pady=(0, 12))

        tk.Button(
            bottom_frame,
            text="开始转换",
            command=self.convert_to_pdf,
            height=2,
        ).pack(fill=tk.X)

    def choose_files(self):
        selected = filedialog.askopenfilenames(
            title="选择要转换的图片",
            filetypes=[
                ("图片文件", "*.jfif *.jpg *.jpeg"),
                ("JFIF 文件", "*.jfif"),
                ("JPEG 文件", "*.jpg *.jpeg"),
                ("所有文件", "*.*"),
            ],
        )

        if not selected:
            return

        for file_path in selected:
            path = Path(file_path)
            if path not in self.files:
                self.files.append(path)

        self.refresh_listbox()

    def choose_save_path(self):
        selected = filedialog.asksaveasfilename(
            title="选择 PDF 保存地址",
            defaultextension=".pdf",
            initialfile="转换结果.pdf",
            filetypes=[("PDF 文件", "*.pdf")],
        )

        if selected:
            self.save_path = Path(selected)
            if self.save_path.suffix.lower() != ".pdf":
                self.save_path = self.save_path.with_suffix(".pdf")
            self.save_label.config(text=f"保存到：{self.save_path}")

    def clear_files(self):
        self.files.clear()
        self.refresh_listbox()

    def remove_selected(self):
        index = self._selected_index()
        if index is None:
            return

        self.files.pop(index)
        self.refresh_listbox()

        if self.files:
            self.listbox.selection_set(min(index, len(self.files) - 1))

    def start_drag(self, event):
        index = self.listbox.nearest(event.y)
        if index < 0 or index >= len(self.files):
            return

        self.drag_index = index
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(index)

    def drag_item(self, event):
        if self.drag_index is None:
            return

        target_index = self.listbox.nearest(event.y)
        if target_index < 0 or target_index >= len(self.files):
            return

        if target_index == self.drag_index:
            return

        dragged_file = self.files.pop(self.drag_index)
        self.files.insert(target_index, dragged_file)
        self.drag_index = target_index

        self.refresh_listbox()
        self.listbox.selection_set(target_index)
        self.listbox.activate(target_index)

    def end_drag(self, event):
        self.drag_index = None

    def show_context_menu(self, event):
        index = self.listbox.nearest(event.y)
        if index < 0 or index >= len(self.files):
            return

        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(index)
        self.listbox.activate(index)
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def convert_to_pdf(self):
        if not self.files:
            messagebox.showwarning("提示", "请先选择至少一个 JFIF/JPEG 文件。")
            return

        if self.save_path is None:
            messagebox.showwarning("提示", "请先选择 PDF 保存位置，并输入文件名。")
            return

        output_path = self.save_path

        try:
            with open(output_path, "wb") as f:
                f.write(img2pdf.convert([str(path) for path in self.files]))
        except Exception as exc:
            messagebox.showerror("转换失败", f"生成 PDF 时出错：\n{exc}")
            return

        messagebox.showinfo("转换完成", f"PDF 已保存到：\n{output_path}")

    def refresh_listbox(self):
        self.listbox.delete(0, tk.END)
        for index, path in enumerate(self.files, start=1):
            self.listbox.insert(tk.END, f"{index}. {path}")

    def _selected_index(self):
        selection = self.listbox.curselection()
        if not selection:
            return None
        return selection[0]


if __name__ == "__main__":
    root = tk.Tk()
    app = JfifToPdfApp(root)
    root.mainloop()
