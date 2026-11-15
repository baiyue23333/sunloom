# SUNLOOM

> **声明：本项目是一个基于 Anima（Qwen-Image / `anima-base`）架构构建的本地 AI 出图工作站。**
>
> **开源发布声明（重要）**：本仓库仅提供工作站前后端代码、工作流编排模板与通用提示词积木框架，**不包含、亦不随仓库分发任何底层绘画模型、LoRA 权重文件、ONNX 打标模型或私有角色卡资产（含角色专属正/负向提示词、角色人设及生成图片）**。所有模型权重与角色卡需由使用者在本地自行准备。

仓库地址：https://github.com/baiyue23333/sunloom

---

## 一、工作站概述

**SUNLOOM** 是一套围绕 **Anima（Qwen-Image）** 底模深度定制的本地出图与工作流管理工作站，由 **FastAPI 站台（`127.0.0.1:8770`）+ ComfyUI（`127.0.0.1:8188`）+ 规则编排引擎 + SQLite 持久化层** 组成。

相比直接在 ComfyUI 中手工连线，SUNLOOM 将提示词拼装、构图分流、LoRA 适配、重映多阶段重绘、显存分级调度与复现溯源整合到同一个 Web 界面中：

| 核心能力 | 说明 |
| --- | --- |
| **Anima 专属工作流编译** | 使用 `UNETLoader` + `CLIPLoader (qwen_3_06b_base, type=stable_diffusion)` + `VAELoader (qwen_image_vae)` + 动态 `LoraLoaderModelOnly` 链自动拼装提交 ComfyUI（传统架构 / Qwen-2.1 主线推理已下线） |
| **`@宏` 积木与服装派生** | 内置 `670` 条结构化 `@宏` 英文自然语言积木，支持按性别（女 `f` / 男 `m` / 中性）过滤、旧别名自动映射、`@STRIP_*` 脱除词两阶段剥离与权重包装 |
| **双出图模式** | **常规直出模式**（全图一次 T2I，`denoise=1.0`，画师自由度最高）与 **合作（重映）模式**（三页签独立工作台：`环境 → 人物 → 出图`） |
| **重映三段式高精管线** | `01 出板` → `02 SDPose/BiRefNet 身体蒙版裁切放大重绘 + 低频色温融合` → `03 脸部椭圆精修 / 手部凸包精修 + 写实脚底阴影`，全程写入 `manifest.json` 与 PNG 元数据 |
| **纯规则审校与引导** | 已移除本地 LLM 依赖，改用快速确定性规则完成积木冲突检测（`ir.py`）、一键修正（`prompt_fix.py`）与光线/色温引导（`light_guide.py`） |
| **显存 / 内存分级调度** | 内置 `aggressive` / `balanced` / `performance` 三档显存策略：同底模热命中保留、跨模型族（`anima` ↔ `sdpose` / `birefnet`）切换显式释放、CUDA OOM 自动清模重试一次 |
| **11 个功能页签** | 拼装、工作流向导、词库、服装、画廊、配方、打标、训练、复现、引擎、维护 |

---

## 二、仓库与系统结构

### 2.1 目录总览

