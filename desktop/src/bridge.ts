import { invoke, isTauri } from '@tauri-apps/api/core';
import { version } from '../package.json';
export const desktop = isTauri();

export async function api<T>(path: string, body?: unknown): Promise<T> {
  if (desktop)
    return invoke<T>('api_request', {
      method: body === undefined ? 'GET' : 'POST',
      path,
      body: body ?? null,
    });
  const response = await fetch('/runtime-api' + path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.message || value.error || '请求失败');
  return value as T;
}
export async function bootstrap(): Promise<{ state: string; error?: string; version: string }> {
  if (desktop) return invoke('desktop_bootstrap');
  await api('/api/health');
  return { state: 'ready', version };
}
export async function exportTask(taskId: string, format: string): Promise<string> {
  if (desktop) return invoke('save_export', { taskId, format });
  const meta = await api<{ export_id: string; filename: string }>(
    format === 'sqlite' ? '/api/backup' : '/api/tasks/export',
    format === 'sqlite' ? {} : { task_id: taskId, format },
  );
  const response = await fetch('/runtime-api/api/exports/' + meta.export_id);
  if (!response.ok) throw new Error('导出文件下载失败');
  const href = URL.createObjectURL(await response.blob());
  const anchor = document.createElement('a');
  anchor.href = href;
  anchor.download = meta.filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(href), 10000);
  return meta.filename;
}
export async function nativeAction(action: 'hide_to_tray' | 'quit_app') {
  if (desktop) return invoke(action);
}
