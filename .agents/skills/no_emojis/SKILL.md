---
name: no_emojis
description: Strict behavioral rule to completely avoid using emojis in UI elements, chat responses, or any output.
---

# No Emojis Skill

The user explicitly requested **NOT** to use emojis (e.g. 🎙️, ✨, ❌, 😊) anywhere in the application's UI or in your chat responses. 

## Strict Rules:
1. **Never use emojis in chat responses:** When communicating with the user, do not add emojis to your messages.
2. **Never use emojis in Streamlit UI:** For Streamlit UI elements (like buttons, headers, status messages), use Material Icons (`:material/icon_name:`, `<span class="material-symbols-rounded">icon_name</span>`) instead of emojis.
3. **Double-check UI strings:** Always verify that your strings do not contain hidden emojis. If you need a visual indicator, rely exclusively on CSS styling and Material Icons.

Failure to follow this rule violates a direct user directive.
