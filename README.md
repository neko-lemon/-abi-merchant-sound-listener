# 暗区战地商人 · 听声识物

Windows 桌面工具，辅助识别《暗区突围：无限》战地商人神秘货物的拾起、放下音效。监听系统播放声音，按声音组列出中文物品名称、占格尺寸、联系人价格和类别；价值高于 100 万的物品价格用深红色标出；如果该声音组的某个规格里的物品**全部**超过 100 万（没有便宜货混在里面），占格下拉框右边会出现红色描边提示（例如「买2×3！」）。所有结果文字带黑色描边。支持窗口置顶、背景透明与鼠标穿透。

## 下载与使用

下载 `商人听金.exe`，双击运行。在播放设备下拉框中选择游戏声音实际输出的设备，点击“开始监听”，然后拖动神秘货物。可根据货物占格缩小候选范围。游戏里可以用全局热键：`Alt+4` 开始/停止监听，`Alt+5` 显示/隐藏窗口。

窗口置顶默认开启，可在主界面取消。窗口背景默认透明：整个窗口底色被抠掉，包括候选列表的背景，游戏画面完全可见；透明处的鼠标点击会穿透到游戏（拖动窗口请用标题栏）。识别结果只显示最相似的那一组，物品按左右两列排布，一屏能看全，不需要滚动；窗口可自由缩放，结果会按可用空间自动缩放字号。拖动“面板不透明度”滑块可让剩下的文字和控件一起变半透明。游戏使用独占全屏时，建议切换到无边框窗口模式。

程序不使用任何鼠标/键盘钩子：唯一涉及全局输入的是 `RegisterHotKey` 注册的两个热键。

**匹配分和音效峰值强度都不是掉落概率。** 多件物品可能共用同一声音组，仅靠音频无法区分组内物品。参考表包含 38 组音效及 189 件物品；非线性节点探测器不在当前参考表中。

## 从源码运行

需要 Windows 和 Python 3.11+。

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe merchant_listener.py
```

程序使用 `catalog.json` 和 `reference/`（76 段参考音效）。程序不读取游戏内存，也不上传录音。

源码按职责拆分：`merchant_listener.py`（入口与启动异常兜底）、`app.py`（界面与录音）、`matcher.py`（匹配算法）、`winutil.py`（全局热键、错误日志）、`textimg.py`（描边文字）、`resources.py`（路径与物品目录）。出错时会在 `%TEMP%\商人听金.log` 追加一行记录。

## 打包 exe

```bash
bash tools/build_exe.sh
```

产物为 `dist/商人听金.exe`（单文件、无控制台）；脚本结束时会自动清掉 `build/` 与 `.spec` 中间文件。脚本会先运行 `tools/patch_scipy_for_pyinstaller.py`：scipy 的 `stats/_distn_infrastructure.py` 末尾用模块级 `dir()` + `exec('del ...')` 清理临时字符串，这个写法在 PyInstaller 冻结环境里会抛 `NameError: name 'obj' is not defined`，导致 exe 启动即崩。补丁把该段换成等价函数（`tools/patch_scipy_for_pyinstaller.py`，幂等）。**重装依赖后需重新运行一次该脚本，或直接跑 `tools/build_exe.sh`。**

打包完可以跑一次自检（启动 exe、确认窗口出现、进程存活、没有新的错误日志）：

```bash
.venv/Scripts/python.exe tools/smoke_test.py dist/商人听金.exe
```

## 发布 Release

本地一键（构建 → 自检 → 打标签 → 推送 → 建 Release → 上传 exe）：

```bash
bash tools/release.sh                 # 自动把最新 vX.Y.Z 的补丁号 +1
bash tools/release.sh v1.2.0          # 指定版本
bash tools/release.sh v1.2.0 --draft --prerelease
bash tools/release.sh --dry-run       # 只构建、自检并打印计划，不动远端
```

认证二选一：`gh auth login`（推荐，脚本会自动用它），或 `export GITHUB_TOKEN=<带 repo 权限的 PAT>`。

也可以交给 GitHub Actions：`.github/workflows/release.yml` 会在推送 `v*` 标签（或手动触发）时，在 Windows runner 上自动构建并挂到 Release：

```bash
git tag -a v1.2.0 -m v1.2.0
git push origin v1.2.0
```

## 测试范围

`docs/逐组召回测试报告.md` 列出了 38 组音效各自的拾起、放下测试。每段参考音效在四种模拟背景下测试，共 304 次；安静、低频音乐和宽带杂音场景各为 76/76，高频音乐为 74/76。这是参考音效混音测试，不代表真实游戏环境的召回率。

## 数据来源

音效、物品分组及类别来自社区维护的 [ABI Builder 战地商人页面](https://abibuilder.com/merchant)，中文名称来自 [abi-assets 游戏本地化数据](https://github.com/hexaov91/abi-assets/tree/main/localization/game)。类别标签是对参考表英文类别的中文翻译。参考表版本：`1.0.0.151.4`。本项目与游戏官方及上述社区项目无关联。

## 开源协议

本项目编写的程序代码与文档采用 [MIT 协议](LICENSE)。游戏音效、物品图片和游戏数据不属于 MIT 授权范围，详见 [第三方资源说明](THIRD_PARTY_ASSETS.md)。
