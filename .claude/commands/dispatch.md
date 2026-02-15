Dispatch a worker agent to execute a task.

1. Read `TASKS.md` and identify the task to dispatch. If the user didn't specify one, show pending tasks with their "Agent Type" recommendations and ask which to dispatch.

2. Read `AGENTS.md` to check the agent registry and module ownership. Determine the agent ID for this dispatch (e.g., `codex-1`, `claude-2`).

3. Construct the launch command based on the recommended agent type:

   **For Codex workers:**
   ```
   codex --full-auto -C <project-root> \
     "You are agent <agent-id>. Follow the startup protocol in AGENTS.md. \
      Work on task <task-id> in TASKS.md. When done, update docs/HANDOFF.md \
      and commit to branch work/<agent-id>/<task-id>."
   ```

   **For Claude Code workers:**
   ```
   claude --print -C <project-root> \
     "You are agent <agent-id>. Read CLAUDE.md, then docs/PROJECT_CHARTER.md, \
      then docs/HANDOFF.md. Work on task <task-id> in TASKS.md. When done, \
      update docs/HANDOFF.md and commit to branch work/<agent-id>/<task-id>."
   ```

4. Before executing, show the user:
   - **Task:** title and summary
   - **Agent:** type and ID
   - **Mode:** work mode from task
   - **Command:** the full launch command
   - **Branch:** where the work will land

5. Ask: "Ready to dispatch? (The dispatch sound will play as confirmation.)"

6. On approval:
   - Update TASKS.md: move task to In Progress, set Assigned to the agent ID
   - Update AGENTS.md: add agent to registry if not already there
   - Execute the launch command in the background
   - Confirm dispatch with the task ID and branch name

7. If the user declines, do not execute. Ask if they want to modify the command or pick a different task.
