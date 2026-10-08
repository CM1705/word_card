#!/usr/bin/env python3
"""No-network API tests for the portable vocabulary maker."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import vocabulary_maker as app


FAKE_MP3 = b"\xff\xfb\x90\x64" + (b"vocabulary-maker-test" * 80)
calls: list[str] = []


async def fake_synthesize(text: str) -> bytes:
    calls.append(text)
    return FAKE_MP3


def request(url: str, *, method: str = "GET", payload=None, token: str = ""):
    headers = {}
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["X-Vocabulary-Token"] = token
    return urlopen(Request(url, data=body, headers=headers, method=method), timeout=5)


def expect_http_error(status: int, *args, **kwargs) -> None:
    try:
        request(*args, **kwargs)
    except HTTPError as error:
        assert error.code == status, (error.code, status, error.read())
        assert json.loads(error.read().decode("utf-8") or "{}") if False else True
        return
    raise AssertionError(f"Expected HTTP {status}")


def start_lifecycle_server(source: str, *, grace: float = 0.2, stale: float = 5.0):
    server = app.VocabularyServer(
        source,
        page_close_grace=grace,
        page_session_stale=stale,
    )
    serve_thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.03},
    )
    monitor_thread = threading.Thread(target=app.idle_monitor, args=(server,), daemon=True)
    serve_thread.start()
    monitor_thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    with request(base + "/") as response:
        page = response.read().decode("utf-8")
    token_match = re.search(r'<meta name="local-app-token" content="([^"]+)">', page)
    assert token_match
    return server, serve_thread, base, token_match.group(1)


def stop_lifecycle_server(server, serve_thread) -> None:
    if serve_thread.is_alive():
        server.shutdown()
        serve_thread.join(timeout=2)
    server.close_lifecycle()
    server.server_close()


def test_page_lifecycle(source: str) -> None:
    page_a = "page-session-a-0001"
    page_b = "page-session-b-0002"

    server, thread, base, token = start_lifecycle_server(source)
    try:
        expect_http_error(403, base + "/v1/page/open", method="POST", payload={"pageId": page_a})
        with request(base + "/v1/page/open", method="POST", payload={"pageId": page_a}, token=token) as response:
            assert response.status == 200
        with request(base + "/v1/page/heartbeat", method="POST", payload={"pageId": page_a}, token=token) as response:
            assert response.status == 200
        with request(base + "/v1/page/close", method="POST", payload={"pageId": page_a}, token=token) as response:
            assert response.status == 200
        assert thread.is_alive(), "关闭宽限期内不应立即退出"
        expect_http_error(409, base + "/v1/page/heartbeat", method="POST", payload={"pageId": page_a}, token=token)
        expect_http_error(409, base + "/v1/page/open", method="POST", payload={"pageId": page_a}, token=token)
        thread.join(timeout=2)
        assert not thread.is_alive(), "最后一个页面关闭后服务没有自动退出"
    finally:
        stop_lifecycle_server(server, thread)

    server, thread, base, token = start_lifecycle_server(source, grace=0.3)
    try:
        request(base + "/v1/page/open", method="POST", payload={"pageId": page_a}, token=token).close()
        request(base + "/v1/page/close", method="POST", payload={"pageId": page_a}, token=token).close()
        request(base + "/").close()
        request(base + "/v1/page/open", method="POST", payload={"pageId": page_b}, token=token).close()
        time.sleep(0.55)
        assert thread.is_alive(), "刷新页面被误判为关闭"
        request(base + "/v1/page/close", method="POST", payload={"pageId": page_b}, token=token).close()
        thread.join(timeout=2)
        assert not thread.is_alive(), "刷新后的页面关闭后服务没有退出"
    finally:
        stop_lifecycle_server(server, thread)

    server, thread, base, token = start_lifecycle_server(source, grace=0.2)
    try:
        request(base + "/v1/page/open", method="POST", payload={"pageId": page_a}, token=token).close()
        request(base + "/v1/page/open", method="POST", payload={"pageId": page_b}, token=token).close()
        request(base + "/v1/page/close", method="POST", payload={"pageId": page_a}, token=token).close()
        time.sleep(0.4)
        assert thread.is_alive(), "关闭一个标签页不应影响另一个标签页"
        request(base + "/v1/page/heartbeat", method="POST", payload={"pageId": page_b}, token=token).close()
        request(base + "/v1/page/close", method="POST", payload={"pageId": page_b}, token=token).close()
        thread.join(timeout=2)
        assert not thread.is_alive(), "全部标签页关闭后服务没有退出"
    finally:
        stop_lifecycle_server(server, thread)

    server, thread, base, token = start_lifecycle_server(source, grace=0.15, stale=0.15)
    try:
        request(base + "/v1/page/open", method="POST", payload={"pageId": page_a}, token=token).close()
        thread.join(timeout=2)
        assert not thread.is_alive(), "页面异常消失后心跳租约没有回收服务"
    finally:
        stop_lifecycle_server(server, thread)


def main() -> None:
    default_temp = tempfile.TemporaryDirectory()
    default_path = Path(default_temp.name) / "default-project.json"
    os.environ["VOCAB_MAKER_DEFAULT_PATH"] = str(default_path)
    assert app.APP_VERSION == "1.10.0"
    app.synthesize_audio = fake_synthesize
    source = app.load_html()
    initial_project = app.validate_project_html(source)
    assert len(initial_project["words"]) == 38
    assert initial_project["words"][-1]["word"] == "error"
    assert '<meta name="vocabulary-app-version" content="1.10.0">' in source
    assert '<title>编程单词卡</title>' in source
    assert 'name="vocabulary-version"' not in source
    assert 'document.title =' not in source
    assert "var fileName = '编程单词卡.html'" in source
    assert '<body data-editing="false" data-exported="false">' in source
    assert "dataset.exported = 'true'" in source
    assert 'body[data-exported="true"] .hero' in source
    assert 'body[data-exported="true"] #toggleEditButton { display: none !important; }' in source
    assert 'id="searchInput"' in source
    assert 'id="categoryFilter"' in source
    assert '.word-card:nth-child(4n + 1)' in source
    assert '.word-card:nth-child(4n)' in source
    assert 'var PALETTES' not in source
    assert 'id="clearAllButton"' in source
    assert 'id="saveDefaultButton"' in source
    assert "fetch('/v1/default'" in source
    assert 'id="batchDeleteButton"' in source
    assert 'id="batchDeleteBackdrop"' in source
    assert 'function deleteSelectedWords()' in source
    assert '<meta name="local-app-token" content="">' in source
    legacy_project = app.validate_project_html(source)
    legacy_project["appVersion"] = "0.9.0"
    legacy_project["words"][0]["phraseTitle"] = "自定义短语标题"
    merged = app.embed_project_data(source, legacy_project)
    merged_project = app.validate_project_html(merged)
    assert '<meta name="vocabulary-app-version" content="1.10.0">' in merged
    assert '<body data-editing="false" data-exported="false">' in merged
    assert merged_project["appVersion"] == "0.9.0"
    assert merged_project["words"][0]["phraseTitle"] == "自定义短语标题"
    server = app.VocabularyServer(source)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with request(base + "/") as response:
            page = response.read().decode("utf-8")
            assert response.status == 200
            assert response.headers.get_content_type() == "text/html"
        token_match = re.search(r'<meta name="local-app-token" content="([^"]+)">', page)
        assert token_match and token_match.group(1)
        token = token_match.group(1)
        assert token not in source
        assert "界面 v1.10.0" in page
        assert "卡片 v003" not in page
        assert "<title>编程单词卡</title>" in page
        assert "导入单词卡" in page
        assert "导出新单词卡" in page
        assert "批量删除" in page
        assert "清空全部单词" in page
        assert "保存为默认内容" in page
        assert "退出制作器" not in page

        with request(base + "/healthz") as response:
            health = json.loads(response.read())
            assert health == {"ok": True, "version": app.APP_VERSION, "voice": app.VOICE}

        expect_http_error(403, base + "/v1/tts", method="POST", payload={"text": "hello"})
        expect_http_error(403, base + "/v1/default", method="POST", payload={"project": initial_project})
        expect_http_error(400, base + "/v1/tts", method="POST", payload={"text": 123}, token=token)
        expect_http_error(400, base + "/v1/tts", method="POST", payload={"text": "hello", "voice": "other"}, token=token)
        expect_http_error(400, base + "/v1/default", method="POST", payload={"project": {}}, token=token)

        saved_project = app.validate_project_html(source)
        saved_project["words"] = saved_project["words"][:2]
        with request(
            base + "/v1/default",
            method="POST",
            payload={"project": saved_project},
            token=token,
        ) as response:
            saved_result = json.loads(response.read())
            assert saved_result == {"ok": True, "wordCount": 2}
        assert default_path.is_file()
        assert len(json.loads(default_path.read_text(encoding="utf-8"))["words"]) == 2
        assert len(app.validate_project_html(app.load_html())["words"]) == 2
        with request(base + "/") as response:
            refreshed_page = response.read().decode("utf-8")
        assert len(app.validate_project_html(refreshed_page)["words"]) == 2

        with request(base + "/v1/tts", method="POST", payload={"text": "  hello  "}, token=token) as response:
            assert response.status == 200
            assert response.headers.get_content_type() == "audio/mpeg"
            assert response.read() == FAKE_MP3
        with request(base + "/v1/tts", method="POST", payload={"text": "hello"}, token=token) as response:
            assert response.read() == FAKE_MP3
        assert calls == ["hello"], calls

        with request(base + "/shutdown", method="POST", payload={}, token=token) as response:
            assert response.status == 200
        thread.join(timeout=3)
        assert not thread.is_alive(), "Server did not shut down"
    finally:
        if thread.is_alive():
            server.shutdown()
            thread.join(timeout=3)
        server.server_close()
    test_page_lifecycle(source)
    default_temp.cleanup()
    print("本地制作器 API 测试通过")


if __name__ == "__main__":
    main()
