#在面临大量文件且它们的命名是有规律的，可以通过该脚本查找出哪些文件没有下载
import os
folder_path = "file_path"  # 你的文件夹路径如E:\\2025\\hathitrust_images
total_files = # 总文件数

# 创建所有应有文件名的列表
expected_files = [f"image_{i:05}.jpg" for i in range(1, total_files + 1)] #根据文件名称进行修改

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
