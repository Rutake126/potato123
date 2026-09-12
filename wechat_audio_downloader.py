# -*- coding: utf-8 -*-
"""
微信公众号教学音频批量下载器 (GUI版)
保存位置: E:\2025\wechat_audio_downloader.py
"""

import os
import re
import sys
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter.scrolledtext import ScrolledText
import requests
from bs4 import BeautifulSoup

# 请求头模拟浏览器
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

GRADE_KEYS = ["一年级", "二年级", "三年级", "四年级", "五年级", "六年级"]
GRADE_PATTERNS = {
    "一年级": ["一上", "一下", "一年级"],
    "二年级": ["二上", "二下", "二年级"],
    "三年级": ["三上", "三下", "三年级"],
    "四年级": ["四上", "四下", "四年级"],
    "五年级": ["五上", "五下", "五年级"],
    "六年级": ["六上", "六下", "六年级"],
}


def clean_filename(name):
    """移除 Windows 不允许的文件名字符"""
    return re.sub(r'[\\/*?:"<>|\r\n\t]', "_", name).strip()


class WeChatAudioDownloaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("微信公众号音频批量下载器 - 彭文峰会课文朗读")
        self.root.geometry("980x720")
        self.root.minsize(800, 600)

        # 状态变量
        self.stop_requested = False
        self.is_running = False
        self.parsed_data = {}  # {grade: [ {title, url, var}, ... ]}
        self.grade_vars = {}   # {grade: BooleanVar}

        self.setup_ui()

    def setup_ui(self):
        # 顶部配置卡片
        top_frame = ttk.LabelFrame(self.root, text=" 链接与存储配置 ", padding=10)
        top_frame.pack(fill="x", padx=10, pady=5)

        # 链接输入行
        ttk.Label(top_frame, text="公众号汇总链接:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.url_var = tk.StringVar(value="https://mp.weixin.qq.com/s/RVfGo09KSg3OJ0Z1olchfg")
        url_entry = ttk.Entry(top_frame, textvariable=self.url_var, width=70)
        url_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=5)

        self.btn_parse = ttk.Button(top_frame, text="🔍 解析文章与年级", command=self.start_parse)
        self.btn_parse.grid(row=0, column=2, padx=5, pady=5)

        # 保存路径行
        ttk.Label(top_frame, text="音频保存目录:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.save_dir_var = tk.StringVar(value=r"E:\2025\音频下载")
        save_entry = ttk.Entry(top_frame, textvariable=self.save_dir_var, width=70)
        save_entry.grid(row=1, column=1, sticky="ew", padx=5, pady=5)

        btn_browse = ttk.Button(top_frame, text="📁 浏览...", command=self.browse_folder)
        btn_browse.grid(row=1, column=2, padx=5, pady=5)

        top_frame.columnconfigure(1, weight=1)

        # 过滤与选项区域
        opt_frame = ttk.LabelFrame(self.root, text=" 识别与过滤设置 ", padding=10)
        opt_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(opt_frame, text="下载识别类型:").pack(side="left", padx=5)
        self.download_recite_var = tk.BooleanVar(value=True)
        self.download_music_var = tk.BooleanVar(value=True)

        chk_recite = ttk.Checkbutton(opt_frame, text="🎙️ 朗读录音", variable=self.download_recite_var)
        chk_recite.pack(side="left", padx=10)

        chk_music = ttk.Checkbutton(opt_frame, text="🎵 配乐伴奏", variable=self.download_music_var)
        chk_music.pack(side="left", padx=10)

        self.create_subfolder_var = tk.BooleanVar(value=True)
        chk_folder = ttk.Checkbutton(opt_frame, text="📂 自动按[年级/单元]创建分类子文件夹", variable=self.create_subfolder_var)
        chk_folder.pack(side="left", padx=20)

        btn_select_all = ttk.Button(opt_frame, text="全选全部", command=lambda: self.toggle_all(True))
        btn_select_all.pack(side="right", padx=5)

        btn_clear_all = ttk.Button(opt_frame, text="取消全选", command=lambda: self.toggle_all(False))
        btn_clear_all.pack(side="right", padx=5)

        # 主体列表区域（按年级分段与单元多选列表）
        list_frame = ttk.LabelFrame(self.root, text=" 年级与单元链接选择 (勾选年级即可全选该年级所有链接，也可单独勾选) ", padding=5)
        list_frame.pack(fill="both", expand=True, padx=10, pady=5)

        # 带有 Canvas + Scrollbar 的滚动列表容器
        self.canvas = tk.Canvas(list_frame, borderwidth=0, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.canvas.yview)
        self.scroll_content = ttk.Frame(self.canvas)

        self.scroll_content.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas_window = self.canvas.create_window((0, 0), window=self.scroll_content, anchor="nw")
        self.canvas.bind('<Configure>', lambda event: self.canvas.itemconfig(self.canvas_window, width=event.width))
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        # 鼠标滚轮支持
        self.canvas.bind_all("<MouseWheel>", lambda event: self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units"))

        self.empty_label = ttk.Label(self.scroll_content, text="请点击上方 [🔍 解析文章与年级] 按钮加载内容", foreground="gray")
        self.empty_label.pack(pady=40, padx=20)

        # 底部操作与日志区
        bottom_frame = ttk.Frame(self.root, padding=5)
        bottom_frame.pack(fill="both", padx=10, pady=5)

        btn_box = ttk.Frame(bottom_frame)
        btn_box.pack(fill="x", pady=2)

        self.btn_start = ttk.Button(btn_box, text="🚀 开始批量下载选定音频", command=self.start_download)
        self.btn_start.pack(side="left", padx=5)

        self.btn_stop = ttk.Button(btn_box, text="⏹️ 停止下载", command=self.stop_download, state="disabled")
        self.btn_stop.pack(side="left", padx=5)

        self.progress_label = ttk.Label(btn_box, text="准备就绪")
        self.progress_label.pack(side="left", padx=15)

        self.progress_bar = ttk.Progressbar(btn_box, orient="horizontal", mode="determinate")
        self.progress_bar.pack(side="right", fill="x", expand=True, padx=5)

        # 实时日志
        self.log_text = ScrolledText(bottom_frame, height=8, wrap="word", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True, pady=5)
        self.log("欢迎使用微信音频批量下载器！配置好链接后点击【解析文章与年级】开始。")

    def log(self, message):
        """输出日志"""
        def _append():
            self.log_text.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {message}\n")
            self.log_text.see(tk.END)
        self.root.after(0, _append)

    def browse_folder(self):
        """选择存储目录"""
        selected = filedialog.askdirectory(initialdir=self.save_dir_var.get())
        if selected:
            self.save_dir_var.set(selected)

    def start_parse(self):
        """异步开始解析"""
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("提示", "请输入微信公众号链接！")
            return

        self.btn_parse.config(state="disabled")
        self.log("正在访问汇总文章并解析各个年级链接，请稍候...")
        threading.Thread(target=self._parse_worker, args=(url,), daemon=True).start()

    def _parse_worker(self, url):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=12)
            resp.encoding = "utf-8"
            soup = BeautifulSoup(resp.text, "html.parser")
            content = soup.find(id="js_content") or soup

            links = content.find_all("a", href=True)
            valid_items = []
            for a in links:
                text = a.get_text(strip=True)
                href = a["href"]
                if "mp.weixin.qq.com" in href and text:
                    valid_items.append({"title": text, "url": href})

            # 分段分类归入一年级到六年级
            categorized = {g: [] for g in GRADE_KEYS}
            categorized["其他/综合"] = []

            for item in valid_items:
                matched_grade = None
                t = item["title"]
                for g, pats in GRADE_PATTERNS.items():
                    if any(p in t for p in pats):
                        matched_grade = g
                        break
                if matched_grade:
                    categorized[matched_grade].append(item)
                else:
                    categorized["其他/综合"].append(item)

            self.root.after(0, self._render_categories, categorized)
            self.log(f"解析成功！共识别到 {len(valid_items)} 个文章链接。")
        except Exception as e:
            self.log(f"解析出错: {e}")
            messagebox.showerror("错误", f"解析失败:\n{e}")
        finally:
            self.root.after(0, lambda: self.btn_parse.config(state="normal"))

    def _render_categories(self, categorized):
        """将分年级的数据渲染成带有全选大复选框与单独单元复选框的界面"""
        # 清除原有子控件
        for widget in self.scroll_content.winfo_children():
            widget.destroy()

        self.parsed_data = {}
        self.grade_vars = {}

        has_data = False
        for grade_name in GRADE_KEYS + ["其他/综合"]:
            items = categorized.get(grade_name, [])
            if not items:
                continue
            has_data = True

            # 年级外层卡片
            g_frame = ttk.LabelFrame(self.scroll_content, text=f" {grade_name} (共 {len(items)} 个单元链接) ", padding=8)
            g_frame.pack(fill="x", expand=True, padx=5, pady=4)

            # 年级全选控制框
            g_var = tk.BooleanVar(value=False)
            self.grade_vars[grade_name] = g_var
            self.parsed_data[grade_name] = []

            chk_all_grade = ttk.Checkbutton(
                g_frame,
                text=f"【全选/取消 {grade_name} 所有链接】",
                variable=g_var,
                command=lambda g=grade_name: self._on_grade_toggle(g)
            )
            chk_all_grade.pack(anchor="w", pady=2)

            # 单元列表复选框
            unit_container = ttk.Frame(g_frame)
            unit_container.pack(fill="x", padx=15, pady=2)

            for item in items:
                u_var = tk.BooleanVar(value=False)
                item_data = {
                    "title": item["title"],
                    "url": item["url"],
                    "var": u_var,
                    "grade": grade_name
                }
                self.parsed_data[grade_name].append(item_data)

                chk_unit = ttk.Checkbutton(
                    unit_container,
                    text=item["title"],
                    variable=u_var,
                    command=lambda g=grade_name: self._check_grade_all_state(g)
                )
                chk_unit.pack(anchor="w", pady=1)

        if not has_data:
            lbl = ttk.Label(self.scroll_content, text="未能匹配到符合年级的链接，请检查文章链接是否正确。")
            lbl.pack(pady=20)

    def _on_grade_toggle(self, grade_name):
        """勾选或取消年级总复选框"""
        state = self.grade_vars[grade_name].get()
        for item in self.parsed_data.get(grade_name, []):
            item["var"].set(state)

    def _check_grade_all_state(self, grade_name):
        """单元单选时，反向更新年级大复选框的状态"""
        items = self.parsed_data.get(grade_name, [])
        if not items:
            return
        all_checked = all(it["var"].get() for it in items)
        self.grade_vars[grade_name].set(all_checked)

    def toggle_all(self, state):
        """全选/清空所有年级和单元"""
        for g_var in self.grade_vars.values():
            g_var.set(state)
        for items in self.parsed_data.values():
            for it in items:
                it["var"].set(state)

    def get_selected_units(self):
        """获取所有被勾选的单元链接"""
        selected = []
        for grade, items in self.parsed_data.items():
            for it in items:
                if it["var"].get():
                    selected.append(it)
        return selected

    def start_download(self):
        """启动下载任务"""
        selected_units = self.get_selected_units()
        if not selected_units:
            messagebox.showwarning("提示", "请先在列表中勾选想要下载的年级或单元！")
            return

        want_recite = self.download_recite_var.get()
        want_music = self.download_music_var.get()
        if not want_recite and not want_music:
            messagebox.showwarning("提示", "请至少勾选一种下载识别类型（朗读录音 或 配乐伴奏）！")
            return

        save_root = self.save_dir_var.get().strip()
        if not save_root:
            messagebox.showwarning("提示", "请指定音频保存目录！")
            return

        os.makedirs(save_root, exist_ok=True)

        self.is_running = True
        self.stop_requested = False
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.btn_parse.config(state="disabled")

        threading.Thread(
            target=self._download_worker,
            args=(selected_units, save_root, want_recite, want_music),
            daemon=True
        ).start()

    def stop_download(self):
        """停止下载"""
        if self.is_running:
            self.stop_requested = True
            self.log("收到停止指令，正在安全中断...")

    def is_audio_matched(self, audio_name, want_recite, want_music):
        """依据识别标准判断音频是否满足下载要求"""
        name_lower = audio_name.lower()
        is_music = "配乐" in name_lower or "伴奏" in name_lower or "纯音乐" in name_lower
        is_recite = "朗读" in name_lower or "课文" in name_lower or "录音" in name_lower or not is_music

        if want_recite and want_music:
            return True
        if want_music and is_music:
            return True
        if want_recite and is_recite and not is_music:
            return True
        return False

    def _download_worker(self, selected_units, save_root, want_recite, want_music):
        total_units = len(selected_units)
        self.log(f"开始批量下载，共选中 {total_units} 个单元链接...")

        total_downloaded = 0
        total_failed = 0

        self.root.after(0, lambda: self.progress_bar.configure(maximum=total_units, value=0))

        for idx, unit in enumerate(selected_units, 1):
            if self.stop_requested:
                self.log("下载任务已被用户手动停止！")
                break

            unit_title = unit["title"]
            unit_url = unit["url"]
            grade_name = unit["grade"]

            self.root.after(0, lambda i=idx, t=total_units, u=unit_title: [
                self.progress_label.config(text=f"正在处理 ({i}/{t}): {u[:20]}..."),
                self.progress_bar.config(value=i)
            ])

            self.log(f"\n--- [{idx}/{total_units}] 正在打开单元: {unit_title} ---")

            try:
                sub_resp = requests.get(unit_url, headers=HEADERS, timeout=12)
                sub_resp.encoding = "utf-8"
                sub_soup = BeautifulSoup(sub_resp.text, "html.parser")

                # 提取子页面中的所有 mpvoice
                mpvoices = sub_soup.find_all("mpvoice")
                found_audios = []
                for v in mpvoices:
                    fid = v.get("voice_encode_fileid")
                    name = v.get("name") or "未命名音频"
                    if fid:
                        found_audios.append((name, fid))

                # 正则备用提取
                if not found_audios:
                    raw_ids = re.findall(r'voice_encode_fileid=["\']([^"\']+)["\']', sub_resp.text)
                    for raw_id in raw_ids:
                        found_audios.append((f"音频_{raw_id[:8]}", raw_id))

                if not found_audios:
                    self.log("  [!] 提示: 该单元页面内未检测到微信语音。")
                    continue

                # 确定保存子目录
                if self.create_subfolder_var.get():
                    target_folder = os.path.join(save_root, clean_filename(grade_name), clean_filename(unit_title))
                else:
                    target_folder = save_root
                os.makedirs(target_folder, exist_ok=True)

                # 逐个筛选下载
                for a_name, file_id in found_audios:
                    if self.stop_requested:
                        break

                    if not self.is_audio_matched(a_name, want_recite, want_music):
                        self.log(f"  [-] 跳过 (类型未勾选): {a_name}")
                        continue

                    # 格式化文件名
                    clean_name = clean_filename(a_name)
                    if not clean_name.endswith(".mp3"):
                        file_name = f"{clean_name}.mp3"
                    else:
                        file_name = clean_name

                    dest_path = os.path.join(target_folder, file_name)

                    # 已存在则跳过
                    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 1024:
                        self.log(f"  [√] 文件已存在，跳过: {file_name}")
                        total_downloaded += 1
                        continue

                    audio_link = f"https://res.wx.qq.com/voice/getvoice?mediaid={file_id}"
                    self.log(f"  [↓] 正在下载: {file_name}")

                    try:
                        down_resp = requests.get(audio_link, headers=HEADERS, stream=True, timeout=15)
                        if down_resp.status_code == 200:
                            with open(dest_path, "wb") as f:
                                for chunk in down_resp.iter_content(chunk_size=32 * 1024):
                                    if chunk:
                                        f.write(chunk)
                            self.log(f"  [√] 保存成功 -> {dest_path}")
                            total_downloaded += 1
                        else:
                            self.log(f"  [×] 下载失败 (HTTP {down_resp.status_code}): {file_name}")
                            total_failed += 1
                    except Exception as err:
                        self.log(f"  [×] 下载网络异常: {err}")
                        total_failed += 1

                    time.sleep(0.3)  # 避免过快请求

                time.sleep(0.5)

            except Exception as e:
                self.log(f"  [×] 打开单元链接失败: {e}")

        # 完成提示
        self.log(f"\n==========================================")
        self.log(f"下载任务结束！成功: {total_downloaded} 个，失败: {total_failed} 个")
        self.log(f"保存目录: {save_root}")
        self.log(f"==========================================")

        self.root.after(0, self._on_download_finished, total_downloaded, total_failed)

    def _on_download_finished(self, success, failed):
        self.is_running = False
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.btn_parse.config(state="normal")
        self.progress_label.config(text="下载完成")
        messagebox.showinfo("下载完成", f"下载任务已完成！\n成功下载/已存在: {success} 个\n失败: {failed} 个\n\n请前往保存目录查看。")


def main():
    root = tk.Tk()
    # Windows 高清 DPI 适配支持
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    app = WeChatAudioDownloaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
