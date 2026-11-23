# sitepix

Website ready images from a local model on your Mac. One command takes a prompt and gives back a finished file at the exact size you asked for, already converted to WebP and named from the prompt. It runs on Apple Silicon with no account, no API key, and no cost per image, and it works two ways: as a normal command line tool, and as an MCP server so any AI assistant can make the images a task needs.

```
sitepix "a lighthouse on a rocky coast at dusk, flat illustration" --size hero -o ./images
/Users/you/site/images/a-lighthouse-on-a-rocky-coast.webp
```

## Why

Image models produce a PNG at whatever size they like. A website needs a 1600x900 header, a 1200x630 share image, and a small thumbnail, all compressed, with sensible file names, in the right folder. sitepix does that last mile, and it adds the two things a tool needs when an assistant calls it over and over on a machine that is busy with other work:

- It checks free memory before each run and stops with a clear message instead of pushing the Mac into swap.
- It runs one generation at a time, so two requests never fight for the same memory.

The image engine is [mflux](https://github.com/filipstrand/mflux), which runs current image models natively on Apple Silicon through MLX. sitepix drives it and handles everything around it.

## Requirements

- A Mac with Apple Silicon (M1 or newer)
- 16 GB of memory or more
- [uv](https://github.com/astral-sh/uv) to install it (`brew install uv`)

## Install

```
uv tool install git+https://github.com/AIAppsAPI/sitepix
sitepix setup
sitepix doctor
```

`sitepix setup` downloads the default model (several GB, one time) and saves an 8 bit copy of it. That step matters: the mflux docs measure a 1024x1024 image at about 7.5 GB of peak memory from a saved 8 bit copy, against about 26 GB when the same model is loaded from the download cache. `sitepix doctor` then confirms everything is in place.

## Use from the command line

```
sitepix "a red fox in the snow"                          # hero size, WebP, current folder
sitepix "a red fox in the snow" --size og -o ./public    # social share image into a folder
sitepix "team at a whiteboard" -o ./img/team.jpg         # exact file name and format
sitepix "abstract blue waves" --size 1200x400 --max-kb 80
sitepix "a red fox in the snow" --seed 42 --json         # repeatable, full details as JSON
```

The only thing printed on standard output is the path of the finished file, so scripts can capture it directly. Progress goes to standard error.

### Sizes

| Name | Pixels | Use |
|---|---|---|
| hero | 1600x900 | wide page header |
| og | 1200x630 | social share image |
| square | 1024x1024 | general purpose |
| thumb | 640x360 | card thumbnail |
| banner | 1920x640 | very wide strip |
| portrait | 832x1216 | tall image |
| icon | 512x512 | small square |

Any explicit size works too, such as `--size 1200x400`. Image models do their best work near one megapixel, so sitepix generates close to that in the right shape, then resizes and center crops to the exact size. You always get the pixels you asked for, never a stretched image.

### Options

| Option | What it does |
|---|---|
| `-o, --output` | A file path, or a folder (the file is then named from the prompt) |
| `-s, --size` | A preset name or WIDTHxHEIGHT, default `hero` |
| `-f, --format` | `webp` (default), `png` or `jpg`. A file extension in `--output` wins |
| `-q, --quality` | 1 to 100 for WebP and JPG, default 82 |
| `--max-kb` | Lower the quality until the file is under this size |
| `--seed` | Fixed seed to reproduce an image |
| `--style` | A named style from your config file |
| `--model` | `z-image-turbo` (default), `flux2-klein-4b` or `flux2-klein-9b` |
| `--low-ram` | Trade speed for lower memory use |
| `--force` | Run even when free memory looks too low |
| `--json` | Print the full result as JSON |

Other commands: `sitepix sizes`, `sitepix styles`, `sitepix init`, `sitepix setup`, `sitepix doctor`, `sitepix serve`.

## Use from an AI assistant

There are two ways, pick whichever your assistant supports.

### As a plain command

Any assistant that can run terminal commands (Claude Code, Codex, Cursor's agent, and others) can use sitepix as it is. Add a line like this to your project instructions file (`CLAUDE.md`, `AGENTS.md`, or the equivalent):

```
To create an image, run: sitepix "description of the image" --size hero -o ./images
It prints the path of the saved file. Sizes: hero, og, square, thumb, banner, portrait, icon, or WIDTHxHEIGHT.
```

### As an MCP server

`sitepix serve` exposes the same function as an MCP tool, so the assistant sees a `generate_image` tool with a description and typed inputs and decides on its own when to call it. This is the route for chat style apps that have no terminal.

Claude Code:

```
claude mcp add sitepix -- sitepix serve
```

Any other MCP client, in its server config:

```json
{
  "mcpServers": {
    "sitepix": { "command": "sitepix", "args": ["serve"] }
  }
}
```

If a desktop app cannot find the command, use the full path printed by `which sitepix`.

The server is a thin layer over the command line core. It runs locally over standard input and output, started by the assistant itself. Nothing listens on the network.

| Tool | Inputs | Returns |
|---|---|---|
| `generate_image` | `prompt`, `size`, `output`, `style`, `format`, `seed` | The saved file path, size and seed |
| `list_options` | none | The size presets and your named styles |

## Styles

A style is a named prompt wrapper, optionally with a LoRA, so every image for a site shares one look. Run `sitepix init` to write a sample config at `~/.config/sitepix/config.json`, then edit it:

```json
{
  "model": "z-image-turbo",
  "output_dir": "~/Pictures/sitepix",
  "format": "webp",
  "quality": 82,
  "styles": {
    "flat": {
      "suffix": "flat vector illustration, simple shapes, limited color palette, white background"
    },
    "brand": {
      "prefix": "zxq style",
      "lora": "~/models/loras/brand.safetensors",
      "lora_scale": 0.8
    }
  }
}
```

```
sitepix "a rocket leaving a launch pad" --style flat
```

Every key is optional. `min_free_gb` overrides how much free memory a run wants before it starts.

## Memory

Before each run with a saved model, sitepix reads how much memory macOS can hand over without swapping and compares it with what the model wants (about 9 GB for the default model). If there is not enough, it stops and says so. Pass `--force` to run anyway, or set `min_free_gb` in the config to change the threshold. The figure for `z-image-turbo` comes from measurements in the mflux docs, the figures for the FLUX.2 klein models are estimates from their size.

## Models and licenses

sitepix is MIT licensed. It ships no model files. Models are downloaded to your own machine by mflux, and each model has its own license that decides what you may do with the images, including commercial use. Read the model card before using a model for paid work:

- `z-image-turbo`: [Tongyi-MAI/Z-Image-Turbo](https://huggingface.co/Tongyi-MAI/Z-Image-Turbo)
- `flux2-klein-4b`: [black-forest-labs/FLUX.2-klein-4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B)
- `flux2-klein-9b`: [black-forest-labs/FLUX.2-klein-9B](https://huggingface.co/black-forest-labs/FLUX.2-klein-9B)

## Use from Python

```python
from sitepix import Request, generate

result = generate(Request(prompt="a red fox in the snow", size="og", output="./public"))
print(result.path, result.width, result.height, result.seed)
```

## Development

The test suite uses a placeholder engine that draws a gradient, so it runs on any machine with no model:

```
pip install -e ".[dev]"
pytest
SITEPIX_BACKEND=mock sitepix "anything" --size og
```

## Status

Early release, version 0.1. If a command fails on your Mac, please open an issue and include the output of `sitepix doctor`.

## More

A full guide to running and training image models on a Mac, including how to train your own LoRA for use as a sitepix style, is at [aiappsapi.com](https://www.aiappsapi.com/articles/local-ai-image-mac/).

## License

MIT
