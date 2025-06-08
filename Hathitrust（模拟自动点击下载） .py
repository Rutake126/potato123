import os
import asyncio
import random
from playwright.async_api import async_playwright
from datetime import datetime

# ========= 配置参数 =========
BOOK_ID = "uc1.$b668612"
TRACKER = "D3"
START_PAGE = 465
END_PAGE = 465
SAVE_FOLDER = f"downloads_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
USE_PROXY = True
PROXY_SERVER = "http://127.0.0.1:7890"  # 修改为你的代理地址
# ===========================

os.makedirs(SAVE_FOLDER, exist_ok=True)

async def run():
    async with async_playwright() as p:
        launch_args = {
            "headless": False
        }
        if USE_PROXY:
            launch_args["proxy"] = {"server": PROXY_SERVER}

        browser = await p.chromium.launch(**launch_args)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()

        for seq in range(START_PAGE, END_PAGE + 1):
            url = (
                f"https://babel.hathitrust.org/cgi/imgsrv/image?"
                f"id={BOOK_ID}&attachment=1&tracker={TRACKER}"
                f"&format=image%2Ftiff&size=ppi%3A300&seq={seq}"
            )
            print(f"准备下载第 {seq} 页: {url}")

            try:
                async with page.expect_download(timeout=10000) as download_info:
                    await page.evaluate(f'''
                        () => {{
                            const link = document.createElement('a');
                            link.href = "{url}";
                            link.download = "";
                            document.body.appendChild(link);
                            link.click();
                            document.body.removeChild(link);
                        }}
                    ''')
                download = await download_info.value
                file_path = os.path.join(SAVE_FOLDER, f"image_seq_{seq}.tiff")
                await download.save_as(file_path)
                print(f"✅ 已保存: {file_path}")
            except Exception as e:
                print(f"❌ 第 {seq} 页下载失败，已跳过: {e}")

            # 等待 2~4 秒
            delay = random.uniform(2, 4)
            print(f"🌙 等待 {delay:.2f} 秒后继续...")
            await asyncio.sleep(delay)

        await context.close()
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
