import os
import time
import random
from playwright.sync_api import sync_playwright
from tqdm import tqdm  # 用于显示下载进度

#用于补充下载中遇到的图片缺失的问题
def run(playwright):
    # 创建保存图片的文件夹
    folder_name = "downloaded_images"
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)

    # 启动浏览器
    browser = playwright.chromium.launch(headless=True)

    # 创建一个新的浏览器上下文，并设置 User-Agent
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    )

    # 创建一个新页面
    page = context.new_page()

    # 下载的 URL 模板
    url_template = "https://ids.lib.harvard.edu/ids/iiif/{}/full/full/0/default.jpg"

    # 缺失图片的编号列表
    missing_images = ['48435392', '48435461', '48435522', '48435635', '48435696', '48435874', '48436198', '48436199']

    try:
        # tqdm 显示下载进度
        for image_id in tqdm(missing_images, desc="Downloading missing images"):
            # 构造图片的 URL
            image_url = url_template.format(image_id)

            try:
                # 访问图片 URL，增加超时时间，并使用 domcontentloaded 状态
                response = page.goto(image_url, wait_until="domcontentloaded", timeout=60000)

                # 获取图片的字节数据
                image_bytes = response.body()

                # 保存图片到文件夹
                image_path = os.path.join(folder_name, f"image_{image_id}.jpg")
                with open(image_path, "wb") as f:
                    f.write(image_bytes)

                print(f"Image {image_id} downloaded successfully.")

            except Exception as e:
                print(f"Error downloading image {image_id}: {e}")

            # 随机延迟，模拟用户行为，防止触发反爬
            time.sleep(random.uniform(1, 3))  # 1 到 3 秒的随机延迟

    except Exception as e:
        print(f"An error occurred: {e}")

    finally:
        # 关闭浏览器
        browser.close()


with sync_playwright() as playwright:
    run(playwright)


