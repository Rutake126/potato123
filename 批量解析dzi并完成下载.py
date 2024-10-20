import os
import asyncio
import requests
import xml.etree.ElementTree as ET
from PIL import Image
from fpdf import FPDF
from PyPDF2 import PdfMerger
from playwright.async_api import async_playwright
import re

# DZI文件模板
dzi_template = '''<?xml version="1.0" encoding="UTF-8"?>
<Image TileSize="{TileSize}" Overlap="{Overlap}" Format="{Format}"
       xmlns="{xmlns}" Url="{Url}">
       <Size Width="{Width}" Height="{Height}"/>
</Image>'''


async def fetch_tile_sources_from_page(page_url, file_index, output_dir, tile_level=0):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        print(f"Loading {page_url}...")
        await page.goto(page_url)
        await page.wait_for_timeout(5000)

        scripts = await page.evaluate(""" 
            () => {
                return Array.from(document.querySelectorAll('script')).map(script => script.textContent);
            }
        """)

        tile_sources = {}
        for script_content in scripts:
            if "tileSources" in script_content:
                tile_sources_match = re.search(r'tileSources:\s*{\s*Image:\s*{([^}]*)}', script_content)
                if tile_sources_match:
                    tile_sources_str = tile_sources_match.group(1)
                    fields = re.findall(r'(\w+):\s*["\']?([^"\',\s]+)["\']?', tile_sources_str)

                    for key, value in fields:
                        tile_sources[key] = value

                    print("Extracted tileSources Data:")
                    for key, value in tile_sources.items():
                        print(f"{key}: {value}")

                    dzi_content = dzi_template.format(
                        TileSize=tile_sources.get("TileSize", "0"),
                        Overlap=tile_sources.get("Overlap", "0"),
                        Format=tile_sources.get("Format", "png"),
                        xmlns=tile_sources.get("xmlns", "https://schemas.microsoft.com/deepzoom/2009"),
                        Url=tile_sources.get("Url", "").rstrip(
                            '/') + f"/{tile_level}/" if tile_level > 0 else tile_sources.get("Url", ""),
                        Width=tile_sources.get("Width", "0"),
                        Height=tile_sources.get("Height", "0"),
                    )

                    dzi_filename = os.path.join(output_dir, f"dzi_{file_index}.dzi")
                    with open(dzi_filename, 'w', encoding='utf-8') as f:
                        f.write(dzi_content)
                    print(f"Wrote to {dzi_filename}")
                else:
                    print("tileSources data not found in the script.")
                break

        await browser.close()


async def download_tiles(dzi_file, output_dir, tile_level=0):
    """Download all tiles for a given DZI file."""
    tree = ET.parse(dzi_file)
    root = tree.getroot()

    width = int(root.find('{https://schemas.microsoft.com/deepzoom/2009}Size').get('Width'))
    height = int(root.find('{https://schemas.microsoft.com/deepzoom/2009}Size').get('Height'))
    tile_size = int(root.get('TileSize') or 510)
    base_url = root.get('Url').rstrip('/')  # 去掉末尾的斜杠

    columns = (width + tile_size - 1) // tile_size
    rows = (height + tile_size - 1) // tile_size
    failed_tiles = []

    os.makedirs(output_dir, exist_ok=True)

    for x in range(columns):
        for y in range(rows):
            # 构造 tile_url，确保不重复层级
            tile_url = f"{base_url}/{x}_{y}.png"
            tile_path = os.path.join(output_dir, f"{x}_{y}.png")

            try:
                response = await asyncio.to_thread(requests.get, tile_url)
                response.raise_for_status()
                with open(tile_path, 'wb') as f:
                    f.write(response.content)
                print(f"Downloaded tile: {tile_url}")
            except Exception as e:
                print(f"Failed to download {tile_url}: {e}")
                failed_tiles.append(tile_url)

    if failed_tiles:
        print("Some tiles could not be downloaded:")
        for failed_tile in failed_tiles:
            print(f"  - {failed_tile}")

    return width, height


def synthesize_image(output_dir, width, height):
    """Synthesize tiles into a single image."""
    tile_size = 510  # Adjust as per your tile size
    synthesized_image = Image.new('RGB', (width, height))

    columns = (width + tile_size - 1) // tile_size
    rows = (height + tile_size - 1) // tile_size

    for x in range(columns):
        for y in range(rows):
            tile_path = os.path.join(output_dir, f"{x}_{y}.png")
            if os.path.exists(tile_path):
                tile_image = Image.open(tile_path)
                position_x = x * tile_size
                position_y = y * tile_size
                synthesized_image.paste(tile_image, (position_x, position_y))

    return synthesized_image


def save_image_as_pdf(image, pdf_path):
    """Save the synthesized image as a PDF."""
    pdf = FPDF()
    pdf.add_page()
    temp_path = "temp_image.jpg"
    image.save(temp_path, "JPEG")
    pdf.image(temp_path, x=0, y=0, w=pdf.w, h=pdf.h)
    pdf.output(pdf_path)
    os.remove(temp_path)
    print(f"PDF saved successfully: {pdf_path}")


def merge_pdfs(pdf_paths, output_path):
    """Merge multiple PDFs into one."""
    merger = PdfMerger()
    for path in pdf_paths:
        merger.append(path)
    merger.write(output_path)
    merger.close()
    print(f"Merged PDF saved: {output_path}")


async def main_fetch():
    """Main function to fetch tile sources and download tiles."""
    with open("success_links.txt", "r") as f:
        urls = f.read().splitlines()

    output_directory = "E:/2025/Processed_Output"
    os.makedirs(output_directory, exist_ok=True)

    pdf_paths = []
    # 获取用户输入的层级
    tile_level = int(input("请输入图像的层级："))

    for index, url in enumerate(urls, start=1):
        page_output_dir = os.path.join(output_directory, f"DZI_{index}")
        os.makedirs(page_output_dir, exist_ok=True)

        # 添加自定义瓦片参数
        await fetch_tile_sources_from_page(url, index, page_output_dir, tile_level)

        dzi_filename = os.path.join(page_output_dir, f"dzi_{index}.dzi")
        if os.path.exists(dzi_filename):
            width, height = await download_tiles(dzi_filename, page_output_dir, tile_level)
            synthesized_image = synthesize_image(page_output_dir, width, height)

            pdf_path = os.path.join(page_output_dir, f"synthesized_{index}.pdf")
            save_image_as_pdf(synthesized_image, pdf_path)
            pdf_paths.append(pdf_path)

    merged_pdf_path = os.path.join(output_directory, "merged_output.pdf")
    merge_pdfs(pdf_paths, merged_pdf_path)
    print("All processing completed.")


if __name__ == "__main__":
    asyncio.run(main_fetch())
