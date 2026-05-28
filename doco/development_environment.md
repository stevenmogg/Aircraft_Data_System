# Development environment configuration

This document captures how we develop the Cozy Aircraft Data System against a **Stratux-based Raspberry Pi 5** from a **Mac**, without requiring the primary codebase to live on the Pi.

**Specification (Stage 1):** [cozy_aircraft_data_system_stage1.md](cozy_aircraft_data_system_stage1.md) — [development roadmap](cozy_aircraft_data_system_stage1.md#development-roadmap), [software structure on the node](cozy_aircraft_data_system_stage1.md#software-structure), [cockpit Wi‑Fi / access point](cozy_aircraft_data_system_stage1.md#cockpit-network).
**Stratux build + imaging runbook:** [stratux_build_and_imaging.md](stratux_build_and_imaging.md).

---

## 1. Primary model: local Mac + deploy to Pi (Option B)

| Aspect | Choice |
|--------|--------|
| **Source of truth** | Git repository and working tree on the Mac (this project folder). |
| **Application code** | Edited locally; reviewed, tested, and versioned on the Mac where practical. |
| **Pi** | Runtime target for Stratux, future FIX-Gateway, services, and [cockpit Wi‑Fi / AP role](cozy_aircraft_data_system_stage1.md#cockpit-network) (Stage 1). |
| **Delivery** | Sync or copy to the Pi using SSH-based tools (e.g. `rsync`, `scp`, or `git pull` on the Pi from a remote). |

**Rationale:** Keeps a normal desktop development flow (Cursor, linters, git) and avoids editing production paths directly as the default habit.

---

## 2. What Option B does and does not provide

**Does provide**

- A stable place for project structure (see the Stage 1 [software tree](cozy_aircraft_data_system_stage1.md#software-structure), rooted at `/cozy-data-system` on the node).
- Clear separation between “dev machine” and “aircraft node”.
- Straightforward collaboration in Cursor against the **Mac workspace**.

**Does not automatically provide**

- A live view of the Pi’s full filesystem inside the primary workspace.
- Implicit knowledge of Pi-only paths (`/etc`, Stratux install layout, systemd units) unless we query them.

To work on Linux and Pi configuration, we use the **bridges** in section 3.

---

## 3. Hybrid extensions (use when helpful)

Use these on top of Option B; they do not replace it.

### 3.1 SSH from the Mac terminal

From Cursor’s terminal (or macOS Terminal), run commands on the Pi via SSH, for example:

```bash
ssh <user>@<pi-hostname-or-ip> 'command'
```

Inspect files, journal logs, and validate services; paste relevant output into the chat when debugging with the AI.

**Prerequisites**

- SSH enabled on the Pi and reachable from the Mac (same LAN, Ethernet, USB gadget, or other path you use).
- Prefer **SSH keys** (`ssh-keygen`, `ssh-copy-id`) over password-only login for day-to-day use.

Optional: add a `Host` block in `~/.ssh/config` (e.g. alias `stratux-pi`) so commands stay short and consistent.

### 3.2 Small helper scripts on the Mac (optional)

If repeated checks become common (status of a service, tail logs, list a config dir), add thin wrappers under something like `scripts/pi-*.sh` in this repo that call `ssh` with the same host/user. Keeps documentation and muscle memory aligned.

### 3.3 Second Cursor window: Remote SSH (optional)

For focused sessions on **Pi filesystem and system configuration** (systemd, networking, Stratux-related paths, kernel modules):

1. **Remote - SSH:** Command Palette → *Remote-SSH: Connect to Host…* → same `user@host` as above.
2. **Open folder** on the Pi (e.g. `/etc` subtree, log directory, or a deploy path).
3. Use that window only while needed; keep **primary** app development in the **local Mac** workspace.

This gives the editor and AI context **on the Pi** without moving the main repo there.

---

## 4. Conventions to fill in locally

These are machine-specific; keep them in notes or your shell profile, not necessarily committed with secrets.

| Item | Your value |
|------|------------|
| Pi SSH user | e.g. `pi` or image default |
| Pi hostname or IP | e.g. `stratux-pi` or `192.168.x.x` |
| Deploy path on Pi | e.g. `/home/<user>/cozy-data-system` (align with [Stage 1 software tree](cozy_aircraft_data_system_stage1.md#software-structure) when created) |

---

## 5. Phase 1 alignment (from Stage 1)

These match [Phase 1 in the roadmap](cozy_aircraft_data_system_stage1.md#development-roadmap). Early milestones still apply on the Pi side regardless of where code is edited:

- Pi + Stratux stable  
- Wi-Fi working (client and/or AP per your rollout)  
- AvPlan (or other EFB) connectivity as required  

Environment setup on the Mac is complete when: **SSH works reliably**, and you have a **documented deploy path** from this repo to the Pi.

---

## 6. Summary

| Mode | When to use |
|------|-------------|
| **Local Mac workspace (B)** | Default for application and project files, git, and most implementation work. |
| **SSH commands / pasted output** | Pi state, logs, and one-off config checks without opening a remote workspace. |
| **Remote SSH window** | Deeper or repeated work directly on Pi paths and system layout. |

Revisit this document if you later standardise on `git pull` on the Pi, CI deploy, or a single Remote-SSH-only workflow.
