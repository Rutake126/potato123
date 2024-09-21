#在面临大量文件且它们的命名是有规律的，可以通过该脚本查找出哪些文件没有下载
import os

# 文件夹路径
folder_path = "E:\\2025\\downloaded_images"  # 替换为你的文件夹路径

# 起始页和总页数 （根据实际情况更改）
start_num = 48435315
total_pages = 885 

# 生成所有应有的文件名
expected_files = [f"image_{i}.jpg" for i in range(start_num, start_num + total_pages)]

# 获取文件夹中实际存在的文件名
actual_files = os.listdir(folder_path)

# 找出缺失的文件
missing_files = [file for file in expected_files if file not in actual_files]

# 打印缺失的文件
if missing_files:
    print(f"Missing files: {missing_files}")
else:
    print("No files are missing.")
#嘿嘿，睡觉了
