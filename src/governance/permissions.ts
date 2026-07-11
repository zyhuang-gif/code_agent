import type { ToolInvocation, ToolPolicy } from "../tools/contracts.js";

export type PermissionDecisionKind = "allow" | "ask" | "deny";
export type PermissionMode = "default" | "plan" | "accept_edits" | "bypass";

export interface PermissionRequest {
  readonly sessionId: string;
  readonly workspace: string;
  readonly invocation: ToolInvocation;
  readonly policy: ToolPolicy;
}

export interface PermissionDecision {
  readonly kind: PermissionDecisionKind;
  readonly reason: string;
  readonly rule?: string;
}

export interface PermissionRule {
  readonly toolPattern: string;
  readonly decision: PermissionDecisionKind;
  readonly reason: string;
}

export interface ApprovalProvider {
  requestApproval(request: PermissionRequest, decision: PermissionDecision): Promise<boolean>;
}

function patternMatches(pattern: string, value: string): boolean {
  const escaped = pattern.replace(/[.+^$()|[\]\\{}]/g, "\\$&").replaceAll("*", ".*");
  return new RegExp("^" + escaped + "$", "i").test(value);
}

export class PermissionEngine {
  constructor(
    private readonly mode: PermissionMode = "default",
    private readonly rules: readonly PermissionRule[] = [],
  ) {}

  evaluate(request: PermissionRequest): PermissionDecision {
    const explicit = this.rules.find((rule) => patternMatches(rule.toolPattern, request.invocation.name));
    if (explicit) {
      return { kind: explicit.decision, reason: explicit.reason, rule: explicit.toolPattern };
    }
    if (this.mode === "bypass") return { kind: "allow", reason: "permission bypass mode" };
    if (this.mode === "plan" && request.policy.access === "write") {
      return { kind: "deny", reason: "plan mode denies write-capable tools" };
    }
    if (request.policy.impact === "destructive") {
      return { kind: "ask", reason: "destructive tool requires explicit approval" };
    }
    if (request.policy.access === "read_only" && !request.policy.openWorld) {
      return { kind: "allow", reason: "local read-only tool" };
    }
    if (this.mode === "accept_edits" && request.policy.access === "write" && !request.policy.openWorld) {
      return { kind: "allow", reason: "accept-edits mode allows local non-destructive writes" };
    }
    return { kind: "ask", reason: "tool has write or external side effects" };
  }
}

export class StaticApprovalProvider implements ApprovalProvider {
  readonly requests: PermissionRequest[] = [];
  constructor(private readonly approved: boolean) {}
  async requestApproval(request: PermissionRequest): Promise<boolean> {
    this.requests.push(request);
    return this.approved;
  }
}

export class DenyApprovalProvider extends StaticApprovalProvider {
  constructor() { super(false); }
}
