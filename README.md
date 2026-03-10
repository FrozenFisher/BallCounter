# FRC 2026 计球器

Windows 半透明浮窗计球工具，适用于 2026 FRC 比赛。

## 功能

- **球数显示**：大字号显示当前球数
- **比赛阶段**：Auto / Teleop，点击按钮切换
- **快捷键**：应用无焦点时也能响应（可自定义绑定）
  - 默认 `o`：+1 球，`p`：+5 球，`[`：-1 球，`]`：-5 球，`t`：切换 Auto/Teleop，`r`：清零，`q`：关闭程序
- **自定义快捷键**：点击「+ 添加自定义」可增加一行，每行可设置：按键、加减球数、加/减类型
- **积分显示**：Auto 分、Teleop 分、总分（根据当前阶段累加）
- **双击球数**：归零
- **可配置**：固定 4 组快捷键（o/p/[ /] 对应 +1/+5/-1/-5）、自定义快捷键行、窗口位置

## 安装

```bash
pip install -r requirements.txt
```

## 运行

```bash
python main.py
```

## 打包为 exe

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "计球器" --clean main.py
```

或直接双击 `build_exe.bat`。

打包完成后，`dist\计球器.exe` 即为可执行文件。首次运行会在 exe 同目录自动生成 `config.json`。

## 配置文件

`config.json` 存储：
- `ball_count`：当前球数
- `phase`：Auto 或 Teleop
- `shortcuts`：固定快捷键（add_small/add_large/minus_small/minus_large/quit）
- `custom_shortcuts`：自定义行 [{ "key": "a", "amount": 3, "type": "add" }, ...]
- `window`：窗口位置与透明度

## 注意事项

- 球数不会小于 0，减到 0 后继续按减键无效
- 修改快捷键后需重启程序生效
- 若全局快捷键无响应，可尝试以管理员身份运行（部分系统策略可能限制）
