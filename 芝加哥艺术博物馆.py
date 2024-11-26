import os
import math
import requests
import concurrent.futures
from PIL import Image
from tqdm import tqdm


class IIIFDownloader:
    def __init__(self, base_url, image_width, image_height, tile_size=256, max_workers=10):
        """
        Initialize IIIF image downloader with multi-threading support

        :param base_url: Base IIIF image URL
        :param image_width: Total image width
        :param image_height: Total image height
        :param tile_size: Size of each tile (default 256)
        :param max_workers: Maximum number of concurrent download threads
        """
        self.base_url = base_url
        self.image_width = image_width
        self.image_height = image_height
        self.tile_size = tile_size
        self.max_workers = max_workers

        # Proxy configuration (optional)
        self.proxies = {
            "http": "http://127.0.0.1:7898",
            "https": "http://127.0.0.1:7898"
        }

        # Output directory setup
        self.output_dir = "tiles"
        os.makedirs(self.output_dir, exist_ok=True)

    def _generate_tile_url(self, x, y):
        """Generate tile URL for specific region"""
        region_x = x * self.tile_size
        region_y = y * self.tile_size
        width = min(self.tile_size, self.image_width - region_x)
        height = min(self.tile_size, self.image_height - region_y)

        return (
            f"{self.base_url}/{region_x},{region_y},{width},{height}/256,/0/default.jpg",
            os.path.join(self.output_dir, f"tile_{x}_{y}.jpg"),
            x, y
        )

    def download_tile(self, tile_info, retries=3):
        """
        Download a single tile with retry mechanism

        :param tile_info: Tuple containing (tile_url, output_path, x, y)
        :param retries: Number of download retries
        :return: Success status and tile information
        """
        tile_url, output_path, x, y = tile_info

        # Skip if tile already exists
        if os.path.exists(output_path):
            return True, (tile_url, output_path, x, y)

        for attempt in range(retries):
            try:
                response = requests.get(
                    tile_url,
                    proxies=self.proxies,
                    timeout=15,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Accept': 'image/jpeg'
                    }
                )

                if response.status_code == 200:
                    with open(output_path, "wb") as f:
                        f.write(response.content)
                    return True, (tile_url, output_path, x, y)

            except requests.exceptions.RequestException as e:
                print(f"Download error for tile {x},{y}: {e}")

        return False, (tile_url, output_path, x, y)

    def download_tiles(self):
        """
        Download tiles using concurrent threading
        """
        # Calculate total number of tiles
        tiles_x = math.ceil(self.image_width / self.tile_size)
        tiles_y = math.ceil(self.image_height / self.tile_size)

        # Generate tile URLs and paths
        tile_urls = [self._generate_tile_url(x, y) for x in range(tiles_x) for y in range(tiles_y)]

        # Progress tracking
        progress_bar = tqdm(total=len(tile_urls), desc="Downloading Tiles", unit="tile",
                            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]")

        # Successful and failed downloads
        successful_tiles = []
        failed_tiles = []

        # Multi-threaded download
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_tile = {executor.submit(self.download_tile, tile): tile for tile in tile_urls}

            for future in concurrent.futures.as_completed(future_to_tile):
                success, tile_info = future.result()
                progress_bar.update(1)

                if success:
                    successful_tiles.append(tile_info)
                else:
                    failed_tiles.append(tile_info)

        progress_bar.close()

        # Report download results
        print(f"\nDownload Summary:")
        print(f"Total Tiles: {len(tile_urls)}")
        print(f"Successful Downloads: {len(successful_tiles)}")
        print(f"Failed Downloads: {len(failed_tiles)}")

        return successful_tiles, failed_tiles

    def stitch_tiles(self):
        """
        Stitch downloaded tiles into a single image
        """
        # Calculate total number of tiles
        tiles_x = math.ceil(self.image_width / self.tile_size)
        tiles_y = math.ceil(self.image_height / self.tile_size)

        # Create output image
        full_image = Image.new("RGB", (self.image_width, self.image_height), color=(240, 240, 255))

        # Stitch tiles
        for x in range(tiles_x):
            for y in range(tiles_y):
                tile_path = os.path.join(self.output_dir, f"tile_{x}_{y}.jpg")

                if os.path.exists(tile_path):
                    tile = Image.open(tile_path)
                    full_image.paste(tile, (x * self.tile_size, y * self.tile_size))

        # Save stitched image with a Windows-inspired filename
        output_filename = "ArchivalImage_Stitched.jpg"
        full_image.save(output_filename, quality=95)
        print(f"Image stitched successfully: {output_filename}")


def main():
    # IIIF Image Configuration
    base_url = "https://www.artic.edu/iiif/2/3a608f55-d76e-fa96-d0b1-0789fbc48f1e"
    image_width = 19848
    image_height = 24629

    # Create downloader instance
    downloader = IIIFDownloader(
        base_url=base_url,
        image_width=image_width,
        image_height=image_height,
        max_workers=20  # Adjust based on your network capacity
    )

    # Download tiles
    successful_tiles, failed_tiles = downloader.download_tiles()

    # Prompt for stitching
    stitch_prompt = input("Would you like to stitch the tiles? (y/n): ").strip().lower()
    if stitch_prompt == "y":
        downloader.stitch_tiles()


if __name__ == "__main__":
    main()
