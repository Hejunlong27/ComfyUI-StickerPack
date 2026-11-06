# ComfyUI-StickerPack

把 `pixel-gif-sticker-pack` 技能的出图原理搬进 ComfyUI：**绿幕精灵图 → 抠图 → 切分 → 脚底对齐 → 合成字幕 → 透明 GIF → 打包 ZIP**。

生成用你本地的 **Qwen-Image 2.1 turbo**，不下载任何新模型。

> **EN** — Turn one paragraph of sticker brief into a finished pack: N green-screen sprite
> sheets → chroma key → grid split → ground alignment → caption compositing → transparent
> looping GIFs → a single ZIP. Runs fully offline on a local Qwen-Image 2.1 turbo checkpoint.
> No model is downloaded by this node pack.

**前置要求**：ComfyUI 0.4x ｜ `Qwen-Image 2.1 turbo`（unet + clip + vae + 4-step LoRA）｜ Pillow ｜ FFmpeg（可选，只用于 mp4 预览）。

---

## 一键出整包：粘一段文案就行

打开 ComfyUI → 左侧 **Workflows** → **① 贴纸表情包·一键9张出ZIP**。

1. 左侧 `ref` 节点上传角色参考图（一张正面全身或半身即可）
2. 把**整段提示词**粘进 ④ SAMPLING 区节点的「提示词」框
3. 点 **Run**，约 8 分钟

**只有一个输入框。** 开头几行写角色外形，空一行后写编号条目，插件会把角色描述自动带进每一条生成提示词。

```
【角色】3D 渲染 Q 版少年，蓬松黑色碎发，白 T 恤，黑阔腿裤配浅灰翻边，黑白帆布鞋

01｜收到！
少年站直身体，右手敬礼，随后点头两下，露出自信的笑。
配字：「收到！保证完成！」
02｜谢谢老板
少年双手捧着咖啡，眼睛笑成月牙，连续鞠躬两次。
配字：「老板大气！」
```

### 不想自己写？用角色提示词让 AI 写

`表情包设计角色提示词.md` 是一段**成品系统提示词**，整段粘给任意大模型（GPT / Claude / 通义 / 豆包都行），
然后描述你的需求，它会**固定输出两个块**：

它输出**一个整块**，原样粘进「提示词」框即可：

```
画面中的角色必须与参考图完全一致：3D 渲染风格的动漫 Q 版少年……干净的棚拍布光。

01｜收到！
少年突然站直身体……点头两下，露出自信的笑容。
配字：「收到！保证完成！」
```

提示词里已经锁死了编号格式、动作写法、字幕长度、emoji 禁令和自检清单，
所以产出的文案能被解析节点直接吃下。省掉「格式不对 → 反复返工」这一环。

画布上也放了三个说明节点：左上「用法」、中间「AI 写文案指引」、script 左边「文案格式规范」。

### 文案格式（自己写时看这个）

完整规则见 `文案规范.md`，核心是三条：

```
01｜收到！
少年突然站直身体，眼神变得认真，右手抬起做出敬礼动作，随后快速点头两下，露出自信的笑容。
配字：「收到！保证完成！」
```

- 每条的**编号行**（`01｜标题`）决定条数和顺序，支持 `01｜` `01|` `01、` `01.` `01：`
- **中间那行**是动作描述，整段传给模型，由模型自己拆成 4 个关键姿势
- **`配字：「…」`** 那行是图上字幕，`「」` 会自动去掉
- 没有 `配字` 行时用标题当字幕
- 没有编号时按空行分块，再不行按行分
- 顶部的 `二、9款表情包具体设计` 这类章节标题会自动跳过
- 支持 3–9 条，不足 9 条会重复最后一条；超过 9 条只用前 9 条

### 产物

```
ComfyUI/output/表情包/
├── 表情包.zip                 # ← 交付物：9 张 GIF + 预览.html + 总览图
├── 001-收到！保证完成！.gif     # 9 张透明 GIF，512×512，6 帧，无限循环
├── ...
├── 009-晚安，好梦～.gif
├── _contact_sheet.png        # 九宫格总览
└── 预览.html                  # 离线浏览页
```

**ZIP 就在生成它的那个文件夹里**，和 GIF 并排。跑完 ⑥ OUTPUT 区的节点会直接显示完整路径。

