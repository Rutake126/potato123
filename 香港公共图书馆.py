import argparse
import os
import re
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

import requests
from DrissionPage import ChromiumOptions, ChromiumPage
from urllib3.exceptions import InsecureRequestWarning


DEFAULT_URL = (
    "https://media.hkpl.gov.hk/api/drmapi/client-api/common/pdfCommon/load"
    "?id=1925009055565668353"
)
DEFAULT_WARMUP_URL = "https://sls.hkpl.gov.hk/"
DEFAULT_REFERER = "https://sls.hkpl.gov.hk/"


def clean_ssl_environment() -> None:
    # A stale SSLKEYLOGFILE path can make Python's TLS handshake fail with
    # FileNotFoundError, which requests then reports as a ProxyError.
    for key in (
        "SSLKEYLOGFILE",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        os.environ.pop(key, None)


def content_disposition_filename(value: Optional[str]) -> Optional[str]:
    if not value:
        return None

    match = re.search(r"filename\*=UTF-8''([^;]+)", value, re.I)
    if match:
        return unquote(match.group(1).strip().strip('"'))

    match = re.search(r'filename="?([^";]+)"?', value, re.I)
    if match:
        return match.group(1).strip()

    return None


def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip()
    return name or "hkpl_book.pdf"


def origin_from_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def normalize_proxy(proxy: Optional[str]) -> Optional[str]:
    if not proxy:
        return None

    proxy = proxy.strip()
    if not proxy:
        return None

    if "://" not in proxy:
        proxy = f"http://{proxy}"

    return proxy


def check_proxy(proxy: Optional[str]) -> None:
    if not proxy:
        return

    parsed = urlparse(proxy)
    host = parsed.hostname
    port = parsed.port
    if not host or not port:
        raise RuntimeError(f"Invalid proxy URL: {proxy}")

    try:
        with socket.create_connection((host, port), timeout=5):
            pass
    except OSError as exc:
        raise RuntimeError(
            f"Cannot connect to proxy {proxy}. Please confirm your proxy app is running "
            f"and that {port} is the HTTP or mixed proxy port."
        ) from exc


def set_chrome_argument(options: ChromiumOptions, name: str, value: Optional[str] = None) -> None:
    if not hasattr(options, "set_argument"):
        return

    try:
        if value is None:
            options.set_argument(name)
        else:
            options.set_argument(name, value)
    except TypeError:
        if value is None:
            options.set_argument(name)
        else:
            options.set_argument(f"{name}={value}")


def configure_browser_proxy(options: ChromiumOptions, proxy: Optional[str], direct: bool) -> None:
    if proxy:
        if hasattr(options, "set_proxy"):
            options.set_proxy(proxy)
        else:
            set_chrome_argument(options, "--proxy-server", proxy)
        return

    if direct:
        set_chrome_argument(options, "--no-proxy-server")
        set_chrome_argument(options, "--proxy-bypass-list", "*")


def configure_browser_ssl(options: ChromiumOptions, insecure: bool) -> None:
    if not insecure:
        return

    set_chrome_argument(options, "--ignore-certificate-errors")
    set_chrome_argument(options, "--ignore-ssl-errors")
    set_chrome_argument(options, "--allow-running-insecure-content")


def get_browser_context(
    warmup_url: str,
    headless: bool,
    wait_seconds: int,
    proxy: Optional[str],
    direct: bool,
    insecure: bool,
) -> tuple[str, dict[str, str]]:
    options = ChromiumOptions()
    if headless:
        options.headless()
    configure_browser_proxy(options, proxy, direct)
    configure_browser_ssl(options, insecure)

    page = ChromiumPage(options)
    try:
        print(f"Opening warmup page: {warmup_url}")
        page.get(warmup_url)
        if wait_seconds > 0:
            time.sleep(wait_seconds)

        user_agent = page.run_js("return navigator.userAgent")
        raw_cookies = page.cookies()
        if isinstance(raw_cookies, dict):
            cookies = raw_cookies
        else:
            cookies = {cookie["name"]: cookie["value"] for cookie in raw_cookies}
        return user_agent, cookies
    finally:
        page.quit()


def build_headers(
    user_agent: str,
    referer: Optional[str],
    include_origin: bool,
    as_navigation: bool,
    range_header: Optional[str] = None,
) -> dict[str, str]:
    headers = {
        "Accept": "application/pdf,application/octet-stream,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Pragma": "no-cache",
        "User-Agent": user_agent,
    }

    if as_navigation:
        headers.update(
            {
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-site" if referer else "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            }
        )
    else:
        headers.update(
            {
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site" if referer else "none",
            }
        )

    if referer:
        headers["Referer"] = referer
        if include_origin:
            headers["Origin"] = origin_from_url(referer)

    if range_header:
        headers["Range"] = range_header

    return headers


def request_profiles(primary_referer: str, warmup_url: str) -> list[tuple[str, Optional[str], bool, bool]]:
    profiles: list[tuple[str, Optional[str], bool, bool]] = []

    def add(name: str, referer: Optional[str], include_origin: bool, as_navigation: bool) -> None:
        profile = (name, referer, include_origin, as_navigation)
        if profile not in profiles:
            profiles.append(profile)

    add("cors referer with origin", primary_referer, True, False)
    add("cors warmup with origin", warmup_url, True, False)
    add("navigation referer", primary_referer, False, True)
    add("navigation warmup", warmup_url, False, True)
    add("referer only", primary_referer, False, False)
    add("warmup referer only", warmup_url, False, False)
    add("no referer", None, False, True)
    return profiles


def print_progress(done: int, total: Optional[int], started_at: float) -> None:
    elapsed = max(time.time() - started_at, 0.001)
    speed = done / elapsed / 1024 / 1024

    if total:
        percent = done / total * 100
        message = f"\r{done / 1024 / 1024:,.1f}/{total / 1024 / 1024:,.1f} MB ({percent:5.1f}%) {speed:,.1f} MB/s"
    else:
        message = f"\r{done / 1024 / 1024:,.1f} MB {speed:,.1f} MB/s"

    sys.stdout.write(message)
    sys.stdout.flush()


def parallel_download(
    session: requests.Session,
    url: str,
    output: Path,
    headers: dict[str, str],
    total: int,
    insecure: bool,
    workers: int,
    part_size_mb: int,
) -> bool:
    part_size = max(part_size_mb, 1) * 1024 * 1024
    ranges = []
    start = 0
    while start < total:
        end = min(start + part_size - 1, total - 1)
        ranges.append((len(ranges), start, end))
        start = end + 1

    parts_dir = output.with_suffix(output.suffix + ".parts")
    parts_dir.mkdir(parents=True, exist_ok=True)

    done_by_part = {}
    for index, start, end in ranges:
        part_file = parts_dir / f"{index:05d}.part"
        expected = end - start + 1
        done_by_part[index] = part_file.stat().st_size if part_file.exists() else 0
        if done_by_part[index] > expected:
            part_file.unlink()
            done_by_part[index] = 0

    started_at = time.time()
    last_print = 0.0

    def total_done() -> int:
        return min(sum(done_by_part.values()), total)

    def maybe_print(force: bool = False) -> None:
        nonlocal last_print
        now = time.time()
        if force or now - last_print >= 0.25:
            print_progress(total_done(), total, started_at)
            last_print = now

    def download_one(index: int, start: int, end: int) -> None:
        part_file = parts_dir / f"{index:05d}.part"
        expected = end - start + 1
        existing = part_file.stat().st_size if part_file.exists() else 0
        if existing == expected:
            maybe_print()
            return

        if existing > expected:
            part_file.unlink()
            existing = 0

        request_headers = dict(headers)
        request_headers["Range"] = f"bytes={start + existing}-{end}"

        with session.get(url, headers=request_headers, stream=True, timeout=(20, 120), verify=not insecure) as response:
            if response.status_code != 206:
                preview = response.raw.read(300, decode_content=True)
                raise RuntimeError(
                    f"Range request failed. status={response.status_code}, preview={preview!r}"
                )

            with part_file.open("ab") as file:
                for chunk in response.iter_content(chunk_size=2 * 1024 * 1024):
                    if not chunk:
                        continue
                    file.write(chunk)
                    done_by_part[index] += len(chunk)
                    maybe_print()

        actual = part_file.stat().st_size
        if actual != expected:
            raise RuntimeError(f"Part {index} size mismatch: expected {expected}, got {actual}")

    print(f"Parallel download: {workers} workers, {len(ranges)} parts, {part_size_mb} MB each")
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(download_one, *item) for item in ranges]
            for future in as_completed(futures):
                future.result()
    except Exception as exc:
        print()
        print(f"Parallel download failed, keeping parts for resume: {parts_dir}")
        print(f"Reason: {exc}")
        return False

    maybe_print(force=True)
    print()

    temp_file = output.with_suffix(output.suffix + ".part")
    with temp_file.open("wb") as merged:
        for index, _, _ in ranges:
            part_file = parts_dir / f"{index:05d}.part"
            with part_file.open("rb") as file:
                for chunk in iter(lambda: file.read(4 * 1024 * 1024), b""):
                    merged.write(chunk)

    temp_file.replace(output)
    for part_file in parts_dir.glob("*.part"):
        part_file.unlink()
    parts_dir.rmdir()
    print(f"Saved: {output}")
    return True


