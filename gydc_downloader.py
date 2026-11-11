#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
古医典藏 / PDF 下载器  (gydc-v4.cintcm.cn)
==========================================

默认「原版 PDF」模式：把书籍详情页链接解析成站点逐页原版 PDF 接口，探测总页数，
逐页取回原版 PDF 后直接合并成一份《书名.pdf》——全程不下载、不落地任何图片，
并完整保留原版自带的中文 OCR 文字层、字体子集和高清 /JPXDecode 图像。

启动前会实测该书的数据源能力：若站点没有生成原版 PDF（只有图像），
自动降级到「图片模式 / 缩略图」，页数探测也改用图像接口，保证这类书仍能下载。

仍保留可选的「图片」模式（旧行为）：按 书名/001.JPG、002.JPG … 落盘，再合成 PDF。

用法
----
    python gydc_downloader.py                                  # 图形界面
    python gydc_downloader.py --cli "https://gydc-v4.cintcm.cn/#/bookDetail?book=1198821" --all
    python gydc_downloader.py --cli 1198821 --pages 1-5 -o D:\\books
    python gydc_downloader.py --cli 1385256 --all --keep-pages   # 另存每页原版 PDF（001.pdf…）
    python gydc_downloader.py --cli 1385256 --all --images       # 改回图片模式（高清）
    python gydc_downloader.py --cli 1385256 --all --low-res      # 图片模式 + 旧缩略图源
    python gydc_downloader.py --cli 1385256 --all --no-pdf       # 图片模式，只下图不合成

只依赖 Python 标准库；图形界面另需 tkinter。装了 pypdf 时由它合并原版 PDF，
没装也不要紧——内置一个纯标准库合并器（对象重编号 + xref 重建），零依赖照样能出 PDF。
图片模式下，装了 Pillow/JPEG2000 时落成 001.JPG，否则落成无损 001.JP2；
自建 PDF 走 /DCTDecode、/JPXDecode，原始字节直嵌，不二次压缩。

站点要点（都是实测结论，改版时优先查这里）
-------------------------------------------
* 详情页是 Vue hash 路由，# 后面的内容不会发给服务器，直接抓 HTML 只有空壳。
* 站点 HTTPS 证书已过期，必须关闭证书校验；标准库用 ssl.CERT_NONE。
* 真正接口： /retrieve/page/getImage?bookId=<id>&page=<n>  -> 缩略图 JPEG，约 421×726
             响应头写 image/png，实际是 JPEG（魔数 FFD8FFE0），按魔数判断。
             /retrieve/page/getPdf?bookId=<id>&page=<n>      -> 单页「原版 PDF」
             /retrieve/page/getXML?bookId=<id>&page=<n>      -> 该页 OCR XML，封面含书名
             /retrieve/book/getBookInfo                       -> 需登录，返回「用户需要登录才能进行操作」
* 单页原版 PDF 不只是图片壳：%PDF-1.6 线性化 PDF，内含 /JPXDecode 高清原图
  （约 1755×3024，逐页不同）、嵌入字体子集 + ToUnicode + FlateDecode 内容流（OCR 文字层）、
  结构树、Metadata。直接合并它，比「抠图 -> 转 JPG -> 重建 PDF」更清晰、更小、且能选中文字。
* 实测没有整本 PDF 直链：前端只按 currentPage 调 getPdf；/retrieve/book/getPdf、
  downloadPdf、getBookPdf、downBook、download 等端点全 404；给 getPdf 加 all=1、
  pageCount=92、type=all 等参数都被忽略，仍返回单页。所以是「逐页取 + 合并」，不是一次拿整本。
* 越界页返回 HTTP 500 + JSON。优先用体积很小的 getXML 二分探测页数；
  没有 OCR XML 的书自动改用 getImage 二分（同样靠 500 判越界）。
* 并非每本书都有全套数据：有些书号是「字母前缀 + 数字」（hwzdt0387），
  服务端只生成了 getImage 图像；getPdf 返回 500（manage_filestorage/pdf/<id>
  找不到文件）、getXML 返回 400、getBookInfo 需登录。能力探测后自动降级为
  「图像模式 / 缩略图」，页数 / 图片 / PDF 照常产出，但 PDF 无文字层，
  清晰度受站点图像限制（约 369~675×600，加 type/width/scale 等参数都拿不到更大图）。
* 接口免登录；页面禁右键 / Ctrl+S 只影响浏览器，不影响接口。
* 原版 PDF 取不到时（网络/权限异常）记录失败页，修好后重跑会重试；需要单页 PDF
  或断点续传时用 --keep-pages。图片模式仍保留高清失败自动回退 getImage 的行为。
