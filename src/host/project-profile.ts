import { readFile } from "node:fs/promises";
import path from "node:path";
import { parse } from "yaml";

const DEFAULT_SETUP_TIMEOUT_SECONDS = 300;
const DEFAULT_TEST_TIMEOUT_SECONDS = 300;
const DEFAULT_COMMAND_TIMEOUT_SECONDS = 300;
const DEFAULT_MAX_FILE_BYTES = 200_000;
const MAX_TIMEOUT_SECONDS = Math.floor(2_147_483_647 / 1_000);

const YAML_FIELDS = new Set([
  "ignore",
  "syntax_check",
  "setup_cmd",
  "setup_needs_network",
  "setup_timeout",
  "test_cmd",
  "test_timeout",
  "command_timeout",
  "pass_when",
  "parse_test_output",
  "language",
  "max_file_bytes",
]);

const HARD_IGNORED_PARTS = new Set([".git", "__pycache__"]);

export type ProfileErrorCode =
  | "read_error"
  | "yaml_parse_error"
  | "invalid_root"
  | "unknown_field"
  | "invalid_type"
  | "out_of_range"
  | "invalid_value";

export interface ProfileErrorOptions {
  readonly code: ProfileErrorCode;
  readonly source?: string;
  readonly field?: string;
  readonly expected?: string;
  readonly actual?: unknown;
  readonly cause?: unknown;
}

export interface SerializedProfileError {
  readonly name: "ProfileError";
  readonly code: ProfileErrorCode;
  readonly message: string;
  readonly source: string;
  readonly field?: string;
  readonly expected?: string;
  readonly actual?: unknown;
}

export class ProfileError extends Error {
  readonly code: ProfileErrorCode;
  readonly source: string;
  readonly field: string | undefined;
  readonly expected: string | undefined;
  readonly actual: unknown;

  constructor(message: string, options: ProfileErrorOptions) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.name = "ProfileError";
    this.code = options.code;
    this.source = options.source ?? "<memory>";
    this.field = options.field;
    this.expected = options.expected;
    this.actual = options.actual;
  }

  toJSON(): SerializedProfileError {
    const serialized: {
      name: "ProfileError";
      code: ProfileErrorCode;
      message: string;
      source: string;
      field?: string;
      expected?: string;
      actual?: unknown;
    } = {
      name: "ProfileError",
      code: this.code,
      message: this.message,
      source: this.source,
    };
    if (this.field !== undefined) serialized.field = this.field;
    if (this.expected !== undefined) serialized.expected = this.expected;
    if (this.actual !== undefined) serialized.actual = this.actual;
    return serialized;
  }
}

export interface ProjectProfileInit {
  readonly ignore?: readonly string[];
  readonly syntaxCheck?: Readonly<Record<string, string>>;
  readonly setupCmd?: string | null;
  readonly setupNeedsNetwork?: boolean;
  readonly setupTimeout?: number;
  readonly testCmd?: string | null;
  readonly testTimeout?: number;
  readonly commandTimeout?: number;
  readonly passWhen?: string;
  readonly parseTestOutput?: string | null;
  readonly language?: string | null;
  readonly maxFileBytes?: number;
}

export class ProjectProfile {
  readonly ignore: readonly string[];
  readonly syntaxCheck: Readonly<Record<string, string>>;
  readonly setupCmd: string | null;
  readonly setupNeedsNetwork: boolean;
  readonly setupTimeout: number;
  readonly testCmd: string | null;
  readonly testTimeout: number;
  readonly commandTimeout: number;
  readonly passWhen: string;
  readonly parseTestOutput: string | null;
  readonly language: string | null;
  readonly maxFileBytes: number;

  constructor(init: ProjectProfileInit = {}) {
    this.ignore = Object.freeze([...(init.ignore ?? [])]);
    this.syntaxCheck = Object.freeze({ ...(init.syntaxCheck ?? {}) });
    this.setupCmd = init.setupCmd ?? null;
    this.setupNeedsNetwork = init.setupNeedsNetwork ?? true;
    this.setupTimeout = init.setupTimeout ?? DEFAULT_SETUP_TIMEOUT_SECONDS;
    this.testCmd = init.testCmd ?? null;
    this.testTimeout = init.testTimeout ?? DEFAULT_TEST_TIMEOUT_SECONDS;
    this.commandTimeout = init.commandTimeout ?? DEFAULT_COMMAND_TIMEOUT_SECONDS;
    this.passWhen = init.passWhen ?? "exit_zero";
    this.parseTestOutput = init.parseTestOutput ?? null;
    this.language = init.language ?? null;
    this.maxFileBytes = init.maxFileBytes ?? DEFAULT_MAX_FILE_BYTES;
  }

