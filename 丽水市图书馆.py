import requests
from tqdm import tqdm
import uuid 

# blobPdf?readerKey
pdf_url = "https://zt.chaoxing.com//reader/blobPdf?readerKey=reader_key_497119a2-79b0-44e2-b573-1e0dba698492"

# 设置请求头
headers = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Cookie": "lv=0; fid=23274; _uid=198229518; "
              "uf=da0883eb5260151ea4b61e3b343b27951db95ec2b45beeef68c7186e61e85d2c7deaca935404f11dc6869c0602f9689a2a80cd29a298e70788b83130e7eb47041e69c3c2ee9b648ffd68be96b6183b1a43db19639184bc45a4cc541a94e96ddeaf269178226178b5; _d=1727413359218; UID=198229518; vc=5B1037E1D70FD0AAC2F2539A4A17212A; vc2=C1F50693C8D75A171723EB9A85962C5E; vc3=Zt1j3kmdlgQTsIl9zOgaJk8gbaK10cynKdOPP%2BGxd%2BouNQUG1oSAniKRgL4maCCXMUeU9UC0HDyi%2BGLjSDHeO%2FhiOYLC%2Bka4SlongpquYkMOLo1TDENCUgObw4Wilu1tRtT0ZlOl3GFjPuBLNaIysuaXF0VF8aKawyX32brwusk%3Df9d99e377449a8136181ece8fc33593d; cx_p_token=6bb26f95cfd69ecbfca50f01346862f2; p_auth_token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1aWQiOiIxOTgyMjk1MTgiLCJsb2dpblRpbWUiOjE3Mjc0MTMzNTkyMjAsImV4cCI6MTcyODAxODE1OX0.xCc7QhKItd8s-6l70dk9UAs_W_q9p-DPpKWwVsqG5cE; xxtenc=68c8809e52a29fb867a5f3af69ef30b4; DSSTASH_LOG=C_38-UN_40-US_198229518-T_1727413359220; browserLocale=zh_CN; SESSION=N2VjMjdlNGYtNWY2MC00OThjLWE4ZTktMzgwNDUzOWJlMjQ3; route=9573ba14c1cb298bd6da06080ffdb1d7",
    "Host": "zt.chaoxing.com",
    "Pragma": "no-cache",
    "Referer": "https://zt.chaoxing.com/",
    "Sec-CH-UA": '"Microsoft Edge";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 "
                  "Safari/537.36 Edg/129.0.0.0 "
}

# 禁用代理（可选）
proxies = {
    "http": None,
    "https": None,
}

# 发起GET请求，并设置禁用代理
response = requests.get(pdf_url, headers=headers, stream=True, proxies=proxies)

# 检查请求是否成功
if response.status_code == 200:
    # 获取PDF文件总大小（字节）
    total_size = int(response.headers.get("Content-Length", 0))

    # 随机生成文件名（带 .pdf 扩展名）
    random_filename = f"{uuid.uuid4()}.pdf"
    print(f"保存为随机文件名: {random_filename}")

    # 使用 tqdm 显示下载进度条
    with open(random_filename, "wb") as file, tqdm(
        desc="下载进度",
        total=total_size,
        unit="B",
        unit_scale=True,
        unit_divisor=1024,
    ) as bar:
        for chunk in response.iter_content(chunk_size=1024):
            file.write(chunk)
            # 更新进度条
            bar.update(len(chunk))
    print("PDF下载完成！")
else:
    print(f"下载失败，状态码：{response.status_code}")

