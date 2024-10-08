from playwright.sync_api import sync_playwright
import re


def extract_ids_from_manifest(manifest_url):
    ids = []

    with sync_playwright() as p:
        # 使用 Playwright 的浏览器上下文来访问 URL 并解析 JSON
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(manifest_url)

        # 解析并获取 JSON 内容
        manifest_content = page.evaluate("() => document.body.innerText")
        browser.close()

        # 解析 JSON 内容并提取需要的部分
        data = eval(manifest_content)  # 转换为 Python 字典

        # 迭代所有的 "sequences" -> "canvases"
        canvases = data['sequences'][0]['canvases']

        for canvas in canvases:
            # 检查是否包含目标 "label"
            label = canvas.get('label', '')
            if label.startswith("(seq."):
                # 获取 `thumbnail` URL
                thumbnail_url = canvas['thumbnail']['@id']

                # 使用正则表达式提取 `id`（例如：53240111）
                match = re.search(r'iiif/(\d+)/full', thumbnail_url)
                if match:
                    ids.append(match.group(1))

    return ids


# 将 ID 写入文本文件的函数
def save_ids_to_txt(ids, filename="ids.txt"):
    with open(filename, 'w') as f:
        for _id in ids:
            f.write(_id + "\n")
    print(f"已将 {len(ids)} 个 ID 写入 {filename} 文件中。")


# 测试解析代码
manifest_url = "https://iiif.lib.harvard.edu/manifests/drs:53239452"
extracted_ids = extract_ids_from_manifest(manifest_url)

# 将提取到的 ID 写入 txt 文件
save_ids_to_txt(extracted_ids)
