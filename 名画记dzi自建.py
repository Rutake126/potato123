import os
import math
import requests
from PIL import Image
import xml.etree.ElementTree as ET
from DrissionPage import ChromiumPage, ChromiumOptions


def get_dzi_info(url):
    """获取页面中的 DZI 信息"""
    print(f"正在访问：{url}")

    options = ChromiumOptions()
    options.set_argument('--headless')
    options.set_argument('--disable-gpu')

    page = ChromiumPage()
    page.get(url)

    script = "return viewer.source.Image;"
    data = page.run_js(script)

    page.close()
    return data if data else None


def generate_dzi_file(dzi_data, filename='image.dzi'):
    """根据 DZI 信息生成 DZI 文件"""
    if not isinstance(dzi_data, dict):
        print("获取的DZI信息不是字典类型，无法生成DZI文件。")
        return

    xml_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<Image TileSize="{dzi_data.get('TileSize', 254)}" Overlap="{dzi_data.get('Overlap', 1)}" 
       Format="{dzi_data.get('Format', 'png')}" 
       xmlns="http://schemas.microsoft.com/deepzoom/2009" 
       Url="{dzi_data.get('Url',
                          'https://minghuaji-1259446244.cos.ap-beijing.myqcloud.com/bundle/0b41b3ed670e4774b68e04cbf4dc0aeb/')}"> 
    <Size Width="{dzi_data.get('Size', {}).get('Width', 9728)}" Height="{dzi_data.get('Size', {}).get('Height', 18151)}"
    /> </Image> '''

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(xml_content)

    print(f'DZI 文件已生成：{filename}')


def parse_dzi(dzi_file):
    """解析 DZI 文件，获取瓦片尺寸和图像尺寸"""
    tree = ET.parse(dzi_file)
    root = tree.getroot()
    namespace = {'dz': 'http://schemas.microsoft.com/deepzoom/2009'}
    size_element = root.find('dz:Size', namespace)

    # 提取瓦片尺寸和图像宽高
    tile_size = int(root.attrib.get('TileSize', 256))
    width = round(float(size_element.attrib['Width']))  # 读取为浮点数并四舍五入
    height = round(float(size_element.attrib['Height']))  # 读取为浮点数并四舍五入

    return tile_size, width, height


def generate_tile_url(base_url, level, col, row, format):
    """生成瓦片的下载 URL"""
    return f"{base_url}{level}/{col}_{row}.{format}"


def download_tile(url, output_dir, failed_urls):
    """下载单个瓦片，若不存在则跳过"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/78.0.3904.97 Safari/537.36",
        "Referer": "https://www.dpm.org.cn"
    }

    if url in failed_urls:
        print(f"跳过已失败的瓦片：{url}")
        return False

    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 404:
            print(f"瓦片不存在，跳过：{url}")
            failed_urls.add(url)
            return False
        response.raise_for_status()

        tile_name = url.split("/")[-1]
        tile_path = os.path.join(output_dir, tile_name)
        with open(tile_path, 'wb') as f:
            f.write(response.content)
        print(f"下载成功：{tile_name}")
        return True

    except requests.exceptions.RequestException as e:
        print(f"下载失败：{url} - 错误：{e}")
        failed_urls.add(url)
        return False


def load_tile(x, y, output_dir):
    """加载单个瓦片"""
    tile_path = os.path.join(output_dir, f"{x}_{y}.png")
    try:
        return Image.open(tile_path)
    except FileNotFoundError:
        print(f"瓦片文件不存在：{tile_path}")
        return None


def stitch_tiles(output_dir, tile_size, num_cols, num_rows, final_width, final_height):
    """拼接所有瓦片"""
    stitched_image = Image.new('RGB', (final_width, final_height))

    for x in range(num_cols):
        for y in range(num_rows):
            tile = load_tile(x, y, output_dir)
            if tile:
                x_position = x * tile_size
                y_position = y * tile_size
                stitched_image.paste(tile, (x_position, y_position))

    stitched_image.save('stitched_image.png')
    print("图像拼接完成，保存为 stitched_image.png")


def main():
    url = 'https://minghuaji.dpm.org.cn/paint/appreciate?id=d7b091dfc44a403d88da9f521b601d9f'
    dzi_data = get_dzi_info(url)

    if dzi_data:
        print("DZI 信息获取成功：", dzi_data)
        generate_dzi_file(dzi_data)

        dzi_file = 'image.dzi'
        base_url = "https://minghuaji-1259446244.cos.ap-beijing.myqcloud.com/bundle/0b41b3ed670e4774b68e04cbf4dc0aeb/"
        output_dir = "tiles"
        os.makedirs(output_dir, exist_ok=True)

        tile_size, width, height = parse_dzi(dzi_file)
        failed_urls_file = "failed_urls.txt"
        failed_urls = set()
        if os.path.exists(failed_urls_file):
            with open(failed_urls_file, 'r', encoding='utf-8') as f:
                failed_urls = set([line.strip() for line in f.readlines()])

        level = 15
        cols = math.ceil(width / tile_size)
        rows = math.ceil(height / tile_size)

        print(f"开始下载缩放级别 {level} 的瓦片...")
        for col in range(cols):
            for row in range(rows):
                url = generate_tile_url(base_url, level, col, row, "png")
                download_tile(url, output_dir, failed_urls)

        with open(failed_urls_file, 'w', encoding='utf-8') as f:
            for url in failed_urls:
                f.write(url + "\n")

        stitch_tiles(output_dir, tile_size, cols, rows, width, height)
    else:
        print("未获取到有效的 DZI 信息，无法生成文件。请检查链接的合法性或网络连接。")


if __name__ == "__main__":
    main()
