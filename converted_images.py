import os
from concurrent.futures import ThreadPoolExecutor
import pyvips  # Use pyvips for efficient image processing


def get_directory(prompt):
    """Prompt the user for a directory and ensure it exists."""
    while True:
        directory = input(f"{prompt}: ").strip()
        if os.path.isdir(directory):
            return directory
        print("Invalid directory. Please enter a valid path.")


# 让用户选择源文件夹
source_dir = get_directory("Enter the source directory")
# 在源文件夹下创建 converted_images 文件夹
target_dir = os.path.join(source_dir, "converted_images")
if not os.path.exists(target_dir):
    os.makedirs(target_dir)
    print(f"Created target directory: {target_dir}")


# 定义转换函数
def convert_jp2_to_jpg(jp2_file):
    try:
        # 拼接输入和输出文件路径
        jp2_path = os.path.join(source_dir, jp2_file)
        jpg_path = os.path.join(target_dir, f"{os.path.splitext(jp2_file)[0]}.jpg")

        # 使用 pyvips 读取 .jp2 文件
        image = pyvips.Image.new_from_file(jp2_path)

        # 转换并保存为 jpg
        image.write_to_file(jpg_path, Q=90)  # 设置质量为 90（可调整）
        print(f"Successfully converted: {jp2_file} -> {jpg_path}")
    except Exception as e:
        print(f"Error converting {jp2_file}: {e}")


# 获取所有 .jp2 文件
jp2_files = [f for f in os.listdir(source_dir) if f.lower().endswith('.jp2')]

# 使用多线程处理文件
with ThreadPoolExecutor() as executor:
    executor.map(convert_jp2_to_jpg, jp2_files)

print("All files processed!")
