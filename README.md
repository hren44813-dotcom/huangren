# huangren

一个用于存放项目代码、文档、素材和测试文件的 GitHub 仓库。

> 当前为通用项目初始化版本，尚未确定具体编程语言或技术框架。后续可以按实际项目需求调整目录结构。

## 项目目录

```text
huangren/
├── README.md         # 项目简介与使用说明
├── .gitignore        # 不上传的本地文件规则
├── src/              # 正式源代码
├── docs/             # 项目文档、需求和使用说明
├── tests/            # 测试代码与测试资料
├── assets/           # 图片、图标等项目静态资源
└── scripts/          # 辅助脚本、批处理和维护工具
```

由于 Git 不跟踪空文件夹，初始目录中的 `.gitkeep` 用于保留文件夹结构，加入正式文件后可以删除。

## 开始使用

### 1. 克隆仓库

```bash
git clone https://github.com/hren44813-dotcom/huangren.git
cd huangren
```

### 2. 开始开发

- 将项目程序放到 `src/`。
- 将需求、操作手册和说明文档放到 `docs/`。
- 将测试代码放到 `tests/`。
- 将项目图片等素材放到 `assets/`。
- 将日常自动化或维护脚本放到 `scripts/`。

### 3. 提交更改

```bash
git add .
git commit -m "Add project files"
git push origin main
```

## 当前状态

- [x] 建立通用项目目录
- [x] 编写仓库 README
- [x] 增加基础 `.gitignore`
- [ ] 确认项目用途与技术栈
- [ ] 添加正式代码与测试

## 安全提醒

不要提交账号密码、API 密钥、访问令牌、`.env` 文件或其他敏感信息；上传文件前先检查 `git status`。
