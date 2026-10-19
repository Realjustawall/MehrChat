[app]
title = Mehr
package.name = mehrchat
package.domain = org.mehrchat
source.dir = .
source.include_exts = py,ttf,txt,json
source.exclude_dirs = tests,dist,build,deploy,scripts,p4a-recipes,reports,.github,__pycache__
version = 0.2.0
requirements = python3==3.13.16,hostpython3==3.13.16,kivy==2.3.1,pynacl==1.6.2,arabic-reshaper==3.0.1,python-bidi==0.4.2,six,chardet==5.2.0,doubleratchet==1.3.0,noiseprotocol==0.3.1,cryptography==50.0.2,pydantic==2.12.3,pydantic-core==2.41.4,openssl==3.5.9,libsodium==1.0.22
orientation = portrait
fullscreen = 0
android.permissions = INTERNET
android.api = 35
android.minapi = 26
android.ndk = 28c
android.archs = arm64-v8a
android.accept_sdk_license = True
android.allow_backup = False
android.release_artifact = apk
p4a.branch = v2026.05.09
p4a.local_recipes = p4a-recipes
[buildozer]
log_level = 2
warn_on_root = 0
