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

export function assessBashCommand(command: string): BashAssessment {
  const reasons: string[] = [];
  const destructive = DESTRUCTIVE_PATTERNS.some((pattern) => pattern.test(command));
  const network = NETWORK_PATTERNS.some((pattern) => pattern.test(command));
  if (destructive) reasons.push("command matches destructive pattern");
  if (network) reasons.push("command may access external systems or the network");
  reasons.push("host shell execution is not sandboxed and is never treated as read-only");
  return {
    policy: {
      access: "write",
      impact: destructive ? "destructive" : "non_destructive",
      concurrency: destructive ? "exclusive" : "serial",
      idempotent: false,
      openWorld: true,
    },
    reasons,
  };
}
