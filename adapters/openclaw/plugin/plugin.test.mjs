import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  CONFORMANCE_SCENARIO,
  conformancePrompt,
  findProposalByDigest,
  lastAssistantText,
  lifecyclePrompt,
  parseCommandArgs,
  readPluginSettings,
  registerContextOsSurfaces,
  resolveProject
} from "./lib.js";

test("parses lifecycle aliases without accepting a path", () => {
  assert.deepEqual(parseCommandArgs("demo setup"), {
    project: "demo",
    action: "setup",
    kind: "lifecycle"
  });
  assert.throws(() => parseCommandArgs("C:\\repo setup"), /configured alias/);
  assert.throws(() => parseCommandArgs("demo setup extra"), /does not accept/);
});

test("apply accepts only an exact lowercase digest", () => {
  const digest = "a".repeat(64);
  assert.deepEqual(parseCommandArgs(`demo apply ${digest}`), {
    project: "demo",
    action: "apply",
    digest,
    kind: "apply"
  });
  assert.throws(() => parseCommandArgs(`demo apply ${"A".repeat(64)}`), /64-character/);
});

test("settings apply bounded timeout defaults", () => {
  assert.equal(readPluginSettings({ projects: { demo: {} } }).runTimeoutSeconds, 600);
  assert.throws(() => readPluginSettings({ projects: {}, runTimeoutSeconds: 30 }), /60 through 1800/);
});

test("extracts the last assistant text", () => {
  assert.equal(lastAssistantText([
    { role: "assistant", content: "first" },
    { role: "user", content: "next" },
    { role: "assistant", content: [{ type: "text", text: "final" }] }
  ]), "final");
});

test("lifecycle prompt is proposal-only", () => {
  const prompt = lifecyclePrompt("update");
  assert.match(prompt, /exact repository root/);
  assert.match(prompt, /do not apply/);
  assert.throws(() => lifecyclePrompt("apply"), /invalid lifecycle/);
  assert.match(conformancePrompt("setup"), /synthetic public-safe fixture/);
  assert.match(conformancePrompt("end"), /pre-reviewed and confirmed synthetic draft/);
});

test("resolves configured roots and finds proposals only by digest", async () => {
  const temp = await mkdtemp(path.join(os.tmpdir(), "context-os-openclaw-plugin-"));
  try {
    const root = path.join(temp, "repo");
    const bin = path.join(temp, "bin");
    await mkdir(path.join(root, "scripts"), { recursive: true });
    await mkdir(path.join(root, ".context-os", "proposals"), { recursive: true });
    await mkdir(bin, { recursive: true });
    await writeFile(path.join(root, "AGENTS.md"), "test\n");
    await writeFile(path.join(root, "scripts", "contextos.sh"), "#!/usr/bin/env bash\n");
    const bashPath = path.join(bin, process.platform === "win32" ? "bash.exe" : "bash");
    await writeFile(bashPath, "stub\n");
    const digest = "b".repeat(64);
    await writeFile(
      path.join(root, ".context-os", "proposals", "one.json"),
      `${JSON.stringify({ proposal_digest: digest })}\n`
    );

    const settings = readPluginSettings({ projects: { demo: { root, bashPath } } });
    const project = await resolveProject(settings, "demo");
    assert.equal(project.root, await import("node:fs/promises").then(({ realpath }) => realpath(root)));
    assert.equal(await findProposalByDigest(project.root, digest), ".context-os/proposals/one.json");
    await assert.rejects(() => findProposalByDigest(project.root, "c".repeat(64)), /no proposal/);

    const rootAlias = path.join(temp, "repo-alias");
    await symlink(root, rootAlias, process.platform === "win32" ? "junction" : "dir");
    const aliasedSettings = readPluginSettings({
      projects: { demo: { root: rootAlias, bashPath } }
    });
    await assert.rejects(() => resolveProject(aliasedSettings, "demo"), /symlink|junction|canonical/);
  } finally {
    await rm(temp, { recursive: true, force: true });
  }
});

