#更新日志2025.12.24
#修复了原先脚本对于同一张图片发起四次请求的bug.
#把之前发布的错误版本更换成正确的版本。

from DrissionPage import ChromiumPage, ChromiumOptions
import time
import os

# --- 配置根据自己的需求进行更换 ---
PROXY_ADDR = '127.0.0.1:7897'
SAVE_DIR = r"E:\2025\downloads"
BOOK_ID = "uc1.32106019930681"
START_SEQ = 1
END_SEQ = 30
# 去掉 attachment=1，防止浏览器自动拦截下载
URL_TEMPLATE = "https://babel.hathitrust.org/cgi/imgsrv/imgsrv/image?id={book_id}&seq={seq}"

# --- 浏览器配置 ---
options = ChromiumOptions()
options.set_argument(f'--proxy-server=http://{PROXY_ADDR}')
options.headless(False)
# 设置下载路径（虽然我们用JS保存，但保留此项作为保险）
options.set_pref("download.default_directory", SAVE_DIR)
options.set_pref("download.prompt_for_download", False)

page = ChromiumPage(options)

# --- 确保目录存在 ---
os.makedirs(SAVE_DIR, exist_ok=True)

# 先访问一个空白页或 HathiTrust 主页，确保脚本在目标域下运行 JS
page.get("https://babel.hathitrust.org/")

# --- 下载逻辑 ---
for seq in range(START_SEQ, END_SEQ + 1):
    url = URL_TEMPLATE.format(book_id=BOOK_ID, seq=seq)
    filename = f"seq{seq}.png"
    print(f"⬇ 正在精准下载: {filename}")

    # 使用 JS 直接将图片转为 Blob 并触发单次保存
    # 这种方式不会引起浏览器页面的 get 行为，从而避免多次触发
    js_code = f"""
    fetch('{url}')
      .then(response => response.blob())
      .then(blob => {{
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        a.download = '{filename}';
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        a.remove();
      }})
      .catch(e => console.error('下载失败:', e));
    """

    page.run_js(js_code)

    # 间隔 3 秒，给 JS 异步执行和文件写入留出时间
    time.sleep(3)

print("✅ 所有精准下载任务已发送")
page.quit()