def make_session(cookies: dict[str, str], proxy: Optional[str], direct: bool) -> requests.Session:
    session = requests.Session()
    session.cookies.update(cookies)
    session.trust_env = False if proxy else not direct
    if proxy:
        session.proxies.update({"https": proxy})
    return session


def proxy_hint(proxy: Optional[str]) -> str:
    if not proxy:
        return ""

    parsed = urlparse(proxy)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 7897
    return (
        f" Proxy {proxy!r} connected at TCP level but requests could not use it. "
        f"For Clash Verge mixed-port, try --download-proxy socks5h://{host}:{port}. "
        f"If SOCKS support is missing, run: python -m pip install requests[socks]."
    )


def probe_filename(
    url: str,
    user_agent: str,
    cookies: dict[str, str],
    referer: str,
    warmup_url: str,
    insecure: bool,
    proxy: Optional[str],
    direct: bool,
) -> Optional[str]:
    session = make_session(cookies, proxy, direct)

    for _, profile_referer, include_origin, as_navigation in request_profiles(referer, warmup_url):
        try:
            response = session.get(
                url,
                headers=build_headers(user_agent, profile_referer, include_origin, as_navigation, "bytes=0-0"),
                timeout=(20, 60),
                verify=not insecure,
                stream=True,
            )
            response.close()
            if response.status_code != 403:
                return content_disposition_filename(response.headers.get("Content-Disposition"))
        except requests.RequestException:
            continue
    return None


