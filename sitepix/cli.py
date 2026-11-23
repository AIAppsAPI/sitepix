"""Command line entry point. `sitepix "a prompt"` is the short form of `sitepix generate`."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__, memory
from .backend import MODELS, BackendError, find_executable, get_backend, has_saved_model, saved_model_dir
from .config import ConfigError, config_path, load_config, write_sample_config
from .core import Request, SitepixError, generate
from .presets import SIZE_NOTES, SIZES, SizeError

COMMANDS = {"generate", "serve", "setup", "doctor", "sizes", "styles", "init"}


def _add_generate_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("prompt", help="what the image should show")
    parser.add_argument("-o", "--output", default="", help="output file, or a folder to name the file from the prompt")
    parser.add_argument("-s", "--size", default="hero", help="preset name or WIDTHxHEIGHT (default: hero)")
    parser.add_argument("-f", "--format", default="", choices=["", "webp", "png", "jpg"], help="output format (default: webp)")
    parser.add_argument("-q", "--quality", type=int, default=0, help="1 to 100 for webp and jpg (default: 82)")
    parser.add_argument("--max-kb", type=int, default=0, help="lower the quality until the file is under this size")
    parser.add_argument("--seed", type=int, default=0, help="fixed seed to repeat a result (default: random)")
    parser.add_argument("--style", default="", help="style name from your config file")
    parser.add_argument("--model", default="", choices=[""] + list(MODELS), help="model to use (default: z-image-turbo)")
    parser.add_argument("--backend", default="", choices=["", "mflux", "mock"], help="mock draws a placeholder with no model")
    parser.add_argument("--low-ram", action="store_true", help="trade speed for lower memory use")
    parser.add_argument("--force", action="store_true", help="run even when free memory looks too low")
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sitepix",
        description="Generate website ready images with a local model on Apple Silicon.",
    )
    parser.add_argument("--version", action="version", version=f"sitepix {__version__}")
    sub = parser.add_subparsers(dest="command")

    _add_generate_args(sub.add_parser("generate", help="generate an image (the default command)"))
    sub.add_parser("serve", help="run as an MCP server over stdio, for AI assistants")
    setup = sub.add_parser("setup", help="save a quantized copy of a model for low memory use")
    setup.add_argument("--model", default="", choices=[""] + list(MODELS))
    sub.add_parser("doctor", help="check that this machine is ready")
    sub.add_parser("sizes", help="list the size presets")
    sub.add_parser("styles", help="list the styles in your config file")
    sub.add_parser("init", help="write a sample config file")
    return parser


def cmd_generate(args) -> int:
    request = Request(
        prompt=args.prompt, size=args.size, output=args.output, format=args.format,
        quality=args.quality, max_kb=args.max_kb, seed=args.seed, style=args.style,
        model=args.model, backend=args.backend, force=args.force, low_ram=args.low_ram,
    )
    result = generate(request)
    # The only thing on stdout is the answer, so callers can capture it directly.
    print(json.dumps(result.to_dict(), indent=2) if args.json else result.path)
    return 0


def cmd_setup(args) -> int:
    model = args.model or load_config().model
    path = get_backend("mflux").save_model(model, log=lambda m: print(f"sitepix: {m}", file=sys.stderr))
    print(path)
    return 0


def cmd_doctor(_args) -> int:
    config = load_config()
    checks = []

    def add(ok, label, detail):
        checks.append((ok, label, detail))

    add(memory.is_apple_silicon(), "Apple Silicon Mac", "required for the mflux engine")
    add(sys.version_info >= (3, 11), "Python 3.11 or newer", sys.version.split()[0])
    total, available = memory.total_bytes(), memory.available_bytes()
    add(total is None or total >= 16 * memory.GB, "16 GB of memory or more", memory.format_gb(total))
    add(True, "memory available now", memory.format_gb(available))
    for name in ("mflux-generate-z-image-turbo", "mflux-save"):
        add(find_executable(name) is not None, name, find_executable(name) or "not found, install mflux")
    add(has_saved_model(config.model), f"saved copy of {config.model}",
        str(saved_model_dir(config.model)) if has_saved_model(config.model) else "missing, run: sitepix setup")
    try:
        import mcp  # noqa: F401
        add(True, "MCP library", "installed")
    except ImportError:
        add(False, "MCP library", "missing, 'sitepix serve' will not work")
    add(True, "config file", str(config_path()) + ("" if config_path().exists() else " (not created, defaults in use)"))

    for ok, label, detail in checks:
        print(f"[{'ok' if ok else '!!'}] {label}: {detail}")
    return 0 if all(ok for ok, _, _ in checks) else 1


def cmd_sizes(_args) -> int:
    for name, (width, height) in SIZES.items():
        print(f"{name:<9} {f'{width}x{height}':<10} {SIZE_NOTES[name]}")
    print("or any explicit size, for example 1200x400")
    return 0


def cmd_styles(_args) -> int:
    config = load_config()
    if not config.styles:
        print(f"no styles defined, add them to {config_path()} (run 'sitepix init' for a sample)")
        return 0
    for style in config.styles.values():
        extras = [part for part in (style.prefix, style.suffix) if part]
        if style.lora:
            extras.append(f"lora {style.lora} at {style.lora_scale:g}")
        print(f"{style.name}: " + " | ".join(extras))
    return 0


def cmd_init(_args) -> int:
    print(write_sample_config())
    return 0


def cmd_serve(_args) -> int:
    from .mcp_server import run

    run()
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # `sitepix "a red fox"` with no command name means generate.
    if argv and argv[0] not in COMMANDS and argv[0] not in ("-h", "--help", "--version"):
        argv.insert(0, "generate")
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    handler = {
        "generate": cmd_generate, "serve": cmd_serve, "setup": cmd_setup, "doctor": cmd_doctor,
        "sizes": cmd_sizes, "styles": cmd_styles, "init": cmd_init,
    }[args.command]
    try:
        return handler(args)
    except (SitepixError, BackendError, ConfigError, SizeError) as exc:
        print(f"sitepix: error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("sitepix: stopped", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
