# VIPI Showcase – source

60-second motion graphics video (1920×1080, 30 fps) in the VIPI brand: monochrome, pixel logo, Geist / Geist Mono. Everything is drawn on a canvas; the soundtrack is synthesized with numpy.

```bash
npm i playwright @fontsource/geist-sans @fontsource/geist-mono
node renderframes.js 4          # renders frames/f00000.png … f01799.png
python3 audio.py                # writes audio.wav
ffmpeg -framerate 30 -i frames/f%05d.png -i audio.wav -c:v libx264 -crf 16 -pix_fmt yuv420p \
  -c:a aac -b:a 256k -af loudnorm=I=-14:TP=-1.5 -shortest VIPI_Showcase.mp4
```

Copy and timings live in `scenes.js` (one function per scene, `sX(t)`); colors, helpers and the pixel logo (`drawLogo`) in `lib.js`.
`node stills.js 12.5 30 44` renders single frames for checking.