def resolve_output(url: str, explicit_output: Optional[str], headers_filename: Optional[str]) -> Path:
    if explicit_output:
        return Path(explicit_output).expanduser().resolve()

    filename = headers_filename
    if not filename:
        parsed = urlparse(url)
        pdf_id = parse_qs(parsed.query).get("id", [None])[0]
        filename = f"hkpl_{pdf_id}.pdf" if pdf_id else "hkpl_book.pdf"

    return (Path.cwd() / safe_filename(filename)).resolve()


def download(
    url: str,
    output: Path,
    user_agent: str,
    cookies: dict[str, str],
    referer: str,
    warmup_url: str,
    insecure: bool,
    proxy: Optional[str],
    direct: bool,
    workers: int,
    part_size_mb: int,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_file = output.with_suffix(output.suffix + ".part")
    session = make_session(cookies, proxy, direct)

    existing_size = temp_file.stat().st_size if temp_file.exists() else 0
    range_header = None
    if existing_size:
        range_header = f"bytes={existing_size}-"
        print(f"Resuming from {existing_size / 1024 / 1024:,.1f} MB")

    last_status = None
    last_preview = None
    response = None

    for profile_name, profile_referer, include_origin, as_navigation in request_profiles(referer, warmup_url):
        headers = build_headers(user_agent, profile_referer, include_origin, as_navigation, range_header)
        print(f"Trying request profile: {profile_name}")
        try:
            response = session.get(url, headers=headers, stream=True, timeout=(20, 120), verify=not insecure)
        except requests.exceptions.ProxyError as exc:
            raise RuntimeError(f"Download proxy failed.{proxy_hint(proxy)} Original error: {exc}") from exc
        except requests.RequestException as exc:
            raise RuntimeError(f"Download request failed: {exc}") from exc
        last_status = response.status_code

        if response.status_code == 403:
            last_preview = response.raw.read(500, decode_content=True)
            response.close()
            continue

        break

    if response is None or last_status == 403:
        raise RuntimeError(
            "Got 403 Forbidden from every request profile. "
            "The server is still rejecting this as a non-reader request. "
            "Please pass the real page where this PDF is opened with --reader-url. "
            f"Last response preview: {last_preview!r}"
        )

    with response:
        if response.status_code == 200 and existing_size:
            print("Server ignored Range header; restarting download.")
            existing_size = 0
            temp_file.unlink(missing_ok=True)

        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "")
        if "pdf" not in content_type.lower():
            preview = response.raw.read(500, decode_content=True)
            raise RuntimeError(
                f"Response is not a PDF. status={response.status_code}, "
                f"content-type={content_type!r}, preview={preview!r}"
            )

        total_header = response.headers.get("Content-Length")
        total = int(total_header) + existing_size if total_header else None

        if workers > 1 and total and existing_size == 0 and response.status_code == 200:
            response.close()
            if parallel_download(session, url, output, headers, total, insecure, workers, part_size_mb):
                return
            print("Falling back to single connection download.")
            response = session.get(url, headers=headers, stream=True, timeout=(20, 120), verify=not insecure)
            response.raise_for_status()
            total_header = response.headers.get("Content-Length")
            total = int(total_header) if total_header else total

        mode = "ab" if existing_size and response.status_code == 206 else "wb"
        done = existing_size if mode == "ab" else 0
        started_at = time.time()

        with temp_file.open(mode) as file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                file.write(chunk)
                done += len(chunk)
                print_progress(done, total, started_at)

    print()
    temp_file.replace(output)
    print(f"Saved: {output}")


