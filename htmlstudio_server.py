#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTML 工作台 · 本地 HTML 收录 / 文本编辑 / 配色 / 交接服务
零依赖，只用 Python 标准库。默认监听 127.0.0.1:8781。

    python htmlstudio_server.py
    python htmlstudio_server.py --port 9000 --host 0.0.0.0
    python htmlstudio_server.py --list
"""

import os
import sys
import re
import io
import json
import time
import html
import uuid
import shutil
import socket
import base64
import struct
import difflib
import hashlib
import mimetypes
import subprocess
import tempfile
import threading
import webbrowser
import zipfile
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote, quote
from urllib.request import urlopen

# --noconsole 打包后没有控制台，print 写入空设备，避免窗口模式下崩溃
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

# PyInstaller onefile 会把资源解压到 _MEIPASS，用该目录定位 index.html / assets
FROZEN = bool(getattr(sys, "frozen", False))
BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
INDEX_HTML = os.path.join(BASE_DIR, "index.html")
# 打包后数据写到 %APPDATA%\HTMLStudio\data；源码运行仍用 ./data
DATA_DIR = (
    os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "HTMLStudio", "data")
    if FROZEN else os.path.join(BASE_DIR, "data")
)
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
HISTORY_DIR = os.path.join(DATA_DIR, "history")
COVER_DIR = os.path.join(DATA_DIR, "covers")
EXPORT_DIR = os.path.join(DATA_DIR, "exports")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
PALETTE_PATH = os.path.join(DATA_DIR, "palettes.json")
LIBRARY_PATH = os.path.join(DATA_DIR, "library.json")

APP_VERSION = "0.1.0"
APP_NAME = "HTML 工作台"

SKIP_DIRS = {
    "node_modules", "__pycache__", ".git", ".svn", ".hg", "dist", "build",
    "site-packages", ".venv", "venv", "env", "Worktrees", "browser_data",
    ".screenshots", ".uploads", ".cache", "HTML工作台",
}
MAX_DEPTH = 9
MAX_SCAN = 2500
MAX_META_READ = 420 * 1024
CACHE_TTL = 6

HTML_EXT = {".html", ".htm"}
TEXT_EXT = {".html", ".htm", ".md", ".markdown", ".txt", ".css", ".js", ".json", ".svg"}

DEFAULT_ROOTS = [
    {"id": "wb", "name": "WorkBuddy", "probe": [os.path.join(os.environ.get("USERPROFILE", ""), "WorkBuddy")]},
    {"id": "trae", "name": "Trae 交付", "probe": [os.path.join(os.environ.get("USERPROFILE", ""), "Documents", "Trae-CN")]},
]

DEFAULT_PROVIDERS = [
    {"id": "trae", "name": "Trae", "cmd": ""},
    {"id": "wb", "name": "WorkBuddy", "cmd": ""},
    {"id": "cursor", "name": "Cursor", "cmd": ""},
    {"id": "claude", "name": "Claude Code", "cmd": ""},
]

SEED_PALETTES = [
    {
        "id": "warm-paper",
        "name": "暖纸编辑风",
        "note": "米纸底 + 墨色正文 + 梅紫/鼠尾草点缀，适合阅读型页面",
        "kind": "light",
        "builtin": True,
        "tokens": {
            "--paper": "#f5f0e8", "--surface": "#fffdfa", "--surface-2": "#eee7dd",
            "--ink": "#29251f", "--muted": "#746d63", "--faint": "#9a9186",
            "--line": "#ded5c8", "--line-strong": "#cfc4b7",
            "--plum": "#4d3045", "--plum-soft": "#e8dfe5",
            "--sage": "#627a67", "--sage-soft": "#dfe8df",
            "--terra": "#b65f42", "--terra-soft": "#f3dfd6",
            "--sand": "#a57c45", "--sand-soft": "#eee2ce",
            "--radius": "22px",
        },
    },
    {
        "id": "ink-night",
        "name": "墨夜纸感",
        "note": "暖黑底 + 纸白字，夜间阅读与数据面板都稳",
        "kind": "dark",
        "builtin": True,
        "tokens": {
            "--bg": "#121110", "--bg2": "#191715", "--card": "#201d1a",
            "--card2": "#26221e", "--card3": "#2e2925",
            "--ink": "#f0ebe3", "--ink2": "#cfc7bb", "--muted": "#9a9186", "--faint": "#716960",
            "--line": "#332e29", "--line2": "#453e37",
            "--paper": "#e8dcc6", "--paper-dim": "#b9a98f",
            "--plum": "#b795ae", "--sage": "#9db49f", "--terra": "#d3896b",
            "--sand": "#c9a76a", "--blue": "#8fb3c7",
            "--radius": "14px",
        },
    },
    {
        "id": "mono-paper",
        "name": "极简黑白",
        "note": "纯黑白灰，图表与文档的通用底子",
        "kind": "light",
        "builtin": True,
        "tokens": {
            "--bg": "#ffffff", "--surface": "#ffffff", "--surface-2": "#f5f5f5",
            "--ink": "#111111", "--muted": "#555555", "--faint": "#888888",
            "--line": "#dddddd", "--line-strong": "#bbbbbb",
            "--accent": "#111111", "--accent-soft": "#eeeeee",
            "--radius": "10px",
        },
    },
]
SEED_PALETTES_BY_ID = {p["id"]: p for p in SEED_PALETTES}

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr", "!doctype",
}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

TOKEN_RE = re.compile(
    r"<!--[\s\S]*?-->"
    r"|<\s*script\b[^>]*>[\s\S]*?<\s*/\s*script\s*>"
    r"|<\s*style\b[^>]*>[\s\S]*?<\s*/\s*style\s*>"
    r"|<[^>]+>",
    re.I,
)
TAG_RE = re.compile(r"<\s*(/?)\s*([a-zA-Z0-9:_-]+)")
ATTR_CLASS_RE = re.compile(r'\bclass\s*=\s*["\']([^"\']*)["\']', re.I)
VAR_RE = re.compile(r"(--[A-Za-z0-9_-]+)\s*:\s*([^;{}]+);")
HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
RGB_RE = re.compile(r"rgba?\([^)]{3,40}\)", re.I)
PALETTE_STYLE_RE = re.compile(
    r"<style\b[^>]*\bid\s*=\s*[\"']?htmlhub-palette[\"']?[^>]*>[\s\S]*?<\s*/\s*style\s*>\s*",
    re.I,
)

_cache = {"t": 0.0, "items": []}
_meta_cache = {}
_lock = threading.RLock()

# 打包运行时：前端定时心跳，页面全部关闭后自动退出
HEARTBEAT_TIMEOUT = 40
_heartbeat = {"seen": False, "t": 0.0}

# 打包为 --noconsole 程序后，任何子进程都不能弹黑窗
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


# ───────────────────────── 基础工具 ─────────────────────────
def read_text(path):
    with open(path, "rb") as f:
        b = f.read()
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", "replace")


def atomic_write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".htmlhub-tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def strip_tags(s):
    s = re.sub(r"<script[\s\S]*?</script>", " ", s, flags=re.I)
    s = re.sub(r"<style[\s\S]*?</style>", " ", s, flags=re.I)
    s = re.sub(r"<!--[\s\S]*?-->", " ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return html.unescape(s).strip()


def page_title(text, fallback, ext=".html"):
    if ext in (".html", ".htm", ".svg"):
        m = re.search(r"<title[^>]*>([\s\S]*?)</title>", text, re.I)
        if m:
            t = re.sub(r"\s+", " ", html.unescape(m.group(1))).strip()
            if t:
                return t[:120]
        m = re.search(r"<h1[^>]*>([\s\S]*?)</h1>", text, re.I)
        if m:
            t = strip_tags(m.group(1))
            if t:
                return t[:120]
    if ext in (".md", ".markdown"):
        m = re.search(r"^\s{0,3}#\s+(.+)$", text, re.M)
        if m:
            return m.group(1).strip()[:120]
    return fallback


def pick_colors(text, limit=5):
    found = {}
    head = text[:120000]
    for m in HEX_RE.findall(head):
        c = m.lower()
        if len(c) in (4, 7, 9):
            found[c] = found.get(c, 0) + 1
    for m in RGB_RE.findall(head):
        c = re.sub(r"\s+", "", m.lower())
        found[c] = found.get(c, 0) + 1
    skip = {"#ffffff", "#000000", "#fff", "#000"}
    ordered = [c for c, _ in sorted(found.items(), key=lambda kv: -kv[1]) if c not in skip]
    return ordered[:limit]


def count_words(s):
    return len(re.findall(r"[\u4e00-\u9fa5]", s)) + len(re.findall(r"[A-Za-z]+", s))


# ───────────────────── 脚本文案同步（语言字典等） ─────────────────────
# 有些页面在运行时用 JS 字典重写文案（例如 setLang 里的 H1/UI 表），
# 只改静态 HTML 会被脚本覆盖。这里把脚本字符串里的同一段文字一起改写。
SCRIPT_PART_RE = re.compile(r"(<script\b[^>]*>)([\s\S]*?)(<\s*/\s*script\s*>)", re.I)
JS_STRING_RE = re.compile(r"(['\"])((?:\\.|(?!\1)[^\\])*)\1")
TAG_SPLIT_RE = re.compile(r"(<[^>]+>)")


def _plain_text(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s))


def _norm_ws(s):
    return re.sub(r"\s+", " ", s).strip()


def _js_escape(s):
    return s.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"').replace("\r", "").replace("\n", "\\n")


def _rewrite_fragment_text(fragment, old, new):
    """保留 fragment 里的标签，把纯文本按 old → new 分摊到各文本段。"""
    tokens = TAG_SPLIT_RE.split(fragment)
    idx = [k for k, t in enumerate(tokens) if t and not t.startswith("<")]
    plain = "".join(_plain_text(tokens[k]) for k in idx)
    if plain != old:
        return None
    spans, pos = [], 0
    for k in idx:
        n = len(_plain_text(tokens[k]))
        spans.append((pos, pos + n, k))
        pos += n
    if not idx or not old:
        return None
    out = {k: "" for k in idx}

    def seg_of(p):
        for s, e, k in spans:
            if s <= p < e:
                return k
        return idx[-1]

    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for off in range(i2 - i1):
                out[seg_of(i1 + off)] += new[j1 + off]
        elif tag in ("replace", "insert"):
            out[seg_of(min(i1, len(old) - 1))] += new[j1:j2]
    for k in idx:
        tokens[k] = html.escape(out[k], quote=False)
    return "".join(tokens)


def sync_script_texts(src, old, new):
    """把脚本字符串里与 old 等价的文案改写为 new，返回 (新源码, 命中数)。"""
    old_n, plain_new = _norm_ws(_plain_text(old)), new.strip()
    if not old_n or not plain_new or old_n == _norm_ws(plain_new):
        return src, 0
    hits = 0

    def repl_block(m):
        nonlocal hits
        code = m.group(2)

        def repl_str(sm):
            nonlocal hits
            quote, body = sm.group(1), sm.group(2)
            if "\\" in body or not body.strip():
                return sm.group(0)
            plain = _plain_text(body)
            if _norm_ws(plain) != old_n:
                return sm.group(0)
            if "<" not in body:
                hits += 1
                return quote + _js_escape(plain_new) + quote
            rebuilt = _rewrite_fragment_text(body, plain, plain_new)
            if rebuilt is None:
                return sm.group(0)
            hits += 1
            return quote + _js_escape(rebuilt) + quote

        return m.group(1) + JS_STRING_RE.sub(repl_str, code) + m.group(3)

    return SCRIPT_PART_RE.sub(repl_block, src), hits


# ───────────────────────── 配置 / 根目录 ─────────────────────────
def ensure_dirs():
    for d in (DATA_DIR, BACKUP_DIR, HISTORY_DIR, COVER_DIR, EXPORT_DIR):
        os.makedirs(d, exist_ok=True)


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            v = json.load(f)
        return v if isinstance(v, dict) else default
    except Exception:
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def detect_roots():
    out = []
    for t in DEFAULT_ROOTS:
        for p in t.get("probe", []):
            if p and os.path.isdir(p):
                out.append({"id": t["id"], "name": t["name"], "path": os.path.normpath(p)})
                break
    return out


_cfg_cache = {"t": 0.0, "cfg": None}


def load_config(force=False):
    now = time.time()
    if not force and _cfg_cache["cfg"] is not None and now - _cfg_cache["t"] < 2:
        return _cfg_cache["cfg"]
    cfg = load_json(CONFIG_PATH, {})
    roots = cfg.get("roots") if isinstance(cfg.get("roots"), list) else None
    if not roots:
        roots = detect_roots()
    clean = []
    for r in roots:
        p = r.get("path", "")
        if p and os.path.isdir(p):
            clean.append({
                "id": str(r.get("id") or "r")[:32],
                "name": str(r.get("name") or os.path.basename(p))[:48],
                "path": os.path.normpath(p),
            })
    cfg["roots"] = clean
    if not isinstance(cfg.get("pins"), list):
        cfg["pins"] = []
    if not isinstance(cfg.get("recent"), list):
        cfg["recent"] = []
    if not isinstance(cfg.get("providers"), list) or not cfg["providers"]:
        cfg["providers"] = DEFAULT_PROVIDERS
    _cfg_cache["t"] = now
    _cfg_cache["cfg"] = cfg
    return cfg


def save_config(cfg):
    save_json(CONFIG_PATH, cfg)
    _cfg_cache["cfg"] = None
    _cache["t"] = 0
    _meta_cache.clear()


def root_by_id(pid):
    for r in load_config()["roots"]:
        if r["id"] == pid:
            return r
    return None


def safe_abs(pid, rel):
    r = root_by_id(pid)
    if not r:
        raise ValueError("未知内容根：" + str(pid))
    rel = (rel or "").replace("\\", "/").strip("/")
    for seg in rel.split("/"):
        if seg in ("..", ".") or not seg:
            if seg == ".":
                continue
            raise ValueError("非法路径")
    base = os.path.realpath(r["path"])
    ap = os.path.realpath(os.path.join(base, rel))
    if ap != base and not ap.startswith(base + os.sep):
        raise ValueError("路径越界")
    return ap


def safe_abs_parent(pid, rel):
    """文件预览专用：允许 ../，但最终路径必须仍在内容根内。"""
    r = root_by_id(pid)
    if not r:
        raise ValueError("未知内容根：" + str(pid))
    rel = (rel or "").replace("\\", "/").lstrip("/")
    if not rel:
        raise ValueError("缺少路径")
    base = os.path.realpath(r["path"])
    ap = os.path.realpath(os.path.join(base, rel))
    if ap == base or not ap.startswith(base + os.sep):
        raise ValueError("路径越界")
    return ap


def split_id(doc_id):
    if "/" not in doc_id:
        raise ValueError("缺少内容根前缀")
    return doc_id.split("/", 1)


# ───────────────────────── 索引扫描 ─────────────────────────
def build_meta(path, ext, st, name):
    key = path
    hit = _meta_cache.get(key)
    if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
        return hit[2]
    meta = {"title": os.path.splitext(name)[0], "excerpt": "", "colors": [], "words": 0}
    try:
        if st.st_size <= MAX_META_READ:
            text = read_text(path)
            plain = strip_tags(text)
            meta["title"] = page_title(text, os.path.splitext(name)[0], ext)
            meta["excerpt"] = plain[:200]
            meta["words"] = count_words(plain)
            meta["colors"] = pick_colors(text)
        else:
            meta["excerpt"] = "大文件，仅登记，不生成摘要"
    except Exception:
        pass
    meta["_key"] = (st.st_mtime, st.st_size)
    _meta_cache[key] = (st.st_mtime, st.st_size, meta)
    return meta


def scan(force=False):
    with _lock:
        now = time.time()
        if not force and now - _cache["t"] < CACHE_TTL and _cache["items"]:
            return _cache["items"]
        cfg = load_config()
        items = []
        for root in cfg["roots"]:
            rp = root["path"]
            if not os.path.isdir(rp):
                continue
            for cur, dirs, files in os.walk(rp):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS]
                rel_dir = os.path.relpath(cur, rp)
                depth = 0 if rel_dir == "." else rel_dir.count(os.sep) + 1
                if depth >= MAX_DEPTH:
                    dirs[:] = []
                for fn in sorted(files):
                    if fn.startswith(("~$", ".")):
                        continue
                    ext = os.path.splitext(fn)[1].lower()
                    if ext not in HTML_EXT:
                        continue
                    ap = os.path.join(cur, fn)
                    try:
                        st = os.stat(ap)
                    except OSError:
                        continue
                    rel = os.path.relpath(ap, rp).replace("\\", "/")
                    try:
                        meta = build_meta(ap, ext, st, fn)
                    except Exception:
                        meta = {"title": os.path.splitext(fn)[0], "excerpt": "", "colors": [], "words": 0}
                    items.append({
                        "id": root["id"] + "/" + rel,
                        "root": root["id"],
                        "rootName": root["name"],
                        "dir": os.path.dirname(rel).replace("\\", "/"),
                        "rel": rel,
                        "name": fn,
                        "ext": ext,
                        "title": meta.get("title"),
                        "excerpt": meta.get("excerpt", ""),
                        "colors": meta.get("colors", []),
                        "words": meta.get("words", 0),
                        "size": st.st_size,
                        "mtime": st.st_mtime,
                    })
                    if len(items) >= MAX_SCAN:
                        break
                if len(items) >= MAX_SCAN:
                    break
            if len(items) >= MAX_SCAN:
                break
        items.sort(key=lambda x: -x["mtime"])
        _cache["t"] = now
        _cache["items"] = items
        return items


def index_payload(force=False):
    items = scan(force=force)
    cfg = load_config()
    pins = set(cfg.get("pins") or [])
    recent = cfg.get("recent") or []
    by_root = {}
    for r in cfg["roots"]:
        by_root[r["id"]] = 0
    for it in items:
        by_root[it["root"]] = by_root.get(it["root"], 0) + 1
    for it in items:
        it["pinned"] = it["id"] in pins
    return {
        "ok": True,
        "items": items,
        "roots": [dict(r, count=by_root.get(r["id"], 0),
                       exists=os.path.isdir(r["path"])) for r in cfg["roots"]],
        "pins": list(pins),
        "recent": recent[:20],
        "library": load_library(),
        "stats": {
            "pages": len(items),
            "size": sum(i["size"] for i in items),
            "roots": len(cfg["roots"]),
        },
    }


# ───────────────────────── 虚拟分类 / 备注 ─────────────────────────
def load_library():
    lib = load_json(LIBRARY_PATH, {})
    cols = lib.get("collections") if isinstance(lib.get("collections"), list) else []
    meta = lib.get("meta") if isinstance(lib.get("meta"), dict) else {}
    clean_cols, seen = [], set()
    for c in cols:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id") or "").strip()[:40]
        name = str(c.get("name") or "").strip()[:60]
        if cid and name and cid not in seen:
            seen.add(cid)
            clean_cols.append({"id": cid, "name": name})
    clean_meta = {}
    for k, v in meta.items():
        if not isinstance(v, dict):
            continue
        rec = {}
        for f in ("alias", "version"):
            s = str(v.get(f) or "").strip()
            if s:
                rec[f] = s[:80]
        c = str(v.get("collection") or "").strip()
        if c:
            rec["collection"] = c[:40]
        if rec:
            clean_meta[str(k)[:400]] = rec
    return {"collections": clean_cols, "meta": clean_meta}


def save_library(lib):
    save_json(LIBRARY_PATH, lib)


# ───────────────────────── 文本分块 ─────────────────────────
def tokenize(raw):
    parts, pos = [], 0
    for m in TOKEN_RE.finditer(raw):
        if m.start() > pos:
            parts.append(["text", raw[pos:m.start()]])
        tok = m.group(0)
        if tok.startswith("<!--"):
            kind = "comment"
        elif re.match(r"<\s*script\b", tok, re.I):
            kind = "script"
        elif re.match(r"<\s*style\b", tok, re.I):
            kind = "style"
        else:
            kind = "tag"
        parts.append([kind, tok])
        pos = m.end()
    if pos < len(raw):
        parts.append(["text", raw[pos:]])
    return parts


def blocks_from_parts(parts):
    blocks = []
    stack = []
    last_heading = ""
    open_heading = None
    for ti, (kind, tok) in enumerate(parts):
        if kind == "tag":
            m = TAG_RE.match(tok)
            if not m:
                continue
            closing, name = m.group(1) == "/", m.group(2).lower()
            if closing:
                if name in HEADING_TAGS and open_heading and open_heading["name"] == name:
                    last_heading = re.sub(r"\s+", " ", open_heading["text"]).strip()[:60]
                    open_heading = None
                for idx in range(len(stack) - 1, -1, -1):
                    if stack[idx][0] == name:
                        del stack[idx:]
                        break
            else:
                if tok.rstrip().endswith("/>") or name in VOID_TAGS:
                    continue
                cm = ATTR_CLASS_RE.search(tok)
                cls = (cm.group(1).split()[0] if cm and cm.group(1).split() else "")
                stack.append((name, cls))
                if name in HEADING_TAGS:
                    open_heading = {"name": name, "text": ""}
            continue
        if kind != "text":
            continue
        m = re.match(r"^(\s*)([\s\S]*?)(\s*)$", tok)
        pre, core, post = m.group(1), m.group(2), m.group(3)
        if not core:
            continue
        text = html.unescape(core)
        if not text.strip() or not re.sub(r"&nbsp;|\s", "", text):
            continue
        if open_heading is not None:
            open_heading["text"] += text + " "
        where = " > ".join((".".join([n, c]) if c else n) for n, c in stack[-2:]) or "body"
        blocks.append({
            "i": len(blocks),
            "ti": ti,
            "pre": pre,
            "post": post,
            "text": text,
            "tag": stack[-1][0] if stack else "root",
            "where": where,
            "heading": last_heading,
        })
    return blocks


def escape_text(s):
    s = re.sub(r"&(?!(?:[a-zA-Z][a-zA-Z0-9]{1,31}|#\d{1,7}|#x[0-9a-fA-F]{1,6});)", "&amp;", s)
    return s.replace("<", "&lt;")


def page_vars(raw):
    """取每个变量第一次出现的值（通常是 :root 里的基础色），避免被深色主题覆盖。"""
    vars_ = {}
    for name, val in VAR_RE.findall(raw[:200000]):
        v = val.strip()
        if len(v) > 80 or name in vars_:
            continue
        vars_[name] = v
        if len(vars_) >= 120:
            break
    return vars_


def injected_css(raw):
    m = PALETTE_STYLE_RE.search(raw)
    if not m:
        return ""
    inner = re.sub(r"^<style\b[^>]*>|</style\s*>$", "", m.group(0), flags=re.I)
    return inner.strip()


def inject_css(raw, css):
    body = '<style id="htmlhub-palette" data-htmlhub="palette">\n%s\n</style>\n' % css
    if PALETTE_STYLE_RE.search(raw):
        return PALETTE_STYLE_RE.sub(body, raw, count=1)
    m = re.search(r"</head\s*>", raw, re.I)
    if m:
        return raw[:m.start()] + body + raw[m.start():]
    m = re.search(r"<body\b[^>]*>", raw, re.I)
    if m:
        return raw[:m.end()] + "\n" + body + raw[m.end():]
    return body + raw


def css_from_tokens(tokens):
    lines = ["/* HTML 工作台 · 配色注入 */", ":root {"]
    for k, v in tokens.items():
        lines.append("  %s: %s;" % (k, v))
    lines.append("}")
    return "\n".join(lines)


# ───────────────────── 元素扫描 / 属性与样式编辑 ─────────────────────
EL_SKIP_TAGS = {
    "html", "head", "body", "meta", "link", "script", "style", "title", "base",
    "br", "hr", "source", "track", "wbr", "param", "col", "area", "embed",
    "template", "noscript", "svg", "path", "g", "use", "defs", "circle", "rect",
    "line", "polyline", "polygon", "text", "tspan", "mask", "lineargradient", "stop",
}
ALLOWED_ATTRS = {"src", "alt", "href", "target", "rel", "title", "width", "height", "loading"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg"}
IMG_REF_RE = re.compile(
    r"[A-Za-z0-9_@%+~./\\-]+\.(?:png|jpe?g|gif|webp|avif|svg)", re.I
)
MAX_ASSETS = 80
STYLE_PROPS = {
    "font-size", "font-weight", "font-style", "line-height", "letter-spacing",
    "color", "background-color", "text-align", "text-decoration",
    "border-radius", "border-color", "border-width", "border-style",
    "padding", "padding-top", "padding-right", "padding-bottom", "padding-left",
    "margin", "margin-top", "margin-right", "margin-bottom", "margin-left",
    "max-width", "min-width", "width", "height", "opacity", "object-fit",
    "box-shadow", "text-shadow", "transform", "justify-content", "align-items", "gap",
}
INLINE_STYLE_PROPS = {"color", "font-size", "font-weight", "font-style", "text-decoration"}
ELEMENT_LIMIT = 1200
ATTR_RE = re.compile(
    r"""([A-Za-z_:@][-A-Za-z0-9_:.@]*)\s*(?:=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?"""
)
STYLE_VALUE_BAD = re.compile(r"[{}<>]|expression\s*\(|javascript\s*:|@import|url\s*\(", re.I)


def parse_attr_list(tag):
    m = TAG_RE.match(tag)
    if not m:
        return []
    inner = tag[m.end():]
    if inner.endswith("/>"):
        inner = inner[:-2]
    elif inner.endswith(">"):
        inner = inner[:-1]
    out = []
    for am in ATTR_RE.finditer(inner):
        key = am.group(1)
        val = am.group(2) if am.group(2) is not None else (
            am.group(3) if am.group(3) is not None else am.group(4)
        )
        out.append((key, None if val is None else html.unescape(val)))
    return out


def parse_attrs(tag):
    return {k.lower(): ("" if v is None else v) for k, v in parse_attr_list(tag)}


def set_tag_attrs(tag, updates):
    m = TAG_RE.match(tag)
    if not m:
        return tag
    selfclose = tag.rstrip().endswith("/>")
    pairs = []
    remaining = {str(k).lower(): v for k, v in updates.items()}
    for k, v in parse_attr_list(tag):
        lk = k.lower()
        if lk in remaining:
            nv = remaining.pop(lk)
            if nv is not None and str(nv) != "":
                pairs.append((k, str(nv)))
            continue
        pairs.append((k, v))
    for k, v in remaining.items():
        if v is not None and str(v) != "":
            pairs.append((k, str(v)))
    out = "<" + m.group(2)
    for k, v in pairs:
        if v is None:
            out += " " + k
        else:
            out += ' %s="%s"' % (k, html.escape(str(v), quote=True).replace("'", "&#39;"))
    out += " />" if selfclose else ">"
    return out


def merge_style(raw_style, updates):
    cur = {}
    for chunk in str(raw_style or "").split(";"):
        if ":" not in chunk:
            continue
        k, v = chunk.split(":", 1)
        k = k.strip().lower()
        if k:
            cur[k] = v.strip()
    for k, v in updates.items():
        k = str(k).strip().lower()
        if k not in STYLE_PROPS:
            raise ValueError("不支持的样式属性：%s" % k)
        v = "" if v is None else str(v).strip()[:160]
        if not v:
            cur.pop(k, None)
            continue
        if STYLE_VALUE_BAD.search(v):
            raise ValueError("样式值不合法：%s" % k)
        cur[k] = v
    return "; ".join("%s: %s" % (k, v) for k, v in cur.items())


def clean_attr_value(name, value):
    v = "" if value is None else str(value).strip()
    if len(v) > 1200:
        raise ValueError("属性值过长")
    if name in ("src", "href") and re.match(r"(?i)\s*(javascript|vbscript|data:text/html)", v):
        raise ValueError("不支持的链接地址")
    if name in ("width", "height") and v and not re.fullmatch(r"\d{1,5}(?:px|%)?", v, re.I):
        raise ValueError("%s 需要是数字，可带 px 或 %%" % name)
    if name == "target" and v not in ("", "_blank", "_self", "_parent", "_top"):
        raise ValueError("不支持的 target")
    return v


def clean_inline_style(styles):
    """校验选中文字的局部样式，拼成 style 字符串。"""
    out = []
    for k, v in (styles or {}).items():
        k = str(k).strip().lower()
        v = str(v if v is not None else "").strip()[:60]
        if k not in INLINE_STYLE_PROPS or not v:
            raise ValueError("不支持的文字样式：%s" % k)
        low = v.lower()
        if k == "color":
            if not re.fullmatch(r"#[0-9a-f]{3,8}|rgba?\([0-9.,%\s]+\)|var\(--[a-z0-9_-]+\)", low):
                raise ValueError("颜色值不合法")
        elif k == "font-size":
            if not re.fullmatch(r"\d{1,3}(?:\.\d+)?(?:px|em|rem|%)", low):
                raise ValueError("字号需要是数字，可带 px/em/rem/%")
        elif k == "font-weight":
            if low not in ("normal", "bold", "bolder", "lighter") and not re.fullmatch(r"[1-9]00", low):
                raise ValueError("字重不合法")
        elif k == "font-style":
            if low not in ("normal", "italic", "oblique"):
                raise ValueError("字型不合法")
        elif k == "text-decoration":
            if low not in ("none", "underline", "line-through", "overline"):
                raise ValueError("装饰线不合法")
        out.append("%s: %s" % (k, v))
    if not out:
        raise ValueError("没有要应用的文字样式")
    return "; ".join(out)


def scan_elements(raw):
    parts = tokenize(raw)
    counters = {}
    out = []
    for ti, (kind, tok) in enumerate(parts):
        if kind != "tag":
            continue
        m = TAG_RE.match(tok)
        if not m or m.group(1) == "/":
            continue
        name = m.group(2).lower()
        if name in EL_SKIP_TAGS:
            continue
        ord_ = counters.get(name, 0)
        counters[name] = ord_ + 1
        attrs = parse_attrs(tok)
        text = ""
        for k in range(ti + 1, min(ti + 4, len(parts))):
            if parts[k][0] == "text":
                text = strip_tags(parts[k][1])[:70]
                break
        out.append({
            "tag": name,
            "ord": ord_,
            "orig": tok,
            "id": attrs.get("id", ""),
            "cls": attrs.get("class", ""),
            "style": attrs.get("style", ""),
            "text": text,
            "attrs": {k: attrs[k] for k in ALLOWED_ATTRS if k in attrs},
        })
        if len(out) >= ELEMENT_LIMIT:
            break
    return out


def apply_element_edits(raw, edits):
    parts = tokenize(raw)
    index = {}
    counters = {}
    for ti, (kind, tok) in enumerate(parts):
        if kind != "tag":
            continue
        m = TAG_RE.match(tok)
        if not m or m.group(1) == "/":
            continue
        name = m.group(2).lower()
        if name in EL_SKIP_TAGS:
            continue
        ord_ = counters.get(name, 0)
        counters[name] = ord_ + 1
        index.setdefault(name, []).append(ti)
    changed = 0
    for e in edits:
        tag = str(e.get("tag") or "").strip().lower()
        try:
            ord_ = int(e.get("ord"))
        except Exception:
            raise ValueError("元素编号不正确")
        orig = str(e.get("orig") or "")
        slots = index.get(tag) or []
        if ord_ < 0 or ord_ >= len(slots):
            raise ValueError("页面元素已变化，请刷新后重试")
        ti = slots[ord_]
        cur = parts[ti][1]
        if orig and cur != orig:
            raise ValueError("页面内容已变化（%s），请刷新后重试" % tag)
        updates = {}
        for k, v in (e.get("attrs") or {}).items():
            k = str(k).strip().lower()
            if k in ALLOWED_ATTRS:
                updates[k] = clean_attr_value(k, v)
        style_updates = e.get("style") or {}
        if style_updates:
            updates["style"] = merge_style(parse_attrs(cur).get("style", ""), style_updates)
        if not updates:
            continue
        parts[ti][1] = set_tag_attrs(cur, updates)
        changed += 1
    if not changed:
        return raw, 0
    return "".join(p[1] for p in parts), changed


def resolve_asset_ref(page_path, src, root_path):
    """把页面里的图片地址解析为相对页面目录的真实路径；找不到返回空串。"""
    s = html.unescape(str(src or "")).strip()
    if not s:
        return ""
    low = s.lower()
    if low.startswith(("data:", "http:", "https:", "blob:", "mailto:", "tel:", "javascript:", "#")):
        return ""
    s = unquote(s.split("#")[0].split("?")[0]).replace("\\", "/")
    if not s:
        return ""
    page_dir = os.path.dirname(page_path)
    root = os.path.realpath(root_path)
    bases = [page_dir]
    if s.startswith("/"):
        d = page_dir
        for _ in range(4):
            nd = os.path.dirname(d)
            if nd == d or not (nd == root or nd.startswith(root + os.sep)):
                break
            d = nd
            bases.append(d)
    rel = s.lstrip("/")
    if not rel:
        return ""
    for b in bases:
        cand = os.path.realpath(os.path.join(b, rel))
        if cand != root and cand.startswith(root + os.sep) and os.path.isfile(cand):
            return os.path.relpath(cand, page_dir).replace("\\", "/")
    return ""


def page_assets(page_path, raw, root_path):
    """列出页面实际使用的图片文件（含脚本里拼出来的同目录图片）。"""
    page_dir = os.path.dirname(page_path)
    out = {}

    def add(ap):
        try:
            ap = os.path.realpath(ap)
            if not os.path.isfile(ap) or os.path.splitext(ap)[1].lower() not in IMG_EXT:
                return
            rel = os.path.relpath(ap, page_dir).replace("\\", "/")
            if rel in out:
                return
            st = os.stat(ap)
            out[rel] = {
                "rel": rel,
                "name": os.path.basename(ap),
                "dir": os.path.dirname(rel).replace("\\", "/") or ".",
                "size": st.st_size,
                "mtime": st.st_mtime,
            }
        except Exception:
            pass

    for m in IMG_REF_RE.finditer(raw):
        val = m.group(0)
        if len(val) > 300:
            continue
        rel = resolve_asset_ref(page_path, val, root_path)
        if rel:
            add(os.path.join(page_dir, rel))

    dirs = set()
    for rel in list(out):
        dirs.add(os.path.dirname(os.path.realpath(os.path.join(page_dir, rel))))
    for d in (os.path.join(page_dir, "assets"), os.path.join(os.path.dirname(page_dir), "assets")):
        if os.path.isdir(d):
            dirs.add(os.path.realpath(d))
    root = os.path.realpath(root_path)
    for d in dirs:
        if not (d == root or d.startswith(root + os.sep)):
            continue
        try:
            names = sorted(os.listdir(d))
        except Exception:
            continue
        for n in names[:200]:
            add(os.path.join(d, n))
        if len(out) >= MAX_ASSETS:
            break

    items = sorted(out.values(), key=lambda a: a["rel"].lower())
    return items[:MAX_ASSETS]


# ───────────────────────── 备份 ─────────────────────────
def backup_page(page_id, raw):
    h = hashlib.sha1(page_id.encode("utf-8")).hexdigest()[:12]
    d = os.path.join(BACKUP_DIR, h)
    os.makedirs(d, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S") + "-%03d" % (int(time.time() * 1000) % 1000)
    with open(os.path.join(d, ts + ".html"), "w", encoding="utf-8", newline="\n") as f:
        f.write(raw)
    try:
        with open(os.path.join(d, "page.txt"), "w", encoding="utf-8") as f:
            f.write(page_id)
    except Exception:
        pass
    olds = sorted(fn for fn in os.listdir(d) if fn.endswith(".html"))
    for fn in olds[:-40]:
        try:
            os.remove(os.path.join(d, fn))
        except OSError:
            pass
    return ts


def list_backups(page_id):
    h = hashlib.sha1(page_id.encode("utf-8")).hexdigest()[:12]
    d = os.path.join(BACKUP_DIR, h)
    out = []
    if not os.path.isdir(d):
        return out
    for fn in sorted((x for x in os.listdir(d) if x.endswith(".html")), reverse=True):
        p = os.path.join(d, fn)
        try:
            st = os.stat(p)
        except OSError:
            continue
        out.append({"ts": fn[:-5], "size": st.st_size, "mtime": st.st_mtime})
    return out[:40]


def backup_path(page_id, ts):
    if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[0-9]{3}", ts or ""):
        raise ValueError("版本号不合法")
    h = hashlib.sha1(page_id.encode("utf-8")).hexdigest()[:12]
    p = os.path.join(BACKUP_DIR, h, ts + ".html")
    if not os.path.isfile(p):
        raise ValueError("版本不存在")
    return p


# ───────────────────────── 变更历史（非版本） ─────────────────────────
HISTORY_LIMIT = 80


def _page_hash(page_id):
    return hashlib.sha1(page_id.encode("utf-8")).hexdigest()[:12]


def history_dir(page_id, create=True):
    root = ""
    if (load_config().get("storeMode") or "beside") == "beside":
        try:
            pid, rel = split_id(page_id)
            ap = safe_abs(pid, rel)
            root = os.path.join(os.path.dirname(ap), ".htmlstudio")
        except Exception:
            root = ""
    d = os.path.join(root, "history", _page_hash(page_id)) if root else os.path.join(HISTORY_DIR, _page_hash(page_id))
    if create:
        os.makedirs(d, exist_ok=True)
    return d


def _beside_history_dir(page_id):
    """页面同级的 .htmlstudio/history/<hash>，与当前存储模式无关。"""
    try:
        pid, rel = split_id(page_id)
        ap = safe_abs(pid, rel)
        return os.path.join(os.path.dirname(ap), ".htmlstudio", "history", _page_hash(page_id))
    except Exception:
        return ""


def _history_read_dirs(page_id):
    """读取历史时同时看当前目录、源文件同级目录和旧的应用数据目录，避免切换模式后记录消失。"""
    out, seen = [], set()
    for d in (history_dir(page_id, create=False), _beside_history_dir(page_id),
              os.path.join(HISTORY_DIR, _page_hash(page_id))):
        if not d:
            continue
        k = os.path.normcase(os.path.abspath(d))
        if k in seen:
            continue
        seen.add(k)
        out.append(d)
    return out


def load_history(page_id):
    entries, seen = [], set()
    dirs = _history_read_dirs(page_id)
    for d in dirs:
        data = load_json(os.path.join(d, "index.json"), {})
        if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
            continue
        for e in data["entries"]:
            eid = e.get("id") if isinstance(e, dict) else ""
            if not eid or eid in seen:
                continue
            if not any(os.path.isfile(os.path.join(x, eid + "-after.html")) for x in dirs):
                continue
            seen.add(eid)
            entries.append(e)
    entries.sort(key=lambda e: e.get("ts") or 0, reverse=True)
    return {"pageId": page_id, "entries": entries}


def diff_blocks(before, after):
    """按文本序列对齐后对比，避免某一块被删除/插入后，后续文本全部错位。"""
    old = [ (b.get("text") or "").strip() for b in before ]
    new = [ (b.get("text") or "").strip() for b in after ]
    out = []

    def push(x, y, idx):
        out.append({
            "i": idx,
            "where": (y.get("where") or x.get("where") or ""),
            "tag": (y.get("tag") or x.get("tag") or ""),
            "from": (x.get("text") or "").strip()[:1500],
            "to": (y.get("text") or "").strip()[:1500],
        })

    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        n = min(i2 - i1, j2 - j1)
        for k in range(n):
            push(before[i1 + k], after[j1 + k], i1 + k)
        for k in range(i1 + n, i2):
            push(before[k], {}, k)
        for k in range(j1 + n, j2):
            push({}, after[k], k)
        if len(out) >= 300:
            del out[300:]
            break
    return out


def record_history(page_id, kind, label, before_raw, after_raw, changes, version=""):
    """保存一条变更记录，包含改前 / 改后快照，供对比界面直接加载。"""
    hd = history_dir(page_id)
    eid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:5]
    try:
        with open(os.path.join(hd, eid + "-before.html"), "w", encoding="utf-8", newline="\n") as f:
            f.write(before_raw)
        with open(os.path.join(hd, eid + "-after.html"), "w", encoding="utf-8", newline="\n") as f:
            f.write(after_raw)
    except OSError:
        pass
    rec = {
        "id": eid,
        "ts": time.time(),
        "kind": kind,
        "label": str(label)[:90],
        "version": str(version or "")[:80],
        "changes": changes[:300],
        "changeCount": len(changes),
        "bytesBefore": len(before_raw.encode("utf-8")),
        "bytesAfter": len(after_raw.encode("utf-8")),
    }
    data = load_history(page_id)
    data["entries"].insert(0, rec)
    keep, drop = data["entries"][:HISTORY_LIMIT], data["entries"][HISTORY_LIMIT:]
    for d in drop:
        for key in ("before", "after"):
            try:
                os.remove(os.path.join(hd, d["id"] + "-" + key + ".html"))
            except OSError:
                pass
    data["entries"] = keep
    save_json(os.path.join(hd, "index.json"), data)
    return rec


def history_snapshot(page_id, eid, which):
    if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[0-9a-f]{5}", eid or ""):
        raise ValueError("记录编号不合法")
    if which not in ("before", "after"):
        raise ValueError("快照类型不合法")
    p = os.path.join(history_dir(page_id, create=False), eid + "-" + which + ".html")
    if not os.path.isfile(p):
        p = ""
        for d in _history_read_dirs(page_id):
            cand = os.path.join(d, eid + "-" + which + ".html")
            if os.path.isfile(cand):
                p = cand
                break
    if not p or not os.path.isfile(p):
        raise ValueError("快照不存在")
    return p


def next_version(cur):
    """0.0.1 → 0.0.2；无版本时从 1.0 开始。"""
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", (cur or "").strip())
    if m:
        return "%s.%s.%d" % (m.group(1), m.group(2), int(m.group(3)) + 1)
    m = re.fullmatch(r"v?(\d+)\.(\d+)", (cur or "").strip())
    if m:
        return "%s.%s.1" % (m.group(1), m.group(2))
    return "1.0.0"



# ───────────────────────── 封面 / 导出 ─────────────────────────
BROWSER_LOCK = threading.Semaphore(2)
COVER_LOCKS = {}
COVER_GUARD = threading.Lock()


def find_browser():
    env = os.environ.get("HTMLSTUDIO_BROWSER")
    cands = [env] if env else []
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            cands.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
            cands.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def page_uri(ap):
    return Path(ap).resolve().as_uri()


def run_headless(args, timeout=60):
    browser = find_browser()
    if not browser:
        raise RuntimeError("未找到 Edge/Chrome，无法生成预览或导出")
    profile = os.path.join(tempfile.gettempdir(), "htmlstudio-" + uuid.uuid4().hex[:8])
    cmd = [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
           "--no-first-run", "--no-default-browser-check",
           "--user-data-dir=" + profile] + args
    try:
        with BROWSER_LOCK:
            proc = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=timeout,
                                  creationflags=NO_WINDOW)
        return proc.returncode
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def _cover_lock(page_id):
    with COVER_GUARD:
        lk = COVER_LOCKS.get(page_id)
        if lk is None:
            lk = threading.Lock()
            COVER_LOCKS[page_id] = lk
        return lk


def cover_file(page_id, ap, mtime):
    key = hashlib.sha1(page_id.encode("utf-8")).hexdigest()[:12]
    name = "%s-%d.png" % (key, int(mtime))
    dest = os.path.join(COVER_DIR, name)
    if os.path.isfile(dest) and os.path.getsize(dest) > 1500:
        return dest
    with _cover_lock(page_id):
        if os.path.isfile(dest) and os.path.getsize(dest) > 1500:
            return dest
        run_headless([
            "--force-device-scale-factor=1", "--window-size=1000,640",
            "--virtual-time-budget=3500", "--screenshot=" + dest, page_uri(ap),
        ], timeout=50)
        if not os.path.isfile(dest) or os.path.getsize(dest) < 1500:
            raise RuntimeError("封面生成失败")
        for f in os.listdir(COVER_DIR):
            if f.startswith(key + "-") and f != name:
                try:
                    os.remove(os.path.join(COVER_DIR, f))
                except OSError:
                    pass
    return dest


def export_pdf(ap, out):
    try:
        cdp_export(ap, "pdf", out)
        return
    except Exception as e:
        print("[export] CDP 失败，回退 CLI:", e)
    run_headless(["--no-pdf-header-footer", "--print-to-pdf=" + out,
                  page_uri(ap)], timeout=90)
    if not os.path.isfile(out):
        raise RuntimeError("PDF 生成失败")


def export_png(ap, out):
    try:
        cdp_export(ap, "png", out)
        return
    except Exception as e:
        print("[export] CDP 失败，回退 CLI:", e)
    run_headless([
        "--force-device-scale-factor=1", "--window-size=1440,960",
        "--virtual-time-budget=2500", "--screenshot=" + out, page_uri(ap),
    ], timeout=70)
    if not os.path.isfile(out):
        raise RuntimeError("图片生成失败")


# ───────────────────── CDP 全页导出（等同浏览器打印） ─────────────────────
def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class _WS:
    """极简 WebSocket 客户端，只用于本机 CDP。"""

    def __init__(self, url):
        body = url.split("://", 1)[1]
        host_port, path = body.split("/", 1)
        host, port = host_port.split(":")
        self.sock = socket.create_connection((host, int(port)), timeout=25)
        key = base64.b64encode(os.urandom(16)).decode()
        req = ("GET /" + path + " HTTP/1.1\r\nHost: " + host_port + "\r\n"
               "Upgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: " + key + "\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            d = self.sock.recv(4096)
            if not d:
                raise RuntimeError("WebSocket 握手失败")
            buf += d

    def send(self, obj):
        data = json.dumps(obj).encode("utf-8")
        head = bytearray([0x81])
        n = len(data)
        if n < 126:
            head.append(0x80 | n)
        elif n < 65536:
            head.append(0x80 | 126)
            head += struct.pack(">H", n)
        else:
            head.append(0x80 | 127)
            head += struct.pack(">Q", n)
        mask = os.urandom(4)
        head += mask
        self.sock.sendall(bytes(head) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _read(self, n):
        buf = b""
        while len(buf) < n:
            d = self.sock.recv(n - len(buf))
            if not d:
                raise RuntimeError("WebSocket 连接断开")
            buf += d
        return buf

    def recv(self):
        b1, b2 = self._read(2)
        n = b2 & 0x7F
        if n == 126:
            n = struct.unpack(">H", self._read(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", self._read(8))[0]
        return json.loads(self._read(n).decode("utf-8", "replace"))

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def cdp_export(ap, kind, out):
    browser = find_browser()
    if not browser:
        raise RuntimeError("未找到 Edge/Chrome")
    port = _free_port()
    profile = os.path.join(tempfile.gettempdir(), "htmlstudio-cdp-" + uuid.uuid4().hex[:8])
    proc = subprocess.Popen([
        browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--no-first-run", "--no-default-browser-check",
        "--remote-debugging-port=" + str(port),
        "--user-data-dir=" + profile, "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    ws = None
    try:
        ws_url = ""
        deadline = time.time() + 15
        while time.time() < deadline and not ws_url:
            try:
                with urlopen("http://127.0.0.1:%d/json/list" % port, timeout=2) as r:
                    pages = json.loads(r.read().decode("utf-8"))
                for t in pages:
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        ws_url = t["webSocketDebuggerUrl"]
                        break
            except Exception:
                time.sleep(0.2)
            if not ws_url:
                time.sleep(0.2)
        if not ws_url:
            raise RuntimeError("浏览器调试端口未就绪")
        ws = _WS(ws_url)
        mid = [0]

        def cmd(method, params=None):
            mid[0] += 1
            ws.send({"id": mid[0], "method": method, "params": params or {}})
            while True:
                msg = ws.recv()
                if msg.get("id") == mid[0]:
                    if msg.get("error"):
                        raise RuntimeError(msg["error"].get("message", "CDP 错误"))
                    return msg.get("result", {})

        cmd("Page.enable")
        cmd("Runtime.enable")
        cmd("Emulation.setDeviceMetricsOverride", {
            "width": 1440, "height": 1200, "deviceScaleFactor": 1, "mobile": False,
        })
        ws.send({"id": 9001, "method": "Page.navigate", "params": {"url": page_uri(ap)}})
        t0 = time.time()
        while time.time() - t0 < 30:
            msg = ws.recv()
            if msg.get("method") == "Page.loadEventFired":
                break
        cmd("Runtime.evaluate", {
            "expression": "(document.fonts&&document.fonts.ready)?document.fonts.ready.then(()=>1):1",
            "awaitPromise": True, "returnByValue": True,
        })
        time.sleep(0.9)
        metrics = cmd("Page.getLayoutMetrics")
        size = metrics.get("cssContentSize") or metrics.get("contentSize") or {}
        w = max(320, int(size.get("width") or 1440))
        h = min(40000, max(240, int(size.get("height") or 900)))
        if kind == "png":
            cmd("Emulation.setDeviceMetricsOverride", {
                "width": w, "height": h, "deviceScaleFactor": 1, "mobile": False,
            })
            time.sleep(0.4)
            shot = cmd("Page.captureScreenshot", {
                "format": "png", "captureBeyondViewport": True,
                "clip": {"x": 0, "y": 0, "width": w, "height": h, "scale": 1},
            })
            with open(out, "wb") as f:
                f.write(base64.b64decode(shot["data"]))
        else:
            paper_w = max(4.0, min(60.0, w / 96.0))
            pdf = cmd("Page.printToPDF", {
                "printBackground": True, "preferCSSPageSize": False,
                "paperWidth": round(paper_w, 2), "paperHeight": 11.69,
                "marginTop": 0, "marginBottom": 0, "marginLeft": 0, "marginRight": 0,
            })
            with open(out, "wb") as f:
                f.write(base64.b64decode(pdf["data"]))
        if not os.path.isfile(out) or os.path.getsize(out) < 1200:
            raise RuntimeError("导出结果为空")
    finally:
        if ws:
            ws.close()
        try:
            proc.terminate()
        except Exception:
            pass
        shutil.rmtree(profile, ignore_errors=True)


def safe_filename(title, ext):
    s = re.sub(r'[\\/:*?"<>|\s]+', "-", (title or "page")).strip(" .-")[:60] or "page"
    return s + ext


def zip_pages(ids):
    buf = io.BytesIO()
    used = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for page_id in ids:
            try:
                pid, rel = split_id(page_id)
                ap = safe_abs(pid, rel)
            except Exception:
                continue
            if not os.path.isfile(ap):
                continue
            r = root_by_id(pid) or {}
            arc = (r.get("name") or pid) + "/" + rel.replace("\\", "/")
            arc = re.sub(r'[\\:*?"<>|]+', "-", arc)
            base, ext = os.path.splitext(arc)
            cand, n = arc, 1
            while cand in used:
                n += 1
                cand = "%s-%d%s" % (base, n, ext)
            used.add(cand)
            z.write(ap, cand)
    return buf.getvalue()


# ───────────────────────── 配色库 ─────────────────────────
def load_palettes():
    data = load_json(PALETTE_PATH, {"palettes": []})
    saved = data.get("palettes") if isinstance(data.get("palettes"), list) else []
    by_id = {}
    for p in SEED_PALETTES:
        by_id[p["id"]] = dict(p)
    for p in saved:
        if not isinstance(p, dict) or not p.get("id"):
            continue
        pid = p["id"]
        merged = dict(by_id.get(pid, {}))
        merged.update({
            "id": pid,
            "name": p.get("name") or merged.get("name") or pid,
            "note": p.get("note", merged.get("note", "")),
            "kind": p.get("kind") or merged.get("kind") or "light",
            "tokens": p.get("tokens") if isinstance(p.get("tokens"), dict) else merged.get("tokens", {}),
            "builtin": bool(merged.get("builtin")),
            "createdAt": p.get("createdAt", merged.get("createdAt", 0)),
        })
        by_id[pid] = merged
    out = [by_id[k] for k in by_id]
    out.sort(key=lambda x: (0 if x.get("builtin") else 1, x.get("name", "")))
    return out


def save_palettes_list(pals):
    save_json(PALETTE_PATH, {"palettes": pals})


# ───────────────────────── 交接提示词 ─────────────────────────
def build_handoff(page_id, abs_path, title, goals, notes, palette, provider_name, extra):
    goals = [g for g in (goals or []) if g]
    lines = []
    lines.append("# HTML 页面升级任务 · %s" % (title or os.path.basename(abs_path)))
    lines.append("")
    lines.append("## 目标文件")
    lines.append("")
    lines.append("- 绝对路径：`%s`" % abs_path)
    lines.append("- 页面标识：`%s`" % page_id)
    lines.append("- 目标平台：%s" % (provider_name or "任意 AI Agent"))
    lines.append("")
    lines.append("## 这次想做什么")
    lines.append("")
    if goals:
        for g in goals:
            lines.append("- %s" % g)
    else:
        lines.append("- 按下面的要求优化这个页面。")
    if notes:
        lines.append("")
        lines.append("补充说明：%s" % notes.strip())
    if palette and palette.get("tokens"):
        lines.append("")
        lines.append("## 配色方案 · %s" % palette.get("name", "自定义"))
        lines.append("")
        lines.append("请把这些变量写入页面 `:root`（同名变量直接覆盖，不要新建重复变量）：")
        lines.append("")
        lines.append("```css")
        lines.append(css_from_tokens(palette["tokens"]))
        lines.append("```")
        if palette.get("note"):
            lines.append("")
            lines.append("风格说明：%s" % palette["note"])
    if extra:
        lines.append("")
        lines.append("## 参考卡 / 附加材料")
        lines.append("")
        for e in extra:
            lines.append("- `%s`" % e)
    lines.append("")
    lines.append("## 交付要求")
    lines.append("")
    lines.append("1. 直接改写上面这个文件，保持单文件、零构建、离线可用。")
    lines.append("2. 不要改动与本次目标无关的脚本逻辑与数据结构。")
    lines.append("3. 保留页面原有的语言与文案语气；中英日文切换（如有）必须同步更新。")
    lines.append("4. 改完后自查：页面能直接双击打开、控制台无报错、桌面与 560px 窄屏都不溢出。")
    lines.append("5. 若新增配色，请同时保留 `htmlhub-palette` 注入块，不要删掉已有变量。")
    lines.append("")
    lines.append("---")
    lines.append("由「HTML 工作台」生成 · %s" % time.strftime("%Y-%m-%d %H:%M"))
    return "\n".join(lines)


# ───────────────────────── HTTP ─────────────────────────
class Handler(BaseHTTPRequestHandler):
    server_version = "HTMLStudio/1.0"

    def log_message(self, fmt, *args):
        if getattr(self.server, "verbose", False):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, data, ctype, code=200, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if not (extra and "Cache-Control" in extra):
            self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def send_file(self, ap, download=None):
        if not os.path.isfile(ap):
            self.send_json({"ok": False, "error": "文件不存在"}, 404)
            return
        ctype, _ = mimetypes.guess_type(ap)
        if ap.lower().endswith((".html", ".htm")):
            ctype = "text/html; charset=utf-8"
        elif ap.lower().endswith((".css", ".js", ".json", ".svg", ".md", ".txt")):
            ctype = (ctype or "text/plain") + "; charset=utf-8"
        ctype = ctype or "application/octet-stream"
        with open(ap, "rb") as f:
            data = f.read()
        extra = {}
        if download:
            from urllib.parse import quote
            extra["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(download)
        self.send_bytes(data, ctype, extra=extra)

    def read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            raw = self.rfile.read(n)
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    # ---------- GET ----------
    def do_GET(self):
        u = urlparse(self.path)
        path = unquote(u.path)
        q = parse_qs(u.query)

        if path in ("/", "/index.html"):
            if os.path.exists(INDEX_HTML):
                self.send_file(INDEX_HTML)
            else:
                self.send_json({"ok": False, "error": "index.html 不在同目录"}, 500)
            return

        if path == "/favicon.ico":
            self.send_bytes(b"", "image/x-icon", 204)
            return

        if path == "/api/ping":
            _heartbeat["seen"] = True
            _heartbeat["t"] = time.time()
            self.send_json({"ok": True})
            return

        if path.startswith("/assets/"):
            name = os.path.basename(path[len("/assets/"):])
            ap = os.path.join(BASE_DIR, "assets", name)
            if os.path.isfile(ap):
                self.send_file(ap)
            else:
                self.send_json({"ok": False, "error": "资源不存在"}, 404)
            return

        if path.startswith("/files/"):
            try:
                rest = path[len("/files/"):]
                if "/" not in rest:
                    raise ValueError("缺少路径")
                pid, rel = rest.split("/", 1)
                ap = safe_abs_parent(pid, rel)
                self.send_file(ap)
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 400)
            return

        if path == "/api/meta":
            cfg = load_config()
            pals = load_palettes()
            idx = index_payload()
            self.send_json({
                "ok": True,
                "version": APP_VERSION,
                "name": APP_NAME,
                "roots": idx["roots"],
                "probed": [dict(r) for r in detect_roots()],
                "manual": os.path.exists(CONFIG_PATH),
                "stats": dict(idx["stats"], palettes=len(pals)),
                "providers": cfg.get("providers", []),
                "dataDir": DATA_DIR,
            })
            return

        if path == "/api/index":
            self.send_json(index_payload(force="1" in q.get("force", [])))
            return

        if path == "/api/page":
            try:
                page_id = (q.get("p") or [""])[0]
                pid, rel = split_id(page_id)
                ap = safe_abs(pid, rel)
                if not os.path.isfile(ap):
                    raise ValueError("页面不存在")
                raw = read_text(ap)
                parts = tokenize(raw)
                blocks = blocks_from_parts(parts)
                st = os.stat(ap)
                root_path = root_by_id(pid)["path"]
                elements = scan_elements(raw)
                for e in elements:
                    if e["tag"] == "img":
                        e["resolved"] = resolve_asset_ref(ap, (e["attrs"] or {}).get("src", ""), root_path)
                ver = (load_library()["meta"].get(page_id) or {}).get("version", "")
                self.send_json({
                    "ok": True,
                    "id": page_id,
                    "path": ap,
                    "version": ver,
                    "title": page_title(raw, os.path.splitext(os.path.basename(ap))[0]),
                    "mtime": st.st_mtime,
                    "size": st.st_size,
                    "blocks": [{"i": b["i"], "text": b["text"], "tag": b["tag"],
                                "where": b["where"], "heading": b["heading"]} for b in blocks],
                    "vars": page_vars(raw),
                    "colors": pick_colors(raw, 8),
                    "elements": elements,
                    "assets": page_assets(ap, raw, root_path),
                    "css": injected_css(raw),
                    "hasInjection": bool(PALETTE_STYLE_RE.search(raw)),
                })
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 400)
            return

        if path == "/api/palettes":
            self.send_json({"ok": True, "palettes": load_palettes()})
            return

        if path == "/api/backups":
            try:
                page_id = (q.get("p") or [""])[0]
                pid, rel = split_id(page_id)
                safe_abs(pid, rel)
                self.send_json({"ok": True, "list": list_backups(page_id)})
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 400)
            return

        if path == "/api/backup/raw":
            try:
                page_id = (q.get("p") or [""])[0]
                ts = (q.get("ts") or [""])[0]
                pid, rel = split_id(page_id)
                safe_abs(pid, rel)
                self.send_file(backup_path(page_id, ts))
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 400)
            return

        if path == "/api/storage":
            try:
                page_id = (q.get("p") or [""])[0]
                mode = load_config().get("storeMode") or "beside"
                ap, beside_root = "", ""
                if page_id:
                    pid, rel = split_id(page_id)
                    ap = safe_abs(pid, rel)
                    beside_root = os.path.join(os.path.dirname(ap), ".htmlstudio")
                legacy = os.path.join(HISTORY_DIR, _page_hash(page_id)) if page_id else ""
                self.send_json({
                    "ok": True, "mode": mode, "page": ap, "file": ap,
                    "besideRoot": beside_root,
                    "history": history_dir(page_id, create=False) if page_id else "",
                    "legacy": legacy, "legacyExists": bool(legacy and os.path.isdir(legacy)),
                    "backup": BACKUP_DIR, "exports": EXPORT_DIR, "data": DATA_DIR,
                })
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 400)
            return

        if path == "/api/history":
            try:
                page_id = (q.get("p") or [""])[0]
                pid, rel = split_id(page_id)
                safe_abs(pid, rel)
                hist = load_history(page_id)
                lib = load_library()
                version = (lib["meta"].get(page_id) or {}).get("version", "")
                self.send_json({"ok": True, "pageId": page_id, "version": version,
                                "entries": hist["entries"]})
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 400)
            return

        if path == "/api/history/raw":
            try:
                page_id = (q.get("p") or [""])[0]
                eid = (q.get("e") or [""])[0]
                which = (q.get("which") or ["before"])[0]
                pid, rel = split_id(page_id)
                safe_abs(pid, rel)
                self.send_file(history_snapshot(page_id, eid, which))
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 400)
            return

        if path == "/api/template":
            kind = (q.get("kind") or ["blank"])[0]
            title = (q.get("title") or ["未命名页面"])[0]
            self.send_json({"ok": True, "html": template_html(kind, title)})
            return

        if path == "/api/cover":
            try:
                page_id = (q.get("p") or [""])[0]
                pid, rel = split_id(page_id)
                ap = safe_abs(pid, rel)
                if not os.path.isfile(ap):
                    raise ValueError("页面不存在")
                st = os.stat(ap)
                dest = cover_file(page_id, ap, st.st_mtime)
                with open(dest, "rb") as f:
                    data = f.read()
                self.send_bytes(data, "image/png", extra={"Cache-Control": "public, max-age=604800"})
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 404)
            return

        if path in ("/api/export/pdf", "/api/export/png"):
            try:
                page_id = (q.get("p") or [""])[0]
                pid, rel = split_id(page_id)
                ap = safe_abs(pid, rel)
                if not os.path.isfile(ap):
                    raise ValueError("页面不存在")
                st = os.stat(ap)
                ext = ".pdf" if path.endswith("pdf") else ".png"
                key = hashlib.sha1((page_id + str(st.st_mtime) + ext).encode("utf-8")).hexdigest()[:16]
                out = os.path.join(EXPORT_DIR, key + ext)
                if not os.path.isfile(out):
                    if ext == ".pdf":
                        export_pdf(ap, out)
                    else:
                        export_png(ap, out)
                with open(out, "rb") as f:
                    data = f.read()
                title = page_title(read_text(ap), os.path.splitext(os.path.basename(ap))[0])
                ctype = "application/pdf" if ext == ".pdf" else "image/png"
                self.send_bytes(data, ctype, extra={
                    "Content-Disposition": "attachment; filename*=UTF-8''" + quote(safe_filename(title, ext)),
                    "Cache-Control": "no-store",
                })
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 500)
            return

        if path == "/api/export/zip":
            try:
                ids = [x for x in (q.get("p") or []) if x][:300]
                if not ids:
                    raise ValueError("没有选择页面")
                data = zip_pages(ids)
                name = "html-studio-" + time.strftime("%Y%m%d") + ".zip"
                self.send_bytes(data, "application/zip", extra={
                    "Content-Disposition": "attachment; filename=" + name,
                    "Cache-Control": "no-store",
                })
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 400)
            return

        self.send_json({"ok": False, "error": "未知接口"}, 404)

    # ---------- POST ----------
    def do_POST(self):
        u = urlparse(self.path)
        path = u.path

        try:
            if path == "/api/text":
                self.handle_text_patch()
            elif path == "/api/inline":
                self.handle_inline_patch()
            elif path == "/api/element":
                self.handle_element_patch()
            elif path == "/api/asset":
                self.handle_asset()
            elif path == "/api/save":
                self.handle_save()
            elif path == "/api/palette/apply":
                self.handle_palette_apply()
            elif path == "/api/palette/remove":
                self.handle_palette_remove()
            elif path == "/api/palettes/save":
                self.handle_palette_save()
            elif path == "/api/palettes/delete":
                self.handle_palette_delete()
            elif path == "/api/library":
                self.handle_library()
            elif path == "/api/new":
                self.handle_new()
            elif path == "/api/import":
                self.handle_import()
            elif path == "/api/restore":
                self.handle_restore()
            elif path == "/api/storage":
                self.handle_storage()
            elif path == "/api/version":
                self.handle_set_version()
            elif path == "/api/pin":
                self.handle_pin()
            elif path == "/api/handoff":
                self.handle_handoff()
            elif path == "/api/reveal":
                self.handle_reveal()
            elif path == "/api/open":
                self.handle_open()
            elif path == "/api/roots/save":
                self.handle_roots_save()
            elif path == "/api/roots/add":
                self.handle_roots_add()
            elif path == "/api/roots/reset":
                self.handle_roots_reset()
            else:
                self.send_json({"ok": False, "error": "未知接口"}, 404)
        except Exception as e:
            self.send_json({"ok": False, "error": str(e)}, 400)

    # ---------- handlers ----------
    def handle_library(self):
        data = self.read_body()
        lib = load_library()
        act = data.get("action")
        if act == "meta":
            pid = str(data.get("id") or "").strip()
            if not pid:
                raise ValueError("缺少页面")
            rec = lib["meta"].get(pid, {})
            for f in ("alias", "version"):
                if f in data:
                    v = str(data.get(f) or "").strip()[:80]
                    if v:
                        rec[f] = v
                    else:
                        rec.pop(f, None)
            if "collection" in data:
                c = str(data.get("collection") or "").strip()[:40]
                if c:
                    rec["collection"] = c
                else:
                    rec.pop("collection", None)
            if rec:
                lib["meta"][pid] = rec
            else:
                lib["meta"].pop(pid, None)
        elif act == "bulk":
            ids = [str(x) for x in (data.get("ids") or []) if x]
            c = str(data.get("collection") or "").strip()[:40]
            for pid in ids:
                rec = lib["meta"].get(pid, {})
                if c:
                    rec["collection"] = c
                else:
                    rec.pop("collection", None)
                if rec:
                    lib["meta"][pid] = rec
                else:
                    lib["meta"].pop(pid, None)
        elif act == "collection.add":
            name = str(data.get("name") or "").strip()[:60]
            if not name:
                raise ValueError("分类名不能为空")
            cid = "c" + uuid.uuid4().hex[:8]
            lib["collections"].append({"id": cid, "name": name})
        elif act == "collection.rename":
            cid = str(data.get("id") or "").strip()
            name = str(data.get("name") or "").strip()[:60]
            if not cid or not name:
                raise ValueError("分类名不能为空")
            hit = False
            for c in lib["collections"]:
                if c["id"] == cid:
                    c["name"] = name
                    hit = True
            if not hit:
                raise ValueError("分类不存在")
        elif act == "collection.remove":
            cid = str(data.get("id") or "").strip()
            lib["collections"] = [c for c in lib["collections"] if c["id"] != cid]
            for k, v in list(lib["meta"].items()):
                if v.get("collection") == cid:
                    v.pop("collection", None)
                    if not v:
                        lib["meta"].pop(k, None)
        else:
            raise ValueError("未知操作")
        save_library(lib)
        self.send_json({"ok": True, "library": lib})

    def handle_text_patch(self):
        data = self.read_body()
        page_id = data.get("p", "")
        edits = data.get("edits") or []
        pid, rel = split_id(page_id)
        ap = safe_abs(pid, rel)
        if not os.path.isfile(ap):
            raise ValueError("页面不存在")
        raw = read_text(ap)
        parts = tokenize(raw)
        blocks = blocks_from_parts(parts)
        changed = 0
        for e in edits:
            idx = int(e.get("i", -1))
            new = e.get("text", "")
            orig = e.get("orig", "")
            if idx < 0 or idx >= len(blocks):
                raise ValueError("文本块编号越界，请刷新后重试")
            b = blocks[idx]
            if b["text"] != orig:
                raise ValueError("页面内容已变化（%s），请刷新后重试" % (b["where"] or b["tag"]))
            if new == orig:
                continue
            parts[b["ti"]][1] = b["pre"] + escape_text(new) + b["post"]
            changed += 1
        if not changed:
            self.send_json({"ok": True, "changed": 0, "message": "没有改动"})
            return
        out = "".join(p[1] for p in parts)
        script_hits = 0
        for e in edits:
            orig = e.get("orig", "")
            new = e.get("text", "")
            if orig and new and orig != new:
                out, n = sync_script_texts(out, orig, new)
                script_hits += n
        ts = backup_page(page_id, raw)
        atomic_write(ap, out)
        _cache["t"] = 0
        _meta_cache.pop(ap, None)
        parts2 = tokenize(out)
        blocks2 = blocks_from_parts(parts2)
        changes = diff_blocks(blocks, blocks2)
        ver = (load_library()["meta"].get(page_id) or {}).get("version", "")
        try:
            record_history(page_id, "text", "文本 · %d 处" % changed, raw, out, changes, ver)
        except Exception:
            pass
        self.send_json({
            "ok": True,
            "changed": changed,
            "backup": ts,
            "mtime": os.stat(ap).st_mtime,
            "blocks": [{"i": b["i"], "text": b["text"], "tag": b["tag"],
                        "where": b["where"], "heading": b["heading"]} for b in blocks2],
            "vars": page_vars(out),
            "colors": pick_colors(out, 8),
        })

    def handle_inline_patch(self):
        data = self.read_body()
        page_id = data.get("p", "")
        idx = int(data.get("i", -1))
        orig = str(data.get("orig") or "")
        sel = str(data.get("sel") or "")
        css = clean_inline_style(data.get("style") or {})
        if not sel:
            raise ValueError("先选中要改的文字")
        pid, rel = split_id(page_id)
        ap = safe_abs(pid, rel)
        if not os.path.isfile(ap):
            raise ValueError("页面不存在")
        raw = read_text(ap)
        parts = tokenize(raw)
        blocks = blocks_from_parts(parts)
        if idx < 0 or idx >= len(blocks):
            raise ValueError("文本块编号越界，请刷新后重试")
        b = blocks[idx]
        if b["text"] != orig:
            raise ValueError("页面内容已变化（%s），请刷新后重试" % (b["where"] or b["tag"]))
        tok = parts[b["ti"]][1]
        cut = len(tok) - len(b["post"]) if b["post"] else len(tok)
        core = html.unescape(tok[len(b["pre"]):cut])
        if core != orig:
            raise ValueError("这段文字的源码结构较复杂，请刷新后重试")
        start = data.get("start")
        if not (isinstance(start, int) and 0 <= start <= len(core) - len(sel) and core[start:start + len(sel)] == sel):
            start = core.find(sel)
            if start < 0:
                raise ValueError("这段文字已变化，请重新选择")
            if core.find(sel, start + 1) >= 0:
                raise ValueError("同一段里有重复文字，请只选中其中一处")
        end = start + len(sel)
        wrap = '<span style="%s">%s</span>' % (css, escape_text(sel))
        parts[b["ti"]][1] = b["pre"] + escape_text(core[:start]) + wrap + escape_text(core[end:]) + b["post"]
        out = "".join(p[1] for p in parts)
        ts = backup_page(page_id, raw)
        atomic_write(ap, out)
        _cache["t"] = 0
        _meta_cache.pop(ap, None)
        try:
            changes = diff_blocks(blocks, blocks_from_parts(tokenize(out)))
            ver = (load_library()["meta"].get(page_id) or {}).get("version", "")
            record_history(page_id, "text", "文字样式 · 1 处", raw, out, changes, ver)
        except Exception:
            pass
        self.send_json({"ok": True, "backup": ts, "mtime": os.stat(ap).st_mtime})

    def handle_element_patch(self):
        data = self.read_body()
        page_id = data.get("p", "")
        edits = data.get("edits") or []
        if not edits:
            raise ValueError("没有要修改的元素")
        pid, rel = split_id(page_id)
        ap = safe_abs(pid, rel)
        if not os.path.isfile(ap):
            raise ValueError("页面不存在")
        raw = read_text(ap)
        out, changed = apply_element_edits(raw, edits)
        if not changed:
            self.send_json({"ok": True, "changed": 0, "message": "没有改动"})
            return
        ts = backup_page(page_id, raw)
        atomic_write(ap, out)
        _cache["t"] = 0
        _meta_cache.pop(ap, None)
        try:
            ver = (load_library()["meta"].get(page_id) or {}).get("version", "")
            record_history(page_id, "element", "元素 · %d 处" % changed, raw, out, [], ver)
        except Exception:
            pass
        self.send_json({"ok": True, "changed": changed, "backup": ts,
                        "mtime": os.stat(ap).st_mtime})

    def handle_asset(self):
        data = self.read_body()
        page_id = data.get("p", "")
        pid, rel = split_id(page_id)
        ap = safe_abs(pid, rel)
        if not os.path.isfile(ap):
            raise ValueError("页面不存在")
        blob = str(data.get("data") or "")
        m = re.match(r"^data:image/(png|jpeg|jpg|gif|webp|avif);base64,([A-Za-z0-9+/=\s]+)$", blob, re.I | re.S)
        if not m:
            raise ValueError("只支持 PNG / JPG / GIF / WebP / AVIF 图片")
        ext = {"png": ".png", "jpeg": ".jpg", "jpg": ".jpg",
               "gif": ".gif", "webp": ".webp", "avif": ".avif"}[m.group(1).lower()]
        try:
            buf = base64.b64decode(re.sub(r"\s+", "", m.group(2)), validate=True)
        except Exception:
            raise ValueError("图片数据无法解析")
        if not buf:
            raise ValueError("图片为空")
        if len(buf) > 8 * 1024 * 1024:
            raise ValueError("图片不能超过 8MB")
        target = str(data.get("target") or "").strip().replace("\\", "/")
        if target:
            page_dir = os.path.dirname(ap)
            dest = os.path.realpath(os.path.join(page_dir, target))
            root = os.path.realpath(root_by_id(pid)["path"])
            if dest == root or not dest.startswith(root + os.sep):
                raise ValueError("图片路径越界")
            if not os.path.isfile(dest):
                raise ValueError("目标图片不存在")
            t_ext = os.path.splitext(dest)[1].lower()
            if t_ext not in IMG_EXT:
                raise ValueError("目标不是图片文件")
            allow = {".jpg", ".jpeg"} if t_ext in (".jpg", ".jpeg") else {t_ext}
            if ext not in allow:
                raise ValueError("请选择同格式图片（%s）" % t_ext)
            bdir = os.path.join(page_dir, ".htmlstudio", "asset-backups")
            os.makedirs(bdir, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            shutil.copy2(dest, os.path.join(bdir, stamp + "-" + os.path.basename(dest)))
            tmp = dest + ".htmlhub-tmp"
            with open(tmp, "wb") as f:
                f.write(buf)
            os.replace(tmp, dest)
            rel_target = os.path.relpath(dest, page_dir).replace("\\", "/")
            self.send_json({"ok": True, "rel": rel_target, "size": len(buf),
                            "name": os.path.basename(dest), "mtime": os.stat(dest).st_mtime})
            return
        stem = os.path.splitext(os.path.basename(str(data.get("name") or "image")))[0]
        stem = re.sub(r"[^\w\u4e00-\u9fa5.-]+", "-", stem).strip(".-")[:48] or "image"
        adir = os.path.join(os.path.dirname(ap), "assets")
        os.makedirs(adir, exist_ok=True)
        base = stem
        n = 1
        while os.path.exists(os.path.join(adir, stem + ext)):
            stem = base + "-%d" % n
            n += 1
        with open(os.path.join(adir, stem + ext), "wb") as f:
            f.write(buf)
        self.send_json({"ok": True, "rel": "assets/" + stem + ext,
                        "size": len(buf), "name": stem + ext})

    def handle_save(self):
        data = self.read_body()
        page_id = data.get("p", "")
        text = data.get("text", "")
        pid, rel = split_id(page_id)
        ap = safe_abs(pid, rel)
        if not os.path.isfile(ap):
            raise ValueError("页面不存在")
        raw = read_text(ap)
        ts = backup_page(page_id, raw)
        atomic_write(ap, text)
        _cache["t"] = 0
        _meta_cache.pop(ap, None)
        try:
            changes = diff_blocks(blocks_from_parts(tokenize(raw)), blocks_from_parts(tokenize(text)))
            ver = (load_library()["meta"].get(page_id) or {}).get("version", "")
            record_history(page_id, "text", "整体保存 · %d 处" % len(changes), raw, text, changes, ver)
        except Exception:
            pass
        self.send_json({"ok": True, "backup": ts, "mtime": os.stat(ap).st_mtime,
                        "bytes": len(text.encode("utf-8"))})

    def handle_palette_apply(self):
        data = self.read_body()
        page_id = data.get("p", "")
        tokens = data.get("tokens") or {}
        pid, rel = split_id(page_id)
        ap = safe_abs(pid, rel)
        if not os.path.isfile(ap):
            raise ValueError("页面不存在")
        clean = {}
        for k, v in tokens.items():
            k = str(k).strip()
            v = str(v).strip()
            if not re.fullmatch(r"--[A-Za-z0-9_-]+", k) or not v or len(v) > 80:
                continue
            if re.search(r"[;{}<>]", v):
                continue
            clean[k] = v
        if not clean:
            raise ValueError("没有可应用的变量")
        raw = read_text(ap)
        ts = backup_page(page_id, raw)
        out = inject_css(raw, css_from_tokens(clean))
        atomic_write(ap, out)
        _cache["t"] = 0
        _meta_cache.pop(ap, None)
        try:
            ver = (load_library()["meta"].get(page_id) or {}).get("version", "")
            vars_changed = []
            for k, v in clean.items():
                vars_changed.append({"i": -1, "where": k, "tag": "css", "from": "", "to": v})
            record_history(page_id, "palette", "配色 · %d 个变量" % len(clean), raw, out, vars_changed, ver)
        except Exception:
            pass
        self.send_json({"ok": True, "applied": len(clean), "backup": ts,
                        "css": injected_css(out), "mtime": os.stat(ap).st_mtime})

    def handle_palette_remove(self):
        data = self.read_body()
        page_id = data.get("p", "")
        pid, rel = split_id(page_id)
        ap = safe_abs(pid, rel)
        if not os.path.isfile(ap):
            raise ValueError("页面不存在")
        raw = read_text(ap)
        if not PALETTE_STYLE_RE.search(raw):
            self.send_json({"ok": True, "removed": False, "message": "没有注入配色"})
            return
        ts = backup_page(page_id, raw)
        out = PALETTE_STYLE_RE.sub("", raw, count=1)
        atomic_write(ap, out)
        _cache["t"] = 0
        _meta_cache.pop(ap, None)
        try:
            ver = (load_library()["meta"].get(page_id) or {}).get("version", "")
            record_history(page_id, "palette", "移除配色注入", raw, out, [], ver)
        except Exception:
            pass
        self.send_json({"ok": True, "removed": True, "backup": ts})

    def handle_palette_save(self):
        data = self.read_body()
        card = data.get("card") or {}
        tokens = card.get("tokens") or {}
        clean = {}
        for k, v in tokens.items():
            k = str(k).strip()
            v = str(v).strip()
            if re.fullmatch(r"--[A-Za-z0-9_-]+", k) and v and len(v) <= 80:
                clean[k] = v
        if not clean:
            raise ValueError("配色卡没有变量")
        name = (card.get("name") or "").strip()[:40]
        if not name:
            raise ValueError("配色卡需要名字")
        pid = "u-" + hashlib.sha1((name + str(time.time())).encode("utf-8")).hexdigest()[:10]
        new = {
            "id": pid, "name": name,
            "note": (card.get("note") or "").strip()[:160],
            "kind": card.get("kind") if card.get("kind") in ("light", "dark") else "light",
            "tokens": clean, "builtin": False, "createdAt": time.time(),
        }
        data_all = load_json(PALETTE_PATH, {"palettes": []})
        saved = [p for p in data_all.get("palettes", []) if isinstance(p, dict)]
        saved.append(new)
        save_palettes_list(saved)
        self.send_json({"ok": True, "palette": new, "palettes": load_palettes()})

    def handle_palette_delete(self):
        data = self.read_body()
        pid = data.get("id", "")
        if pid in SEED_PALETTES_BY_ID:
            raise ValueError("内置配色不能删除")
        data_all = load_json(PALETTE_PATH, {"palettes": []})
        saved = [p for p in data_all.get("palettes", []) if isinstance(p, dict) and p.get("id") != pid]
        save_palettes_list(saved)
        self.send_json({"ok": True, "palettes": load_palettes()})

    def handle_new(self):
        data = self.read_body()
        pid = data.get("root", "")
        sub = (data.get("dir") or "").replace("\\", "/").strip("/")
        name = (data.get("name") or "").strip()
        title = (data.get("title") or os.path.splitext(name)[0] or "未命名页面").strip()
        kind = data.get("template") or "blank"
        if not name:
            raise ValueError("文件名不能为空")
        if not os.path.splitext(name)[1]:
            name += ".html"
        if os.path.splitext(name)[1].lower() not in (".html", ".htm"):
            raise ValueError("只能新建 HTML 文件")
        if name != re.sub(r'[\\/:*?"<>|]', "-", name):
            raise ValueError("文件名包含非法字符")
        rel = (sub + "/" + name) if sub else name
        ap = safe_abs(pid, rel)
        if os.path.exists(ap):
            raise ValueError("同名文件已存在")
        atomic_write(ap, template_html(kind, title))
        _cache["t"] = 0
        self.send_json({"ok": True, "id": pid + "/" + rel})

    def handle_import(self):
        data = self.read_body()
        pid = data.get("root", "")
        sub = (data.get("dir") or "").replace("\\", "/").strip("/")
        files = data.get("files") or []
        if not isinstance(files, list) or not files:
            raise ValueError("没有收到文件")
        out = []
        for f in files[:80]:
            name = os.path.basename((f.get("name") or "").replace("\\", "/")).strip()
            if not name:
                continue
            if os.path.splitext(name)[1].lower() not in (".html", ".htm"):
                continue
            text = f.get("text") or ""
            if len(text.encode("utf-8", "ignore")) > 8 * 1024 * 1024:
                continue
            base, ext = os.path.splitext(name)
            n = 1
            rel = (sub + "/" + name) if sub else name
            while os.path.exists(safe_abs(pid, rel)):
                n += 1
                rel = ((sub + "/" if sub else "") + "%s-%d%s" % (base, n, ext))
            ap = safe_abs(pid, rel)
            atomic_write(ap, text)
            out.append(pid + "/" + rel)
        if not out:
            raise ValueError("没有有效的 HTML 文件")
        _cache["t"] = 0
        self.send_json({"ok": True, "imported": out, "count": len(out)})

    def handle_restore(self):
        data = self.read_body()
        page_id = data.get("p", "")
        ts = data.get("ts", "")
        pid, rel = split_id(page_id)
        ap = safe_abs(pid, rel)
        if not os.path.isfile(ap):
            raise ValueError("页面不存在")
        src = backup_path(page_id, ts)
        with open(src, encoding="utf-8") as f:
            restored = f.read()
        raw = read_text(ap)
        backup_page(page_id, raw)
        atomic_write(ap, restored)
        _cache["t"] = 0
        _meta_cache.pop(ap, None)
        try:
            changes = diff_blocks(blocks_from_parts(tokenize(raw)), blocks_from_parts(tokenize(restored)))
            ver = (load_library()["meta"].get(page_id) or {}).get("version", "")
            record_history(page_id, "restore", "恢复备份 · %s" % ts, raw, restored, changes, ver)
        except Exception:
            pass
        self.send_json({"ok": True, "mtime": os.stat(ap).st_mtime})

    def handle_set_version(self):
        """把当前内容标记为一个版本；不自动升版本，由用户显式确认。"""
        data = self.read_body()
        page_id = str(data.get("p") or "").strip()
        label = str(data.get("label") or "").strip()[:80]
        if not page_id:
            raise ValueError("缺少页面")
        pid, rel = split_id(page_id)
        ap = safe_abs(pid, rel)
        if not os.path.isfile(ap):
            raise ValueError("页面不存在")
        lib = load_library()
        rec = lib["meta"].get(page_id, {})
        if not label:
            label = next_version(rec.get("version") or "")
        rec["version"] = label
        lib["meta"][page_id] = rec
        save_library(lib)
        raw = read_text(ap)
        try:
            record_history(page_id, "version", "标记版本 · %s" % label, raw, raw, [], label)
        except Exception:
            pass
        self.send_json({"ok": True, "version": label, "mtime": os.stat(ap).st_mtime})

    def handle_pin(self):
        data = self.read_body()
        page_id = data.get("p", "")
        pinned = bool(data.get("pinned"))
        cfg = load_config(force=True)
        pins = [x for x in cfg.get("pins", []) if x != page_id]
        if pinned:
            pins.insert(0, page_id)
        cfg["pins"] = pins
        save_config(cfg)
        self.send_json({"ok": True, "pinned": pinned, "pins": pins})

    def handle_handoff(self):
        data = self.read_body()
        page_id = data.get("p", "")
        goals = data.get("goals") or []
        notes = data.get("notes") or ""
        palette = data.get("palette") or {}
        extra = [x for x in (data.get("extra") or []) if isinstance(x, str)]
        provider = data.get("provider") or ""
        pid, rel = split_id(page_id)
        ap = safe_abs(pid, rel)
        if not os.path.isfile(ap):
            raise ValueError("页面不存在")
        cfg = load_config()
        pname = provider
        for p in cfg.get("providers", []):
            if p.get("id") == provider:
                pname = p.get("name")
        raw = read_text(ap)
        title = page_title(raw, os.path.splitext(os.path.basename(ap))[0])
        md = build_handoff(page_id, ap, title, goals, notes, palette, pname, extra)
        self.send_json({"ok": True, "markdown": md, "title": title, "path": ap,
                        "filename": re.sub(r'[\\/:*?"<>|]', "-", (title or "handoff"))[:60] + "-交接.md"})

    def handle_storage(self):
        data = self.read_body()
        mode = str(data.get("mode") or "").strip()
        if mode not in ("beside", "data"):
            raise ValueError("未知存储模式")
        cfg = load_config(force=True)
        cfg["storeMode"] = mode
        save_config(cfg)
        self.send_json({"ok": True, "mode": mode, "data": DATA_DIR})

    def handle_reveal(self):
        data = self.read_body()
        if data.get("dir"):
            d = os.path.normpath(str(data.get("dir")))
            allowed = [DATA_DIR] + [r["path"] for r in load_config()["roots"]]
            low = d.lower()
            if not any(low == a.lower() or low.startswith(a.lower() + os.sep) for a in allowed):
                raise ValueError("路径不在允许范围")
            os.makedirs(d, exist_ok=True)
            subprocess.Popen(["explorer", d.replace("/", "\\")], creationflags=NO_WINDOW)
            self.send_json({"ok": True})
            return
        pid, rel = split_id(data.get("p", ""))
        ap = safe_abs(pid, rel)
        if not os.path.exists(ap):
            raise ValueError("文件不存在")
        subprocess.Popen(["explorer", "/select,", ap.replace("/", "\\")],
                         creationflags=NO_WINDOW)
        self.send_json({"ok": True})

    def handle_open(self):
        data = self.read_body()
        pid, rel = split_id(data.get("p", ""))
        ap = safe_abs(pid, rel)
        if not os.path.isfile(ap):
            raise ValueError("文件不存在")
        os.startfile(ap)
        self.send_json({"ok": True})

    def handle_roots_save(self):
        data = self.read_body()
        raw = data.get("roots")
        if not isinstance(raw, list) or not raw:
            raise ValueError("至少保留一个内容根")
        clean, seen = [], set()
        for r in raw:
            p = os.path.normpath((r.get("path") or "").strip())
            if not p:
                continue
            if not os.path.isdir(p):
                raise ValueError("目录不存在：" + p)
            rid = (r.get("id") or "r").strip().replace(" ", "_")[:32]
            while rid in seen:
                rid += "_2"
            seen.add(rid)
            clean.append({"id": rid, "name": (r.get("name") or os.path.basename(p))[:48], "path": p})
        if not clean:
            raise ValueError("没有有效目录")
        cfg = load_config(force=True)
        cfg["roots"] = clean
        save_config(cfg)
        self.send_json({"ok": True, "roots": clean})

    def handle_roots_add(self):
        data = self.read_body()
        raw = (data.get("path") or "").strip().strip('"').strip("'")
        if not raw:
            raise ValueError("路径不能为空")
        p = os.path.normpath(os.path.expanduser(raw))
        if not os.path.isdir(p):
            raise ValueError("目录不存在：" + p)
        self.send_json({"ok": True, "root": {
            "id": "u_" + re.sub(r"[^A-Za-z0-9]+", "_", os.path.basename(p))[:20],
            "name": os.path.basename(p) or p, "path": p,
        }})

    def handle_roots_reset(self):
        if os.path.exists(CONFIG_PATH):
            os.remove(CONFIG_PATH)
        _cfg_cache["cfg"] = None
        _cache["t"] = 0
        _meta_cache.clear()
        cfg = load_config(force=True)
        self.send_json({"ok": True, "roots": cfg["roots"], "probed": detect_roots()})


# ───────────────────────── 新建模板 ─────────────────────────
def template_html(kind, title):
    title = html.escape(title or "未命名页面")
    if kind == "article":
        body = """
  <main class="page">
    <header class="head">
      <p class="kicker">NOTE · %s</p>
      <h1>%s</h1>
      <p class="lead">这里写导语：一句话说清这页要解决什么问题。</p>
    </header>
    <article class="body">
      <h2>第一节</h2>
      <p>把结论放在第一段，再补证据。段落之间留出呼吸感，别堆满屏。</p>
      <h2>第二节</h2>
      <p>可以用引用、列表和表格，但每块只承担一个意思。</p>
    </article>
  </main>""" % (time.strftime("%Y.%m.%d"), title)
        extra_css = """
  .page{max-width:760px;margin:0 auto;padding:72px 28px 120px}
  .kicker{font:500 11px/1 var(--mono,monospace);letter-spacing:.2em;color:var(--terra,#b65f42);text-transform:uppercase}
  h1{font-size:clamp(32px,5vw,52px);line-height:1.15;letter-spacing:-.02em;margin:18px 0 0}
  .lead{color:var(--muted,#746d63);font-size:17px;line-height:1.9;margin-top:16px}
  .body{margin-top:56px}
  .body h2{font-size:22px;margin:42px 0 12px}
  .body p{color:var(--ink,#29251f);font-size:16px;line-height:2;margin:12px 0}"""
    elif kind == "dashboard":
        body = """
  <main class="wrap">
    <header class="top">
      <div>
        <p class="kicker">DASHBOARD</p>
        <h1>%s</h1>
      </div>
      <span class="stamp">更新于 %s</span>
    </header>
    <section class="cards">
      <div class="card"><span>指标一</span><b>128</b><em>+12%% 环比</em></div>
      <div class="card"><span>指标二</span><b>64%%</b><em>目标 70%%</em></div>
      <div class="card"><span>指标三</span><b>¥ 8.6k</b><em>本月累计</em></div>
      <div class="card"><span>指标四</span><b>3.2h</b><em>平均处理时长</em></div>
    </section>
    <section class="panel">
      <h2>趋势</h2>
      <div class="chart"><i style="--h:38%%"></i><i style="--h:56%%"></i><i style="--h:44%%"></i><i style="--h:72%%"></i><i style="--h:61%%"></i><i style="--h:84%%"></i><i style="--h:76%%"></i></div>
    </section>
  </main>""" % (title, time.strftime("%Y-%m-%d"))
        extra_css = """
  .wrap{max-width:1080px;margin:0 auto;padding:56px 28px 100px}
  .top{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap}
  h1{font-size:clamp(28px,4vw,42px);line-height:1.2;margin:10px 0 0}
  .stamp{font:500 11px/1 var(--mono,monospace);color:var(--faint,#9a9186)}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin-top:36px}
  .card{background:var(--surface,#fffdfa);border:1px solid var(--line,#ded5c8);border-radius:16px;padding:20px}
  .card span{font-size:12px;color:var(--muted,#746d63)}
  .card b{display:block;font-size:32px;margin:8px 0 4px;letter-spacing:-.02em}
  .card em{font-style:normal;font-size:12px;color:var(--sage,#627a67)}
  .panel{background:var(--surface,#fffdfa);border:1px solid var(--line,#ded5c8);border-radius:18px;padding:24px;margin-top:16px}
  .chart{display:flex;align-items:flex-end;gap:10px;height:180px;margin-top:20px}
  .chart i{flex:1;height:var(--h);background:linear-gradient(180deg,var(--terra,#b65f42),color-mix(in srgb,var(--terra,#b65f42) 40%%,transparent));border-radius:6px 6px 0 0}"""
    elif kind == "palette":
        body = """
  <main class="wrap">
    <p class="kicker">PALETTE CARD</p>
    <h1>%s</h1>
    <p class="lead">把这张卡放到工作台里，就能一键把配色注入其他 HTML。</p>
    <section class="swatches">
      <i style="--c:#f5f0e8"></i><i style="--c:#fffdfa"></i><i style="--c:#ded5c8"></i>
      <i style="--c:#4d3045"></i><i style="--c:#b65f42"></i><i style="--c:#627a67"></i>
      <i style="--c:#29251f"></i><i style="--c:#a57c45"></i>
    </section>
    <section class="meta">
      <div><span>底色</span><b>#f5f0e8</b></div>
      <div><span>正文</span><b>#29251f</b></div>
      <div><span>强调</span><b>#4d3045</b></div>
      <div><span>点缀</span><b>#b65f42</b></div>
    </section>
  </main>""" % title
        extra_css = """
  .wrap{max-width:860px;margin:0 auto;padding:64px 28px 100px}
  h1{font-size:clamp(30px,4.6vw,46px);margin:14px 0 0;letter-spacing:-.02em}
  .lead{color:var(--muted,#746d63);line-height:1.9;margin-top:14px}
  .swatches{display:grid;grid-template-columns:repeat(8,1fr);gap:8px;margin:44px 0 10px;height:120px}
  .swatches i{background:var(--c);border:1px solid rgba(0,0,0,.06);border-radius:10px}
  .meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
  .meta div{background:var(--surface,#fffdfa);border:1px solid var(--line,#ded5c8);border-radius:12px;padding:14px}
  .meta span{display:block;font-size:11px;color:var(--muted,#746d63);margin-bottom:6px}
  .meta b{font-family:var(--mono,monospace);font-size:13px}"""
    elif kind == "landing":
        body = """
  <main>
    <section class="hero">
      <p class="kicker">LANDING</p>
      <h1>%s</h1>
      <p class="lead">一句话说清卖点，再用三个证据把人留住。</p>
      <div class="cta"><a class="btn" href="#">开始使用</a><a class="btn ghost" href="#">看看细节</a></div>
    </section>
    <section class="grid">
      <div class="cell"><b>01</b><h3>先讲结论</h3><p>每块只回答一个问题，不写形容词堆砌。</p></div>
      <div class="cell"><b>02</b><h3>再给证据</h3><p>数字、截图、真实场景，比排比句有用。</p></div>
      <div class="cell"><b>03</b><h3>最后给动作</h3><p>一个明确按钮，别让人猜下一步。</p></div>
    </section>
  </main>""" % title
        extra_css = """
  .hero{max-width:900px;margin:0 auto;padding:110px 28px 60px;text-align:center}
  h1{font-size:clamp(36px,6vw,64px);line-height:1.1;letter-spacing:-.03em;margin:18px 0 0}
  .lead{color:var(--muted,#746d63);font-size:17px;line-height:1.9;margin:18px auto 0;max-width:520px}
  .cta{display:flex;gap:12px;justify-content:center;margin-top:30px;flex-wrap:wrap}
  .btn{display:inline-flex;padding:12px 22px;border-radius:999px;background:var(--plum,#4d3045);color:#fff;font-size:14px}
  .btn.ghost{background:transparent;color:var(--ink,#29251f);border:1px solid var(--line-strong,#cfc4b7)}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;max-width:1000px;margin:0 auto;padding:0 28px 100px}
  .cell{background:var(--surface,#fffdfa);border:1px solid var(--line,#ded5c8);border-radius:18px;padding:26px}
  .cell b{font-family:var(--mono,monospace);font-size:11px;color:var(--terra,#b65f42)}
  .cell h3{font-size:18px;margin:12px 0 8px}
  .cell p{color:var(--muted,#746d63);font-size:14px;line-height:1.85}"""
    else:
        body = """
  <main class="page">
    <p class="kicker">BLANK</p>
    <h1>%s</h1>
    <p class="lead">从这里开始写第一句话。</p>
  </main>""" % title
        extra_css = """
  .page{max-width:720px;margin:0 auto;padding:96px 28px}
  h1{font-size:clamp(30px,5vw,46px);margin:14px 0 0;letter-spacing:-.02em}
  .lead{color:var(--muted,#746d63);line-height:1.9;margin-top:14px}"""

    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>%s</title>
<style>
  :root{
    --paper:#f5f0e8; --surface:#fffdfa; --surface-2:#eee7dd;
    --ink:#29251f; --muted:#746d63; --faint:#9a9186;
    --line:#ded5c8; --line-strong:#cfc4b7;
    --plum:#4d3045; --terra:#b65f42; --sage:#627a67; --sand:#a57c45;
    --radius:22px;
    --sans:"PingFang SC","Microsoft YaHei","Segoe UI",system-ui,sans-serif;
    --mono:"Cascadia Mono",Consolas,monospace;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--paper);color:var(--ink);font-family:var(--sans);-webkit-font-smoothing:antialiased;line-height:1.7}
  a{color:inherit;text-decoration:none}
  .kicker{font-family:var(--mono);font-size:11px;letter-spacing:.2em;color:var(--terra);text-transform:uppercase}
%s
</style>
</head>
<body>%s
</body>
</html>
""" % (title, extra_css, body)


# ───────────────────────── 启动 ─────────────────────────
def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class ExclusiveHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False


def heartbeat_watchdog(srv):
    """打包运行时：浏览器页面全部关闭后自动关闭服务。"""
    while True:
        time.sleep(4)
        if _heartbeat["seen"] and time.time() - _heartbeat["t"] > HEARTBEAT_TIMEOUT:
            srv.shutdown()
            return


def main():
    ensure_dirs()
    host, port, verbose, list_only = "127.0.0.1", 8781, False, False
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--port" and i + 1 < len(args):
            port = int(args[i + 1]); i += 2; continue
        if a == "--host" and i + 1 < len(args):
            host = args[i + 1]; i += 2; continue
        if a in ("--verbose", "-v"):
            verbose = True
        if a == "--list":
            list_only = True
        i += 1

    if list_only:
        for it in scan(force=True):
            print("%6.1fKB  %-10s %s" % (it["size"] / 1024, it["root"], it["rel"]))
        print("共 %d 个 HTML" % len(scan()))
        return

    srv, used_port = None, None
    for try_port in range(port, min(port + 40, 65535)):
        try:
            srv = ExclusiveHTTPServer((host, try_port), Handler)
            used_port = try_port
            break
        except OSError:
            continue
    if srv is None:
        print("端口 %d 起连续 40 个都被占用，无法启动" % port)
        return
    srv.verbose = verbose

    stats = index_payload(force=True)
    print("=== %s v%s ===" % (APP_NAME, APP_VERSION))
    print("本机 http://127.0.0.1:%d/" % used_port)
    if host == "0.0.0.0":
        print("局域网 http://%s:%d/" % (lan_ip(), used_port))
    print("已收录 %d 个 HTML，内容根 %d 个" % (stats["stats"]["pages"], stats["stats"]["roots"]))
    for r in load_config()["roots"]:
        print("  %s → %s" % (r["name"], r["path"]))

    if FROZEN:
        threading.Thread(target=heartbeat_watchdog, args=(srv,), daemon=True).start()

    if "--no-browser" not in args:
        threading.Timer(0.8, lambda: webbrowser.open("http://127.0.0.1:%d/" % used_port)).start()

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
