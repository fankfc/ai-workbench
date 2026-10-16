"use strict";

// src/preload/index.ts
var import_electron2 = require("electron");

// src/preload/backup.ts
var import_electron = require("electron");
var backupBridge = {
  createBackup: () => import_electron.ipcRenderer.invoke("storage.backup.create", {}),
  restoreBackup: () => import_electron.ipcRenderer.invoke("storage.backup.restore", {})
};

// src/preload/index.ts
var call = (method, input = {}) => import_electron2.ipcRenderer.invoke(`workbench:${method}`, input);
var bridge = {
  ...backupBridge,
  status: () => call("status"),
  retryBackend: () => call("retryBackend"),
  createConversation: (input) => call("createConversation", input),
  listConversations: (input) => call("listConversations", input),
  updateConversation: (input) => call("updateConversation", input),
  deleteConversation: (input) => call("deleteConversation", input),
  listMessages: (input) => call("listMessages", input),
  submitTurn: (input) => call("submitTurn", input),
  cancelTurn: (input) => call("cancelTurn", input),
  getTask: (input) => call("getTask", input),
  chooseFiles: (input) => call("chooseFiles", input),
  listAttachments: (input) => call("listAttachments", input),
  removeAttachment: (input) => call("removeAttachment", input),
  listArtifacts: (input) => call("listArtifacts", input),
  previewArtifact: (input) => call("previewArtifact", input),
  saveArtifact: (input) => call("saveArtifact", input),
  saveArtifactPair: (input) => call("saveArtifactPair", input),
  getSettings: () => call("getSettings"),
  updatePreferences: (input) => call("updatePreferences", input),
  probeConnection: (input) => call("probeConnection", input),
  getUsage: (input) => call("getUsage", input),
  getStorage: () => call("getStorage"),
  previewCleanup: () => call("previewCleanup"),
  cleanupStorage: (input) => call("cleanupStorage", input),
  exportDiagnostics: () => call("exportDiagnostics"),
  previewRelocation: () => call("previewRelocation"),
  relocateStorage: (input) => call("relocateStorage", input),
  getExportDirectory: () => call("getExportDirectory"),
  chooseExportDirectory: () => call("chooseExportDirectory"),
  clearExportDirectory: () => call("clearExportDirectory"),
  subscribePublic: (input, listener) => {
    const receive = (_event, frame) => {
      if (frame?.conversation_id === input.conversationId) listener(frame);
    };
    import_electron2.ipcRenderer.on("workbench:public", receive);
    call("subscribePublic", input).catch(() => {
    });
    return () => {
      import_electron2.ipcRenderer.removeListener("workbench:public", receive);
      call("unsubscribePublic", { conversationId: input.conversationId }).catch(() => {
      });
    };
  }
};
import_electron2.contextBridge.exposeInMainWorld("workbench", Object.freeze(bridge));
