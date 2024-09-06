import os

# 文件夹路径
folder_path = "E:\\2025\\hathitrust_images"  # 你的文件夹路径
total_files = 1184  # 总文件数

# 创建所有应有文件名的列表
expected_files = [f"image_{i:05}.jpg" for i in range(1, total_files + 1)]

# 获取文件夹中实际存在的文件名
actual_files = os.listdir(folder_path)

# 找出缺失的文件
missing_files = [file for file in expected_files if file not in actual_files]

# 打印缺失的文件
if missing_files:
    print(f"Missing files: {missing_files}")
else:
    print("No files are missing.")
