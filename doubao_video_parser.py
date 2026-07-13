"""
Python port of the video parsing part of doubao-downloader.

Workflow:
1. Open Doubao with DrissionPage and wait for you to scan/login.
2. Inject a JSON.parse hook into the page to collect video creation records.
3. Resolve each video vid to a downloadable main_url through Doubao's own
   homepage -> node_info -> get_download_info API chain.
4. Download the resolved no-watermark mp4 files.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

import requests
from DrissionPage import ChromiumOptions, ChromiumPage


BASE_URL = "https://www.doubao.com/chat/"
COMMON_QUERY = (
    "aid=497858&device_platform=web&samantha_web=1&use-olympus-account=1"
    "&version_code=20800&pkg_type=release_version"
)
GET_VIDEO_INFO_URL = f"/samantha/aispace/get_download_info?{COMMON_QUERY}"
GET_NODE_INFO_URL = f"/samantha/aispace/node_info?{COMMON_QUERY}"
HOME_PAGE_URL = f"/samantha/aispace/homepage?{COMMON_QUERY}"


CAPTURE_JS = r"""
(() => {
  if (window.__doubaoVideoCaptorInstalled) return;
  window.__doubaoVideoCaptorInstalled = true;
  window.__doubaoVideoRecords = window.__doubaoVideoRecords || [];
  window.__doubaoVideoRecordKeys = window.__doubaoVideoRecordKeys || {};

  function findAllKeysInJson(obj, key) {
    const results = [];
    function search(current) {
      if (current && typeof current === 'object') {
        if (!Array.isArray(current) && Object.prototype.hasOwnProperty.call(current, key)) {
          results.push(current[key]);
        }
        const items = Array.isArray(current) ? current : Object.values(current);
        for (const item of items) search(item);
      }
    }
    search(obj);
    return results;
  }

  function extractTtsContentText(ttsContent) {
    if (!ttsContent) return '';
    try {
      const parsed = JSON.parse(ttsContent);
      return parsed && parsed.text ? parsed.text : String(ttsContent);
    } catch (_) {
      return String(ttsContent);
    }
  }

  function pushRecord(baseInfo, creation) {
    if (!creation || !creation.video || !creation.video.vid) return;
    const video = creation.video;
    const cover = video.cover || {};
    const record = {
      vid: video.vid,
      key: cover.key || String(video.vid),
      cover_url: cover.image_thumb && cover.image_thumb.url || '',
      prompt: video.gen_params && video.gen_params.prompt || '',
      conversation_id: baseInfo.conversation_id || '',
      message_id: baseInfo.message_id || '',
      index_in_conv: baseInfo.index_in_conv || '',
      bot_reply_message_id: baseInfo.bot_reply_message_id || '',
      tts_content: baseInfo.tts_content || '',
      create_time: baseInfo.create_time || ''
    };
    const dedupeKey = [record.message_id, record.vid, record.key].join(':');
    if (window.__doubaoVideoRecordKeys[dedupeKey]) return;
    window.__doubaoVideoRecordKeys[dedupeKey] = true;
    window.__doubaoVideoRecords.push(record);
  }

  function extractCreations(creationsArray, baseInfo) {
    if (!Array.isArray(creationsArray)) return;
    creationsArray.forEach((creations) => {
      if (!Array.isArray(creations)) return;
      creations.forEach((creation) => pushRecord(baseInfo || {}, creation));
    });
  }

  const originParse = JSON.parse;
  window.__doubaoOriginParse = window.__doubaoOriginParse || originParse;
  JSON.parse = function(text, reviver) {
    const jsonData = originParse.call(this, text, reviver);
    try {
      if (typeof text !== 'string' || !text.includes('creations')) return jsonData;

      const messageList = findAllKeysInJson(jsonData, 'messages');
      if (messageList.length === 0 && jsonData.message_id) {
        extractCreations(findAllKeysInJson(jsonData, 'creations'), {
          message_id: jsonData.message_id
        });
      } else {
        messageList.forEach((messages) => {
          if (!Array.isArray(messages)) return;
          messages.forEach((message) => {
            const baseInfo = {
              index_in_conv: Number(message.index_in_conv || 0),
              bot_reply_message_id: message.bot_reply_message_id || '',
              tts_content: extractTtsContentText(message.tts_content),
              conversation_id: message.conversation_id || '',
              message_id: message.message_id || '',
              create_time: message.create_time ? Number(message.create_time) * 1000 : ''
            };
            extractCreations(findAllKeysInJson(message, 'creations'), baseInfo);
          });
        });
      }
    } catch (err) {
      console.warn('[doubao-video-parser] capture error:', err);
    }
    return jsonData;
  };
})();
"""


def safe_filename(value: str, max_len: int = 140) -> str:
    value = value.strip() or "doubao_video"
    value = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", value)
    value = re.sub(r"\s+", " ", value).strip(" ._")
    return (value[:max_len].strip(" ._") or "doubao_video")


def make_page(profile_dir: Path | None) -> ChromiumPage:
    options = ChromiumOptions()
    if profile_dir:
        profile_dir.mkdir(parents=True, exist_ok=True)
        options.set_user_data_path(str(profile_dir))
        options.set_user("Default")
    options.set_argument("--disable-blink-features", "AutomationControlled")
    page = ChromiumPage(options)
    page.add_init_js(CAPTURE_JS)
    return page


def browser_post(page: ChromiumPage, url: str, body: dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
    token = uuid.uuid4().hex
    body_text = json.dumps(body or {}, ensure_ascii=False)
    js = r"""
      const token = arguments[0];
      const url = arguments[1];
      const bodyText = arguments[2];
      window.__doubaoPyBridge = window.__doubaoPyBridge || {};
      window.__doubaoPyBridge[token] = { pending: true };
      fetch(url, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: bodyText
      }).then(async (res) => {
        const text = await res.text();
        let data = null;
        try { data = JSON.parse(text); } catch (_) {}
        window.__doubaoPyBridge[token] = {
          pending: false,
          ok: res.ok,
          status: res.status,
          statusText: res.statusText,
          data,
          text
        };
      }).catch((err) => {
        window.__doubaoPyBridge[token] = {
          pending: false,
          ok: false,
          error: String(err && err.message || err)
        };
      });
    """
    page.run_js(js, token, url, body_text)

    deadline = time.time() + timeout
    while time.time() < deadline:
        result = page.run_js(
            "return window.__doubaoPyBridge && window.__doubaoPyBridge[arguments[0]];",
            token,
        )
        if result and not result.get("pending"):
            if not result.get("ok"):
                raise RuntimeError(
                    f"POST {url} failed: {result.get('status')} {result.get('statusText')}"
                    f" {result.get('error') or result.get('text') or ''}"
                )
            data = result.get("data")
            if isinstance(data, dict) and data.get("code") not in (None, 0):
                raise RuntimeError(f"POST {url} API error: {data.get('message') or data}")
            return data
        time.sleep(0.2)
    raise TimeoutError(f"POST {url} timed out")


def get_home_creation_id(page: ChromiumPage) -> str:
    data = browser_post(page, HOME_PAGE_URL)
    for child in data.get("data", {}).get("children", []) or []:
        if child.get("name") == "我的创作" and child.get("id"):
            return str(child["id"])
    raise RuntimeError("没有从 homepage 接口找到“我的创作”的 id。")


def get_node_id(page: ChromiumPage, creation_id: str, vid: str, size: int = 200) -> str:
    data = browser_post(
        page,
        GET_NODE_INFO_URL,
        {
            "node_id": creation_id,
            "need_full_path": True,
            "size": size,
            "sort_param": {
                "need_sort_config": True,
                "sort_order": 1,
                "sort_type": 0,
            },
        },
    )
    for child in data.get("data", {}).get("children", []) or []:
        if str(child.get("key")) == str(vid) and child.get("id"):
            return str(child["id"])
    raise RuntimeError(f"没有在“我的创作”最近 {size} 条里找到 vid={vid} 的 node_id。")


def get_video_url(page: ChromiumPage, creation_id: str, vid: str) -> str:
    node_id = get_node_id(page, creation_id, vid)
    data = browser_post(page, GET_VIDEO_INFO_URL, {"requests": [{"node_id": node_id}]})
    main_url = (
        data.get("data", {})
        .get("download_infos", [{}])[0]
        .get("main_url")
    )
    if not main_url:
        raise RuntimeError(f"vid={vid} 未返回 main_url。")
    return str(main_url)


def collect_records(page: ChromiumPage, seconds: int) -> list[dict[str, Any]]:
    last_count = -1
    deadline = time.time() + seconds
    while time.time() < deadline:
        records = page.run_js("return window.__doubaoVideoRecords || [];") or []
        count = len(records)
        if count != last_count:
            print(f"[capture] 已捕获视频：{count} 个")
            last_count = count
        time.sleep(1)

    records = page.run_js("return window.__doubaoVideoRecords || [];") or []
    deduped: dict[str, dict[str, Any]] = {}
    for item in records:
        key = str(item.get("vid") or "")
        if key and key not in deduped:
            deduped[key] = item
    return list(deduped.values())


def download_file(url: str, path: Path, user_agent: str = "") -> None:
    headers = {
        "Referer": "https://www.doubao.com/",
    }
    if user_agent:
        headers["User-Agent"] = user_agent

    with requests.get(url, headers=headers, stream=True, timeout=60) as response:
        response.raise_for_status()
        tmp_path = path.with_suffix(path.suffix + ".part")
        with tmp_path.open("wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
        tmp_path.replace(path)


def build_name(record: dict[str, Any], index: int) -> str:
    title = record.get("tts_content") or record.get("prompt") or record.get("message_id") or record.get("vid")
    prefix = f"{index:03d}"
    message_id = str(record.get("message_id") or "")[-8:]
    stem = safe_filename(f"{prefix}_{title}_{message_id}".strip("_"))
    return f"{stem}.mp4"


def save_urls(records: list[dict[str, Any]], path: Path) -> None:
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="用 DrissionPage 解析并下载豆包无水印视频。")
    parser.add_argument("--url", default=BASE_URL, help="打开的豆包页面，默认 https://www.doubao.com/chat/")
    parser.add_argument("--out", default="videos", help="视频保存目录，默认当前脚本目录下 videos")
    parser.add_argument("--profile", default=".drission_profile", help="浏览器用户数据目录，用于保留扫码登录态")
    parser.add_argument("--capture-seconds", type=int, default=20, help="登录/刷新后自动捕获页面数据的秒数")
    parser.add_argument("--no-refresh", action="store_true", help="扫码后不自动刷新页面")
    parser.add_argument("--urls-only", action="store_true", help="只解析并保存 main_url，不下载 mp4")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    out_dir = (script_dir / args.out).resolve() if not Path(args.out).is_absolute() else Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    profile_dir = (script_dir / args.profile).resolve() if args.profile else None

    page = make_page(profile_dir)
    print("[open] 正在打开豆包页面...")
    page.get(args.url)
    input("[login] 请在打开的浏览器里扫码/确认登录，并打开含有视频创作的对话或创作页。完成后回到这里按 Enter：")

    if not args.no_refresh:
        print("[capture] 正在刷新页面，让初始化脚本从页面接口响应里捕获视频 vid...")
        page.refresh()
        time.sleep(2)

    records = collect_records(page, args.capture_seconds)
    if not records:
        print("[empty] 没捕获到视频。请在浏览器里滚动/打开对应对话后，再运行一次或加大 --capture-seconds。")
        return 2

    print(f"[resolve] 准备解析 {len(records)} 个视频地址...")
    user_agent = page.run_js("return navigator.userAgent;") or ""
    creation_id = get_home_creation_id(page)
    resolved: list[dict[str, Any]] = []

    for index, record in enumerate(records, start=1):
        vid = str(record.get("vid") or "")
        try:
            main_url = get_video_url(page, creation_id, vid)
            record["main_url"] = main_url
            resolved.append(record)
            print(f"[resolve] {index}/{len(records)} vid={vid} OK")
        except Exception as exc:
            record["error"] = str(exc)
            print(f"[resolve] {index}/{len(records)} vid={vid} FAILED: {exc}")

    save_urls(resolved, out_dir / "doubao_video_urls.json")
    if args.urls_only:
        print(f"[done] 已保存解析结果：{out_dir / 'doubao_video_urls.json'}")
        return 0

    for index, record in enumerate(resolved, start=1):
        url = record.get("main_url")
        if not url:
            continue
        name = build_name(record, index)
        target = out_dir / name
        if target.exists():
            print(f"[skip] 已存在：{target.name}")
            continue
        try:
            print(f"[download] {index}/{len(resolved)} {target.name}")
            download_file(str(url), target, user_agent=user_agent)
        except Exception as exc:
            print(f"[download] FAILED {target.name}: {exc}")

    print(f"[done] 视频目录：{out_dir}")
    print(f"[done] 地址清单：{out_dir / 'doubao_video_urls.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
