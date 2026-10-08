# 编程单词卡（word_card）

一个**单文件离线单词卡**：词汇、音标、释义、短语、固定发音音频和完整编辑界面全部内嵌在**一个 HTML 文件**里，双击就能看、能听、能改；配套一个免安装的 Windows 制作器 `单词卡制作器.exe`，负责联网生成固定发音、管理默认词库，并把编辑结果导出成新的单文件 HTML。

- 界面版本：**v1.10.0**
- 内置词库：**38** 个编程词汇，每词 1 段 `en-US-GuyNeural` 男声固定发音（base64 内嵌，离线可听）
- 成品 HTML **不需要联网**；只有「在线生成固定发音」这一步会调用微软 Edge TTS

## 下载（免安装，只下载 exe 即可）

### [⬇ 点此下载最新版 VocabularyCardMaker.exe](https://github.com/CM1705/word_card/releases/latest/download/VocabularyCardMaker.exe)

这个链接始终指向**最新版本**，约 16 MB，不需要 GitHub 账号，也不用下载整个项目。

下载后**双击即可运行**，不需要安装 Python 或任何依赖。首次运行若遇到 Windows SmartScreen 提示，选择「更多信息 → 仍要运行」即可（程序未做代码签名）。

> 附件名为何是英文的 `VocabularyCardMaker.exe`：GitHub 会剔除 Release 附件名中的非 ASCII 字符，中文文件名会被清空并回退成 `default.exe`。程序内部显示的名称仍是「单词卡制作器」。

## 目录结构

| 路径 | 说明 |
| --- | --- |
| `vocabulary_maker.py` | 制作器本体：本地 HTTP 服务、Edge TTS 代理、默认词库读写、页面生命周期管理 |
| `unified-template.html` | 统一模板：同一份文件既是成品单词卡、也是编辑界面（含 `__APP_VERSION__` / `__APP_DATA__` 占位符） |
| `default-vocabulary.html` | 默认词库数据源（旧版单词本，内含 38 个词及其固定音频） |
| `build_unified.py` | 把数据源注入模板，生成 `exe-assets/vocabulary-v001.html` |
| `exe-assets/vocabulary-v001.html` | 构建产物：最终单文件 HTML，同时也是 EXE 内置的默认页面 |
| `vocabulary_maker.spec` | PyInstaller 打包配置（单文件、无控制台、内嵌 assets） |
| `vocabulary_maker_version.txt` | Windows 文件版本信息（1.10.0） |
| `.gitignore` | 忽略 `__pycache__`、`exe-build/`、`exe-dist/`、`可运行/` 等中间产物与成品 |
| `.gitattributes` | 统一 LF 换行，并把 `.exe` 标为二进制防止被转换 |

> 免安装的 `VocabularyCardMaker.exe` **不放在仓库里**（否则克隆项目要多下载 16 MB 二进制），而是作为 Release 附件单独分发，见上方「下载」一节。

## 快速开始（普通用户，推荐）

1. 从上方「下载」一节获取 `VocabularyCardMaker.exe`
2. 双击运行 —— 会自动用默认浏览器打开制作器页面
3. 点 **✎ 编辑单词** 进入编辑模式，可 **＋ 添加单词**、编辑、**批量删除**、**清空全部单词**，或按住卡片拖动调整顺序
4. 新单词在编辑弹窗里点 **在线生成固定发音**（此步需要联网）
5. 点 **↓ 导出新单词卡**，会下载 `编程单词卡.html` —— 这就是可以离线分发的成品

小技巧：

- 把已有的单词卡 HTML **拖到 EXE 图标上**，可以直接打开那份词库继续编辑
- 点 **★ 保存为默认内容**，把当前词库存为默认（下次打开即为此内容），保存在 `%LOCALAPPDATA%\VocabularyCardMaker\default-project.json`
- 关掉所有页面后制作器会自动退出（约 4 秒宽限，用来避免刷新被误判为关闭）；闲置 1 小时也会自动退出

