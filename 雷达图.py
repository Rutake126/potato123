import os
import requests
from urllib.parse import urlparse, parse_qs

def download_file(url, proxy, folder):
    try:
        # 使用代理下载文件
        response = requests.get(url, proxies=proxy, stream=True)
        response.raise_for_status()  # 检查请求是否成功

        # 解析文件名
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        seq = query_params.get('seq', ['1'])[0]  # 获取 seq 参数
        filename = f"image_seq_{seq}.tiff"  # 使用 seq 生成文件名

        # 保存文件
        file_path = os.path.join(folder, filename)
        with open(file_path, 'wb') as file:
            for chunk in response.iter_content(chunk_size=8192):
                file.write(chunk)

        print(f"{filename} 下载完成！")
    except Exception as e:
        print(f"{url} 下载失败: {e}")
        return False  # 返回失败状态
    return True  # 返回成功状态

if __name__ == "__main__":
    # 设置代理
    proxy = {
        "http": "http://127.0.0.1:7898",  # 根据你的代理设置修改
        "https": "http://127.0.0.1:7898"
    }

    # 创建下载文件夹
    folder = "downloaded_images"
    os.makedirs(folder, exist_ok=True)

    # 用户选择下载方式
    choice = input("选择下载方式：1. 下载全部  2. 自定义页数（用逗号分隔，例如 1,2,3）: ")

    failed_downloads = []  # 用于记录下载失败的链接

    if choice == '1':
        # 循环下载所有页面
        for seq in range(1, 287):
            url = f"https://babel.hathitrust.org/cgi/imgsrv/image?id=gri.ark%3A%2F13960%2Ft53g2nr9r&attachment=1&tracker=D1&format=image%2Ftiff&size=ppi%3A300&seq={seq}"
            if not download_file(url, proxy, folder):
                failed_downloads.append(url)

    elif choice == '2':
        # 用户输入自定义页数
        pages = input("请输入要下载的页数（用逗号分隔）: ")
        page_list = [p.strip() for p in pages.split(',')]
        for seq in page_list:
            try:
                seq_num = int(seq)  # 转换为整数
                url = f"https://babel.hathitrust.org/cgi/imgsrv/image?id=gri.ark%3A%2F13960%2Ft53g2nr9r&attachment=1&tracker=D1&format=image%2Ftiff&size=ppi%3A300&seq={seq_num}"
                download_file(url, proxy, folder)
            except ValueError:
                print(f"无效的页码: {seq}")

    else:
        print("无效的选择，请输入 1 或 2。")

    # 打印下载失败记录
    if choice == '1' and failed_downloads:
        print("\n下载失败的链接:")
        for failed_url in failed_downloads:
            print(failed_url)