"""

from __future__ import annotations

import argparse
import html
import io
import json
import os
import queue
import re
import ssl
import struct
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path

# --------------------------------------------------------------------------
# 站点常量
# --------------------------------------------------------------------------
BASE = "https://gydc-v4.cintcm.cn"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
MIN_JPEG_BYTES = 3000
HD_MIN_WIDTH = 1000          # 宽度低于此值视为旧的缩略图，高清模式下会重下
MIN_ORIGINAL_PDF_BYTES = 10000   # 单页原版 PDF 的最小合理体积
BAD_FILENAME = re.compile(r'[\\/:*?"<>|\r\n\t\x00-\x1f]')
CACHE_DIR = Path.home() / ".gydc_downloader"
CACHE_FILE = CACHE_DIR / "pages.json"
SETTINGS_FILE = CACHE_DIR / "settings.json"


def detail_url(bid: str) -> str:
    return f"{BASE}/#/bookDetail?book={bid}"


def image_url(bid: str, page: int) -> str:
    return f"{BASE}/retrieve/page/getImage?bookId={bid}&page={page}"


def image_template(bid: str) -> str:
    """给用户看的「正确链接」模板，{page} 由程序逐页替换。"""
    return f"{BASE}/retrieve/page/getImage?bookId={bid}&page={{page}}"


def pdf_url(bid: str, page: int) -> str:
    """高清源：单页 PDF，内部嵌着 /JPXDecode 的 JPEG2000 原图。"""
    return f"{BASE}/retrieve/page/getPdf?bookId={bid}&page={page}"


def pdf_template(bid: str) -> str:
    return f"{BASE}/retrieve/page/getPdf?bookId={bid}&page={{page}}"


def xml_url(bid: str, page: int) -> str:
    return f"{BASE}/retrieve/page/getXML?bookId={bid}&page={page}"


INFO_URL = f"{BASE}/retrieve/book/getBookInfo"


# --------------------------------------------------------------------------
# 链接解析：把用户粘贴的任何形式统一成 bookId
# --------------------------------------------------------------------------
# 书号不只是纯数字：站点里还有 hwzdt0387 这类「字母前缀 + 数字」的编号。
# 允许字母/数字开头，后跟字母、数字、下划线、连字符；长度 3~48。
_BOOK_ID = r"[A-Za-z0-9][A-Za-z0-9_-]{2,47}"
_BOOK_PATTERNS = (
    re.compile(r'book(?:Id|id)?\s*[=:]\s*(' + _BOOK_ID + r')', re.I),
    re.compile(r'recordId\s*[=:]\s*(' + _BOOK_ID + r')', re.I),
    re.compile(r'/book(?:Detail)?/(' + _BOOK_ID + r')', re.I),
)


@dataclass(frozen=True)
class BookRef:
    book_id: str
    raw: str

    @property
    def detail(self) -> str:
        return detail_url(self.book_id)

    @property
    def template(self) -> str:
        """缩略图接口模板（备用源）。"""
        return image_template(self.book_id)

    @property
    def hd_template(self) -> str:
        """高清接口模板（默认主源）。"""
        return pdf_template(self.book_id)

    def template_for(self, hd: bool) -> str:
        return self.hd_template if hd else self.template

    def image(self, page: int) -> str:
        return image_url(self.book_id, page)

    def pdf(self, page: int) -> str:
        return pdf_url(self.book_id, page)

    def xml(self, page: int) -> str:
        return xml_url(self.book_id, page)


def parse_book_input(raw: str) -> BookRef:
    """接受: 详情页 URL / 图像接口 URL / 裸 bookId / 带 bookId= 的任意 URL。

    bookId 既可以是纯数字（1198821），也可以是字母数字混合（hwzdt0387）。
    """
    s = (raw or "").strip()
    if not s:
        raise ValueError("链接不能为空")
    if re.fullmatch(_BOOK_ID, s):
        return BookRef(s, s)
    decoded = urllib.parse.unquote(urllib.parse.unquote(s))
    for pat in _BOOK_PATTERNS:
        m = pat.search(decoded)
        if m:
            return BookRef(m.group(1), s)
    m = re.search(r"(\d{5,12})", decoded)          # 退化：抓最像书号的长数字
    if m:
        return BookRef(m.group(1), s)
    raise ValueError("无法从输入里识别 bookId；支持纯数字或字母数字混合书号，"
                     "例如 ...#/bookDetail?book=1198821 或 ...?book=hwzdt0387")


def sanitize_filename(name: str, limit: int = 80) -> str:
    name = html.unescape(name or "").strip()
    name = BAD_FILENAME.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name[:limit] or "untitled")


class Cancelled(Exception):
    """用户点了「停止任务」。"""


# --------------------------------------------------------------------------
# HTTP：标准库实现，关闭过期证书校验，带重试 / 节流 / 取消
# --------------------------------------------------------------------------
@dataclass
class Resp:
    status: int
    body: bytes
    content_type: str = ""


class HttpClient:
    def __init__(self, timeout=25, retries=3, pause=0.08, token="", proxy="",
                 cancel: threading.Event | None = None):
        self.timeout = timeout
        self.retries = retries
        self.pause = pause
        self.token = token.strip()
        self.cancel = cancel
        self._ctx = ssl.create_default_context()
        self._ctx.check_hostname = False          # 站点证书已过期
        self._ctx.verify_mode = ssl.CERT_NONE
        handlers = [urllib.request.HTTPSHandler(context=self._ctx)]
        if proxy.strip():
            handlers.append(urllib.request.ProxyHandler(
                {"http": proxy.strip(), "https": proxy.strip()}))
        self._opener = urllib.request.build_opener(*handlers)
        self._lock = threading.Lock()
        self._last = 0.0

    def _check_cancel(self):
        if self.cancel is not None and self.cancel.is_set():
            raise Cancelled()

    def _throttle(self):
        if self.pause <= 0:
            return
        with self._lock:
            delta = time.monotonic() - self._last
            if delta < self.pause:
                time.sleep(self.pause - delta)
            self._last = time.monotonic()

    def _headers(self) -> dict:
        h = {"User-Agent": UA, "Referer": BASE + "/", "Accept": "*/*"}
        if self.token:
            h["Authorization"] = self.token
        return h

    def get(self, url: str) -> Resp:
        req = urllib.request.Request(url, headers=self._headers())
        last_exc = None
        for attempt in range(self.retries + 1):
            self._check_cancel()
            self._throttle()
            try:
                with self._opener.open(req, timeout=self.timeout) as r:
                    return Resp(r.status, r.read(), r.headers.get("Content-Type", ""))
            except urllib.error.HTTPError as e:
                try:
                    body = e.read()
                except Exception:
                    body = b""
                return Resp(e.code, body, e.headers.get("Content-Type", "") if e.headers else "")
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_exc = e
                if attempt < self.retries:
                    time.sleep(0.6 * (attempt + 1))
        raise last_exc or RuntimeError("请求失败")

    def post_form(self, url: str, form: dict) -> Resp:
        data = urllib.parse.urlencode(form).encode()
        req = urllib.request.Request(url, data=data, headers={
            **self._headers(), "Content-Type": "application/x-www-form-urlencoded"})
        try:
            with self._opener.open(req, timeout=self.timeout) as r:
                return Resp(r.status, r.read(), r.headers.get("Content-Type", ""))
        except urllib.error.HTTPError as e:
            return Resp(e.code, e.read(), "")


# --------------------------------------------------------------------------
# 书名 / 总页数
# --------------------------------------------------------------------------
def _title_from_xml(http: HttpClient, bid: str, page: int) -> tuple[str, str]:
    """从某页 OCR XML 里挑出最像书名的那一行：字体最大（fs 最大）且不太长的一行。

    返回 (书名, "OCR 题名")；找不到返回 ("", "")。
    """
    try:
        r = http.get(xml_url(bid, page))
    except Exception:
        return "", ""
    if r.status != 200:
        return "", ""
    text = r.body.decode("utf-8-sig", "replace")
    blocks = re.findall(r"<bl\b([^>]*)>(.*?)</bl>", text, re.S | re.I)
    if not blocks:
        return "", ""
    best, best_fs = "", -1
    for attrs, content in blocks:
        c = re.sub(r"<[^>]+>", "", content).strip()
        if not c or len(c) > 30:          # 太长的是正文/题跋，不是书名
            continue
        m = re.search(r'fs="(\d+)"', attrs)
        fs = int(m.group(1)) if m else 0
        if fs > best_fs:
            best_fs, best = fs, c
    if best:
        return sanitize_filename(html.unescape(best)), "OCR 题名"
    return "", ""


def fetch_title(http: HttpClient, bid: str) -> tuple[str, str]:
    """返回 (书名, 来源说明)。OCR XML 免登录可用，因此不需要账号。

    封面（第 1 页）未必有 OCR 文字层：有些书封面是图片，书名要到第 2~6 页的
    书名页才出现（例如《景岳全書》的封面 XML 是空的，书名在第 2 页）。
    所以先试官方元数据，再扫前几页 XML，挑字体最大的一行当书名。
    """
    # 有 token 时先试官方元数据，拿到的是规范书名
    if http.token:
        try:
            r = http.post_form(INFO_URL, {"bookId": bid})
            obj = json.loads(r.body.decode("utf-8", "replace"))
            name = (obj.get("data") or {}).get("bookName")
            if name:
                return sanitize_filename(str(name)), "官方元数据"
        except Exception:
            pass
    # 封面优先；没有（或被图片占满）再往后扫几页找书名页，取字体最大的一行
    for page in range(1, 7):
        try:
            title, src = _title_from_xml(http, bid, page)
        except Exception:
            title, src = "", ""
        if title:
            return title, (f"第 {page} 页 {src}" if page > 1 else src)
    return f"book_{bid}", "回退：使用书号"


def _cache_get(bid: str) -> int | None:
    try:
        data = json.loads(CACHE_FILE.read_text("utf-8"))
        item = data.get(bid)
        if item and datetime.fromisoformat(item["time"]) > datetime.now() - timedelta(days=7):
            return int(item["pages"])
    except Exception:
        pass
    return None


def _cache_set(bid: str, pages: int):
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        data = {}
        if CACHE_FILE.exists():
            try:
                data = json.loads(CACHE_FILE.read_text("utf-8"))
            except Exception:
                data = {}
        data[bid] = {"pages": pages, "time": datetime.now().isoformat(timespec="seconds")}
        CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    except Exception:
        pass


def _xml_page_ok(http: HttpClient, bid: str, page: int) -> bool:
    """越界页 = HTTP 500；偶发 5xx 重试一次，避免二分被单次抖动带偏。"""
    for attempt in range(2):
        r = http.get(xml_url(bid, page))
        if r.status == 200 and b"<page" in r.body[:600]:
            return True
        if r.status < 500 or r.status > 599:
            return False
        if attempt == 0:
            time.sleep(0.25)
    return False


def _image_page_ok(http: HttpClient, bid: str, page: int) -> bool:
    """无 OCR XML 的书（如 hwzdt0387）用图像接口判页：越界同样是 HTTP 500。"""
    for attempt in range(2):
        r = http.get(image_url(bid, page))
        if r.status == 200 and len(r.body) >= MIN_JPEG_BYTES and is_jpeg(r.body):
            return True
        if r.status < 500 or r.status > 599:
            return False
        if attempt == 0:
            time.sleep(0.25)
    return False


def detect_total_pages(http: HttpClient, bid: str, cap: int = 100000,
                       log=None, use_cache: bool = True,
                       cancel: threading.Event | None = None) -> int:
    """用轻量 XML 接口做「指数扩展 + 二分」定位末页。

    cap 只是一个「安全天花板」：只有真实页数确实越过 cap、且 cap 这一页本身仍有效
    时才会被截断。早期版本在 hi 刚超过 cap 就直接 return cap，会把 5532 页误判成 4096。
    """
    def say(msg):
        if log:
            log(msg)

    def check_cancel():
        # GUI 显式传入 cancel；CLI 未传时以 HttpClient 自带的为准
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        http._check_cancel()

    if use_cache:
        hit = _cache_get(bid)
        if hit:
            say(f"页数缓存命中：{hit} 页")
            return hit

    # 有些书（如 hwzdt0387）服务端没有生成 OCR XML，getXML 直接 400；
    # 这时改用 getImage 做同样的二分，越界页同样返回 500。
    xml_ok = _xml_page_ok(http, bid, 1)
    if xml_ok:
        page_ok = _xml_page_ok
    else:
        say("该书没有 OCR XML（服务端未生成文字层），改用图像接口探测页数")
        page_ok = _image_page_ok
        if not _image_page_ok(http, bid, 1):
            raise RuntimeError("第 1 页都无法访问：书号可能有误，或该册需要登录权限")

    # 指数扩展找上界；cap 只是「安全天花板」，不再在 hi 刚超过 cap 时直接 return cap
    #（那样会把 5532 页误判成 4096）。只有真实越界页被压到 cap、且 cap 本身仍有效时，
    # 才以 cap 作为结果并给出提示。
    lo, hi = 1, 2
    overflow = False
    while page_ok(http, bid, hi):
        lo = hi
        hi *= 2
        if hi > cap:
            hi = cap
            overflow = True
            break
        check_cancel()
    say(f"探测区间：第 {lo} 页有效，第 {hi} 页越界")
    if overflow and page_ok(http, bid, cap):
        # 上界被压到 cap 且 cap 本身仍有效：真实页数可能超过 cap，按上限处理
        say(f"页数探测到上限 {cap}（该书实际可能更多，已按上限 {cap} 处理）")
        total = cap
    else:
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            if page_ok(http, bid, mid):
                lo = mid
            else:
                hi = mid
            check_cancel()
        total = lo

    # 边界加固：确认后面两页确实越界；若有效说明中间有空洞，线性补齐
    while total < cap and page_ok(http, bid, total + 1):
        total += 1
        check_cancel()

    # XML 探测出来的末页还要用图像复核一次，避免两种源页数不一致；
    # 图像探测时判据本身就是图像，无需再复核。
    if xml_ok:
        r = http.get(image_url(bid, total))
        ok = r.status == 200 and is_jpeg(r.body)
        if not ok:
            rp = http.get(pdf_url(bid, total))
            ok = rp.status == 200 and b"/JPXDecode" in rp.body
        if not ok:
            say(f"警告：第 {total} 页的 XML 有效但图像取不到，已回退一页")
            total = max(1, total - 1)

    _cache_set(bid, total)
    say(f"识别完成：共 {total} 页")
    return total


# --------------------------------------------------------------------------
# JPEG / PDF
# --------------------------------------------------------------------------
_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def is_jpeg(data: bytes) -> bool:
    return len(data) >= MIN_JPEG_BYTES and data[:3] == b"\xff\xd8\xff"


# --- JPEG2000：高清源 ------------------------------------------------------
JP2_BOX = b"\x00\x00\x00\x0cjP  \r\n\x87\n"


def is_jpx(data: bytes) -> bool:
    """JPEG2000 codestream（FF4FFF51）或 JP2 容器，都认。"""
    return (len(data) >= MIN_JPEG_BYTES and
            (data[:4] == b"\xff\x4f\xff\x51" or data[:12] == JP2_BOX))


def jpx_dimensions(data: bytes) -> tuple[int, int, int]:
    """从 codestream 的 SIZ 段读 (宽, 高, 通道数)，纯标准库。"""
    i = 0
    if data[:12] == JP2_BOX:                     # JP2 容器：跳到 jp2c 盒
        box = data.find(b"jp2c")
        if box < 0:
            raise ValueError("JP2 容器里找不到 jp2c")
        i = box + 4
    if data[i:i + 4] != b"\xff\x4f\xff\x51":     # SOC + SIZ 标记
        raise ValueError("不是有效的 JPEG2000 codestream")
    xsiz, ysiz, xosiz, yosiz = struct.unpack(">IIII", data[i + 8:i + 24])
    csiz = struct.unpack(">H", data[i + 40:i + 42])[0]
    return xsiz - xosiz, ysiz - yosiz, csiz


def extract_jpx_from_pdf(pdf: bytes) -> tuple[bytes, int, int]:
    """从站点单页 PDF 抠出 /JPXDecode 的原始 codestream，返回 (数据, 宽, 高)。

    实测对象形如：
      24 0 obj<</Subtype/Image/Length 304536/Filter/JPXDecode/Name/Im1/
      ColorSpace/DeviceRGB/Width 1755.0/Height 3024.0/Type/XObject>>stream
      <FF 4F FF 51 ...>
      endstream
    /Length 就是纯数据长度，stream 后的 CRLF 不属于数据；宽高逐页不同。
    """
    if not pdf.startswith(b"%PDF"):
        raise ValueError("getPdf 返回的不是 PDF")
    m = re.search(rb"/JPXDecode", pdf)
    if not m:
        raise ValueError("单页 PDF 里没有 /JPXDecode 图像")
    obj = pdf.rfind(b" obj", 0, m.start())
    dic = pdf[max(0, obj + 4):m.end() + 200]
    lm = re.search(rb"/Length\s+(\d+)", dic)
    wm = re.search(rb"/Width\s+([\d.]+)", dic)
    hm = re.search(rb"/Height\s+([\d.]+)", dic)
    if not (lm and wm and hm):
        raise ValueError("图像对象缺少 /Length 或 /Width//Height")
    length = int(lm.group(1))
    s = pdf.find(b"stream", m.end())
    if s < 0:
        raise ValueError("图像对象缺少 stream")
    s += 6
    if pdf[s:s + 2] == b"\r\n":
        s += 2
    elif pdf[s:s + 1] in (b"\n", b"\r"):
        s += 1
    raw = pdf[s:s + length]
    if not is_jpx(raw):
        raise ValueError("截出的字节不是 JPEG2000 codestream")
    w, h = int(float(wm.group(1))), int(float(hm.group(1)))
    if w <= 0 or h <= 0:
        w, h, _ = jpx_dimensions(raw)
    return raw, w, h


_PIL_OK: bool | None = None


def hd_extension() -> str:
    """高清页落盘扩展名：有 Pillow/JPEG2000 就转 .JPG，否则保留无损 .JP2。"""
    global _PIL_OK
    if _PIL_OK is None:
        try:
            from PIL import features
            _PIL_OK = bool(features.check("jpg_2000"))
        except Exception:
            _PIL_OK = False
    return ".JPG" if _PIL_OK else ".JP2"


def jpx_to_jpeg(raw: bytes) -> bytes | None:
    """JPEG2000 -> 高质量 JPEG；Pillow 不可用或图像异常时返回 None。"""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        im.load()
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=95, subsampling=0, optimize=True)
        return buf.getvalue()
    except Exception:
        return None


def jpeg_dimensions(data: bytes) -> tuple[int, int, int]:
    """返回 (宽, 高, 颜色分量数)，支持基线 / 渐进 JPEG。"""
    i = 2
    n = len(data)
    while i < n - 9:
        if data[i] != 0xFF:
            i += 1
            continue
        while i < n and data[i] == 0xFF:
            i += 1
        if i >= n:
            break
        marker = data[i]
        i += 1
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            continue
        if marker in (0xD9, 0xDA):
            break
        if i + 2 > n:
            break
        seglen = struct.unpack(">H", data[i:i + 2])[0]
        if seglen < 2:
            break
        if marker in _SOF:
            h, w = struct.unpack(">HH", data[i + 3:i + 7])
            return w, h, data[i + 7]
        i += seglen
    raise ValueError("无法解析 JPEG 尺寸（文件可能损坏）")


_JPX_CS = {1: "/DeviceGray", 3: "/DeviceRGB", 4: "/DeviceCMYK"}


def image_object(data: bytes) -> tuple[bytes, int, int]:
    """把原始图像字节包成 PDF 图像 XObject，不重新编码。"""
    if is_jpeg(data):
        w, h, comp = jpeg_dimensions(data)
        cs = {1: "/DeviceGray", 3: "/DeviceRGB", 4: "/DeviceCMYK"}.get(comp, "/DeviceRGB")
        filt, extra = "/DCTDecode", f" /ColorSpace {cs} /BitsPerComponent 8"
    elif is_jpx(data):
        w, h, csiz = jpx_dimensions(data)
        filt, extra = "/JPXDecode", f" /ColorSpace {_JPX_CS.get(csiz, '/DeviceRGB')}"
    else:
        raise ValueError(f"无法识别的图像格式：{data[:8].hex()}")
    head = (f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h}"
            f"{extra} /Filter {filt} /Length {len(data)} >>\nstream\n").encode("ascii")
    return head + data + b"\nendstream", w, h


def build_pdf(paths: list[Path], out: Path, dpi: float = 150,
              progress=None) -> Path:
    """纯标准库 PDF：JPEG -> DCTDecode，JPEG2000 -> JPXDecode，原始字节直嵌。"""
    objects: list[bytes | None] = [None, None]      # 1=Catalog, 2=Pages
    kids: list[int] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    for idx, p in enumerate(paths):
        img, w, h = image_object(p.read_bytes())
        pw, ph = round(w * 72.0 / dpi, 2), round(h * 72.0 / dpi, 2)
        img_id = add(img)
        content = f"q {pw} 0 0 {ph} 0 0 cm /Im0 Do Q\n".encode("ascii")
        cont_id = add(b"<< /Length " + str(len(content)).encode() +
                      b" >>\nstream\n" + content + b"endstream")
        page_id = add(
            (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {pw} {ph}] "
             f"/Resources << /XObject << /Im0 {img_id} 0 R >> >> "
             f"/Contents {cont_id} 0 R >>").encode("ascii"))
        kids.append(page_id)
        if progress:
            progress(idx + 1, len(paths), "合成 PDF")

    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = ("<< /Type /Pages /Kids [" + " ".join(f"{k} 0 R" for k in kids) +
                  f"] /Count {len(kids)} >>").encode("ascii")

    buf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for num, body in enumerate(objects, 1):
        offsets.append(len(buf))
        buf += f"{num} 0 obj\n".encode("ascii") + (body or b"") + b"\nendobj\n"
    xref = len(buf)
    buf += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    buf += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        buf += f"{off:010d} 00000 n \n".encode("ascii")
    buf += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode("ascii")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(bytes(buf))
    return out


# --------------------------------------------------------------------------
# 原版 PDF 合并：逐页 getPdf 直接合成，全程不落地任何图片
# --------------------------------------------------------------------------
_OBJ_HEAD = re.compile(rb"(?<![\d])(\d{1,7})\s+(\d{1,5})\s+obj\b")
_PDF_REF = re.compile(rb"(?<![\d])(\d{1,7})\s+(\d{1,5})\s+R(?![\w])")
_STREAM_KW = re.compile(rb"\bstream(?:\r\n|\n|\r)")
_TYPE_PAGE = re.compile(rb"/Type\s*/Page\b")
_PARENT_REF = re.compile(rb"/Parent\s+\d{1,7}\s+\d{1,5}\s+R")


def is_original_pdf(data: bytes) -> bool:
    """站点单页原版 PDF 的完整性校验（越界页是 500 JSON，不是 PDF）。"""
    return (len(data) >= MIN_ORIGINAL_PDF_BYTES and
            data.startswith(b"%PDF") and b"/JPXDecode" in data and
            b"%%EOF" in data[-2048:])


class _PdfObj:
    """一个间接对象：字典字节 + stream 原始字节（stream 绝不参与引用重写）。"""
    __slots__ = ("num", "dic", "stream")

    def __init__(self, num: int, dic: bytes, stream: bytes | None):
        self.num, self.dic, self.stream = num, dic, stream


def _split_pdf_objects(data: bytes) -> list[_PdfObj]:
    """拆出所有间接对象。站点单页 PDF 是线性化 PDF，但用传统 xref、/Length 全是
    直接数字、无 /ObjStm 与 /XRef 流，因此可以按 /Length 精确切流，并跳过
    JPEG2000 二进制里偶然出现的假「N 0 obj」。
    """
    if not data.startswith(b"%PDF"):
        raise ValueError("不是 PDF")
    heads = list(_OBJ_HEAD.finditer(data))
    objs: list[_PdfObj] = []
    i = 0
    while i < len(heads):
        m = heads[i]
        num = int(m.group(1))
        start = m.end()
        nxt = heads[i + 1].start() if i + 1 < len(heads) else len(data)
        region = data[start:nxt]
        st = _STREAM_KW.search(region)
        if st:
            dic = region[:st.start()]
            lm = re.search(rb"/Length\s+(\d{1,10})(?![\d])", dic)
            if not lm:
                raise ValueError(f"对象 {num} 的 /Length 不是直接数字，无法精确切流")
            ds = start + st.end()
            de = ds + int(lm.group(1))
            if de > len(data):
                raise ValueError(f"对象 {num} 的 /Length 超出文件")
            objs.append(_PdfObj(num, dic.strip(), data[ds:de]))
            while i + 1 < len(heads) and heads[i + 1].start() < de:
                i += 1                       # 二进制流里的假对象头
        else:
            em = re.search(rb"\bendobj\b", region)
            objs.append(_PdfObj(num, (region[:em.start()] if em else region).strip(), None))
        i += 1
    return objs


def _merge_pdfs_stdlib(blobs: list[bytes]) -> bytes:
    """零依赖合并：全局重编号所有对象、重写间接引用，把各页挂到一棵新 Pages 树。
    原版 PDF 的字体、ToUnicode、内容流、结构树、JPXDecode 高清图都原样保留。
    """
    groups = [_split_pdf_objects(b) for b in blobs]
    k = sum(len(g) for g in groups)
    root_id, cat_id, null_id = k + 1, k + 2, k + 3
    size = k + 4                            # 含 0 号 free 条目

    bodies: list[tuple[int, bytes]] = []
    page_ids: list[int] = []
    n = 0
    for grp in groups:
        mp = {o.num: n + j + 1 for j, o in enumerate(grp)}
        found = 0
        for o in grp:
            n += 1

            def repl(m, _mp=mp):
                return b"%d 0 R" % _mp.get(int(m.group(1)), null_id)

            dic = _PDF_REF.sub(repl, o.dic)      # 只改字典，stream 原样
            if _TYPE_PAGE.search(o.dic):
                dic = _PARENT_REF.sub(b"/Parent %d 0 R" % root_id, dic)
                page_ids.append(n)
                found += 1
            body = (dic + b"\nstream\n" + o.stream + b"\nendstream"
                    if o.stream is not None else dic)
            bodies.append((n, body))
        if found != 1:
            raise ValueError(f"某个单页 PDF 里有 {found} 个 /Type/Page 对象，结构异常")

    bodies.append((root_id, b"<< /Type /Pages /Kids [" +
                   b" ".join(b"%d 0 R" % p for p in page_ids) +
                   b"] /Count %d >>" % len(page_ids)))
    bodies.append((cat_id, b"<< /Type /Catalog /Pages %d 0 R >>" % root_id))
    bodies.append((null_id, b"null"))       # 悬空引用统一落到这里

    buf = bytearray(b"%PDF-1.6\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0] * size
    for num, body in bodies:
        offsets[num] = len(buf)
        buf += b"%d 0 obj\n" % num + body + b"\nendobj\n"
    xref = len(buf)
    buf += b"xref\n0 %d\n" % size + b"0000000000 65535 f \n"
    for i in range(1, size):
        buf += b"%010d 00000 n \n" % offsets[i]
    buf += (b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (size, cat_id, xref))
    return bytes(buf)


def merge_original_pdfs(blobs: list[bytes]) -> tuple[bytes, str]:
    """返回 (合并后的 PDF 字节, 引擎名)。pypdf 优先，不可用时用内置合并器。"""
    if not blobs:
        raise ValueError("没有可合并的原版 PDF 页")
    try:
        from pypdf import PdfReader, PdfWriter
        w = PdfWriter()
        for b in blobs:
            w.add_page(PdfReader(io.BytesIO(b)).pages[0])
        buf = io.BytesIO()
        w.write(buf)
        data = buf.getvalue()
        if data.startswith(b"%PDF"):
            return data, "pypdf"
    except Exception:
        pass                                  # 缺依赖或站点格式变了，交给内置合并器
    return _merge_pdfs_stdlib(blobs), "内置合并器（纯标准库）"


def merge_engine_name() -> str:
    """给日志用：当前环境会选哪个合并器。"""
    try:
        import pypdf  # noqa: F401
        return "pypdf"
    except ImportError:
        return "内置合并器（纯标准库）"


# --------------------------------------------------------------------------
# 下载任务
# --------------------------------------------------------------------------
@dataclass
class Config:
    out_root: Path
    title: str = ""
    start: int = 1
    end: int = 1
    workers: int = 3
    dpi: float = 150
    original_pdf: bool = True       # 默认：直接合并原版 PDF，不下载任何图片
    keep_pages: bool = False        # 原版模式：是否把每页原版 PDF 另存为 001.pdf…
    hd: bool = True                 # 图片模式：走 getPdf 抠高清原图（False 用旧缩略图）
    make_pdf: bool = True           # 图片模式：是否由图片合成 PDF
    pdf_in_book_dir: bool = False   # 默认 PDF 落在「保存文件夹」根目录，图片在其下书名子目录
    skip_existing: bool = True
    timeout: int = 25
    retries: int = 3
    pause: float = 0.08
    token: str = ""
    proxy: str = ""
    total_pages: int = 0
    auto_fallback: bool = True          # 站点没有原版 PDF 时自动切到图像模式
    capability: str = ""               # 本次探测到的站点能力，写入 manifest


@dataclass
class BookCapability:
    """这本书在服务端实际具备哪些数据（实测，不靠猜测）。"""
    has_pdf: bool = False      # getPdf 单页原版 PDF 可用
    has_xml: bool = False      # getXML OCR 文字层可用
    has_image: bool = False    # getImage 图像可用

    @property
    def label(self) -> str:
        return (f"原版PDF {'✓' if self.has_pdf else '✗'} / "
                f"OCR文字层 {'✓' if self.has_xml else '✗'} / "
                f"图像 {'✓' if self.has_image else '✗'}")

    @property
    def image_only(self) -> bool:
        return self.has_image and not self.has_pdf


def probe_capabilities(http: HttpClient, bid: str, log=None) -> BookCapability:
    """探测这本书的可用数据源；结果按 HttpClient 实例缓存，避免重复请求。

    站点上并非每本书都有全套数据：hwzdt0387 这类书只有 getImage，
    getPdf 返回 500（服务端找不到 PDF 文件）、getXML 返回 400。
    """
    cache = getattr(http, "_caps", None)
    if cache is None:
        cache = {}
        http._caps = cache
    if bid in cache:
        return cache[bid]

    def once(url, ok) -> bool:
        for i in range(2):
            try:
                r = http.get(url)
                if ok(r):
                    return True
                if not 500 <= r.status <= 599:   # 5xx 可能是抖动，重试一次
                    return False
            except Exception:
                pass
            if i == 0:
                time.sleep(0.3)
        return False

    cap = BookCapability(
        has_pdf=once(pdf_url(bid, 1),
                     lambda r: r.status == 200 and is_original_pdf(r.body)),
        has_xml=once(xml_url(bid, 1),
                     lambda r: r.status == 200 and b"<page" in r.body[:600]),
        has_image=once(image_url(bid, 1),
                       lambda r: (r.status == 200 and len(r.body) >= MIN_JPEG_BYTES
                                  and is_jpeg(r.body))),
    )
    cache[bid] = cap
    if log:
        log(f"能力探测：{cap.label}")
    return cap


def apply_capabilities(cfg: Config, cap: BookCapability, log=None) -> Config:
    """按站点实际能力调整配置：没有原版 PDF 的书自动改走图像模式。"""
    def say(msg):
        if log:
            log(msg)

    if cfg.capability == cap.label:
        return cfg          # CLI / GUI 已经按探测结果配置好，别重复打日志
    if (cfg.original_pdf and cfg.auto_fallback
            and not cap.has_pdf and not cap.has_image):
        raise RuntimeError("该书既没有原版 PDF，也没有可用图像："
                           "书号可能有误，或该册需要登录权限")
    if not cfg.auto_fallback or not cap.image_only:
        return replace(cfg, capability=cap.label)
    new = replace(cfg, original_pdf=False, hd=False, capability=cap.label)
    say("注意：这本书服务端没有生成单页原版 PDF，也没有 OCR 文字层，只有图像；"
        "已自动改用「图像模式 / 缩略图」。")
    say("说明：生成的 PDF 不含可搜索文字；清晰度取决于站点图像"
        "（约 369~675×600），站点未提供更高清的源，加参数也无效。")
    return new


@dataclass
class DownloadResult:
    out_dir: Path
    ok: list[int] = field(default_factory=list)
    skipped: list[int] = field(default_factory=list)
    failed: list[int] = field(default_factory=list)
    hd: list[int] = field(default_factory=list)         # 实际拿到高清原图的页（图片模式）
    fallback: list[int] = field(default_factory=list)   # 高清失败、回退缩略图的页（图片模式）
    pdf: Path | None = None
    mode: str = "original_pdf"                          # original_pdf / hd / thumbnail
    pdf_engine: str = ""                                # 原版模式所用的合并器


def _atomic_write(dest: Path, data: bytes):
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, dest)


# --------------------------------------------------------------------------
# 输出路径分配：避免不同书籍 / 不同范围互相覆盖
# --------------------------------------------------------------------------
def _read_manifest(out_dir: Path) -> dict | None:
    try:
        return json.loads((out_dir / "manifest.json").read_text("utf-8"))
    except Exception:
        return None


def _path_conflict(out_dir: Path, pdf_path: Path, book_id: str,
                   start: int, end: int) -> str | None:
    """返回冲突说明；None 表示可以安全写入（含同一本书同一范围的重跑）。"""
    m = _read_manifest(out_dir)
    if m is None:
        if pdf_path.exists() or any(out_dir.glob("0*.*")):
            return "同名目录已有产物但缺少清单"
        return None
    old_id = str(m.get("book_id", ""))
    if old_id and old_id != str(book_id):
        return f"同名目录属于另一本书（book {old_id}）"
    rng = m.get("downloaded_range") or []
    if len(rng) >= 2 and (int(rng[0]) != start or int(rng[-1]) != end):
        return f"同一本书的不同范围（已有 {rng[0]}–{rng[-1]} 页）"
    return None


def allocate_paths(cfg: Config, ref: BookRef) -> tuple[Path, Path, str]:
    """给本次任务分配不与既有产物冲突的 (书名目录, PDF 路径, 提示文字)。

    正常情况沿用《书名》；一旦检测到会被覆盖，自动改用带书号/页码范围的名称，
    前一本书的产物原样保留。同一本书、同一范围的重跑仍写回原路径，
    以便断点续传和覆盖更新。
    """
    base = sanitize_filename(cfg.title or ref.book_id)
    rng = f"{cfg.start}-{cfg.end}"

    def paths(stem: str):
        d = cfg.out_root / stem
        p = (d / f"{stem}.pdf") if cfg.pdf_in_book_dir else (cfg.out_root / f"{stem}.pdf")
        return d, p

    out_dir, pdf_path = paths(base)
    reason = _path_conflict(out_dir, pdf_path, ref.book_id, cfg.start, cfg.end)
    if reason is None:
        return out_dir, pdf_path, ""

    if "不同范围" in reason:
        stems = [f"{base} {rng}页", f"{base}（{ref.book_id}）{rng}页"]
    else:
        stems = [f"{base}（{ref.book_id}）", f"{base}（{ref.book_id}）{rng}页"]
    stems += [f"{base}（{ref.book_id}）({i})" for i in range(2, 50)]

    for stem in stems:
        out_dir, pdf_path = paths(stem)
        if _path_conflict(out_dir, pdf_path, ref.book_id,
                          cfg.start, cfg.end) is None:
            return (out_dir, pdf_path,
                    f"检测到输出名冲突（{reason}）；本次另存为「{stem}」，已有文件保持不变")
    raise RuntimeError("无法分配不冲突的输出路径，请换个保存文件夹或书名")


# --------------------------------------------------------------------------
# 任务计时
# --------------------------------------------------------------------------
def fmt_duration(seconds: float) -> str:
    total = max(0.0, float(seconds))
    if total < 60:
        return f"{total:.1f} 秒" if total < 10 else f"{int(total)} 秒"
    s = int(total)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h} 小时 {m} 分 {sec} 秒"
    return f"{m} 分 {sec} 秒"


def finish_line(started_at: datetime | None, label: str = "完成") -> str:
    """任务结尾的统一时间行：结束时刻 + 总耗时。"""
    now = datetime.now()
    line = f"{label}时间：{now:%Y-%m-%d %H:%M:%S}"
    if started_at is not None:
        line += f" · 耗时 {fmt_duration((now - started_at).total_seconds())}"
    return line


def _valid_cached(dest: Path, hd: bool = False) -> bool:
    """断点续传校验：魔数要对；高清模式还要排除旧的低清缩略图。"""
    try:
        if dest.stat().st_size < MIN_JPEG_BYTES:
            return False
        data = dest.read_bytes()
    except OSError:
        return False
    if is_jpeg(data):
        if not hd:
            return True
        try:
            return jpeg_dimensions(data)[0] >= HD_MIN_WIDTH
        except ValueError:
            return False
    return bool(hd and is_jpx(data))


def _collect_page_files(out_dir: Path, start: int, end: int) -> list[Path]:
    """按页码收集本轮图片；同页只取一张，.JP2（无损高清）优先于 .JPG。"""
    found: dict[int, list[Path]] = {}
    for p in out_dir.iterdir():
        m = re.match(r"(\d+)\.(JPG|JP2)$", p.name, re.I)
        if not m:
            continue
        num = int(m.group(1))
        if start <= num <= end:
            found.setdefault(num, []).append(p)
    out = []
    for num in sorted(found):
        cand = sorted(found[num],
                      key=lambda q: (0 if q.suffix.upper() == ".JP2" else 1, q.name))
        out.append(cand[0])
    return out


def _valid_original_pdf(dest: Path) -> bool:
    """另存的每页原版 PDF 校验：要完整（含高清图 + EOF），才可用于续传。"""
    try:
        if dest.stat().st_size < MIN_ORIGINAL_PDF_BYTES:
            return False
        return is_original_pdf(dest.read_bytes())
    except OSError:
        return False


def download_original_pdf(ref: BookRef, cfg: Config, http: HttpClient,
                          progress=None, log=None,
                          cancel: threading.Event | None = None) -> DownloadResult:
    """原版 PDF 模式：逐页取 getPdf 的单页原版 PDF，在内存里直接合并。

    默认不落地任何中间文件，输出目录只会有《书名.pdf》与 manifest.json；
    指定 keep_pages 时，额外把每页原版 PDF 存成 书名/001.pdf…，便于单页使用
    和断点续传（重跑自动跳过已存在的页）。
    """
    def say(msg):
        if log:
            log(msg)

    def tick(done, total, msg):
        if progress:
            progress(done, total, msg)

    started_at = datetime.now()
    out_dir, pdf_path, note = allocate_paths(cfg, ref)
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = list(range(cfg.start, cfg.end + 1))
    total = len(pages)
    if total <= 0:
        raise ValueError("页码范围为空")
    grand = total + 1                     # 下载 total 步，合并占最后 1 步

    say(f"输出目录：{out_dir}")
    say(f"目标 PDF：{pdf_path}")
    if note:
        say("注意：" + note)
    say(f"下载范围：{cfg.start} – {cfg.end}（共 {total} 页），并发 {cfg.workers}")
    say("工作模式：原版 PDF —— 逐页 getPdf 直接合并，不下载任何图片")
    say(f"原版接口：{ref.hd_template}")
    say(f"合并引擎：{merge_engine_name()}")
    say("中间文件：" + ("每页另存 书名/001.pdf…" if cfg.keep_pages
                        else "不落地，仅在内存中合并"))

    result = DownloadResult(out_dir=out_dir, mode="original_pdf")

    def one(page: int):
        """返回 (status, page, pdf_bytes)；bytes 直接带回内存，不做图片落盘。"""
        dest = out_dir / f"{page:03d}.pdf"
        if cfg.keep_pages and cfg.skip_existing and _valid_original_pdf(dest):
            return "skipped", page, dest.read_bytes()
        for attempt in range(cfg.retries + 1):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            r = http.get(ref.pdf(page))
            if r.status == 200 and is_original_pdf(r.body):
                if cfg.keep_pages:
                    _atomic_write(dest, r.body)
                return "ok", page, r.body
            if attempt < cfg.retries:
                time.sleep(0.5 * (attempt + 1))
        return "failed", page, b""

    ex = ThreadPoolExecutor(max_workers=max(1, cfg.workers))
    cancelled = False
    by_page: dict[int, bytes] = {}
    try:
        futures = {ex.submit(one, p): p for p in pages}
        done = 0
        for fut in as_completed(futures):
            if cancel is not None and cancel.is_set():
                cancelled = True
                break
            page = futures[fut]
            try:
                status, page, blob = fut.result()
            except Cancelled:
                cancelled = True
                break
            except Exception as e:
                status, blob = "failed", b""
                say(f"  第 {page} 页异常：{e}")
            getattr(result, status).append(page)
            if blob:
                by_page[page] = blob
            done += 1
            label = {"ok": "完成", "skipped": "跳过", "failed": "失败"}[status]
            tick(done, grand, f"第 {page} 页 · {label}（原版 PDF）")
    finally:
        ex.shutdown(wait=not cancelled, cancel_futures=cancelled)
    if cancelled:
        raise Cancelled()

    say(f"页面完成：新增 {len(result.ok)} 页，跳过 {len(result.skipped)} 页，失败 {len(result.failed)} 页")
    if result.failed:
        say("失败页：" + ", ".join(str(p) for p in sorted(result.failed)) +
            "；修好后重跑会自动重试这些页")

    blobs = [by_page[p] for p in pages if p in by_page]
    if not blobs:
        say("没有可用的原版页面，跳过合并")
        tick(grand, grand, "完成（无 PDF）")
    else:
        say(f"正在合并原版 PDF（{len(blobs)} 页）…")
        tick(total, grand, "合并原版 PDF")
        data, engine = merge_original_pdfs(blobs)
        _atomic_write(pdf_path, data)
        result.pdf = pdf_path
        result.pdf_engine = engine
        say(f"PDF 已生成：{pdf_path}")
        say(f"合并引擎：{engine}；保留 OCR 文字层与高清原图，体积 {len(data):,} 字节")
        tick(grand, grand, "合并完成")

    manifest = {
        "book_id": ref.book_id,
        "source_url": ref.detail,
        "mode": "original_pdf",
        "quality": "original",
        "capability": cfg.capability,
        "pdf_api_template": ref.hd_template,
        "image_api_template": ref.template,
        "merge_engine": result.pdf_engine,
        "title": cfg.title,
        "total_pages": cfg.total_pages,
        "downloaded_range": [cfg.start, cfg.end],
        "ok": sorted(result.ok),
        "skipped": sorted(result.skipped),
        "failed": sorted(result.failed),
        "pages_saved": bool(cfg.keep_pages),
        "pdf": str(result.pdf) if result.pdf else None,
        "output_stem": out_dir.name,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "elapsed_seconds": round((datetime.now() - started_at).total_seconds(), 1),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8")
    return result


def download_book(ref: BookRef, cfg: Config, http: HttpClient,
                  progress=None, log=None, cancel: threading.Event | None = None) -> DownloadResult:
    """下载指定页、写清单、合成 PDF。默认分流到原版 PDF 模式；图片模式保留旧行为。

    progress(done, total, msg) / log(msg)。

    会先实测这本书的可用数据源；只有图像、没有原版 PDF 时自动降级，
    保证「只有缩略图」的书（如 hwzdt0387）也能正常下载。
    """
    cap = probe_capabilities(http, ref.book_id, log)
    cfg = apply_capabilities(cfg, cap, log)
    if cfg.original_pdf:
        return download_original_pdf(ref, cfg, http, progress, log, cancel)
    return _download_images(ref, cfg, http, progress, log, cancel)


def _download_images(ref: BookRef, cfg: Config, http: HttpClient,
                     progress=None, log=None,
                     cancel: threading.Event | None = None) -> DownloadResult:
    """图片模式（旧行为）：getPdf 抠高清图 / getImage 缩略图，落盘后再合成 PDF。"""
    def say(msg):
        if log:
            log(msg)

    def tick(done, total, msg):
        if progress:
            progress(done, total, msg)

    started_at = datetime.now()
    out_dir, pdf_path, note = allocate_paths(cfg, ref)
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = list(range(cfg.start, cfg.end + 1))
    total = len(pages)
    if total <= 0:
        raise ValueError("页码范围为空")
    # 下载占前半程、PDF 合成占后半程，进度条全程单调递增，不回跳
    grand = total * 2 if cfg.make_pdf else total
    ext = hd_extension() if cfg.hd else ".JPG"
    say(f"输出目录：{out_dir}")
    if cfg.make_pdf:
        say(f"目标 PDF：{pdf_path}")
    if note:
        say("注意：" + note)
    say(f"下载范围：{cfg.start} – {cfg.end}（共 {total} 页），并发 {cfg.workers}")
    say("画质模式：" + ("高清原图 getPdf → " + ext + "（约 1500~1800 px 宽）"
                       if cfg.hd else "缩略图 getImage（约 350~420 px 宽）"))
    if cfg.hd:
        say(f"高清接口：{ref.hd_template}")
        say(f"备用接口：{ref.template}")
        if ext == ".JP2":
            say("当前 Python 没有可用的 Pillow/JPEG2000，图片存为无损 .JP2；"
                "换用装了 Pillow 的 Python 会自动输出 .JPG。")

    result = DownloadResult(out_dir=out_dir,
                            mode="hd" if cfg.hd else "thumbnail")

    def one(page: int):
        """返回 (status, page, dest, source)；source ∈ hd / thumb / fallback / cached / failed。"""
        dest = out_dir / f"{page:03d}{ext}"
        if cfg.skip_existing and _valid_cached(dest, hd=cfg.hd):
            return "skipped", page, dest, "cached"
        for attempt in range(cfg.retries + 1):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            if cfg.hd:
                r = http.get(ref.pdf(page))
                if r.status == 200:
                    try:
                        raw, _w, _h = extract_jpx_from_pdf(r.body)
                        if ext == ".JPG":
                            jpg = jpx_to_jpeg(raw)
                            if jpg:
                                _atomic_write(dest, jpg)
                                return "ok", page, dest, "hd"
                            # 转码意外失败：这一页改存原始 JP2，不丢画质
                            jp2 = out_dir / f"{page:03d}.JP2"
                            _atomic_write(jp2, raw)
                            return "ok", page, jp2, "hd"
                        _atomic_write(dest, raw)
                        return "ok", page, dest, "hd"
                    except ValueError as e:
                        say(f"  第 {page} 页高清解析失败（{e}），改用缩略图")
                # 高清不可用 -> 静默回退到旧的缩略图接口
            t = http.get(ref.image(page))
            if t.status == 200 and is_jpeg(t.body):
                thumb = out_dir / f"{page:03d}.JPG"
                _atomic_write(thumb, t.body)
                return "ok", page, thumb, ("fallback" if cfg.hd else "thumb")
            if attempt < cfg.retries:
                time.sleep(0.5 * (attempt + 1))
        return "failed", page, dest, "failed"

    ex = ThreadPoolExecutor(max_workers=max(1, cfg.workers))
    cancelled = False
    try:
        futures = {ex.submit(one, p): p for p in pages}
        done = 0
        for fut in as_completed(futures):
            if cancel is not None and cancel.is_set():
                cancelled = True
                break
            page = futures[fut]
            try:
                status, page, dest, source = fut.result()
            except Cancelled:
                cancelled = True
                break
            except Exception as e:
                status, dest, source = "failed", None, "failed"
                say(f"  第 {page} 页异常：{e}")
            getattr(result, status).append(page)
            if source == "hd" or (source == "cached" and cfg.hd):
                result.hd.append(page)   # 高清模式能通过续传校验的一定是清晰图
            elif source == "fallback":
                result.fallback.append(page)
            done += 1
            label = {"ok": "完成", "skipped": "跳过", "failed": "失败"}[status]
            tag = (" · 高清" if source == "hd" else
                   " · 回退缩略图" if source == "fallback" else "")
            tick(done, grand, f"第 {page} 页 · {label}{tag}")
    finally:
        ex.shutdown(wait=not cancelled, cancel_futures=cancelled)
    if cancelled:
        raise Cancelled()

    say(f"图片完成：新增 {len(result.ok)} 页，跳过 {len(result.skipped)} 页，失败 {len(result.failed)} 页")
    if cfg.hd:
        say(f"其中高清 {len(result.hd)} 页，回退缩略图 {len(result.fallback)} 页")
    if result.failed:
        say("失败页：" + ", ".join(str(p) for p in sorted(result.failed)))
    if result.fallback:
        say("回退页：" + ", ".join(str(p) for p in sorted(result.fallback)))

    if cfg.make_pdf:
        files = _collect_page_files(out_dir, cfg.start, cfg.end)
        if not files:
            say("没有可用图片，跳过 PDF 合成")
            tick(grand, grand, "完成（无 PDF）")
        else:
            say(f"正在合成 PDF（{len(files)} 页，{cfg.dpi:g} dpi）…")
            build_pdf(files, pdf_path, dpi=cfg.dpi,
                      progress=lambda d, t, m: tick(
                          total + round(d / t * total), grand, f"合成 PDF {d}/{t}"))
            result.pdf = pdf_path
            say(f"PDF 已生成：{pdf_path}")

    manifest = {
        "book_id": ref.book_id,
        "source_url": ref.detail,
        "mode": result.mode,
        "quality": "hd" if cfg.hd else "thumbnail",
        "capability": cfg.capability,
        "merge_engine": None,
        "hd_api_template": ref.hd_template,
        "image_api_template": ref.template,
        "title": cfg.title,
        "total_pages": cfg.total_pages,
        "downloaded_range": [cfg.start, cfg.end],
        "ok": sorted(result.ok),
        "skipped": sorted(result.skipped),
        "failed": sorted(result.failed),
        "hd_pages": sorted(result.hd),
        "fallback_pages": sorted(result.fallback),
        "pdf": str(result.pdf) if result.pdf else None,
        "output_stem": out_dir.name,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "elapsed_seconds": round((datetime.now() - started_at).total_seconds(), 1),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8")
    return result


# --------------------------------------------------------------------------
# 图形界面（tkinter 可选）
# --------------------------------------------------------------------------
try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, scrolledtext
    _HAS_TK = True
except ImportError:                                  # 无 tkinter 时 CLI 仍可用
    tk = ttk = filedialog = messagebox = scrolledtext = None
    _HAS_TK = False

_GuiBase = tk.Frame if _HAS_TK else object

GREEN = "#c8ef00"
GREEN_ACTIVE = "#b6da00"
GREY = "#666666"


def setup_entry_context_menu(entry: tk.Entry):
    """为 Entry 输入框添加右键菜单（剪切、复制、粘贴、全选）并支持 Ctrl+A 全选快捷键。"""
    menu = tk.Menu(entry, tearoff=0)

    def do_cut():
        try:
            if str(entry.cget("state")) in ("readonly", "disabled"):
                return
            if entry.selection_present():
                text = entry.selection_get()
                entry.clipboard_clear()
                entry.clipboard_append(text)
                first = entry.index("sel.first")
                last = entry.index("sel.last")
                entry.delete(first, last)
        except Exception:
            pass

    def do_copy():
        try:
            if entry.selection_present():
                text = entry.selection_get()
                entry.clipboard_clear()
                entry.clipboard_append(text)
        except Exception:
            pass

    def do_paste():
        try:
            if str(entry.cget("state")) in ("readonly", "disabled"):
                return
            text = entry.clipboard_get()
            if not text:
                return
            if entry.selection_present():
                first = entry.index("sel.first")
                last = entry.index("sel.last")
                entry.delete(first, last)
                entry.insert(first, text)
            else:
                entry.insert("insert", text)
        except Exception:
            pass

    def do_select_all(event=None):
        entry.focus_set()
        entry.select_range(0, "end")
        entry.icursor("end")
        return "break"

    menu.add_command(label="剪切", accelerator="Ctrl+X", command=do_cut)
    menu.add_command(label="复制", accelerator="Ctrl+C", command=do_copy)
    menu.add_command(label="粘贴", accelerator="Ctrl+V", command=do_paste)
    menu.add_separator()
    menu.add_command(label="全选", accelerator="Ctrl+A", command=do_select_all)

    def show_popup(event):
        entry.focus_set()
        try:
            if not entry.selection_present():
                index = entry.index(f"@{event.x}")
                entry.icursor(index)
        except Exception:
            pass

        try:
            has_selection = bool(entry.selection_present())
        except Exception:
            has_selection = False

        is_readonly = str(entry.cget("state")) in ("readonly", "disabled")

        try:
            has_clipboard = bool(entry.clipboard_get())
        except Exception:
            has_clipboard = False

        if is_readonly:
            menu.entryconfigure("剪切", state="disabled")
            menu.entryconfigure("粘贴", state="disabled")
        else:
            menu.entryconfigure("剪切", state="normal" if has_selection else "disabled")
            menu.entryconfigure("粘贴", state="normal" if has_clipboard else "disabled")

        menu.entryconfigure("复制", state="normal" if has_selection else "disabled")
        menu.entryconfigure("全选", state="normal" if len(entry.get()) > 0 else "disabled")

        menu.tk_popup(event.x_root, event.y_root)

    entry.bind("<Button-3>", show_popup)
    entry.bind("<Button-2>", show_popup)
    entry.bind("<Control-a>", do_select_all)
    entry.bind("<Control-A>", do_select_all)
    return menu


class App(_GuiBase):
    """按参考图排布：01 链接 / 02 目录 / 03 范围 / 04 进度 + 底部操作。"""

    def __init__(self, master=None):
        super().__init__(master)
        self.q: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.ref: BookRef | None = None
        self.total_pages = 0
        self.task_started_at: datetime | None = None
        self.cap: BookCapability | None = None   # 解析时探测到的站点能力
        self.settings = self._load_settings()
        self._build_ui()
        self.after(80, self._drain)

    # ---------- 设置持久化 ----------
    def _load_settings(self) -> dict:
        defaults = {
            "out_root": str(Path.home() / "Documents" / "gydc_downloads"),
            "workers": 3, "timeout": 25, "retries": 3, "pause": 0.08,
            "dpi": 150, "original_pdf": True, "keep_pages": False,
            "hd": True, "make_pdf": True, "pdf_in_book_dir": False,
            "skip_existing": True, "token": "", "proxy": "",
        }
        try:
            defaults.update(json.loads(SETTINGS_FILE.read_text("utf-8")))
        except Exception:
            pass
        return defaults

    def _save_settings(self):
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(
                json.dumps(self.settings, ensure_ascii=False, indent=2), "utf-8")
        except Exception:
            pass

    # ---------- UI ----------
    def _build_ui(self):
        self.master.title("古医典藏 / PDF 下载器")
        self.master.geometry("1000x780")
        self.master.minsize(920, 700)
        self.configure(bg="white")
        FONT = ("Microsoft YaHei", 10)
        SMALL = ("Microsoft YaHei", 9)

        head = tk.Frame(self, bg="white")
        head.pack(fill="x", padx=18, pady=(10, 4))
        tk.Label(head, text="古医典藏 / PDF 下载器", bg="white",
                 font=("Microsoft YaHei", 19, "bold")).pack(anchor="w")
        tk.Label(head, text="链接解析 · 原版 PDF · 保留 OCR 文字层", bg="white",
                 fg=GREY, font=SMALL).pack(anchor="w", pady=(2, 0))

        def frame(title, parent=None):
            f = tk.LabelFrame(parent or self, text=title, bg="white", bd=1,
                              relief="solid", padx=12, pady=8,
                              font=("Microsoft YaHei", 10, "bold"))
            return f

        # 01 输入书籍链接
        f1 = frame(" 01  输入书籍链接 ")
        f1.pack(fill="x", padx=18, pady=5)
        row = tk.Frame(f1, bg="white")
        row.pack(fill="x")
        self.link_var = tk.StringVar()
        self.link_entry = tk.Entry(row, textvariable=self.link_var, font=FONT, relief="solid", bd=1)
        self.link_entry.pack(side="left", fill="x", expand=True, ipady=5)
        setup_entry_context_menu(self.link_entry)
        self.parse_btn = tk.Button(row, text="解 析", width=8, bg=GREEN,
                                   activebackground=GREEN_ACTIVE, relief="solid", bd=1,
                                   font=("Microsoft YaHei", 10, "bold"),
                                   command=self._on_parse)
        self.parse_btn.pack(side="left", padx=(8, 0), ipady=3)

        row2 = tk.Frame(f1, bg="white")
        row2.pack(fill="x", pady=(8, 0))
        tk.Label(row2, text="书名", bg="white", font=SMALL).pack(side="left")
        self.title_var = tk.StringVar()
        self.title_entry = tk.Entry(row2, textvariable=self.title_var, font=FONT, relief="solid", bd=1,
                                    width=28)
        self.title_entry.pack(side="left", padx=(6, 16), ipady=3)
        setup_entry_context_menu(self.title_entry)
        tk.Label(row2, text="总页数", bg="white", font=SMALL).pack(side="left")
        self.pages_var = tk.StringVar(value="—")
        tk.Label(row2, textvariable=self.pages_var, bg="white",
                 font=("Microsoft YaHei", 10, "bold")).pack(side="left", padx=(6, 0))
        self.title_from = tk.Label(row2, text="", bg="white", fg=GREY, font=SMALL)
        self.title_from.pack(side="left", padx=(12, 0))

        row3 = tk.Frame(f1, bg="white")
        row3.pack(fill="x", pady=(6, 0))
        tk.Label(row3, text="实际接口", bg="white", font=SMALL).pack(side="left")
        self.api_var = tk.StringVar()
        self.api_entry = tk.Entry(row3, textvariable=self.api_var, font=("Consolas", 9), relief="solid", bd=1,
                                  state="readonly", readonlybackground="#fafafa")
        self.api_entry.pack(side="left", fill="x", expand=True, padx=(6, 8), ipady=3)
        setup_entry_context_menu(self.api_entry)
        tk.Button(row3, text="复制", font=SMALL, relief="solid", bd=1,
                  command=self._copy_api).pack(side="left", ipady=2)

        # ---- 02 / 03 并排等高（紧凑），04 独占下方剩余空间 ----
        mid = tk.Frame(self, bg="white")
        mid.pack(fill="x", padx=18, pady=5)

        f2 = frame(" 02  PDF 保存文件夹 ", mid)
        f2.pack(side="left", fill="both", expand=True, padx=(0, 8))
        r2 = tk.Frame(f2, bg="white")
        r2.pack(fill="x")
        self.out_var = tk.StringVar(value=self.settings["out_root"])
        self.out_entry = tk.Entry(r2, textvariable=self.out_var, font=FONT, relief="solid", bd=1)
        self.out_entry.pack(side="left", fill="x", expand=True, ipady=5)
        setup_entry_context_menu(self.out_entry)
        tk.Button(r2, text="选择", font=FONT, relief="solid", bd=1,
                  command=self._choose_dir).pack(side="left", padx=(8, 0), ipady=3)
        tk.Button(r2, text="打开", font=FONT, relief="solid", bd=1,
                  command=self._open_out_dir).pack(side="left", padx=(6, 0), ipady=3)
        self.out_hint = tk.Label(f2, text="", bg="white", fg=GREY, font=SMALL,
                                 anchor="w", justify="left", wraplength=430)
        self.out_hint.pack(fill="x", pady=(7, 0))

        f3 = frame(" 03  下载范围 ", mid)
        f3.pack(side="left", fill="both", expand=True)
        r3a = tk.Frame(f3, bg="white")
        r3a.pack(fill="x")
        self.whole_var = tk.BooleanVar(value=True)
        tk.Checkbutton(r3a, text="整本下载", variable=self.whole_var, bg="white",
                       font=FONT, command=self._toggle_range).pack(side="left")
        self.range_hint = tk.Label(r3a, text="", bg="white", fg=GREY, font=SMALL)
        self.range_hint.pack(side="right")
        r3 = tk.Frame(f3, bg="white")
        r3.pack(fill="x", pady=(6, 0))
        self.range_label = tk.Label(r3, text="固定页码", bg="white", fg=GREY, font=SMALL)
        self.range_label.pack(side="left")
        self.start_var = tk.StringVar(value="1")
        self.end_var = tk.StringVar(value="10")
        self.start_entry = tk.Entry(r3, textvariable=self.start_var, width=6,
                                    font=FONT, relief="solid", bd=1, state="disabled")
        self.start_entry.pack(side="left", padx=(8, 0))
        setup_entry_context_menu(self.start_entry)
        tk.Label(r3, text="至", bg="white", fg=GREY, font=SMALL).pack(side="left", padx=6)
        self.end_entry = tk.Entry(r3, textvariable=self.end_var, width=6,
                                  font=FONT, relief="solid", bd=1, state="disabled")
        self.end_entry.pack(side="left")
        setup_entry_context_menu(self.end_entry)
        self.mode_hint = tk.Label(f3, text="", bg="white", fg=GREY, font=SMALL,
                                  anchor="w", justify="left", wraplength=430)
        self.mode_hint.pack(fill="x", pady=(7, 0))

        # 底部操作栏：先占住窗口底部，避免被 04 的 expand 挤出可视区
        foot = tk.Frame(self, bg="white")
        foot.pack(side="bottom", fill="x", padx=18, pady=(4, 14))
        self.start_btn = tk.Button(foot, text="开始下载", font=FONT,
                                   relief="solid", bd=1, command=self._on_start)
        self.start_btn.pack(side="left", ipadx=10, ipady=4)
        tk.Button(foot, text="设置", font=SMALL, relief="solid", bd=1,
                  command=self._open_settings).pack(side="left", padx=10, ipady=4)
        self.stop_btn = tk.Button(foot, text="停止任务", font=FONT,
                                  relief="solid", bd=1, command=self._on_stop,
                                  state="disabled")
        self.stop_btn.pack(side="right", ipadx=10, ipady=4)
        self.clear_btn = tk.Button(foot, text="清空日志", font=FONT,
                                   relief="solid", bd=1, command=self._on_clear_log)
        self.clear_btn.pack(side="right", padx=(0, 8), ipadx=10, ipady=4)

        # 04 下载进度
        f4 = frame(" 04  下载进度 ")
        f4.pack(fill="both", expand=True, padx=18, pady=5)
        self.status_var = tk.StringVar(value="请粘贴书籍详情页链接，然后点击解析。")
        tk.Label(f4, textvariable=self.status_var, bg="white", fg=GREY,
                 font=SMALL, anchor="w").pack(fill="x", pady=(0, 8))
        self.pbar = ttk.Progressbar(f4, mode="determinate", maximum=100)
        self.pbar.pack(fill="x", pady=(0, 8))
        self.log_box = scrolledtext.ScrolledText(
            f4, height=6, font=("Consolas", 9), relief="solid", bd=1,
            bg="#fcfcfa", wrap="word")
        self.log_box.pack(fill="both", expand=True)
        self.log_box.insert("end", "等待任务开始。\n")
        self.log_box.configure(state="disabled")

        # 任一相关变量变化，实时刷新左栏「本次输出」
        for v in (self.out_var, self.title_var, self.pages_var,
                  self.start_var, self.end_var, self.whole_var):
            v.trace_add("write", lambda *_: self._refresh_preview())
        self._refresh_preview()

    # ---------- 小工具 ----------
    def _log(self, msg: str):
        self.q.put(("log", msg))

    def _toggle_range(self):
        st = "normal" if not self.whole_var.get() else "disabled"
        self.start_entry.configure(state=st)
        self.end_entry.configure(state=st)
        self.range_label.configure(fg="black" if st == "normal" else GREY)
        self._refresh_preview()

    def _refresh_preview(self):
        """实时刷新 02 / 03 里的输出信息，让这两块始终有内容、不留空框。"""
        try:
            raw_title = self.title_var.get().strip()
            title = sanitize_filename(raw_title) or "（未解析）"
            total = self.total_pages or 0
            if self.whole_var.get():
                s, e, count = 1, total, total
                scope = f"1 – {total} 页（整本）" if total else "整本（待解析）"
            else:
                s = int(self.start_var.get() or 1)
                e = int(self.end_var.get() or s)
                count = max(0, e - s + 1)
                scope = f"{s} – {e} 页"
            original = bool(self.settings.get("original_pdf", True))
            hd = bool(self.settings.get("hd", True))
            cap = self.cap
            degraded = cap is not None and cap.image_only
            if degraded:                 # 解析后已实测：这本书只有图像
                original, hd = False, False
            mode = ("原版 PDF · 可搜索文字" if original else
                    ("高清图片 → 合成 PDF" if hd else "缩略图 → 合成 PDF"))
            if degraded:
                mode += " · 站点仅有图像（自动降级）"
            root = Path(self.out_var.get().strip() or self.settings["out_root"])
            folder = root / (title if raw_title else "书名")
            pdf = ((folder / f"{folder.name}.pdf")
                   if bool(self.settings.get("pdf_in_book_dir")) else
                   (root / f"{folder.name}.pdf"))
            note = ("原版 PDF 直接保存在此目录，不落地任何图片。"
                    if original else "图片模式：此目录下另建书名子目录存放图片。")
            if degraded:
                note = "站点无原版 PDF / OCR 文字层；本目录下另建书名子目录存放图像。"
            self.out_hint.configure(text=f"输出文件：{pdf}\n{note}")
            self.range_hint.configure(
                text=(f"共 {total} 页 · 本次 {count} 页" if total else "解析后显示页数"))
            self.mode_hint.configure(text=f"模式：{mode} · 范围 {scope}")
        except (ValueError, OSError, AttributeError):
            pass

    def _open_out_dir(self):
        """在资源管理器里打开当前保存目录（不存在则先创建）。"""
        try:
            p = Path(self.out_var.get().strip() or self.settings["out_root"])
            p.mkdir(parents=True, exist_ok=True)
            os.startfile(str(p))
        except Exception as e:
            self._log(f"打开目录失败：{e}")

    def _choose_dir(self):
        d = filedialog.askdirectory(initialdir=self.out_var.get() or str(Path.home()))
        if d:
            self.out_var.set(d)
            self.settings["out_root"] = d
            self._save_settings()

    def _copy_api(self):
        if not self.api_var.get():
            return
        self.clipboard_clear()
        self.clipboard_append(self.api_var.get())
        self._log("已复制实际接口地址到剪贴板。")

    def _set_busy(self, busy: bool):
        self.busy = busy
        self.parse_btn.configure(state="disabled" if busy else "normal")
        self.start_btn.configure(state="disabled" if busy else "normal")
        self.stop_btn.configure(state="normal" if busy else "disabled")

    # ---------- 解析 ----------
    def _on_parse(self):
        if self.busy:
            return
        raw = self.link_var.get().strip()
        try:
            ref = parse_book_input(raw)
        except ValueError as e:
            messagebox.showwarning("链接无法识别", str(e))
            return
        self.cancel = threading.Event()
        self._set_busy(True)
        self.status_var.set("正在解析链接、识别书名与总页数…")
        self._log(f"输入：{raw}")
        self._log(f"归一化详情页：{ref.detail}")
        use_pdf = bool(self.settings["original_pdf"]) or bool(self.settings["hd"])
        self._log(f"主用接口   ：{ref.template_for(use_pdf)}")
        if bool(self.settings["original_pdf"]):
            self._log("配置模式   ：原版 PDF（逐页取回后直接合并，不下载图片）")
        else:
            self._log("配置模式   ：图片模式 / " +
                      ("高清原图" if bool(self.settings["hd"]) else "缩略图"))
        if use_pdf:
            self._log(f"备用缩略图接口：{ref.template}")
        self._log("正在探测该书在站点上的可用数据源…")

        def work():
            try:
                http = self._make_http()
                cap = probe_capabilities(http, ref.book_id, log=self._log)
                self.q.put(("cap", cap))
                title, source = fetch_title(http, ref.book_id)
                self.q.put(("title", title, source))
                if source == "回退：使用书号":
                    self._log("提示：该书没有封面 OCR 题名，可在上方「书名」栏手动填写。")
                total = detect_total_pages(http, ref.book_id, log=self._log,
                                           cancel=self.cancel)
                self.q.put(("parsed", ref, title, source, total))
            except Cancelled:
                self.q.put(("cancelled",))
            except Exception as e:
                self.q.put(("error", f"解析失败：{e}"))
        threading.Thread(target=work, daemon=True).start()

    def _on_start(self):
        if self.busy:
            return
        if self.ref is None:
            messagebox.showinfo("请先解析", "请先粘贴链接并点击「解析」，确认书名与总页数。")
            return
        try:
            current_id = parse_book_input(self.link_var.get().strip()).book_id
        except ValueError:
            current_id = ""
        if current_id != self.ref.book_id:
            messagebox.showinfo("链接已变化", "链接与上次解析的不同，请先重新点击「解析」。")
            return
        try:
            if self.whole_var.get():
                start, end = 1, self.total_pages
            else:
                start = int(self.start_var.get())
                end = int(self.end_var.get())
        except ValueError:
            messagebox.showwarning("页码有误", "请输入有效的起止页码。")
            return
        if start < 1 or end < start:
            messagebox.showwarning("页码有误", "页码范围应为 1 ≤ 起始 ≤ 结束。")
            return
        if self.total_pages and end > self.total_pages:
            if not messagebox.askyesno("超出总页数",
                                       f"该书共 {self.total_pages} 页，结束页 {end} 超出范围。\n是否继续？"):
                return
        title = sanitize_filename(self.title_var.get().strip()) or self.ref.book_id
        out_root = Path(self.out_var.get().strip())
        cfg = Config(
            out_root=out_root, title=title, start=start, end=end,
            workers=int(self.settings["workers"]),
            dpi=float(self.settings["dpi"]),
            original_pdf=bool(self.settings["original_pdf"]),
            keep_pages=bool(self.settings["keep_pages"]),
            hd=bool(self.settings["hd"]),
            make_pdf=bool(self.settings["make_pdf"]),
            pdf_in_book_dir=bool(self.settings["pdf_in_book_dir"]),
            skip_existing=bool(self.settings["skip_existing"]),
            timeout=int(self.settings["timeout"]),
            retries=int(self.settings["retries"]),
            pause=float(self.settings["pause"]),
            token=self.settings["token"], proxy=self.settings["proxy"],
            total_pages=self.total_pages,
        )
        cap = self.cap
        if cap is not None:
            cfg = replace(cfg, capability=cap.label)
            if cap.image_only:
                cfg = replace(cfg, original_pdf=False, hd=False)
                self._log("注意：该书只有图像，已自动改用「图像模式 / 缩略图」；"
                          "生成的 PDF 不含可搜索文字。")
        self.settings["out_root"] = str(out_root)
        self._save_settings()
        self.cancel = threading.Event()
        self.task_started_at = datetime.now()
        self._set_busy(True)
        self.pbar["value"] = 0
        self.status_var.set("0% · 准备下载")
        self._log(f"开始任务：{self.task_started_at:%Y-%m-%d %H:%M:%S} · "
                  f"《{title}》 第 {start}–{end} 页 -> {out_root}")
        if cfg.original_pdf:
            self._log("模式：原版 PDF —— 直接合并站点单页原版 PDF，不下载任何图片")
            self._log(f"合并引擎：{merge_engine_name()}" +
                      ("；每页另存 001.pdf…" if cfg.keep_pages else "；不落地中间文件"))
        else:
            self._log("模式：图片下载 —— " +
                      ("高清原图（getPdf 内嵌 JPEG2000）" if cfg.hd
                       else "缩略图（getImage，旧版行为）"))
            if not cfg.make_pdf:
                self._log("提示：未勾选「图片模式：合成 PDF」，本次只下载图片。")

        def work():
            try:
                http = self._make_http()
                res = download_book(
                    self.ref, cfg, http,
                    progress=lambda d, t, m: self.q.put(("progress", d, t, m)),
                    log=self._log, cancel=self.cancel)
                self.q.put(("done", res, cfg))
            except Cancelled:
                self.q.put(("cancelled",))
            except Exception as e:
                self.q.put(("error", f"下载失败：{e}\n{traceback.format_exc(limit=3)}"))
        threading.Thread(target=work, daemon=True).start()

    def _on_stop(self):
        self.cancel.set()
        self._log("已请求停止任务…")

    def _on_clear_log(self):
        try:
            self.log_box.configure(state="normal")
            self.log_box.delete("1.0", "end")
            self.log_box.insert("end", "日志已清空。\n")
            self.log_box.configure(state="disabled")
            self.log_box.see("end")
        except Exception:
            pass

    def _make_http(self) -> HttpClient:
        return HttpClient(
            timeout=int(self.settings["timeout"]),
            retries=int(self.settings["retries"]),
            pause=float(self.settings["pause"]),
            token=self.settings["token"], proxy=self.settings["proxy"],
            cancel=self.cancel)

    # ---------- 队列 -> 主线程 ----------
    def _drain(self):
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "log":
                    self.log_box.configure(state="normal")
                    self.log_box.insert("end", item[1] + "\n")
                    if int(self.log_box.index("end-1c").split(".")[0]) > 1500:
                        self.log_box.delete("1.0", "500.0")
                    self.log_box.see("end")
                    self.log_box.configure(state="disabled")
                elif kind == "cap":
                    self.cap = item[1]
                    if self.cap.image_only:
                        self._log("提示：这本书只有图像，没有原版 PDF / OCR 文字层，"
                                  "下载时会自动改用图像模式。")
                    self._refresh_preview()
                elif kind == "title":
                    self.title_var.set(item[1])
                    self.title_from.configure(text=f"（{item[2]}，可修改）")
                elif kind == "progress":
                    _, done, total, msg = item
                    pct = done * 100.0 / total if total else 0
                    self.pbar["value"] = pct
                    self.status_var.set(f"{pct:.0f}% · {msg}")
                elif kind == "parsed":
                    _, ref, title, source, total = item
                    self.ref, self.total_pages = ref, total
                    self.title_var.set(title)
                    self.title_from.configure(text=f"（{source}，可修改）")
                    self.pages_var.set(str(total))
                    use_pdf = (bool(self.settings["original_pdf"]) or
                               bool(self.settings["hd"]))
                    if self.cap is not None and self.cap.image_only:
                        use_pdf = False
                    self.api_var.set(ref.template_for(use_pdf))
                    self.end_var.set(str(total))
                    self.status_var.set(f"解析完成：《{title}》 共 {total} 页，可点击「开始下载 PDF」。")
                    self._refresh_preview()
                    self._log(f"书名：{title}（{source}）")
                    self._set_busy(False)
                elif kind == "done":
                    _, res, cfg = item
                    self.pbar["value"] = 100
                    msg = (f"完成 · 新增 {len(res.ok)} 页 / 跳过 {len(res.skipped)} 页 / "
                           f"失败 {len(res.failed)} 页")
                    self.status_var.set(msg)
                    self._log(msg)
                    if res.pdf:
                        self._log(f"PDF：{res.pdf}" +
                                  (f"（{res.pdf_engine}）" if res.pdf_engine else ""))
                    end_line = finish_line(self.task_started_at)
                    self._log(f"目录：{res.out_dir}")
                    self._log(end_line)
                    self._set_busy(False)
                    messagebox.showinfo("任务完成",
                                        msg + f"\n\n输出目录：\n{res.out_dir}\n\n" + end_line)
                elif kind == "cancelled":
                    self.status_var.set("已停止 · 已下载的文件保留，可重新开始续传")
                    self._log("任务已停止（已下载文件保留，下次自动跳过）。")
                    self._log(finish_line(self.task_started_at, "中止"))
                    self._set_busy(False)
                elif kind == "error":
                    self.status_var.set("出错 · 详见日志")
                    self._log(item[1])
                    self._log(finish_line(self.task_started_at, "出错"))
                    self._set_busy(False)
                    messagebox.showerror("出错了", item[1].splitlines()[0])
        except queue.Empty:
            pass
        self.after(80, self._drain)

    # ---------- 设置弹窗 ----------
    def _open_settings(self):
        win = tk.Toplevel(self)
        win.title("设置")
        win.geometry("520x560")
        win.configure(bg="white")
        win.transient(self.winfo_toplevel())
        FONT = ("Microsoft YaHei", 10)
        SMALL = ("Microsoft YaHei", 9)
        fields = [
            ("并发数", "workers", "同时下载几页；站点不稳时调成 1~2"),
            ("超时(秒)", "timeout", ""),
            ("失败重试", "retries", ""),
            ("请求间隔(秒)", "pause", "温和一点，避免给站点压力"),
            ("PDF DPI", "dpi", "页面物理尺寸，数值越大页面越小"),
            ("Authorization", "token", "可选：填登录后抓到的 token，用于解锁元数据/更多页"),
            ("代理", "proxy", "可选，如 http://127.0.0.1:7890"),
        ]
        vars_: dict[str, tk.StringVar] = {}
        for i, (label, key, hint) in enumerate(fields):
            tk.Label(win, text=label, bg="white", font=FONT, anchor="w").grid(
                row=i, column=0, sticky="w", padx=16, pady=6)
            v = tk.StringVar(value=str(self.settings[key]))
            ent = tk.Entry(win, textvariable=v, font=FONT, relief="solid", bd=1,
                           show="*" if key == "token" else "")
            ent.grid(row=i, column=1, sticky="ew", padx=8, pady=6)
            setup_entry_context_menu(ent)
            vars_[key] = v
            if hint:
                tk.Label(win, text=hint, bg="white", fg=GREY, font=SMALL,
                         anchor="w").grid(row=i, column=2, sticky="w", padx=6)
        checks = [
            ("直接获取原版 PDF（默认；取消才下载图片）", "original_pdf"),
            ("原版模式：另存每页原版 PDF（001.pdf…，便于续传）", "keep_pages"),
            ("图片模式：使用高清原图（取消则回旧缩略图）", "hd"),
            ("图片模式：由图片合成 PDF", "make_pdf"),
            ("PDF 放在书名目录内", "pdf_in_book_dir"),
            ("跳过已完成的页（断点续传）", "skip_existing"),
        ]
        bools: dict[str, tk.BooleanVar] = {}
        base = len(fields)
        for i, (label, key) in enumerate(checks):
            v = tk.BooleanVar(value=bool(self.settings[key]))
            tk.Checkbutton(win, text=label, variable=v, bg="white", font=FONT).grid(
                row=base + i, column=0, columnspan=3, sticky="w", padx=16, pady=2)
            bools[key] = v
        win.columnconfigure(1, weight=1)

        def save():
            try:
                for key, v in vars_.items():
                    val = v.get().strip()
                    if key in ("workers", "timeout", "retries"):
                        self.settings[key] = max(1, int(val))
                    elif key in ("pause", "dpi"):
                        self.settings[key] = float(val)
                    else:
                        self.settings[key] = val
                for key, v in bools.items():
                    self.settings[key] = bool(v.get())
                self.settings["workers"] = min(8, self.settings["workers"])
                self._save_settings()
                self._refresh_preview()
                self._log("设置已保存。")
                win.destroy()
            except ValueError:
                messagebox.showwarning("格式有误", "数字项请填写有效数值。", parent=win)

        tk.Button(win, text="保存", bg=GREEN, activebackground=GREEN_ACTIVE,
                  font=("Microsoft YaHei", 10, "bold"), relief="solid", bd=1,
                  command=save).grid(row=base + len(checks) + 1, column=1,
                                     sticky="e", padx=8, pady=16, ipadx=16, ipady=3)


# --------------------------------------------------------------------------
# 命令行模式
# --------------------------------------------------------------------------
def run_cli(args) -> int:
    started_at = datetime.now()

    def log(msg):
        print(msg, flush=True)

    try:
        ref = parse_book_input(args.link)
    except ValueError as e:
        print("错误：", e, file=sys.stderr)
        return 2
    log(f"输入       : {ref.raw}")
    log(f"归一化链接 : {ref.detail}")
    http = HttpClient(timeout=args.timeout, retries=args.retries, pause=args.pause,
                      token=args.token, proxy=args.proxy)
    cap = probe_capabilities(http, ref.book_id, log=log)

    image_mode = bool(args.images or args.low_res or args.no_pdf)
    original = not image_mode
    hd = not args.low_res
    make_pdf = not args.no_pdf
    auto_ok = not args.no_auto_fallback
    if auto_ok and cap.image_only and original:
        original, image_mode = False, True
        log("注意       : 该书没有单页原版 PDF / OCR 文字层，只有图像，"
            "已自动改用「图像模式 / 缩略图」")
        log("说明       : 生成的 PDF 不含可搜索文字；站点未提供更高清的图源。")
    if auto_ok and cap.image_only:
        hd = False                      # 没有 getPdf，别让每页再白跑一次 500
    use_pdf = original or hd
    log(f"主用接口   : {ref.template_for(use_pdf)}")
    if use_pdf:
        log(f"备用接口   : {ref.template}")
    if original:
        log("工作模式   : 原版 PDF —— 逐页 getPdf 直接合并，不下载任何图片")
        log(f"合并引擎   : {merge_engine_name()}")
    else:
        log("工作模式   : 图片下载 —— " +
            ("高清原图 getPdf → " + hd_extension() if hd else "缩略图 getImage"))

    title = args.title or fetch_title(http, ref.book_id)[0]
    log(f"书名       : {title}")
    if not args.title and not cap.has_xml:
        log("提示       : 该书无封面 OCR 题名，已用书号代替；可用 --title 指定书名。")
    total = detect_total_pages(http, ref.book_id, log=log,
                               use_cache=not args.no_cache)
    log(f"总页数     : {total}")

    if args.pages:
        m = re.fullmatch(r"\s*(\d+)\s*[-~:]\s*(\d+)\s*", args.pages)
        if not m:
            print("错误：--pages 形如 1-10", file=sys.stderr)
            return 2
        start, end = int(m.group(1)), int(m.group(2))
    elif args.all:
        start, end = 1, total
    else:
        start, end = args.start, min(args.end, total)
    if start < 1 or end < start:
        print("错误：页码范围无效", file=sys.stderr)
        return 2

    def prog(done, n, msg):
        if done == n or done % 10 == 0:
            log(f"  [{done}/{n}] {msg}")

    cfg = Config(out_root=Path(args.out), title=title, start=start, end=end,
                 workers=args.workers, dpi=args.dpi,
                 original_pdf=original, keep_pages=args.keep_pages,
                 hd=hd, make_pdf=make_pdf,
                 pdf_in_book_dir=args.pdf_in_book_dir,
                 skip_existing=not args.force,
                 timeout=args.timeout, retries=args.retries, pause=args.pause,
                 token=args.token, proxy=args.proxy, total_pages=total,
                 auto_fallback=auto_ok, capability=cap.label)
    try:
        res = download_book(ref, cfg, http, progress=prog, log=log)
    except Cancelled:
        log(finish_line(started_at, "中止"))
        return 1
    except Exception as e:
        print("失败：", e, file=sys.stderr)
        traceback.print_exc()
        log(finish_line(started_at, "出错"))
        return 1
    log(f"\n完成：新增 {len(res.ok)} / 跳过 {len(res.skipped)} / 失败 {len(res.failed)}")
    log(f"目录：{res.out_dir}")
    if res.pdf:
        log(f"PDF ：{res.pdf}" +
            (f"（{res.pdf_engine}）" if res.pdf_engine else ""))
    log(finish_line(started_at))
    return 0 if not res.failed else 3


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="古医典藏 / PDF 下载器（不传 --cli 则打开图形界面）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("用法")[-1])
    p.add_argument("--cli", action="store_true", help="使用命令行模式")
    p.add_argument("link", nargs="?", help="详情页链接或 bookId（命令行模式必填）")
    p.add_argument("-o", "--out", default=str(Path.home() / "Documents" / "gydc_downloads"),
                   help="保存根目录，其下自动建以书名命名的子目录")
    p.add_argument("--all", action="store_true", help="下载整本")
    p.add_argument("--pages", help="页码范围，如 1-10")
    p.add_argument("--start", type=int, default=1, help="起始页（默认 1）")
    p.add_argument("--end", type=int, default=10, help="结束页（默认 10）")
    p.add_argument("--title", help="手动指定书名（跳过自动识别）")
    p.add_argument("--workers", type=int, default=3, help="并发数，默认 3")
    p.add_argument("--dpi", type=float, default=150,
                   help="图片模式：由图片合成 PDF 的 DPI，默认 150")
    p.add_argument("--images", action="store_true",
                   help="改用图片模式（默认直接获取并合并原版 PDF，不下载图片）")
    p.add_argument("--keep-pages", action="store_true",
                   help="原版 PDF 模式：另存每页原版 PDF 为 书名/001.pdf…（便于续传与单页使用）")
    p.add_argument("--low-res", action="store_true",
                   help="图片模式：改用旧的 getImage 缩略图源")
    p.add_argument("--no-pdf", action="store_true",
                   help="图片模式：只下载图片不合成 PDF（传入即切到图片模式）")
    p.add_argument("--pdf-in-book-dir", action="store_true",
                   help="PDF 放到书名子目录内（默认放在保存根目录）")
    p.add_argument("--force", action="store_true", help="不跳过已完成的页，强制重下")
    p.add_argument("--no-cache", action="store_true", help="忽略页数缓存，重新探测")
    p.add_argument("--no-auto-fallback", action="store_true",
                   help="关闭自动降级：即使探测到该书没有原版 PDF，也强制按原设定模式执行")
    p.add_argument("--timeout", type=int, default=25)
    p.add_argument("--retries", type=int, default=3)
    p.add_argument("--pause", type=float, default=0.08)
    p.add_argument("--token", default="", help="可选：登录后抓到的 Authorization token")
    p.add_argument("--proxy", default="", help="可选：http://127.0.0.1:7890")
    p.add_argument("--print-api", action="store_true", help="只打印解析出的真实接口地址后退出")
    return p


def main() -> int:
    args = build_parser().parse_args()
    if args.cli or args.print_api:
        if not args.link:
            print("错误：命令行模式需要提供链接或 bookId", file=sys.stderr)
            return 2
        if args.print_api:
            ref = parse_book_input(args.link)
            print(ref.detail)
            print(ref.hd_template)      # 原版 PDF / 高清主源
            print(ref.template)         # 缩略图备用源
            return 0
        return run_cli(args)
    if not _HAS_TK:
        print("当前 Python 未安装 tkinter，无法打开图形界面。\n"
              "请改用系统 Python 运行，或使用命令行模式：\n"
              f'  {sys.executable} "{os.path.abspath(__file__)}" --cli "<链接>" --all',
              file=sys.stderr)
        return 2
    root = tk.Tk()
    app = App(root)
    app.pack(fill="both", expand=True)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
