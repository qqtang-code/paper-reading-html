---
name: paper-reading-html
description: >-
  论文精读 HTML 生成与部署。当用户给出一篇论文(arXiv 链接 / PDF 文件),要求"讲解、精读、
  梳理、读论文、做笔记、paper reading、生成 HTML 解读页、放到个人主页/项目页/github.io 子路径",
  或要求"英文版、English edition、双语、中英切换、bilingual"时使用。
  产出"图文配合"的中文精读页面:全部图表按原文 300 DPI 高清提取、等比缩放不裁剪、图表随讲解段落
  内嵌(而非图表单列、文字单讲),并可将产物推送到远程 GitHub / GitHub Pages。可按需生成同目录
  英文版 en.html 与全站 中/EN 语言切换(pr-lang 偏好记忆)。适用于任何论文讲解
  场景:即使只是一个链接或一句"帮我讲讲这篇",也用它。论文缺少的关键对照/推导视图,可按本技能的
  自绘图表规程(lieflat-charts 对接)补一张,并与原文图表严格区分。
---

# 论文精读 HTML(Paper Reading HTML)

把一篇论文变成"图文配合"的中文精读 HTML 页面。命名灵感:arXiv:2606.13233 (ReSET, NVFP4 推理)
精读页的经验模板。

## 产出物

- `res.html`(建议命名 `XXX论文精读_HTML.html`,XXX=论文名缩写)——单文件中文精读页
- `figs/`——全部图表,按原文版面 300 DPI 高清 PNG,等比展示不裁剪
- 可选:`en.html`——同目录英文版(完整镜像或速读版),与中文页共用 `figs/`;
  配套全站 中/EN 语言切换(localStorage `pr-lang`,详见第 7 步)
- 可选:`figs/chart-*.svg`——**本页自绘图表**(论文给不出、由你用 lieflat-charts 体系绘制),
  必须标「本页自绘」且不占用论文图表编号(见第 5.5 步 / `references/lieflat-charts.md`)
- 可选:推送 GitHub 仓库 + GitHub Pages 部署子路径

## 流程总览

1. 获取论文(下载 PDF + 全文)
2. 通读并定位所有 Figure/Table(编号、所在页、区域)
3. 高 DPI 提取图表(核心:验证裁剪框 → 渲染 → 复核)
4. 按"图文配合"结构撰写 HTML(模板在 `assets/template.html`)
5. 校验(结构/锚点/图片/表格完整性)
5.5 可选:论文给不出的关键视图,用 lieflat-charts 体系自绘并合规嵌入(见第 5.5 步)
6. 可选:git 推送 + GitHub Pages 部署
7. 可选:中英双语版(en.html + 语言切换器,见第 7 步)

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

用 `scripts/locate_figs.py` 程序化定位(不要靠肉眼猜),它输出每页的图注位置、光栅图框、矢量图带,并自动生成页级候选 `crops.json`:

```bash
python3 "$SKILL_DIR/scripts/locate_figs.py" paper.pdf crops.json
```

若同页有多个图,按脚本打印的边界把 rect 拆细。每张图坐标确定后,**人工复核一遍**(内容与图注是否对齐、是否混入正文)。该冒烟路径由 CI 用 `assets/example_paper.pdf` 持续验证。

裁得"对齐"的 rect 推荐程序化求法,不要手推文本块边界:以"上下邻近元素(图注/正文)的 span 边界"围出安全窗口,
在窗口内渲染该页并扫描非白像素(<248 灰度)得到精确**墨迹包围盒**,四边加统一留白(约 5pt;受图注距离限制时
取空隙中点)。这样不会贴边、不会削掉表格线,也不会留下左右不对称的大片空白。

## 第 3 步:高 DPI 提取(核心)

```bash
python3 "$SKILL_DIR/scripts/extract_figs.py" paper.pdf crops.json out/
```

- `crops.json` 格式:`{"fig1": {"page": 2, "rect": [x0,y0,x1,y1]}, ...}`(rect 为 PDF 点坐标;**page 是 0 基索引**,
  脚本直接 `doc[page]`,不是"第几页";日志里 `PDF p.N` 才是 1 基显示)
