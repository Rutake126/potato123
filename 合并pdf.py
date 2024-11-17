import os
from PIL import Image
from pathlib import Path
from reportlab.pdfgen import canvas
import glob


class PDFGenerator:
    def __init__(self, input_dir, output_file):
        self.input_dir = Path(input_dir)
        self.output_file = output_file
        self.image_paths = []

    def get_sorted_images(self):
        """Get sorted list of image paths from numbered folders"""
        image_paths = []
        for i in range(1, 28):
            folder = self.input_dir / f"url_{i}"
            if folder.exists():
                jpg_files = list(folder.glob("*.jpg"))
                if jpg_files:
                    image_paths.append(jpg_files[0])
                else:
                    print(f"No jpg file found in {folder}")
        return image_paths

    def create_pdf(self):
        """Create PDF from images"""
        try:
            image_paths = self.get_sorted_images()
            if not image_paths:
                print("No images found!")
                return

            # Create PDF without specifying page size
            c = canvas.Canvas(self.output_file)
            total_images = len(image_paths)

            for idx, img_path in enumerate(image_paths, 1):
                try:
                    # Get image size
                    img = Image.open(img_path)
                    img_width, img_height = img.size

                    # Set page size to match image size
                    c.setPageSize((img_width, img_height))

                    # Draw image at full size at (0,0)
                    c.drawImage(str(img_path), 0, 0, img_width, img_height)

                    # New page unless it's the last image
                    if idx < total_images:
                        c.showPage()

                    # Print progress
                    print(f"Processing image {idx}/{total_images}")

                except Exception as e:
                    print(f"Error processing image {img_path}: {e}")

            # Save PDF
            c.save()
            print(f"\nPDF created successfully: {self.output_file}")

        except Exception as e:
            print(f"Error creating PDF: {e}")


def main():
    input_dir = r"E:\2025\dpm_tiles"
    output_file = os.path.join(input_dir, "combined_images.pdf")
    pdf_gen = PDFGenerator(input_dir, output_file)
    pdf_gen.create_pdf()


if __name__ == "__main__":
    main()
