"""The one function everything else calls: turn a request into a finished image file."""

from __future__ import annotations

import contextlib
import os
import re
import secrets
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from . import memory
from .backend import BackendError, Job, get_backend, has_saved_model, model_spec
from .config import Config, load_config, home_dir
from .presets import parse_size, plan_generation

FORMATS = {"webp": "WEBP", "png": "PNG", "jpg": "JPEG", "jpeg": "JPEG"}
MAX_PROMPT_CHARS = 2000


class SitepixError(RuntimeError):
    pass


@dataclass
class Request:
    prompt: str
    size: str = "hero"
    output: str = ""
    format: str = ""
    quality: int = 0
    max_kb: int = 0
    seed: int = 0
    style: str = ""
    model: str = ""
    backend: str = ""
    force: bool = False
    low_ram: bool = False


@dataclass
class Result:
    path: str
    width: int
    height: int
    bytes: int
    format: str
    seed: int
    model: str
    backend: str
    generated_size: str
    seconds: float
    prompt: str

    def to_dict(self) -> dict:
        return asdict(self)


def _log(message: str) -> None:
    print(f"sitepix: {message}", file=sys.stderr, flush=True)


def slugify(text: str, max_words: int = 6, max_chars: int = 60) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    slug = "-".join(words[:max_words])[:max_chars].strip("-")
    return slug or "image"


def resolve_output(output: str, default_dir: str, prompt: str, ext: str) -> Path:
    """An output with a file extension is used as given. Anything else is a
    folder, and the file name comes from the prompt."""
    target = Path(output or default_dir or ".").expanduser()
    if target.suffix.lower().lstrip(".") in FORMATS:
        return target
    base = slugify(prompt)
    candidate = target / f"{base}.{ext}"
    counter = 2
    while candidate.exists():
        candidate = target / f"{base}-{counter}.{ext}"
        counter += 1
    return candidate


def check_memory(model: str, backend_name: str, config: Config, force: bool) -> None:
    if backend_name != "mflux":
        return
    if not memory.is_apple_silicon():
        raise SitepixError("the mflux engine needs a Mac with Apple Silicon (M1 or newer)")
    spec = model_spec(model)
    if not has_saved_model(model):
        _log(
            f"no saved copy of {model} found, loading from the download cache uses much more memory. "
            f"Run 'sitepix setup' once to fix that."
        )
        return
    need = config.min_free_gb if config.min_free_gb is not None else spec.need_gb
    available = memory.available_bytes()
    if available is None:
        return
    if available < need * memory.GB:
        message = (
            f"{memory.format_gb(available)} of memory is available and {model} wants about {need:g} GB. "
            f"Close some apps, or pass --force to run anyway."
        )
        if not force:
            raise SitepixError(message)
        _log(message + " Continuing because --force was given.")


@contextlib.contextmanager
def job_lock(timeout: float = 1800.0):
    """One generation at a time. Two at once do not go faster, they fight for memory."""
    import fcntl

    lock_path = home_dir() / "job.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "w")
    deadline = time.monotonic() + timeout
    announced = False
    try:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if not announced:
                    _log("another generation is running, waiting for it to finish")
                    announced = True
                if time.monotonic() > deadline:
                    raise SitepixError("timed out waiting for another generation to finish")
                time.sleep(1.0)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def finish_image(source: Path, target: Path, width: int, height: int, fmt: str, quality: int, max_kb: int) -> None:
    """Scale to cover the target size, center crop to it exactly, and encode."""
    from PIL import Image

    pil_format = FORMATS[fmt]
    with Image.open(source) as opened:
        image = opened.convert("RGB")
    scale = max(width / image.width, height / image.height)
    if scale != 1.0:
        new_size = (max(width, round(image.width * scale)), max(height, round(image.height * scale)))
        image = image.resize(new_size, Image.LANCZOS)
    left = (image.width - width) // 2
    top = (image.height - height) // 2
    image = image.crop((left, top, left + width, top + height))

    target.parent.mkdir(parents=True, exist_ok=True)
    if pil_format == "PNG":
        image.save(target, "PNG", optimize=True)
        return
    options = {"method": 6} if pil_format == "WEBP" else {"optimize": True, "progressive": True}
    current = quality
    while True:
        image.save(target, pil_format, quality=current, **options)
        if not max_kb or target.stat().st_size <= max_kb * 1024 or current <= 40:
            return
        current -= 6


def generate(request: Request, config: Config | None = None) -> Result:
    config = config or load_config()
    prompt = (request.prompt or "").strip()
    if not prompt:
        raise SitepixError("the prompt is empty")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise SitepixError(f"the prompt is longer than {MAX_PROMPT_CHARS} characters")

    style = config.style(request.style) if request.style else None
    model = request.model or (style.model if style and style.model else "") or config.model
    model_spec(model)
    backend_name = request.backend or os.environ.get("SITEPIX_BACKEND", "mflux")
    backend = get_backend(backend_name)

    fmt = (request.format or config.format).lower()
    if fmt not in FORMATS:
        raise SitepixError(f"unknown format '{fmt}', use webp, png or jpg")
    ext = "jpg" if fmt == "jpeg" else fmt
    quality = request.quality or config.quality
    if not 1 <= quality <= 100:
        raise SitepixError("quality must be between 1 and 100")

    width, height = parse_size(request.size)
    gen_width, gen_height = plan_generation(width, height)
    target = resolve_output(request.output, config.output_dir, prompt, ext)
    if target.suffix:
        fmt = target.suffix.lower().lstrip(".")
    seed = request.seed or secrets.randbelow(2**31 - 1) + 1
    full_prompt = style.apply(prompt) if style else prompt

    check_memory(model, backend_name, config, request.force)

    started = time.monotonic()
    with job_lock():
        with tempfile.TemporaryDirectory(prefix="sitepix-") as tmp:
            raw = Path(tmp) / "raw.png"
            job = Job(
                prompt=full_prompt,
                width=gen_width,
                height=gen_height,
                seed=seed,
                model=model,
                out_png=raw,
                lora=os.path.expanduser(style.lora) if style and style.lora else "",
                lora_scale=style.lora_scale if style else 1.0,
                low_ram=request.low_ram,
            )
            _log(f"generating {gen_width}x{gen_height} with {model}, seed {seed}")
            try:
                backend.generate(job, log=_log)
            except BackendError as exc:
                raise SitepixError(str(exc)) from exc
            finish_image(raw, target, width, height, fmt, quality, request.max_kb)

    return Result(
        path=str(target.resolve()),
        width=width,
        height=height,
        bytes=target.stat().st_size,
        format="jpg" if fmt == "jpeg" else fmt,
        seed=seed,
        model=model,
        backend=backend_name,
        generated_size=f"{gen_width}x{gen_height}",
        seconds=round(time.monotonic() - started, 1),
        prompt=full_prompt,
    )