test("registers operator-scoped gateway lifecycle and apply methods with alias-only inputs", async () => {
  const temp = await mkdtemp(path.join(os.tmpdir(), "context-os-openclaw-gateway-"));
  try {
    const root = path.join(temp, "repo");
    const bin = path.join(temp, "bin");
    await mkdir(path.join(root, "scripts"), { recursive: true });
    await mkdir(path.join(root, ".context-os", "proposals"), { recursive: true });
    await mkdir(bin, { recursive: true });
    await writeFile(path.join(root, "AGENTS.md"), "test\n");
    await writeFile(path.join(root, "scripts", "contextos.sh"), "#!/usr/bin/env bash\n");
    const bashPath = path.join(bin, process.platform === "win32" ? "bash.exe" : "bash");
    await writeFile(bashPath, "stub\n");
    const digest = "d".repeat(64);
    await writeFile(
      path.join(root, ".context-os", "proposals", "approved.json"),
      `${JSON.stringify({ proposal_digest: digest })}\n`
    );

    const methods = new Map();
    const commands = [];
    const calls = { run: [], wait: [], messages: [], apply: [] };
    const api = {
      pluginConfig: {
        projects: { demo: { root, bashPath } },
        runTimeoutSeconds: 60
      },
      runtime: {
        subagent: {
          async run(params) {
            calls.run.push(params);
            return { runId: "run-owned" };
          },
          async waitForRun(params) {
            calls.wait.push(params);
            return { status: "ok", startedAt: 1, endedAt: 2 };
          },
          async getSessionMessages(params) {
            calls.messages.push(params);
            return { messages: [{ role: "assistant", content: "done" }] };
          }
        },
        system: {
          async runCommandWithTimeout(argv, options) {
            calls.apply.push({ argv, options });
            return { code: 0, termination: "exit", stdout: "applied", stderr: "" };
          }
        }
      },
      registerGatewayMethod(name, handler, options) {
        methods.set(name, { handler, options });
      },
      registerCommand(command) {
        commands.push(command);
      }
    };
    const ids = ["session-id", "idempotency-id", "scenario-session", "scenario-idempotency"];
    registerContextOsSurfaces(api, { randomId: () => ids.shift() });

    assert.deepEqual([...methods.keys()], [
      "contextos.run",
      "contextos.wait",
      "contextos.result",
      "contextos.apply"
    ]);
    assert.equal(commands.length, 1);
    assert.deepEqual(methods.get("contextos.run").options, { scope: "operator.write" });
    assert.deepEqual(methods.get("contextos.wait").options, { scope: "operator.read" });
    assert.deepEqual(methods.get("contextos.result").options, { scope: "operator.read" });
    assert.deepEqual(methods.get("contextos.apply").options, { scope: "operator.write" });

    async function invoke(name, params) {
      let response;
      await methods.get(name).handler({
        params,
        respond(ok, payload, error) {
          response = { ok, payload, error };
        }
      });
      return response;
    }

    const started = await invoke("contextos.run", { alias: "demo", action: "start" });
    assert.deepEqual(started, {
      ok: true,
      payload: {
        runId: "run-owned",
        sessionKey: "agent:main:subagent:contextos-session-id"
      },
      error: undefined
    });
    assert.equal(calls.run[0].cwd, await import("node:fs/promises").then(({ realpath }) => realpath(root)));
    assert.equal(calls.run[0].message, "/skill start");
    assert.equal("root" in calls.run[0], false);

    const unmarkedScenario = await invoke("contextos.run", {
      alias: "demo",
      action: "update",
      scenario: CONFORMANCE_SCENARIO
    });
    assert.equal(unmarkedScenario.ok, false);
    assert.match(unmarkedScenario.error.message, /disposable/i);
    await writeFile(path.join(root, ".context-os-live-disposable"), "disposable\n");
    const scenario = await invoke("contextos.run", {
      alias: "demo",
      action: "update",
      scenario: CONFORMANCE_SCENARIO
    });
    assert.equal(scenario.ok, true);
    assert.match(calls.run[1].message, /Live OpenClaw checkpoint completed/);
    const unknownScenario = await invoke("contextos.run", {
      alias: "demo",
      action: "start",
      scenario: "arbitrary-prompt"
    });
    assert.equal(unknownScenario.ok, false);
    assert.match(unknownScenario.error.message, /scenario must be/);

    const waited = await invoke("contextos.wait", { runId: "run-owned", timeoutMs: 1_000 });
    assert.equal(waited.ok, true);
    assert.deepEqual(calls.wait[0], { runId: "run-owned", timeoutMs: 1_000 });
    const result = await invoke("contextos.result", {
      sessionKey: "agent:main:subagent:contextos-session-id"
    });
    assert.deepEqual(result.payload, {
      sessionKey: "agent:main:subagent:contextos-session-id",
      text: "done"
    });

    const applied = await invoke("contextos.apply", { alias: "demo", digest });
    assert.equal(applied.ok, true);
    assert.deepEqual(calls.apply[0].argv, [
      await import("node:fs/promises").then(({ realpath }) => realpath(bashPath)),
      "scripts/contextos.sh",
      "apply",
      ".context-os/proposals/approved.json",
      "--confirm",
      digest,
      "--runtime",
      "openclaw"
    ]);
    assert.equal(calls.apply[0].options.cwd, await import("node:fs/promises").then(({ realpath }) => realpath(root)));

    const unknown = await invoke("contextos.run", { alias: "missing", action: "start" });
    assert.equal(unknown.ok, false);
    assert.match(unknown.error.message, /unknown project alias/);
    const injectedPath = await invoke("contextos.apply", { alias: "demo", digest, proposalPath: "elsewhere.json" });
    assert.equal(injectedPath.ok, false);
    assert.match(injectedPath.error.message, /unexpected parameter/);
    const foreignWait = await invoke("contextos.wait", { runId: "run-foreign" });
    assert.equal(foreignWait.ok, false);
    assert.match(foreignWait.error.message, /not owned/);
    const foreignResult = await invoke("contextos.result", { sessionKey: "agent:main:subagent:other" });
    assert.equal(foreignResult.ok, false);
    assert.match(foreignResult.error.message, /not owned/);
  } finally {
    await rm(temp, { recursive: true, force: true });
  }
});
