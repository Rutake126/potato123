import os
import requests
from PIL import Image
import xml.etree.ElementTree as ET
from datetime import datetime


timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
download_path = os.path.join('E:\\2025', f'download_{timestamp}')
os.makedirs(download_path, exist_ok=True)


# 下载和解析 XML
dzi = "https://opac.lib.takushoku-u.ac.jp/kyugaichi/htmls/resources/2013_013_001/root.xml"
response = requests.get(dzi)
xml_content = response.text

# 打印 XML 内容进行调试
print("XML 内容：")
print(xml_content)

root = ET.fromstring(xml_content)

# 获取 <image> 节点并提取信息 ，没有的可以换成resource
image_node = root.find('.//image')
if image_node is None:
    image_node = root.find('.//resource')

if image_node is not None:
    print("找到节点：", image_node.tag)
else:
    print("未找到节点")

if image_node is not None:
    wi = int(image_node.attrib['width'])
    hi = int(image_node.attrib['height'])
    tsize = int(image_node.attrib['tilewidth'])
else:
    raise ValueError("XML 文件中未找到 <image> 节点")

# 输出获取的参数
print(f"Width: {wi}, Height: {hi}, Tile Width: {tsize}")

# 计算列数和行数
cols = (wi // tsize) + 1
rows = (hi // tsize) + 1

# 下载图像瓦片并拼接
if not os.path.exists(download_path):
    os.makedirs(download_path)

for i in range(rows):
    string = []
    for j in range(cols):
        nh = tsize if i < rows - 1 else hi % tsize or tsize  # 确保至少有一个瓦片
        nw = tsize if j < cols - 1 else wi % tsize or tsize

        num1 = f"{j * tsize:05d}"
        num2 = f"{i * tsize:05d}"
        num3 = f"{nw:05d}"
        num4 = f"{nh:05d}"
        image_name = f"{num1}{num2}{num3}{num4}.jpg"
        img_path = os.path.join(download_path, f"{j}_{i}.jpg")
        file_url = f"{dzi.replace('root.xml', '0/')}{image_name}"

        print(f"Downloading {file_url}")
        img_response = requests.get(file_url)
        if img_response.status_code == 200:
            with open(img_path, "wb") as f:
                f.write(img_response.content)
            string.append(img_path)
        else:
            print(f"Failed to download {file_url}. Status code: {img_response.status_code}")

    # 拼接当前行的图像
    if string:
        row_image = Image.open(string[0])
        for img_path in string[1:]:
            next_image = Image.open(img_path)
            new_width = row_image.width + next_image.width
            new_image = Image.new('RGB', (new_width, row_image.height))
            new_image.paste(row_image, (0, 0))
            new_image.paste(next_image, (row_image.width, 0))
            row_image = new_image
        row_image.save(os.path.join(download_path, f"row{i}.jpg"))

# 最后合并所有行的图像
final_images = [Image.open(os.path.join(download_path, f"row{i}.jpg")) for i in range(rows)]
full_image = Image.new('RGB', (wi, hi))
y_offset = 0
for img in final_images:
    full_image.paste(img, (0, y_offset))
    y_offset += img.height

full_image.save(os.path.join(download_path, "full.jpg"))
print(f"全图已保存为 {os.path.join(download_path, 'full.jpg')}")
