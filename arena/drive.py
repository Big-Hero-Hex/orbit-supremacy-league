"""Anonymous reads of the four explicitly shared upload folders only."""
import html
import ast
import gzip
import hashlib
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

def parse_metadata(text, folder):
    """Public Drive file revision hints; no embedded web-client API keys used.

    The folder page is undocumented. Require a recognized file schema; the
    caller falls back to a real content hash if metadata cannot be trusted.
    """
    match = re.search(r"window\['_DRIVE_ivd'\]\s*=\s*'(.*?)';", text, re.S)
    if not match: raise ValueError("Public revision metadata unavailable")
    tree = json.loads(ast.literal_eval("'" + match.group(1).replace(r"\/", "/") + "'"))
    found = {}
    def visit(value):
        if not isinstance(value,list): return
        if (len(value)>13 and isinstance(value[0],str) and isinstance(value[1],list)
                and folder in value[1] and isinstance(value[2],str) and value[2].lower().endswith(".zip")
                and isinstance(value[3],str) and "/" in value[3]):
            item={"file_id":value[0],"filename":value[2]}
            if all(isinstance(value[i],int) and 946684800000<=value[i]<100000000000000 for i in (9,10)) and isinstance(value[13],int):
                revision={"id":value[0],"name":value[2],"created_ms":value[9],"modified_ms":value[10],"size":value[13]}
                item.update(metadata_fingerprint=hashlib.sha256(json.dumps(revision,sort_keys=True).encode()).hexdigest(),
                            modified_ms=value[10],size_bytes=value[13])
            found[value[0]]=item
        for child in value: visit(child)
    visit(tree)
    return list(found.values())

def model_metadata(folder):
    request=urllib.request.Request("https://drive.google.com/drive/folders/"+folder,
                                   headers={"User-Agent":"Mozilla/5.0","Accept-Encoding":"gzip"})
    try:
        with urllib.request.urlopen(request,timeout=30) as response:
            if "accounts.google.com" in response.url: raise ValueError("Drive requires login")
            payload=response.read(4*1024*1024)
            if response.headers.get("Content-Encoding")=="gzip":payload=gzip.decompress(payload)
        return parse_metadata(payload.decode("utf-8"),folder)
    except (ValueError,SyntaxError,TypeError,UnicodeError):
        # A Google page-format change must not hide a changed model. Without
        # validated revision hints the caller downloads and hashes the ZIP.
        return list_models(folder)

def download(file_id, target):
    # gdown follows Google's bounded download confirmation form; no Google OAuth,
    # API keys, browser cookies, or local model files are transferred to runners.
    import gdown
    output = gdown.download(id=file_id, output=str(target), quiet=True, use_cookies=False)
    if not output or not Path(output).is_file(): raise ValueError("模型無法公開下載；請檢查連結權限")
    if Path(output).stat().st_size > 64 * 1024 * 1024: raise ValueError("模型ZIP超過64MiB，請只上傳模型")
