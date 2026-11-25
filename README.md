# NELL512-Turnip

Build Mesa Turnip untuk Adreno 6xx / 7xx, khususnya patch Android 10 (A10).

- Driver: Mesa Turnip (main branch)
- Target: Adreno 6xx / 7xx
- Emulator: Winlator, GameHub, dan emulator berbasis driver Turnip
- Cara install: impor file ZIP melalui menu Driver

## Download

Ambil build terbaru di tab **Actions** (artifact) atau **Releases**.
Build date: lihat nama file / deskripsi driver.

## Catatan

Build masih tahap pengujian dan dapat mengandung bug.
Dites di Poco F1, Android 10.

## Build Lokal

1. Ambil [turnip_builder.sh](turnip_builder.sh) di Linux.
2. Jalankan: `bash ./turnip_builder.sh`

## Modifikasi

- Menambahkan `shim.c` dan `patch.py`
- Mengedit `turnip_builder.sh`
- Kompatibilitas Android 10 (A10)

## Credits

- Original CI script: [ilhan-athn7/freedreno_turnip-CI](https://github.com/ilhan-athn7/freedreno_turnip-CI)
- Fork CI: [Weab-chan/freedreno_turnip-CI](https://github.com/Weab-chan/freedreno_turnip-CI)
- Build script: [StevenMXZ/Adreno-Tools-Drivers](https://github.com/StevenMXZ/Adreno-Tools-Drivers)
- Driver source: [Mesa](https://gitlab.freedesktop.org/mesa/mesa)
- Modified & built by NELL512

## References

- https://forum.xda-developers.com/t/getting-freedreno-turnip-mesa-vulkan-driver-on-a-poco-f3.4323871/
- https://gitlab.freedesktop.org/mesa/mesa/-/issues/6802

## License

- `patch.py`, `shim.c`: GPL-3.0 (lihat `LICENSE`)
- Driver hasil build: Mesa, lisensi MIT
