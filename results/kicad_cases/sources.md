# Public KiCad PCB case sources

KiCad CLI version: `10.0.2`.

The cases below are converted from public KiCad PCB projects. The experiment uses KiCad CLI when available to export original board images, then parses `.kicad_pcb` S-expression text to extract connector/gold-finger-like footprint parameters.

| Case | Repository | License | PCB file | Selected footprint | Pins | Pitch/mm | Export | Obstacles |
|---|---|---|---|---|---:|---:|---|---|
| kicad_pcie_test_dual_ww37 | [mengstr/PCIeTestPCB](https://github.com/mengstr/PCIeTestPCB) | CC0-1.0 | `data/kicad_public/PCIeTestPCB/PCIeTest.kicad_pcb` | `matseng:PAD64-1.5_1.0` | 64 | 1.5 | kicad_cli | 47.6:11.4:65.8:19.5;86.8:7.1:106.4:14.9 |
| kicad_pi5_pcie_breakout | [m1geo/Pi5_PCIe](https://github.com/m1geo/Pi5_PCIe) | MIT | `data/kicad_public/Pi5_PCIe/Pi5_PCIe.kicad_pcb` | `10018783-11200TLF:AMPHENOL_10018783-11200TLF` | 36 | 2.0 | kicad_cli | 59.8:9.0:78.8:16.0 |
| kicad_pi5_m2_hat | [m1geo/Pi5_PCIe](https://github.com/m1geo/Pi5_PCIe) | MIT | `data/kicad_public/Pi5_PCIe/Pi5_M2_Hat.kicad_pcb` | `ngff:AMPHENOL_MDT420M03001` | 69 | 2.54 | kicad_cli | 42.8:11.7:59.2:20.0;78.1:7.3:95.7:15.3 |
| kicad_pcie_aux_signal_breakout | [Supercookiegaming/PCIe-Aux-Signal-Breakout](https://github.com/Supercookiegaming/PCIe-Aux-Signal-Breakout) | not specified in GitHub API result | `data/kicad_public/PCIe-Aux-Signal-Breakout/KiCad/PCIe-Aux-Signal-Breakout/PCIe-Aux-Signal-Breakout.kicad_pcb` | `PCIexpress:PCIexpress_x1` | 36 | 1.0 | kicad_cli | 39.1:9.0:51.5:16.0 |
