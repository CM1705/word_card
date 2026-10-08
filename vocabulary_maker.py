#!/usr/bin/env python3
"""Portable local vocabulary-card editor with embedded Edge TTS support."""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import sys
import threading
import time
import webbrowser
from collections import OrderedDict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import edge_tts


APP_TITLE = "单词卡制作器"
APP_VERSION = "1.10.0"
VOICE = "en-US-GuyNeural"
RESOURCE_NAME = "vocabulary-v001.html"
MAX_REQUEST_BYTES = 4096
MAX_DEFAULT_PROJECT_BYTES = 50 * 1024 * 1024
MAX_TEXT_LENGTH = 80
MAX_AUDIO_BYTES = 2 * 1024 * 1024
IDLE_SHUTDOWN_SECONDS = 60 * 60
PAGE_CLOSE_GRACE_SECONDS = 4.0
PAGE_SESSION_STALE_SECONDS = 150.0
PAGE_MONITOR_INTERVAL_SECONDS = 0.25
PAGE_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{12,96}")
APP_DATA_PATTERN = re.compile(
    r'(<script(?=[^>]*\btype=["\']application/json["\'])(?=[^>]*\bid=["\']app-data["\'])[^>]*>)'
    r'([\s\S]*?)(</script\s*>)',
    flags=re.I,
)


def bundle_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def executable_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def saved_default_path() -> Path:
    override = os.environ.get("VOCAB_MAKER_DEFAULT_PATH", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    base = Path(local_app_data) if local_app_data else Path.home() / ".vocabulary-card-maker"
    return base / "VocabularyCardMaker" / "default-project.json"


def show_error(message: str) -> None:
    if os.name == "nt":
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, APP_TITLE, 0x10)
    else:
        print(f"{APP_TITLE}: {message}", file=sys.stderr)


def find_requested_project() -> Path | None:
    for raw in sys.argv[1:]:
        candidate = Path(raw.strip('"')).expanduser()
        if candidate.is_file() and candidate.suffix.lower() in {".html", ".htm"}:
            return candidate.resolve()
    return None


def validate_project_data(data: object) -> dict[str, object]:
    if not isinstance(data, dict):
        raise ValueError("单词卡版本格式不受支持。")
    words = data.get("words")
    if data.get("schemaVersion") != 1 or not isinstance(words, list):
        raise ValueError("单词卡版本格式不受支持。")
    if data.get("voice") != VOICE:
        raise ValueError("所选单词卡使用了不同的固定声音。")
    if len(words) > 2000:
        raise ValueError("词条数量超过支持范围。")
    seen_ids: set[str] = set()
    seen_words: set[str] = set()
    for item in words:
        if not isinstance(item, dict):
            raise ValueError("单词卡中存在不完整的词条。")
        item_id = item.get("id")
        word = item.get("word")
        meaning = item.get("meaning")
        if not isinstance(item_id, str) or not item_id or len(item_id) > 128:
            raise ValueError("单词卡中存在无效的词条编号。")
        if not isinstance(word, str) or not word.strip() or len(word) > MAX_TEXT_LENGTH:
            raise ValueError("单词卡中存在无效的单词。")
        if not isinstance(meaning, str) or not meaning.strip() or len(meaning) > 4000:
            raise ValueError(f"“{word}”缺少有效释义。")
        word_key = word.strip().casefold()
        if item_id in seen_ids or word_key in seen_words:
            raise ValueError("单词卡中存在重复词条。")
        seen_ids.add(item_id)
        seen_words.add(word_key)
        phrases = item.get("phrases", [])
        if not isinstance(phrases, list) or len(phrases) > 100:
            raise ValueError(f"“{word}”的短语格式不受支持。")
        for phrase in phrases:
            if not isinstance(phrase, dict):
                raise ValueError(f"“{word}”的短语格式不受支持。")
            if not isinstance(phrase.get("en", ""), str) or not isinstance(phrase.get("zh", ""), str):
                raise ValueError(f"“{word}”的短语格式不受支持。")
        audio_data = item.get("audioData", "")
        audio_text = item.get("audioText", "")
        if not isinstance(audio_data, str) or not isinstance(audio_text, str):
            raise ValueError(f"“{word}”的固定发音格式不受支持。")
        if audio_data and not audio_data.startswith("data:audio/mpeg;base64,"):
            raise ValueError(f"“{word}”的固定发音格式不受支持。")
    return data


