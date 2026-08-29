import { lstat, readFile, realpath, stat } from "node:fs/promises";
import { createHash, randomUUID } from "node:crypto";
import path from "node:path";

export const PROJECT_ALIAS_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/;
export const LIFECYCLE_ACTIONS = new Set(["setup", "start", "update", "end"]);
export const CONFORMANCE_SCENARIO = "synthetic-conformance-v1";

const MAX_OPERATOR_MESSAGE_CHARS = 16 * 1024;
const MAX_OWNED_SESSIONS = 128;

export function parseCommandArgs(raw) {
  const parts = String(raw ?? "").trim().split(/\s+/u).filter(Boolean);
  if (parts.length < 2) {
    throw new Error("usage: /contextos <project-alias> <setup|start|update|end> | /contextos <project-alias> continue <session-key> <response>");
  }
  const [project, action, sessionKey, ...responseParts] = parts;
  if (!PROJECT_ALIAS_RE.test(project)) {
    throw new Error("project must be a configured alias using lowercase letters, digits, '-' or '_'");
  }
  if (LIFECYCLE_ACTIONS.has(action)) {
    if (parts.length !== 2) {
      throw new Error(`/${"contextos"} ${project} ${action} does not accept additional arguments`);
    }
    return { project, action, kind: "lifecycle" };
  }
  if (action === "continue") {
    if (!sessionKey || responseParts.length === 0) {
      throw new Error("continue requires an owned session key and operator response");
    }
    return { project, sessionKey, message: responseParts.join(" "), kind: "continue" };
  }
  throw new Error(`unsupported lifecycle action: ${action}`);
}

export function readPluginSettings(pluginConfig) {
  if (!pluginConfig || typeof pluginConfig !== "object" || Array.isArray(pluginConfig)) {
    throw new Error("context-os plugin config is missing");
  }
  const projects = pluginConfig.projects;
  if (!projects || typeof projects !== "object" || Array.isArray(projects)) {
    throw new Error("context-os plugin config must define projects");
  }
  if (Object.keys(projects).length === 0) {
    throw new Error("context-os plugin config must define at least one project");
  }
  const runTimeoutSeconds = pluginConfig.runTimeoutSeconds ?? 600;
  if (!Number.isInteger(runTimeoutSeconds) || runTimeoutSeconds < 60 || runTimeoutSeconds > 1800) {
    throw new Error("runTimeoutSeconds must be an integer from 60 through 1800");
  }
  return { projects, runTimeoutSeconds };
}

function isWithin(root, candidate) {
  const relative = path.relative(root, candidate);
  return relative === "" || (!relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative));
}

function canonicalPathKey(value) {
  const normalized = path.normalize(value);
  return process.platform === "win32" ? normalized.toLowerCase() : normalized;
}

async function requireCanonicalPath(configuredPath, description, expectedKind) {
  const directInfo = await lstat(configuredPath);
  if (directInfo.isSymbolicLink()) {
    throw new Error(`${description} must not be a symlink or junction`);
  }
  const canonical = await realpath(configuredPath);
  if (canonicalPathKey(path.resolve(configuredPath)) !== canonicalPathKey(canonical)) {
    throw new Error(`${description} must be canonical and contain no symlinked path components`);
  }
  const canonicalInfo = await stat(canonical);
  if (!canonicalInfo[expectedKind]()) {
    throw new Error(`${description} is not a ${expectedKind === "isDirectory" ? "directory" : "file"}`);
  }
  return canonical;
}

async function requireRegularFileInside(root, relativePath) {
  const candidate = path.join(root, relativePath);
  const linkInfo = await lstat(candidate);
  if (!linkInfo.isFile() || linkInfo.isSymbolicLink()) {
    throw new Error(`${relativePath} must be a regular, non-symlink file`);
  }
  const canonical = await realpath(candidate);
  if (!isWithin(root, canonical)) {
    throw new Error(`${relativePath} resolves outside the configured project`);
  }
  return canonical;
}

