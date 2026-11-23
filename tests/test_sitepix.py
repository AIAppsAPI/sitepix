import json

import pytest
from PIL import Image

from sitepix import cli, core, memory, presets
from sitepix.backend import Job, MfluxBackend, get_backend
from sitepix.config import Config, Style, load_config, write_sample_config

VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                              100000.
Pages active:                           1500000.
Pages inactive:                          200000.
Pages speculative:                        50000.
Pages throttled:                              0.
Pages wired down:                        300000.
Pages purgeable:                          10000.
Swapouts:                                     0.
"""


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SITEPIX_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SITEPIX_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("SITEPIX_BACKEND", "mock")
    monkeypatch.chdir(tmp_path)


def test_parse_size_presets_and_explicit():
    assert presets.parse_size("hero") == (1600, 900)
    assert presets.parse_size("1200x630") == (1200, 630)
    assert presets.parse_size(" 800 X 600 ") == (800, 600)
    with pytest.raises(presets.SizeError):
        presets.parse_size("huge")
    with pytest.raises(presets.SizeError):
        presets.parse_size("9000x9000")


@pytest.mark.parametrize("name", list(presets.SIZES))
def test_plan_generation_covers_target_in_range(name):
    width, height = presets.SIZES[name]
    gen_w, gen_h = presets.plan_generation(width, height)
    assert gen_w % 16 == 0 and gen_h % 16 == 0
    assert gen_w >= 256 and gen_h >= 256
    assert gen_w * gen_h <= presets.MAX_PIXELS * 1.1
    # same shape as the target within one rounding step, so the crop is small
    assert abs(gen_w / gen_h - width / height) < 0.08


def test_plan_generation_scales_large_and_small():
    assert presets.plan_generation(1600, 900) == (1600, 912)
    big_w, big_h = presets.plan_generation(3840, 2160)
    assert big_w < 3840 and big_w * big_h <= presets.MAX_PIXELS * 1.1
    small_w, small_h = presets.plan_generation(640, 360)
    assert small_w > 640 and small_w * small_h >= presets.MIN_PIXELS


def test_parse_vm_stat():
    assert memory.parse_vm_stat(VM_STAT) == (100000 + 200000 + 50000 + 10000) * 16384
    assert memory.parse_vm_stat("garbage") is None


def test_slugify_and_output_naming(tmp_path):
    assert core.slugify("A Red Fox, in the SNOW! at dawn near a lake") == "a-red-fox-in-the-snow"
    assert core.slugify("!!!") == "image"
    first = core.resolve_output(str(tmp_path), ".", "red fox", "webp")
    assert first.name == "red-fox.webp"
    first.write_bytes(b"x")
    assert core.resolve_output(str(tmp_path), ".", "red fox", "webp").name == "red-fox-2.webp"
    explicit = core.resolve_output(str(tmp_path / "a" / "hero.png"), ".", "red fox", "webp")
    assert explicit.name == "hero.png"


def test_generate_writes_exact_size_webp(tmp_path):
    result = core.generate(core.Request(prompt="a red fox in the snow", size="og", output=str(tmp_path)))
    assert result.path.endswith("a-red-fox-in-the-snow.webp")
    with Image.open(result.path) as image:
        assert image.size == (1200, 630)
        assert image.format == "WEBP"
    assert result.backend == "mock" and result.seed > 0 and result.bytes > 0


def test_generate_formats_and_extension_wins(tmp_path):
    out = tmp_path / "nested" / "pic.jpg"
    result = core.generate(core.Request(prompt="lighthouse", size="640x360", output=str(out), format="png"))
    with Image.open(out) as image:
        assert image.format == "JPEG" and image.size == (640, 360)
    assert result.format == "jpg"
    png = core.generate(core.Request(prompt="lighthouse", size="icon", output=str(tmp_path), format="png"))
    with Image.open(png.path) as image:
        assert image.format == "PNG" and image.size == (512, 512)


def test_same_seed_same_image(tmp_path):
    a = core.generate(core.Request(prompt="harbor", size="icon", output=str(tmp_path / "a.png"), seed=5))
    b = core.generate(core.Request(prompt="harbor", size="icon", output=str(tmp_path / "b.png"), seed=5))
    assert open(a.path, "rb").read() == open(b.path, "rb").read()


def test_max_kb_lowers_quality(tmp_path):
    big = core.generate(core.Request(prompt="noise", size="hero", output=str(tmp_path / "big.jpg"), quality=95))
    small = core.generate(
        core.Request(prompt="noise", size="hero", output=str(tmp_path / "small.jpg"), quality=95, max_kb=1, seed=big.seed)
    )
    assert small.bytes <= big.bytes


def test_bad_inputs(tmp_path):
    with pytest.raises(core.SitepixError):
        core.generate(core.Request(prompt="   "))
    with pytest.raises(core.SitepixError):
        core.generate(core.Request(prompt="x", format="gif"))
    with pytest.raises(Exception):
        core.generate(core.Request(prompt="x", model="nope"))


def test_style_applies_prompt_and_lora(tmp_path):
    config = Config(styles={"flat": Style(name="flat", prefix="zxq style", suffix="white background", lora="~/l.safetensors", lora_scale=0.8)})
    result = core.generate(core.Request(prompt="a fox", size="icon", output=str(tmp_path), style="flat"), config)
    assert result.prompt == "zxq style, a fox, white background"
    with pytest.raises(Exception):
        core.generate(core.Request(prompt="a fox", style="missing"), config)


def test_config_roundtrip(tmp_path):
    path = write_sample_config()
    config = load_config(path)
    assert config.model == "z-image-turbo" and "flat" in config.styles
    path.write_text("{not json")
    with pytest.raises(Exception):
        load_config(path)


def test_mflux_command_from_hub(tmp_path, monkeypatch):
    monkeypatch.setattr("sitepix.backend.find_executable", lambda name: f"/bin/{name}")
    job = Job(prompt="a fox", width=1280, height=720, seed=7, model="z-image-turbo", out_png=tmp_path / "o.png")
    cmd = MfluxBackend().build_command(job)
    assert cmd[0] == "/bin/mflux-generate-z-image-turbo"
    assert cmd[cmd.index("--model") + 1] == "z-image-turbo"
    assert cmd[cmd.index("--quantize") + 1] == "8"
    assert cmd[cmd.index("--steps") + 1] == "9"
    assert cmd[cmd.index("--width") + 1] == "1280" and cmd[cmd.index("--seed") + 1] == "7"
    assert "--base-model" not in cmd and "--lora-paths" not in cmd


def test_mflux_command_with_saved_model_and_lora(tmp_path, monkeypatch):
    from sitepix.backend import saved_model_dir

    monkeypatch.setattr("sitepix.backend.find_executable", lambda name: f"/bin/{name}")
    folder = saved_model_dir("flux2-klein-4b")
    folder.mkdir(parents=True)
    (folder / "weights.safetensors").write_bytes(b"x")
    job = Job(prompt="p", width=1024, height=1024, seed=1, model="flux2-klein-4b", out_png=tmp_path / "o.png",
              lora="/l.safetensors", lora_scale=0.7, low_ram=True)
    cmd = MfluxBackend().build_command(job)
    assert cmd[0] == "/bin/mflux-generate-flux2"
    assert cmd[cmd.index("--model") + 1] == str(folder)
    assert cmd[cmd.index("--base-model") + 1] == "flux2-klein-4b"
    assert "--quantize" not in cmd
    assert cmd[cmd.index("--lora-scales") + 1] == "0.7" and cmd[-1] == "--low-ram"


def test_mflux_missing_gives_install_hint(tmp_path, monkeypatch):
    monkeypatch.setattr("sitepix.backend.find_executable", lambda name: None)
    job = Job(prompt="p", width=512, height=512, seed=1, model="z-image-turbo", out_png=tmp_path / "o.png")
    with pytest.raises(Exception, match="uv tool install"):
        MfluxBackend().build_command(job)


def test_real_backend_refuses_off_mac(monkeypatch):
    monkeypatch.setattr(memory, "is_apple_silicon", lambda: False)
    with pytest.raises(core.SitepixError, match="Apple Silicon"):
        core.generate(core.Request(prompt="x", backend="mflux"))


def test_memory_gate(monkeypatch):
    monkeypatch.setattr(memory, "is_apple_silicon", lambda: True)
    monkeypatch.setattr(core, "has_saved_model", lambda model: True)
    monkeypatch.setattr(memory, "available_bytes", lambda: 4 * memory.GB)
    with pytest.raises(core.SitepixError, match="4.0 GB"):
        core.check_memory("z-image-turbo", "mflux", Config(), force=False)
    core.check_memory("z-image-turbo", "mflux", Config(), force=True)
    core.check_memory("z-image-turbo", "mflux", Config(min_free_gb=2), force=False)
    monkeypatch.setattr(memory, "available_bytes", lambda: 32 * memory.GB)
    core.check_memory("z-image-turbo", "mflux", Config(), force=False)


def test_cli_prints_only_the_path(tmp_path, capsys):
    assert cli.main(["a green hill", "-s", "thumb", "-o", str(tmp_path)]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and out[0].endswith("a-green-hill.webp")


def test_cli_json_and_errors(tmp_path, capsys):
    assert cli.main(["generate", "a hill", "-s", "icon", "-o", str(tmp_path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["width"] == 512 and data["generated_size"] == "784x784"
    assert cli.main(["a hill", "-s", "nonsense"]) == 1
    assert "unknown size" in capsys.readouterr().err


def test_cli_sizes_styles_init(capsys):
    assert cli.main(["sizes"]) == 0 and "hero" in capsys.readouterr().out
    assert cli.main(["styles"]) == 0 and "no styles" in capsys.readouterr().out
    assert cli.main(["init"]) == 0
    capsys.readouterr()
    assert cli.main(["styles"]) == 0 and "flat" in capsys.readouterr().out
    assert cli.main(["init"]) == 1


def test_mcp_tools(tmp_path):
    from sitepix import mcp_server

    message = mcp_server.generate_image("a small boat", size="icon", output=str(tmp_path))
    assert message.startswith("Saved ") and "512x512 webp" in message
    assert mcp_server.generate_image("x", size="bogus").startswith("Error:")
    assert "hero: 1600x900" in mcp_server.list_options()
    server = mcp_server.build_server()
    assert server.name == "sitepix"


def test_mock_backend_lookup():
    assert get_backend("mock").name == "mock"
    with pytest.raises(Exception):
        get_backend("other")
