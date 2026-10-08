# xiaoyaoxian 的知识库

一个知识库风格的个人博客，使用 [Hugo](https://gohugo.io/)（extended 版）构建。
没有第三方主题、没有前端依赖，构建产物是纯静态文件，可部署到任意 Web 服务器或 GitHub Pages。

- **线上地址**：<http://103.236.97.137:27834/>
- **风格参考**：[yuy0ung.github.io](https://yuy0ung.github.io)，主题代码为自行实现
- **构建环境**：Hugo v0.167.0 extended

## 特性

- 📚 **文档树导航**：左侧按栏目折叠展示全部文章，自动展开当前文章所在目录
- 🔍 **全文搜索**：`Ctrl / Cmd + K` 唤起，支持方向键选择、回车跳转
- 🧭 **大纲定位**：右侧自动生成 TOC，滚动时高亮当前章节
- 🌗 **明暗主题**：跟随系统偏好，可手动切换并记住选择
- 💻 **代码块美化**：macOS 风格窗口 + 一键复制，明暗两套语法配色
- 👀 **悬停预览**：首页鼠标悬停文章标题即可预览摘要
- ⬇️ **导出 Markdown**：文章右上角一键下载该篇的 `.md` 源文件
- 🗂️ **可折叠目录树**：点左栏边框上的圆钮收起/展开，正文自动加宽，状态会被记住
- 🔎 **图片放大**：点击正文图片全屏查看；多图时可用左右箭头 / 键盘 `←` `→` / 手机滑动切换，Esc 关闭
- 📱 **响应式**：移动端顶栏有「目录」按钮，左栏从左侧滑出为抽屉（点遮罩 / `Esc` / 点文章链接自动收起），搜索变为全屏

## 日常使用（TL;DR）

```bash
hugo new content/blog/Java基础/新文章.md   # 1. 新建文章（自动套模板）
hugo server -D                             # 2. 本地预览 → http://localhost:1313
./deploy/deploy.sh                         # 3. 发布上线
```

只改样式或配置时，第 1 步可跳过，直接跑第 3 步。
线上地址与服务器信息见「部署到自己的服务器」一节。

## 快速开始

### 1. 安装 Hugo

需要 **extended** 版本（v0.128 及以上）：

```bash
# macOS
brew install hugo

# Windows
winget install Hugo.Hugo.Extended

# Linux（以 deb 为例）
sudo dpkg -i hugo_extended_0.167.0_linux-amd64.deb
```

### 2. 本地预览

```bash
hugo server -D
```

打开 http://localhost:1313 即可。

### 3. 新建文章

```bash
hugo new content/blog/Java基础/我的新文章.md
```

## 写文章

### 三种创建方式

| 想创建 | 做法 | 关键点 |
| --- | --- | --- |
| **栏目 / 子模块** | 文件夹 + `_index.md` | 少了 `_index.md` 就不算栏目，里面的文章会被平铺到上一级 |
| **普通文章** | 单个 `.md` 文件 | 没有配图时最简单 |
| **带图片的文章** | 文件夹 + `index.md` + 图片 | 图片和 `index.md` 放同一个文件夹 |

> 记住一句话：**`_index.md` 是栏目，`index.md` 是文章**，只差一个下划线。

#### 1. 创建栏目（子模块）

```bash
hugo new content/blog/运维/kafka/_index.md
```

建好后打开改一下 `weight`（越小越靠前，默认 10）。

#### 2. 创建普通文章

```bash
hugo new content/blog/运维/kafka/初始kafka.md
```

#### 3. 创建带图片的文章

```bash
mkdir -p "content/blog/运维/kafka/Kafka安装与配置"
cp ~/图片/架构图.png "content/blog/运维/kafka/Kafka安装与配置/"
```

再新建 `content/blog/运维/kafka/Kafka安装与配置/index.md`，正文里用**相对路径**引用图片：

```markdown
![Kafka 架构图](架构图.png)
```

### 目录结构就是文档树

左侧的文档树完全由 `content/blog/` 下的目录结构决定：

```text
content/blog/
├── _index.md                       ← 根栏目「全部文章」
├── Java基础/                        ← 栏目
│   ├── _index.md                   ← 栏目标题 / 排序（必须有）
│   ├── 集合框架/                    ← 子模块（可以无限嵌套）
│   │   ├── _index.md
│   │   └── ArrayList-源码剖析.md    ← 普通文章
│   └── JVM/
│       ├── _index.md
│       └── 内存模型/                ← 三级也没问题
│           ├── _index.md
│           └── 堆与栈.md
├── 运维/
│   ├── _index.md
│   └── kafka/
│       ├── _index.md
│       ├── 初始kafka.md            ← 普通文章
│       └── Kafka安装与配置/         ← 带图片的文章（page bundle）
│           ├── index.md            ← 必须是 index.md，不是 _index.md
│           ├── 架构图.png
│           └── img/
│               └── 细节图.png       ← 图片也可以放子文件夹
└── 随笔/
    ├── _index.md
    └── hello-world.md
```

规律很简单：

- **文件夹 + `_index.md`** = 栏目，在左栏显示为可折叠的分组
- **单个 `.md` 文件** = 普通文章，点击后打开
- **文件夹 + `index.md`** = 带图片的文章，图片跟着文章一起管理
- 栏目可以任意嵌套，子栏目会自动出现在父栏目下面
- ⚠️ 栏目（`_index.md`）写了 `draft = true` 的话，**整个栏目会从站点消失**；
  只给文章加 draft 则栏目还在，只是里面是空的

### Front matter 字段

每个文件开头 `+++` 之间是元信息：

| 字段        | 必填  | 作用                         |
| --------- | --- | -------------------------- |
| `title`   | 是   | 文章标题（页面大标题、左栏、搜索结果都用它）     |
| `date`    | 是   | 日期，显示在首页树和文章页              |
| `weight`  | 否   | 排序，数字越小越靠前；不写则按日期倒序        |
| `tags`    | 否   | 标签，显示在文章标题下方               |
| `summary` | 否   | 摘要，用于搜索结果和首页悬停预览；不写则自动截取正文 |
| `draft`   | 否   | 写 `true` 表示草稿，正式构建时会被跳过    |

### 正文写法

- 用 `##` / `###` 写标题，会自动出现在右侧「大纲」并支持滚动高亮
- **不要**用 `#` 写一级标题（页面标题已由 `title` 生成）
- 代码块用三反引号加语言名，会自动高亮并带复制按钮
- 支持表格、引用块、有序/无序列表、分隔线、行内代码等标准 Markdown
- 站内链接用根路径：`[另一篇](/blog/开发工具/git-常用命令速查/)`

### 代码块支持哪些语言

高亮由 Hugo 内置的 **Chroma** 完成，支持 200 多种语言。写法是三反引号后直接跟语言名：

````markdown
```python
print("hello")
```
````

常用的语言名（下面这些都已实测可用）：

| 类别      | 语言名                                                                                                                                      |
| ------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| 脚本 / 后端 | `python` `javascript` `typescript` `go` `rust` `java` `c` `cpp` `csharp` `php` `ruby` `perl` `lua` `kotlin` `swift` `scala` `r` `matlab` |
| Shell   | `bash` `shell` `zsh` `powershell`                                                                                                        |
| 数据 / 配置 | `json` `yaml` `toml` `xml` `ini` `sql` `graphql` `protobuf`                                                                              |
| 前端      | `html` `css` `scss` `markdown`                                                                                                           |
| 运维 / 其他 | `dockerfile` `nginx` `makefile` `diff` `http` `vim`                                                                                      |

- 语言名**大小写不敏感**，`Python` 与 `python` 效果一致
- 写了不认识的名称不会报错，只会**退化成纯文本**
- 想要纯文本但保留代码块样式，写 `text` 或 `plaintext`
- 完整列表见 [Chroma 支持的词法器](https://github.com/alecthomas/chroma#supported-languages)

### 图片怎么放

带图片的文章要用 **page bundle** 写法：文件夹名就是文章名，里面放一个 `index.md`，
图片和它放在一起（也可以再放子文件夹）。

```text
content/blog/运维/kafka/Kafka安装与配置/
├── index.md        ← 必须是 index.md（不是 _index.md）
├── 架构图.png
└── img/
    └── 细节图.png
```

然后在 `index.md` 里用**相对路径**引用：

```markdown
![Kafka 架构图](架构图.png)
![细节](img/细节图.png)     ← 子文件夹也能用
```

好处是图片和文章一起管理，删除文章时图片不会残留。
少量全局图片（头像、logo）放到 `static/`，用 `/图片名` 引用。

> ⚠️ **普通单文件文章（如 `理解HashMap.md`）不能用 `assets/xxx.png` 这类相对路径。**
> 单文件文章的网址会比文件多一层目录（`.../理解hashmap/`），相对路径会指向不存在的地址，
> 图片就裂了。**只要文章里有图片，就必须改成 page bundle（文件夹 + `index.md`）**，
> 图片和 `index.md` 放在同一个文件夹里。

> 图片文件名建议用英文或数字；中文虽然能用，但链接里会变成百分号编码。

正文里的图片都可以**点击放大**：点击后全屏查看，按 `Esc`、点背景或点右上角 × 关闭，
键盘用户也可以 `Tab` 聚焦到图片后按回车打开。

一篇文章有**多张图片**时，放大后还能切换：

- 左右两侧的箭头按钮（循环切换，到头会绕回）
- 键盘 `←` / `→`
- 手机左右滑动
- 顶部会显示「第几张 / 共几张」，只有一张图时自动隐藏切换控件

### 图片压缩（省流量）

文章多起来以后图片会明显拖慢页面，仓库里带了两个脚本。它们需要 ImageMagick
（`magick` 命令），Debian/Ubuntu 下 `sudo apt install imagemagick` 即可。

**1. 把 PNG/JPG 批量转成 WebP**

```bash
python3 scripts/optimize-images.py                    # 转完保留原图，便于回滚
python3 scripts/optimize-images.py --delete-originals # 确认没问题后清掉原图
```

转换会自动改写同目录 `index.md` 里的引用（`xxx.png` → `xxx.webp`），
所以**不用手改 Markdown**。实测压缩率约 40%~60%。

**2. 缩小过宽的图片**

```bash
python3 scripts/shrink-oversized.py --max-width 2500
```

只处理宽度超过 `--max-width` 的图，等比缩小并原图替换。阅读区宽度有限，
2500 对截图类图片已经完全够用。默认跳过未超宽的图，不会反复重新编码。

> 两个脚本都会**原地修改** `content/` 下的文件，建议先在 git 里提交一次，
> 或者先 `--dry-run` 看看会动哪些文件。

### 导出 Markdown

每篇文章右上角都有一个「导出 MD」按钮，点击即可下载该篇的**原始源文件**
（含 front matter，和 `content/` 里的内容逐字节一致），文件名就是文章标题。

实现方式是 Hugo 的自定义输出格式（见 `hugo.toml` 的 `outputFormats.Markdown`
和 `layouts/_default/single.md`）：构建时会在每篇文章目录下额外生成一个
`index.md`，按钮通过 `download` 属性触发下载。

草稿（`draft = true`）不会生成导出文件。

> 部署提示：`deploy/deploy.sh` 已经带了 `--cleanDestinationDir`，
> 避免本地用 `hugo server -D` 预览时产生的草稿文件被一起同步到服务器。

### 草稿与预览

```bash
hugo server -D     # 预览（-D 表示包含草稿）
hugo server        # 预览（不显示 draft = true 的文章）
```

新建的文章默认**不是**草稿，写完直接就能看到。
如果想先存着不发布，在 front matter 里加一行 `draft = true`，
这样执行正式构建（`hugo` / `./deploy/deploy.sh`）时它不会被发布。

## 个性化配置

站点信息集中在 `hugo.toml`。当前配置如下（改成你自己的即可）：

| 配置项                        | 当前值                            | 说明                           |
| -------------------------- | ------------------------------ | ---------------------------- |
| `title`                    | `xiaoyaoxian的知识库`              | 站点标题（顶栏 + 首页）                |
| `baseURL`                  | `http://103.236.97.137:27834/` | 线上地址，**必须和实际访问地址一致**         |
| `params.author`            | `xiaoyaoxian`                  | 作者名                          |
| `params.avatar`            | `/photo.jpg`                   | 顶栏头像，图片放 `static/` 后填 `/文件名` |
| `params.favicon`           | `/photo.jpg`                   | 浏览器标签页图标                     |
| `params.description`       | `记录技术、思考与生活`                   | 首页副标题                        |
| `params.aboutURL`          | `/about/`                      | 右上角「关于我」跳转地址                 |
| `params.github`            | `https://github.com/daiyinbao` | GitHub 链接                    |
| `params.footer`            | `Created by xiaoyaoxian · …`   | 页脚文案                         |
| `params.searchPlaceholder` | `搜索文章...`                      | 搜索框占位文字                      |
| `params.sidebarTitle`      | `文档`                           | 左栏标题                         |

配色集中在 `assets/css/main.css` 顶部的 CSS 变量（`:root` 与
`[data-theme="dark"]`），改 `--link-color` 等即可整体换色。

代码块的语法高亮由 `assets/css/syntax.css` 控制（亮色 github / 暗色 monokai），
这个文件是 `python3 scripts/gen-syntax.py` 生成的，不要手改。想换配色就改脚本里的
`github` / `monokai` 再重新生成。

`content/about.md` 是「关于我」页面的内容
（**目前还是 `Your Name` 占位文案，记得改成你自己的**）。

### 换头像

头像显示在顶栏左上角（32×32 圆形）。

1. 把图片放进 `static/`，例如 `static/avatar.jpg`

2. 改 `hugo.toml`：
   
   ```toml
   avatar = "/avatar.jpg"
   ```

支持 `jpg` / `png` / `svg` / `webp`。建议用**正方形**图片，边长 128px 以上
（太小会糊，非正方形会被裁成圆形）。

### 换浏览器标签页图标（favicon）

1. 把图标放进 `static/`，例如 `static/favicon.png`

2. 改 `hugo.toml`：
   
   ```toml
   favicon = "/favicon.png"
   ```

支持 `svg` / `png` / `ico` / `jpg` / `webp` / `gif`，会自动识别类型。
用非 SVG 格式时还会额外输出一个 `apple-touch-icon`，方便添加到 iOS 主屏。

> **改完没变化？** 浏览器对 favicon 的缓存非常顽固，请强制刷新
> （`Ctrl/Cmd + Shift + R`）；还不行就换个文件名（如 `favicon-v2.png`）来绕开缓存。

> **当前状态**：头像和 favicon 都已指向 `static/photo.jpg`（你自己的图片）。
> 早期的占位图 `static/avatar.svg`、`static/favicon.svg` 还留在目录里，用不到可以删掉。

## 部署到 GitHub Pages（可选）

本项目当前部署在自建服务器上（见下一节）；如果你也想同时挂一份到 GitHub Pages，
按下面步骤操作即可（两者可以并存）。

1. 新建一个 GitHub 仓库，把本项目推送到 `main` 分支：
   
   ```bash
   git init
   git add .
   git commit -m "init blog"
   git branch -M main
   git remote add origin git@github.com:<用户名>/<仓库名>.git
   git push -u origin main
   ```

2. 仓库 **Settings → Pages → Build and deployment → Source** 选择 **GitHub Actions**。

3. 修改 `hugo.toml` 里的 `baseURL` 为你的地址：
   
   - 用户/组织页仓库（仓库名必须是 `<用户名>.github.io`）：`https://<用户名>.github.io/`
   - 普通项目仓库：`https://<用户名>.github.io/<仓库名>/`

4. 推送后 `.github/workflows/hugo.yml` 会自动构建并部署，几分钟后即可访问。

## 部署到自己的服务器（不用 Docker）

Hugo 生成的是纯静态文件，服务器上只需要一个 Web 服务器（Nginx / Caddy / Apache 都行），
**不需要 Node、PHP、数据库**。

> **这台服务器已经部署好了（2026-10-06），日常只需一条命令更新**
> 
> | 项目     | 值                                           |
> | ------ | ------------------------------------------- |
> | 访问地址   | <http://103.236.97.137:27834/>              |
> | 服务器系统  | Debian 13，Nginx 1.26                        |
> | 站点目录   | `/var/www/blog`                             |
> | SSH 登录 | `ssh -p 34365 root@103.236.97.137`（已配置公钥免密） |
> | 更新文章   | 本地写完 → 项目目录执行 `./deploy/deploy.sh`          |
> 
> **注意两点：**
> 
> 1. 外网端口是 NAT 转发：`103.236.97.137:27834` → 服务器内网 `80`。
> 2. 服务器在中国大陆，未备案的 80/443 会被运营商拦截（返回"该网站暂时无法访问"备案提示页），
>    所以走非标准端口 `27834` 绕开拦截。`baseURL` 必须写成 `http://103.236.97.137:27834/`。

### 方案一：本地构建 + rsync 上传（推荐）

服务器上不用装 Hugo，本地构建好直接传 `public/` 即可。

1. 本地确认能构建：
   
   ```bash
   hugo --gc --minify --baseURL https://blog.example.com/
   ```

2. 准备发布配置：
   
   ```bash
   cp deploy/deploy.env.example deploy/deploy.env
   # 编辑 deploy/deploy.env，填服务器地址、目标目录、域名
   ```
   
   > 本项目**已经配好了** `deploy/deploy.env`（服务器地址、SSH 端口、`/var/www/blog`、
   > `baseURL`），日常直接跳到第 3 步即可。

3. 一键发布：
   
   ```bash
   ./deploy/deploy.sh
   ```
   
   脚本做的事：本地构建 → `rsync --delete` 同步到服务器目录。
   之后每次写完文章，重跑一次这个脚本就更新了。

4. 服务器目录权限（首次）：
   
   ```bash
   sudo mkdir -p /var/www/blog
   sudo chown -R "$USER":"$USER" /var/www/blog
   ```

### 方案二：源码放服务器，在服务器上构建

```bash
# 1. 服务器安装 Hugo（extended）
wget https://github.com/gohugoio/hugo/releases/download/v0.167.0/hugo_extended_0.167.0_linux-amd64.tar.gz
tar xzf hugo_extended_0.167.0_linux-amd64.tar.gz
sudo mv hugo /usr/local/bin/

# 2. 把项目传上去（本地执行）
rsync -avz --exclude public --exclude resources ./ user@server:/opt/my_blog/

# 3. 在服务器上构建
cd /opt/my_blog
hugo --gc --minify --baseURL https://blog.example.com/ -d /var/www/blog
```

### 配置 Nginx

```bash
sudo cp deploy/nginx.conf /etc/nginx/conf.d/blog.conf
sudo vim /etc/nginx/conf.d/blog.conf   # 改 server_name 和 root
sudo nginx -t && sudo systemctl reload nginx
```

`deploy/nginx.conf` 已经处理好了干净 URL（`/blog/xxx/` → `/blog/xxx/index.html`）、
静态资源缓存、gzip 和自定义 404 页。

### 配置 HTTPS

```bash
# 用 Let's Encrypt 免费证书（需要域名已解析到服务器）
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d blog.example.com
```

或者把 Nginx 换成 [Caddy](https://caddyserver.com/)，两行配置自动签发证书：

```caddyfile
blog.example.com {
    root * /var/www/blog
    file_server
    encode gzip
}
```

### 常见坑

- **`baseURL` 必须和实际访问地址一致**，否则 CSS/JS 会 404。
  用子目录部署（如 `https://example.com/blog/`）时，`baseURL` 结尾要有斜杠。
  带端口的地址也要写上端口，例如本项目就是 `http://103.236.97.137:27834/`。
- **图片打不开 / 返回 403**：`static/` 里的文件权限不能是 `600`。
  `rsync -a` 会原样保留权限，nginx（以 `www-data` 运行）读不了就会 403。
  本地先 `chmod 644 static/图片名`，或到服务器上执行
  `find /var/www/blog -type f -exec chmod 644 {} +`。
- **文章目录是中文**，链接里是百分号编码，Nginx 会自动解码，只要服务器文件系统是 UTF-8 就没问题。
- **更新后没变化**：确认浏览器缓存；CSS/JS 带内容指纹会自动更新，但 `index.html` 可能被缓存，
  刷新时用 `Ctrl/Cmd + Shift + R`。
- **国内服务器的 80/443 会被拦截**：未备案时运营商会返回「该网站暂时无法访问」的备案提示页
  （本机 `curl 127.0.0.1` 却是 200）。两个办法：① 完成 ICP 备案后用 80/443；
  ② 像本项目一样用 NAT 映射到非标准端口绕开。

## 其他托管方式

除 GitHub Pages 和自建服务器外，也都可以直接部署：

- **Cloudflare Pages**：构建命令 `hugo --gc --minify`，输出目录 `public`
- **Vercel / Netlify**：同上，环境变量设 `HUGO_VERSION=0.167.0`
- **对象存储 + CDN**：把 `public/` 上传到 OSS / S3，开启静态网站托管

## 目录结构

```text
.
├── hugo.toml                 # 站点配置（标题、头像、baseURL 等）
├── README.md                 # 本文档
├── content/
│   ├── _index.md             # 首页
│   ├── about.md              # 「关于我」页面
│   └── blog/                 # 所有文章（目录结构 = 文档树）
│       └── <栏目>/<文章>.md
├── layouts/
│   ├── index.html            # 首页模板
│   ├── index.json            # 搜索索引（全文搜索用）
│   ├── 404.html              # 404 页面
│   ├── _default/
│   │   ├── baseof.html       # 页面骨架（侧栏折叠按钮、抽屉遮罩）
│   │   ├── single.html       # 文章页（含导出 MD 按钮）
│   │   ├── single.md         # 导出 MD 的输出模板
│   │   └── list.html         # 栏目页
│   └── partials/             # header、文档树、搜索弹窗、head、scripts
├── assets/
│   ├── css/main.css          # 样式（设计变量 + 响应式规则）
│   ├── css/syntax.css        # 代码高亮配色
│   └── js/main.js            # 交互脚本（原生 JS，无依赖）
├── static/                   # 头像、favicon 等原样拷贝的资源
├── archetypes/default.md     # `hugo new` 用的文章模板
├── deploy/
│   ├── nginx.conf            # Nginx 站点配置
│   ├── deploy.sh             # 构建 + rsync 发布脚本
│   ├── deploy.env.example    # 发布配置模板
│   └── deploy.env            # 本地实际配置（已 gitignore）
└── .github/workflows/hugo.yml # GitHub Pages 自动部署（可选）
```

## 当前内容

站点现有 10 个栏目（左栏顺序）：

`Java 基础`、`后端框架`、`算法`、`Agent 开发`、`运维`、`Linux`、`开发工具`、`日常使用`、`面试`、`随笔`

已有的文章：

| 路径 | 说明 |
| --- | --- |
| `content/blog/开发工具/git-常用命令速查.md` | Git 常用命令速查表 |
| `content/blog/开发工具/hugo-搭建个人博客.md` | 本站的搭建记录 |
| `content/blog/运维/kafka/初始kafka.md` | Kafka 笔记（目前还是模板正文，待补充） |
| `content/blog/随笔/hello-world.md` | 开博第一篇 |

还可以清理的：

| 路径 | 说明 |
| --- | --- |
| `static/avatar.svg`、`static/favicon.svg` | 早期占位图；现在头像 / 图标用的是 `static/photo.jpg` |

## 许可

主题代码可自由使用与修改；请替换为自己的头像与文章内容。
