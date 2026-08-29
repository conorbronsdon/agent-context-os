import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  CONFORMANCE_SCENARIO,
  conformanceContinuationPrompt,
  conformancePrompt,
  lastAssistantText,
  lifecyclePrompt,
  parseCommandArgs,
  operatorSafeText,
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
  assert.deepEqual(parseCommandArgs("demo continue agent:main:subagent:owned confirmed public audience"), {
    project: "demo",
    sessionKey: "agent:main:subagent:owned",
    message: "confirmed public audience",
    kind: "continue"
  });
  assert.throws(() => parseCommandArgs("demo continue agent:main:subagent:owned"), /operator response/);
});

test("settings apply bounded timeout defaults", () => {
  assert.equal(readPluginSettings({ projects: { demo: {} } }).runTimeoutSeconds, 600);
  assert.throws(() => readPluginSettings({ projects: {} }), /at least one project/);
  assert.throws(() => readPluginSettings({ projects: { demo: {} }, runTimeoutSeconds: 30 }), /60 through 1800/);
});

test("extracts the last assistant text", () => {
  assert.equal(lastAssistantText([
    { role: "assistant", content: "first" },
    { role: "user", content: "next" },
    { role: "assistant", content: [{ type: "text", text: "final" }] }
  ]), "final");
});

test("escapes terminal-unsafe native command output", () => {
  assert.equal(operatorSafeText("safe\n\ttext"), "safe\n\ttext");
  assert.equal(
    operatorSafeText("erase\r\u001b[2J bidi \u202e unicode café"),
    "erase\\u{d}\\u{1b}[2J bidi \\u{202e} unicode caf\\u{e9}"
  );
});

test("lifecycle prompt is proposal-only", () => {
  const prompt = lifecyclePrompt("update");
  assert.match(prompt, /exact repository root/);
  assert.match(prompt, /do not apply/);
  assert.throws(() => lifecyclePrompt("apply"), /invalid lifecycle/);
  assert.match(conformancePrompt("setup", "contextos-continuity-test"), /ask one setup question/);
  assert.match(conformancePrompt("setup", "contextos-continuity-test"), /contextos-continuity-test/);
  assert.match(conformancePrompt("setup", "contextos-continuity-test"), /Conformance continuity proof/);
  assert.match(conformancePrompt("setup", "contextos-continuity-test"), /"status":"awaiting_input"/);
  assert.match(conformanceContinuationPrompt("setup"), /synthetic public-safe fixture/);
  assert.match(conformanceContinuationPrompt("setup"), /Conformance continuity proof/);
  assert.throws(() => conformanceContinuationPrompt("update"), /only for setup/);
  assert.match(conformancePrompt("start"), /Only if the required kernel inventory succeeds/);
  assert.match(conformancePrompt("start"), /"status":"blocked"/);
  assert.match(conformancePrompt("end"), /pre-reviewed and confirmed synthetic draft/);
});

test("resolves configured roots without accepting aliases", async () => {
  const temp = await mkdtemp(path.join(os.tmpdir(), "context-os-openclaw-plugin-"));
  try {
    const root = path.join(temp, "repo");
    await mkdir(path.join(root, "scripts"), { recursive: true });
    await writeFile(path.join(root, "AGENTS.md"), "test\n");
    await writeFile(path.join(root, "scripts", "contextos.sh"), "#!/usr/bin/env bash\n");

    const settings = readPluginSettings({ projects: { demo: { root } } });
    const project = await resolveProject(settings, "demo");
    assert.equal(project.root, await import("node:fs/promises").then(({ realpath }) => realpath(root)));

    const rootAlias = path.join(temp, "repo-alias");
    await symlink(root, rootAlias, process.platform === "win32" ? "junction" : "dir");
    const aliasedSettings = readPluginSettings({
      projects: { demo: { root: rootAlias } }
    });
    await assert.rejects(() => resolveProject(aliasedSettings, "demo"), /symlink|junction|canonical/);
  } finally {
    await rm(temp, { recursive: true, force: true });
  }
});