def main() -> None:
    clean_ssl_environment()

    parser = argparse.ArgumentParser(description="Download HKPL PDF with DrissionPage browser cookies.")
    parser.add_argument("--url", default=DEFAULT_URL, help="PDF API URL.")
    parser.add_argument(
        "--warmup-url",
        default=DEFAULT_WARMUP_URL,
        help="Allowed HKPL page opened by DrissionPage before downloading.",
    )
    parser.add_argument(
        "--referer",
        default=DEFAULT_REFERER,
        help="Referer used for the PDF request.",
    )
    parser.add_argument(
        "--reader-url",
        help="Real HKPL reader/book page URL. When set, it is used as both --warmup-url and --referer.",
    )
    parser.add_argument("-o", "--output", help="Output PDF path.")
    parser.add_argument("--headless", action="store_true", help="Run Chromium headlessly.")
    parser.add_argument("--wait", type=int, default=3, help="Seconds to wait after opening the warmup page.")
    parser.add_argument("--workers", type=int, default=8, help="Parallel Range download workers. Use 1 for single connection.")
    parser.add_argument("--part-size-mb", type=int, default=16, help="Part size for parallel download.")
    parser.add_argument(
        "--proxy",
        help="Proxy for Chromium and requests, for example http://127.0.0.1:7890. If omitted, direct mode is used.",
    )
    parser.add_argument(
        "--browser-proxy",
        help="Proxy only for DrissionPage Chromium warmup page. Overrides --proxy for Chromium.",
    )
    parser.add_argument(
        "--download-proxy",
        help="Proxy only for PDF download requests. Overrides --proxy for requests.",
    )
    parser.add_argument(
        "--clash-mixed-port",
        type=int,
        help="Shortcut for Clash Verge mixed port, for example 7897. It sets --download-proxy socks5h://127.0.0.1:PORT.",
    )
    parser.add_argument(
        "--use-system-proxy",
        action="store_true",
        help="Use Windows/environment proxy settings. By default the script bypasses them.",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification, similar to curl -k.",
    )
    args = parser.parse_args()

    if args.insecure:
        requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

    if args.reader_url:
        args.warmup_url = args.reader_url
        args.referer = args.reader_url

    browser_proxy = normalize_proxy(args.browser_proxy or args.proxy)
    clash_download_proxy = f"socks5h://127.0.0.1:{args.clash_mixed_port}" if args.clash_mixed_port else None
    download_proxy = normalize_proxy(args.download_proxy or clash_download_proxy or args.proxy)
    browser_direct = not args.use_system_proxy and not browser_proxy
    download_direct = not args.use_system_proxy and not download_proxy

    print("Opening Chromium with DrissionPage to collect browser cookies...")
    if browser_direct:
        print("Browser proxy mode: direct connection, system proxy bypassed.")
    elif browser_proxy:
        print(f"Browser proxy mode: explicit proxy {browser_proxy}")
    else:
        print("Browser proxy mode: system proxy.")

    if download_direct:
        print("Download proxy mode: direct connection, system proxy bypassed.")
    elif download_proxy:
        print(f"Download proxy mode: explicit proxy {download_proxy}")
        check_proxy(download_proxy)
    else:
        print("Download proxy mode: system proxy.")

    user_agent, cookies = get_browser_context(
        args.warmup_url,
        args.headless,
        args.wait,
        browser_proxy,
        browser_direct,
        args.insecure,
    )
    print(f"Collected {len(cookies)} cookies.")

    header_filename = probe_filename(
        args.url,
        user_agent,
        cookies,
        args.referer,
        args.warmup_url,
        args.insecure,
        download_proxy,
        download_direct,
    )
    output = resolve_output(args.url, args.output, header_filename)
    download(
        args.url,
        output,
        user_agent,
        cookies,
        args.referer,
        args.warmup_url,
        args.insecure,
        download_proxy,
        download_direct,
        max(args.workers, 1),
        max(args.part_size_mb, 1),
    )


if __name__ == "__main__":
    main()
