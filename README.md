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
