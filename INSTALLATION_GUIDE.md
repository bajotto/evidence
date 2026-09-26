# Installation Guide: Standalone vs. Service Mode

This repo's protocol delivery works in two complementary modes. This guide explains what each one does, which to choose, and how to install and configure them.

## The two modes at a glance

| Aspect | Standalone | Service (MCP) |
|--------|-----------|---------------|
| **What it is** | Hooks or static rules injected per-session | One persistent process handling all requests |
| **How it runs** | Runs when your agent starts a session | Runs in the background (you start it once) |
| **Speed** | Fresh read every time (slightly slower) | Caches answer (slightly faster) |
| **Dependencies** | None — uses your agent's own hook/rule API | Requires Python 3.9+ to run the server |
| **Offline** | ✅ Works offline | ✅ Works offline (both local) |
| **Best for** | Single agent, single machine | Multiple agents sharing one server, or MCP-only agent |
| **Setup complexity** | Simple: one `install.sh` call | Simple: one `install.sh` call, plus start the server |

**Both modes read the same `SCIENTIFIC_PROTOCOL.md`. They do not conflict — you can run both at the same time.**

---

## Mode 1: Standalone (recommended for most projects)

### What happens

1. Your agent (Claude Code, Devin, Cursor, etc.) starts a session
2. A **hook** or **static rule** runs automatically
3. Reads `SCIENTIFIC_PROTOCOL.md` and extracts the current header
4. Injects the header into that session's context
5. Session ends, hook ends — no background process

### Pros
- ✅ Zero daemon to manage
- ✅ Always reads the latest protocol (never stale)
- ✅ Works completely offline
- ✅ No extra Python process
- ✅ Same tool.yaml or rules config already familiar to you

### Cons
- ⊘ Slightly slower (file read + parse per session)
- ⊘ Each agent needs its own adapter (claude/, devin/, cursor/, etc.)

### Installation

**For Claude Code or Devin:**
```bash
cd /path/to/this/repo
./claude/install.sh /path/to/your/project
# or
./devin/install.sh /path/to/your/project
```

**For Cursor, Codex, or Trae:**
```bash
cd /path/to/this/repo
./cursor/install.sh /path/to/your/project
# or ./codex/install.sh /path/to/your/project
# or ./trae/install.sh /path/to/your/project
```

Each script:
- Copies the method docs to your project
- Sets up the hook (Claude, Devin) or static rules (Cursor, Codex, Trae)
- Creates `SCIENTIFIC_PROTOCOL.md` from the template if you don't have one
- Is **idempotent** — safe to run multiple times

### Verification

```bash
# Claude Code
grep -r "protocol-header.sh" ~/.claude/hooks/
# or check your IDE's hook config

# Cursor
cat /path/to/your/project/.cursor/rules/scientific-method.mdc | head -5
# should start with: ---
# alwaysApply: true

# Devin / Codex / Trae
# Similar static-rule checks per tool
```

### To disable standalone mode later

**Claude Code:**
```bash
rm ~/.claude/hooks/protocol-header.sh ~/.claude/hooks/session-start-protocol-global.sh
```

**Devin:**
```bash
rm ~/.devin/hooks/protocol-header.sh ~/.devin/hooks/session-start-protocol-devin.sh
```

**Cursor:**
```bash
rm /path/to/your/project/.cursor/rules/scientific-method.mdc
```

**Codex:**
```bash
rm /path/to/your/project/AGENTS.md  # if it was only used for the method
```

**Trae:**
```bash
rm /path/to/your/project/.trae/rules/scientific-method.md
```

---

## Mode 2: Service (MCP) — for shared servers or multiple agents

### What happens

1. You **start the MCP server once** (or keep it running):
   ```bash
   python3 /path/to/repo/method/service/protocol_mcp_server.py
   ```
2. Your **MCP-capable agent** (Cursor, Codex CLI, Trae, or Claude Desktop) **registers** the server in its config
3. Whenever the agent needs the protocol, it **calls the server** instead of re-reading the file
4. The server **responds immediately** with the current header or search results
5. Server keeps running until you stop it

### Pros
- ✅ One process for multiple agents (on the same machine)
- ✅ Slightly faster (answers are immediate, no re-parsing)
- ✅ True "service" architecture — agents never call hooks directly
- ✅ Easy to extend (add more tools to the MCP server)

### Cons
- ⊘ Requires managing a background process
- ⊘ If server crashes, agents lose access (but they can still fall back to the protocol file)
- ⊘ Needs Python 3.9+ on your machine

### Installation

**Step 1: Copy the server to a stable location**

```bash
mkdir -p ~/.scientific-method-ai
cp /path/to/repo/method/service/protocol_mcp_server.py ~/.scientific-method-ai/
```

**Step 2: Register with your agent(s)**

```bash
# Cursor (per-project)
cd /path/to/your/project
/path/to/repo/cursor/install.sh .
# This creates .cursor/mcp.json with the server registered

# Codex (global)
codex mcp add scientific-method -- python3 ~/.scientific-method-ai/protocol_mcp_server.py

# Trae (per-project)
cd /path/to/your/project
/path/to/repo/trae/install.sh .
```

**Step 3: Start the server**

```bash
python3 ~/.scientific-method-ai/protocol_mcp_server.py
```

**To keep it running in the background:**
```bash
# macOS / Linux
nohup python3 ~/.scientific-method-ai/protocol_mcp_server.py > ~/.scientific-method-ai/server.log 2>&1 &
echo $! > ~/.scientific-method-ai/server.pid

# Or with systemd (Linux)
# Create ~/.config/systemd/user/scientific-method-mcp.service
# (see "Systemd setup" below)
```

### Verification

