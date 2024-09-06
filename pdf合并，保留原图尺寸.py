import os
from PIL import Image, UnidentifiedImageError
from fpdf import FPDF
from tqdm import tqdm  # 导入 tqdm 用于进度条

# 假设图片文件存储在指定的文件夹中
folder_path = "E:\\2025\\hathitrust_images"  # 将此路径替换为实际的图片文件夹路径

# Step 1: 获取图片文件列表
image_files = [os.path.join(folder_path, f) for f in os.listdir(folder_path) if f.endswith(('.jpg', '.png', '.jpeg'))]

# Step 2: 将图片合并为一个PDF
if image_files:
    pdf = FPDF()
    for image_file in tqdm(image_files, desc="合并图片为 PDF", unit="文件"):  # 使用 tqdm 添加进度条
        try:
            with Image.open(image_file) as image:
                pdf.add_page()
                pdf.image(image_file, 0, 0, 210, 297)  # 以 A4 大小插入图片
        except (IOError, UnidentifiedImageError) as e:
            print(f"Error processing file {image_file}: {e}")
            continue

    output_pdf = "output.pdf"
    pdf.output(output_pdf)

    print(f"PDF 文件已生成: {output_pdf}")
else:
    print("没有成功下载任何图片，未生成 PDF 文件。")
