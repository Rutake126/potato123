import requests
from PIL import Image
from fpdf import FPDF
import os
import time

# Base URL template with a placeholder for the page number
base_url_template = "https://rmda.kulib.kyoto-u.ac.jp/iiif/3/RB00023187%2FRB00023187_{page_num:05}_0.ptif/full/3017,/0/default.jpg"

# Number of pages
total_pages = 19

# List to store downloaded image filenames
image_files = []

# Enhanced headers to better mimic a real browser
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Referer': 'https://rmda.kulib.kyoto-u.ac.jp/',
    'DNT': '1',
}

# Create a session to persist cookies and headers across requests
session = requests.Session()
session.headers.update(headers)

# Step 1: 下载所有图片
for page in range(1, total_pages + 1):
    page_num_str = f"{page:05}"  # Format the page number as a zero-padded 5-digit string
    img_url = base_url_template.format(page_num=page_num_str)
    try:
        response = session.get(img_url, proxies={"http": None, "https": None})

        if response.status_code == 200:  # 检查响应状态
            img_filename = f"image_{page:03}.jpg"
            with open(img_filename, 'wb') as handler:
                handler.write(response.content)
                image_files.append(img_filename)
                print(f"Page {page} downloaded successfully.")
        elif response.status_code == 403:
            print(f"Failed to download page {page}: HTTP 403 - Access Forbidden")
            break
        else:
            print(f"Failed to download page {page}: HTTP {response.status_code}")
            break

        # 增加请求间隔，避免被反爬虫机制识别
        time.sleep(2)  # 间隔2秒
    except requests.exceptions.RequestException as e:
        print(f"Error downloading page {page}: {e}")
        break

# Step 2: 将图片合并为一个PDF
if image_files:
    pdf = FPDF()
    for image_file in image_files:
        try:
            with Image.open(image_file) as image:
                pdf.add_page()
                pdf.image(image_file, 0, 0, 210, 297)  # 以A4大小插入图片
        except (IOError, UnidentifiedImageError) as e:
            print(f"Error processing file {image_file}: {e}")
            continue

    output_pdf = "output.pdf"
    pdf.output(output_pdf)

    # Step 3: 清理下载的图片文件
    for image_file in image_files:
        os.remove(image_file)

    print(f"PDF 文件已生成: {output_pdf}")
else:
    print("没有成功下载任何图片，未生成 PDF 文件。")