  shouldIgnore(relativePath: string): boolean {
    const normalized = normalizeRelativePath(relativePath);
    const parts = normalized.split("/").filter(Boolean);
    if (parts.some((part) => HARD_IGNORED_PARTS.has(part))) return true;
    if (normalized.endsWith(".pyc") || parts.some((part) => part.endsWith(".egg-info"))) return true;
    return this.ignore.some((pattern) => matchesIgnorePattern(normalized, parts, pattern));
  }
}

export function createDefaultProjectProfile(): ProjectProfile {
  return new ProjectProfile();
}

export function parseProjectProfile(value: unknown, source = "<memory>"): ProjectProfile {
  if (value === null || value === undefined) return createDefaultProjectProfile();
  if (!isPlainRecord(value)) {
    throw profileError("invalid_root", source, undefined, "mapping or empty document", value);
  }

  const unknownFields = Object.keys(value).filter((key) => !YAML_FIELDS.has(key)).sort();
  if (unknownFields.length > 0) {
    throw profileError(
      "unknown_field",
      source,
      unknownFields.join(", "),
      "known snake_case ProjectProfile field",
      unknownFields,
    );
  }

  return new ProjectProfile({
    ignore: readStringArray(value, "ignore", [], source),
    syntaxCheck: readStringMap(value, "syntax_check", {}, source),
    setupCmd: readNullableString(value, "setup_cmd", null, source),
    setupNeedsNetwork: readBoolean(value, "setup_needs_network", true, source),
    setupTimeout: readPositiveInteger(
      value,
      "setup_timeout",
      DEFAULT_SETUP_TIMEOUT_SECONDS,
      MAX_TIMEOUT_SECONDS,
      source,
    ),
    testCmd: readNullableString(value, "test_cmd", null, source),
    testTimeout: readPositiveInteger(
      value,
      "test_timeout",
      DEFAULT_TEST_TIMEOUT_SECONDS,
      MAX_TIMEOUT_SECONDS,
      source,
    ),
    commandTimeout: readPositiveInteger(
      value,
      "command_timeout",
      DEFAULT_COMMAND_TIMEOUT_SECONDS,
      MAX_TIMEOUT_SECONDS,
      source,
    ),
    passWhen: readNonEmptyString(value, "pass_when", "exit_zero", source),
    parseTestOutput: readNullableString(value, "parse_test_output", null, source),
    language: readNullableString(value, "language", null, source),
    maxFileBytes: readPositiveInteger(value, "max_file_bytes", DEFAULT_MAX_FILE_BYTES, Number.MAX_SAFE_INTEGER, source),
  });
}

export async function loadProjectProfile(filePath: string): Promise<ProjectProfile> {
  const source = path.resolve(filePath);
  let yamlText: string;
  try {
    yamlText = await readFile(source, "utf8");
  } catch (error) {
    throw new ProfileError(`failed to read ProjectProfile ${source}: ${errorMessage(error)}`, {
      code: "read_error",
      source,
      cause: error,
    });
  }

  let value: unknown;
  try {
    value = parse(yamlText);
  } catch (error) {
    throw new ProfileError(`failed to parse ProjectProfile ${source}: ${errorMessage(error)}`, {
      code: "yaml_parse_error",
      source,
      cause: error,
    });
  }
  return parseProjectProfile(value, source);
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value) as unknown;
  return prototype === Object.prototype || prototype === null;
}

function hasOwn(record: Readonly<Record<string, unknown>>, field: string): boolean {
  return Object.prototype.hasOwnProperty.call(record, field);
}

