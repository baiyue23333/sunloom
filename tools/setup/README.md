# 可选环境

出图主流程只需要 ComfyUI + 一个模型，其他都是可选的。

| 模块 | 需要什么 | 脚本 |
| --- | --- | --- |
| ComfyUI | 本机安装（推荐 v0.3.60+） | install_comfyui.ps1 |
| 训练 | kohya sd-scripts | install_kohya.ps1 |
| 打标 | onnxruntime + WD14 模型 | download_wd14.ps1 |
| 手部自动检测 | SDPose 自定义节点 | 暂不提供，改用框选式手部精修 |

未安装时，对应按钮会返回可读错误并提示运行哪个脚本。

    powershell -ExecutionPolicy Bypass -File tools/setup/install_comfyui.ps1
    powershell -ExecutionPolicy Bypass -File tools/setup/install_kohya.ps1
    powershell -ExecutionPolicy Bypass -File tools/setup/download_wd14.ps1
