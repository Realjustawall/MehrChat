"""Pinned recipe with cache and wheel-version checks."""
import os
from pathlib import Path
from pythonforandroid.recipes.cryptography import CryptographyRecipe as Upstream
class CryptographyRecipe(Upstream):
    version='50.0.2'
    def get_build_dir(self,arch):return super().get_build_dir(arch)+'-v'+self.version
    def should_build(self,arch):
        p=Path(self.ctx.get_python_install_dir(arch.arch))/'cryptography/__about__.py'
        return not (p.exists() and ('__version__ = "'+self.version+'"') in p.read_text())
    def install_wheel(self,arch,built_wheels):
        selected=[p for p in built_wheels if Path(p).name.startswith('cryptography-'+self.version+'-')]
        if not selected:raise RuntimeError('Pinned native wheel was not built')
        return super().install_wheel(arch,selected)
    def get_recipe_env(self,arch,**kwargs):
        env=super().get_recipe_env(arch,**kwargs)
        for key in ('RUSTUP_HOME','CARGO_HOME','RUSTUP_TOOLCHAIN'):
            if key in os.environ:env[key]=os.environ[key]
        return env
recipe=CryptographyRecipe()