> 早期版本这里有个坑：`StickerSaveZip` 的 `folder` 留空时会把 zip **复制到 `output` 根目录**，
> 于是 `output/表情包/` 里只剩一堆 GIF，看起来像"没生成 zip"。现在留空 = 原地不动，
> 填了才额外复制一份。

`save_mp4` 默认关 —— mp4 不进 zip，开着只会让输出文件夹多一倍文件。要 mp4 预览自己打开。

图里有两个 **PreviewImage**：一个显示全部 54 帧（9 张 × 6 帧），一个显示九宫格总览。
画布左上角有一个 Note 节点写着同样的步骤。

---

## 安装

把整个 `comfyui-sticker-pack` 目录拷进 `custom_nodes`，文件夹名改成 `ComfyUI-StickerPack`：

```
<ComfyUI 根目录>/custom_nodes/ComfyUI-StickerPack
```

重启 ComfyUI。节点在右键菜单 **sticker pack** 分类下，共 6 个。

依赖只有 `Pillow` + `numpy`，ComfyUI 自带。

---

### 画布分区

工作流按数据流从左到右分成六区，每区一个色框：

| 区 | 颜色 | 内容 |
|---|---|---|
| **① INPUT** | 蓝 | 角色参考图（`ref.png`）+ 说明「文案在哪」 |
| **② MODELS** | 绿 | `UNETLoader` / `CLIPLoader` / `VAELoader`，全部指向本地 Qwen-Image 2.1 |
| **③ LORAS** | 棕 | `LoraLoaderModelOnly`，默认挂 turbo LoRA 但**强度 0**（不生效）。想加风格 LoRA 就把强度调上去 |
| **④ SAMPLING** | 赭 | `StickerAutoPack`：文案、角色描述、宽高、sigmas、cfg、seed、字幕样式、帧序、打包名全在这一个节点上 |
| **⑤ PREVIEWS** | 靛 | 两个 `PreviewImage`：全部 54 帧 + 九宫格总览 |
| **⑥ OUTPUT** | 深绿 | `StickerSaveZip` 接 `zip_path`，把整包复制到 `output/` 并校验完整性，路径回显在运行结果里；下面一个 Note 写产物目录结构 |

模型链路是 `UNETLoader → LoraLoaderModelOnly → StickerAutoPack.model`，LoRA 强度为 0 时等价于直连。

## 工作流清单

打开 ComfyUI → 左侧 **Workflows** → 选带 ①②③④ 前缀的。

| 工作流 | 节点数 | 用途 |
|---|---|---|
| **① 贴纸表情包·一键整包** | **8** | 一个节点干完全部：解析文案 → 生成 9 张 → 合成 GIF → 打包 ZIP |
| ② 贴纸表情包·一键9张出ZIP | 57 | 九条生成分支铺在画布上，可逐条调；**这是实测跑通过一次的版本** |
| ③ 贴纸表情包·已有图集打包 | 20 | 手上已有绿幕图集，只跑打包段 |
| ④ 贴纸表情包·手动调参链 | 7 | 单张贴纸的逐节点后处理，调参数用 |

① 和 ② 产出的东西完全一样，区别只在图的形态：

| | ① 一键整包 | ② 57 节点 |
|---|---|---|
| 画布 | 8 个节点 | 57 个节点，连线密 |
| 中间张量 | 一次只有一个，每轮结束就释放 | 全部同时存活 |
| 峰值内存 | 低 | 高（16 GB 机器容易炸） |
| 单条调参 | 改 script 里的那一条 | 直接改那条分支的提示词 |
| 断点续跑 | 不支持，中途停就全丢 | 可以只跑某几条 |

**内存吃紧就用 ①。** 需要逐条精调就用 ②。

工作流目录里还有一个 `api格式-不能从侧边栏打开/` 子文件夹，里面是 API 格式版本，**只能**用命令行跑：

```bash
python run_pack.py --workflow workflows/sticker_pack_9qwen_api.json \
  --server http://127.0.0.1:8188 --ref path/to/角色参考图.jpg
```

### 为什么 API 格式打不开

- ComfyUI 侧边栏「Workflows」只认**画布图格式**：顶层必须是 `{"nodes": [...], "links": [...]}`。
- API 格式是 `{"1": {"class_type": ..., "inputs": ...}}`，那是提交给 `/prompt` 的**执行图**，没有 `nodes` 字段，解析直接失败。
- 前端里确实有 `loadApiJson` / `isApiJson`，但只挂在**资源面板（Assets）的「以工作流打开」**上，侧边栏的打开路径不走它。
- 所以交付物必须是画布图格式。本仓库的两个 UI 工作流都经过实测：在浏览器里 `app.loadGraphData()` 加载成功，再用 `app.graphToPrompt()` 转回执行图，与已验证跑通的 API 版本**逐节点完全一致**。

