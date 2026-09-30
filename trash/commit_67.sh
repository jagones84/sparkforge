#!/bin/bash
cd /home/jagones/Repositories/sparkpulse-app
git add app/src/main/java/com/jagones/sparkpulse/ForgeScreen.kt app/build.gradle.kts
cat > /tmp/jag67msg <<'MSGEOF'
JAG-67: jump-to-latest pill in the chat + drop the redundant trace "X"

Chat: instead of always force-scrolling to the last message, follow new messages
only while the user is already at the bottom (like modern chats); when they have
scrolled up, a "ultimo" pill appears and animates straight to the latest message,
so no more long manual scroll.

Panels: the AGENTE/TRACE header was already a clickable open/close toggle, so the
second "X" box beside it was redundant (and no longer needed) -- removed.

v1.6.14 (versionCode 22). Build + install OK on oneplus-15r, unit tests green.
MSGEOF
git commit -F /tmp/jag67msg
git log -1 --oneline
