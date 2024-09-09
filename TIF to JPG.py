from PIL import Image
import os


def convert_tif_to_jpg_or_png(folder, output_format='JPEG'):
    output_format = output_format.upper()

    for filename in os.listdir(folder):
        if filename.endswith('.tif') or filename.endswith('.TIF'):
            file_path = os.path.join(folder, filename)

            with Image.open(file_path) as img:
                base_name = os.path.splitext(filename)[0]
                output_filename = f"{base_name}.{output_format.lower()}"
                output_path = os.path.join(folder, output_filename)

                img.save(output_path, format=output_format)
                print(f"Converted {filename} to {output_filename}")


if __name__ == "__main__":
    input_folder = r'file_path' #E:\2025
    convert_tif_to_jpg_or_png(input_folder, output_format='JPEG')