export async function resolveProject(settings, alias) {
  const configured = settings.projects[alias];
  if (!configured || typeof configured !== "object" || Array.isArray(configured)) {
    throw new Error(`unknown project alias: ${alias}`);
  }
  if (typeof configured.root !== "string" || !path.isAbsolute(configured.root)) {
    throw new Error(`project ${alias} root must be absolute`);
  }
  const root = await requireCanonicalPath(configured.root, `project ${alias} root`, "isDirectory");
  await requireRegularFileInside(root, "AGENTS.md");
  await requireRegularFileInside(root, path.join("scripts", "contextos.sh"));
  return { root };
}

function textFromContent(content) {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((part) => part && typeof part === "object" && part.type === "text" && typeof part.text === "string")
    .map((part) => part.text)
    .join("\n")
    .trim();
}

export function lastAssistantText(messages) {
  if (!Array.isArray(messages)) return "";
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message?.role !== "assistant") continue;
    const text = textFromContent(message.content);
    if (text) return text;
  }
  return "";
}

export function operatorSafeText(value) {
  return [...String(value ?? "")].map((character) => {
    const codePoint = character.codePointAt(0);
    if (character === "\n" || character === "\t" || (codePoint >= 0x20 && codePoint <= 0x7e)) {
      return character;
    }
    return `\\u{${codePoint.toString(16)}}`;
  }).join("");
}

export function lifecyclePrompt(action) {
  if (!LIFECYCLE_ACTIONS.has(action)) throw new Error("invalid lifecycle action");
  return [
    `Invoke the Context OS ${action} lifecycle skill for this repository.`,
    "Treat the runtime working directory as the exact repository root.",
    "Create and report any proposal, including its exact path, digest, and diff, but do not apply it.",
    "Use only lightweight repository context; do not read or quote the separate OpenClaw workspace, USER.md, MEMORY.md, or private host memory.",
    "If setup, update, or end needs operator facts or confirmation, ask for them and wait for a continuation turn instead of inventing them.",
    "Never substitute the private OpenClaw workspace and never search an ancestor for another repository."
  ].join(" ");
}

export function conformancePrompt(action, continuityChallenge) {
  if (!LIFECYCLE_ACTIONS.has(action)) throw new Error("invalid lifecycle action");
  if (action === "setup" && (typeof continuityChallenge !== "string" || !continuityChallenge)) {
    throw new Error("synthetic setup requires a continuity challenge");
  }
  const result = "CONTEXTOS_LIVE_RESULT=";
  const prompts = {
    setup: [
      "Invoke /skill setup, remember the supplied continuity value, ask one setup question, and do not create a proposal in this turn.",
      `When continued, include ${continuityChallenge} verbatim under a dedicated 'Conformance continuity proof' heading in the proposed project context; this is deliberate public-safe synthetic test data, not project narrative. Do not print it in this turn.`,
      `End with ${result}{"status":"awaiting_input"}.`
    ],
    start: [
      "Invoke /skill start and keep the repository read-only. Report the continuity inventory.",
      `Only if the required kernel inventory succeeds, end with ${result}{"status":"started"}.`,
      `If a required kernel or tool call is denied or unavailable, end with ${result}`,
      '{"status":"blocked","reason":"<short-machine-readable-reason>"} instead.'
    ],
    update: [
      "Invoke /skill update with the reviewed synthetic fact 'Live OpenClaw checkpoint completed.'.",
      `Create and show the complete proposal diff, do not apply it, then end with ${result}`,
      '{"proposal":"<repo-relative path>","digest":"<sha256>"}.'
    ],
    end: [
      "Invoke /skill end using this explicitly pre-reviewed and confirmed synthetic draft:",
      "outcome 'OpenClaw live lifecycle exercised', next action 'Review promotion evidence', no durable decision,",
      `and no personal facts. Create and show the complete proposal diff, do not apply it, then end with ${result}`,
      '{"proposal":"<repo-relative path>","digest":"<sha256>"}.'
    ]
  };
  return prompts[action].join(" ");
}

