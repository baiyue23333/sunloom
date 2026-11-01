# 部署到 Linux（Ubuntu）

> 这份是给 Linux 服务器/云 GPU 用的；Windows 走 [新手指南](新手指南.md) 里的一键脚本。
> 实测环境：Ubuntu 24.04 + RTX 4090 + Python 3.12。

## 0. 前置

| 项 | 要求 |
| --- | --- |
| 系统 | Ubuntu 22.04 / 24.04，root 或有 sudo |
| GPU | NVIDIA 驱动已装（`nvidia-smi` 能出卡） |
| Python | 3.10+（系统自带即可） |
| ComfyUI | 另装，默认 `127.0.0.1:8188` |

## 1. 装系统依赖

```bash
apt-get update -qq
apt-get install -y python3-venv python3-pip
```

> 很多云镜像是「有 python3 没 pip」，这一步就是补它。

## 2. 放代码

```bash
cd /root
git clone https://github.com/baiyue23333/sunloom.git
cd sunloom
```

`git clone` 不通时，本地打包上传：

```bash
# 本地
tar czf sunloom.tar.gz --exclude=.git --exclude=output sunloom-open
# 服务器
scp -P <端口> sunloom.tar.gz root@<主机>:/root/ && cd /root && tar xzf sunloom.tar.gz
```

## 3. 建虚拟环境 + 装依赖

```bash
cd /root/sunloom
python3 -m venv .venv
.venv/bin/pip install -U pip -i https://pypi.tuna.tsinghua.edu.cn/simple
.venv/bin/pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

依赖只有三个：`fastapi` / `uvicorn` / `pillow`。

## 4. 写配置

```bash
cp config.example.json station/data/config.json
```

按实际改三处：

```json
{
  "comfy_url": "http://127.0.0.1:8188",
  "model": {
    "unet_name": "你的-unet.safetensors",
    "clip_name": "你的文本编码器.safetensors",
    "vae_name": "你的-vae.safetensors",
    "clip_type": "stable_diffusion"
  }
}
```

> `model` 里的名字必须和 ComfyUI `models/` 下的**文件名**完全一致。

## 5. 启动

```bash
cd /root/sunloom/station
nohup ../.venv/bin/python -m uvicorn server:app --host 0.0.0.0 --port 8790 \
  > /root/sunloom-station.log 2>&1 &
```

只给自己看可以绑 `127.0.0.1`；要远程访问就 `0.0.0.0`（记得安全组/防火墙）。

## 6. 自检（30 秒）

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8790/            # 200
curl -s http://127.0.0.1:8790/api/bootstrap | head -c 120                    # tokens/notes/garments
curl -s http://127.0.0.1:8790/api/templates | head -c 120                    # 模板列表
curl -s -X POST http://127.0.0.1:8790/api/expand -H 'Content-Type: application/json' \
  -d '{"positive":[{"token":"@SUBJ"},{"token":"@CAM_BUST"}],"negative":[]}'
```

预期 `bootstrap` 里有 `tokens`、`notes`、`garments`；`expand` 返回展开后的英文提示词。

## 7. 接上 ComfyUI

```bash
cd /root/ComfyUI
python3 -m venv .venv
.venv/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple torch torchvision torchaudio
.venv/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
.venv/bin/python main.py --listen 0.0.0.0 --port 8188
```

模型按 ComfyUI 的目录放：

```
ComfyUI/models/
  diffusion_models/  unet（UNet 加载器）
  text_encoders/     CLIP（CLIPLoader）
  vae/               VAE
  loras/             LoRA
```

单文件 checkpoint 用户：把 `station/workflows/t2i.json` 的加载节点换成 `CheckpointLoaderSimple`。

## 8. 从本机访问

平台不映射 8790 时用 SSH 隧道：

```bash
ssh -p <端口> -L 8790:127.0.0.1:8790 root@<主机>
# 然后浏览器打开 http://127.0.0.1:8790/
```

## 9. 常见问题

| 现象 | 原因 / 处理 |
| --- | --- |
| `pip3: command not found` | 没装 python3-pip，见第 1 步 |
| `ModuleNotFoundError: fastapi` | 用了系统 python 而不是 `.venv/bin/python` |
| `Address already in use` | 换端口 `--port 8791`，或 kill 旧进程 |
| 页面能开、出图报 ComfyUI 离线 | ComfyUI 没起，或 `config.json` 的 `comfy_url` 不对 |
| 下载慢/超时 | 给 pip 加 `-i https://pypi.tuna.tsinghua.edu.cn/simple` |
| 模型名报错 | `config.json` 里的名字要和 `ComfyUI/models/` 文件名一字不差 |

## 10. 验收清单

| 检查 | 通过标准 |
| --- | --- |
| 首页 | 200，标题 `SUNLOOM · block studio` |
| 静态资源 | `/app.js` 200 |
| bootstrap | 含 tokens / notes / garments |
| templates | 返回模板数组 |
| expand | 返回展开后的英文提示词 |
| validate | 缺 `@SUBJ` 时给出 `NO_SUBJECT` |
| 存储 | `station/data/station.db` 自动生成 |
| 出图 | ComfyUI 在线后能跑通一张 640×896 |
