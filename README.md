# BugBits source snapshot

这是游戏逆向研究与重实现的**MIT源码快照**，包含当前Python模块、网页源码、工具、harness与选定测试。它不是原游戏发行包，也不是已完成的忠实复刻。

## 内容与授权

本快照不含原游戏EXE、DLL、DATA、纹理、模型、关卡、动画、音频、截图、内存采样、烘焙图集或网页运行包。原Git历史、私有配置、第三方技能和未逐项审查的研究材料也不包含。

原游戏及相关名称、素材的权利归各自权利人；此项目与权利人没有已确认的关联或认可。本快照不提供原素材的下载链接、破解或许可绕过功能。

**项目代码按MIT许可证发布**，见根级`LICENSE`。用户已确认有权公开项目代码并选择MIT。此源码快照已准备，但远程GitHub上传状态须由实际发布回执确认。

`web/NotoSansSC-subset.woff2`是独立第三方字体，按SIL OFL-1.1提供，见`web/OFL.txt`。项目MIT代码许可不覆盖该字体，也不授权任何原游戏素材。

## 本地资源

解析、渲染和游戏集成需要使用者自行提供有权使用的本地游戏数据。代码支持`BUGBITS_DATA`指定包含`data/`的安装根目录；检查`src/bugbits/assets/__init__.py`的路径规则。没有这些资源，不能直接运行原作关卡或生成网页资源包。

Python渲染部分使用Pillow，浏览器运行包使用Pyodide；本快照没有打包这些第三方运行时。Web目录是源码，直接打开index.html不等于装载完整游戏。

选定测试保留了资源相关用例，因此不能在无原素材环境宣称全套测试通过。以下合成格式测试不需要原素材，可在安装所需Python依赖后执行：

```sh
PYTHONPATH=src:tests python3 -B -m unittest test_assets_v3d_world_synthetic
```

依赖内部research或私有原运行证据的部分测试不在此快照；完整开发现场和原验收报告没有上传。

## 发布清单

`PUBLICATION_MANIFEST.json`记录复制代码的路径、字节数与SHA256，以及排除内容、已确认的授权和尚未执行的GitHub上传状态。审查说明见`PUBLICATION_REVIEW.md`。

目标：GitHub公开仓库`tomcatgwl/bugbits-source`。本地Git仓库是新建的单一源码快照，不携带开发仓库的旧历史。
