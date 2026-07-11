export type HookEventType =
  | "session_start"
  | "user_prompt_submit"
  | "pre_model_call"
  | "post_model_call"
  | "pre_tool_use"
  | "permission_request"
  | "post_tool_use"
  | "post_tool_use_failure"
  | "pre_compact"
  | "post_compact"
  | "stop"
  | "session_end";

export interface HookEvent<TPayload = unknown> {
  readonly type: HookEventType;
  readonly sessionId: string;
  readonly payload: TPayload;
}

export interface HookResult<TPayload = unknown> {
  readonly action?: "continue" | "block";
  readonly reason?: string;
  readonly payload?: TPayload;
}

export type HookHandler = (event: HookEvent) => Promise<HookResult | void> | HookResult | void;

export interface HookEmission<TPayload = unknown> {
  readonly blocked: boolean;
  readonly reason?: string;
  readonly payload: TPayload;
}

export class HookBus {
  readonly #handlers = new Map<HookEventType, HookHandler[]>();

  on(type: HookEventType, handler: HookHandler): () => void {
    const handlers = this.#handlers.get(type) ?? [];
    handlers.push(handler);
    this.#handlers.set(type, handlers);
    return () => {
      const current = this.#handlers.get(type) ?? [];
      this.#handlers.set(type, current.filter((candidate) => candidate !== handler));
    };
  }

  async emit<TPayload>(event: HookEvent<TPayload>): Promise<HookEmission<TPayload>> {
    let payload = event.payload;
    for (const handler of this.#handlers.get(event.type) ?? []) {
      const result = await handler({ ...event, payload });
      if (!result) {
        continue;
      }
      if ("payload" in result && result.payload !== undefined) {
        payload = result.payload as TPayload;
      }
      if (result.action === "block") {
        return {
          blocked: true,
          reason: result.reason ?? `blocked by ${event.type} hook`,
          payload,
        };
      }
    }
    return { blocked: false, payload };
  }
}