```text
sunloom/
├─ 启动全部.bat                  # Windows 一键启动：看护进程 + FastAPI(8770) + 打开浏览器
├─ .gitignore                    # 发布过滤：屏蔽模型、LoRA、角色卡、数据库与出图产物
├─ README.md                     # 本说明文档
├─ core/
│  └─ store.py                   # SQLite WAL 存储层（recipes / cards / templates / jobs_history / coop_runs）
├─ station/
│  ├─ server.py                  # FastAPI 应用装配与路由挂载入口（port 8770）
│  ├─ routes_*.py                # 拆分的 API 路由（jobs / coop / cards / library / gallery / hand / mem / maint / promptlib）
│  ├─ svc_*.py                   # 业务服务层（svc_state / svc_jobs / svc_coop / svc_recipes / svc_mem / svc_obs）
│  ├─ graph.py / comfy.py        # ComfyUI JSON 图编译、KSampler 与 LoRA 链注入、WebSocket/HTTP 客户端
│  ├─ ir.py / promptlib.py       # 纯规则提示板校验器、词库读写
│  ├─ workflows/                 # Anima 基准模板：anima_t2i.json / anima_i2i.json / anima_inpaint.json / sdpose_probe.json
│  └─ static/                    # 前端 SPA（index.html + app.js + js/lora.js + js/transparency.js + style.css）
├─ ref/
│  ├─ prompts.py                 # 唯一的 @宏 加载、别名解析、@STRIP_* 剥离与性别判定实现
│  ├─ prompt_lib.json            # 通用积木与备注词库（发布版应剥离个人角色卡专属词条）
│  ├─ lora_roles.json            # 画师/背景/厚涂 LoRA 角色分类规则（前后端共用唯一源）
│  └─ lora_base_overrides.json   # LoRA 底模归属覆写表（按 anima 严格过滤）
├─ tools/
│  ├─ comfy_paths.py             # 通过 ComfyUI /system_stats 动态探测 input/output/models 路径
│  ├─ coop_reproject.py          # 合作模式主线：重映工作台流水线执行器
│  ├─ reproj_parts.py            # SDPose / BiRefNet 蒙版裁切、人脸与手部检测、脚底投影
│  ├─ reproj_provenance.py       # 重映 manifest.json 与 PNG PngInfo 血缘元数据嵌入
│  ├─ hand_precise.py / fusion.py# 局部精修、颜色低频融合
│  ├─ mem_plan.py                # 合作流水线跨模型显存计划调度与 mem_plan.json 落盘
│  ├─ prompt_fix.py / light_guide.py # 规则一键修正与光线引导
│  ├─ cutout.py / standee_template.py # BiRefNet 抠图与立绘双层排版模板
│  ├─ check_sizes.py             # 代码单文件 ≤ 20KB 静态检查闸门
│  ├─ fix_paths.py               # 迁移目录后重映射配方/数据库绝对路径
│  └─ watchdog.py / ui_smoke.mjs # 站台进程看护与 Playwright UI 冒烟检查
└─ tests/
   └─ run_tests.py               # 全量回归入口（121 项测试：完整性/展开/校验/重映/显存/契约）
```

### 2.2 核心数据流（一次生成是如何流转的）

```text
1. 词库装配
   ref/prompts.py 读取通用 @宏库 +（可选）本地导入的角色卡 views / 服装派生 @OUT_* @NEG_*
        │
        ▼  前端 S.pos / S.neg 积木车道（含启用开关与单块权重）
2. 规则审校与展开
   POST /api/validate（ir.py 冲突校验） → POST /api/fix/blocks（prompt_fix.py 一键修正）
   POST /api/expand  → prompts.py 按词边界展开宏，@STRIP_* 两阶段剥离衣物词再包权重
        │
        ├─▶【常规直出模式】POST /api/run → svc_jobs._submit()
        │      └─ graph.build() 编译 anima_t2i / i2i / inpaint + LoRA 链 → ComfyUI :8188
        │
        └─▶【合作重映模式】POST /api/coop (mode=reproject) → tools/coop_reproject.py
               ├─ [1/3] 01_plate：真实尺寸 + 场景/人物提示混合出板
               ├─ [2/3] 02_body ：SDPose/BiRefNet 抠出人体框，裁切放大重绘 + lowfreq_match 融色
               └─ [3/3] 03_face / 04_hands / 05_shadow：椭圆修脸 + 凸包修手 + 脚底阴影
        │
        ▼
3. 显存调度与落盘溯源
   svc_mem / mem_plan 协调模型驻留与释放 → 图片存至 SD-Picture/ → SQLite (station.db) 入库配方
```

---

## 三、部署与使用教程

### 3.1 环境与前置模型准备（Anima 必需件）

1. **基础运行环境**：
   - Python **3.10**（推荐 3.10，其他版本需自行补齐对应轮子）
   - **ComfyUI**（支持 **ComfyUI Desktop** 或标准独立版，默认监听 `http://127.0.0.1:8188`）
   - 可选：Node.js + Playwright（仅用于运行 `tools/ui_smoke.mjs` 前端冒烟测试）
2. **安装 Python 依赖**：
   ```bash
   pip install fastapi uvicorn pydantic pillow numpy opencv-python aiohttp psutil httpx
   ```
3. **准备 Anima 底层模型文件（需自行获取，本仓库不提供）**：
   请将以下三件套放入你的 ComfyUI `models/` 对应目录（文件名为工作流模板默认引用的基准名）：
   - Diffusion UNET：`models/diffusion_models/anima-base-v1.0.safetensors`
   - Text Encoder (CLIP)：`models/text_encoders/qwen_3_06b_base.safetensors`
   - VAE：`models/vae/qwen_image_vae.safetensors`
   - （可选）将你自己收集或训练的 **Anima 兼容 LoRA** 放入 `models/loras/`。工作站会通过 ComfyUI 过滤出仅兼容 `anima` 底模的 LoRA。
   - （可选）若使用**打标页**的 WD14 自动反推，需自行放置 ONNX 模型至 `ref/wd14/model.onnx`。
