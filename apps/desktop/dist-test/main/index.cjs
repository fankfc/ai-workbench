"use strict";
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: !0 });
}, __copyProps = (to, from, except, desc) => {
  if (from && typeof from == "object" || typeof from == "function")
    for (let key of __getOwnPropNames(from))
      !__hasOwnProp.call(to, key) && key !== except && __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  return to;
};
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: !0 }), mod);

// src/main/index.ts
var index_exports = {};
__export(index_exports, {
  UpdateCoordinator: () => UpdateCoordinator
});
module.exports = __toCommonJS(index_exports);
var import_electron5 = require("electron"), import_node_path8 = require("node:path"), import_promises8 = require("node:fs/promises"), import_node_crypto5 = require("node:crypto"), import_node_url = require("node:url");

// src/main/backend.ts
var import_node_child_process = require("node:child_process"), import_node_crypto = require("node:crypto"), import_node_readline = require("node:readline"), import_node_path = require("node:path"), import_promises = require("node:fs/promises");

// src/shared/validation.ts
function record(value) {
  if (!value || typeof value != "object" || Array.isArray(value)) throw new Error("\u8BF7\u6C42\u5B57\u6BB5\u4E0D\u7B26\u5408\u63A5\u53E3\u8981\u6C42\u3002");
  return value;
}
function exact(value, keys) {
  if (Object.keys(value).some((key) => !keys.includes(key))) throw new Error("\u8BF7\u6C42\u5B57\u6BB5\u4E0D\u7B26\u5408\u63A5\u53E3\u8981\u6C42\u3002");
}
function string(value, max = 128) {
  if (typeof value != "string" || !value.trim() || value.length > max) throw new Error("\u8BF7\u6C42\u5B57\u6BB5\u4E0D\u7B26\u5408\u63A5\u53E3\u8981\u6C42\u3002");
  return value;
}
function id(value) {
  let result = string(value);
  if (!/^[a-zA-Z0-9_-]+$/.test(result)) throw new Error("\u8BF7\u6C42\u5B57\u6BB5\u4E0D\u7B26\u5408\u63A5\u53E3\u8981\u6C42\u3002");
  return result;
}
function acceptHandshake(value, identity, pid) {
  try {
    let v = record(value);
    return v.kind === "backend.ready" && v.instance_id === identity && v.pid === pid && v.protocol_version === "1.0" && Number.isInteger(v.port) && Number(v.port) > 0 && Number(v.port) < 65536;
  } catch {
    return !1;
  }
}
function isTrustedSender(event, window2, url) {
  return event.sender === window2.webContents && event.senderFrame === window2.webContents.mainFrame && event.senderFrame?.url?.split("#")[0] === url;
}
function validateCall(method, value) {
  let v = record(value);
  if (["status", "getSettings", "getStorage", "exportDiagnostics", "retryBackend", "previewRelocation", "getExportDirectory", "chooseExportDirectory", "clearExportDirectory", "storage.backup.create", "storage.backup.restore"].includes(method))
    return exact(v, []), v;
  if (["createConversation"].includes(method))
    return exact(v, ["title"]), string(v.title, 200), v;
  if (method === "listConversations") {
    if (exact(v, ["query", "archived", "offset"]), v.query !== void 0 && (typeof v.query != "string" || v.query.length > 200)) throw new Error("\u641C\u7D22\u5185\u5BB9\u8FC7\u957F\u3002");
    if (v.archived !== void 0 && typeof v.archived != "boolean") throw new Error("\u5F52\u6863\u53C2\u6570\u65E0\u6548\u3002");
    if (v.offset !== void 0 && (!Number.isInteger(v.offset) || Number(v.offset) < 0)) throw new Error("\u5206\u9875\u53C2\u6570\u65E0\u6548\u3002");
    return v;
  }
  if (method === "updateConversation") {
    exact(v, ["conversationId", "title", "pinned", "archived", "expected_version"]), id(v.conversationId), v.title !== void 0 && string(v.title, 200);
    for (let key of ["pinned", "archived"]) if (v[key] !== void 0 && typeof v[key] != "boolean") throw new Error("\u66F4\u65B0\u53C2\u6570\u65E0\u6548\u3002");
    if (v.expected_version !== void 0 && (!Number.isInteger(v.expected_version) || Number(v.expected_version) < 1)) throw new Error("\u7248\u672C\u65E0\u6548\u3002");
    return v;
  }
  if (["listMessages", "chooseFiles", "listAttachments", "listArtifacts", "subscribePublic", "deleteConversation"].includes(method)) {
    if (exact(v, method === "subscribePublic" ? ["conversationId", "afterSeq"] : ["conversationId"]), id(v.conversationId), method === "subscribePublic" && (!Number.isInteger(v.afterSeq) || Number(v.afterSeq) < 0)) throw new Error("\u4E8B\u4EF6\u6E38\u6807\u65E0\u6548\u3002");
    return v;
  }
  if (method === "removeAttachment")
    return exact(v, ["conversationId", "attachmentId"]), id(v.conversationId), id(v.attachmentId), v;
  if (method === "submitTurn") {
    if (exact(v, ["conversationId", "text", "provider_profile_id", "client_request_id", "connection_version", "attachment_ids", "domain", "profile_inputs"]), id(v.conversationId), string(v.text, 65536), id(v.provider_profile_id), id(v.client_request_id), string(v.connection_version), !["code", "paper", "document", "mixed"].includes(String(v.domain))) throw new Error("\u4EFB\u52A1\u7C7B\u578B\u65E0\u6548\u3002");
    if (!Array.isArray(v.attachment_ids) || v.attachment_ids.length > 20) throw new Error("\u9644\u4EF6\u53C2\u6570\u65E0\u6548\u3002");
    if (v.attachment_ids.forEach(id), v.profile_inputs !== void 0) {
      let p = record(v.profile_inputs);
      exact(p, { document: ["audience", "purpose", "source_refs", "formats"], paper: ["research_question", "evidence_refs", "data_refs", "formats"], code: ["requirements", "test_command", "workspace_ref"], mixed: ["data_refs", "formats"] }[String(v.domain)]);
      let ref = (value2) => {
        let path = string(value2, 256);
        if (path === "input/user_request.txt" && v.domain === "document") return;
        let matched = /^input\/attachment_([a-zA-Z0-9_-]+)\.(md|txt|csv|json|pdf|docx)$/.exec(path);
        if (!matched || !v.attachment_ids.includes(matched[1])) throw new Error("\u6750\u6599\u5F15\u7528\u4E0D\u5C5E\u4E8E\u672C\u6B21\u4EFB\u52A1\u3002");
      };
      for (let [key, value2] of Object.entries(p))
        if (["source_refs", "evidence_refs", "data_refs"].includes(key)) {
          if (!Array.isArray(value2) || value2.length > 20) throw new Error("\u6750\u6599\u5F15\u7528\u6570\u91CF\u65E0\u6548\u3002");
          value2.forEach(ref);
        } else if (key === "workspace_ref") ref(value2);
        else if (key === "formats") {
          if (!Array.isArray(value2) || value2.length > 3 || new Set(value2).size !== value2.length || value2.some((item) => !["pdf", "docx", "markdown"].includes(String(item)))) throw new Error("\u6587\u4EF6\u683C\u5F0F\u65E0\u6548\u3002");
        } else if (string(value2, key === "test_command" ? 1024 : 8192), key === "test_command" && /[\r\n\0]/.test(String(value2))) throw new Error("\u6D4B\u8BD5\u547D\u4EE4\u9700\u4E3A\u5355\u884C\u9879\u76EE\u8BF4\u660E\u3002");
      if (JSON.stringify(p).length > 32768) throw new Error("\u4EFB\u52A1\u8D44\u6599\u8FC7\u957F\u3002");
    }
    return v;
  }
  if (method === "cancelTurn" || method === "getTask")
    return exact(v, ["taskId"]), id(v.taskId), v;
  if (method === "probeConnection")
    return exact(v, ["connectionId"]), id(v.connectionId), v;
  if (method === "updatePreferences") {
    if (exact(v, ["expected_version", "preferences"]), !Number.isInteger(v.expected_version) || Number(v.expected_version) < 1) throw new Error("\u504F\u597D\u7248\u672C\u65E0\u6548\u3002");
    let p = record(v.preferences);
    if (exact(p, ["theme", "font_size", "send_shortcut", "close_behavior"]), !["system", "light", "dark"].includes(String(p.theme)) || !["enter", "ctrl-enter"].includes(String(p.send_shortcut)) || !["quit", "minimize"].includes(String(p.close_behavior)) || !Number.isInteger(p.font_size) || Number(p.font_size) < 14 || Number(p.font_size) > 22) throw new Error("\u504F\u597D\u53C2\u6570\u65E0\u6548\u3002");
    return v;
  }
  if (method === "getUsage") {
    exact(v, ["role", "function", "task_id", "offset", "date_from", "date_to"]);
    for (let key of ["role", "function", "date_from", "date_to"]) v[key] !== void 0 && string(v[key], 64);
    if (v.task_id !== void 0 && id(v.task_id), v.offset !== void 0 && (!Number.isInteger(v.offset) || Number(v.offset) < 0)) throw new Error("\u5206\u9875\u53C2\u6570\u65E0\u6548\u3002");
    return v;
  }
  if (method === "previewCleanup")
    return exact(v, []), v;
  if (method === "relocateStorage")
    return exact(v, ["version"]), string(v.version, 256), v;
  if (method === "cleanupStorage") {
    if (exact(v, ["version", "sha256s"]), string(v.version), !Array.isArray(v.sha256s) || v.sha256s.length > 1e4 || v.sha256s.some((hash) => typeof hash != "string" || !/^[a-f0-9]{64}$/.test(hash))) throw new Error("\u6E05\u7406\u7248\u672C\u65E0\u6548\u3002");
    return v;
  }
  if (["previewArtifact", "saveArtifact", "saveArtifactPair"].includes(method)) {
    if (exact(v, ["conversationId", "bundleId", "artifactIds"]), id(v.conversationId), id(v.bundleId), !Array.isArray(v.artifactIds) || v.artifactIds.length !== (method === "saveArtifactPair" ? 2 : 1)) throw new Error("\u6587\u4EF6\u9009\u62E9\u65E0\u6548\u3002");
    return v.artifactIds.forEach(id), v;
  }
  throw new Error("\u4E0D\u652F\u6301\u8BE5\u684C\u9762\u64CD\u4F5C\u3002");
}

