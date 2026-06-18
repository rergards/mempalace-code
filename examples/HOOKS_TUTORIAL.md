# How to Use mempalace-code Hooks (Auto-Save)

mempalace-code hooks are a legacy Claude Code "Auto-Save" feature. For Codex, Gemini, Cursor, and other agents, use MCP + `docs/LLM_USAGE_RULES.md` instead.

### 1. What are these hooks?
* **Save Hook** (`mempal_save_hook.sh`): Saves new facts and decisions every 15 messages.
* **PreCompact Hook** (`mempal_precompact_hook.sh`): Saves your context right before the AI's memory window fills up.

### 2. Setup for Claude Code
Add this to your configuration file to enable automatic background saving:

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "", 
        "hooks": [{"type": "command", "command": "./hooks/mempal_save_hook.sh"}]
      }
    ],
    "PreCompact": [
      {
        "matcher": "", 
        "hooks": [{"type": "command", "command": "./hooks/mempal_precompact_hook.sh"}]
      }
    ]
  }
}
