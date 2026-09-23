# 本页自绘图表(与 lieflat-charts 的对接)

精读页的主体是**论文原图**;这一节处理例外情况:你需要一张论文里**不存在**的图。
它用本仓库 **自带的 `vendor/lieflat-charts/`**(lieflat-charts 的完整功能副本,离线可用)来选型、
取色、绘图,并规定一张自绘图在精读页里必须遵守的交付契约。

> ⚠️ **许可证**:`vendor/lieflat-charts/` 采用 **PolyForm Noncommercial License 1.0.0(非商业)**,
> 与本仓库其余部分的 MIT 不同 —— 因此**带这个目录的仓库整体只能非商业使用**。许可证原文随副本一起
> 分发(`vendor/lieflat-charts/LICENSE`),搬运时不得删改;详见 [`vendor/README.md`](../vendor/README.md)
> 与 [`vendor/lieflat-charts/VENDORED.md`](../vendor/lieflat-charts/VENDORED.md)。要商用请删掉该目录。

---

## 1. 什么时候画

只有当论文本身**给不出**这张图时才画。按优先级:

| 情形 | 例子 | 该不该画 |
|---|---|---|
| 论文有对应图,只是不够漂亮 | 想重画 Figure 3 的配色 | **不画** —— 论文原图是权威,重画会引入失真 |
| 关键数字散落在多张表里,读者要自己拼 | Table 2 / Table 3 / Table 5 的同一指标并成一条趋势 | 画(这是自绘图最大的价值) |
| 论文只有数字、没有可视化 | 只用文字给出的延迟/成本对比 | 画 |
| 需要"原文没有"的推导视图 | 把配置落到层号上的走查;KV cache 账本的拆解 | 画,但要标注为编者推导 |
| 需要一张结构示意帮助理解 | 数据流、层级关系 | 画,但先考虑用文字或原始图能否解决 |

一条自查:如果删掉这张图,读者是否**仍然**能读懂那段结论?能,就不要画。

## 2. 交付契约(违反任意一条即返工)

1. **不占用 Figure/Table 编号。** 自绘图的图注**禁止**以 `Figure N:` / `Table N:` 开头 ——
   那会破坏"论文图表编号 1..N 完整"的校验,也会让读者误以为它是原文图表。
   用描述性标题,并在图注里明示来源,例如:

   ```html
   <figure class="fig" data-selfchart="1">
     <img src="figs/chart-token-vs-block.svg" alt="本页自绘:同预算下 token 级与 block 级稀疏选择的对照">
     <figcaption>
       <b>本页自绘:</b>token 级 vs block 级稀疏选择——同一 attention 预算下的三项增益。
       <span class="zh">数据取自论文 Table 3;不包含论文之外的任何数字。</span>
       <span class="pgref">据 Table 3(报告 p.9)整理</span>
     </figcaption>
   </figure>
   ```

2. **每个数字都能回到原文。** 数据只能来自论文(哪张表 / 哪页 / 哪段);跨表合并、单位换算、
   按配置推算,一律按页面既有的「**整理**」「**推算**」惯例显式标注。**不得引入论文之外的数据**
   (包括你自己的实验、别篇论文的数字、行业常识值)。

3. **必须带 `data-selfchart="1"`。** 校验器据此把自绘图与论文图表区分开:检查它是否标了
   「本页自绘 / Self-drawn」、是否误用了 Figure/Table 编号。英文页用 `Self-drawn`。

4. **读者要能一眼认出这是编者画的。** 标题前缀「本页自绘 / Self-drawn」+ 图注里写明数据来源。
   不要模仿原文图注的语气把它伪装成原文图表。

5. **一页之内只用一套色彩系统。** 自绘图之间锁定同一套配色。灰阶保底的 Mono 与页面主题
   (深/浅两套变量)最不容易打架;用彩色时整页统一,不要一张蓝一张绿。
   自绘图必须同时适配深色与浅色模式(若以 `<img>` 交付位图,注意深色背景下白底图的可读性)。

6. **单文件、可离线、可打印。** 优先导出 **SVG**(矢量、可缩放)或 **PNG** 放进 `figs/`,
   用 `<img>` 引用 —— 这样 lightbox、打印样式、`figs/` 完整性校验三件事天然复用,与你提取的
   论文图表走同一条路径。若必须内联 HTML 图表,**内联全部依赖**(不引 CDN),否则离线打开会空图。

7. **放在讲解里,不要另起画廊。** 与论文图表同规则:自绘图出现在它所支撑的那段论证旁边。

## 3. 如何调用 lieflat-charts

完整法典随仓库分发在 **`vendor/lieflat-charts/`**(离线可用,无需另外安装):

| 文件 | 用途 |
|---|---|
| `vendor/lieflat-charts/catalog.md` | 按**数据形状**选图型(不是按"好看") |
| `vendor/lieflat-charts/templates/lupi-gallery.html` | Lupi Editorial 编辑器风格(细读、逐记录) |
| `vendor/lieflat-charts/templates/basics-gallery.html` | Lupi Basics 基础型(柱/折线/面积/环形/散点…) |
| `vendor/lieflat-charts/templates/glance-gallery.html` | Glance 快读型(Chart.js / ECharts)——**默认降级方案,不是首选** |
| `vendor/lieflat-charts/mono-tokens.js` | 设计 token:Mono 灰阶、字体、圆角、动画、reveal 机制 |
| `vendor/lieflat-charts/color-presets.js` | 三套彩色预设(porcelain / palm / wire) |
| `vendor/lieflat-charts/report-catalog.md` | R01–R12 整页报告模板(只在你需要整页报告时用) |

