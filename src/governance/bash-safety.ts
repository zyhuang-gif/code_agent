import type { ToolPolicy } from "../tools/contracts.js";

export interface BashAssessment {
  readonly policy: ToolPolicy;
  readonly reasons: readonly string[];
}

const DESTRUCTIVE_PATTERNS: readonly RegExp[] = [
  /(^|[;&|]\s*)rm\s+.*-[a-z]*r[a-z]*f/i,
  /remove-item\b.*-recurse\b.*-force/i,
  /git\s+reset\s+--hard/i,
  /git\s+clean\s+-[^\s]*f/i,
  /git\s+push\b.*--force(?:-with-lease)?/i,
  /docker\s+(?:system|builder|image|volume)\s+prune/i,
  /\b(?:format|mkfs)\b/i,
  /\b(?:drop\s+database|truncate\s+table)\b/i,
  /\b(?:del|rd|rmdir)\b.*(?:\/s|\/q)/i,
];

const NETWORK_PATTERNS: readonly RegExp[] = [
  /\bhttps?:\/\//i,
  /\b(?:curl|wget)\b/i,
  /invoke-webrequest|invoke-restmethod/i,
  /\b(?:npm|pnpm|yarn|pip|uv)\s+(?:install|add|sync)\b/i,
  /\bgit\s+(?:fetch|pull|push|clone)\b/i,
];

const READ_ONLY_PATTERNS: readonly RegExp[] = [
  /^\s*(?:pwd|cd\s*|dir\b|ls\b|tree\b|cat\b|type\b|get-content\b|get-childitem\b)/i,
  /^\s*(?:rg|grep|findstr|select-string)\b/i,
  /^\s*git\s+(?:status|diff|log|show|branch(?:\s+--list)?|rev-parse|worktree\s+list)\b/i,
  /^\s*(?:node|npm|python|pytest|tsc)\s+--?version\b/i,
];

export function assessBashCommand(command: string): BashAssessment {
  const reasons: string[] = [];
  const destructive = DESTRUCTIVE_PATTERNS.some((pattern) => pattern.test(command));
  const openWorld = NETWORK_PATTERNS.some((pattern) => pattern.test(command));
  const readOnly = !destructive && !openWorld && READ_ONLY_PATTERNS.some((pattern) => pattern.test(command));
  if (destructive) reasons.push("command matches destructive pattern");
  if (openWorld) reasons.push("command may access external systems or the network");
  if (readOnly) reasons.push("command matches local read-only pattern");
  if (reasons.length === 0) reasons.push("command side effects are not provably read-only");
  return {
    policy: {
      access: readOnly ? "read_only" : "write",
      impact: destructive ? "destructive" : "non_destructive",
      concurrency: readOnly ? "parallel_safe" : destructive ? "exclusive" : "serial",
      idempotent: readOnly,
      openWorld,
    },
    reasons,
  };
}
