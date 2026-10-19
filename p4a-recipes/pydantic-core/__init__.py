import os
from pythonforandroid.recipe import RustCompiledComponentsRecipe
class PydanticcoreRecipe(RustCompiledComponentsRecipe):
    version='2.41.4'
    url='https://github.com/pydantic/pydantic-core/archive/refs/tags/v{version}.tar.gz'
    site_packages_name='pydantic_core'
    def get_recipe_env(self,arch,**kwargs):
        env=super().get_recipe_env(arch,**kwargs)
        for key in ('RUSTUP_HOME','CARGO_HOME','RUSTUP_TOOLCHAIN'):
            if key in os.environ:env[key]=os.environ[key]
        return env
recipe=PydanticcoreRecipe()
