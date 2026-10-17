# 暗区战地商人 · 听声识物

Windows 桌面工具，辅助识别《暗区突围：无限》战地商人神秘货物的拾起、放下音效。监听系统播放声音，按声音组列出中文物品名称、占格尺寸、联系人价格和类别；价值高于 100 万的物品价格用深红色标出，所有结果文字带黑色描边。支持窗口置顶、背景透明与鼠标穿透。

## 下载与使用

下载 `商人听金.exe`，双击运行。在播放设备下拉框中选择游戏声音实际输出的设备，点击“开始监听”，然后拖动神秘货物。可根据货物占格缩小候选范围。游戏里可以用全局热键：`Alt+4` 开始/停止监听，`Alt+5` 显示/隐藏窗口。

窗口置顶默认开启，可在主界面取消。窗口背景默认透明：整个窗口底色被抠掉，包括候选列表的背景，游戏画面完全可见；透明处的鼠标点击会穿透到游戏（拖动窗口请用标题栏；鼠标移到候选列表上滚动滚轮即可翻看，一格一行）。拖动“面板不透明度”滑块可让剩下的文字和控件一起变半透明。游戏使用独占全屏时，建议切换到无边框窗口模式。

「滚轮/点击增强」默认开启：只有在鼠标位于窗口矩形内时才临时挂上鼠标钩子（用于透明状态下的滚轮翻页和控件点击兜底），鼠标一离开就卸载；不需要可以取消勾选。

**匹配分和音效峰值强度都不是掉落概率。** 多件物品可能共用同一声音组，仅靠音频无法区分组内物品。参考表包含 38 组音效及 189 件物品；非线性节点探测器不在当前参考表中。

## 从源码运行

需要 Windows 和 Python 3.11+。

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe merchant_listener.py
```

程序使用 `catalog.json` 和 `reference/`（76 段参考音效）。程序不读取游戏内存，也不上传录音。

源码按职责拆分：`merchant_listener.py`（入口与启动异常兜底）、`app.py`（界面与录音）、`matcher.py`（匹配算法）、`winhook.py`（鼠标钩子、全局热键、错误日志）、`textimg.py`（描边文字）、`resources.py`（路径与物品目录）。出错时会在 `%TEMP%\商人听金.log` 追加一行记录。

## 打包 exe

```bash
bash tools/build_exe.sh
```

产物为 `dist/商人听金.exe`（单文件、无控制台）；脚本结束时会自动清掉 `build/` 与 `.spec` 中间文件。脚本会先运行 `tools/patch_scipy_for_pyinstaller.py`：scipy 的 `stats/_distn_infrastructure.py` 末尾用模块级 `dir()` + `exec('del ...')` 清理临时字符串，这个写法在 PyInstaller 冻结环境里会抛 `NameError: name 'obj' is not defined`，导致 exe 启动即崩。补丁把该段换成等价函数（`tools/patch_scipy_for_pyinstaller.py`，幂等）。**重装依赖后需重新运行一次该脚本，或直接跑 `tools/build_exe.sh`。**

## 测试范围

`docs/逐组召回测试报告.md` 列出了 38 组音效各自的拾起、放下测试。每段参考音效在四种模拟背景下测试，共 304 次；安静、低频音乐和宽带杂音场景各为 76/76，高频音乐为 74/76。这是参考音效混音测试，不代表真实游戏环境的召回率。

## 数据来源

音效、物品分组及类别来自社区维护的 [ABI Builder 战地商人页面](https://abibuilder.com/merchant)，中文名称来自 [abi-assets 游戏本地化数据](https://github.com/hexaov91/abi-assets/tree/main/localization/game)。类别标签是对参考表英文类别的中文翻译。参考表版本：`1.0.0.151.4`。本项目与游戏官方及上述社区项目无关联。

## 开源协议

本项目编写的程序代码与文档采用 [MIT 协议](LICENSE)。游戏音效、物品图片和游戏数据不属于 MIT 授权范围，详见 [第三方资源说明](THIRD_PARTY_ASSETS.md)。
