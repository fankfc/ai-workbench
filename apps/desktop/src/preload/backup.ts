import { ipcRenderer } from 'electron';
import type { BackupResult } from '../shared/desktop-bridge';
export const backupBridge={
  createBackup:():Promise<BackupResult>=>ipcRenderer.invoke('storage.backup.create',{}),
  restoreBackup:():Promise<BackupResult>=>ipcRenderer.invoke('storage.backup.restore',{}),
};
