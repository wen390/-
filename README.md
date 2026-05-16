# PCB 金手指测试尾板布点布线原型

本工程用于支撑毕业设计《面向 PCB 金手指的测试尾板布点布线设计》。程序采用 C++17 编写，读取案例参数 CSV，生成测试点布点、布线路径、实验指标和 SVG 可视化结果。

## 构建

如果本机安装了 CMake：

```bash
cmake -S . -B build
cmake --build build
```

当前工作区也已经配置了本地 CMake wheel，可直接使用：

```bash
.venv/bin/cmake -S . -B build
.venv/bin/cmake --build build
```

macOS 环境还可直接使用 Makefile：

```bash
make
```

## 运行

```bash
./pcb_tail_router --case data/case_01.csv --out results/case_01
```

批量运行 5 个仿真实验案例：

```bash
make run-all
```

每个结果目录包含：

- `placement.csv`：测试点坐标。
- `routes.csv`：每条网络的布线成功状态、线长和路径。
- `metrics.csv`：各算法的覆盖率、布通率、面积占比、线长、违规数、拥塞峰值、拥挤网格数和运行时间。
- `layout.svg`：金手指、障碍区、测试点和布线路径可视化。
- `layout_baseline_rule.svg`：人工/规则基线方案的布线结果。
- `layout_kmeans_tabu_astar.svg`：K-means + 禁忌搜索方案的布线结果。
- `layout_pso_hanan_tabu_astar.svg`：PSO-Hanan 候选引导方案的布线结果。
- `layout_pso_congestion_reroute_astar.svg`：拥塞反馈拆线重布方案的布线结果。

## 公开 KiCad 案例实验

公开 PCB 案例实验脚本优先调用 KiCad CLI 导出原始 PCB 板图，再抽取连接器参数并运行本工程算法。macOS 官方安装包中的默认路径为：

```bash
/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
```

脚本的探测顺序为：环境变量 `KICAD_CLI`、系统 `PATH` 中的 `kicad-cli`、上述 macOS 官方路径。若 KiCad CLI 不可用，脚本会回退到 `.kicad_pcb` 文本解析，并在报告中标注为 fallback。

运行公开案例实验：

```bash
.venv/bin/python tools/kicad_public_experiments.py
```

如需手动指定 KiCad CLI：

```bash
KICAD_CLI=/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli .venv/bin/python tools/kicad_public_experiments.py
```

输出位于 `results/kicad_cases/`：

- `summary.csv`：论文表格用的指标汇总。
- `experiment_report.md`：KiCad CLI 版本、公开仓库来源、许可证、指标口径和结果说明。
- `comparison_contact_sheet.png`：原始 KiCad PCB、规则基线布线和设计算法布线的总览截图。
- 每个案例目录中的 `original_kicad_pcb.svg/.pdf/.png`：由 KiCad CLI 导出的原始 PCB 截图。
- 每个案例目录中的 `comparison_original_baseline_algorithm.png`：原始 PCB、基线方案、设计算法的三联对比图。

## 真实 EDA 文件解析实验

审阅意见补充版实验进一步接入真实 EDA 文件解析，脚本会读取公开 KiCad 工程，并在项目提供制造文件时解析 Gerber/Excellon 信息；解析结果会转换为算法 CSV，其中 `pin_positions` 字段保存从真实焊盘抽取的端子坐标。

```bash
KICAD_CLI=/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli .venv/bin/python tools/eda_case_experiments.py
```

输出位于：

- `data/eda_cases/`：由公开 EDA 文件解析得到的算法输入 CSV。
- `results/eda_cases/summary.csv`：真实 EDA 案例的对比实验汇总。
- `results/eda_cases/eda_parse_report.md`：解析字段、公开来源、KiCad CLI 版本和量化结论。
- `results/eda_cases/sources.md`：公开仓库 URL、许可证和文件类型说明。
- `results/eda_cases/eda_contact_sheet.png`：原始 EDA/KiCad 板图、解析覆盖图和算法布线结果总览。

对应论文补充稿由下列脚本生成：

```bash
/Users/yunhe/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 tools/build_eda_supplement_docx.py
```

## 算法说明

布点阶段先根据尾板尺寸、网格步长和障碍区生成候选测试点；再用金手指横向分布近似 K-means 分组，得到测试点初始目标带；随后用局部禁忌搜索降低线长和拥挤度。`pso_hanan_tabu_astar` 参考 `secret4233/auto_routing` 中 PSO/Hanan 点优化思想，但按本工程数据结构重新实现，不直接复制外部源码。最新的 `pso_congestion_reroute_astar` 进一步参考网络流论文中的拥塞建模/预布线思想、蚁群论文中的信息素/拆线重布思想，对预布线路径建立动态拥塞图，并在 A* 代价中加入历史拥塞惩罚。实验中的四组方法分别为：

- `baseline_rule`：规则行列式布点基线。
- `kmeans_tabu_astar`：K-means 分带 + 禁忌搜索 + A*。
- `pso_hanan_tabu_astar`：PSO 参数搜索 + Hanan 思想候选引导 + 禁忌搜索 + A*。
- `pso_congestion_reroute_astar`：PSO-Hanan 布点 + 动态拥塞代价 + 拆线重布式 A*。

## 文档渲染环境

工作区已配置本地 LibreOffice：

```bash
tools/LibreOffice.app/Contents/MacOS/soffice --version
```

论文 DOCX 已通过 LibreOffice 转为 PDF，并使用 `tools/render_pdf_pages.py` 渲染为逐页 PNG。渲染产物位于：

```bash
results/thesis_render_full/
```
