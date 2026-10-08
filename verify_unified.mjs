import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const root = process.cwd();
const assetDir = path.join(root, 'exe-assets');
const entries = fs.readdirSync(assetDir, { withFileTypes: true });
const files = entries.filter((entry) => entry.isFile());
const directories = entries.filter((entry) => entry.isDirectory());

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

assert(directories.length === 0, '构建资源目录不能包含子目录');
assert(files.length === 1, `构建资源目录应只有 1 个文件，实际为 ${files.length}`);
assert(files[0].name.endsWith('.html'), '唯一构建资源必须是 HTML');

const outputPath = path.join(assetDir, files[0].name);
const output = fs.readFileSync(outputPath, 'utf8');
const source = fs.readFileSync(path.join(root, 'default-vocabulary.html'), 'utf8');
const sourceDataMatch = source.match(/<script type="application\/json" id="app-data">([\s\S]*?)<\/script>/);
assert(sourceDataMatch, '默认词汇文件缺少内嵌数据');
const sourceProject = JSON.parse(sourceDataMatch[1]);

assert(/^<!DOCTYPE html>/i.test(output), '缺少 HTML doctype');
assert(/<meta charset="UTF-8">/i.test(output), '缺少 UTF-8 声明');
assert(/name="viewport"/i.test(output), '缺少移动端 viewport');
assert(!output.includes('__APP_DATA__'), '数据占位符未替换');
assert(!output.includes('__APP_VERSION__'), '界面版本占位符未替换');
assert(!/<script[^>]+src=/i.test(output), '不允许外部脚本');
assert(!/<link[^>]+(?:rel="stylesheet"|href=)/i.test(output), '不允许外部样式');
assert(!/<(?:img|audio|video|source)[^>]+src=["']https?:/i.test(output), '不允许外部媒体');
assert(!/@import\s+/i.test(output), '不允许 CSS @import');
assert(!/url\(\s*["']?https?:/i.test(output), '不允许远程 CSS 资源');

const dataMatch = output.match(/<script type="application\/json" id="app-data">([\s\S]*?)<\/script>/);
assert(dataMatch, '找不到内嵌应用数据');
const project = JSON.parse(dataMatch[1]);
assert(project.schemaVersion === 1, 'schemaVersion 错误');
assert(project.appVersion === '1.10.0', '项目界面版本错误');
assert(project.voice === 'en-US-GuyNeural', '固定声音配置错误');
assert(project.version === 3, '默认单词卡版本号错误');
assert(project.words.length === 38, `应迁移 38 个单词，实际为 ${project.words.length}`);
assert(new Set(project.words.map((item) => item.id)).size === project.words.length, '词条 ID 重复');
assert(new Set(project.words.map((item) => item.word.toLowerCase())).size === project.words.length, '单词重复');
assert(project.words.every((item) => item.word && item.meaning), '存在缺少必填字段的词条');
assert(project.words.every((item) => typeof item.phraseTitle === 'string' && item.phraseTitle), '初始短语栏目名称迁移错误');
assert(project.words.every((item) => item.audioText === item.word && item.audioData.startsWith('data:audio/mpeg;base64,')), '存在缺失或错配的固定发音');
assert(project.words.reduce((sum, item) => sum + item.phrases.length, 0) === 38, '短语迁移数量错误');

const expectedOrder = ['AI','elif','else','enter','for','if','import','in','input','integer','print','Python','range','shift','space','while','and','or','not','True','False','int','float','str','string','bool','len','list','random','variable','loop','code','run','stop','save','open','file','error'];
assert(JSON.stringify(project.words.map((item) => item.word)) === JSON.stringify(expectedOrder), '单词顺序或内容迁移错误');

const oldAudio = new Map(sourceProject.words.map((item) => [item.word, item.audioData.split(',', 2)[1]]));
assert(oldAudio.size === 38, '默认词汇音频提取失败');
for (const item of project.words) {
  const payload = item.audioData.split(',', 2)[1];
  const bytes = Buffer.from(payload, 'base64');
  assert(bytes.length > 1000, `${item.word} 音频异常短`);
  assert(bytes[0] === 0xff && (bytes[1] & 0xe0) === 0xe0, `${item.word} 不是有效 MPEG 音频`);
  const oldHash = crypto.createHash('sha256').update(Buffer.from(oldAudio.get(item.word), 'base64')).digest('hex');
  const newHash = crypto.createHash('sha256').update(bytes).digest('hex');
  assert(oldHash === newHash, `${item.word} 的旧音频未被原样复用`);
}

const idMatches = [...output.matchAll(/\sid="([^"]+)"/g)].map((match) => match[1]);
assert(new Set(idMatches).size === idMatches.length, 'HTML 中存在重复 ID');
assert(output.includes('@media (max-width: 720px)'), '缺少手机布局');
assert(output.includes('@media (min-width: 620px)'), '缺少平板布局');
assert(output.includes('@media (min-width: 980px)'), '缺少电脑布局');
assert(output.includes('clone.outerHTML'), '缺少单文件自导出逻辑');
assert(output.includes('new File([htmlText]'), '缺少 HTML 文件生成逻辑');
assert(output.includes("card.dataset.wordId = item.id"), '卡片缺少稳定的拖动排序标识');
assert(output.includes("addEventListener('pointerdown'"), '缺少按住拖动入口');
assert(output.includes("addEventListener('pointermove'"), '缺少鼠标/触摸拖动过程');
assert(output.includes("addEventListener('pointerup'"), '缺少拖动完成处理');
assert(output.includes("addEventListener('pointercancel'"), '缺少触摸取消处理');
assert(output.includes('body[data-local-app="true"][data-editing="true"] .drag-handle'), '拖动手柄未限制在制作器编辑模式');
assert(output.includes("if (!isLocalApp || document.body.dataset.editing !== 'true') return"), '备用排序未限制在制作器编辑模式');
assert(output.includes("dataset.localApp = 'false'"), '导出成品未关闭本地制作器状态');
assert(output.includes('<body data-editing="false" data-exported="false">'), '制作器页面缺少导出状态标记');
assert(output.includes("dataset.exported = 'true'"), '导出成品未启用纯单词卡视图');
assert(output.includes('body[data-exported="true"] .hero'), '导出成品未隐藏顶部标题区');
assert(!output.includes('body[data-exported="true"] .toolbar,\n'), '导出成品错误隐藏了搜索工具栏');
assert(output.includes('body[data-exported="true"] #toggleEditButton { display: none !important; }'), '导出成品未隐藏编辑按钮');
assert(output.includes('grid-template-columns: minmax(0, 1fr) minmax(150px, 210px);'), '导出成品搜索与分类布局错误');
assert(output.includes('body[data-exported="true"] .search-wrap { grid-column: auto; }'), '导出成品移动端搜索布局错误');
assert(output.includes('id="searchInput"'), '导出成品缺少单词搜索框');
assert(output.includes('id="categoryFilter"'), '导出成品缺少分类下拉框');
assert(output.includes("searchInput.addEventListener('input'"), '单词搜索框未连接筛选功能');
assert(output.includes("categoryFilter.addEventListener('change'"), '分类下拉框未连接筛选功能');
assert(!output.includes('var PALETTES'), '卡片仍使用随词条移动的颜色数组');
assert(!output.includes("card.style.setProperty('--card-a'"), '卡片颜色仍写入词条节点');
assert(output.includes('.word-card:nth-child(4n + 1)'), '四列布局缺少第 1 列固定颜色');
assert(output.includes('.word-card:nth-child(4n + 2)'), '四列布局缺少第 2 列固定颜色');
assert(output.includes('.word-card:nth-child(4n + 3)'), '四列布局缺少第 3 列固定颜色');
assert(output.includes('.word-card:nth-child(4n) {'), '四列布局缺少第 4 列固定颜色');
assert(output.includes('.word-card:nth-child(3n + 1)'), '三列布局未按当前列固定颜色');
assert(output.includes('.word-card:nth-child(2n + 1)'), '两列布局未按当前列固定颜色');
assert(output.includes('wordGrid.appendChild(renderCard(item))'), '卡片颜色仍可能依赖导入顺序');
assert(output.includes('id="clearAllButton"'), '编辑工具栏缺少一键清空按钮');
assert(output.includes('id="saveDefaultButton"'), '编辑工具栏缺少保存默认内容按钮');
assert(output.includes('function clearAllWords()'), '缺少一键清空单词逻辑');
assert(output.includes("project.words = []"), '一键清空没有清除全部词条');
assert(output.includes("window.confirm('确定清空全部单词吗？"), '一键清空缺少防误触确认');
assert(output.includes('async function saveDefaultProject()'), '缺少保存默认内容逻辑');
assert(output.includes("fetch('/v1/default'"), '保存默认内容未连接制作器');
assert(output.includes("addEventListener('click', clearAllWords)"), '一键清空按钮未连接功能');
assert(output.includes("addEventListener('click', saveDefaultProject)"), '保存默认内容按钮未连接功能');
assert(output.includes('id="batchDeleteButton"'), '编辑工具栏缺少批量删除按钮');
assert(output.includes('id="batchDeleteBackdrop"'), '缺少批量删除窗口');
assert(output.includes('id="batchDeleteSearch"'), '批量删除缺少搜索框');
assert(output.includes('id="selectVisibleWordsButton"'), '批量删除缺少全选当前结果');
assert(output.includes('function deleteSelectedWords()'), '缺少批量删除处理逻辑');
assert(output.includes("project.words = project.words.filter"), '批量删除没有从词条数据中移除所选项');
assert(output.includes("window.confirm('确定删除选中的 ' + count + ' 个单词吗？')"), '批量删除缺少确认步骤');
assert(output.includes("addEventListener('click', openBatchDelete)"), '批量删除按钮未连接功能');
assert(output.includes("addEventListener('click', deleteSelectedWords)"), '批量删除确认按钮未连接功能');
assert(output.includes('body[data-exported="true"] .results-line'), '导出成品未隐藏结果信息栏');
assert(output.includes('body[data-exported="true"] .edit-dock'), '导出成品未隐藏编辑工具栏');
assert(output.includes('body[data-exported="true"] .card-actions'), '导出成品未隐藏卡片编辑按钮');
assert(output.includes('body[data-exported="true"] .footer-note'), '导出成品未隐藏底部说明');
assert(output.includes('body[data-exported="true"] .modal-backdrop'), '导出成品未隐藏编辑弹窗');
assert(output.includes('body[data-exported="true"] .toast'), '导出成品未隐藏提示消息');
assert(output.includes('body[data-exported="true"] .app-shell { padding-bottom: 22px; }'), '导出成品仍保留过大的底部留白');
assert(output.includes("fetch('/v1/page/' + action"), '缺少页面生命周期通知');
assert(output.includes("window.addEventListener('pagehide', notifyPageClosed)"), '关闭网页时未通知制作器');
assert(output.includes("window.addEventListener('pageshow'"), '缺少刷新和页面恢复保护');
assert(output.includes("sendPageLifecycle('heartbeat'"), '缺少页面异常关闭回收心跳');
assert(output.includes('id="phraseTitleInput"'), '缺少可编辑的短语栏目名称');
assert(output.includes("record.phraseTitle = phraseTitleInput.value.trim() || '短语搭配'"), '短语栏目名称没有保存到词条');
assert(output.includes("textNode('div', 'phrase-label', phraseTitleFor(item))"), '卡片没有显示自定义短语栏目名称');
assert(output.includes("item.phraseTitle = phraseTitleFor(item).slice(0, 40)"), '旧版本短语栏目名称未兼容');
assert(output.includes('font-size: .88rem; font-weight: 800; letter-spacing: .04em;'), '短语栏目标题字号未调整');
assert(output.includes('font-size: .94rem; line-height: 1.45;'), '短语内容字号未调整');

const appVersionMeta = output.match(/<meta name="vocabulary-app-version" content="([^"]+)">/);
assert(appVersionMeta && appVersionMeta[1] === '1.10.0', 'HTML 界面版本号错误');
assert(output.includes('<title>编程单词卡</title>'), '页面标题没有固定为“编程单词卡”');
assert(!/<title>[^<]*v\d+/i.test(output), '页面标题仍包含单词卡版本号');
assert(!output.includes('name="vocabulary-version"'), '生成的单词卡仍包含版本号元数据');
assert(!output.includes('document.title ='), '脚本仍会修改固定页面标题');
assert(!output.includes('nextVersion'), '导出逻辑仍会递增单词卡版本号');
assert(!output.includes('project.version ='), '导出逻辑仍会修改单词卡版本号');
assert(!output.includes("clone.querySelector('title')"), '导出逻辑仍会修改页面标题');
assert(output.includes("var fileName = '编程单词卡.html'"), '导出文件名仍包含版本号');
assert(output.includes("'界面 v' + APP_VERSION"), '制作器未显示当前界面版本');
assert(output.includes('project.appVersion = APP_VERSION'), '导出没有使用当前界面版本');
assert(!output.includes('1.9.0'), '成品仍残留旧界面版本号');
assert(output.includes('>导入单词卡\n'), '工具栏缺少“导入单词卡”');
assert(output.includes('>↓ 导出新单词卡</button>'), '工具栏缺少“导出新单词卡”');
assert(!output.includes('id="shutdownButton"'), '工具栏仍包含退出制作器按钮');
assert(!output.includes('退出制作器'), '成品仍残留退出制作器文字');

const setEditingMatch = output.match(/function setEditing\(enabled\) \{([\s\S]*?)\n    \}\n\n    function getBatchDeleteWords/);
assert(setEditingMatch, '找不到编辑模式切换逻辑');
assert(!setEditingMatch[1].includes('showToast'), '进入编辑模式时仍会显示提示');

const scriptMatches = [...output.matchAll(/<script(?![^>]*type="application\/json")[^>]*>([\s\S]*?)<\/script>/g)];
assert(scriptMatches.length === 1, `应有 1 段应用脚本，实际为 ${scriptMatches.length}`);
for (const match of scriptMatches) new Function(match[1]);

console.log(`验证通过：${files[0].name}`);
console.log(`词条 ${project.words.length} 个，短语 ${project.words.reduce((sum, item) => sum + item.phrases.length, 0)} 条，固定音频 ${project.words.length} 段`);
console.log(`单文件大小 ${(Buffer.byteLength(output) / 1024).toFixed(1)} KB`);