- ⚠️ **页码 off-by-one 是隐形炸弹**:把"第 N 页"直接写进 page,会静默截取第 N+1 页的同一坐标——
  PNG 尺寸照样正确(尺寸只由 rect 决定),但内容全错;尺寸核对发现不了,必须靠下面的像素对照。
- 脚本用 `page.get_pixmap(dpi=300, clip=rect)` 渲染,输出 `out/fig1.png`…
- **DPI 固定 300**;对宽幅图(如多面板并排)可给更宽的 rect,但绝不缩放 render。
- 提取后必须**三重复核**:
  1. **像素对照(防错页)**:用 fitz 直渲染 `doc[page]` 的同一 rect,与输出 PNG 逐像素/哈希一致;
     再渲染 `doc[page+1]` 同一 rect,确认与前者**不同**;
  2. **文本块核对(防框大/框小)**:列出框内全部文本块,确认只含本图内容
     (有正文句子混入 = 框大了;缺面板标签 = 框小了);
  3. **边框全白检查(防贴边/削墨)**:PNG 四边 1px 内不得有墨迹(灰度 <248)——
     贴边说明 rect 紧贴内容,按第 2 步的墨迹包围盒法重裁。

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
4. **表格一律用"图"呈现,禁止空表格壳**:页面里的每个 Table 必须是
   `<div class="tbl-wrap"><figure class="fig"><img src="figs/tableN.png">…<figcaption>…</figcaption></figure></div>`
   ——即"300 DPI 表格原图 + figcaption 标题/解读",figcaption 首行写 `Table N: 表题`。
   **禁止**在 figure 外面再包一层只含 `<caption>` 的 `<table class="data">` 空壳
   (即 `<div class="tbl-wrap"><table><caption>…</caption></table><figure>…</figure></div>`
   的嵌套写法)。空壳表格没有内容单元格,宽度会缩到内容最小宽度,导致一长条标题疯狂换行成
   "窄长条";且脚本删除/修改时极易误伤嵌套其中的表格图片 figure。若确需在正文内放数据型
   `<table>`(如术语速查),必须带 thead/tbody 真实内容行,不能只有 caption。
   附带地,图注(含 Table 系列)默认放在 figure 内由 figcaption 承载,天然占满容器宽度、
   正常换行。
5. 正文包含:封面 header(标题/作者/arXiv 链接/关键词 pill)、目录导航、按"背景→观察→方法→系统→实验→
   补充→点评"讲述、每节 `sec-no`+`h2.sec`、局部 `note`/`takeaway` 强调块、公式用 `.math` 块、
   结尾脚注说明"图片为原文高清提取"。
6. 中文文本与 HTML 结构用文件写入,避免 heredoc 转义问题;超长 HTML 分 part1/part2 写后 `cat` 合并。
7. **读者体验层(v2 模板内置,必须保留)**:深色模式(记忆偏好、默认跟随系统)、顶栏章节跳转、
   点击图片 lightbox 看原图、回到顶部、文末术语速查章节(正文缩写用 `<abbr title>` 悬停释义)、
   公式用 KaTeX 渲染(display `$$…$$` + 内联 `$…$`),避免 Unicode 组合字符(Ĥ/H̄/τ₀ 等)在部分字体下错位、og 分享标签、打印友好(@media print)。校验器会逐项检查这些特性,
   缺失即 FAIL。
8. **溯源标注(推荐;缺项时校验器输出 WARN 提醒)**:速览章"读数约定"note、上游方法的行内引用、
   点评章"技术来源一览"表与"未披露、值得补测"清单、每张图注末尾的原文页码(`span.pgref`)。
   做法与代码样例见下节"溯源与深读增强"。

