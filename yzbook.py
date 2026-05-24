import os
import sys
import time
import re
from io import BytesIO
from math import ceil
import requests
from PIL import Image
from selenium import webdriver


def download_yunzhan_pdf(url, output_filename="xx.pdf"):
    print(f"开始处理链接: {url}")

    # 1. 配置 Selenium (移除了性能日志监听，大幅降低内存占用防止崩溃)
    options = webdriver.ChromeOptions()
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--log-level=3")

    print("正在启动 Chrome 浏览器...")
    driver = webdriver.Chrome(options=options)

    final_page_links = []

    try:
        driver.get(url)
        print("等待页面加载（5秒）...")
        time.sleep(5)

        # ================= 核心改进方案 A：直接读取内存中的书籍配置 (最快最准) =================
        print("尝试从浏览器内存中直接读取全书页码顺序...")
        pages_config = driver.execute_script("""
            var candidates = [
                window.fliphtml5_pages, window.configForPages,
                (window.bookConfig && window.bookConfig.pages),
                (window.htmlConfig && window.htmlConfig.pages),
                (window.sliderConfig && window.sliderConfig.pages),
                (window.articleConfig && window.articleConfig.pages)
            ];
            for (var i=0; i<candidates.length; i++) {
                if (candidates[i] && Array.isArray(candidates[i]) && candidates[i].length > 0) {
                    return candidates[i];
                }
            }
            if (window.bookConfig) {
                for (var key in window.bookConfig) {
                    if (Array.isArray(window.bookConfig[key]) && window.bookConfig[key].length > 0 && window.bookConfig[key][0] && window.bookConfig[key][0].path) {
                        return window.bookConfig[key];
                    }
                }
            }
            return null;
        """)

        # 智能提取 base_url，去除尾部的 mobile/index.html 等
        clean_url = url.split('?')[0]
        base_url = re.sub(r'/mobile(/index\.html)?/?$', '', clean_url)
        base_url = re.sub(r'/index\.html$', '', base_url).rstrip('/')

        if pages_config and len(pages_config) > 0:
            print(f"🎉 成功读取到 {len(pages_config)} 页的配置！无需模拟翻页！")
            for p in pages_config:
                raw_path = p.get('path') or p.get('url') or p.get('image') or (
                    p.get('n') and p['n'][0] if isinstance(p.get('n'), list) else None)
                if raw_path:
                    clean_name = raw_path.split('?')[0].lstrip('/')
                    full_url = f"{base_url}/files/large/{clean_name}"
                    final_page_links.append(full_url)

        else:
            # ================= 备用方案 B：翻页 + DOM 映射 (精准修复你的原逻辑) =================
            print("内存配置未找到，切换回【翻页 + DOM 映射】模式...")
            try:
                num_pages = driver.execute_script("return originTotalPageCount;")
            except Exception:
                num_pages = driver.execute_script("return totalPageCount;")

            if not num_pages:
                print("错误：无法读取书籍页数。")
                return

            print(f"书籍总页数: {num_pages}")
            flips = ceil((num_pages - 1) / 2)

            page_links = []

            def get_dom_page_map():
                """扫描当前 DOM，建立 URL -> 真实页码 的准确映射关系"""
                return driver.execute_script("""
                    let map = {};
                    let imgs = document.querySelectorAll('img[src*="/files/large/"]');
                    for(let i=0; i<imgs.length; i++) {
                        let img = imgs[i];
                        let pageDiv = img.closest('div[id^="page"]');
                        if (pageDiv) {
                            let match = pageDiv.id.match(/page(\d+)/);
                            if (match) {
                                map[img.src.split('?')[0]] = parseInt(match[1]);
                            }
                        }
                    }
                    return map;
                """)

            dom_map = get_dom_page_map()
            initial_urls = list(dom_map.keys())
            # 根据 DOM 中的真实页码排序，而不是根据 URL 字母排序！
            initial_urls.sort(key=lambda u: dom_map.get(u, 0))
            page_links.extend(initial_urls)

            for i in range(flips):
                current_p1 = 1 + 2 * i
                current_p2 = 2 + 2 * i
                print(f"\r正在翻页并动态捕获: {current_p1} & {current_p2} / {num_pages} 页...", end="", flush=True)

                driver.execute_script("nextPageFun(\"mouse wheel flip\")")
                time.sleep(1.5)

                new_dom_map = get_dom_page_map()
                dom_map.update(new_dom_map)

                turn_urls = [u for u in new_dom_map.keys() if u not in page_links]
                turn_urls.sort(key=lambda u: dom_map.get(u, 0))
                page_links.extend(turn_urls)

            final_page_links = page_links
            print("\n页面捕获完成！")

    finally:
        driver.quit()

    # 去重并保持顺序
    seen = set()
    unique_links = []
    for link in final_page_links:
        if link not in seen:
            seen.add(link)
            unique_links.append(link)

    def extract_final_num(u):
        match = re.search(r'/(\d+)(?:\.\w+)$', u)
        return int(match.group(1)) if match else 0

    numeric_count = sum(1 for u in unique_links if re.search(r'/\d+\.\w+$', u))
    if numeric_count > len(unique_links) * 0.5:
        unique_links.sort(key=extract_final_num)

    print(f"最终整理出图片数: {len(unique_links)} 张")

    # 3. 下载图片并合成 PDF
    images = []
    print("开始顺序下载图片并转换为 PDF 格式...")
    for index, img_url in enumerate(unique_links):
        print(f"\r正在处理第 {index + 1} / {len(unique_links)} 页...", end="", flush=True)
        try:
            response = requests.get(img_url, timeout=15)
            if response.status_code == 200:
                img = Image.open(BytesIO(response.content)).convert("RGB")
                images.append(img)
            else:
                print(f"\n[警告] 第 {index + 1} 页下载失败，状态码: {response.status_code}")
        except Exception as e:
            print(f"\n[警告] 第 {index + 1} 页下载异常: {e}")

    if not images:
        print("\n没有成功下载到任何图片，无法生成 PDF。")
        return

    print(f"\n正在合成并保存为 PDF 文件: {output_filename} ...")
    images[0].save(output_filename, save_all=True, append_images=images[1:])
    print("已生成完毕！")


if __name__ == "__main__":
    TARGET_URL = "https://book.xx365.com/xltqx/cvxe/mobile/index.html"
    download_yunzhan_pdf(TARGET_URL, output_filename="顺序修正版.pdf")
