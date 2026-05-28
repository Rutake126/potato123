import os
import time
from DrissionPage import ChromiumPage
from pypdf import PdfWriter
import requests


def download_and_merge_pdfs(book_id, total_pages, output_filename="merged_book.pdf"):
    # 1. Initialize DrissionPage (ChromiumPage)
    # This opens a browser instance which helps bypass basic anti-bot protections and handles sessions
    page = ChromiumPage()

    # Create a temporary directory to store individual pages
    temp_dir = "temp_pdf_pages"
    os.makedirs(temp_dir, exist_ok=True)

    # Get the session/cookies from DrissionPage to use with requests for faster downloading
    # If the site requires login, log in manually in the browser window before starting
    session = requests.Session()
    for cookie in page.cookies():
        session.cookies.set(cookie['name'], cookie['value'])

    headers = {
        "User-Agent": page.user_agent,
        "Referer": f"https://gydc-v4.cintcm.cn/"
    }

    downloaded_files = []

    print(f"Starting download of {total_pages} pages...")

    try:
        for page_num in range(1, total_pages + 1):
            url = f"https://gydc-v4.cintcm.cn/retrieve/page/getPdf?bookId={book_id}&page={page_num}"
            file_path = os.path.join(temp_dir, f"page_{page_num}.pdf")

            # Download the file using requests (faster than navigating the browser for 411 pages)
            response = session.get(url, headers=headers, stream=True)

            if response.status_code == 200:
                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                downloaded_files.append(file_path)
                print(f"Successfully downloaded page {page_num}/{total_pages}")
            else:
                print(f"Failed to download page {page_num}. Status code: {response.status_code}")

            # Anti-banning safety delay (adjust as needed)
            time.sleep(0.5)

        # 2. Merge PDFs using pypdf
        if downloaded_files:
            print("\nMerging PDFs... Please wait.")
            merger = PdfWriter()

            for pdf in downloaded_files:
                merger.append(pdf)

            merger.write(output_filename)

            print(f"\nSuccess! All pages merged into: {output_filename}")
        else:
            print("\nNo pages were downloaded. Merger skipped.")

    finally:
        # 3. Clean up temporary files
        print("Cleaning up temporary files...")
        for file in downloaded_files:
            try:
                os.remove(file)
            except Exception:
                pass
        try:
            os.rmdir(temp_dir)
        except Exception:
            pass

        page.quit()


if __name__ == "__main__":
    BOOK_ID = "171883648428"
    TOTAL_PAGES = 411
    OUTPUT_NAME = "cintcm_book_171883648428.pdf"

    download_and_merge_pdfs(BOOK_ID, TOTAL_PAGES, OUTPUT_NAME)