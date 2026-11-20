# HTML 工作台 · HTML Studio

> 把 AI 生成的 HTML 收进一个本地工作台：点哪里改哪里，不用再让 AI 整页重写。

一个零依赖、离线可用的本地 HTML 可视化编辑器。后端只有 Python 标准库，前端是单文件 `index.html`，数据全部留在你自己的电脑上。

[English](#english) · [日本語](#日本語)

---

## 功能

- **收录本地 HTML**：添加任意目录作为内容根，自动索引其中的 `.html` / `.htm` 页面。
- **文本编辑**：按段落/标题逐块修改文案；支持撤销、版本历史与自动备份。
- **少量文字样式**：在预览里选中一小段文字，浮条直接改颜色、加粗、斜体、下划线、字号，只影响选中的文字。
- **元素编辑**：选中页面里的图片、链接、按钮、卡片等元素，修改地址、链接、尺寸、颜色、圆角、内外边距等；支持在预览里点选。
- **图片替换**：列出页面用到的全部图片（包括脚本动态切换的图），可缩略图预览并原地替换，旧图自动备份。
- **配色**：读取并修改页面 CSS 变量，实时预览；内置配色卡，可保存/复用/移除注入。
- **三语界面**：简体中文 / English / 日本語。
- **明暗主题**：浅色与深色两套界面。
- **导出与交接**：导出修改后的页面、生成交接说明，方便交给别人继续改。
- **安全边界**：默认只监听 `127.0.0.1`；所有写操作先备份；路径必须落在内容根内。

## 环境要求

- Python 3.9+（不需要安装任何第三方包）
- 现代浏览器（Chrome / Edge / Firefox / Safari）

## 快速开始

```bash
python htmlstudio_server.py
```

浏览器会自动打开 `http://127.0.0.1:8781/`。首次使用点左上角「添加目录」，选择一个存放 HTML 的文件夹即可开始。

常用参数：

```bash
python htmlstudio_server.py --port 9000        # 换端口
python htmlstudio_server.py --host 0.0.0.0    # 允许局域网访问（注意安全）
python htmlstudio_server.py --list            # 只列出已收录页面后退出
python htmlstudio_server.py --no-browser      # 不自动打开浏览器
```

## 使用流程

1. **收录**：添加内容根目录，列表里会出现所有 HTML 页面。
2. **选中页面**：中间是实时预览，右侧是编辑面板。
3. **改文案**：在「文本」里逐块修改，或在预览里直接选中文字。
4. **调样式**：选中文字用浮动工具条；选中元素用「元素」面板；整体配色用「配色」面板。
5. **应用**：改动会先进入草稿，点「应用修改 / 应用配色」写入文件，写入前自动备份。
6. **回滚**：在「版本」里查看历史与差异，必要时一键恢复。

## 数据与备份

| 内容 | 位置 |
| --- | --- |
| 配置、索引、配色卡 | `data/`（打包运行时为 `%APPDATA%\HTMLStudio\data`） |
| 页面备份 | `data/backups/` |
| 版本历史 | `data/history/` |
| 图片替换备份 | 页面所在目录的 `.htmlstudio/asset-backups/` |

- 服务默认只绑定 `127.0.0.1`，不会暴露到公网。
- 所有文件写入都限制在已添加的内容根内，拒绝越界路径。
- 本项目不收集、不上传任何数据。

## 目录结构

```
html-studio/
├─ htmlstudio_server.py   # 本地服务：索引、编辑、备份、配色、导出
├─ index.html             # 单文件前端（三语 / 明暗 / 预览）
├─ assets/                # 图标
├─ app.config.json        # 可选：Windows 安装包配置
├─ LICENSE
└─ README.md
```

## 打包为 Windows 程序（可选）

1. 用 PyInstaller 打包为单文件、无控制台窗口：

   ```bash
   pip install pyinstaller
   pyinstaller --noconfirm --onefile --name HTMLStudio --noconsole ^
     --add-data "index.html;." --add-data "assets;assets" htmlstudio_server.py
   ```

2. 需要安装向导时，可用 Inno Setup 基于 `app.config.json` 生成安装包。

## 贡献

欢迎提 Issue 和 PR。提交前请确保：

- 不包含任何个人路径、密钥、Token 或私有页面内容；
- 保持零第三方运行时依赖；
- 三语界面的文案同步更新。

## License

[MIT](LICENSE)

---

<a id="english"></a>
## English

HTML Studio is a zero-dependency, offline-first visual editor for AI-generated HTML pages.

- Index any local folder of HTML files and edit them in place.
- Edit text block by block, or select a few words to change color / bold / italic / underline / size.
- Edit elements (images, links, buttons, cards): src, href, size, colors, radius, spacing.
- Replace any image used by the page — including images swapped by scripts — with automatic backups.
- Tune CSS variables with live preview, or apply built-in palettes.
- Trilingual UI (Chinese / English / Japanese), light and dark themes, version history, export and handoff notes.

Run it with:

```bash
python htmlstudio_server.py
```

Then open <http://127.0.0.1:8781/>. Everything stays on your machine; the server binds to `127.0.0.1` by default.

---

<a id="日本語"></a>
## 日本語

HTML Studio は、AI が生成した HTML をローカルで編集するための、依存パッケージ不要のビジュアルエディタです。

- ローカルの HTML フォルダを取り込み、その場で編集
- 段落ごとのテキスト編集、選択した数文字だけの色・太字・斜体・下線・サイズ変更
- 画像・リンク・ボタンなどの要素編集、画像の置換（自動バックアップ付き）
- CSS 変数の調整と配色プリセット、ライブプレビュー
- 中国語 / 英語 / 日本語の UI、ライト・ダークテーマ、変更履歴と書き出し

```bash
python htmlstudio_server.py
```

起動後 <http://127.0.0.1:8781/> を開きます。データはすべてローカルに保存され、既定では `127.0.0.1` のみで待ち受けます。
