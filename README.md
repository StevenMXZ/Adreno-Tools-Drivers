# NELL512-Turnip

Build Mesa Turnip untuk Adreno 6xx / 7xx, khususnya patch Android 10/A10.

- Driver: Mesa Turnip 27.0.0-devel
- Target: Adreno 6xx / 7xx
- Emulator: Winlator, GameHub, dan emulator berbasis driver Turnip
- Cara install: impor file ZIP melalui menu Driver

## Download
https://github.com/NELL512/NELL512-Turnip/releases

## Catatan
Build masih tahap pengujian dan dapat mengandung bug.

tes on Poco f1 android 10 

This is a bash script to build freedreno/turnip for android as an adrenotool package.
  
### To Build Locally
- Obtain the script [turnip_builder.sh](https://raw.githubusercontent.com/Weab-chan/freedreno_turnip-CI/main/turnip_builder.sh) on your linux environment. (visit the link and use ```CTRL + S``` keys)
- Execute script on linux terminal ```bash ./turnip_builder.sh```

### References

- https://forum.xda-developers.com/t/getting-freedreno-turnip-mesa-vulkan-driver-on-a-poco-f3.4323871/
- https://github.com/ilhan-athn7/freedreno_turnip-CI
- https://gitlab.freedesktop.org/mesa/mesa/-/issues/6802
## Credits
- Original CI script: ilhan-athn7/freedreno_turnip-CI
  https://github.com/ilhan-athn7/freedreno_turnip-CI
- Build script: StevenMXZ/Adreno-Tools-Drivers
  https://github.com/StevenMXZ/Adreno-Tools-Drivers
- Driver source: Mesa / Turnip
  https://gitlab.freedesktop.org/mesa/mesa
- Modified & built by NELL512
-Modifications:
Applied shim.c , patch.py and edited turnip_builder.sh
-**Android 10 (A10) compatibility**

Build date: November 25, 2026

License: GPL-3.0