function readStringArray(
  record: Readonly<Record<string, unknown>>,
  field: string,
  fallback: readonly string[],
  source: string,
): readonly string[] {
  if (!hasOwn(record, field)) return fallback;
  const value = record[field];
  if (!Array.isArray(value)) throw profileError("invalid_type", source, field, "array of strings", value);
  for (const [index, item] of value.entries()) {
    if (typeof item !== "string") {
      throw profileError("invalid_type", source, `${field}[${String(index)}]`, "string", item);
    }
  }
  return value as string[];
}

function readStringMap(
  record: Readonly<Record<string, unknown>>,
  field: string,
  fallback: Readonly<Record<string, string>>,
  source: string,
): Readonly<Record<string, string>> {
  if (!hasOwn(record, field)) return fallback;
  const value = record[field];
  if (!isPlainRecord(value)) throw profileError("invalid_type", source, field, "mapping of strings", value);
  const entries = Object.entries(value);
  for (const [key, command] of entries) {
    if (typeof command !== "string") {
      throw profileError("invalid_type", source, `${field}.${key}`, "string", command);
    }
  }
  return Object.fromEntries(entries) as Record<string, string>;
}

function readNullableString(
  record: Readonly<Record<string, unknown>>,
  field: string,
  fallback: string | null,
  source: string,
): string | null {
  if (!hasOwn(record, field)) return fallback;
  const value = record[field];
  if (typeof value === "string" || value === null) return value;
  throw profileError("invalid_type", source, field, "string or null", value);
}

function readNonEmptyString(
  record: Readonly<Record<string, unknown>>,
  field: string,
  fallback: string,
  source: string,
): string {
  if (!hasOwn(record, field)) return fallback;
  const value = record[field];
  if (typeof value !== "string") throw profileError("invalid_type", source, field, "non-empty string", value);
  if (value.length === 0) throw profileError("invalid_value", source, field, "non-empty string", value);
  return value;
}

function readBoolean(
  record: Readonly<Record<string, unknown>>,
  field: string,
  fallback: boolean,
  source: string,
): boolean {
  if (!hasOwn(record, field)) return fallback;
  const value = record[field];
  if (typeof value === "boolean") return value;
  throw profileError("invalid_type", source, field, "boolean", value);
}

function readPositiveInteger(
  record: Readonly<Record<string, unknown>>,
  field: string,
  fallback: number,
  maximum: number,
  source: string,
): number {
  if (!hasOwn(record, field)) return fallback;
  const value = record[field];
  if (typeof value !== "number" || !Number.isSafeInteger(value)) {
    throw profileError("invalid_type", source, field, "positive integer", value);
  }
  if (value < 1 || value > maximum) {
    throw profileError("out_of_range", source, field, `integer from 1 through ${String(maximum)}`, value);
  }
  return value;
}

function profileError(
  code: ProfileErrorCode,
  source: string,
  field: string | undefined,
  expected: string,
  actual: unknown,
): ProfileError {
  const location = field === undefined ? source : `${source} field ${field}`;
  return new ProfileError(`invalid ProjectProfile ${location}: expected ${expected}`, {
    code,
    source,
    ...(field === undefined ? {} : { field }),
    expected,
    actual,
  });
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function normalizeRelativePath(relativePath: string): string {
  return relativePath.replaceAll("\\", "/").replace(/^\.\//, "").replace(/\/{2,}/g, "/");
}

function matchesIgnorePattern(normalizedPath: string, parts: readonly string[], pattern: string): boolean {
  const normalizedPattern = normalizeRelativePath(pattern);
  if (parts.includes(normalizedPattern)) return true;
  const regex = fnmatchPattern(normalizedPattern);
  return regex.test(normalizedPath) || parts.some((part) => regex.test(part));
}

function fnmatchPattern(pattern: string): RegExp {
  let source = "";
  for (let index = 0; index < pattern.length; index += 1) {
    const character = pattern[index]!;
    if (character === "*") {
      source += ".*";
    } else if (character === "?") {
      source += ".";
    } else {
      source += escapeRegex(character);
    }
  }
  return new RegExp(`^${source}$`, process.platform === "win32" ? "i" : "");
}

function escapeRegex(character: string): string {
  return /[\\^$.*+?()[\]{}|]/.test(character) ? `\\${character}` : character;
}