// src/main/backend.ts
function runtimeResources(developmentRoot, packaged, resourcesPath) {
  return packaged ? { root: resourcesPath, python: (0, import_node_path.join)(resourcesPath, "python", "python.exe") } : { root: developmentRoot };
}
function childEnvironment(token, instance) {
  let env = {};
  for (let key of ["PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "COMSPEC"]) process.env[key] && (env[key] = process.env[key]);
  return { ...env, PYTHONUTF8: "1", PYTHONUNBUFFERED: "1", WORKBENCH_API_TOKEN: token, WORKBENCH_INSTANCE_ID: instance };
}
var BackendSupervisor = class {
  constructor(options) {
    this.options = options;
    this.status = { state: "offline", provider_mode: options.providerMode, message: "\u672C\u5730\u670D\u52A1\u5C1A\u672A\u8FDE\u63A5\u3002" };
  }
  options;
  token = (0, import_node_crypto.randomBytes)(32).toString("hex");
  child;
  base = "";
  stopping = !1;
  generation = 0;
  starting;
  stopTask;
  attempts = 0;
  backendPid;
  status;
  async start() {
    if (this.stopTask || this.status.state === "stopping") throw new Error("\u672C\u5730\u670D\u52A1\u6B63\u5728\u9000\u51FA\uFF0C\u8BF7\u7A0D\u540E\u91CD\u8BD5\u3002");
    if (this.starting) return this.starting;
    if (this.status.state === "ready") return this.status;
    if (this.child && [this.child.pid, this.backendPid].some((pid) => this.alive(pid))) throw new Error("\u65E7\u7684\u6258\u7BA1\u670D\u52A1\u9000\u51FA\u5C1A\u672A\u786E\u8BA4\uFF0C\u65E0\u6CD5\u91CD\u590D\u542F\u52A8\u3002\u8BF7\u91CD\u8BD5\u9000\u51FA\u5E94\u7528\u3002");
    if (this.attempts >= 3) throw new Error("\u672C\u5730\u670D\u52A1\u591A\u6B21\u542F\u52A8\u5931\u8D25\u3002\u8BF7\u91CD\u65B0\u6253\u5F00\u5E94\u7528\u3002");
    return this.starting = this.launch().finally(() => {
      this.starting = void 0;
    }), this.starting;
  }
  async launch() {
    let generation = this.generation;
    if (this.attempts++, this.stopping = !1, this.status = { ...this.status, state: "starting", message: "\u6B63\u5728\u8FDE\u63A5\u672C\u5730\u670D\u52A1\u2026" }, await (0, import_promises.mkdir)(this.options.dataRoot, { recursive: !0 }), generation !== this.generation)
      throw this.attempts--, new Error("\u672C\u5730\u670D\u52A1\u542F\u52A8\u5DF2\u53D6\u6D88\u3002");
    let instance = (0, import_node_crypto.randomUUID)(), executable = this.options.python ?? (0, import_node_path.join)(this.options.root, "services/orchestrator/.venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python"), child = (this.options.spawnProcess ?? import_node_child_process.spawn)(executable, ["-m", "app.api.launcher", "--host", "127.0.0.1", "--port", "0", "--data-root", this.options.dataRoot, "--provider-mode", this.options.providerMode], { cwd: (0, import_node_path.join)(this.options.root, "services/orchestrator"), env: childEnvironment(this.token, instance), windowsHide: !0, stdio: ["ignore", "pipe", "pipe"] });
    this.child = child, child.stderr?.on("data", () => {
    }), child.on("exit", () => {
      this.child === child && (this.base = "", this.stopping || (this.status = { ...this.status, state: "offline", message: "\u672C\u5730\u670D\u52A1\u5DF2\u65AD\u5F00\u3002\u8349\u7A3F\u5DF2\u4FDD\u5B58\uFF0C\u53EF\u4EE5\u91CD\u8BD5\u8FDE\u63A5\u3002" }));
    });
    try {
      let ready = await new Promise((resolve4, reject) => {
        let settled = !1, lines = (0, import_node_readline.createInterface)({ input: child.stdout }), timeout = setTimeout(() => finish(new Error("\u672C\u5730\u670D\u52A1\u542F\u52A8\u8D85\u65F6\u3002")), this.options.timeoutMs ?? 2e4), earlyExit = () => finish(new Error("\u672C\u5730\u670D\u52A1\u5728\u5C31\u7EEA\u524D\u9000\u51FA\u3002")), failed = () => finish(new Error("\u65E0\u6CD5\u542F\u52A8\u672C\u5730\u670D\u52A1\u3002")), finish = (error, value) => {
          settled || (settled = !0, clearTimeout(timeout), lines.close(), child.off("exit", earlyExit), child.off("error", failed), error ? reject(error) : resolve4(value));
        };
        lines.on("line", async (line) => {
          if (!(line.length > 4096))
            try {
              let value = JSON.parse(line);
              acceptHandshake(value, instance, value.pid) && await this.ownsProcess(value.pid, child.pid) && (this.backendPid = value.pid, finish(void 0, value));
            } catch {
            }
        }), child.once("exit", earlyExit), child.once("error", failed);
      });
      if (generation !== this.generation) throw new Error("\u672C\u5730\u670D\u52A1\u542F\u52A8\u5DF2\u53D6\u6D88\u3002");
      this.base = `http://127.0.0.1:${ready.port}`;
      let health = await this.request("/v1/health", "GET", void 0, Math.min(this.options.timeoutMs ?? 5e3, 5e3));
      if (generation !== this.generation) throw new Error("\u672C\u5730\u670D\u52A1\u542F\u52A8\u5DF2\u53D6\u6D88\u3002");
      if (health.instance_id !== instance || health.pid !== this.backendPid || health.protocol_version !== "1.0" || health.provider_mode !== this.options.providerMode || child.exitCode !== null) throw new Error("\u672C\u5730\u670D\u52A1\u8EAB\u4EFD\u6838\u9A8C\u5931\u8D25\u3002");
      return this.status = { ...this.status, state: "ready", message: this.options.providerMode === "fake" ? "\u6F14\u793A\u6A21\u5F0F\uFF1A\u4F7F\u7528\u6A21\u62DF\u6A21\u578B\u54CD\u5E94\u3002" : "\u672C\u5730\u670D\u52A1\u5DF2\u8FDE\u63A5\u3002" }, this.attempts = 0, this.status;
    } catch (error) {
      let cleaned = await this.terminate();
      generation !== this.generation && (this.attempts = Math.max(0, this.attempts - 1));
      let message = error instanceof Error ? error.message : "\u672C\u5730\u670D\u52A1\u8FDE\u63A5\u5931\u8D25\u3002", failure = cleaned ? message : message + " \u6258\u7BA1\u670D\u52A1\u9000\u51FA\u5C1A\u672A\u786E\u8BA4\uFF0C\u65E0\u6CD5\u91CD\u590D\u542F\u52A8\u3002";
      throw this.stopTask || (this.status = { ...this.status, state: "offline", message: failure }), new Error(failure);
    }
  }
  async ownsProcess(candidate, owner) {
    if (candidate === owner) return !0;
    if (process.platform !== "win32" || !Number.isInteger(candidate) || candidate < 1) return !1;
    let powershell = (0, import_node_path.join)(process.env.SystemRoot ?? "C:/Windows", "System32/WindowsPowerShell/v1.0/powershell.exe"), command = `$candidateProcess = Get-CimInstance Win32_Process -Filter 'ProcessId=${candidate}'; if ($candidateProcess.ParentProcessId -eq ${owner}) { 'owned' }`;
    return new Promise((resolve4) => (0, import_node_child_process.execFile)(powershell, ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command], { windowsHide: !0, timeout: 1e4 }, (error, stdout) => resolve4(!error && stdout.trim() === "owned")));
  }
  async request(path, method = "GET", body, timeoutMs = 1e4) {
    return await (await this.response(path, method, body, timeoutMs)).json();
  }
  async response(path, method = "GET", body, timeoutMs = 1e4, extraHeaders = {}) {
    if (!this.base || !path.startsWith("/v1/") || path.includes("://") || path.includes("..")) throw new Error("\u672C\u5730\u670D\u52A1\u5C1A\u672A\u5C31\u7EEA\u3002");
    let headers = { Authorization: `Bearer ${this.token}`, ...extraHeaders }, content;
    body instanceof Uint8Array ? content = body : body !== void 0 && (content = JSON.stringify(body), Object.assign(headers, { "Content-Type": "application/json" }));
    try {
      let response = await (this.options.fetchRequest ?? fetch)(this.base + path, { method, headers, body: content, signal: AbortSignal.timeout(timeoutMs), redirect: "error" });
      if (!response.ok) {
        let message = "\u672C\u5730\u64CD\u4F5C\u6682\u4E0D\u53EF\u7528\uFF0C\u8BF7\u7A0D\u540E\u91CD\u8BD5\u3002";
        try {
          let error = await response.json();
          typeof error.detail == "string" && /[\u4e00-\u9fff]/.test(error.detail) && error.detail.length < 300 && (message = error.detail);
        } catch {
        }
        throw new Error(message);
      }
      return response;
    } catch (error) {
      throw error instanceof Error && /[\u4e00-\u9fff]/.test(error.message) ? error : new Error("\u672C\u5730\u670D\u52A1\u6682\u65F6\u65E0\u6CD5\u8FDE\u63A5\u3002\u8349\u7A3F\u5DF2\u4FDD\u5B58\uFF0C\u8BF7\u91CD\u8BD5\u3002");
    }
  }
  stop() {
    return this.stopTask ? this.stopTask : (this.generation++, this.stopping = !0, this.status = { ...this.status, state: "stopping", message: "\u6B63\u5728\u4FDD\u5B58\u5F53\u524D\u8FDB\u5EA6\u2026" }, this.stopTask = this.finishStop().finally(() => {
      this.stopTask = void 0;
    }), this.stopTask);
  }
  async finishStop() {
    let saved = !1;
    try {
      saved = (await this.request("/v1/checkpoint", "POST", {}, 2e3)).saved === !0;
    } catch {
    }
    let journalSaved = !0, record2 = async (cleaned2) => {
      try {
        await (0, import_promises.writeFile)((0, import_node_path.join)(this.options.dataRoot, "desktop-recovery.json"), JSON.stringify({ checkpoint_confirmed: saved, cleanup_confirmed: cleaned2, time: (/* @__PURE__ */ new Date()).toISOString() }));
      } catch {
        journalSaved = !1;
      }
    };
    await record2(!1);
    let cleaned = await this.terminate();
    if (await record2(cleaned), this.status = { ...this.status, state: "offline", message: cleaned ? journalSaved ? saved ? "\u5F53\u524D\u8FDB\u5EA6\u5DF2\u4FDD\u5B58\u3002" : "\u4FDD\u5B58\u5C1A\u672A\u786E\u8BA4\uFF0C\u4E0B\u6B21\u542F\u52A8\u5C06\u68C0\u67E5\u6062\u590D\u72B6\u6001\u3002" : "\u672C\u5730\u670D\u52A1\u5DF2\u9000\u51FA\uFF0C\u6062\u590D\u8BB0\u5F55\u5C1A\u672A\u4FDD\u5B58\u3002" : "\u6258\u7BA1\u670D\u52A1\u9000\u51FA\u5C1A\u672A\u786E\u8BA4\uFF0C\u65E0\u6CD5\u91CD\u590D\u542F\u52A8\u3002" + (journalSaved ? "\u5DF2\u8BB0\u5F55\u6062\u590D\u72B6\u6001\uFF0C" : "\u6062\u590D\u8BB0\u5F55\u5C1A\u672A\u4FDD\u5B58\uFF0C") + "\u8BF7\u91CD\u8BD5\u9000\u51FA\u5E94\u7528\u3002" }, !cleaned) throw new Error(this.status.message);
  }
  async relocateTo(destination, persist) {
    let previous = this.options.dataRoot;
    await this.stop();
    try {
      await persist?.(destination), this.options.dataRoot = destination, await this.start();
    } catch (error) {
      throw this.options.dataRoot = previous, await persist?.(previous).catch(() => {
      }), await this.start().catch(() => {
      }), error;
    }
  }
  alive(pid) {
    if (!pid) return !1;
    try {
      return process.kill(pid, 0), !0;
    } catch {
      return !1;
    }
  }
  processesGone(child, pids) {
    return pids.every((pid) => !pid || (pid === child?.pid ? child.exitCode !== null || child.signalCode !== null : !this.alive(pid)));
  }
  async terminate() {
    let child = this.child;
    this.base = "";
    let pids = [child?.pid, this.backendPid], timeout = this.options.terminationTimeoutMs ?? 1500;
    if (!child) return this.processesGone(child, pids);
    if (child.exitCode !== null || !child.pid) {
      let cleaned2 = this.processesGone(child, pids);
      return cleaned2 && this.child === child && (this.child = void 0, this.backendPid = void 0), cleaned2;
    }
    let exited = new Promise((resolve4) => child.once("exit", () => resolve4()));
    if (process.platform === "win32") {
      let taskkill = (0, import_node_path.join)(process.env.SystemRoot ?? "C:/Windows", "System32/taskkill.exe");
      await new Promise((resolve4) => {
        let killer = (this.options.spawnTreeKiller ?? import_node_child_process.spawn)(taskkill, ["/PID", String(child.pid), "/T", "/F"], { windowsHide: !0, stdio: "ignore" }), settled = !1, finish = () => {
          settled || (settled = !0, clearTimeout(timer), resolve4());
        }, timer = setTimeout(() => {
          killer.kill(), finish();
        }, timeout);
        killer.once("exit", finish), killer.once("error", finish);
      }), await Promise.race([exited, new Promise((resolve4) => setTimeout(resolve4, timeout))]);
      let cleaned2 = this.processesGone(child, pids);
      return cleaned2 && this.child === child && (this.child = void 0, this.backendPid = void 0), cleaned2;
    }
    child.kill("SIGTERM"), await Promise.race([exited.then(() => !0), new Promise((resolve4) => setTimeout(() => resolve4(!1), timeout))]) || (child.kill("SIGKILL"), await Promise.race([exited, new Promise((resolve4) => setTimeout(resolve4, timeout))]));
    let cleaned = this.processesGone(child, pids);
    return cleaned && this.child === child && (this.child = void 0, this.backendPid = void 0), cleaned;
  }
};

// src/main/update-coordinator.ts
var import_node_crypto2 = require("node:crypto"), import_node_fs = require("node:fs"), import_promises2 = require("node:fs/promises"), import_node_path2 = require("node:path");

// src/main/updates.ts
function version(value) {
  if (!/^\d+\.\d+\.\d+$/.test(value)) return null;
  let parts = value.split(".").map(Number);
  return parts.every(Number.isSafeInteger) ? parts : null;
}
function compare(left, right) {
  for (let i = 0; i < 3; i++)
    if (left[i] !== right[i]) return left[i] > right[i] ? 1 : -1;
  return 0;
}
function evaluateUpdate(input) {
  let reasons = [], { manifest, current, observed, backup } = input, proposed = version(manifest.version), active = version(current.version), minimum = version(manifest.minCompatibleVersion);
  return (!proposed || !active || !minimum) && reasons.push("VERSION_INVALID"), proposed && active && compare(proposed, active) <= 0 && reasons.push("NETWORK_DOWNGRADE_OR_REPLAY"), minimum && active && compare(active, minimum) < 0 && reasons.push("COMPATIBILITY_WINDOW"), (!Number.isSafeInteger(manifest.sequence) || manifest.sequence <= current.sequence) && reasons.push("MANIFEST_REPLAY"), manifest.channel !== current.channel && reasons.push("CHANNEL_MISMATCH"), (!/^[0-9a-f]{64}$/.test(manifest.packageSha256) || observed.packageSha256 !== manifest.packageSha256) && reasons.push("PACKAGE_HASH_MISMATCH"), (observed.signatureStatus !== "Valid" || observed.chainValid !== !0 || observed.timestampValid !== !0 || observed.testCertificate !== !1) && reasons.push("SIGNATURE_UNTRUSTED"), (!observed.publisherThumbprint || !input.trustedPublisherThumbprints.some((pin) => pin.toUpperCase() === observed.publisherThumbprint.toUpperCase())) && reasons.push("PUBLISHER_UNTRUSTED"), (!Number.isSafeInteger(manifest.targetSchema) || manifest.targetSchema < 1 || !manifest.compatibleRollbackSchemas.includes(current.schema)) && reasons.push("SCHEMA_ROLLBACK_INCOMPATIBLE"), (backup.consistent !== !0 || backup.verified !== !0 || backup.schema !== current.schema || !/^[0-9a-f]{64}$/.test(backup.sha256)) && reasons.push("VERIFIED_BACKUP_REQUIRED"), input.checkpointsSaved !== !0 && reasons.push("TASK_CHECKPOINTS_REQUIRED"), { state: reasons.length ? "REJECTED" : "READY_FOR_EXTERNAL_INSTALL", activeVersion: current.version, reasons };
}

// src/main/update-coordinator.ts
var phases = ["STAGING", "VERIFYING", "QUIESCING", "BACKING_UP", "BACKED_UP", "INSTALLING", "MIGRATING", "CHECKING_HEALTH", "COMMITTING", "COMMITTED", "ROLLING_BACK", "ROLLED_BACK", "REJECTED", "BLOCKED"], terminal = /* @__PURE__ */ new Set(["COMMITTED", "ROLLED_BACK", "REJECTED"]), affecting = /* @__PURE__ */ new Set(["INSTALLING", "MIGRATING", "CHECKING_HEALTH", "COMMITTING", "ROLLING_BACK", "BLOCKED"]), rootsInUse = /* @__PURE__ */ new Set(), maxBytes = 512 * 1024 * 1024, maxBackupBytes = 256 * 1024 * 1024, maxJournalBytes = 64 * 1024, maxEvents = 64, maxRecoveries = 3, maxOperations = 32, hex = (value) => typeof value == "string" && /^[a-f0-9]{64}$/.test(value), UpdateFault = class extends Error {
  constructor(reason) {
    super(reason);
    this.reason = reason;
  }
  reason;
}, UpdateInterrupted = class extends Error {
  constructor(phase) {
    super("UPDATE_INTERRUPTED:" + phase);
    this.phase = phase;
  }
  phase;
};
function fault(reason) {
  throw new UpdateFault(reason);
}
function within(path, root) {
  let value = (0, import_node_path2.relative)((0, import_node_path2.resolve)(root), (0, import_node_path2.resolve)(path));
  return value !== "" && !value.startsWith("..") && !(0, import_node_path2.isAbsolute)(value);
}
function canonical(value) {
  return Array.isArray(value) ? "[" + value.map(canonical).join(",") + "]" : value && typeof value == "object" ? "{" + Object.keys(value).sort().map((k) => JSON.stringify(k) + ":" + canonical(value[k])).join(",") + "}" : JSON.stringify(value);
}
var hashObject = (value) => (0, import_node_crypto2.createHash)("sha256").update(canonical(value)).digest("hex");
function validCurrent(value) {
  return value && /^\d+\.\d+\.\d+$/.test(value.version) && typeof value.channel == "string" && value.channel.length > 0 && Number.isSafeInteger(value.sequence) && value.sequence >= 0 && Number.isSafeInteger(value.schema) && value.schema > 0 && typeof value.packagePath == "string" && (0, import_node_path2.isAbsolute)(value.packagePath) && hex(value.packageSha256);
}
function validManifest(value) {
  return value && Object.keys(value).sort().join(",") === "channel,compatibleRollbackSchemas,minCompatibleVersion,packageSha256,sequence,targetSchema,version" && typeof value.version == "string" && typeof value.minCompatibleVersion == "string" && typeof value.channel == "string" && Number.isSafeInteger(value.sequence) && Number.isSafeInteger(value.targetSchema) && Array.isArray(value.compatibleRollbackSchemas) && value.compatibleRollbackSchemas.length <= 32 && value.compatibleRollbackSchemas.every((v) => Number.isSafeInteger(v) && v > 0) && hex(value.packageSha256);
}
async function noLinks(path) {
  let current = (0, import_node_path2.resolve)(path);
  for (; ; ) {
    try {
      (await (0, import_promises2.lstat)(current)).isSymbolicLink() && fault("UPDATE_LINK_FORBIDDEN");
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
    let parent = (0, import_node_path2.dirname)(current);
    if (parent === current) break;
    current = parent;
  }
}
async function fileHash(path, limit = maxBytes) {
  await noLinks(path);
  let info = await (0, import_promises2.lstat)(path);
  (!info.isFile() || info.nlink !== 1 || info.size > limit) && fault("UPDATE_FILE_INVALID");
  let digest = (0, import_node_crypto2.createHash)("sha256"), count = 0;
  for await (let chunk of (0, import_node_fs.createReadStream)(path))
    count += chunk.length, count > limit && fault("UPDATE_FILE_LIMIT"), digest.update(chunk);
  return count !== info.size && fault("UPDATE_FILE_CHANGED"), digest.digest("hex");
}
async function copyDurably(source, target) {
  await (0, import_promises2.copyFile)(source, target, import_node_fs.constants.COPYFILE_EXCL);
  let handle = await (0, import_promises2.open)(target, "r+");
  try {
    await handle.sync();
  } finally {
    await handle.close();
  }
}
var UpdateCoordinator = class {
  constructor(config, ports) {
    this.ports = ports;
    (![config.root, config.incomingRoot, config.knownGoodRoot].every(import_node_path2.isAbsolute) || !config.trustedPublisherThumbprints.length || config.trustedPublisherThumbprints.some((p) => typeof p != "string" || !p)) && fault("UPDATE_CONFIG_INVALID"), this.config = { root: (0, import_node_path2.resolve)(config.root), incomingRoot: (0, import_node_path2.resolve)(config.incomingRoot), knownGoodRoot: (0, import_node_path2.resolve)(config.knownGoodRoot), trustedPublisherThumbprints: [...config.trustedPublisherThumbprints] }, (this.config.root === this.config.incomingRoot || this.config.root === this.config.knownGoodRoot || within(this.config.root, this.config.incomingRoot) || within(this.config.incomingRoot, this.config.root) || within(this.config.root, this.config.knownGoodRoot) || within(this.config.knownGoodRoot, this.config.root)) && fault("UPDATE_ROOTS_OVERLAP");
  }
  ports;
  config;
  journalPath() {
    return (0, import_node_path2.join)(this.config.root, "update-journal.json");
  }
  operation(journal) {
    return (0, import_node_path2.join)(this.config.root, "transactions", journal.operationId);
  }
  async lock(work) {
    let key = this.config.root.toLowerCase();
    rootsInUse.has(key) && fault("UPDATE_ALREADY_RUNNING"), rootsInUse.add(key);
    try {
      return await noLinks(this.config.root), await (0, import_promises2.mkdir)((0, import_node_path2.join)(this.config.root, "transactions"), { recursive: !0 }), await work();
    } finally {
      rootsInUse.delete(key);
    }
  }
  async readJournal() {
    let path = this.journalPath();
    await noLinks(path);
    try {
      let info = await (0, import_promises2.lstat)(path);
      (!info.isFile() || info.nlink !== 1 || info.size > maxJournalBytes) && fault("UPDATE_JOURNAL_INVALID");
      let j = JSON.parse(await (0, import_promises2.readFile)(path, "utf8"));
      return (j.formatVersion !== 1 || !/^[a-f0-9]{32}$/.test(j.operationId) || !phases.includes(j.phase) || !validCurrent(j.previous) || !validManifest(j.manifest) || j.manifestSha256 !== hashObject(j.manifest) || j.candidateSha256 !== null && !hex(j.candidateSha256) || typeof j.resumePending != "boolean" || !Number.isSafeInteger(j.recoveries) || j.recoveries < 0 || j.recoveries > maxRecoveries || !Array.isArray(j.events) || j.events.length > maxEvents || !Array.isArray(j.reasons) || j.reasons.some((r) => typeof r != "string") || j.backup !== null && (j.backup.relativePath !== "backup.zip" || !hex(j.backup.sha256) || !Number.isSafeInteger(j.backup.schema) || j.backup.schema !== j.previous.schema)) && fault("UPDATE_JOURNAL_INVALID"), await noLinks(this.operation(j)), j;
    } catch (error) {
      if (error.code === "ENOENT") return null;
      throw error;
    }
  }
  async save(journal, phase, notify = !0) {
    journal.events.length >= maxEvents && fault("UPDATE_JOURNAL_LIMIT"), journal.phase = phase, journal.events.push({ phase, at: (/* @__PURE__ */ new Date()).toISOString() });
    let content = JSON.stringify(journal);
    Buffer.byteLength(content) > maxJournalBytes && fault("UPDATE_JOURNAL_LIMIT");
    let temporary = this.journalPath() + "." + (0, import_node_crypto2.randomUUID)() + ".tmp";
    await noLinks(this.journalPath());
    try {
      let handle = await (0, import_promises2.open)(temporary, "wx", 384);
      try {
        await handle.writeFile(content), await handle.sync();
      } finally {
        await handle.close();
      }
      await (0, import_promises2.rename)(temporary, this.journalPath());
    } finally {
      await (0, import_promises2.unlink)(temporary).catch(() => {
      });
    }
    notify && await this.ports.phaseReached?.(phase);
  }
  async current() {
    let value = await this.ports.readCurrent();
    return (!validCurrent(value) || ![this.config.root, this.config.knownGoodRoot].some((root) => within(value.packagePath, root))) && fault("UPDATE_CURRENT_INVALID"), structuredClone(value);
  }
  target(j) {
    return { version: j.manifest.version, channel: j.manifest.channel, sequence: j.manifest.sequence, schema: j.manifest.targetSchema, packagePath: (0, import_node_path2.join)(this.operation(j), "candidate.exe"), packageSha256: j.manifest.packageSha256 };
  }
  async outcome(state, journal, reasons = []) {
    let current = await this.current().catch(() => null);
    return { state, activeVersion: current?.version ?? "unknown", schema: current?.schema ?? null, sequence: current?.sequence ?? null, reasons, operationId: journal?.operationId, manualRecoveryRequired: state === "BLOCKED", message: state === "COMMITTED" ? "\u66F4\u65B0\u5B8C\u6210\u3002" : state === "ROLLED_BACK" ? "\u66F4\u65B0\u672A\u5B8C\u6210\uFF0C\u5DF2\u6062\u590D\u517C\u5BB9\u7684\u4E0A\u4E00\u7248\u672C\u4E0E\u6570\u636E\u3002" : state === "REJECTED" ? "\u66F4\u65B0\u672A\u901A\u8FC7\u6838\u9A8C\uFF0C\u5F53\u524D\u7248\u672C\u548C\u6570\u636E\u4FDD\u7559\u3002" : state === "INTERRUPTED" ? "\u66F4\u65B0\u5DF2\u4E2D\u65AD\uFF0C\u91CD\u65B0\u542F\u52A8\u540E\u5C06\u68C0\u67E5\u6062\u590D\u8FDB\u5EA6\u3002" : "\u66F4\u65B0\u6062\u590D\u53D7\u963B\uFF0C\u8BF7\u4FDD\u7559\u5F53\u524D\u76EE\u5F55\u548C\u6062\u590D\u8BB0\u5F55\u3002" };
  }
  async signed(path, sha256) {
    let observed = await this.ports.verifySignature(path);
    return (observed.signatureStatus !== "Valid" || observed.chainValid !== !0 || observed.timestampValid !== !0 || observed.testCertificate !== !1) && fault("SIGNATURE_UNTRUSTED"), (!observed.publisherThumbprint || !this.config.trustedPublisherThumbprints.some((pin) => pin.toUpperCase() === observed.publisherThumbprint.toUpperCase())) && fault("PUBLISHER_UNTRUSTED"), await fileHash(path) !== sha256 && fault("PACKAGE_HASH_MISMATCH"), { ...observed, packageSha256: sha256 };
  }
  async manifest(j) {
    let receipt = await this.ports.verifyManifest(j.manifest, j.manifestSha256, j.manifest.packageSha256);
    (receipt.authenticated !== !0 || receipt.manifestSha256 !== j.manifestSha256 || receipt.packageSha256 !== j.manifest.packageSha256) && fault("MANIFEST_AUTHENTICATION_FAILED");
  }
  async unchanged(j, allowTarget = !1) {
    let current = await this.current();
    hashObject(current) !== hashObject(j.previous) && (!allowTarget || hashObject(current) !== hashObject(this.target(j))) && fault("AUTHORITATIVE_CURRENT_CHANGED");
  }
  async resumedReject(j, reasons) {
    return j.reasons = reasons, await this.save(j, "REJECTED", !1), this.resumeTerminal(j);
  }
  async resumeTerminal(j) {
    if (!j.resumePending) return this.outcome(j.phase, j, j.reasons);
    try {
      return await this.ports.resume(), j.resumePending = !1, j.reasons = j.reasons.filter((r) => r !== "TASK_RESUME_FAILED"), await this.save(j, j.phase, !1), this.outcome(j.phase, j, j.reasons);
    } catch (error) {
      return j.resumePending = !0, error instanceof UpdateInterrupted ? this.outcome("INTERRUPTED", j, ["INTERRUPTED_" + error.phase]) : (j.reasons.includes("TASK_RESUME_FAILED") || j.reasons.push("TASK_RESUME_FAILED"), await this.save(j, j.phase, !1).catch(() => {
      }), this.outcome("BLOCKED", j, j.reasons));
    }
  }
  async update(manifest, packagePath) {
    return this.lock(async () => {
      let j = null;
      try {
        let existing = await this.readJournal();
        if (existing && (!terminal.has(existing.phase) || existing.resumePending)) return this.outcome("BLOCKED", existing, ["PENDING_UPDATE_RECOVERY_REQUIRED"]);
        let previous = await this.current();
        validManifest(manifest) || fault("MANIFEST_INVALID"), (await (0, import_promises2.readdir)((0, import_node_path2.join)(this.config.root, "transactions"))).length >= maxOperations && fault("UPDATE_OPERATION_LIMIT"), j = { formatVersion: 1, operationId: (0, import_node_crypto2.randomUUID)().replaceAll("-", ""), phase: "STAGING", previous, manifest: structuredClone(manifest), manifestSha256: hashObject(manifest), candidateSha256: null, backup: null, resumePending: !1, recoveries: 0, reasons: [], events: [] }, await (0, import_promises2.mkdir)(this.operation(j)), await this.save(j, "STAGING"), (!(0, import_node_path2.isAbsolute)(packagePath) || !within(packagePath, this.config.incomingRoot)) && fault("UPDATE_PATH_OUTSIDE_INBOX"), await fileHash(packagePath), await fileHash(previous.packagePath);
        let staged = (0, import_node_path2.join)(this.operation(j), "candidate.exe"), predecessor = (0, import_node_path2.join)(this.operation(j), "previous.exe");
        await copyDurably(packagePath, staged), await copyDurably(previous.packagePath, predecessor), j.candidateSha256 = await fileHash(staged), j.candidateSha256 !== manifest.packageSha256 && fault("PACKAGE_HASH_MISMATCH"), await fileHash(predecessor) !== previous.packageSha256 && fault("ROLLBACK_PACKAGE_HASH_MISMATCH"), await this.save(j, "VERIFYING"), await this.manifest(j);
        let observed = await this.signed(staged, j.candidateSha256);
        await this.signed(predecessor, previous.packageSha256);
        let reasons = evaluateUpdate({ manifest: j.manifest, current: previous, observed, trustedPublisherThumbprints: this.config.trustedPublisherThumbprints, backup: { consistent: !1, verified: !1, schema: previous.schema, sha256: "" }, checkpointsSaved: !1 }).reasons.filter((r) => !["VERIFIED_BACKUP_REQUIRED", "TASK_CHECKPOINTS_REQUIRED"].includes(r));
        if (reasons.length) throw new UpdateFault(reasons.join(","));
        j.resumePending = !0, await this.save(j, "QUIESCING");
        let quiet = await this.ports.quiesce();
        (quiet.newTasksStopped !== !0 || quiet.activeWorkStopped !== !0 || quiet.checkpointsSaved !== !0) && fault("TASK_CHECKPOINTS_REQUIRED"), await this.unchanged(j), await this.save(j, "BACKING_UP");
        let created = await this.ports.createBackup(previous), backupPath = (0, import_node_path2.join)(this.operation(j), "backup.zip"), originalHash = await fileHash(created.path, maxBackupBytes);
        await copyDurably(created.path, backupPath);
        let backupHash = await fileHash(backupPath, maxBackupBytes);
        originalHash !== backupHash && fault("BACKUP_CHANGED_DURING_COPY");
        let backup = await this.ports.verifyBackup(backupPath), ready = evaluateUpdate({ manifest: j.manifest, current: previous, observed, trustedPublisherThumbprints: this.config.trustedPublisherThumbprints, backup: { ...backup, sha256: backupHash }, checkpointsSaved: quiet.checkpointsSaved });
        if (ready.state !== "READY_FOR_EXTERNAL_INSTALL") throw new UpdateFault(ready.reasons.join(","));
        j.backup = { relativePath: "backup.zip", sha256: backupHash, schema: backup.schema }, await this.save(j, "BACKED_UP"), await this.unchanged(j), await this.manifest(j), await this.signed(staged, j.candidateSha256);
        let target = this.target(j);
        await this.save(j, "INSTALLING");
        let installed = await this.ports.install(staged, target);
        (installed.version !== target.version || installed.packageSha256 !== target.packageSha256) && fault("INSTALL_RECEIPT_MISMATCH"), await this.save(j, "MIGRATING"), (await this.ports.migrate(target)).schema !== target.schema && fault("MIGRATION_SCHEMA_MISMATCH"), await this.save(j, "CHECKING_HEALTH");
        let health = await this.ports.health(target);
        return (health.healthy !== !0 || health.version !== target.version || health.schema !== target.schema) && fault("FIRST_HEALTH_FAILED"), await this.unchanged(j), await this.save(j, "COMMITTING"), await this.ports.commitCurrent(target), hashObject(await this.current()) !== hashObject(target) && fault("AUTHORITATIVE_COMMIT_MISMATCH"), await this.save(j, "COMMITTED", !1), this.resumeTerminal(j);
      } catch (error) {
        if (error instanceof UpdateInterrupted) return this.outcome("INTERRUPTED", j, ["INTERRUPTED_" + error.phase]);
        let reasons = error instanceof UpdateFault ? error.reason.split(",") : ["UPDATE_OPERATION_FAILED"];
        return j && affecting.has(j.phase) ? this.rollback(j, reasons) : j ? this.resumedReject(j, reasons) : this.outcome("REJECTED", null, reasons);
      }
    });
  }
  async rollback(j, reasons) {
    try {
      await this.unchanged(j, !0);
      let quiet = await this.ports.quiesce();
      (quiet.newTasksStopped !== !0 || quiet.activeWorkStopped !== !0) && fault("ROLLBACK_NOT_QUIESCENT");
      let predecessor = (0, import_node_path2.join)(this.operation(j), "previous.exe"), backupPath = (0, import_node_path2.join)(this.operation(j), "backup.zip");
      await fileHash(predecessor) !== j.previous.packageSha256 && fault("ROLLBACK_PACKAGE_HASH_MISMATCH"), await this.signed(predecessor, j.previous.packageSha256), (!j.backup || j.backup.schema !== j.previous.schema || await fileHash(backupPath, maxBackupBytes) !== j.backup.sha256) && fault("ROLLBACK_BACKUP_HASH_MISMATCH");
      let backup = await this.ports.verifyBackup(backupPath);
      (backup.verified !== !0 || backup.consistent !== !0 || backup.schema !== j.previous.schema) && fault("ROLLBACK_BACKUP_INCOMPATIBLE"), j.reasons = reasons, await this.save(j, "ROLLING_BACK");
      let installed = await this.ports.rollbackInstall(predecessor, j.previous);
      (installed.version !== j.previous.version || installed.packageSha256 !== j.previous.packageSha256) && fault("ROLLBACK_INSTALL_MISMATCH");
      let restored = await this.ports.restoreBackup(backupPath, j.previous);
      (restored.verified !== !0 || restored.schema !== j.previous.schema) && fault("ROLLBACK_SCHEMA_MISMATCH");
      let health = await this.ports.health(j.previous);
      return (health.healthy !== !0 || health.version !== j.previous.version || health.schema !== j.previous.schema) && fault("ROLLBACK_HEALTH_FAILED"), await this.ports.commitCurrent(j.previous), hashObject(await this.current()) !== hashObject(j.previous) && fault("ROLLBACK_COMMIT_MISMATCH"), await this.save(j, "ROLLED_BACK", !1), this.resumeTerminal(j);
    } catch (error) {
      return error instanceof UpdateInterrupted ? this.outcome("INTERRUPTED", j, ["INTERRUPTED_" + error.phase]) : (j.reasons = [...reasons, error instanceof UpdateFault ? error.reason : "ROLLBACK_OPERATION_FAILED"], await this.save(j, "BLOCKED", !1).catch(() => {
      }), this.outcome("BLOCKED", j, j.reasons));
    }
  }
  async recover() {
    return this.lock(async () => {
      let j = null;
      try {
        return j = await this.readJournal(), j ? terminal.has(j.phase) && !j.resumePending ? this.outcome(j.phase, j, j.reasons) : j.recoveries >= maxRecoveries ? this.outcome("BLOCKED", j, ["RECOVERY_ATTEMPTS_EXHAUSTED"]) : (j.recoveries++, await this.save(j, j.phase, !1), terminal.has(j.phase) ? this.resumeTerminal(j) : affecting.has(j.phase) ? this.rollback(j, ["INTERRUPTED_UPDATE_RECOVERY"]) : (await this.unchanged(j), this.resumedReject(j, ["INTERRUPTED_BEFORE_INSTALL"]))) : null;
      } catch (error) {
        return this.outcome("BLOCKED", j, [error instanceof UpdateFault ? error.reason : "RECOVERY_JOURNAL_INVALID"]);
      }
    });
  }
};

// src/main/ipc.ts
var import_electron4 = require("electron"), import_promises6 = require("node:fs/promises");

// src/renderer/chat/public-events.ts
var fields = {
  "message.accepted": ["message_id", "text", "language"],
  "response.pending": ["status"],
  "answer.published": ["message_id", "text", "language", "content_version_id", "approval_id"],
  "artifacts.published": ["bundle_id", "version_id", "artifacts"],
  "request.failed": ["error_code", "text", "language", "action"],
  "request.cancelled": ["text", "language", "cancel_requested", "external_stop_confirmed"],
  "input.required": ["prompt_id", "text", "language"]
};
function parsePublicEvent(value) {
  try {
    let v = record(value);
    if (exact(v, ["schema_version", "event_id", "conversation_id", "turn_id", "task_id", "attempt_id", "sequence", "kind", "payload"]), v.schema_version !== "1.0" || !Number.isInteger(v.sequence) || Number(v.sequence) < 1 || typeof v.kind != "string" || !fields[v.kind]) return null;
    for (let key of ["event_id", "conversation_id", "turn_id", "task_id", "attempt_id"]) id(v[key]);
    let p = record(v.payload);
    if (exact(p, fields[v.kind]), Object.keys(p).length !== fields[v.kind].length) return null;
    if (v.kind === "response.pending") {
      if (p.status !== "pending") return null;
    } else if (v.kind === "artifacts.published") {
      if (id(p.bundle_id), id(p.version_id), !Array.isArray(p.artifacts) || !p.artifacts.length) return null;
      for (let artifact of p.artifacts) {
        let a = record(artifact);
        exact(a, ["artifact_id", "artifact_pair_id", "format", "language", "file_name", "size_bytes"]), id(a.artifact_id), a.artifact_pair_id !== null && id(a.artifact_pair_id);
        for (let key of ["format", "language", "file_name"]) string(a[key], 256);
        if (!Number.isInteger(a.size_bytes) || Number(a.size_bytes) < 0) return null;
      }
    } else {
      if (string(p.text, 1048576), string(p.language, 32), ["request.failed", "request.cancelled"].includes(v.kind) && p.language !== "zh-CN" || v.kind === "input.required" && !["zh-CN", "en"].includes(String(p.language)) || v.kind === "request.cancelled" && (p.cancel_requested !== !0 || p.external_stop_confirmed !== null && typeof p.external_stop_confirmed != "boolean") || v.kind === "request.failed" && !["retry", "reconnect", "provide_input", "none"].includes(String(p.action))) return null;
      for (let key of ["message_id", "content_version_id", "approval_id", "prompt_id", "error_code"]) p[key] !== void 0 && id(p[key]);
    }
    return v;
  } catch {
    return null;
  }
}

// src/main/attachments.ts
var import_electron = require("electron"), import_node_path3 = require("node:path"), import_promises3 = require("node:fs/promises");
async function chooseFiles(window2, backend2, conversation) {
  let result = await import_electron.dialog.showOpenDialog(window2, { title: "\u6DFB\u52A0\u4EFB\u52A1\u6750\u6599", properties: ["openFile", "multiSelections"], filters: [{ name: "\u4EFB\u52A1\u6750\u6599", extensions: ["txt", "md", "pdf", "docx", "csv", "json"] }] });
  if (result.canceled) return [];
  if (result.filePaths.length > 20) throw new Error("\u4E00\u6B21\u6700\u591A\u6DFB\u52A0 20 \u4E2A\u6587\u4EF6\u3002");
  let imported = [];
  for (let path of result.filePaths) {
    let metadata = await (0, import_promises3.stat)(path);
    if (!metadata.isFile() || metadata.size > 20 * 1024 * 1024) throw new Error("\u6587\u4EF6\u8FC7\u5927\u6216\u65E0\u6CD5\u8BFB\u53D6\u3002\u6BCF\u4E2A\u6587\u4EF6\u4E0A\u9650\u4E3A 20 MB\u3002");
    let bytes = new Uint8Array(await (0, import_promises3.readFile)(path)), response = await backend2.response(`/v1/conversations/${conversation}/attachments`, "POST", bytes, 15e3, { "Content-Type": "application/octet-stream", "X-Filename": encodeURIComponent((0, import_node_path3.basename)(path)) });
    imported.push(await response.json());
  }
  return imported;
}

// src/main/artifact-files.ts
var import_electron2 = require("electron"), import_node_crypto3 = require("node:crypto"), import_node_path4 = require("node:path"), import_promises4 = require("node:fs/promises"), import_node_fs2 = require("node:fs");
function safeFilename(name) {
  if (!name || (0, import_node_path4.basename)(name) !== name || /[<>:"/\\|?*\x00-\x1f]/.test(name) || /[. ]$/.test(name) || /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(name)) throw new Error("\u6587\u4EF6\u540D\u79F0\u4E0D\u53D7\u652F\u6301\u3002");
  return name;
}
function verifyBytes(bytes, expected) {
  if (!/^[a-f0-9]{64}$/.test(expected) || (0, import_node_crypto3.createHash)("sha256").update(bytes).digest("hex") !== expected) throw new Error("\u6587\u4EF6\u68C0\u67E5\u5931\u8D25\uFF0C\u6682\u65F6\u65E0\u6CD5\u4FDD\u5B58\u3002");
}
async function saveFilesAtomically(files, operations = { link: import_promises4.link, unlink: import_promises4.unlink }) {
  let temporary = [], saved = [];
  try {
    if (new Set(files.map((file) => file.path.toLocaleLowerCase())).size !== files.length) throw new Error("\u6587\u4EF6\u540D\u79F0\u91CD\u590D\uFF0C\u8BF7\u9009\u62E9\u5176\u4ED6\u4F4D\u7F6E\u3002");
    for (let file of files) {
      await (0, import_promises4.access)((0, import_node_path4.dirname)(file.path), import_node_fs2.constants.W_OK);
      try {
        throw await (0, import_promises4.access)(file.path), new Error("\u540C\u540D\u6587\u4EF6\u5DF2\u5B58\u5728\uFF0C\u8BF7\u9009\u62E9\u5176\u4ED6\u4F4D\u7F6E\u3002");
      } catch (error) {
        if (error.code !== "ENOENT") throw error;
      }
      let temp = (0, import_node_path4.join)((0, import_node_path4.dirname)(file.path), `.workbench-${(0, import_node_crypto3.randomUUID)()}.tmp`);
      temporary.push(temp);
      let handle = await (0, import_promises4.open)(temp, "wx");
      try {
        await handle.writeFile(file.bytes), await handle.sync();
      } finally {
        await handle.close();
      }
    }
    for (let index = 0; index < files.length; index++)
      await operations.link(temporary[index], files[index].path), saved.push(files[index].path);
    return saved.map((path) => (0, import_node_path4.basename)(path));
  } catch (error) {
    let remaining = [];
    for (let path of saved)
      try {
        await operations.unlink(path);
      } catch {
        remaining.push((0, import_node_path4.basename)(path));
      }
    throw remaining.length ? new Error(`\u53CC\u8BED\u6587\u4EF6\u4FDD\u5B58\u672A\u5B8C\u6574\u5B8C\u6210\u3002\u65E0\u6CD5\u64A4\u56DE\u7684\u6587\u4EF6\u4ECD\u5DF2\u4FDD\u5B58\uFF1A${remaining.join("\u3001")}\u3002\u8BF7\u68C0\u67E5\u76EE\u6807\u76EE\u5F55\u540E\u91CD\u8BD5\u3002`) : error instanceof Error && /[\u4e00-\u9fff]/.test(error.message) ? error : new Error("\u4FDD\u5B58\u5931\u8D25\uFF0C\u8BF7\u68C0\u67E5\u76EE\u5F55\u7A7A\u95F4\u548C\u6743\u9650\u540E\u91CD\u8BD5\u3002\u672C\u6B21\u6587\u4EF6\u672A\u4FDD\u5B58\u3002");
  } finally {
    for (let temp of temporary) await (0, import_promises4.unlink)(temp).catch(() => {
    });
  }
}
var ArtifactFiles = class {
  constructor(backend2, window2, defaultDirectory = () => {
  }) {
    this.backend = backend2;
    this.window = window2;
    this.defaultDirectory = defaultDirectory;
  }
  backend;
  window;
  defaultDirectory;
  async selected(input) {
    let bundle = (await this.backend.request(`/v1/conversations/${input.conversationId}/bundles`)).items.find((value) => value.bundle_id === input.bundleId);
    if (!bundle) throw new Error("\u8BE5\u6587\u4EF6\u7EC4\u5C1A\u672A\u53D1\u5E03\u6216\u5DF2\u5931\u6548\u3002");
    let artifacts = input.artifactIds.map((identity) => bundle.artifacts.find((value) => value.artifact_id === identity));
    if (artifacts.some((value) => !value)) throw new Error("\u6587\u4EF6\u4E0D\u5C5E\u4E8E\u5F53\u524D\u4F1A\u8BDD\u3002");
    if (artifacts.length === 2 && (!artifacts[0].artifact_pair_id || artifacts[0].artifact_pair_id !== artifacts[1].artifact_pair_id || artifacts[0].language === artifacts[1].language || artifacts[0].format !== artifacts[1].format)) throw new Error("\u53CC\u8BED\u6587\u4EF6\u7248\u672C\u4E0D\u4E00\u81F4\u3002");
    return artifacts.map((value) => value);
  }
  async save(input) {
    let artifacts = await this.selected(input), paths;
    if (artifacts.length === 2) {
      let selection = await import_electron2.dialog.showOpenDialog(this.window, { title: "\u4FDD\u5B58\u540C\u4E00\u7248\u672C\u7684\u4E24\u4EFD\u6587\u4EF6", defaultPath: this.defaultDirectory(), properties: ["openDirectory", "createDirectory"] });
      if (selection.canceled) return { cancelled: !0, saved: [] };
      paths = artifacts.map((artifact) => (0, import_node_path4.join)(selection.filePaths[0], safeFilename(artifact.file_name)));
    } else {
      let filename = safeFilename(artifacts[0].file_name), directory = this.defaultDirectory(), selection = await import_electron2.dialog.showSaveDialog(this.window, { title: "\u4FDD\u5B58\u6587\u4EF6", defaultPath: directory ? (0, import_node_path4.join)(directory, filename) : filename });
      if (selection.canceled || !selection.filePath) return { cancelled: !0, saved: [] };
      paths = [selection.filePath];
    }
    let files = [];
    for (let index = 0; index < artifacts.length; index++) {
      let artifact = artifacts[index], response = await this.backend.response(`/v1/conversations/${input.conversationId}/bundles/${input.bundleId}/artifacts/${artifact.artifact_id}/download`);
      if (artifact.size_bytes > 128 * 1024 * 1024) throw new Error("\u6587\u4EF6\u8FC7\u5927\uFF0C\u6682\u65F6\u65E0\u6CD5\u4FDD\u5B58\u3002");
      let bytes = new Uint8Array(await response.arrayBuffer());
      if (bytes.length !== artifact.size_bytes) throw new Error("\u6587\u4EF6\u68C0\u67E5\u5931\u8D25\uFF0C\u6682\u65F6\u65E0\u6CD5\u4FDD\u5B58\u3002");
      verifyBytes(bytes, artifact.sha256 ?? response.headers.get("X-Content-SHA256") ?? ""), files.push({ path: paths[index], bytes });
    }
    return { cancelled: !1, saved: await saveFilesAtomically(files) };
  }
  async preview(input) {
    let [artifact] = await this.selected(input);
    try {
      let response = await this.backend.response(`/v1/conversations/${input.conversationId}/bundles/${input.bundleId}/artifacts/${artifact.artifact_id}/preview`), contentType = response.headers.get("Content-Type") ?? "", bytes = new Uint8Array(await response.arrayBuffer());
      if (bytes.length > 20 * 1024 * 1024) throw new Error("\u9884\u89C8\u5185\u5BB9\u8FC7\u5927\uFF0C\u8BF7\u4FDD\u5B58\u540E\u6253\u5F00\u3002");
      return contentType.startsWith("text/plain") ? { available: !0, format: "md", language: artifact.language, text: new TextDecoder("utf-8", { fatal: !0 }).decode(bytes) } : contentType.startsWith("application/pdf") && Buffer.from(bytes.subarray(0, 5)).toString() === "%PDF-" ? { available: !0, format: "pdf", language: artifact.language, data: Buffer.from(bytes).toString("base64") } : { available: !1, format: artifact.format, language: artifact.language, message: "\u6682\u65F6\u65E0\u6CD5\u9884\u89C8\uFF0C\u53EF\u4FDD\u5B58\u540E\u6253\u5F00\u3002" };
    } catch (error) {
      return { available: !1, format: artifact.format, language: artifact.language, message: error instanceof Error && /[\u4e00-\u9fff]/.test(error.message) ? error.message : "\u6682\u65F6\u65E0\u6CD5\u9884\u89C8\uFF0C\u53EF\u4FDD\u5B58\u540E\u6253\u5F00\u3002" };
    }
  }
};

// src/main/backup-ipc.ts
var import_electron3 = require("electron"), import_promises5 = require("node:fs/promises"), import_node_path5 = require("node:path");
var channels = ["storage.backup.create", "storage.backup.restore"], maxBytes2 = 256 * 1024 * 1024;
function installBackupIpc(window2, backend2, url, persist) {
  for (let channel of channels) import_electron3.ipcMain.handle(channel, async (event, input) => {
    if (!isTrustedSender(event, window2, url)) throw new Error("\u8BF7\u6C42\u6765\u6E90\u4E0D\u53D7\u652F\u6301\u3002");
    validateCall(channel, input);
    try {
      if (channel === "storage.backup.create") {
        let selection2 = await import_electron3.dialog.showSaveDialog(window2, { title: "\u4FDD\u5B58\u4E00\u81F4\u6027\u5907\u4EFD", defaultPath: "workbench-backup.zip", filters: [{ name: "\u5DE5\u4F5C\u53F0\u5907\u4EFD", extensions: ["zip"] }] });
        if (selection2.canceled || !selection2.filePath) return { cancelled: !0, saved: !1 };
        let created = await backend2.request("/v1/backups", "POST", {}, 12e4);
        if (created.verified !== !0) throw new Error("\u5907\u4EFD\u5C1A\u672A\u6838\u9A8C\u3002");
        let backupId2 = id(created.backup_id), response = await backend2.response(`/v1/backups/${backupId2}/download`, "GET", void 0, 12e4);
        if (!response.headers.get("Content-Type")?.includes("application/zip")) throw new Error("\u5907\u4EFD\u683C\u5F0F\u4E0D\u53D7\u652F\u6301\u3002");
        let bytes2 = new Uint8Array(await response.arrayBuffer());
        if (bytes2.length > maxBytes2) throw new Error("\u5907\u4EFD\u8D85\u8FC7 256 MB \u4E0A\u9650\u3002");
        return verifyBytes(bytes2, response.headers.get("X-Content-SHA256") ?? ""), await saveFilesAtomically([{ path: selection2.filePath, bytes: bytes2 }]), { cancelled: !1, saved: !0, files_verified: created.files_verified, size_bytes: bytes2.length };
      }
      let selection = await import_electron3.dialog.showOpenDialog(window2, { title: "\u9009\u62E9\u5DE5\u4F5C\u53F0\u5907\u4EFD", properties: ["openFile"], filters: [{ name: "\u5DE5\u4F5C\u53F0\u5907\u4EFD", extensions: ["zip"] }] });
      if (selection.canceled || selection.filePaths.length !== 1) return { cancelled: !0, restored: !1 };
      let selected = selection.filePaths[0], observed = await (0, import_promises5.lstat)(selected);
      if (!observed.isFile() || observed.isSymbolicLink() || observed.nlink !== 1 || observed.size > maxBytes2) throw new Error("\u5907\u4EFD\u6587\u4EF6\u7C7B\u578B\u6216\u5927\u5C0F\u4E0D\u53D7\u652F\u6301\u3002");
      let handle = await (0, import_promises5.open)(selected, "r"), bytes;
      try {
        let current = await handle.stat();
        if (current.dev !== observed.dev || current.ino !== observed.ino || current.size !== observed.size) throw new Error("\u5907\u4EFD\u6587\u4EF6\u5DF2\u6539\u53D8\uFF0C\u8BF7\u91CD\u65B0\u9009\u62E9\u3002");
        bytes = await handle.readFile();
      } finally {
        await handle.close();
      }
      if (bytes.length !== observed.size) throw new Error("\u5907\u4EFD\u6587\u4EF6\u5DF2\u6539\u53D8\uFF0C\u8BF7\u91CD\u65B0\u9009\u62E9\u3002");
      let imported = await (await backend2.response("/v1/backups/import", "POST", bytes, 12e4, { "Content-Type": "application/zip" })).json();
      if (imported.verified !== !0) throw new Error("\u5907\u4EFD\u5C1A\u672A\u6838\u9A8C\u3002");
      let backupId = id(imported.backup_id);
      if ((await import_electron3.dialog.showMessageBox(window2, { type: "question", title: "\u6062\u590D\u5DF2\u6838\u9A8C\u5907\u4EFD", message: `\u5DF2\u6838\u9A8C ${imported.files_verified} \u4E2A\u6587\u4EF6\uFF0C\u6570\u636E\u5E93\u7248\u672C ${imported.schema_version}\u3002`, detail: "\u786E\u8BA4\u540E\u5C06\u5728\u72EC\u7ACB\u76EE\u5F55\u6062\u590D\u5E76\u91CD\u65B0\u8FDE\u63A5\u672C\u5730\u670D\u52A1\u3002\u5F53\u524D\u76EE\u5F55\u4F1A\u4FDD\u7559\u3002\u5907\u4EFD\u4E0D\u542B\u8FDE\u63A5\u51ED\u8BC1\uFF0C\u6062\u590D\u540E\u8BF7\u91CD\u65B0\u6838\u9A8C\u6A21\u578B\u8FDE\u63A5\u3002", buttons: ["\u53D6\u6D88", "\u6062\u590D\u5E76\u91CD\u65B0\u8FDE\u63A5"], defaultId: 0, cancelId: 0, noLink: !0 })).response !== 1) return { cancelled: !0, restored: !1 };
      let result = await backend2.request(`/v1/backups/${backupId}/restore`, "POST", {}, 12e4);
      if (result.verified !== !0 || result.source_retained !== !0 || typeof result.destination != "string" || !(0, import_node_path5.isAbsolute)(result.destination)) throw new Error("\u6062\u590D\u526F\u672C\u5C1A\u672A\u6838\u9A8C\uFF0C\u539F\u76EE\u5F55\u4FDD\u7559\u3002");
      return await backend2.relocateTo(result.destination, persist), {
        cancelled: !1,
        restored: !0,
        verified: !0,
        restart_required: !1,
        source_retained: !0,
        files_verified: result.files_verified,
        credential_restored: !1,
        reconnect_required: !0
      };
    } catch (error) {
      throw new Error(error instanceof Error && /[\u4e00-\u9fff]/.test(error.message) ? error.message : "\u5907\u4EFD\u64CD\u4F5C\u672A\u5B8C\u6210\uFF0C\u539F\u76EE\u5F55\u4FDD\u7559\u3002\u8BF7\u68C0\u67E5\u6587\u4EF6\u3001\u7A7A\u95F4\u548C\u4EFB\u52A1\u72B6\u6001\u3002");
    }
  });
  return () => {
    for (let channel of channels) import_electron3.ipcMain.removeHandler(channel);
  };
}

// src/main/ipc.ts
function installIpc(window2, backend2, url, onPreferences, onFrame, onRelocation, exports2) {
  let removeBackupIpc = installBackupIpc(window2, backend2, url, onRelocation), artifactFiles = new ArtifactFiles(backend2, window2, () => exports2?.path), subscriptions = /* @__PURE__ */ new Map(), methods = ["status", "retryBackend", "createConversation", "listConversations", "updateConversation", "deleteConversation", "listMessages", "submitTurn", "cancelTurn", "getTask", "chooseFiles", "listAttachments", "removeAttachment", "listArtifacts", "previewArtifact", "saveArtifact", "saveArtifactPair", "getSettings", "updatePreferences", "probeConnection", "getUsage", "getStorage", "previewCleanup", "cleanupStorage", "exportDiagnostics", "subscribePublic", "unsubscribePublic", "previewRelocation", "relocateStorage", "getExportDirectory", "chooseExportDirectory", "clearExportDirectory"], relocations = /* @__PURE__ */ new Map(), route = (v) => `/v1/conversations/${v.conversationId}`, startSubscription = (v) => {
    let existing = subscriptions.get(v.conversationId);
    existing && (existing.closed = !0, clearTimeout(existing.timer));
    let subscription = { cursor: v.afterSeq, closed: !1, timer: void 0 };
    subscriptions.set(v.conversationId, subscription);
    let poll = async () => {
      if (!(subscription.closed || window2.isDestroyed()))
        try {
          let text = await (await backend2.response(`${route(v)}/events?after_seq=${subscription.cursor}`)).text();
          for (let block of text.split(/\r?\n\r?\n/)) {
            let data = block.split(/\r?\n/).filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trim()).join(`
`);
            if (data)
              try {
                let frame = parsePublicEvent(JSON.parse(data));
                frame && frame.conversation_id === v.conversationId && frame.sequence > subscription.cursor && (subscription.cursor = frame.sequence, onFrame?.(frame), !subscription.closed && !window2.isDestroyed() && window2.webContents.send("workbench:public", frame));
              } catch {
              }
          }
        } catch {
        } finally {
          subscription.closed || (subscription.timer = setTimeout(poll, 250));
        }
    };
    return poll(), { subscribed: !0 };
  };
  for (let method of methods) import_electron4.ipcMain.handle(`workbench:${method}`, async (event, input) => {
    if (!isTrustedSender(event, window2, url)) throw new Error("\u8BF7\u6C42\u6765\u6E90\u4E0D\u53D7\u652F\u6301\u3002");
    let v = validateCall(method === "unsubscribePublic" ? "listMessages" : method, input);
    try {
      switch (method) {
        case "status":
          return backend2.status;
        case "retryBackend":
          return await backend2.start();
        case "createConversation":
          return await backend2.request("/v1/conversations", "POST", v);
        case "listConversations": {
          let query = new URLSearchParams({ query: String(v.query ?? ""), archived: String(v.archived ?? !1), offset: String(v.offset ?? 0) });
          return await backend2.request(`/v1/conversations?${query}`);
        }
        case "updateConversation": {
          let { conversationId, ...body } = v;
          return await backend2.request(route(v), "PATCH", body);
        }
        case "deleteConversation":
          return await backend2.request(route(v), "DELETE");
        case "listMessages":
          return await backend2.request(`${route(v)}/messages`);
        case "submitTurn": {
          let { conversationId, ...body } = v;
          if (v.profile_inputs) {
            let refs = Object.entries(v.profile_inputs).filter(([key]) => key.endsWith("_ref") || key.endsWith("_refs")).flatMap(([, value]) => Array.isArray(value) ? value : [value]).filter((value) => value !== "input/user_request.txt");
            if (refs.length) {
              let page = await backend2.request(`${route(v)}/attachments`), allowed = new Set(page.items.filter((file) => file.status === "ready" && v.attachment_ids.includes(file.id)).map((file) => `input/attachment_${file.id}.${file.name.split(".").at(-1).toLowerCase()}`));
              if (refs.some((ref) => !allowed.has(ref))) throw new Error("\u6750\u6599\u5F15\u7528\u4E0E\u6240\u9009\u6587\u4EF6\u4E0D\u4E00\u81F4\uFF0C\u8BF7\u91CD\u65B0\u9009\u62E9\u3002");
            }
          }
          return await backend2.request(`${route(v)}/turns`, "POST", body);
        }
        case "cancelTurn":
          return await backend2.request(`/v1/tasks/${v.taskId}/cancel`, "POST", {});
        case "getTask":
          return await backend2.request(`/v1/tasks/${v.taskId}`);
        case "chooseFiles":
          return await chooseFiles(window2, backend2, String(v.conversationId));
        case "listAttachments":
          return await backend2.request(`${route(v)}/attachments`);
        case "removeAttachment":
          return await backend2.request(`${route(v)}/attachments/${v.attachmentId}`, "DELETE");
        case "listArtifacts":
          return await backend2.request(`${route(v)}/bundles`);
        case "previewArtifact":
          return await artifactFiles.preview(v);
        case "saveArtifact":
        case "saveArtifactPair":
          return await artifactFiles.save(v);
        case "getSettings": {
          let settings = await backend2.request("/v1/settings");
          return onPreferences(settings), settings;
        }
        case "updatePreferences": {
          let settings = await backend2.request("/v1/settings", "PATCH", v);
          return onPreferences(settings), settings;
        }
        case "probeConnection":
          return await backend2.request(`/v1/settings/connections/${v.connectionId}/probe`, "POST", {});
        case "getUsage":
          return await backend2.request(`/v1/usage?${new URLSearchParams(Object.entries(v).map(([key, value]) => [key, String(value)]))}`);
        case "getStorage":
          return await backend2.request("/v1/storage");
        case "getExportDirectory":
          return exports2?.status ?? { configured: !1, label: "\u6BCF\u6B21\u4FDD\u5B58\u65F6\u9009\u62E9" };
        case "chooseExportDirectory": {
          if (!exports2) throw new Error("\u76EE\u5F55\u504F\u597D\u6682\u4E0D\u53EF\u7528\u3002");
          let selection = await import_electron4.dialog.showOpenDialog(window2, { title: "\u9009\u62E9\u9ED8\u8BA4\u5BFC\u51FA\u76EE\u5F55", defaultPath: exports2.path, properties: ["openDirectory", "createDirectory"] });
          return selection.canceled ? exports2.status : await exports2.set(selection.filePaths[0]);
        }
        case "clearExportDirectory": {
          if (!exports2) throw new Error("\u76EE\u5F55\u504F\u597D\u6682\u4E0D\u53EF\u7528\u3002");
          return await exports2.set();
        }
        case "previewRelocation": {
          let selection = await import_electron4.dialog.showOpenDialog(window2, { title: "\u9009\u62E9\u65B0\u7684\u672C\u5730\u5B58\u50A8\u76EE\u5F55", properties: ["openDirectory", "createDirectory"] });
          if (selection.canceled) return { cancelled: !0 };
          let destination = selection.filePaths[0], preview = await backend2.request("/v1/storage/relocation-preview", "POST", { destination });
          return relocations.clear(), relocations.set(preview.version, destination), { cancelled: !1, version: preview.version, ready: preview.ready, files: preview.files, required_bytes: preview.required_bytes, source_retained: preview.source_retained };
        }
        case "relocateStorage": {
          let destination = relocations.get(String(v.version));
          if (!destination) throw new Error("\u76EE\u5F55\u9009\u62E9\u5DF2\u5931\u6548\uFF0C\u8BF7\u91CD\u65B0\u9884\u68C0\u3002");
          let result = await backend2.request("/v1/storage/relocate", "POST", v);
          if (result.verified !== !0) throw new Error("\u76EE\u5F55\u8FC1\u79FB\u5C1A\u672A\u6838\u9A8C\u3002");
          return await backend2.relocateTo(destination, onRelocation), relocations.delete(String(v.version)), { verified: !0, restart_required: !1, source_retained: result.source_retained, files_verified: result.files_verified };
        }
        case "previewCleanup":
          return await backend2.request("/v1/storage/cleanup-preview", "POST", {});
        case "cleanupStorage":
          return await backend2.request("/v1/storage/cleanup", "POST", v);
        case "exportDiagnostics": {
          let selection = await import_electron4.dialog.showSaveDialog(window2, { title: "\u4FDD\u5B58\u8131\u654F\u8BCA\u65AD", defaultPath: "workbench-diagnostics.zip" });
          if (selection.canceled || !selection.filePath) return { cancelled: !0, saved: [] };
          let response = await backend2.response("/v1/diagnostics/export", "POST", {});
          if (!response.headers.get("Content-Type")?.includes("application/zip")) throw new Error("\u8BCA\u65AD\u5BFC\u51FA\u683C\u5F0F\u6682\u4E0D\u53EF\u7528\u3002");
          return await (0, import_promises6.writeFile)(selection.filePath, Buffer.from(await response.arrayBuffer()), { flag: "wx" }), { cancelled: !1, saved: ["workbench-diagnostics.zip"] };
        }
        case "subscribePublic":
          return startSubscription(v);
        case "unsubscribePublic": {
          let subscription = subscriptions.get(String(v.conversationId));
          return subscription && (subscription.closed = !0, clearTimeout(subscription.timer), subscriptions.delete(String(v.conversationId))), { subscribed: !1 };
        }
      }
    } catch (error) {
      throw new Error(error instanceof Error && /[\u4e00-\u9fff]/.test(error.message) ? error.message : "\u64CD\u4F5C\u6682\u672A\u5B8C\u6210\uFF0C\u8BF7\u91CD\u8BD5\u3002");
    }
  });
  return () => {
    removeBackupIpc();
    for (let subscription of subscriptions.values())
      subscription.closed = !0, clearTimeout(subscription.timer);
    for (let method of methods) import_electron4.ipcMain.removeHandler(`workbench:${method}`);
  };
}

// src/main/local-assets.ts
var import_node_path6 = require("node:path");
function localAssetPath(root, requestUrl) {
  let url = new URL(requestUrl);
  if (url.protocol !== "workbench:" || url.hostname !== "desktop" || url.search || url.username || url.password) throw new Error("\u8D44\u6E90\u5730\u5740\u65E0\u6548\u3002");
  let path = decodeURIComponent(url.pathname);
  if (path.includes("\\") || path.includes("\0")) throw new Error("\u8D44\u6E90\u5730\u5740\u65E0\u6548\u3002");
  let target = (0, import_node_path6.resolve)(root, "." + path), segment = (0, import_node_path6.relative)(root, target);
  if (!segment || segment.startsWith("..") || (0, import_node_path6.isAbsolute)(segment)) throw new Error("\u8D44\u6E90\u5730\u5740\u65E0\u6548\u3002");
  return target;
}

// src/main/export-directory.ts
var import_promises7 = require("node:fs/promises"), import_node_fs3 = require("node:fs"), import_node_path7 = require("node:path"), import_node_crypto4 = require("node:crypto"), ExportDirectory = class {
  constructor(config) {
    this.config = config;
  }
  config;
  directory;
  async load() {
    try {
      let value = JSON.parse(await (0, import_promises7.readFile)(this.config, "utf8"));
      typeof value.directory == "string" && (0, import_node_path7.isAbsolute)(value.directory) && (this.directory = value.directory);
    } catch {
    }
  }
  get path() {
    return this.directory;
  }
  get status() {
    return { configured: !!this.directory, label: this.directory ? (0, import_node_path7.basename)(this.directory) : "\u6BCF\u6B21\u4FDD\u5B58\u65F6\u9009\u62E9" };
  }
  async set(directory) {
    if (directory) {
      if (!(0, import_node_path7.isAbsolute)(directory)) throw new Error("\u76EE\u5F55\u9009\u62E9\u65E0\u6548\u3002");
      await (0, import_promises7.access)(directory, import_node_fs3.constants.W_OK);
    }
    let temporary = this.config + "." + (0, import_node_crypto4.randomUUID)() + ".tmp";
    try {
      await (0, import_promises7.writeFile)(temporary, JSON.stringify({ directory: directory ?? null }), { mode: 384, flag: "wx" }), await (0, import_promises7.rename)(temporary, this.config), this.directory = directory;
    } finally {
      await (0, import_promises7.unlink)(temporary).catch(() => {
      });
    }
    return this.status;
  }
};

// src/main/index.ts
import_electron5.protocol.registerSchemesAsPrivileged([{ scheme: "workbench", privileges: { standard: !0, secure: !0, supportFetchAPI: !0, corsEnabled: !0 } }]);
var userDataArgument = process.argv.find((value) => value.startsWith("--user-data-dir="));
userDataArgument && import_electron5.app.setPath("userData", (0, import_node_path8.resolve)(userDataArgument.slice(16)));
import_electron5.app.setName("\u534F\u4F5C\u5DE5\u4F5C\u53F0");
var window, backend, quitting = !1, closeBehavior = "quit", cleanup, testState = { frames: [] };
globalThis.__desktopTest = { getPublicFrames: () => structuredClone(testState.frames), getBackendStatus: () => backend?.status, getManagedPid: () => backend?.child?.pid ?? null, getServicePid: () => backend?.backendPid ?? null, stopBackend: () => backend?.stop(), getWindow: () => window };
var lock = import_electron5.app.requestSingleInstanceLock();
lock ? (import_electron5.app.on("second-instance", () => {
  window && (window.isMinimized() && window.restore(), window.show(), window.focus());
}), import_electron5.app.on("activate", () => {
  window?.show(), window?.focus();
}), import_electron5.app.on("before-quit", (event) => {
  quitting || (event.preventDefault(), quitting = !0, backend?.stop().catch(() => {
  }).finally(() => {
    cleanup?.(), import_electron5.app.quit();
  }));
}), import_electron5.app.whenReady().then(async () => {
  let runtime = runtimeResources((0, import_node_path8.resolve)(__dirname, "../../../.."), import_electron5.app.isPackaged, process.resourcesPath), root = runtime.root, providerMode = process.argv.includes("--demo") ? "fake" : "real", rendererRoot = (0, import_node_path8.join)(__dirname, "../renderer"), rendererUrl = "workbench://desktop/index.html";
  import_electron5.protocol.handle("workbench", (request) => {
    try {
      return request.method !== "GET" ? new Response(null, { status: 405 }) : import_electron5.net.fetch((0, import_node_url.pathToFileURL)(localAssetPath(rendererRoot, request.url)).href);
    } catch {
      return new Response(null, { status: 404 });
    }
  });
  let dataRoot = (0, import_node_path8.join)(import_electron5.app.getPath("userData"), "workbench"), managedConfig = (0, import_node_path8.join)(import_electron5.app.getPath("userData"), "managed-storage.json"), exports2 = new ExportDirectory((0, import_node_path8.join)(import_electron5.app.getPath("userData"), "export-directory.json"));
  await exports2.load();
  try {
    let config = JSON.parse(await (0, import_promises8.readFile)(managedConfig, "utf8"));
    typeof config.dataRoot == "string" && (0, import_node_path8.isAbsolute)(config.dataRoot) && (dataRoot = config.dataRoot);
  } catch {
  }
  backend = new BackendSupervisor({ root, dataRoot, providerMode, python: runtime.python }), import_electron5.session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(!1)), window = new import_electron5.BrowserWindow({ width: 1440, height: 900, minWidth: 320, minHeight: 480, show: !1, title: "\u534F\u4F5C\u5DE5\u4F5C\u53F0", webPreferences: { preload: (0, import_node_path8.join)(__dirname, "../preload/index.cjs"), contextIsolation: !0, nodeIntegration: !1, sandbox: !0, webSecurity: !0, allowRunningInsecureContent: !1 } }), window.removeMenu(), window.webContents.setWindowOpenHandler(() => ({ action: "deny" })), window.webContents.on("will-navigate", (event, url) => {
    url !== rendererUrl && event.preventDefault();
  }), window.webContents.on("will-attach-webview", (event) => event.preventDefault()), window.on("close", (event) => {
    !quitting && closeBehavior === "minimize" && (event.preventDefault(), window?.minimize());
  }), window.on("closed", () => {
    window = void 0;
  }), cleanup = installIpc(window, backend, rendererUrl, (settings) => {
    settings?.preferences?.close_behavior && (closeBehavior = settings.preferences.close_behavior);
  }, (frame) => testState.frames.push(frame), async (destination) => {
    let temporary = managedConfig + "." + (0, import_node_crypto5.randomUUID)() + ".tmp";
    try {
      await (0, import_promises8.writeFile)(temporary, JSON.stringify({ dataRoot: destination }), { mode: 384, flag: "wx" }), await (0, import_promises8.rename)(temporary, managedConfig);
    } finally {
      await (0, import_promises8.unlink)(temporary).catch(() => {
      });
    }
  }, exports2), await window.loadURL(rendererUrl), window.show();
  try {
    await backend.start();
  } catch {
  }
}), import_electron5.app.on("window-all-closed", () => import_electron5.app.quit())) : import_electron5.app.quit();
// Annotate the CommonJS export names for ESM import in node:
0 && (module.exports = {
  UpdateCoordinator
});