```bash
# Check that the server is running
ps aux | grep protocol_mcp_server.py

# Test a request (in another terminal)
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test"}}}' | \
  python3 ~/.scientific-method-ai/protocol_mcp_server.py 2>/dev/null | head -5
```

### Systemd setup (Linux, optional but recommended)

**Create `~/.config/systemd/user/scientific-method-mcp.service`:**
```ini
[Unit]
Description=Scientific Method MCP Server
After=network.target

[Service]
Type=simple
ExecStart=%h/.scientific-method-ai/protocol_mcp_server.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

**Enable and start:**
```bash
systemctl --user enable scientific-method-mcp
systemctl --user start scientific-method-mcp
systemctl --user status scientific-method-mcp
```

**View logs:**
```bash
journalctl --user -u scientific-method-mcp -f
```

### To disable service mode later

**Remove the server**:
```bash
rm ~/.scientific-method-ai/protocol_mcp_server.py
rm ~/.config/systemd/user/scientific-method-mcp.service 2>/dev/null
systemctl --user daemon-reload 2>/dev/null
```

**Unregister from agents**:
```bash
# Cursor: delete .cursor/mcp.json or remove the entry
rm /path/to/your/project/.cursor/mcp.json

# Codex: 
codex config rm mcp_servers.scientific-method

# Trae:
rm /path/to/your/project/.trae/mcp.json
```

---

## Choosing: standalone or service, or both?

### Use **standalone only** if:
- You work on one machine with one agent
- You like zero background processes
- Simplicity matters more than speed
- You're offline often

### Use **service only** if:
- Multiple agents on the same machine need the protocol
- You prefer a centralized architecture
- Speed is important (slight optimization)
- You're comfortable managing a background process

### Use **both** (recommended for teams) if:
- You want redundancy (if server crashes, agents still work via their own hooks)
- You're using multiple agents (some have hooks, some only have MCP)
- You have a mix of cloud and local agents
- You want flexibility to switch modes

**Both run on the same `SCIENTIFIC_PROTOCOL.md` and never conflict.**

---

## Installation command reference

| Agent | Standalone | Service | Command |
|-------|-----------|---------|---------|
| **Claude Code** | ✅ Hook | ✗ Not supported | `./claude/install.sh /project` |
| **Devin** | ✅ Hook | ✗ Not supported | `./devin/install.sh /project` |
| **Cursor** | ✅ Rules | ✅ MCP | `./cursor/install.sh /project` |
| **Codex CLI** | ✅ AGENTS.md | ✅ MCP | `./codex/install.sh /project` |
| **Trae IDE** | ✅ Rules | ✅ MCP | `./trae/install.sh /project` |

**All `install.sh` scripts are idempotent** — safe to run multiple times.

---

## Troubleshooting

### "Protocol not found"
- **Standalone:** Did you copy `method/PROJECT_PROTOCOL_TEMPLATE.md` to `SCIENTIFIC_PROTOCOL.md` in your project?
- **Service:** Is the server running? `ps aux | grep protocol_mcp_server`

### "Hook not running" (Standalone)
- **Claude Code:** Check `~/.claude/hooks/` — script should be there
- **Devin:** Check `~/.devin/hooks/` — script should be there
- **Cursor:** Check `{project}/.cursor/rules/scientific-method.mdc`
- **Codex:** Check `{project}/AGENTS.md` and run `codex config trust {project}`
- **Trae:** Check `{project}/.trae/rules/scientific-method.md`

### "MCP server not responding" (Service)
```bash
# Is it running?
ps aux | grep protocol_mcp_server.py

# Restart it
pkill -f protocol_mcp_server.py
python3 ~/.scientific-method-ai/protocol_mcp_server.py
```

### "Protocol is stale" (Service)
The server caches nothing — each request reads the file. If it feels stale:
```bash
# Verify the file has the latest content
cat /path/to/project/SCIENTIFIC_PROTOCOL.md | head -30
```

---

## Next steps

1. **Choose your mode** using the table above
2. **Run the install script** for your agent
3. **Copy the protocol template**: `cp method/PROJECT_PROTOCOL_TEMPLATE.md /your/project/SCIENTIFIC_PROTOCOL.md`
4. **Verify** (see "Verification" sections above for your mode)
5. **Read the method**: [`method/SCIENTIFIC_METHOD.md`](method/SCIENTIFIC_METHOD.md)
6. **Update your protocol** as you work — both modes read the same file

---

## For agents (Claude, Devin, Cursor, etc.)

If you're an agent running a setup flow:

1. **Ask the human which mode they prefer** (see "Choosing" section above)
2. **If they don't know:** default to **standalone** (simpler, zero daemon)
3. **Run the appropriate `install.sh`:**
   ```bash
   cd /path/to/scientific-method-ai
   ./{tool}/install.sh /path/to/their/project
   ```
4. **Verify it worked:**
   - Standalone: Check hook/rule files exist
   - Service: Run the server, test with the verification commands above
5. **Ask them to copy the template:**
   ```bash
   cp method/PROJECT_PROTOCOL_TEMPLATE.md /their/project/SCIENTIFIC_PROTOCOL.md
   ```
6. **Point them to** `method/SCIENTIFIC_METHOD.md` to read how to use it

---

## See also

- [`README.md`](README.md) — overview of the entire repo
- [`method/SCIENTIFIC_METHOD.md`](method/SCIENTIFIC_METHOD.md) — how to write and maintain a protocol
- [`method/ENFORCEMENT_MODEL.md`](method/ENFORCEMENT_MODEL.md) — why delivery mode matters
- `{tool}/README.md` (e.g., `cursor/README.md`) — agent-specific tested behavior and gotchas