---

## 节点说明

| 节点 | 作用 | 关键参数 |
|---|---|---|
| **Sticker · 脚本文案解析** | 一段提示词 → 9 条提示词 + 9 条字幕 | `提示词` 一个框搞定 |
| **Sticker · 整包出图+ZIP** | N 张图集进，N 张 GIF + 总览图 + ZIP 出 | `captions` 一行一个字幕、`cols/rows`、`frame_order`、`durations`、`pack_name` |
| **Sticker · 绿幕抠图** | `#00FF00` 键控 + despill + 羽化，顺带抹水印 | `min_green`、`dominance`、`erode`、`blank_wm_w/h` |
| **Sticker · 切分图集** | 按网格切格 | `cols/rows`、`row_index` |
| **Sticker · 脚底对齐** | alpha 底部 6% 的 x 质心当脚底锚点，全格拉齐 | `pad`、`band_ratio`、`lifts` |
| **Sticker · 合成字幕帧** | 统一缩放贴 512，底部描白边字幕，按帧序排 | `text`、`font_path`、`ink`、`frame_order` |
| **Sticker · 保存 GIF** | 全帧共享 255 色调色板、二值 alpha、disposal=2 | `durations`、`loop` |

`StickerPackBatch` 内部依次跑前五个节点，所以整包只需要一个节点。

### 一键整包的 16 个参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `brief` | 空 | 唯一必填。开头写角色外形，空一行后写编号条目 |
| `cells` | 4 | 一条动作拆几个关键姿势。3 快 25% |
| `width` / `height` | 1536 / 1024 | 精灵图尺寸。1280 宽省 17% 时间 |
| `ref_resolution` | 1024 | 参考图缩放边长，越大细节越准越慢 |
| `sampler_name` | euler | turbo 模型配 euler |
| `sigmas` | turbo 序列 | 换模型才需要改 |
| `cfg` | 1.0 | turbo 必须 1.0 |
| `seed` | 1000 | 第 i 条用「种子 + i」 |
| `font_path` | 微软雅黑 Bold | 必须覆盖中文字形 |
| `canvas` | 512 | 微信/QQ 表情够用 |
| `frame_order` | 0,1,2,3,2,1 | 正放再倒放，首尾衔接成循环 |
| `durations` | 320,180,180,600,180,180 | 毫秒，与帧序一一对应 |
| `pack_name` | 表情包 | 输出文件夹名 = zip 名 |
| `save_mp4` | 关 | 额外生成 mp4。不进 zip，开着只是多一倍文件 |
| `steps` | 6 | 实际采样步数。8 = 原始质量，6 = 推荐，4 = 极速 |

完整逐条说明见 **`节点参数说明.md`**（由 `gen_docs.py` 从节点定义自动生成）。
画布上把鼠标悬停到任一参数也会显示同样的说明。



### 为什么必须有「脚底对齐」

图像生成模型给 4 个连续姿势时，每个姿势在格内的 x 位置会差几十像素（实测 ±36px）。
合成时若对全部帧取统一包围盒 + 单一缩放，这些偏移会变成**角色在画面里横向滑步**。

跳跃/离地的姿势脚底本来不在地面，用 `lifts` 补偿，例如 `3:-45`。

### 帧序与时长

逗号分隔整数，长度不必相等（不足自动补最后一帧）。

```
frame_order = 0,1,2,3,2,1
durations   = 320,180,180,600,180,180     # 共 1640ms，正放 + 倒放
```

---

## 出图提示词要点

1. **角色外形完整重写一遍** —— 参考图不能替代文字描述，模型换姿势时会改脸。
2. **对齐锁**：「4 格中头部中心、头部大小、身体比例、机位、镜头、光线与躯干基线必须完全一致，双脚踩在同一条地平线上。不要缩放、平移或改变角色大小。」
3. **背景锁**：「纯色绿幕 #00FF00，完全均匀，没有渐变、地面、阴影、反射、边框、网格线、文字、水印。」
4. **单格描述**：每格只改一只手 + 表情。

