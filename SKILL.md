---
name: paper-reading-html
description: >-
  论文精读 HTML 生成与部署。当用户给出一篇论文(arXiv 链接 / PDF 文件),要求"讲解、精读、
  梳理、读论文、做笔记、paper reading、生成 HTML 解读页、放到个人主页/项目页/github.io 子路径"时使用。
  产出"图文配合"的中文精读页面:全部图表按原文 300 DPI 高清提取、等比缩放不裁剪、图表随讲解段落
  内嵌(而非图表单列、文字单讲),并可将产物推送到远程 GitHub / GitHub Pages。适用于任何论文讲解
  场景:即使只是一个链接或一句"帮我讲讲这篇",也用它。
---

# 论文精读 HTML(Paper Reading HTML)

把一篇论文变成"图文配合"的中文精读 HTML 页面。命名灵感:arXiv:2606.13233 (ReSET, NVFP4 推理)
精读页的经验模板。

## 产出物

- `res.html`(建议命名 `XXX论文精读_HTML.html`,XXX=论文名缩写)——单文件中文精读页
- `figs/`——全部图表,按原文版面 300 DPI 高清 PNG,等比展示不裁剪
- 可选:推送 GitHub 仓库 + GitHub Pages 部署子路径

## 流程总览

1. 获取论文(下载 PDF + 全文)
2. 通读并定位所有 Figure/Table(编号、所在页、区域)
3. 高 DPI 提取图表(核心:验证裁剪框 → 渲染 → 复核)
4. 按"图文配合"结构撰写 HTML(模板在 `assets/template.html`)
5. 校验(结构/锚点/图片/表格完整性)
6. 可选:git 推送 + GitHub Pages 部署

## 第 1 步:获取论文

```bash
# arXiv PDF 直接下载(download 后必须 file 确认是 PDF)
curl -sL -o paper.pdf "https://arxiv.org/pdf/2606.13233"
file paper.pdf   # 期望: PDF document
```

提取全文(任选):系统有 `pdftotext` 优先 `pdftotext -layout paper.pdf paper.txt`;
否则 Python(pypdf/PyMuPDF 按页提取,每页加 `===== PAGE N =====` 分隔)。
随后**通读全文**,记录:章节结构、每个 Figure/Table 的编号与页号、关键数字、
方法的核心逻辑。正文 + 附录都要读。

## 第 2 步:定位图表

用 PyMuPDF 程序化定位,不要靠肉眼猜:

```python
import fitz
doc = fitz.open('paper.pdf')
for pno in range(len(doc)):
    page = doc[pno]
    print(pno+1, [c for c in page.search_for("Figure")])  # 图注位置
    print(pno+1, [c for c in page.search_for("Table")])   # 表注位置
```

配合两种手段确定每个图的**精确裁剪框**:
- `page.get_images(full=True)` + `page.get_image_rects()`:光栅图的实际位置;
- `page.get_drawings()` 的 y 聚类 + `page.get_text('blocks')`:矢量图的绘图边界与文字块范围;

三者交叉验证,得到每个图的 (page_idx, rect)。矩形必须刚好包住该图全部面板与图注,
**不得混入正文或其他图**。

## 第 3 步:高 DPI 提取(核心)

```bash
python3 "$SKILL_DIR/scripts/extract_figs.py" paper.pdf crops.json out/
```

- `crops.json` 格式:`{"fig1": {"page": 2, "rect": [x0,y0,x1,y1]}, ...}`(rect 为 PDF 点坐标,0 基页码)
- 脚本用 `page.get_pixmap(dpi=300, clip=rect)` 渲染,输出 `out/fig1.png`…
- **DPI 固定 300**;对宽幅图(如多面板并排)可给更宽的 rect,但绝不缩放 render。
- 提取后必须**程序化复核**:对每个 crop,列出框内全部文本块,确认只含本图内容
  (有正文句子混入 = 框大了;缺面板标签 = 框小了),并确认输出 PNG 尺寸与预期一致。

图表数量核对:Figure 与 Table 必须与论文实际一致(正文 + 附录)。表格数表格数量必须在 HTML 里
与论文完全对齐(编号 1..N 不重不漏),图片同理。

## 第 4 步:撰写 HTML(图文配合)

用 `assets/template.html` 作骨架(样式已内置:响应式、图随文走)。**铁律:**

1. **图片等比缩放、绝不裁剪**:`<img>` 用 `max-width:100%; height:auto;`(禁止固定像素宽
   度 + `overflow-x:auto` 方案,禁止 `width`/`height` 属性写死)。图片文件本身是 300 DPI 原图,
   HTML 只负责等比展示。
2. **图表随讲解内嵌**:每个 Figure/Table 必须出现在与之对应的讲解段落里(先讲原理 → 图/表在旁 →
   紧接逐点解读),**禁止**"图表全部单列在一个库/画廊章节、文字另外单讲"。导航、章节都按讲述顺序组织。
3. 每个 `<figure>` 必须有 `figcaption`:首行英文原图注,再一行中文解读(标注 `class="zh"`)。
4. 每个 `<table>` 用 `<caption>` 写表号+表题;"ReSET 行"等关键行加 `hl` 高亮。
5. 正文包含:封面 header(标题/作者/arXiv 链接/关键词 pill)、目录导航、按"背景→观察→方法→系统→实验→
   补充→点评"讲述、每节 `sec-no`+`h2.sec`、局部 `note`/`takeaway` 强调块、公式用 `.math` 块、
   结尾脚注说明"图片为原文高清提取"。
6. 中文文本与 HTML 结构用文件写入,避免 heredoc 转义问题;超长 HTML 分 part1/part2 写后 `cat` 合并。

## 第 5 步:校验

```bash
python3 "$SKILL_DIR/scripts/validate.py" res.html
```

检查:① 引用的每个 img 存在且无缺;② Figure 数、Table 数与论文一致;③ Table caption 编号
1..N 完整、无重复;④ 所有 `href="#..."` 锚点存在;⑤ 标签开闭平衡;⑥ 每个 img 都带
`max-width:100%` 与 `height:auto`;⑦ 关键数字出现(抽查)。全部 PASS 才可交付。

## 第 6 步(可选):推送与 GitHub Pages 部署

skill 目录本身可推送到远程仓库;精读页推独立的 `<PaperName>-Project-Page` 仓库并开 Pages(模仿
`https://<user>.github.io/<PaperName>-Project-Page/` 的项目页形态):

```bash
gh repo create <PaperName>-Project-Page --public --source=. --push
gh api -X POST repos/<user>/<PaperName>-Project-Page/pages \
  -f "source[branch]=main" -f "source[path]=/"
```

交付时:报告 HTML 路径、figs/ 目录、仓库链接、Pages URL。

## 目录

```
paper-reading-html/
├── SKILL.md
├── assets/template.html      ← HTML 骨架(样式 + 结构)
├── scripts/extract_figs.py   ← crops.json → 300DPI PNG
└── scripts/validate.py       ← HTML 完整性校验
```