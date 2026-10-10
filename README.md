# BugBits source snapshot

这是游戏逆向研究与重实现的**MIT源码仓库**，包含Python模块、网页源码、工具、harness、选定测试及经过审查的独立原生内核与网格数组工具。它不是原游戏发行包，也不是已完成的忠实复刻。

## 内容与授权

本快照不含原游戏EXE、DLL、DATA、纹理、模型、关卡、动画、音频、截图、内存采样、烘焙图集或网页运行包。原Git历史、私有配置、第三方技能和未逐项审查的研究材料也不包含。

原游戏及相关名称、素材的权利归各自权利人；此项目与权利人没有已确认的关联或认可。本快照不提供原素材的下载链接、破解或许可绕过功能。

**项目代码按MIT许可证发布**，见根级`LICENSE`。用户已确认有权公开项目代码并选择MIT。本仓库已发布；新增进展按相同素材排除与许可边界审查后提交。

`web/NotoSansSC-subset.woff2`是独立第三方字体，按SIL OFL-1.1提供，见`web/OFL.txt`。项目MIT代码许可不覆盖该字体，也不授权任何原游戏素材。

## 本地资源

解析、渲染和游戏集成需要使用者自行提供有权使用的本地游戏数据。代码支持`BUGBITS_DATA`指定包含`data/`的安装根目录；检查`src/bugbits/assets/__init__.py`的路径规则。没有这些资源，不能直接运行原作关卡或生成网页资源包。

Python渲染部分使用Pillow，浏览器运行包使用Pyodide；本快照没有打包这些第三方运行时。Web目录是源码，直接打开index.html不等于装载完整游戏。

选定测试保留了资源相关用例，因此不能在无原素材环境宣称全套测试通过。以下合成格式测试不需要原素材，可在安装所需Python依赖后执行：

```sh
PYTHONPATH=src:tests python3 -B -m unittest test_assets_v3d_world_synthetic
```

依赖内部research或私有原运行证据的部分测试不在此快照；完整开发现场和原验收报告没有上传。

## 独立原生内核

`native/`只包含自主编写的字节处理代码、Godot项目配置、独立引用生命周期元数据与合成测试，不包含完整原生游戏或任何原作运行数据。代码实现整数时域/空间滤波和固定像素中心缩小；接口、限制和无需原素材的测试命令见 [native/README.md](native/README.md)。内核测试通过不能证明完整画面、遮挡或游戏还原通过。

## 发布清单

`PUBLICATION_MANIFEST.json`记录当前发布代码的路径、字节数与SHA256、排除内容和已确认的授权。新增发布审查见`PUBLICATION_REVIEW.md`。文件清单不替代远程提交回执。

目标：GitHub公开仓库`tomcatgwl/bugbits-source`。仓库从独立源码快照开始，后续增量提交仍不携带私有开发仓库的旧历史。

Camera controls now also provide in-page buttons for the available views. They share the existing selection, level eligibility and asynchronous loading rules. The native select remains available. This compatibility entry does not establish the cause of a specific embedded-browser failure or original-game visual fidelity. The repository still contains no original assets.

Camera selection now retains the requested view while loading and shows a loading status. Success commits the view; failure restores the current view and reports the reason. This UI repair does not change camera matrices or establish original-game visual fidelity.

Camera mesh loading uses the selected level dependency closure, including future scripted units, and downloads at most four resources concurrently. Packages without unit dependency metadata keep the full-unit fallback. Size/SHA checks, cancellation and atomic view commit remain enabled. The 30-second deadline and camera matrices are unchanged. Synthetic resource-loading tests require Node.js and no game assets: `PYTHONPATH=src:tests python3 -B -m unittest test_mesh_resource_loading`.
