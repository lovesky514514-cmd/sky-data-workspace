export const statusNames: Record<string, string> = {
  draft: '草稿',
  queued: '排队中',
  running: '采集中',
  paused: '已暂停',
  completed: '已完成',
  partial: '部分完成',
  failed: '执行失败',
  cancelled: '已取消',
};
export function date(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.valueOf())
    ? '—'
    : d.toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      });
}
export function display(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}
export function parseUrls(text: string): string[] {
  const values = [
    ...new Set(
      text
        .split(/\r?\n/)
        .map((v) => v.trim())
        .filter(Boolean),
    ),
  ];
  if (!values.length || values.length > 30) throw new Error('请输入 1–30 个来源网址，每行一个。');
  for (const value of values) {
    let parsed: URL;
    try {
      parsed = new URL(value);
    } catch {
      throw new Error('来源网址格式不正确。');
    }
    if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password)
      throw new Error('请使用不含账号密码的 HTTP / HTTPS 网址。');
  }
  return values;
}
export function errorText(value: unknown): string {
  return value instanceof Error
    ? value.message
    : typeof value === 'string'
      ? value
      : '操作失败，请稍后重试。';
}
