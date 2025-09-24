# from moviepy import* （这个导入命令可以和3 line 相互替换）
#不要使用from moviepy.editor import VideoFileClip，这样会显示没有moviepy模块。
from moviepy import VideoFileClip
import os


def webm_to_mp4(input_file: str, output_dir: str):
    # 取出不带扩展名的文件名
    filename = os.path.splitext(os.path.basename(input_file))[0]
    output_file = os.path.join(output_dir, f"{filename}.mp4")

    # 加载 webm 文件
    clip = VideoFileClip(input_file)
    # 保存为 mp4 (默认使用 libx264 编码)
    clip.write_videofile(output_file, codec="libx264", audio_codec="aac")
    print(f"转换完成，输出文件: {output_file}")


# 地址自行更换

if __name__ == "__main__":
    input_path = r"C:\Users\HP\Desktop\Screen_recording_20250923_234606.webm"
    output_dir = r"C:\Users\HP\Desktop"
    webm_to_mp4(input_path, output_dir)
