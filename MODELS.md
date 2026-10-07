# Models and custom nodes

This repository contains **no model weights**. Download every file from its authors and keep their licenses.
The file names below are the defaults of the workflow templates. If yours differ (or live in a subfolder), pass them
with `--wan key=value` / `--krea key=value` (see README), or run `pvs check`: it finds files in subfolders and prints the
exact flag to use.

Tested with ComfyUI 0.37 on one RTX 4090 (24 GB VRAM) and 44 GB system RAM.

## Custom nodes

| Node | Repository | License | Install |
|---|---|---|---|
| `UnetLoaderGGUF` | [city96/ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF) | Apache-2.0 | `git clone https://github.com/city96/ComfyUI-GGUF` into `ComfyUI/custom_nodes`, then `pip install --upgrade gguf` |
| `MiniMaxH3PixelArtRefiner` | [envy-ai/ComfyUI-Krea2-Pixel-Art-Refiner](https://github.com/envy-ai/ComfyUI-Krea2-Pixel-Art-Refiner) | no license file in the repository at the time of writing – check before redistributing | `git clone https://github.com/envy-ai/ComfyUI-Krea2-Pixel-Art-Refiner.git krea2_pixel_art_refiner` into `ComfyUI/custom_nodes` |

`WanImageToVideo`, `ModelComputeDtype`, `KSamplerAdvanced` and the Krea 2 loaders are ComfyUI core nodes. Restart
ComfyUI after installing custom nodes.

## Video model: Wan 2.2 I2V A14B

| File (default name) | Folder | Source | License | Size |
|---|---|---|---|---|
| `Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf` | `models/unet` | [QuantStack/Wan2.2-I2V-A14B-GGUF](https://huggingface.co/QuantStack/Wan2.2-I2V-A14B-GGUF/tree/main/HighNoise) (`HighNoise/`) | Apache-2.0 (Wan 2.2) | 9.65 GB |
| `Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf` | `models/unet` | [QuantStack/Wan2.2-I2V-A14B-GGUF](https://huggingface.co/QuantStack/Wan2.2-I2V-A14B-GGUF/tree/main/LowNoise) (`LowNoise/`) | Apache-2.0 | ≈ 9.65 GB |
| `wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors` | `models/loras` | [Comfy-Org/Wan_2.2_ComfyUI_Repackaged](https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/tree/main/split_files/loras) (`split_files/loras/`) | Apache-2.0 | |
| `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | `models/text_encoders` | [Comfy-Org/Wan_2.2_ComfyUI_Repackaged](https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/tree/main/split_files/text_encoders) (`split_files/text_encoders/`) | Apache-2.0 | 6.74 GB |
| `wan_2.1_vae.safetensors` | `models/vae` | [Comfy-Org/Wan_2.2_ComfyUI_Repackaged](https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/tree/main/split_files/vae) (`split_files/vae/`) | Apache-2.0 | 254 MB |

Only the **low-noise** lightx2v LoRA is needed: the high-noise stage deliberately runs without it (it damps motion).
Other GGUF quantisations work too (Q5/Q6/Q8 if you have the RAM); pass `--wan wan_high=… --wan wan_low=…`.

## Pixel model: Krea 2 Turbo + k2-pixel

| File (default name) | Folder | Source | License | Size |
|---|---|---|---|---|
| `krea2_turbo_fp8_scaled.safetensors` | `models/diffusion_models` | [Comfy-Org/Krea-2](https://huggingface.co/Comfy-Org/Krea-2/tree/main/diffusion_models) (`diffusion_models/`), original: [krea/Krea-2-Turbo](https://huggingface.co/krea/Krea-2-Turbo) | **Krea 2 Community License** ([terms](https://www.krea.ai/krea-2-licensing)) | |
| `qwen3vl_4b_fp8_scaled.safetensors` | `models/text_encoders` | [Comfy-Org/Krea-2](https://huggingface.co/Comfy-Org/Krea-2/tree/main/text_encoders) (`text_encoders/`) | Apache-2.0 (Qwen3-VL) | 5.24 GB |
| `qwen_image_vae.safetensors` | `models/vae` | [Comfy-Org/Krea-2](https://huggingface.co/Comfy-Org/Krea-2/tree/main/vae) (`vae/`) | Apache-2.0 (Qwen-Image VAE) | |
| `k2-pixel32.safetensors` | `models/loras` | [e-n-v-y/Krea-2-Pixel-Art](https://huggingface.co/e-n-v-y/Krea-2-Pixel-Art) | MIT (adapter; the Krea 2 base license still applies to the model) | 74 MB |
| `k2-pixel64.safetensors` | `models/loras` | [e-n-v-y/Krea-2-Pixel-Art](https://huggingface.co/e-n-v-y/Krea-2-Pixel-Art) | MIT | 74 MB |

`k2-pixel32` is used for grids up to 48 px (one art pixel = 32 image pixels = 2 × 2 Krea tokens), `k2-pixel64` above
that or with `--cell 16`. Do not use `k2-pixel128` at 1024²: at 8 px per art pixel (half a token) it effectively draws
a 64 grid.

## Licenses in short

* **This repository** (code, workflow templates, docs, example images): MIT, see [LICENSE](LICENSE).
* **The models** keep their own licenses. Wan 2.2, Qwen3-VL and the Qwen-Image VAE are Apache-2.0; the k2-pixel LoRAs
  are MIT; **Krea 2 is under the Krea 2 Community License**, which has its own conditions for commercial use. Read the
  terms of every model before you ship anything you made with it.
