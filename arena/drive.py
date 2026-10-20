"""Anonymous reads of the four explicitly shared upload folders only."""
import html
import json
import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.items = []; self.href = None; self.text = []
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = dict(attrs).get("href"); self.text = []
    def handle_data(self, data):
        if self.href: self.text.append(data)
    def handle_endtag(self, tag):
        if tag == "a" and self.href:
            m = re.search(r"https://drive\.google\.com/file/d/([-\w]+)/", self.href)
            if m: self.items.append({"file_id": m.group(1), "filename": "".join(self.text).strip()})
            self.href = None

def list_models(folder):
    request = urllib.request.Request("https://drive.google.com/embeddedfolderview?id=" + folder, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        text = response.read(4 * 1024 * 1024).decode("utf-8")
        if "accounts.google.com" in response.url: raise ValueError("資料夾尚未允許知道連結的人檢視")
    if "<title>" not in text.lower(): raise ValueError("Drive清單格式異常，沒有當成空資料夾")
    parser = Links(); parser.feed(text)
    files = {x["file_id"]: x for x in parser.items if x["filename"].lower().endswith(".zip")}
    return list(files.values())

def download(file_id, target):
    # gdown follows Google's bounded download confirmation form; no Google OAuth,
    # API keys, browser cookies, or local model files are transferred to runners.
    import gdown
    output = gdown.download(id=file_id, output=str(target), quiet=True, use_cookies=False)
    if not output or not Path(output).is_file(): raise ValueError("模型無法公開下載；請檢查連結權限")
    if Path(output).stat().st_size > 64 * 1024 * 1024: raise ValueError("模型ZIP超過64MiB，請只上傳模型")