> **经验教训(MMLongEmbed 精读页踩坑)**:某次修复把"空表格壳"误删成"整个容器",
> 连带删掉了嵌套其中的表格原图 `<figure>`,页面只剩 caption 文字。教训有两点:
> ① 不要为标题包空表格壳——标题直接放 figcaption,避免嵌套结构剪不断理还乱;
> ② 修改既有 HTML 时,先 `grep -A3 '<table class="data">'` 看清楚真实嵌套结构再动手,
> 删除用精准的闭标签匹配并本地验证 `validate.py` + 数 `<figure class="fig">` 数量,
> 提交前务必确认表格图片引用(`figs/tableN.png`)一条不少。

### 溯源与深读增强(推荐;校验器对缺项输出 `WARN (recommended)`)

精读页的可信度来自"每个数字都能回到原文"。以下四件套把它做成读者可见的规范:

**① 读数约定(速览章 `.note`)**

```html
<div class="note"><b>读数约定:</b>本页全部数字以论文原文为准;凡由本页依据论文配置整理、归纳或换算的内容,
均以「<b>整理</b>」「<b>推算</b>」显式标注,便于与论文口径区分。记号沿用论文:$L$ 为总层数,$m$ 为压缩率。</div>
```

英文版对应 "Reading conventions:",标注用 **[organized] / [estimated]**。

**② 引用与来源标注**

- 正文首次提到上游方法时给行内引用 `(Author et al., Year)`——引用口径取自论文自己的标注,
  不要自行补论文没引的文献;
- 点评章加"技术来源一览"真实数据表(`<table class="data wrap">`,三列:组件 / 论文标注的上游 /
  本代的改造),caption 用描述性标题(**禁止**以 "Table N" 开头,会触发表号 1..N 完整性校验);
  表尾注明"引用为论文行内标注口径,本页未逐条核对参考文献条目"。

**③ 配置落到具体数字的走查(方法章)**

- 讲完抽象机制后,补一段"把论文配置落到层号/张量/参数"的走查:列出论文给出的关键配置,
  并推出一个可数的结论——如"编码器 3 组×6 层、解码器 5 组×4 层,全模型 40 层里只有 4 层
  真正从零生成全局 KV";
- 只列论文确实给出的配置;直接加总的标「整理」,凡是换算/推算的标「推算」并给出换算过程。

**④ "未披露、值得补测"清单(点评章)**

- 3–5 条,与"论文自述局限"分开写;措辞用"未见…披露 / 值得… / 待…"的开放句式;
- 断言"论文没有 X"之前先全文检索确认(如 `grep throughput paper.txt`);
- 区分"论文口径的数字"与"本页机制归纳"(如"每 token 890 字节"是论文总量,分项拆解是本页归纳)。

**图注原文页码**:每张 figcaption 末尾(解读行之后)加 `<span class="pgref">报告 p.X</span>`
(英文版 `Report p.X`),用脚本从 crops.json 批量注入(幂等、自动补 CSS、缺图会报错):

```bash
python3 "$SKILL_DIR/scripts/add_pagerefs.py" res.html crops.json                        # 中文页
python3 "$SKILL_DIR/scripts/add_pagerefs.py" en.html crops.json --label "Report p.{p}"  # 英文页
```

## 第 5 步:校验

**在 HTML 所在目录运行**(相对路径 `figs/` 才能解析):

```bash
cd <HTML所在目录>
python3 "$SKILL_DIR/scripts/validate.py" res.html
```

检查:① 引用的每个 img 存在且无缺;② Figure 数、Table 数与论文一致;③ Table caption 编号
1..N 完整、无重复;③b 图注里的 `<b>Figure N:</b>` / `<b>Table N:</b>` 标签同样必须 1..N 不重不漏
(漏一个编号 = 漏一张图表);④ 所有 `href="#..."` 锚点存在;⑤ 标签开闭平衡;⑥ 每个 img 都带
`max-width:100%` 与 `height:auto`;⑦ 关键数字出现(抽查);⑧ **无"空表格壳"**——形如
`<table class="data"><caption>…</caption></table>`、只有标题没有内容单元格的表格会被
校验器判 FAIL(术语速查等真实数据表不受影响)。⑨ 页面里若存在语言切换器
(`class="lang-toggle"` 的链接),其 `href` 指向的本地文件必须真实存在;⑩ `span.pgref` 要么每张
图注都有、要么一张都没有(只标一部分判 FAIL)。⑪ **自绘图合规**——带 `data-selfchart` 的 figure
必须在图注里标「本页自绘 / Self-drawn」,且**不得**使用 `Figure N:` / `Table N:` 编号(见第 5.5 步)。
全部 PASS 才可交付。