4. **常用环境变量（按需设置）**：
   - `STATION_COMFY`：ComfyUI 地址，默认 `http://127.0.0.1:8188`
   - `COMFY_SHARED_DIR`：ComfyUI 离线时用于回退探测 `input/output/models` 的根目录
   - `STATION_DB`：覆盖默认 SQLite 数据库路径（`station/data/station.db`）
   - `SUNLOOM_ROOT`：显式指定工作站根目录

### 3.2 启动工作站

1. 先启动 **ComfyUI**（确保 `127.0.0.1:8188` 可访问）。
2. 启动 SUNLOOM 站台（Windows 可直接双击 `启动全部.bat`，或命令行启动）：
   ```powershell
   cd station
   python -m uvicorn server:app --host 127.0.0.1 --port 8770
   ```
3. 浏览器打开 `http://127.0.0.1:8770/`。进入右上角或「维护」页，可执行**管线自检**确认 ComfyUI 与 Anima 三件套连通正常。

### 3.3 两种出图模式上手步骤

#### 方式 A：常规直出模式（适合快速抽卡与发挥画师个人笔触）
1. 在右侧栏选择底模（仅列出 Anima 底模）与步数/CFG/尺寸；**默认不会预挂任何人物画师 LoRA**。
2. 从左侧**积木库**点击添加场景、光影、机位、构图、动作、服装等积木到正/负向车道，或点击**「随机（手气）」**一键组合。
3. **若想测试或最大化某位画师 LoRA 的原始画风**：
   - 在画师下拉选择画师后，将右侧「**身份强度**」设为 **`不锁身份 0`**（否则强/弱身份词会锁定发型瞳色等特征）；
   - 或直接点击**「画师自由发挥」**将画布精简为纯主体词 + 该画师真实触发词。
4. 若顶部校验出现冲突，可点击**「一键修正」**让规则引擎自动消冲突、再点**「▶ 出图」**。

#### 方式 B：合作重映模式（适合大场景人物构图 + 局部精细重绘）
1. 点击顶部或工作台的**「合作模式」**切换为**重映三页签工作台**，按顺序操作：
   - **① 环境**：选择主场景槽位、开关室内加门/环境细节，并在「环境画师 LoRA」选择场景/厚涂系 LoRA；
   - **② 人物**：添加人物特征、动作或拖拽服装积木，可选本地角色卡与视角；选择人物画师 LoRA；
   - **③ 出图**：设置共用光影、景别、环境与人物默认占比（默认 `ratio=0.34`，约 **环境 66% / 人物 34%** 1/3 全身）以及环境/人物 LoRA 权重（默认 `0.70 / 0.85`），确认顶部三个就绪胶囊就绪后点击**「▶ 出图」**；也可随时点参数栏右上角**「数据」**查看本机 Anima LoRA 推荐值与占比对照。
2. 后台会依次执行「整体出板（自动按占比补充景别防人物过度放大）→ 人体裁切重绘（自动附带画师触发词与中性光照后缀）→ 脸部/手部精修 → 脚底接触阴影」，可在右下角悬浮卡查看实时进度，成图与过程记录保存在 `SD-Picture/coop/`。

### 3.4 自定义积木与导入自有角色卡
- **新增/编辑积木**：在「**词库**」页可直接增删改积木、设置性别归属（`f` / `m` / 中性）及备注。
- **使用自有角色卡**：在工作台或角色卡管理处导入/新建你自己的 JSON 角色卡（包含你的 LoRA 配比、专属正向块 `pos_blocks` 与专属负向块 `neg_blocks`）。角色卡仅保存在本地 `station/data/cards.json` 与 `ref/cards/`，不会随公开代码库分发。

---

## 四、关键机制详细解释

### 4.1 为什么基于 Anima 的工作站不能混挂其他底模 LoRA？
Anima（基于 Qwen-Image 架构、`qwen_3_06b_base` 文本编码器与 `qwen_image_vae`）在权重张量维度和概念表达上与 SD1.5 / Flux 完全不同。`svc_state.py` 中的 `_lora_base_map()` 会结合权重元数据与 `ref/lora_base_overrides.json` 严格判定 LoRA 底模，前后端下拉与校验会拦截非 Anima LoRA，避免运行时维度报错或出图崩坏。