def validate_project_html(source: str) -> dict[str, object]:
    match = APP_DATA_PATTERN.search(source)
    if not match:
        raise ValueError("所选文件不是可继续编辑的单词卡版本。")
    try:
        data = json.loads(match.group(2))
    except json.JSONDecodeError as exc:
        raise ValueError("单词卡中的数据已损坏。") from exc
    return validate_project_data(data)


def load_saved_default() -> dict[str, object] | None:
    path = saved_default_path()
    if not path.is_file() or path.stat().st_size > MAX_DEFAULT_PROJECT_BYTES:
        return None
    try:
        return validate_project_data(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None


def save_default_project(project: dict[str, object]) -> None:
    project = validate_project_data(project)
    payload = json.dumps(project, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_DEFAULT_PROJECT_BYTES:
        raise ValueError("默认内容超过 50 MB，无法保存。")
    path = saved_default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + secrets.token_hex(6))
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def embed_project_data(shell: str, project: dict[str, object]) -> str:
    match = APP_DATA_PATTERN.search(shell)
    if not match:
        raise ValueError("内置制作界面缺少单词卡数据位置。")
    payload = json.dumps(project, ensure_ascii=False, separators=(",", ":"))
    payload = (
        payload.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    return shell[: match.start(2)] + payload + shell[match.end(2) :]


def load_html() -> str:
    requested = find_requested_project()
    default_path = bundle_dir() / RESOURCE_NAME
    if not default_path.is_file() and not getattr(sys, "frozen", False):
        default_path = Path(__file__).resolve().parent / "exe-assets" / RESOURCE_NAME
    if not default_path.is_file():
        raise FileNotFoundError(f"找不到内置页面：{default_path}")
    shell = default_path.read_text(encoding="utf-8")
    validate_project_html(shell)
    if requested is not None:
        if requested.stat().st_size > MAX_DEFAULT_PROJECT_BYTES:
            raise ValueError("单词卡文件超过 50 MB，无法打开。")
        project = validate_project_html(requested.read_text(encoding="utf-8"))
        project["appVersion"] = APP_VERSION
        return embed_project_data(shell, project)
    saved = load_saved_default()
    if saved is None:
        return shell
    saved["appVersion"] = APP_VERSION
    return embed_project_data(shell, saved)


class AudioCache:
    def __init__(self, limit: int = 256) -> None:
        self.limit = limit
        self.items: OrderedDict[str, bytes] = OrderedDict()
        self.lock = threading.Lock()

    def get(self, text: str) -> bytes | None:
        with self.lock:
            value = self.items.get(text)
            if value is not None:
                self.items.move_to_end(text)
            return value

    def put(self, text: str, audio: bytes) -> None:
        with self.lock:
            self.items[text] = audio
            self.items.move_to_end(text)
            while len(self.items) > self.limit:
                self.items.popitem(last=False)


async def synthesize_audio(text: str) -> bytes:
    audio = bytearray()
    communicate = edge_tts.Communicate(
        text,
        VOICE,
        connect_timeout=10,
        receive_timeout=60,
    )
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
            if len(audio) > MAX_AUDIO_BYTES:
                raise ValueError("生成的音频超过大小限制。")
    if not audio:
        raise RuntimeError("语音服务没有返回音频。")
    return bytes(audio)


class VocabularyServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        html_source: str,
        port: int = 0,
        *,
        page_close_grace: float = PAGE_CLOSE_GRACE_SECONDS,
        page_session_stale: float = PAGE_SESSION_STALE_SECONDS,
    ) -> None:
        super().__init__(("127.0.0.1", port), VocabularyHandler)
        self.token = secrets.token_urlsafe(32)
        self.html_source = self._inject_token(html_source)
        self.cache = AudioCache()
        self.tts_slots = threading.BoundedSemaphore(2)
        self.default_lock = threading.Lock()
        self.last_activity = time.monotonic()
        self.page_served = False
        self.page_close_grace = page_close_grace
        self.page_session_stale = page_session_stale
        self.page_sessions: dict[str, float] = {}
        self.closed_page_ids: dict[str, float] = {}
        self.page_lock = threading.Lock()
        self.empty_since: float | None = None
        self.last_page_delivery = 0.0
        self.last_lifecycle_check = time.monotonic()
        self.page_shutdown_started = False
        self.lifecycle_stop = threading.Event()

    def _inject_token(self, source: str) -> bytes:
        pattern = r'(<meta\s+name="local-app-token"\s+content=")[^"]*(">)'
        updated, count = re.subn(pattern, rf"\g<1>{self.token}\g<2>", source, count=1, flags=re.I)
        if count != 1:
            raise ValueError("单词卡缺少本地制作器标记，无法安全启动。")
        return updated.encode("utf-8")

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    def note_page_load(self) -> None:
        with self.page_lock:
            now = time.monotonic()
            self.page_served = True
            self.last_page_delivery = now
            self.page_shutdown_started = False
            if not self.page_sessions:
                self.empty_since = now

    def page_open(self, page_id: str) -> bool:
        with self.page_lock:
            if page_id in self.closed_page_ids:
                return False
            self.page_sessions[page_id] = time.monotonic()
            self.empty_since = None
            self.page_shutdown_started = False
            return True

    def page_heartbeat(self, page_id: str) -> bool:
        with self.page_lock:
            if page_id not in self.page_sessions:
                return False
            self.page_sessions[page_id] = time.monotonic()
            return True

    def page_close(self, page_id: str) -> None:
        with self.page_lock:
            now = time.monotonic()
            self.page_sessions.pop(page_id, None)
            self.closed_page_ids[page_id] = now
            if not self.page_sessions:
                self.empty_since = now

    def page_lifecycle_should_shutdown(self) -> bool:
        now = time.monotonic()
        with self.page_lock:
            check_gap = now - self.last_lifecycle_check
            self.last_lifecycle_check = now
            if check_gap > 30.0:
                for page_id in self.page_sessions:
                    self.page_sessions[page_id] = now
                if self.empty_since is not None:
                    self.empty_since = now
                if self.page_served:
                    self.last_page_delivery = now
            expired = [
                page_id
                for page_id, last_seen in self.page_sessions.items()
                if now - last_seen > self.page_session_stale
            ]
            for page_id in expired:
                self.page_sessions.pop(page_id, None)
            tombstone_limit = self.page_session_stale * 2
            for page_id, closed_at in list(self.closed_page_ids.items()):
                if now - closed_at > tombstone_limit:
                    self.closed_page_ids.pop(page_id, None)
            if expired and not self.page_sessions and self.empty_since is None:
                self.empty_since = now
            if (
                not self.page_served
                or self.page_sessions
                or self.empty_since is None
                or self.page_shutdown_started
            ):
                return False
            empty_reference = max(self.empty_since, self.last_page_delivery)
            if now - empty_reference < self.page_close_grace:
                return False
            self.page_shutdown_started = True
            return True

    def close_lifecycle(self) -> None:
        self.lifecycle_stop.set()


class VocabularyHandler(BaseHTTPRequestHandler):
    server: VocabularyServer
    server_version = f"VocabularyMaker/{APP_VERSION}"
    sys_version = ""

    COMMON_HEADERS: ClassVar[dict[str, str]] = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Cross-Origin-Resource-Policy": "same-origin",
    }

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _send_headers(self, status: int, content_type: str, length: int = 0) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        for name, value in self.COMMON_HEADERS.items():
            self.send_header(name, value)
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
            "connect-src 'self'; media-src data: blob:; img-src data:; font-src 'none'; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
        )
        self.end_headers()

    def _json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_headers(status, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def _authorized(self) -> bool:
        supplied = self.headers.get("X-Vocabulary-Token", "")
        return secrets.compare_digest(supplied, self.server.token)

    def _valid_host(self) -> bool:
        host = self.headers.get("Host", "")
        port = self.server.server_address[1]
        return host in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def do_GET(self) -> None:  # noqa: N802
        if not self._valid_host():
            self._json(HTTPStatus.MISDIRECTED_REQUEST, {"error": "Host not allowed"})
            return
        self.server.touch()
        path = self.path.split("?", 1)[0]
        if path in {"/", "/index.html"}:
            self.server.note_page_load()
            body = self.server.html_source
            self._send_headers(HTTPStatus.OK, "text/html; charset=utf-8", len(body))
            self.wfile.write(body)
            return
        if path in {"/health", "/healthz"}:
            self._json(HTTPStatus.OK, {"ok": True, "version": APP_VERSION, "voice": VOICE})
            return
        if path == "/favicon.ico":
            self._send_headers(HTTPStatus.NO_CONTENT, "image/x-icon", 0)
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._valid_host():
            self._json(HTTPStatus.MISDIRECTED_REQUEST, {"error": "Host not allowed"})
            return
        path = self.path.split("?", 1)[0]
        if not self._authorized():
            self._json(HTTPStatus.FORBIDDEN, {"error": "请求未通过本地制作器验证。"})
            return
        self.server.touch()
        if path == "/shutdown":
            self._json(HTTPStatus.OK, {"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if path == "/v1/default":
            payload = self._read_json_payload(MAX_DEFAULT_PROJECT_BYTES)
            if payload is None:
                return
            try:
                project = validate_project_data(payload.get("project"))
                project["appVersion"] = APP_VERSION
                with self.server.default_lock:
                    save_default_project(project)
                    current = self.server.html_source.decode("utf-8")
                    self.server.html_source = embed_project_data(current, project).encode("utf-8")
            except ValueError as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            except OSError as exc:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"保存默认内容失败：{exc}"})
                return
            self._json(HTTPStatus.OK, {"ok": True, "wordCount": len(project["words"])})
            return
        if path in {"/v1/page/open", "/v1/page/heartbeat", "/v1/page/close"}:
            payload = self._read_json_payload()
            if payload is None:
                return
            page_id = payload.get("pageId")
            if not isinstance(page_id, str) or PAGE_ID_PATTERN.fullmatch(page_id) is None:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "页面标识不正确。"})
                return
            if path.endswith("/open"):
                accepted = self.server.page_open(page_id)
            elif path.endswith("/heartbeat"):
                accepted = self.server.page_heartbeat(page_id)
            else:
                self.server.page_close(page_id)
                accepted = True
            if not accepted:
                self._json(HTTPStatus.CONFLICT, {"error": "页面会话已经结束，请刷新页面。"})
                return
            self._json(HTTPStatus.OK, {"ok": True})
            return
        if path != "/v1/tts":
            self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return

        payload = self._read_json_payload()
        if payload is None:
            return
        raw_text = payload.get("text", "")
        if not isinstance(raw_text, str):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "单词必须是文本。"})
            return
        text = raw_text.strip()
        requested_voice = str(payload.get("voice", VOICE))
        if requested_voice != VOICE:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "只允许使用固定的 Guy 声音。"})
            return
        if not text or len(text) > MAX_TEXT_LENGTH or any(ord(char) < 32 for char in text):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "单词为空或长度不符合要求。"})
            return

        cached = self.server.cache.get(text)
        if cached is not None:
            self._send_audio(cached)
            return
        try:
            with self.server.tts_slots:
                cached = self.server.cache.get(text)
                if cached is None:
                    cached = asyncio.run(synthesize_audio(text))
                    self.server.cache.put(text, cached)
            self._send_audio(cached)
        except Exception as exc:  # edge-tts exposes several network exception types
            self._json(HTTPStatus.BAD_GATEWAY, {"error": f"固定发音生成失败：{exc}"})

    def _send_audio(self, audio: bytes) -> None:
        self._send_headers(HTTPStatus.OK, "audio/mpeg", len(audio))
        self.wfile.write(audio)

    def _read_json_payload(self, max_bytes: int = MAX_REQUEST_BYTES) -> dict[str, object] | None:
        if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
            self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "请求必须使用 JSON 格式。"})
            return None
        raw_length = self.headers.get("Content-Length", "")
        try:
            length = int(raw_length)
        except ValueError:
            length = -1
        if length < 1 or length > max_bytes:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "请求内容过大。"})
            return None
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "请求格式不正确。"})
            return None
        if not isinstance(payload, dict):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "请求格式不正确。"})
            return None
        return payload


def idle_monitor(server: VocabularyServer) -> None:
    while not server.lifecycle_stop.wait(PAGE_MONITOR_INTERVAL_SECONDS):
        if server.page_lifecycle_should_shutdown():
            server.shutdown()
            return
        if server.page_served and time.monotonic() - server.last_activity > IDLE_SHUTDOWN_SECONDS:
            server.shutdown()
            return


def main() -> int:
    try:
        html_source = load_html()
        requested_port = int(os.environ.get("VOCAB_MAKER_PORT", "0"))
        server = VocabularyServer(html_source, requested_port)
    except Exception as exc:
        show_error(str(exc))
        return 1

    if "--self-test" in sys.argv:
        server.server_close()
        return 0

    host, port = server.server_address
    url = f"http://{host}:{port}/"
    threading.Thread(target=idle_monitor, args=(server,), daemon=True).start()
    if os.environ.get("VOCAB_MAKER_NO_BROWSER") != "1":
        threading.Timer(0.5, lambda: webbrowser.open_new_tab(url)).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.close_lifecycle()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