**不要用「透明背景」** —— 模型会把透明画成白/浅灰棋盘格，抠图时会把角色的白 T 恤一起抠掉。必须绿幕 + 色度键控。

规格：**1536×1024，4 列 × 1 行**（每格 384×1024，全身姿势纵向空间充足）。

---

## 排错

### 节点标题显示英文类名、控件显示 UNKNOWN

例如标题是 `StickerScriptParser` 而不是 `Sticker · 脚本文案解析`，下面几个框显示 `UNKNOWN`。

**原因**：ComfyUI 后端没有注册这个节点。前端在拿不到节点定义时，会退回占位渲染——
标题用原始类名，控件用 UNKNOWN，但右侧的输出名（captions / p1…p9）仍然正常显示，
因为那是从工作流 JSON 里读出来的。

**解法**：**完全退出 ComfyUI 再重新启动**。刷新网页不管用，节点定义是后端启动时一次性注册的。
从桌面版退出（或托盘右键退出）后重开即可。

如果重启后仍然 UNKNOWN，看 ComfyUI 控制台有没有 `IMPORT FAILED: ...ComfyUI-StickerPack`，
那说明插件本身没加载成功，把报错发出来。

### 跑完只看到一堆 GIF，没有 ZIP

两个可能：

1. **zip 在上一级目录** —— v1.5 之前 `StickerSaveZip.folder` 留空会把 zip 复制到 `output` 根目录。
   去 `ComfyUI/output/` 下找 `<包名>.zip`，或者升级到 v1.5（留空 = 原地不动）。
2. **中途失败** —— v1.5 之前 zip 只在最后一步生成，任何一张出错就整包没有。
   v1.5 起改成增量打包：每完成一张就刷新一次 zip，中断也能拿到已完成的部分。
   控制台搜 `[Sticker] 完成：x/9` 看实际完成几张。

### 其他

**`Cannot handle this data type: (1, 1, 5)`** —— VAE 解码结果带了 alpha 通道（4 通道），
和 alpha 叠成 5 通道后 PIL 拒绝。v1.4 起 `_to_rgb_uint8()` 会强制归一成 HWC 3 通道，
CHW/4 通道/带 batch 维都能吃。

**`hostbuf_file_reader_read failed`** —— ComfyUI 读模型权重时内存不够，不是工作流的问题。
关掉占内存的程序，确认可用内存 > 4GB；不够就把 `script` 拆成两批跑。

**`queuePrompt` 返回 false / 点了 Run 没反应** —— `ref` 节点引用的图片不在 input 目录。
重新上传一次，文件名保持 `ref.png`。

---

## 性能

实测基线（RTX 4060 Laptop 8G，1536×1024，cells=4，8 步）：**单张 172 秒，9 张约 27 分钟**。
其中采样 107 秒、VAE 解码 52 秒。解码那 52 秒是因为 unet 还占着显存，整张解码必然 OOM，
落到了「三遍分块再平均」的兜底路径。

v1.5 起做了四件事，默认档预计压到 **10–13 分钟**：

| 手段 | 为什么有效 | 预计收益 |
|---|---|---|
| **三段式：先全部编码 → 再全部采样 → 最后全部解码** | 原来是逐条「编码→采样→解码」，每条都要把 8.9GB 文本编码器、6.9GB unet、0.6GB VAE 轮换一遍。9 条 = 27 次模型换入换出。分段后每个模型只加载一次 | 省约 3 分钟 |
| **解码阶段先卸载 unet** | VAE 单独占显存后能走整张解码，不再触发三遍分块平均 | 单张 52s → 约 10–15s，省约 5 分钟 |
| **`steps` 参数（默认 6）** | 在同一条 sigma 曲线上等距重采样，不是硬编码新曲线 | 采样快 25%，省约 3 分钟 |
| **`width` 默认 1536 → 1280** | 少 17% 像素，每格仍有 320px | 省约 2 分钟 |

再想快，按需调：

| 参数 | 改成 | 效果 |
|---|---|---|
| `steps` | 4 | 采样再快 1/3，细节略降 |
| `cells` | 3 | 少 25% 采样时间，动作连贯度略降 |
| `width` | 1024 | 再省 20% 像素，人物会小一圈 |
| `save_mp4` | 关（默认已关） | 省 9 次 ffmpeg 调用 |

**启动参数也值钱**：你的 venv 里装了 SageAttention 2.2.0 和 Triton，但默认没启用。
启动时加这两个参数，注意力部分通常还能再快 20–30%：