## 开发环境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install edge-tts pyinstaller
```

## 常用命令

| 目的 | 命令 |
| --- | --- |
| 重新生成单文件页面 | `python build_unified.py` |
| 本地启动制作器 | `python vocabulary_maker.py` |
| 只做启动自检（不启服务） | `python vocabulary_maker.py --self-test` |
| 接口测试（不需要网络） | `python test_maker_server.py`（本机脚本，未入库） |
| 校验构建产物 | `node verify_unified.mjs`（本机脚本，未入库） |
| 打包 EXE | `pyinstaller vocabulary_maker.spec --noconfirm --clean --workpath exe-build --distpath exe-dist` |

打包完成后，把 `exe-dist/单词卡制作器.exe` 复制到 `可运行/`，即为可发布的免安装版本（`可运行/` 已在 `.gitignore` 中，不会进入仓库）。

发布新版本让别人能单独下载 exe：在 GitHub 仓库页面进入 **Releases → Draft a new release**，填好 tag（例如 `v1.11.0`），把 `可运行/单词卡制作器.exe` 拖进附件区即可。

> ⚠️ 附件名**必须用 ASCII**（例如 `VocabularyCardMaker.exe`）。GitHub 会剔除附件名中的非 ASCII 字符，中文名会被清空并回退成 `default.exe`，导致 `releases/latest/download/...` 直链失效。

## 环境变量

| 变量 | 作用 |
| --- | --- |
| `VOCAB_MAKER_PORT` | 固定监听端口（默认 `0`，即随机端口） |
| `VOCAB_MAKER_NO_BROWSER` | 设为 `1` 时不自动打开浏览器 |
| `VOCAB_MAKER_DEFAULT_PATH` | 覆盖「默认内容」JSON 的保存路径 |

## 数据格式

每个单词卡 HTML 内都嵌有一段 `<script type="application/json" id="app-data">`：

```json
{
  "schemaVersion": 1,
  "voice": "en-US-GuyNeural",
  "version": 3,
  "appVersion": "1.10.0",
  "words": [
    {
      "id": "3f1c…",
      "word": "print",
      "phonetic": "[prɪnt]",
      "category": "function",
      "meaning": "输出/打印：把内容显示到屏幕上。",
      "phraseTitle": "短语搭配",
      "phrases": [{ "en": "print()", "zh": "打印函数" }],
      "audioText": "print",
      "audioData": "data:audio/mpeg;base64,……"
    }
  ]
}
```

约束：

- `voice` 固定为 `en-US-GuyNeural`，其他声音会被拒绝
- 单词（忽略大小写）不可重复
- 只有 `audioText === word` 且 `audioData` 存在时，才被视为「有固定发音」，可导出到成品

## 安全说明

制作器只监听 `127.0.0.1`，每次启动生成随机 token 并注入页面，所有 POST 请求都必须携带 `X-Vocabulary-Token`；服务端同时校验 `Host` 头，页面 CSP 禁止外部脚本、外部样式和远程媒体。所以成品 HTML 是**完全自包含**的，不依赖任何在线资源。

## 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `No module named 'edge_tts'` | 未安装 edge-tts | 执行 `pip install edge-tts` |
| 生成固定发音失败 / timeout | 网络无法连接微软 TTS 服务 | 检查网络或代理后重试 |
| 页面提示「请使用单词卡制作器打开」 | 直接用浏览器打开了 HTML，没有经过 EXE | 用 EXE 打开，或把 HTML 拖到 EXE 上 |
| 导出时提示缺少固定发音 | 该单词没有 Guy 音频 | 在编辑弹窗点「在线生成固定发音」，或导入对应 MP3 |

## 版本记录

- **1.10.0** —— 统一单文件模板：搜索与分类筛选、卡片按当前列固定配色、拖拽排序、批量删除、清空全部、保存为默认内容、页面生命周期自动退出；固定声音 `en-US-GuyNeural`；导出文件名固定为 `编程单词卡.html`
- 更早的 JSON + `build.py` 方案已废弃，相关文件仅保留在本地，未纳入本仓库