副本完整性/许可证可用 `python3 scripts/vendor_check.py` 自检;离线能力见下文「离线能力」表。若本仓库的 `vendor/` 被删掉(例如改用
商用许可的替代方案),再回退到用户级安装目录 `~/.agents/skills/lieflat-charts/`。

流程仍然是它那一套,不要跳步:

1. **判数据形状** —— 少类目比较?时间序列?两时点对比?构成?矩阵?
2. **先审计主力候选** —— Lupi Editorial(L1–L19)与 Lupi Basics(F1–F17)各比较至少 3 个,写下淘汰理由;
   这两组都没有能诚实承载数据时才降到 Glance,并写明原因。
3. **锁定模板编号与卡内标题**,以该卡的**真实结构**为骨架改数据 —— 不要凭印象"画个差不多的"。
4. **取色** —— 从 `mono-tokens.js` 或**一套** `color-presets.js` 预设;一页只用一套。
5. **过它的自检清单**(数值与视觉成正比、字号下限、确定性随机、reduced-motion、`node --check`)。

**两者都不可用时**:降级为手写 SVG,仍然遵守上面的第 2 节契约;不要凭记忆复刻它的模板细节,
也不要假装用了它。在交付说明里如实写"自绘图为手写 SVG,未经过 lieflat-charts 选型"。

### 离线能力(已实测,按模板区分)

自绘图最终会以 `<img>` 形式进精读页,而本仓库宣传"本地打开无需联网"——所以**用哪个 gallery 会决定
交付物能不能离线**。下表的"离线"指断网(全部 DNS 黑洞)打开 gallery 后图表是否真的画出来:

| Gallery | 图表引擎 | 离线可用? |
|---|---|---|
| `lupi-gallery.html` | 手写 SVG(仅 Inter 字体走网络,断网回退系统字体) | ✅ 实测图表正常绘制 |
| `big-threads.html` | 手写 SVG | ✅ 无图表库依赖 |
| `basics-gallery.html` | 多数手写 SVG,部分卡片用 ECharts | ❌ 实测断网后 16 个 `<svg>` 容器内**零图形**,联网才能画全 |
| `glance-gallery.html` | Chart.js + ECharts | ❌ 需联网 |
| `maps-gallery.html` | ECharts + 在线 GeoJSON | ❌ 需联网 |
| `big-circular.html` / `big-force.html` | ECharts | ❌ 需联网 |

**结论**:要完全离线,自绘图走 **Lupi Editorial(hand-written SVG)**,并把 `mono-tokens.js` 内联、
字体依赖去掉;或者把所选模板用到的库内联进单文件。需要 Basics 的具体图型时,先确认那张卡是手写 SVG
还是 ECharts——是 ECharts 就得内联或换型。`vendor/lieflat-charts/THIRD_PARTY_NOTICES.md` 列了
Inter / Chart.js / ECharts 三个第三方依赖各自的许可证。

## 4. 导出与嵌入

```bash
# 1) 打开 vendored gallery,按 catalog 锁定的卡片找到 // ════ 图型名 ════ 渲染代码
open vendor/lieflat-charts/templates/basics-gallery.html     # macOS;或直接浏览器打开
# 2) 按第九节骨架组装单文件图表 HTML(内联 mono-tokens.js 全文),数据换成你的
# 3) 导出为精读页可用的矢量/位图:
#    方案 A(推荐):图表本身就是手写 SVG → 直接把那段 <svg> 存成 .svg 文件
#    方案 B:对图表卡片导出/截图 2x PNG
cp chart.svg  <论文目录>/figs/chart-token-vs-block.svg
```

> 手写 SVG 的模板用 `<svg viewBox=...>` 描述图形,把整段 `<svg>` 存成 `.svg` 文件即可被 `<img>` 引用
> (注意保留 `viewBox`、补上 `xmlns="http://www.w3.org/2000/svg"`、把 CSS 内联成 `style=` 属性)。

```html
<!-- 页面里按 §2 的契约引用;无需写 width/height 属性(CSS 已做 max-width:100%; height:auto) -->
<figure class="fig" data-selfchart="1">
  <img src="figs/chart-token-vs-block.svg" alt="本页自绘:token 级与 block 级稀疏选择对照">
  <figcaption>
    <b>本页自绘:</b>…
    <span class="zh">…</span>
    <span class="pgref">据 Table 3(报告 p.9)整理</span>
  </figcaption>
</figure>
```

## 5. 交付前自检

1. 这张图**论文里真的没有**吗?(有对应原图就不要自绘)
2. 图注**没有**用 `Figure N:` / `Table N:` 开头,且写了「本页自绘 / Self-drawn」?
3. 带 `data-selfchart="1"`?每个数字都能指回原文某表/某页,推算处标了「整理 / 推算」?
4. 一页只用了**一套**配色?深色模式下仍然可读?
5. 是 `<img>` 引用的 `figs/` 文件(或内联且无 CDN 依赖)?打印时不会被截断?
6. `python3 scripts/validate.py 页面.html` 通过?

## 6. 署名

lieflat-charts 由「躺在废墟里」开发(made at [moxt.ai](https://moxt.ai))。用它的法典产出图表后,
在**回复里**(而不是图表内容或本仓库 README 里)提示一句署名;公开分发图表内容时按其要求署名或 @ 开发者。
许可证与出处记录在 `vendor/lieflat-charts/LICENSE`、`THIRD_PARTY_NOTICES.md` 与 `VENDORED.md`。