推荐项缺失不判 FAIL,以 `WARN (recommended)` 提示:读数约定 / 行内引用 / 原文页码 / 待补测清单 /
没有来源标注的 figure(既无 `Figure N:` 也无「本页自绘」标记)。

## 第 5.5 步(可选):本页自绘图表(对接 lieflat-charts)

主题是**论文原图**;当论文给不出一张你需要的图时,才自绘。
**完整规程见 [`references/lieflat-charts.md`](references/lieflat-charts.md)**,片段模板见
[`assets/chart-figure.html`](assets/chart-figure.html)。要点:

- **什么时候画**:关键数字散落在多张表里需要合并;论文只有数字没有图;需要一张"原文没有"的推导
  视图(如把配置落到层号上的走查)。**论文已有对应图就不要重画** —— 原图是权威,重画会引入失真。
- **三条硬规则**:
  1. **不占用编号** —— 图注禁止以 `Figure N:` / `Table N:` 开头,必须标「本页自绘 / Self-drawn」,
     并带 `data-selfchart="1"`(校验器据此判 FAIL);
  2. **数据可溯源** —— 每个数字都要能指回原文某表/某页;跨表合并、换算一律标「整理」或「推算」;
     **不得引入论文之外的任何数字**;
  3. **单文件、可离线** —— 优先导出 SVG/PNG 放 `figs/` 用 `<img>` 引用(lightbox/打印/图片校验天然复用);
     必须内联 HTML 图表时内联全部依赖,不引 CDN。
- **选型与绘制交给 lieflat-charts skill**(用户级技能目录,通常是 `~/.agents/skills/lieflat-charts/`):
  按 `catalog.md` 用**数据形状**选型 → 先审计 Lupi Editorial(L1–L19)与 Lupi Basics(F1–F17),各比较
  至少 3 个并写下淘汰理由 → 才允许降到 Glance → 以锁定的 gallery 卡片为结构骨架改数据 → 从
  `mono-tokens.js` 或**一套** `color-presets.js` 预设取色。未安装时降级为手写 SVG,仍须遵守上面三条。
- **一页只用一套色彩系统**,且自绘图要同时适配深色与浅色模式。

> ⚠️ **许可**:lieflat-charts 采用 **PolyForm Noncommercial License 1.0.0**(非商业),与本技能仓库的
> MIT 不同 —— 因此**只按依赖调用,不把它的模板/代码复制进本仓库或产物再分发**。自绘图的成品可以随
> 精读页发布(那是使用产出);若要再分发它的模板文件本身,需遵守其许可证并署名(开发者为「躺在废墟里」)。

## 第 6 步(可选):推送与 GitHub Pages 部署

skill 目录本身可推送到远程仓库;精读页推独立的 `<PaperName>-Project-Page` 仓库并开 Pages(模仿
`https://<user>.github.io/<PaperName>-Project-Page/` 的项目页形态):

```bash
gh repo create <PaperName>-Project-Page --public --source=. --push
gh api -X POST repos/<user>/<PaperName>-Project-Page/pages \
  -f "source[branch]=main" -f "source[path]=/"
```

交付时:报告 HTML 路径、figs/ 目录、仓库链接、Pages URL。

## 第 7 步(可选):中英双语版(中文精读 + English edition)

用户要求"英文版 / 中英切换 / 面向国际读者"时,在**同一论文目录**加 `en.html`,与中文页共用
`figs/`(绝不重复提取图片),不改动已交付的中文页。英文版深度按论文重要性二选一:

- **完整英文镜像**(旗舰论文):全部章节、全部图表、逐段翻译,结构 1:1 对应中文页;
- **英文速读版**(常规论文):完整速览(kv 卡列贡献/关键数字)+ 论文全部图表按叙述顺序内嵌
  (原图注 + 英文解读)+ 点评。体量约为镜像版一半,但**图表一张不少**。

