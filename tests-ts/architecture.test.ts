import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

async function sourceFiles(directory: string): Promise<string[]> {
  const files: string[] = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const candidate = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...(await sourceFiles(candidate)));
    else if (entry.name.endsWith(".ts")) files.push(candidate);
  }
  return files;
}

function imports(source: string): readonly string[] {
  return [...source.matchAll(/from\s+["']([^"']+)["']/g)].map((match) => match[1] ?? "");
}

test("four-layer dependency boundaries are mechanically enforced", async () => {
  const rules: Readonly<Record<string, readonly string[]>> = {
    engine: ["node:fs", "node:child_process", "/extensions/", "../extensions", "/host/", "../host"],
    tools: ["/engine/", "../engine", "/services/", "../services", "/governance/", "../governance", "/extensions/", "../extensions", "/host/", "../host"],
    services: ["/engine/", "../engine", "/governance/", "../governance", "/extensions/", "../extensions", "/host/", "../host"],
    governance: ["/engine/", "../engine", "/services/", "../services", "/extensions/", "../extensions", "/host/", "../host"],
  };

  for (const [layer, forbidden] of Object.entries(rules)) {
    for (const file of await sourceFiles(path.resolve("src", layer))) {
      const source = await readFile(file, "utf8");
      for (const imported of imports(source)) {
        assert.equal(
          forbidden.some((fragment) => imported.includes(fragment)),
          false,
          layer + " must not import " + imported + " in " + path.relative(process.cwd(), file),
        );
      }
    }
  }
});

test("engine has no CMake-specific routing branch", async () => {
  const files = await sourceFiles(path.resolve("src", "engine"));
  const source = (await Promise.all(files.map((file) => readFile(file, "utf8")))).join("\n").toLowerCase();
  assert.equal(source.includes("cmake"), false);
});