test("registers operator-scoped lifecycle continuation with owned sessions", async () => {
  const temp = await mkdtemp(path.join(os.tmpdir(), "context-os-openclaw-gateway-"));
  try {
    const root = path.join(temp, "repo");
    await mkdir(path.join(root, "scripts"), { recursive: true });
    await writeFile(path.join(root, "AGENTS.md"), "test\n");
    await writeFile(path.join(root, "scripts", "contextos.sh"), "#!/usr/bin/env bash\n");

    const methods = new Map();
    const commands = [];
    const calls = { run: [], wait: [], messages: [] };
    let runSequence = 0;
    let gatewaySequence = 0;
    let capabilitySequence = 0;
    const api = {
      pluginConfig: {
        projects: { demo: { root } },
        runTimeoutSeconds: 60
      },
      runtime: {
        subagent: {
          async run(params) {
            calls.run.push(params);
            runSequence += 1;
            return { runId: `run-owned-${runSequence}` };
          },
          async waitForRun(params) {
            calls.wait.push(params);
            return { status: "ok", startedAt: 1, endedAt: 2 };
          },
          async getSessionMessages(params) {
            calls.messages.push(params);
            return { messages: [{ role: "assistant", content: "done" }] };
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
    const ids = [
      "session-id", "idempotency-id", "continue-idempotency",
      "scenario-session", "continuity-id", "scenario-idempotency", "scenario-continue-idempotency",
      "native-session", "native-idempotency"
    ];
    const surfaces = registerContextOsSurfaces(api, {
      randomId: () => ids.shift(),
      randomCapability: () => `capability-${++capabilitySequence}`,
      maxOwnedSessions: 3
    });

    assert.deepEqual([...methods.keys()], [
      "contextos.run",
      "contextos.continue",
      "contextos.wait",
      "contextos.result"
    ]);
    assert.equal(commands.length, 1);
    assert.deepEqual(methods.get("contextos.run").options, { scope: "operator.write" });
    assert.deepEqual(methods.get("contextos.continue").options, { scope: "operator.write" });
    assert.deepEqual(methods.get("contextos.wait").options, { scope: "operator.read" });
    assert.deepEqual(methods.get("contextos.result").options, { scope: "operator.read" });

    async function invoke(name, params, token = "gateway-a") {
      let response;
      gatewaySequence += 1;
      await methods.get(name).handler({
        params,
        client: { connect: { auth: { token, deviceToken: `rotating-device-${gatewaySequence}` } } },
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
        runId: "run-owned-1",
        sessionKey: "agent:main:subagent:contextos-session-id",
        ownershipToken: "contextos-owner-capability-1"
      },
      error: undefined
    });
    assert.equal(calls.run[0].cwd, await import("node:fs/promises").then(({ realpath }) => realpath(root)));
    assert.equal(calls.run[0].message, "/skill start");
    assert.equal(calls.run[0].lightContext, true);
    assert.equal("root" in calls.run[0], false);

    const continued = await invoke("contextos.continue", {
      alias: "demo",
      sessionKey: "agent:main:subagent:contextos-session-id",
      message: "The audience is public.",
      ownershipToken: "contextos-owner-capability-1"
    });
    assert.equal(continued.ok, true);
    assert.equal(calls.run[1].sessionKey, "agent:main:subagent:contextos-session-id");
    assert.match(calls.run[1].message, /audience is public/);
    assert.equal(calls.run[1].lightContext, true);
    const continuedWait = await invoke("contextos.wait", {
      runId: "run-owned-2",
      timeoutMs: 1_000,
      ownershipToken: "contextos-owner-capability-1"
    });
    assert.equal(continuedWait.ok, true, continuedWait.error?.message);
    const crossGatewayContinue = await invoke("contextos.continue", {
      alias: "demo",
      sessionKey: "agent:main:subagent:contextos-session-id",
      message: "injected",
      ownershipToken: "contextos-owner-wrong"
    });
    assert.equal(crossGatewayContinue.ok, false);
    assert.match(crossGatewayContinue.error.message, /not owned by this operator/);
    await assert.rejects(
      () => surfaces.continueLifecycle(
        "demo", "agent:main:subagent:contextos-session-id", "response", undefined, "different-operator"
      ),
      /not owned by this operator and conversation/
    );
    const wrongAlias = await invoke("contextos.continue", {
      alias: "missing",
      sessionKey: "agent:main:subagent:contextos-session-id",
      message: "response",
      ownershipToken: "contextos-owner-capability-1"
    });
    assert.equal(wrongAlias.ok, false);
    assert.match(wrongAlias.error.message, /not owned by that project alias/);

    const unmarkedScenario = await invoke("contextos.run", {
      alias: "demo",
      action: "setup",
      scenario: CONFORMANCE_SCENARIO
    });
    assert.equal(unmarkedScenario.ok, false);
    assert.match(unmarkedScenario.error.message, /disposable/i);
    await writeFile(path.join(root, ".context-os-live-disposable"), "disposable\n");
    const scenario = await invoke("contextos.run", {
      alias: "demo",
      action: "setup",
      scenario: CONFORMANCE_SCENARIO
    });
    assert.equal(scenario.ok, true);
    assert.equal(scenario.payload.ownershipToken, "contextos-owner-capability-3");
    assert.equal(scenario.payload.continuityChallenge, "contextos-continuity-continuity-id");
    assert.match(calls.run[2].message, /contextos-continuity-continuity-id/);
    assert.match(calls.run[2].message, /awaiting_input/);
    const scenarioContinued = await invoke("contextos.continue", {
      alias: "demo",
      sessionKey: "agent:main:subagent:contextos-scenario-session",
      scenario: CONFORMANCE_SCENARIO,
      ownershipToken: "contextos-owner-capability-3"
    });
    assert.equal(scenarioContinued.ok, true);
    assert.match(calls.run[3].message, /Lifecycle Fixture/);
    assert.doesNotMatch(calls.run[3].message, /contextos-continuity-continuity-id/);
    assert.equal(calls.run[3].sessionKey, "agent:main:subagent:contextos-scenario-session");
    const scenarioInjection = await invoke("contextos.continue", {
      alias: "demo",
      sessionKey: "agent:main:subagent:contextos-scenario-session",
      scenario: CONFORMANCE_SCENARIO,
      message: "arbitrary",
      ownershipToken: "contextos-owner-capability-3"
    });
    assert.equal(scenarioInjection.ok, false);
    assert.match(scenarioInjection.error.message, /no message/);
    const unknownScenario = await invoke("contextos.run", {
      alias: "demo",
      action: "start",
      scenario: "arbitrary-prompt"
    });
    assert.equal(unknownScenario.ok, false);
    assert.match(unknownScenario.error.message, /scenario must be/);

    const crossGatewayWait = await invoke(
      "contextos.wait", {
        runId: "run-owned-1", timeoutMs: 1_000, ownershipToken: "contextos-owner-wrong"
      }
    );
    assert.equal(crossGatewayWait.ok, false);
    assert.match(crossGatewayWait.error.message, /not owned by this operator/);
    const waited = await invoke("contextos.wait", {
      runId: "run-owned-1",
      timeoutMs: 1_000,
      ownershipToken: "contextos-owner-capability-1"
    });
    assert.equal(waited.ok, true, waited.error?.message);
    assert.deepEqual(calls.wait[1], { runId: "run-owned-1", timeoutMs: 1_000 });
    const result = await invoke("contextos.result", {
      sessionKey: "agent:main:subagent:contextos-session-id",
      ownershipToken: "contextos-owner-capability-1"
    });
    assert.deepEqual(result.payload, {
      sessionKey: "agent:main:subagent:contextos-session-id",
      text: "done"
    });
    const crossGatewayResult = await invoke("contextos.result", {
      sessionKey: "agent:main:subagent:contextos-session-id",
      ownershipToken: "contextos-owner-wrong"
    });
    assert.equal(crossGatewayResult.ok, false);
    assert.match(crossGatewayResult.error.message, /not owned by this operator/);

    const unknown = await invoke("contextos.run", { alias: "missing", action: "start" });
    assert.equal(unknown.ok, false);
    assert.match(unknown.error.message, /unknown project alias/);
    const injectedPath = await invoke("contextos.continue", {
      alias: "demo",
      sessionKey: "agent:main:subagent:contextos-session-id",
      message: "response",
      ownershipToken: "contextos-owner-capability-1",
      proposalPath: "elsewhere.json"
    });
    assert.equal(injectedPath.ok, false);
    assert.match(injectedPath.error.message, /unexpected parameter/);
    const foreignWait = await invoke("contextos.wait", {
      runId: "run-foreign", ownershipToken: "contextos-owner-capability-1"
    });
    assert.equal(foreignWait.ok, false);
    assert.match(foreignWait.error.message, /not owned/);
    const foreignResult = await invoke("contextos.result", {
      sessionKey: "agent:main:subagent:other",
      ownershipToken: "contextos-owner-capability-1"
    });
    assert.equal(foreignResult.ok, false);
    assert.match(foreignResult.error.message, /not owned/);

    const nativeContext = {
      args: "demo update",
      commandBody: "/contextos demo update",
      channel: "test",
      senderId: "operator-a",
      sessionKey: "conversation-a",
      isAuthorizedSender: true,
      agentId: "main"
    };
    const nativeStarted = await commands[0].handler(nativeContext);
    assert.match(nativeStarted.text, /contextos-native-session/);
    const crossPrincipal = await commands[0].handler({
      ...nativeContext,
      args: "demo continue agent:main:subagent:contextos-native-session injected response",
      commandBody: "/contextos demo continue agent:main:subagent:contextos-native-session injected response",
      senderId: "operator-b"
    });
    assert.match(crossPrincipal.text, /not owned by this operator and conversation/);
    await assert.rejects(
      () => surfaces.startLifecycle("demo", "end"),
      /owned lifecycle session limit reached/
    );
  } finally {
    await rm(temp, { recursive: true, force: true });
  }
});
