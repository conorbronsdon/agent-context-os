# Regenerates docs/assets/start-demo.gif — the /start session in the README.
#
#   docker run --rm -v "$PWD:/vhs" ghcr.io/charmbracelet/vhs docs/start-demo.tape
#
# or, with vhs installed locally, from the repo root:
#
#   vhs docs/start-demo.tape
#
# The session itself is scripted in docs/demo/start-session.sh — it reads no
# state and calls no model, so every render shows the same session. The GIF
# bytes are NOT reproducible run to run: real terminal timing plus the encoder
# shift the output by a few hundred bytes, so expect a small binary diff on a
# re-render even when nothing changed. Judge it by watching it, not by `cmp`.
#
# The tape stages that script as `claude` on PATH inside the recording, which
# is why the repo file keeps an honest name.

Output docs/assets/start-demo.gif

Set Shell "bash"
Set FontSize 13
Set Width 800
Set Height 480
Set Padding 10
Set TypingSpeed 70ms

Set Theme { "background": "#0d1117", "foreground": "#c9d1d9", "cursor": "#c9d1d9", "selection": "#264f78", "black": "#0d1117", "red": "#ff7b72", "green": "#3fb950", "yellow": "#e3b341", "blue": "#58a6ff", "magenta": "#bc8cff", "cyan": "#39c5cf", "white": "#c9d1d9", "brightBlack": "#7d8590", "brightRed": "#ffa198", "brightGreen": "#56d364", "brightYellow": "#e3b341", "brightBlue": "#79c0ff", "brightMagenta": "#d2a8ff", "brightCyan": "#56d4dd", "brightWhite": "#f0f6fc" }

Hide
Type "mkdir -p /tmp/vhsbin && cp docs/demo/start-session.sh /tmp/vhsbin/claude && chmod +x /tmp/vhsbin/claude" Enter
Type "export PATH=/tmp/vhsbin:$PATH" Enter
Type `export PS1='$ '` Enter
Type "clear" Enter
Show

Sleep 800ms
Type "claude"
Sleep 400ms
Enter

# start-session.sh paces its own output; this covers the full run plus a beat
# on the final prompt.
Sleep 8s
Sleep 4s