export function conformanceContinuationPrompt(action) {
  if (action !== "setup") throw new Error("synthetic continuation is supported only for setup");
  const result = "CONTEXTOS_LIVE_RESULT=";
  return [
      "Continue the existing /skill setup workflow using only this pre-reviewed synthetic public-safe fixture:",
      "project name 'Lifecycle Fixture' and purpose 'verify Context OS'. Include the continuity value supplied in the",
      "earlier turn verbatim under a dedicated 'Conformance continuity proof' heading; it is deliberately not repeated here.",
      "no personal facts, links, credentials, or imported material. The repository audience is explicitly confirmed",
      `as sanitized and disposable. Create and show the complete proposal diff, do not apply it, then end with ${result}`,
      '{"proposal":"<repo-relative path>","digest":"<sha256>"}.'
  ].join(" ");
}

async function requireDisposableConformanceMarker(root) {
  const marker = await requireRegularFileInside(root, ".context-os-live-disposable");
  if ((await readFile(marker, "utf8")).trim() !== "disposable") {
    throw new Error("synthetic conformance requires a disposable repository marker containing exactly 'disposable'");
  }
}

function requireParams(value, allowedKeys) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("params must be an object");
  }
  const unexpected = Object.keys(value).filter((key) => !allowedKeys.includes(key));
  if (unexpected.length > 0) throw new Error(`unexpected parameter: ${unexpected[0]}`);
  return value;
}

function requireAlias(value) {
  if (typeof value !== "string" || !PROJECT_ALIAS_RE.test(value)) {
    throw new Error("alias must be a configured project alias");
  }
  return value;
}

function requireLifecycleAction(value) {
  if (typeof value !== "string" || !LIFECYCLE_ACTIONS.has(value)) {
    throw new Error("action must be one of setup, start, update, or end");
  }
  return value;
}

function requireOwnedString(value, name) {
  if (typeof value !== "string" || value.length === 0 || value.length > 512) {
    throw new Error(`${name} must be a non-empty string`);
  }
  return value;
}

function requireOperatorMessage(value) {
  if (typeof value !== "string" || value.trim().length === 0 || value.length > MAX_OPERATOR_MESSAGE_CHARS) {
    throw new Error(`message must contain 1 through ${MAX_OPERATOR_MESSAGE_CHARS} characters`);
  }
  return value.trim();
}

function commandPrincipal(ctx) {
  const sender = ctx.senderId ?? ctx.from;
  const conversation = ctx.sessionKey ?? ctx.sessionId;
  if (typeof sender !== "string" || !sender || typeof conversation !== "string" || !conversation) {
    throw new Error("native lifecycle commands require stable sender and conversation identifiers");
  }
  return JSON.stringify({
    sender,
    conversation,
    channel: ctx.channel,
    channelId: ctx.channelId ?? null,
    accountId: ctx.accountId ?? null,
    messageThreadId: ctx.messageThreadId ?? null,
    threadParentId: ctx.threadParentId ?? null
  });
}

function requireAuthenticatedGateway(client) {
  const auth = client?.connect?.auth;
  const credential = auth?.token ?? auth?.password ?? auth?.deviceToken;
  if (typeof credential !== "string" || !credential) {
    throw new Error("Gateway lifecycle methods require an authenticated client credential");
  }
}

function gatewayHandler(run) {
  return async ({ params, client, respond }) => {
    try {
      requireAuthenticatedGateway(client);
      respond(true, await run(params));
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      respond(false, undefined, { code: "contextos_error", message });
    }
  };
}

/**
 * Register both the human command and the operator-only automation API.
 * The ownership maps deliberately live only for this plugin process: callers
 * cannot use result/wait as a general session inspection surface.
 */
