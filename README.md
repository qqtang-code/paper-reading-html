# paper-reading-html

把一篇论文变成**图文配合**的中文精读 HTML 页面——所有图表按原文 300 DPI 高清提取、等比展示不裁剪,图表嵌在对应讲解段落里,而不是"图表单列、文字单讲"。为 ZCode 环境设计,同时提供手动脚本可供独立使用。

## 用法(A 方案:在 ZCode 里)

装有 ZCode 的机器上,把本仓库放进用户级技能目录即可被自动发现:

```bash
mkdir -p ~/.agents/skills && git clone https://github.com/qqtang-code/paper-reading-html ~/.agents/skills/paper-reading-html
```

然后直接对对话模型说:

- "帮我精读 https://arxiv.org/abs/XXXX.XXXXX 并生成 HTML"
- "精读这篇,并部署到我 github.io 的子路径"
- "把本地这个 PDF 做成精读页"
- 或强制触发:`/paper-reading-html <需求>`

产出固定为 `xxx论文精读_HTML.html` + 同目录 `figs/`(原始 300 DPI 图,页面等比展示)。

## 用法(B 方案:手动使用)

不依赖 Agent 时,三个脚本可独立工作:

```bash
# 1. 下载论文
curl -sL -o paper.pdf "https://arxiv.org/pdf/XXXX.XXXXX"

# 2. 自动定位图表 → 生成 crops.json(每个 Figure/Table 的裁剪框)
python3 scripts/locate_figs.py paper.pdf crops.json

# 3. 按 crops.json 渲染 300 DPI PNG
python3 scripts/extract_figs.py paper.pdf crops.json figs/

# 4. 以 assets/template.html 为骨架填写讲解(样式、图文配合结构已内置)
#    <img src="figs/fig1.png"> 挂在对应讲解段落里

# 5. 校验
python3 scripts/validate.py 你的页面.html
```

`locate_figs.py` 输出的框是"页级"候选,多图同页时按打印的边界把 `crops.json` 里的 rect 拆细(坐标单位:PDF 点,原点在页左上)。

## 脚本与模板

| 文件 | 作用 |
|---|---|
| `scripts/locate_figs.py` | 自动检测光栅图/矢量图/图注,生成 `crops.json` |
| `scripts/extract_figs.py` | `crops.json` → 300 DPI PNG(固定 300,不缩放) |
| `scripts/validate.py` | 校验:图片存在 + 响应式、Figure/Table 数量与表号、锚点、标签平衡;exit 0=PASS |
| `assets/template.html` | 图文配合页面样式骨架(hero/目录/章节/图注/表格样式) |
| `SKILL.md` | ZCode 技能主体:完整流程与铁律 |

## 产出规范(铁律)

1. **图片等比缩放、绝不裁剪**:`<img>` 不加固定像素宽高,响应式由 CSS `figure.fig img { max-width:100%; height:auto }` 保证;图片文件本身保持 300 DPI 原图。
2. **图表随讲解内嵌**:每个 Figure/Table 出现在对应讲解段落里(讲原理 → 图/表在旁 → 逐点解读),禁止独立"图表库"章节。
3. **图表不重不漏**:Figure 与 Table 数量与论文一致,表号 1..N 齐全。
4. 每个 `<figure>` 图注:英文原图注 + 中文解读;每个 `<table>` 用 `<caption>` 写表号表题。
5. 文本/结构用文件写入,避免 heredoc 转义;超长 HTML 分 part1/part2 写后 cat 合并。
6. **读者体验层(模板内置,校验器强制检查)**:深色模式(记忆偏好)、顶栏章节跳转、点击图片 lightbox 看原图、回到顶部、术语速查 + 正文 `<abbr>` 悬停释义、公式用 KaTeX 渲染(display $$…$$ + 内联 $…$)、og 分享标签、打印友好。

## 部署到 GitHub Pages(可选)

```bash
gh repo create <PaperName>-Project-Page --public --source=. --push
gh api -X POST repos/<user>/<PaperName>-Project-Page/pages \
  -f "source[branch]=main" -f "source[path]=/"
# → https://<user>.github.io/<PaperName>-Project-Page/
```

## 实例

- 本 skill 首个产物(实测校验通过):ReSET 论文精读页 <https://qqtang-code.github.io/ReSET-Project-Page/>
  - 8 张 Figure(300 DPI)+ 16 张 Table 全部内嵌,图文随讲解段落走。

## 许可证

MIT。本仓库以"读者的使用体验"为第一优先级:任何环节让你困惑,欢迎开 issue 或 PR。