```
python main.py --use-sage-attention --fast
```

`--use-sage-attention` 若报错就去掉（个别模型不支持），`--fast` 一般都能用。

### 运行时验证状态（重要）

`StickerAutoPack` 的**代码正确性已静态验证**，但**端到端没能在本机跑完**：

- ✅ 插件导入、节点注册：`/object_info/StickerAutoPack` 返回 200
- ✅ 节点契约检查通过（控件数量、输出槽位、class_type）
- ✅ 编码走的是 ComfyUI 官方 `comfy_extras.nodes_qwen.TextEncodeQwenImage21`，
  调用方式与你 `comfyui-ecom-main-image` 插件里已验证的写法完全一致
- ✅ 采样走 `comfy.sample.sample_custom`，签名对着 ComfyUI 源码核对过
- ❌ 实际出图没跑通 —— 本机可用内存只剩 **0.9 GB**（总 15.2 GB），
  ComfyUI 加载权重时直接 `hostbuf_file_reader_read failed` 并段错误退出。
  同一台机器在内存宽裕时（21:52 那次）是跑完过 57 节点版的

**所以你第一次跑 ① 时，如果报错请先看内存。** 建议：
1. 重启一次机器（最干净），或至少关掉浏览器 / 微信 / 其它占内存的程序
2. 确认任务管理器里「可用内存」> 4 GB 再点 Run
3. 还是不行就用 ②，它至少跑通过一次

---

## 验证记录

**已在真实 ComfyUI 0.42.1 + RTX 4060 Laptop 上跑通：**

- **脚本解析节点**：粘贴 9 条文案 → 正确拆出 9 条字幕 + 9 条提示词（在 ComfyUI 里实测，`PreviewAny` 回读验证）
- **打包段**（9 张图集 → 9 GIF + ZIP）：120 秒，ZIP 11 个条目 / 1.36MB，`testzip()` 通过
- **全链路 9 条**：21:52 那次跑完，471 秒，54 帧预览 + ZIP
- **UI 工作流**：`app.loadGraphData()` 加载成功，`app.queuePrompt()` 能排队执行

### ⚠️ 内存不足会报 `hostbuf_file_reader_read failed`

这是 ComfyUI 的 `comfy-aimdo` 读模型权重失败，**不是工作流的问题**。

本次复测时机器只剩 **1.2 GB 可用内存**（总 15.2 GB），跑到第 9 条采样时炸了，报错栈是
`hostbuf_file_reader_read` → `cast_to_gathered` → 读 diffusion 权重。同一张图在内存充足时是跑得完的。

**对策（任选）**：
1. 跑之前关掉浏览器等占内存的程序，确认可用内存 > 4 GB
2. 从桌面版 ComfyUI 启动（它的内存策略比命令行 headless 稳）
3. 还是不够就把 9 条拆两批跑：`script` 里先留前 5 条，跑完再换成后 4 条

**踩过的坑（已修）**：
1. 调色板最近邻必须用 **int32** —— `(a-b)**2` 用 int16 溢出（255²=65025>32767），会让黑发变白发。
2. ComfyUI 的 **IMAGE 是 `[B,H,W,C]`、MASK 是 `[B,H,W]`**，两者维度不同，不能共用一个 batch 归一化函数。
3. 总览图必须先把 512 帧 **resize 到 tile 尺寸**再贴，否则只会贴进左上角一块。
4. 把 STRING widget 当输入接时，节点 `inputs` 里要加 `{"name": ..., "widget": {"name": ...}}`，否则连线接不上。

---

## 自检命令

```bash
python test_core.py <精灵图.png> --text "懂的都懂" --out out.gif   # 纯 PIL 全链路
python test_nodes_contract.py                                     # 节点契约 vs 工作流
python build_workflows.py                                         # 重新生成工作流
python gen_docs.py                                                # 重新生成节点参数说明

# 需要 torch（用 ComfyUI 的解释器）
<ComfyUI 的 python> test_autopack_mock.py
<ComfyUI 的 python> test_e2e_nodes.py
```

`test_autopack_mock.py` 用桩件替掉 comfy / nodes / nodes_qwen，把 `StickerAutoPack`
从解析一路跑到 ZIP，并断言传给 `sample_custom` 的 `latent_image` 是张量而不是字典
—— 这是实际踩过的坑，加进来防止回归。