### en.html 的约定

- `<html lang="en">`;读者体验层(深色模式/顶栏/lightbox/KaTeX/术语表 `id="s9"`/abbr 悬停)
  与中文页完全一致,校验器同样强制检查。
- 图注结构对应中文页的 `.zh` 解读行,改用 `<span class="ex">` 承载英文解读(CSS 样式照抄 `.zh`):

```html
<figcaption>
  <b>Figure 7:</b>Using $\hat{H}_{\text{step}}$ only can misclassify low-entropy tokens.
  <span class="ex">If the step-relative threshold were used everywhere, ...</span>
</figcaption>
```

- **速读版里的真实 HTML 数据表,`<caption>` 禁止以 "Table N:" 开头**:校验器要求
  `<caption>Table N` 编号 1..N 连续完整,速读版只收录论文表格的子集,必然断号判 FAIL。
  写描述性标题并括注出处,如 `<caption>AIME-120 accuracy (from the paper's Table 1)</caption>`
  ——不触发编号检查,信息也不丢。(镜像版收录全部表格时不受此限。)
- 公式里出现 `<`/`>`(如 `\begin{cases}` 的分支)必须写 `&lt;`/`&gt;` 实体,DOM 文本解码后
  KaTeX 才能正确解析。
- 溯源四件套同样镜像:速览章 "Reading conventions" note、行内引用、点评章 lineage 表与
  "Not disclosed, worth testing next" 清单;图注页码用 `--label "Report p.{p}"` 注入。

### 语言偏好约定(pr-lang)

全站统一用 `localStorage['pr-lang']`(`'zh'`/`'en'`)记住读者选择,**首次访问跟随浏览器语言**
(任何 `zh` 开头的 locale → zh,否则 en)。判定逻辑固定写法:

```js
var lang = null; try{ lang = localStorage.getItem('pr-lang'); }catch(e){}
if (lang !== 'zh' && lang !== 'en') {
  lang = String(navigator.language || navigator.userLanguage || 'en').toLowerCase().indexOf('zh') === 0 ? 'zh' : 'en';
}
```

### 精读页的语言切换器

每个中文页顶栏(theme-toggle 旁)加 EN 按钮,**先写偏好再跳转**,让目标页直接以所选语言
渲染;英文页对称地链回中文页。样式与 theme-toggle 同族:

```css
.lang-toggle{border:1px solid var(--border); background:var(--card); color:var(--ink);
             border-radius:8px; padding:4px 10px; font-size:12.5px; cursor:pointer;
             text-decoration:none; font-weight:700; white-space:nowrap}
.lang-toggle:hover{border-color:var(--accent); color:var(--accent)}
```

```html
<!-- 中文页 → 英文版 -->
<a class="lang-toggle" href="en.html" title="Read in English"
   onclick="try{localStorage.setItem('pr-lang','en')}catch(e){}">EN</a>
<!-- 英文页 → 中文版(中文页文件名按实际,如 index.html) -->
<a class="lang-toggle" href="index.html" title="阅读中文版"
   onclick="try{localStorage.setItem('pr-lang','zh')}catch(e){}">中文</a>
```

### 门户/索引页:页内双语(inline i18n)

合集首页等多语言导航页**不要**复制成两份 HTML,用"双 span + CSS 显隐"在同一页内即时切换:

```html
<!-- ① <head> 最前面、首帧绘制前设置 lang,避免闪一下错语言 -->
<script>
(function(){
  var lang = null;
  try{ lang = localStorage.getItem('pr-lang'); }catch(e){}
  if (lang !== 'zh' && lang !== 'en') {
    lang = String(navigator.language || navigator.userLanguage || 'en').toLowerCase().indexOf('zh') === 0 ? 'zh' : 'en';
  }
  document.documentElement.lang = (lang === 'en') ? 'en' : 'zh-CN';
})();
</script>
```

```css
/* ② 双语并存,按 html lang 显隐(zh 两种写法都要覆盖) */
html[lang="en"] .i18n-zh{display:none!important}
html[lang="zh-CN"] .i18n-en{display:none!important}
html[lang="zh"] .i18n-en{display:none!important}
```

