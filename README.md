# 🐋 暴喵大肥鱼一键管家 (Baomiao DaFeiYu Butler)

> **定位**：面向全网玩家与小白用户的 **QQ 赛博大肥鱼桌宠 · 傻瓜式一键托管部署工具**。  
> 彻底解决原版 AstrBot + NapCat 配置门槛高、命令行繁琐的痛点，集成了**小黑盒 @星野 大肥鱼赛博伴侣 V3.6 Pro 完整人设（好感度系统 + 双形态变身 + 大白饭契约）**。

---

## 🌟 核心特色与降维打击（对比竞品迅游百宝箱）

| 对比维度 | 竞品做法 (如迅游百宝箱) | 暴喵大肥鱼一键管家 |
| :--- | :--- | :--- |
| **交付形态** | 原始压缩包，强迫用户解压到 D 盘英文目录，分步点 bat | **单文件 `.exe`**，双击自启优雅现代 Web 界面，路径完全无感 |
| **算力成本** | 强迫用户去官网绑卡充值 10 元买 Key | **支持自备 DeepSeek Key**，密钥只保存在本机，不回显到管理页面 |
| **权限配置** | 需手动配置管理员和白名单 | 自动写入主人大号管理员，可一键开启"仅主人可用"白名单模式 |
| **人设灵魂** | 默认冷冰冰的基础助手 | 内置小黑盒 **@星野 V3.6 Pro 完整人设**（好感度表白、双形态变大变小🍚、大白饭投喂契约） |
| **下载校验** | 直接解压来源不明的压缩包 | NapCat 固定版本并通过官方 Release SHA-256 校验，拒绝 ZIP 路径穿越 |

---

## 📂 项目结构

```text
baomiao-dafeiyu-butler/
├── app.py                 # 主程序入口（轻量内置多线程服务端 + 自动唤起桌面 UI）
├── build_exe.py           # 一键编译单文件 .exe 打包脚本
├── requirements-build.txt # 固定 PyInstaller 构建版本
├── tests/                 # 标准库单元测试
├── build_windows.bat      # Windows 用户双击一键编译批处理
├── core/
│   ├── config.py          # 本地配置保存与读取
│   ├── generator.py       # 自动生成 AstrBot & NapCat 联动配置文件
│   ├── downloader.py      # 多镜像高速下载与自动解压引擎
│   ├── process_manager.py # 进程生命周期守护与扫码二维码实时捕获
│   └── persona.py         # 大肥鱼 V3.6 Pro 完整人设 Prompt
└── web/
    ├── index.html         # 暴喵现代紫黑风控制台界面
    ├── css/style.css      # 玻璃拟态与现代动效样式
    └── js/app.js          # 前端交互与 Server-Sent Events (SSE) 实时日志流
```

---

## 🚀 快速运行与使用

### 1. 本地直接开发/调试运行
管理器本身只使用 Python 标准库；部署 AstrBot 时需要本机已有 Python 3.12：
```bash
python app.py
```
启动后会自动在系统浏览器中弹出控制台界面（默认 `http://127.0.0.1:18999`）。

---

### 2. 编译为 Windows 单文件 `暴喵大肥鱼一键管家.exe`
在 Windows 环境下，只需运行：
```bash
python build_exe.py
# 或直接双击运行 build_windows.bat
```
编译完成后会在 `dist/` 目录生成独立的 **`暴喵大肥鱼一键管家.exe`**，可直接分享给用户使用。

---

## 📱 小白用户使用三步走

1. **输入主人大号 QQ**：将该 QQ 写入 AstrBot 管理员列表；
2. **输入机器人小号 QQ**：准备用来当大肥鱼躯体的备用 QQ 号，并填写 DeepSeek API Key；
3. **点击【一键部署并启动】**：
   * 下载并校验 NapCat 4.18.41；
   * 使用 Python 3.12 创建隔离环境并安装 AstrBot 4.29.3；
   * 自动生成并写入双端配置文件；
   * 界面直接弹出二维码，拿手机小号 QQ 扫码即可瞬间激活！


---

## 🔐 运行环境与安全说明

- 管理器 HTTP 服务只监听 `127.0.0.1`，并校验 `Host` / `Origin`，不开放局域网访问。
- ⚠️ **账号风险**：NapCat 属于第三方 QQ 客户端，登录后存在被腾讯风控、限制或封禁账号的可能。请务必使用闲置小号、勿用常用主号，由此产生的账号风险由使用者自行承担。
- DeepSeek API Key 保存在本机 `~/.baomiao_dafeiyu/config.json`，接口读取时会自动隐藏。
- NapCat 使用固定版本和 SHA-256 校验；解压前会拒绝绝对路径、`..` 穿越和符号链接。
- AstrBot 管理面板只监听 `127.0.0.1`。首次管理密码保存在 `~/.baomiao_dafeiyu/astrbot_dashboard_password.txt`。
- AstrBot 4.29.3 需要 Python 3.12。若本机没有 Python 3.12，部署会明确失败，不会启动未完成的服务。
- 当前版本未实现“暴喵免配通道”，界面会明确提示选择 DeepSeek，避免生成不可用配置。

## ✅ 开发验证

```bash
python -m unittest discover -s tests -v
```

测试覆盖下载包路径穿越防护、AstrBot/NapCat 配置生成、接口参数校验。
