[app]
title = Blue Orb Survival Arena
package.name = blueorb
package.domain = org.jhonny
source.dir = .
source.include_exts = py,ttf,png,json
source.exclude_dirs = SAVES,bin,.github,.buildozer
version = 2.4
requirements = python3,pygame
orientation = landscape
fullscreen = 1
android.permissions = INTERNET
android.api = 33
android.minapi = 21
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
android.wakelock = True
p4a.bootstrap = sdl2
p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 1
