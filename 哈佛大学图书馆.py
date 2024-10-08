import os
from datetime import datetime
from tqdm import tqdm
import concurrent.futures
from playwright.sync_api import sync_playwright
#1.2版本，读取txt的数字id，更方便下载

# 定义图片下载函数
def download_image(image_id, image_number, url_template, folder_name):
    with sync_playwright() as playwright:
        try:
            # 启动浏览器并创建上下文
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
            )
            page = context.new_page()

            # 去除换行符和空白字符
            image_id = image_id.strip()
            image_url = url_template.format(image_id)
            response = page.goto(image_url, wait_until="domcontentloaded", timeout=120000)  # 增加超时时间
            image_bytes = response.body()

            # 确保文件名不包含非法字符，使用自定义的序号命名文件
            image_path = os.path.join(folder_name, f"{image_number}.jpg")
            with open(image_path, "wb") as f:
                f.write(image_bytes)

            print(f"Image {image_id} downloaded successfully as {image_number}.jpg.")
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


# 从 dis.txt 中读取 ID 列表
def read_ids_from_file(filename="ids.txt"):
    try:
        with open(filename, "r") as f:
            # 使用 .strip() 去除每行末尾的换行符和多余的空白字符
            ids = [line.strip() for line in f.readlines()]
        return ids
    except FileNotFoundError:
        print(f"文件 {filename} 不存在。请确保 ids.txt 文件存在并包含所需 ID。")
        return []


# 主函数
def run():
    # 配置 URL 模板
    url_template = "https://ids.lib.harvard.edu/ids/iiif/{}/full/full/0/default.jpg"

    # 从文件中读取 ID 列表
    ids = read_ids_from_file()

    # 限制下载的图片数量为 246
    ids = ids[:246]

    if not ids:
        print("没有可用的 ID 来下载图片。")
        return

    # 创建新文件夹用于存放图片
    folder_name = create_new_folder()

    print(f"Starting download of {len(ids)} images.")

    # 使用多进程下载图片
    with concurrent.futures.ProcessPoolExecutor(max_workers=4) as executor:
        list(tqdm(
            executor.map(download_image, ids, range(1, len(ids) + 1), [url_template]*len(ids), [folder_name]*len(ids)),
            total=len(ids),
            desc="Downloading images"
        ))


if __name__ == "__main__":
    run()
