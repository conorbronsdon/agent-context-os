import { lstat, readFile, readdir, realpath, stat } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import path from "node:path";

export const PROJECT_ALIAS_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/;
export const PROPOSAL_DIGEST_RE = /^[a-f0-9]{64}$/;
export const LIFECYCLE_ACTIONS = new Set(["setup", "start", "update", "end"]);
export const CONFORMANCE_SCENARIO = "synthetic-conformance-v1";

const MAX_PROPOSAL_BYTES = 2 * 1024 * 1024;

export function parseCommandArgs(raw) {
  const parts = String(raw ?? "").trim().split(/\s+/u).filter(Boolean);
  if (parts.length < 2) {
    throw new Error("usage: /contextos <project-alias> <setup|start|update|end|apply> [proposal-digest]");
  }
  const [project, action, digest] = parts;
  if (!PROJECT_ALIAS_RE.test(project)) {
    throw new Error("project must be a configured alias using lowercase letters, digits, '-' or '_'");
  }
  if (LIFECYCLE_ACTIONS.has(action)) {
    if (parts.length !== 2) {
      throw new Error(`/${"contextos"} ${project} ${action} does not accept additional arguments`);
    }
    return { project, action, kind: "lifecycle" };
  }
  if (action === "apply") {
    if (parts.length !== 3 || !PROPOSAL_DIGEST_RE.test(digest ?? "")) {
      throw new Error("apply requires exactly one lowercase 64-character proposal digest");
    }
    return { project, action, digest, kind: "apply" };
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
  if (typeof configured.bashPath !== "string" || !path.isAbsolute(configured.bashPath)) {
    throw new Error(`project ${alias} bashPath must be absolute`);
  }

  const root = await requireCanonicalPath(configured.root, `project ${alias} root`, "isDirectory");
  await requireRegularFileInside(root, "AGENTS.md");
  await requireRegularFileInside(root, path.join("scripts", "contextos.sh"));

  const bashPath = await requireCanonicalPath(configured.bashPath, `project ${alias} bashPath`, "isFile");
  if (isWithin(root, bashPath)) {
    throw new Error(`project ${alias} bashPath must be outside the repository`);
  }
  return { root, bashPath };
}

export async function findProposalByDigest(root, digest) {
  if (!PROPOSAL_DIGEST_RE.test(digest)) {
    throw new Error("invalid proposal digest");
  }
  const proposalDir = path.join(root, ".context-os", "proposals");
  const proposalDirInfo = await lstat(proposalDir);
  if (!proposalDirInfo.isDirectory() || proposalDirInfo.isSymbolicLink()) {
    throw new Error("proposal directory must be a regular, non-symlink directory");
  }
  const canonicalDir = await realpath(proposalDir);
  if (!isWithin(root, canonicalDir)) {
    throw new Error("proposal directory resolves outside the configured project");
  }
  const matches = [];
  for (const entry of await readdir(canonicalDir, { withFileTypes: true })) {
    if (!entry.isFile() || entry.isSymbolicLink() || !entry.name.endsWith(".json")) continue;
    const candidate = path.join(canonicalDir, entry.name);
    const info = await lstat(candidate);
    if (!info.isFile() || info.isSymbolicLink() || info.size > MAX_PROPOSAL_BYTES) continue;
    const canonicalCandidate = await realpath(candidate);
    if (!isWithin(root, canonicalCandidate) || canonicalPathKey(candidate) !== canonicalPathKey(canonicalCandidate)) {
      continue;
    }
    let parsed;
    try {
      parsed = JSON.parse(await readFile(candidate, "utf8"));
    } catch {
      continue;
    }
    if (parsed?.proposal_digest === digest) matches.push(candidate);
  }
  if (matches.length === 0) throw new Error(`no proposal matches digest ${digest}`);
  if (matches.length !== 1) throw new Error(`multiple proposals match digest ${digest}`);
  const relative = path.relative(root, matches[0]);
  if (!isWithin(root, matches[0]) || relative === "" || path.isAbsolute(relative)) {
    throw new Error("matched proposal is outside the configured project");
  }
  return relative.split(path.sep).join("/");
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

export function lifecyclePrompt(action) {
  if (!LIFECYCLE_ACTIONS.has(action)) throw new Error("invalid lifecycle action");
  return [
    `Invoke the Context OS ${action} lifecycle skill for this repository.`,
    "Treat the runtime working directory as the exact repository root.",
    "Create and report any proposal, including its exact path, digest, and diff, but do not apply it.",
    "Never substitute the private OpenClaw workspace and never search an ancestor for another repository."
  ].join(" ");
}

export function conformancePrompt(action) {
  if (!LIFECYCLE_ACTIONS.has(action)) throw new Error("invalid lifecycle action");
  const result = "CONTEXTOS_LIVE_RESULT=";
  const prompts = {
    setup: [
      "Invoke /skill setup using only this pre-reviewed synthetic public-safe fixture:",
      "project name 'Lifecycle Fixture', purpose 'verify Context OS', current focus 'complete live conformance',",
      "no personal facts, links, credentials, or imported material. The repository audience is explicitly confirmed",
      `as sanitized and disposable. Create and show the complete proposal diff, do not apply it, then end with ${result}`,
      '{"proposal":"<repo-relative path>","digest":"<sha256>"}.'
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

async function requireDisposableConformanceMarker(root) {
  const marker = await requireRegularFileInside(root, ".context-os-live-disposable");
  if ((await readFile(marker, "utf8")).trim() !== "disposable") {
    throw new Error("synthetic conformance requires a disposable repository marker containing exactly 'disposable'");
  }
}

export function renderProcessFailure(result) {
  const output = [result?.stdout, result?.stderr].filter((value) => typeof value === "string" && value.trim()).join("\n").trim();
  const suffix = output ? `\n${output}` : "";
  return `Context OS apply failed (exit=${String(result?.code)}, termination=${String(result?.termination)}).${suffix}`;
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

function gatewayHandler(run) {
  return async ({ params, respond }) => {
    try {
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
  const runs = new Map();
  const sessions = new Set();

  const settings = () => readPluginSettings(api.pluginConfig);

  async function startLifecycle(alias, action, agentId = "main", scenario) {
    const parsedAlias = requireAlias(alias);
    const parsedAction = requireLifecycleAction(action);
    const project = await resolveProject(settings(), parsedAlias);
    if (scenario !== undefined && scenario !== CONFORMANCE_SCENARIO) {
      throw new Error(`scenario must be ${CONFORMANCE_SCENARIO}`);
    }
    if (scenario === CONFORMANCE_SCENARIO) {
      await requireDisposableConformanceMarker(project.root);
    }
    const sessionKey = `agent:${agentId}:subagent:contextos-${nextId()}`;
    const { runId } = await api.runtime.subagent.run({
      sessionKey,
      message: scenario === CONFORMANCE_SCENARIO ? conformancePrompt(parsedAction) : `/skill ${parsedAction}`,
      extraSystemPrompt: lifecyclePrompt(parsedAction),
      cwd: project.root,
      deliver: false,
      lightContext: false,
      idempotencyKey: nextId()
    });
    requireOwnedString(runId, "runId");
    runs.set(runId, sessionKey);
    sessions.add(sessionKey);
    return { runId, sessionKey };
  }

  async function waitForLifecycle(runId, requestedTimeoutMs) {
    const parsedRunId = requireOwnedString(runId, "runId");
    if (!runs.has(parsedRunId)) throw new Error("runId is not owned by this Context OS plugin process");
    const maximum = settings().runTimeoutSeconds * 1000;
    const timeoutMs = requestedTimeoutMs ?? maximum;
    if (!Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > maximum) {
      throw new Error(`timeoutMs must be an integer from 1 through ${maximum}`);
    }
    return await api.runtime.subagent.waitForRun({ runId: parsedRunId, timeoutMs });
  }

  async function lifecycleResult(sessionKey) {
    const parsedSessionKey = requireOwnedString(sessionKey, "sessionKey");
    if (!sessions.has(parsedSessionKey)) {
      throw new Error("sessionKey is not owned by this Context OS plugin process");
    }
    const { messages } = await api.runtime.subagent.getSessionMessages({
      sessionKey: parsedSessionKey,
      limit: 20
    });
    return { sessionKey: parsedSessionKey, text: lastAssistantText(messages) };
  }

  async function applyProposal(alias, digest) {
    const parsedAlias = requireAlias(alias);
    if (typeof digest !== "string" || !PROPOSAL_DIGEST_RE.test(digest)) {
      throw new Error("digest must be a lowercase 64-character proposal digest");
    }
    const currentSettings = settings();
    const project = await resolveProject(currentSettings, parsedAlias);
    const proposal = await findProposalByDigest(project.root, digest);
    const result = await api.runtime.system.runCommandWithTimeout(
      [
        project.bashPath,
        "scripts/contextos.sh",
        "apply",
        proposal,
        "--confirm",
        digest,
        "--runtime",
        "openclaw"
      ],
      {
        cwd: project.root,
        timeoutMs: currentSettings.runTimeoutSeconds * 1000,
        maxOutputBytes: 1024 * 1024,
        maxPreservedOutputLines: 200,
        killProcessTree: true
      }
    );
    if (result.code !== 0 || result.termination !== "exit") {
      throw new Error(renderProcessFailure(result));
    }
    const output = [result.stdout, result.stderr]
      .filter((value) => value?.trim())
      .join("\n")
      .trim();
    return { digest, output: output || `Applied proposal ${digest}.` };
  }

  api.registerGatewayMethod(
    "contextos.run",
    gatewayHandler(async (rawParams) => {
      const params = requireParams(rawParams, ["alias", "action", "scenario"]);
      return await startLifecycle(params.alias, params.action, "main", params.scenario);
    }),
    { scope: "operator.write" }
  );
  api.registerGatewayMethod(
    "contextos.wait",
    gatewayHandler(async (rawParams) => {
      const params = requireParams(rawParams, ["runId", "timeoutMs"]);
      return await waitForLifecycle(params.runId, params.timeoutMs);
    }),
    { scope: "operator.read" }
  );
  api.registerGatewayMethod(
    "contextos.result",
    gatewayHandler(async (rawParams) => {
      const params = requireParams(rawParams, ["sessionKey"]);
      return await lifecycleResult(params.sessionKey);
    }),
    { scope: "operator.read" }
  );
  api.registerGatewayMethod(
    "contextos.apply",
    gatewayHandler(async (rawParams) => {
      const params = requireParams(rawParams, ["alias", "digest"]);
      return await applyProposal(params.alias, params.digest);
    }),
    { scope: "operator.write" }
  );

  api.registerCommand({
    name: "contextos",
    description: "Run or apply a proposal-gated Context OS lifecycle action",
    acceptsArgs: true,
    requireAuth: true,
    requiredScopes: ["operator.write"],
    async handler(ctx) {
      try {
        if (!ctx.isAuthorizedSender) throw new Error("authorized sender required");
        const command = parseCommandArgs(ctx.args);
        if (command.kind === "apply") {
          const applied = await applyProposal(command.project, command.digest);
          return { text: applied.output };
        }
        const started = await startLifecycle(command.project, command.action, ctx.agentId || "main");
        const completed = await waitForLifecycle(started.runId);
        if (completed.status !== "ok") {
          throw new Error(completed.error || `subagent run ${started.runId} ended with status ${completed.status}`);
        }
        const result = await lifecycleResult(started.sessionKey);
        return { text: result.text || `Context OS ${command.action} completed in run ${started.runId}.` };
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        return { text: `Context OS: ${message}` };
      }
    }
  });

  return { startLifecycle, waitForLifecycle, lifecycleResult, applyProposal };
}
