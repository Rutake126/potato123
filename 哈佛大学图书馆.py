import os
import time
import random
from datetime import datetime
from tqdm import tqdm
import concurrent.futures
from playwright.sync_api import sync_playwright

#更新：使用 enumerate 生成顺序编号，从 1 开始递增到 total_pages，确保文件名是 image_1.jpg 到 image_217.jpg。
# 定义图片下载函数，增加 image_number 参数用于顺序命名文件
def download_image(image_id, image_number, url_template, folder_name):
    with sync_playwright() as playwright:
        try:
            # 启动浏览器并创建上下文
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
            )
            page = context.new_page()

            image_url = url_template.format(image_id)
            response = page.goto(image_url, wait_until="domcontentloaded", timeout=120000)  # 增加超时时间

            # 检查响应状态码
            if response.status == 200:
                image_bytes = response.body()
                # 使用顺序号命名文件，而非 image_id
                image_path = os.path.join(folder_name, f"image_{image_number}.jpg")
                with open(image_path, "wb") as f:
                    f.write(image_bytes)

                print(f"Image {image_id} (renamed to image_{image_number}.jpg) downloaded successfully.")
            else:
                print(f"Failed to download image {image_id}. Status code: {response.status}")
        except Exception as e:
            print(f"Error downloading image {image_id}: {e}")
        finally:
            # 关闭浏览器
            browser.close()


# 自动创建新文件夹（根据当前时间戳）
def create_new_folder(base_folder="downloaded_images"):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")  # 使用当前时间创建唯一文件夹名称
    new_folder = os.path.join(base_folder, f"download_{timestamp}")
    if not os.path.exists(new_folder):
        os.makedirs(new_folder)
    return new_folder


# 从文件中读取 ID
def read_ids_from_file(file_name):
    with open(file_name, "r") as f:
        return [line.strip() for line in f.readlines() if line.strip().isdigit()]


# 主函数
def run():
    # 配置 URL 模板
    url_template = "https://ids.lib.harvard.edu/ids/iiif/{}/full/full/0/default.jpg"

    # 读取 ID 列表
    ids = read_ids_from_file("extracted_data.txt")

    # 提示用户请求的总页数
    total_pages = len(ids)
    print(f"共请求 {total_pages} 页。")

    # 创建新文件夹用于存放图片
    folder_name = create_new_folder()

    # 使用多进程下载图片，并使用 enumerate 为每个图片编号
    with concurrent.futures.ProcessPoolExecutor(max_workers=4) as executor:
        list(tqdm(
            executor.map(download_image, ids, range(1, total_pages + 1), [url_template] * total_pages,
                         [folder_name] * total_pages),
            total=total_pages,
            desc="Downloading images"
        ))


if __name__ == "__main__":
    run()
