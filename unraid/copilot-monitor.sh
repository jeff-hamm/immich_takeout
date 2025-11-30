#!/bin/bash
#
# copilot-monitor.sh - Wrapper to run scripts under Copilot CLI monitoring
#
# Call this at the top of your script with the script path and args:
#   /usr/local/bin/copilot-monitor.sh "$0" "$@"
#   
#   # Your script logic here (only runs after copilot monitoring completes)
#
# Flags (parsed automatically):
#   --unwrapped         Skip Copilot wrapping, run directly
#   --copilot <model>   Use specified model (e.g., claude-sonnet-4.5)
#
# Environment:
#   COPILOT_MODEL       Default model if --copilot not specified
#   GH_TOKEN            GitHub token for creating pull requests (optional)
#
# Git Integration:
#   If the agent makes changes to files in a git repository, it will:
#   1. Create/update a branch named 'copilot'
#   2. Commit and push the changes
#   3. Create a pull request to merge into main (requires gh CLI and GH_TOKEN)
#

set -e

# First arg is the script path
script_path="$1"
shift

model=""
unwrapped=false
args=()

# Parse flags from remaining args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --unwrapped)
            unwrapped=true
            shift
            ;;
        --copilot)
            if [[ -n "$2" && "$2" != --* ]]; then
                model="$2"
                shift 2
            else
                shift
            fi
            ;;
        *)
            args+=("$1")
            shift
            ;;
    esac
done

# If unwrapped, just exit and let the calling script continue
if [[ "$unwrapped" == true ]]; then
    exit 0
fi

# Resolve script path
script_path="$(realpath "$script_path")"

# Build the args string for the wrapped call
args_str="${args[*]}"

# Determine model: --copilot flag > COPILOT_MODEL env > none
if [[ -z "$model" && -n "$COPILOT_MODEL" ]]; then
    model="$COPILOT_MODEL"
fi

# Build copilot command with required flags for non-interactive execution
copilot_cmd="copilot --allow-all-tools"
if [[ -n "$model" ]]; then
    copilot_cmd="$copilot_cmd --model $model"
fi

echo "Launching with Copilot CLI to monitor execution..."
[[ -n "$model" ]] && echo "Using model: $model"

# Build git instructions for the prompt
git_instructions=""
if command -v git &> /dev/null; then
    git_instructions="

IMPORTANT - Git Integration Instructions:
If you make ANY changes to files that are inside a git repository, you MUST:
1. Check if there are uncommitted changes using 'git status'
2. If changes exist:
   a. Switch to or create a branch named 'copilot': git checkout -B copilot
   b. Stage all changes: git add -A
   c. Commit with a descriptive message: git commit -m 'Copilot: <brief description of changes>'
   d. Push to remote: git push -u origin copilot --force
   e. If 'gh' CLI is available and GH_TOKEN is set, create a pull request:
      - First check if a PR already exists: gh pr list --head copilot --state open
      - If no PR exists, create one: gh pr create --base main --head copilot --title 'Copilot automated changes' --body '<description of what was changed and why>'
      - If PR exists, it will be auto-updated by the push
3. Report what git operations you performed in your summary"
fi

# Run copilot with tee to show output in real-time and capture it
prompt="Execute this command: $script_path --unwrapped $args_str

Watch the output carefully. If there are any errors or unexpected behavior, explain them.
${git_instructions}

After the command completes, you MUST output exactly these 3 lines at the end:
===
<one line summary of what happened, including any git operations performed>
EXIT_CODE=<the numeric exit code from the command>"

output=$($copilot_cmd -p "$prompt" 2>&1 | tee /dev/stderr)
copilot_exit=${PIPESTATUS[0]}

# Parse the analysis line (line after ===)
analysis=$(echo "$output" | sed -n '/^===$/,/^EXIT_CODE=/{ /^===$/d; /^EXIT_CODE=/d; p; }' | head -1)

# Parse exit code from copilot output
exit_code=$(echo "$output" | grep -oP 'EXIT_CODE=\K[0-9]+' | tail -1)

# Print summary
if [[ -n "$analysis" ]]; then
    echo ""
    echo "=== Copilot Analysis ==="
    echo "$analysis"
fi

# If we couldn't parse an exit code, use copilot's exit code or default to 1
if [[ -z "$exit_code" ]]; then
    if [[ $copilot_exit -ne 0 ]]; then
        exit_code=$copilot_exit
    else
        exit_code=1
    fi
fi

# Exit with the parsed code
exit "$exit_code"