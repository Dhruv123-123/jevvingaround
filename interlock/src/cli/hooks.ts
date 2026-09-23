export const ZSH_INIT = `# interlock: gate risky commands before they run (zsh). Add: eval "$(interlock shell-init zsh)"
interlock-accept-line() {
  if [[ -n "$BUFFER" && "$INTERLOCK" != "off" ]]; then
    zle -I
    if interlock shell -- "$BUFFER" < /dev/tty; then
      zle .accept-line
    else
      zle reset-prompt
    fi
  else
    zle .accept-line
  fi
}
zle -N accept-line interlock-accept-line
`;

export const BASH_INIT = `# interlock: gate risky commands before they run (bash). Add: eval "$(interlock shell-init bash)"
# Uses extdebug: a non-zero return from the DEBUG trap skips the command. Rougher than the zsh widget.
shopt -s extdebug
__interlock_trap() {
  [[ "$INTERLOCK" == "off" ]] && return 0
  [[ -n "$COMP_LINE" ]] && return 0
  [[ "$BASH_COMMAND" == "$PROMPT_COMMAND" || "$BASH_COMMAND" == __interlock_* || "$BASH_COMMAND" == interlock\\ * ]] && return 0
  interlock shell -- "$BASH_COMMAND" < /dev/tty
}
trap '__interlock_trap' DEBUG
`;

export const PRE_PUSH = `#!/bin/sh
# interlock pre-push hook. Bypass once with INTERLOCK=off git push, or git push --no-verify.
[ "$INTERLOCK" = "off" ] && exit 0
command -v interlock >/dev/null 2>&1 || { echo "[interlock] not on PATH; letting the push through" >&2; exit 0; }
exec interlock git-push "$@"
`;