### 4.2 画师 LoRA 的“触发词”与“两模式约束差异”
- **按元数据真实触发词生效**：站台不会给画师硬塞互相打架的风格形容词（例如强加厚涂/赛璐璐词反过来盖住画师），而是仅对训练时依赖特定触发词的模型自动补足真实触发词（例如 `artistTrigger()`），保持笔触原生还原。
- **常规直出 vs 合作重映的自由度区别**：
  - 常规直出为全图 `denoise=1.0`，只要不锁角色身份特征，画师可自由决定构图与笔触；
  - 合作重映为了解决“小人物脸糊”和“人物像贴纸”问题，`02_body` 阶段采用裁切后 `inpaint`（`denoise` 随人物占比在 `0.40 ~ 0.56` 之间自适应）并做 `20%` 低频色调融合（`fusion.lowfreq_match`），因此重映模式优先保证光影一致性与脸手质量，构图自由度相对直出更克制。

### 4.3 `@STRIP_*` 剥离机制与防误伤
当用户给某套服装搭配「赤脚（`@STRIP_SHOES`）」「无袜（`@STRIP_SOCKS`）」等积木时，单纯靠负向提示词往往压不住正向服装里已写死的 `loafers, socks`。`ref/prompts.py` 采取两阶段处理：
1. 展开正向文本时，先按块对原始服装文本做**正则词边界清洗**，精准删除鞋子/袜子等词汇；
2. 再包装单块权重，并在末尾补入 `bare feet` / `bare legs` 等替代词，同时支持把 `@STRIP_*` 放进负向车道而不触发误报。

### 4.4 显存 / 内存分级调度与低显存防 OOM
为兼容 8GB 等消费级显存环境，`station/svc_mem.py` 与 `tools/mem_plan.py` 维护全局调度策略：
- **同族热命中**：连续使用 Anima 出图时保留模型驻留，跳过重复加载；
- **分段清模**：低显存触发 `soft_free`（仅回收碎片）或 `hard_unload`（卸载模型）；重映流水线在 `Anima` ↔ `SDPose` ↔ `BiRefNet` 间切换时显式卸模，避免多个大模型挤爆显存；
- **OOM 自愈**：一旦 ComfyUI 返回 CUDA OOM，自动执行一次清模与内存整理后原参数重试。

---

## 五、开发维护与验证命令

改动代码或积木库后，请依次运行以下三项检查（单份代码文件不得超过 `20KB`）：

```powershell
# 1. 文件体积闸门
python tools/check_sizes.py

# 2. 前端 UI 冒烟检查（需站台正在监听 8770）
node tools/ui_smoke.mjs 8770

# 3. 服务端/规则/展开/重映/显存全量回归（建议使用 Python 3.10）
python tests/run_tests.py
```

若整个目录发生磁盘路径迁移，可先预演再应用路径修复脚本，更新配方库与缓存中的绝对路径：
```powershell
python tools/fix_paths.py          # 预演
python tools/fix_paths.py --apply  # 确认后写回
```

---

## 六、开源发布检查清单（推送 GitHub 前必看）

面向 `https://github.com/baiyue23333/sunloom` 对外发布时，请务必确认**不包含任何私有模型、LoRA 或角色卡内容**：

1. **已由 `.gitignore` 屏蔽的内容（新建独立仓库时自动生效）**：
   - 模型与 LoRA：`*.safetensors`、`*.ckpt`、`*.onnx`、`*.pt`、`*.pth`、`models/`、`ref/wd14/*.onnx`；
   - 角色卡与专属正负向：`station/data/cards.json`、`ref/cards/`、`ref/character.json`、`station/data/snapshots/`、`ref/artist_recipes.json`；
   - 本地历史与图片：`SD-Picture/`、`station/data/station.db*`、`station/data/recipes.json`、`产出作品/2026/`、`产出作品/画师参考/`、`**/*.png`。
2. **从现有工作区导出或清理 Git 暂存区前，额外核查已跟踪文件**：
   - 检查 `ref/prompt_lib.json`、`ref/prompts.py` 中是否仍留有个人原创角色相关的示例特征积木（如 `@ID_*`、`@BODY_*`），公开通用版可按需清洗替换；
   - 检查 `station/data/cards.json`、`ref/cards/`、`ref/character_whitelist.json`、`station/data/station.db`、`station/data/recipes.json` 等文件是否已在旧仓库索引中（发布前可通过导出纯净分支或 `git rm --cached` 解除跟踪，切勿误删本地工作文件）。
