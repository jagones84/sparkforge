#!/usr/bin/env bash
# Rebuild the vendored WebUI editor libs (CodeMirror 6 + marked + DOMPurify).
# One-off build; needs node >= 18, npm and network access. The generated files
# under ./vendor are committed, so this is only run to bump the libraries.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="$HERE/vendor"
BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT
mkdir -p "$OUT"
cd "$BUILD"
printf '{"private":true,"type":"module"}\n' > package.json

npm install --no-audit --no-fund \
  @codemirror/state @codemirror/view @codemirror/commands @codemirror/language \
  @codemirror/search @codemirror/autocomplete \
  @codemirror/lang-javascript @codemirror/lang-python @codemirror/lang-json \
  @codemirror/lang-markdown @codemirror/lang-html @codemirror/lang-css \
  @codemirror/lang-yaml @codemirror/theme-one-dark marked dompurify esbuild

cat > cm-entry.js <<'EOF'
export { EditorState, Compartment } from "@codemirror/state";
export { EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter, drawSelection, dropCursor, rectangularSelection, crosshairCursor, highlightSpecialChars } from "@codemirror/view";
export { defaultKeymap, history, historyKeymap, indentWithTab, undo, redo } from "@codemirror/commands";
export { syntaxHighlighting, defaultHighlightStyle, bracketMatching, indentOnInput, foldGutter, foldKeymap, LanguageSupport, StreamLanguage } from "@codemirror/language";
export { searchKeymap, highlightSelectionMatches, openSearchPanel } from "@codemirror/search";
export { autocompletion, completionKeymap, closeBrackets, closeBracketsKeymap } from "@codemirror/autocomplete";
export { javascript } from "@codemirror/lang-javascript";
export { python } from "@codemirror/lang-python";
export { json } from "@codemirror/lang-json";
export { markdown } from "@codemirror/lang-markdown";
export { html } from "@codemirror/lang-html";
export { css } from "@codemirror/lang-css";
export { yaml } from "@codemirror/lang-yaml";
export { oneDark } from "@codemirror/theme-one-dark";
EOF

cat > marked-entry.js <<'EOF'
import { marked } from "marked";
window.marked = marked;
EOF

cat > purify-entry.js <<'EOF'
import DOMPurify from "dompurify";
window.DOMPurify = DOMPurify;
EOF

npx esbuild cm-entry.js --bundle --format=esm --minify --outfile="$OUT/codemirror.js"
npx esbuild marked-entry.js --bundle --format=iife --minify --outfile="$OUT/marked.min.js"
npx esbuild purify-entry.js --bundle --format=iife --minify --outfile="$OUT/purify.min.js"
ls -l "$OUT"
