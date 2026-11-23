"""Image engines. The real one drives the mflux command line tools, the mock one
draws a placeholder so everything else can be tested on any machine."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import home_dir


class BackendError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelSpec:
    name: str
    command: str
    steps: int
    # Free memory wanted before a run starts, when loading a saved 8 bit copy.
    # z-image-turbo comes from the mflux docs (7.5 GB measured peak at 1024x1024),
    # the others are estimates from model size.
    need_gb: float
    measured: bool
    license_note: str


MODELS = {
    "z-image-turbo": ModelSpec(
        "z-image-turbo", "mflux-generate-z-image-turbo", 9, 9.0, True,
        "see the Tongyi-MAI/Z-Image-Turbo model card",
    ),
    "flux2-klein-4b": ModelSpec(
        "flux2-klein-4b", "mflux-generate-flux2", 4, 9.0, False,
        "see the black-forest-labs/FLUX.2-klein-4B model card",
    ),
    "flux2-klein-9b": ModelSpec(
        "flux2-klein-9b", "mflux-generate-flux2", 4, 14.0, False,
        "see the black-forest-labs/FLUX.2-klein-9B model card",
    ),
}

QUANTIZE = 8


def model_spec(name: str) -> ModelSpec:
    if name not in MODELS:
        raise BackendError(f"unknown model '{name}', supported: {', '.join(MODELS)}")
    return MODELS[name]


def saved_model_dir(name: str) -> Path:
    return home_dir() / "models" / f"{name}-q{QUANTIZE}"


def has_saved_model(name: str) -> bool:
    folder = saved_model_dir(name)
    return folder.is_dir() and any(folder.iterdir())


def find_executable(name: str) -> str | None:
    """Look beside the running Python first, since a tool install keeps the
    mflux commands inside its own environment and off the PATH."""
    beside = Path(sys.executable).parent / name
    if beside.is_file():
        return str(beside)
    return shutil.which(name)


@dataclass
class Job:
    prompt: str
    width: int
    height: int
    seed: int
    model: str
    out_png: Path
    lora: str = ""
    lora_scale: float = 1.0
    low_ram: bool = False


class MfluxBackend:
    name = "mflux"

    def build_command(self, job: Job) -> list[str]:
        spec = model_spec(job.model)
        exe = find_executable(spec.command)
        if not exe:
            raise BackendError(
                f"{spec.command} was not found. Install mflux with: uv tool install --upgrade mflux"
            )
        cmd = [exe]
        if has_saved_model(job.model):
            cmd += ["--model", str(saved_model_dir(job.model)), "--base-model", spec.name]
        else:
            cmd += ["--model", spec.name, "--quantize", str(QUANTIZE)]
        cmd += [
            "--prompt", job.prompt,
            "--width", str(job.width),
            "--height", str(job.height),
            "--steps", str(spec.steps),
            "--seed", str(job.seed),
            "--output", str(job.out_png),
        ]
        if job.lora:
            cmd += ["--lora-paths", job.lora, "--lora-scales", str(job.lora_scale)]
        if job.low_ram:
            cmd.append("--low-ram")
        return cmd

    def generate(self, job: Job, log=None) -> None:
        cmd = self.build_command(job)
        if log:
            log("running " + Path(cmd[0]).name)
        # The engine's progress output goes to our stderr, never stdout,
        # so stdout stays clean for the caller.
        result = subprocess.run(cmd, stdout=sys.stderr)
        if result.returncode != 0:
            hint = " See the engine output above."
            if result.returncode in (-9, 137):
                hint = " The process was killed, which usually means the Mac ran out of memory."
            raise BackendError(f"{Path(cmd[0]).name} failed with exit code {result.returncode}.{hint}")
        if not job.out_png.exists():
            raise BackendError("the image engine finished without writing an image")

    def save_model(self, model: str, log=None) -> Path:
        spec = model_spec(model)
        exe = find_executable("mflux-save")
        if not exe:
            raise BackendError("mflux-save was not found. Install mflux with: uv tool install --upgrade mflux")
        target = saved_model_dir(model)
        if has_saved_model(model):
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        cmd = [exe, "--path", str(target), "--model", spec.name, "--quantize", str(QUANTIZE)]
        if log:
            log(f"saving an {QUANTIZE} bit copy of {model} to {target} (downloads the model on first use)")
        result = subprocess.run(cmd, stdout=sys.stderr)
        if result.returncode != 0:
            raise BackendError(f"mflux-save failed with exit code {result.returncode}")
        return target


class MockBackend:
    """Draws a gradient whose colors come from the prompt. No model, no Mac needed."""

    name = "mock"

    def generate(self, job: Job, log=None) -> None:
        from PIL import Image

        digest = hashlib.sha256(f"{job.prompt}|{job.seed}".encode()).digest()
        start, end = digest[0:3], digest[3:6]
        row = Image.new("RGB", (job.width, 1))
        pixels = row.load()
        span = max(1, job.width - 1)
        for x in range(job.width):
            t = x / span
            pixels[x, 0] = tuple(int(start[i] + (end[i] - start[i]) * t) for i in range(3))
        row.resize((job.width, job.height)).save(job.out_png, "PNG")

    def save_model(self, model: str, log=None) -> Path:
        model_spec(model)
        return saved_model_dir(model)


def get_backend(name: str):
    if name == "mflux":
        return MfluxBackend()
    if name == "mock":
        return MockBackend()
    raise BackendError(f"unknown backend '{name}', use mflux or mock")