export function registerContextOsSurfaces(api, options = {}) {
  const nextId = options.randomId ?? randomUUID;
  const nextCapability = options.randomCapability ?? randomUUID;
  const maxOwnedSessions = options.maxOwnedSessions ?? MAX_OWNED_SESSIONS;
  if (!Number.isInteger(maxOwnedSessions) || maxOwnedSessions < 1 || maxOwnedSessions > MAX_OWNED_SESSIONS) {
    throw new Error(`maxOwnedSessions must be an integer from 1 through ${MAX_OWNED_SESSIONS}`);
  }
  const runs = new Map();
  const sessions = new Map();

  const settings = () => readPluginSettings(api.pluginConfig);
  const capabilityOwner = (value) => {
    const token = requireOwnedString(value, "ownershipToken");
    return `gateway-capability:${createHash("sha256").update(token).digest("hex")}`;
  };

  async function startLifecycle(alias, action, agentId = "main", scenario, ownerKey = "gateway-operator") {
    const parsedAlias = requireAlias(alias);
    const parsedAction = requireLifecycleAction(action);
    const project = await resolveProject(settings(), parsedAlias);
    if (scenario !== undefined && scenario !== CONFORMANCE_SCENARIO) {
      throw new Error(`scenario must be ${CONFORMANCE_SCENARIO}`);
    }
    if (scenario === CONFORMANCE_SCENARIO) {
      await requireDisposableConformanceMarker(project.root);
    }
    if (sessions.size >= maxOwnedSessions) {
      throw new Error("owned lifecycle session limit reached; restart the Gateway before starting another workflow");
    }
    const sessionKey = `agent:${agentId}:subagent:contextos-${nextId()}`;
    const continuityChallenge = scenario === CONFORMANCE_SCENARIO && parsedAction === "setup"
      ? `contextos-continuity-${nextId()}`
      : undefined;
    const { runId } = await api.runtime.subagent.run({
      sessionKey,
      message: scenario === CONFORMANCE_SCENARIO
        ? conformancePrompt(parsedAction, continuityChallenge)
        : `/skill ${parsedAction}`,
      extraSystemPrompt: lifecyclePrompt(parsedAction),
      cwd: project.root,
      deliver: false,
      lightContext: true,
      idempotencyKey: nextId()
    });
    requireOwnedString(runId, "runId");
    runs.set(runId, { sessionKey, ownerKey });
    sessions.set(sessionKey, { alias: parsedAlias, action: parsedAction, agentId, scenario, ownerKey });
    return { runId, sessionKey, ...(continuityChallenge ? { continuityChallenge } : {}) };
  }

  async function continueLifecycle(alias, sessionKey, message, scenario, ownerKey = "gateway-operator") {
    const parsedAlias = requireAlias(alias);
    const parsedSessionKey = requireOwnedString(sessionKey, "sessionKey");
    const owned = sessions.get(parsedSessionKey);
    if (!owned) throw new Error("sessionKey is not owned by this Context OS plugin process");
    if (owned.alias !== parsedAlias) throw new Error("sessionKey is not owned by that project alias");
    if (owned.ownerKey !== ownerKey) throw new Error("sessionKey is not owned by this operator and conversation");
    const project = await resolveProject(settings(), parsedAlias);
    if (owned.scenario === CONFORMANCE_SCENARIO) {
      if (scenario !== CONFORMANCE_SCENARIO || message !== undefined) {
        throw new Error(`synthetic continuation requires scenario ${CONFORMANCE_SCENARIO} and no message`);
      }
      await requireDisposableConformanceMarker(project.root);
    } else if (scenario !== undefined) {
      throw new Error("scenario is not owned by this lifecycle session");
    }
    const { runId } = await api.runtime.subagent.run({
      sessionKey: parsedSessionKey,
      message: owned.scenario === CONFORMANCE_SCENARIO
        ? conformanceContinuationPrompt(owned.action)
        : `Operator response for the Context OS ${owned.action} workflow:\n${requireOperatorMessage(message)}`,
      extraSystemPrompt: lifecyclePrompt(owned.action),
      cwd: project.root,
      deliver: false,
      lightContext: true,
      idempotencyKey: nextId()
    });
    requireOwnedString(runId, "runId");
    runs.set(runId, { sessionKey: parsedSessionKey, ownerKey });
    return { runId, sessionKey: parsedSessionKey };
  }

  async function waitForLifecycle(runId, requestedTimeoutMs, ownerKey = "gateway-operator") {
    const parsedRunId = requireOwnedString(runId, "runId");
    const ownedRun = runs.get(parsedRunId);
    if (!ownedRun) throw new Error("runId is not owned by this Context OS plugin process");
    if (ownedRun.ownerKey !== ownerKey) throw new Error("runId is not owned by this operator");
    const maximum = settings().runTimeoutSeconds * 1000;
    const timeoutMs = requestedTimeoutMs ?? maximum;
    if (!Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > maximum) {
      throw new Error(`timeoutMs must be an integer from 1 through ${maximum}`);
    }
    const result = await api.runtime.subagent.waitForRun({ runId: parsedRunId, timeoutMs });
    if (result?.status !== "running") runs.delete(parsedRunId);
    return result;
  }

  async function lifecycleResult(sessionKey, ownerKey = "gateway-operator") {
    const parsedSessionKey = requireOwnedString(sessionKey, "sessionKey");
    const owned = sessions.get(parsedSessionKey);
    if (!owned) {
      throw new Error("sessionKey is not owned by this Context OS plugin process");
    }
    if (owned.ownerKey !== ownerKey) throw new Error("sessionKey is not owned by this operator");
    const { messages } = await api.runtime.subagent.getSessionMessages({
      sessionKey: parsedSessionKey,
      limit: 20
    });
    return { sessionKey: parsedSessionKey, text: lastAssistantText(messages) };
  }

  api.registerGatewayMethod(
    "contextos.run",
    gatewayHandler(async (rawParams) => {
      const params = requireParams(rawParams, ["alias", "action", "scenario"]);
      const ownershipToken = `contextos-owner-${nextCapability()}`;
      const result = await startLifecycle(
        params.alias, params.action, "main", params.scenario, capabilityOwner(ownershipToken)
      );
      return { ...result, ownershipToken };
    }),
    { scope: "operator.write" }
  );
  api.registerGatewayMethod(
    "contextos.continue",
    gatewayHandler(async (rawParams) => {
      const params = requireParams(
        rawParams, ["alias", "sessionKey", "message", "scenario", "ownershipToken"]
      );
      const result = await continueLifecycle(
        params.alias, params.sessionKey, params.message, params.scenario,
        capabilityOwner(params.ownershipToken)
      );
      return { ...result, ownershipToken: params.ownershipToken };
    }),
    { scope: "operator.write" }
  );
  api.registerGatewayMethod(
    "contextos.wait",
    gatewayHandler(async (rawParams) => {
      const params = requireParams(rawParams, ["runId", "timeoutMs", "ownershipToken"]);
      return await waitForLifecycle(
        params.runId, params.timeoutMs, capabilityOwner(params.ownershipToken)
      );
    }),
    { scope: "operator.read" }
  );
  api.registerGatewayMethod(
    "contextos.result",
    gatewayHandler(async (rawParams) => {
      const params = requireParams(rawParams, ["sessionKey", "ownershipToken"]);
      return await lifecycleResult(
        params.sessionKey, capabilityOwner(params.ownershipToken)
      );
    }),
    { scope: "operator.read" }
  );
  api.registerCommand({
    name: "contextos",
    description: "Run or continue a proposal-gated Context OS lifecycle action",
    acceptsArgs: true,
    requireAuth: true,
    requiredScopes: ["operator.write"],
    async handler(ctx) {
      try {
        if (!ctx.isAuthorizedSender) throw new Error("authorized sender required");
        const command = parseCommandArgs(ctx.args);
        const principal = commandPrincipal(ctx);
        const started = command.kind === "continue"
          ? await continueLifecycle(command.project, command.sessionKey, command.message, undefined, principal)
          : await startLifecycle(command.project, command.action, ctx.agentId || "main", undefined, principal);
        const completed = await waitForLifecycle(started.runId, undefined, principal);
        if (completed.status !== "ok") {
          throw new Error(completed.error || `subagent run ${started.runId} ended with status ${completed.status}`);
        }
        const result = await lifecycleResult(started.sessionKey, principal);
        const owned = sessions.get(started.sessionKey);
        const text = operatorSafeText(
          result.text || `Context OS ${owned?.action ?? "lifecycle"} completed in run ${started.runId}.`
        );
        if (owned?.action === "start") return { text };
        return {
          text: `${text}\n\nContinue this owned workflow with: /contextos ${owned.alias} continue ${started.sessionKey} <response>`
        };
      } catch (error) {
        const message = operatorSafeText(error instanceof Error ? error.message : String(error));
        return { text: `Context OS: ${message}` };
      }
    }
  });

  return { startLifecycle, continueLifecycle, waitForLifecycle, lifecycleResult };
}
