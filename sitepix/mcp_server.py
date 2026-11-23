"""MCP server. A thin layer: every tool calls the same core function the command line uses."""

from __future__ import annotations

from .config import ConfigError, load_config
from .core import Request, SitepixError, generate
from .presets import SIZE_NOTES, SIZES, SizeError


def generate_image(
    prompt: str,
    size: str = "hero",
    output: str = "",
    style: str = "",
    format: str = "webp",
    seed: int = 0,
) -> str:
    """Generate an image with a local model on this Mac and save it as a file.

    Use this when a task needs an image: a page header, a blog illustration,
    a social share image, a placeholder. Nothing is uploaded and there is no
    cost per image. A generation takes from several seconds to a couple of
    minutes, and only one runs at a time.

    Args:
        prompt: What the image should show, as a plain descriptive sentence.
            Name the subject, setting, lighting and style.
        size: A preset (hero 1600x900, og 1200x630, square 1024x1024,
            thumb 640x360, banner 1920x640, portrait 832x1216, icon 512x512)
            or an explicit WIDTHxHEIGHT such as 1200x400.
        output: Where to save. A path ending in .webp, .png or .jpg is used as
            given. A folder path gets a file named from the prompt. Empty uses
            the user's default folder.
        style: Optional style name from the user's config. Call list_options
            to see which exist.
        format: webp (default, smallest), png or jpg.
        seed: A fixed number to reproduce an image. 0 picks a random seed.

    Returns the absolute path of the saved file with its size and seed.
    """
    try:
        result = generate(Request(prompt=prompt, size=size, output=output, style=style, format=format, seed=seed))
    except (SitepixError, ConfigError, SizeError) as exc:
        return f"Error: {exc}"
    return (
        f"Saved {result.path} ({result.width}x{result.height} {result.format}, "
        f"{result.bytes // 1024} KB, seed {result.seed}, {result.seconds}s)"
    )


def list_options() -> str:
    """List the size presets and the user's named styles for generate_image."""
    lines = ["Sizes:"]
    for name, (width, height) in SIZES.items():
        lines.append(f"  {name}: {width}x{height}, {SIZE_NOTES[name]}")
    try:
        styles = load_config().styles
    except ConfigError as exc:
        return "\n".join(lines) + f"\nStyles: could not read config ({exc})"
    lines.append("Styles:")
    if not styles:
        lines.append("  none defined")
    for style in styles.values():
        lines.append(f"  {style.name}: " + (style.suffix or style.prefix or "custom LoRA"))
    return "\n".join(lines)


def build_server():
    # The MCP library renamed its server class in version 2, so accept either.
    try:
        from mcp.server.mcpserver import MCPServer as Server
    except ImportError:
        from mcp.server.fastmcp import FastMCP as Server

    server = Server("sitepix")
    server.tool()(generate_image)
    server.tool()(list_options)
    return server


def run() -> None:
    build_server().run()
