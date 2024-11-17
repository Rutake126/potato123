import asyncio
import aiohttp
import os
from PIL import Image
import io
import warnings
import numpy as np
import re


class ImageDownloader:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/114.0.0.0 Safari/537.36",
            "Referer": "https://www.dpm.org.cn/"
        }
        self.base_url = "https://www.dpm.org.cn"
        self.output_dir = "dpm_tiles"
        self.tile_size = 256
        self.current_url_info = None
        self.total_urls = 0
        self.current_url_index = 0
        self.max_retries = 2

    def extract_url_info(self, url):
        """Extract image information from URL"""
        pattern = r"/Uploads/tilegenerator/dest/files/image/(\d+)/(\d+)/(\d+)/([^.]+)\.xml"
        match = re.search(pattern, url)
        if match:
            return {
                'path': f"/Uploads/tilegenerator/dest/files/image/{match.group(1)}/{match.group(2)}/{match.group(3)}/{match.group(4)}"
            }
        return None

    def load_urls(self, file_path):
        """Load URLs from a text file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                urls = [line.strip() for line in f if line.strip()]
            self.total_urls = len(urls)
            print(f"Loaded {self.total_urls} URLs from {file_path}")
            return urls
        except Exception as e:
            print(f"Error loading URLs from file: {e}")
            return []

    async def download_tile(self, session, x, y, level, retry_count=0):
        """Download a single tile with retry logic"""
        if not self.current_url_info:
            return None

        tile_url = f"{self.current_url_info['path']}_files/{level}/{x}_{y}.jpg"
        full_url = self.base_url + tile_url

        try:
            async with session.get(full_url) as response:
                if response.status == 200:
                    return await response.read()
                if retry_count < self.max_retries:
                    print(f"\nRetrying tile {x},{y} at level {level} (Attempt {retry_count + 2})")
                    await asyncio.sleep(1)  # Wait before retry
                    return await self.download_tile(session, x, y, level, retry_count + 1)
                return None
        except Exception as e:
            if retry_count < self.max_retries:
                print(f"\nRetrying tile {x},{y} at level {level} (Attempt {retry_count + 2})")
                await asyncio.sleep(1)  # Wait before retry
                return await self.download_tile(session, x, y, level, retry_count + 1)
            print(f"Error downloading tile {x},{y} at level {level}: {e}")
            return None

    async def test_level_validity(self, session, level):
        """Test if the level exists by checking a few tiles"""
        test_positions = [(0, 0), (0, 1), (1, 0), (1, 1)]
        for x, y in test_positions:
            tile_data = await self.download_tile(session, x, y, level)
            if tile_data:
                return True
        return False

    async def get_level_dimensions(self, session, level):
        """Get dimensions for specific level by testing tiles"""
        max_test = 100

        async def check_tile(x, y):
            tile_data = await self.download_tile(session, x, y, level)
            return tile_data is not None

        x_size = y_size = 0

        print("Detecting image dimensions...")
        for i in range(max_test):
            x_exists = await check_tile(i, 0)
            y_exists = await check_tile(0, i)

            if not x_exists and x_size == 0:
                x_size = i
            if not y_exists and y_size == 0:
                y_size = i

            if x_size != 0 and y_size != 0:
                break

            print(f"Scanning dimensions... Current size: {i}x{i}", end='\r')

        print(f"\nDetected image grid size: {x_size}x{y_size} tiles")
        return x_size, y_size

    def precise_crop(self, image):
        """Precisely crop the image to content edges using advanced edge detection"""
        # Convert to numpy array
        img_array = np.array(image)

        if len(img_array.shape) == 3:
            # Convert to grayscale for edge detection
            gray_array = np.mean(img_array, axis=2)
        else:
            gray_array = img_array

        # Calculate gradients for edge detection
        gradient_x = np.gradient(gray_array, axis=1)
        gradient_y = np.gradient(gray_array, axis=0)
        gradient_magnitude = np.sqrt(gradient_x ** 2 + gradient_y ** 2)

        # Find significant edges (adjust threshold as needed)
        edge_threshold = np.percentile(gradient_magnitude, 90)
        edges = gradient_magnitude > edge_threshold

        # Find the outermost significant edges
        rows = np.where(np.any(edges, axis=1))[0]
        cols = np.where(np.any(edges, axis=0))[0]

        if len(rows) == 0 or len(cols) == 0:
            return image

        # Add a small buffer to ensure we don't crop too tightly
        buffer = 2
        top = max(rows[0] - buffer, 0)
        bottom = min(rows[-1] + buffer, img_array.shape[0])
        left = max(cols[0] - buffer, 0)
        right = min(cols[-1] + buffer, img_array.shape[1])

        return image.crop((left, top, right, bottom))

    async def download_level(self, session, level, url_index):
        """Download and compose image for specific level"""
        print(f"\nProcessing URL {url_index + 1}/{self.total_urls}")
        print(f"Analyzing level {level}...")

        tiles_x, tiles_y = await self.get_level_dimensions(session, level)

        if tiles_x == 0 or tiles_y == 0:
            print(f"No tiles found at level {level}")
            return False

        # Create canvas with transparent background
        canvas = Image.new('RGBA', (tiles_x * self.tile_size, tiles_y * self.tile_size), (0, 0, 0, 0))

        print(f"Downloading {tiles_x * tiles_y} tiles...")
        total_tiles = tiles_x * tiles_y
        downloaded_tiles = 0

        for y in range(tiles_y):
            for x in range(tiles_x):
                tile_data = await self.download_tile(session, x, y, level)
                if tile_data:
                    try:
                        tile_image = Image.open(io.BytesIO(tile_data))
                        if tile_image.mode != 'RGBA':
                            tile_image = tile_image.convert('RGBA')
                        canvas.paste(tile_image, (x * self.tile_size, y * self.tile_size))

                        downloaded_tiles += 1
                        tile_progress = (downloaded_tiles / total_tiles) * 100
                        total_progress = ((url_index + tile_progress / 100) / self.total_urls) * 100
                        print(f"Current image: {tile_progress:.1f}% | Overall progress: {total_progress:.1f}%",
                              end='\r')
                    except Exception as e:
                        print(f"\nError processing tile {x},{y}: {e}")

        print("\nProcessing final image...")
        canvas = canvas.convert('RGB')
        canvas = self.precise_crop(canvas)

        # Create output directory with URL index
        url_output_dir = os.path.join(self.output_dir, f"url_{url_index + 1}")
        os.makedirs(url_output_dir, exist_ok=True)

        print("Saving image...")
        output_path = os.path.join(url_output_dir, f"final_image_level_{level}.jpg")
        canvas.save(output_path, "JPEG", quality=95)
        print(f"Saved final image to {output_path}")

        print(f"Final image dimensions: {canvas.size[0]}x{canvas.size[1]} pixels")
        return True

    async def get_valid_level(self, session):
        """Get a valid level from user input with retry logic"""
        while True:
            print("\nIt is recommended to enter a level of 0-15 (higher level = higher resolution)")
            try:
                level = int(input("Enter desired level: "))
                if 0 <= level <= 15:
                    return level
                else:
                    print("Please enter a number between 0 and 15.")
            except ValueError:
                print("Please enter a valid number.")

    async def run(self):
        """Main execution function"""
        # Load URLs from file
        urls = self.load_urls(r"E:\2025\1.txt")
        if not urls:
            print("No URLs found in the file. Exiting...")
            return

        try:
            # Ask user for download mode
            while True:
                choice = input("\nDo you want to download all URLs or a single URL?\n1: All URLs\n2: Single "
                               "URL\nEnter your choice (1 or 2): ")
                if choice in ['1', '2']:
                    break
                print("Please enter either 1 or 2.")

            # Get level input
            async with aiohttp.ClientSession(headers=self.headers) as session:
                level = await self.get_valid_level(session)

                if choice == '1':
                    # Download all URLs
                    url_range = range(len(urls))
                else:
                    # Let user choose a specific URL
                    while True:
                        print("\nAvailable URLs:")
                        for i, url in enumerate(urls, 1):
                            print(f"{i}: {url}")
                        try:
                            url_index = int(input(f"\nEnter URL number (1-{len(urls)}): ")) - 1
                            if 0 <= url_index < len(urls):
                                url_range = [url_index]
                                break
                            else:
                                print(f"Please enter a number between 1 and {len(urls)}.")
                        except ValueError:
                            print("Please enter a valid number.")

                # Process selected URLs
                for i in url_range:
                    url = urls[i]
                    url_info = self.extract_url_info(url)
                    if not url_info:
                        print(f"\nInvalid URL format for URL {i + 1}: {url}")
                        continue

                    self.current_url_info = url_info
                    self.current_url_index = i
                    print(f"\nProcessing URL {i + 1}/{self.total_urls}: {url}")

                    print("Testing level validity...")
                    if await self.test_level_validity(session, level):
                        await self.download_level(session, level, i)
                    else:
                        print(f"No valid image found at level {level} for URL: {url}")

            print("\nBatch download completed!")

        except Exception as e:
            print(f"An error occurred: {e}")


async def main():
    downloader = ImageDownloader()
    await downloader.run()


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=ResourceWarning)
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
