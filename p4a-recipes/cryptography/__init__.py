"""Pinned Rust extension linked to Android's embedded Python runtime."""

import os
from pathlib import Path
from pythonforandroid.recipes.cryptography import CryptographyRecipe as Upstream


class CryptographyRecipe(Upstream):
    version = "50.0.2"

    def get_build_dir(self, arch):
        return super().get_build_dir(arch) + "-v" + self.version + "-python-link1"

    def marker(self, arch):
        return (
            Path(self.ctx.get_python_install_dir(arch.arch))
            / "cryptography/_mehrchat_android_link_v1.txt"
        )

    def should_build(self, arch):
        marker = self.marker(arch)
        return not (marker.exists() and marker.read_text() == self.version)

    def install_wheel(self, arch, built_wheels):
        selected = [
            p
            for p in built_wheels
            if Path(p).name.startswith("cryptography-" + self.version + "-")
        ]
        if not selected:
            raise RuntimeError("Pinned native wheel was not built")
        result = super().install_wheel(arch, selected)
        self.marker(arch).write_text(self.version)
        return result

    def get_recipe_env(self, arch, **kwargs):
        env = super().get_recipe_env(arch, **kwargs)
        for key in ("RUSTUP_HOME", "CARGO_HOME", "RUSTUP_TOOLCHAIN"):
            if key in os.environ:
                env[key] = os.environ[key]
        python = self.ctx.python_recipe.major_minor_version_string
        # Android does not expose the interpreter's symbols globally to plugins.
        # Keep DT_NEEDED even when PyO3's extension-module feature omits linking.
        env["RUSTFLAGS"] += (
            " -C link-arg=-Wl,--no-as-needed"
            + " -C link-arg=-lpython"
            + python
            + " -C link-arg=-Wl,--as-needed"
            + " -C link-arg=-Wl,-z,max-page-size=16384"
        )
        return env


recipe = CryptographyRecipe()