```html
<!-- ③ 文案成对书写;卡片等链接按语言分别指向对应语言版本 -->
<span class="i18n-zh">论文精读合集</span><span class="i18n-en">Paper Reading Collection</span>
<button class="lang-toggle" id="langToggle" title="Switch language / 切换语言">
  <span class="i18n-zh">EN</span><span class="i18n-en">中文</span>
</button>
```

```js
// ④ 切换:只改 lang 属性(CSS 连动),顺手换标题
var TITLES = {zh:'论文精读合集', en:'Paper Reading Collection'};
function curLang(){ return document.documentElement.lang === 'en' ? 'en' : 'zh'; }
function applyTitle(){ document.title = TITLES[curLang()]; }
applyTitle();
document.getElementById('langToggle').addEventListener('click', function(){
  var next = curLang() === 'en' ? 'zh' : 'en';
  document.documentElement.lang = next === 'en' ? 'en' : 'zh-CN';
  try{ localStorage.setItem('pr-lang', next); }catch(e){}
  applyTitle();
});
```

优点:不用 innerHTML 换文案(链接与事件全保留)、两种语言都在 DOM 里(SEO 双收)、
`<head>` 内联脚本先于首帧执行不闪屏。注意两点:打印样式里隐藏 `.lang-toggle`;
门户卡片在两种语言下**直接指向对应语言页面**(不要依赖重定向)。

### 目录入口的语言分流

若论文目录有 `index.html` 入口,改成"读 pr-lang → `location.replace` 到对应语言页"的
重定向 stub,并留无 JS 兜底链接:

```html
<script>
(function(){
  var ZH = 'Declarative-Attention论文精读_HTML.html', EN = 'en.html';
  var lang = null; try{ lang = localStorage.getItem('pr-lang'); }catch(e){}
  if (lang !== 'zh' && lang !== 'en') {
    lang = String(navigator.language || navigator.userLanguage || 'en').toLowerCase().indexOf('zh') === 0 ? 'zh' : 'en';
  }
  location.replace(lang === 'en' ? EN : ZH);
})();
</script>
<p>正在跳转…… Redirecting…</p>
<p><a href="中文页.html">中文精读版</a> · <a href="en.html">English edition</a></p>
```

重定向只兜"直接输入目录 URL"的场景;且该 stub 不是阅读页,不必过校验器。

### 双语版的校验与上线

- `en.html` 与中文页跑**同一个** `validate.py`(在页面所在目录运行),`SPOT_CHECKS` 各自抽查
  关键数字,双语两版都要 PASS 才可交付;
- 推送后先等 Pages 构建完成再验收,早测 404 多半只是传播延迟:

```bash
gh api repos/<user>/<repo>/pages/builds/latest --jq '.status'   # 期望 "built"
```

- 验收脚本逐页 GET 全部页面,并解析每页 `<img src="figs/...">` 全量回访(单次失败重试 2 次,
  规避本机偶发 SSL 抖动),要求 failures=0。

## 目录

```
paper-reading-html/
├── SKILL.md                ← 本文件
├── README.md               ← 读者视角的使用指南(两种用法 + 铁律)
├── references/
│   └── lieflat-charts.md   ← 本页自绘图表的完整规程(何时画 + 交付契约 + 对接方式 + 许可)
├── assets/
│   ├── template.html       ← HTML 骨架(样式 + 结构)
│   ├── chart-figure.html   ← 自绘图表的插入片段(data-selfchart + 「本页自绘」标注)
│   └── example_paper.pdf   ← CI 冒烟测试用样例论文
├── scripts/
│   ├── locate_figs.py      ← 自动检测图表位置 → crops.json
│   ├── extract_figs.py     ← crops.json → 300DPI PNG
│   ├── add_pagerefs.py     ← crops.json → 图注原文页码(span.pgref)
│   └── validate.py         ← HTML 完整性校验
└── .github/workflows/validate.yml  ← CI:语法 + locate 冒烟 + 模板完整性
```