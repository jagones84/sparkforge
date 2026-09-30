#!/bin/bash
set -e
rm -f /home/jagones/shot_pulse.png /home/jagones/shot_forge.png /home/jagones/shot_cards.png \
      /home/jagones/shot_agent.png /home/jagones/ui.xml /home/jagones/ui2.xml \
      /home/jagones/ui3.xml /home/jagones/ui4.xml /home/jagones/d.xml /home/jagones/f.xml 2>/dev/null || true
cd /home/jagones/Repositories/sparkpulse-app
git add app/src/main/java/com/jagones/sparkpulse/ForgeScreen.kt app/build.gradle.kts
git commit -m "JAG-62: tool-call details in a lateral drawer (v1.6.11)

The inline expand-in-place made the transcript jump around. A tap on a tool
card now opens a right-edge drawer (slide-in + scrim) showing input/output/
error, closed by the > arrow, a scrim tap. The card stays compact (2-line
summary + chevron)."
git log --oneline -n 3
