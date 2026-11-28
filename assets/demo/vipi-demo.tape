# Records assets/demo/vipi-demo.gif with VHS (https://github.com/charmbracelet/vhs).
# Run from the repository root after `vipi setup --ocr-mode balanced`:
#   vhs assets/demo/vipi-demo.tape
# The scan is real; re-record whenever the CLI output changes.
#
# The README GIF shortens the wait while the scan runs but keeps the run
# percentage climbing. VHS records in real time; afterwards keep the first 8 s,
# play the wait until the result 6x faster and keep the result from its first
# frame (45.9 s in the 0.22.0 recording):
#   ffmpeg -i assets/demo/vipi-demo.gif -filter_complex \
#     "[0]trim=0:8,setpts=PTS-STARTPTS[a];[0]trim=8:45.9,setpts=(PTS-STARTPTS)/6[b];[0]trim=start=45.9,setpts=PTS-STARTPTS[c];[a][b][c]concat=n=3:v=1,fps=25,split[x][y];[x]palettegen[p];[y][p]paletteuse=dither=none" \
#     -loop 0 cut.gif && mv cut.gif assets/demo/vipi-demo.gif

Output assets/demo/vipi-demo.gif

Require vipi

Set Shell zsh
Set FontSize 18
Set Width 1200
Set Height 640
Set Padding 24
Set TypingSpeed 40ms

# Use the project environment if there is one (VHS starts a fresh shell, so an
# activated venv is not inherited) and hide third-party model-loading progress bars.
Hide
Type "[ -f .venv/bin/activate ] && source .venv/bin/activate"
Enter
Type "export HF_HUB_DISABLE_PROGRESS_BARS=1 TRANSFORMERS_VERBOSITY=error"
Enter
# Scan a copy in a short folder so the recording shows no personal paths.
Type "mkdir -p /tmp/vipi-demo && cp examples/*.png /tmp/vipi-demo/ && cd /tmp/vipi-demo"
Enter
Type "PROMPT='$ '"
Enter
Type "clear"
Enter
Show

Type "vipi scan hidden-injection.png --ocr-mode balanced --verbose"
Sleep 500ms
Enter

# Local balanced scans of one image take about 20-40 s on Apple Silicon.
Wait+Screen@120s /images completed/
Sleep 4s
