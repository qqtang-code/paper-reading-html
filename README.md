# paper-reading-html

把一篇论文变成**图文配合**的中文精读 HTML 页面——所有图表按原文 300 DPI 高清提取、等比展示不裁剪,图表嵌在对应讲解段落里,而不是"图表单列、文字单讲"。支持配套英文版(`en.html`)与全站 中/EN 一键切换。为 ZCode 环境设计,同时提供手动脚本可供独立使用。

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
| `scripts/validate.py` | 校验:图片存在 + 响应式、Figure/Table 数量与表号、锚点、标签平衡;exit 0=PASS(推荐项缺项以 WARN 提示) |
| `scripts/add_pagerefs.py` | 从 `crops.json` 给每张图注注入原文页码 `span.pgref`(幂等,自动补 CSS) |
| `scripts/vendor_check.py` | 校验 `vendor/lieflat-charts/` 副本完整、许可证随副本分发(CI 也跑) |
| `assets/template.html` | 图文配合页面样式骨架(hero/目录/章节/图注/表格样式) |
| `assets/chart-figure.html` | **本页自绘图表的插入片段**(`data-selfchart` + 「本页自绘」标注,复制即用) |
| `references/lieflat-charts.md` | **本页自绘图表的完整规程**:何时画 + 交付契约 + 用法 + 许可说明 |
| `vendor/lieflat-charts/` | 图表法典**副本**(catalog / galleries / tokens / reports,1.4MB,离线可用;PolyForm **非商业**许可) |
| `SKILL.md` | ZCode 技能主体:完整流程与铁律 |

## 产出规范(铁律)

1. **图片等比缩放、绝不裁剪**:`<img>` 不加固定像素宽高,响应式由 CSS `figure.fig img { max-width:100%; height:auto }` 保证;图片文件本身保持 300 DPI 原图。
2. **图表随讲解内嵌**:每个 Figure/Table 出现在对应讲解段落里(讲原理 → 图/表在旁 → 逐点解读),禁止独立"图表库"章节。
3. **图表不重不漏**:Figure 与 Table 数量与论文一致,图注里的 `Figure N:` / `Table N:` 标签
   1..N 不重不漏(校验器会 FAIL)。若某张图来自作者自绘而非论文,它**不占编号**、必须标
   「本页自绘 / Self-drawn」并带 `data-selfchart="1"`(见第 8 条)。
4. **表格一律用"图"呈现,禁止空表格壳**:每个 Table 页面呈现为
   `<div class="tbl-wrap"><figure class="fig"><img src="figs/tableN.png">…<figcaption>…</figcaption></figure></div>`
   ——图注(标题 + 中文解读)放 figcaption,里面是表格 300 DPI 原图;
   **禁止**为标题再包一层只含 `<caption>` 的空 `<table class="data">` 壳
   (宽度会缩成窄长条,且删除时易误伤嵌套的表格图片)。
   校验器会检测"只有 caption、无内容单元格"的空壳表并判 FAIL;
   术语速查这类真实数据表不受影响(须带 thead/tbody 内容行)。
5. 文本/结构用文件写入,避免 heredoc 转义;超长 HTML 分 part1/part2 写后 cat 合并。
6. **读者体验层(模板内置,校验器强制检查)**:深色模式(记忆偏好)、顶栏章节跳转、点击图片 lightbox 看原图、回到顶部、术语速查 + 正文 `<abbr>` 悬停释义、公式用 KaTeX 渲染(display $$…$$ + 内联 $…$)、og 分享标签、打印友好。
8. **自绘图表与论文图表严格区分(可选能力)**:论文给不出一张关键对照/推导视图时,可按
   `references/lieflat-charts.md` 自绘一张(选型与绘制走 `vendor/lieflat-charts/` 的法典)。三条硬规则:
   **不占用 Figure/Table 编号**、**每个数字都能回到原文(推算标「整理/推算」,不得引入论文之外的数字)**、
   **单文件可离线**(优先 SVG/PNG 放 `figs/` 用 `<img>` 引用)。校验器会检查标注与编号合规。
9. **溯源标注(推荐,校验器 WARN 提醒)**:速览章"读数约定"(数字以原文为准,整理/推算显式标注)、上游方法的行内引用、点评章"技术来源一览"表与"未披露、值得补测"清单、每张图注末尾的原文页码(`span.pgref`,脚本注入)。详见 `SKILL.md` 的"溯源与深读增强"。

## 中英双语版(可选)

要求"英文版 / 中英切换 / 面向国际读者"时,在同一论文目录生成 `en.html`(与中文页共用 `figs/`):旗舰论文做**完整英文镜像**(全章节逐段翻译),常规论文做**英文速读版**(速览 + 论文全部图表原图注 + 解读)。语言行为由 `localStorage['pr-lang']` 统一约定——首次访问跟随浏览器语言,之后记住读者选择:

- 精读页顶栏 中/EN 按钮互相跳转,切换时先写偏好再导航;
- 合集门户用"双 span + CSS 显隐"做**页内即时切换**(不复制页面、两种语言都可被搜索引擎索引、首帧前设置语言不闪屏);
- 目录入口 `index.html` 按语言偏好 `location.replace` 分流,并留无 JS 兜底链接。

校验器会检查切换器指向的目标文件真实存在。完整模式与代码样例见 `SKILL.md` 第 7 步。

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
- 双语合集(中/EN 全站切换,18 个页面 + 262 个请求线上验收零失败,按「注意力与 KV Cache / 高效推理与部署 / 评测基准」三类组织):
  <https://qqtang-code.github.io/Paper-Reading-Collection/>
  - 7 篇中文精读 + 7 篇英文版(Declarative Attention、DeepSeek-V4.1-Flash 为完整镜像,其余为速读版);
  - 完整英文版示例:<https://qqtang-code.github.io/Paper-Reading-Collection/attention-kv-cache/declarative-attention/en.html>
- 溯源与深读增强的完整示例(读数约定 / 行内引用 / 技术来源一览 / 未披露清单 / 图注原文页码):
  DeepSeek-V4.1-Flash 精读页 <https://qqtang-code.github.io/DeepSeek-V4.1-Flash-Project-Page/>
  - 中文页与英文页均含全部图表(300 DPI,18 张)、层配置落层走查与上述溯源规范。

## 许可证

MIT。本仓库以"读者的使用体验"为第一优先级:任何环节让你困惑,欢迎开 issue 或 PR。

### 第三方依赖与混合许可(重要)

`vendor/lieflat-charts/` 是 **lieflat-charts** skill 的副本(图表选型 / 模板骨架 / 设计 token),
用于"本页自绘图表"能力。它的许可证是 **PolyForm Noncommercial License 1.0.0(非商业)**,
与本仓库其余部分的 MIT **不同**,且 MIT 无法覆盖它。

因此:**带 `vendor/lieflat-charts/` 的仓库整体只能用于非商业目的**。
- 许可证原文随副本一起分发(`vendor/lieflat-charts/LICENSE`),搬运时不得删改;
- 出处、版本摘要(manifest digest)与刷新方法见 `vendor/lieflat-charts/VENDORED.md`;
- 若要在商业场景使用本仓库,**删掉 `vendor/lieflat-charts/` 即可** —— 其余流程(图表提取、校验、
  中英双语页、部署)没有任何非 MIT 依赖,只是"自绘图表"这一步需要换成别的图表库;
- 上游开发者是「躺在废墟里」,公开分发用它产出的图表内容时请署名。

自检:`python3 scripts/vendor_check.py`(CI 也会跑)。