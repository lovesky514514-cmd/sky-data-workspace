import { useState } from 'react';
import {
  Cpu,
  ShieldCheck,
  Database,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  Download,
  Check,
} from 'lucide-react';
import { api, exportTask } from './bridge';
import { errorText } from './format';
import { Spinner } from './components';
import type { AIStatus } from './types';

export default function SettingsView({
  status,
  refresh,
  notify,
}: {
  status: AIStatus | null;
  refresh: () => Promise<void>;
  notify: (s: string) => void;
}) {
  const [busy, setBusy] = useState(''),
    [check, setCheck] = useState<boolean | null>(null);
  async function update(values: object) {
    setBusy('settings');
    try {
      await api('/api/settings', values);
      await refresh();
      notify('设置已保存');
    } catch (e) {
      notify(errorText(e));
    } finally {
      setBusy('');
    }
  }
  async function test() {
    setBusy('test');
    setCheck(null);
    try {
      const r = await api<{ passed: boolean }>('/api/ai/check', {});
      setCheck(r.passed);
    } catch (e) {
      setCheck(false);
      notify(errorText(e));
    } finally {
      setBusy('');
    }
  }
  return (
    <div className="settings-layout">
      <section className="panel settings-card">
        <div className="settings-card-title">
          <div className="settings-icon">
            <Cpu size={22} />
          </div>
          <div>
            <h3>本地 AI 引擎</h3>
            <p>Ollama + Qwen3.5 9B</p>
          </div>
          <label className="switch">
            <input
              aria-label="开启AI"
              type="checkbox"
              disabled={!!busy || !status}
              checked={status?.preferences.ai_enabled ?? true}
              onChange={(e) => update({ ai_enabled: e.target.checked })}
            />
            <span />
          </label>
        </div>
        <div className="model-card">
          <img src="/app-avatar.jpg" alt="应用图标" />
          <div>
            <b>qwen3.5:9b</b>
            <span>
              {status?.ai.details?.parameter_size || '9B'} ·{' '}
              {status?.ai.details?.quantization_level || '本地模型'}
            </span>
          </div>
          <span
            className={'connection ' + (status?.ai.installed && status.ai.connected ? 'on' : '')}
          >
            <i />
            {!status?.preferences.ai_enabled
              ? 'AI已关闭'
              : status?.ai.installed
                ? '已安装'
                : status?.ai.connected
                  ? '模型缺失'
                  : '服务未连接'}
          </span>
        </div>
        <div className="setting-row">
          <div>
            <b>Ollama 服务</b>
            <p>仅连接本机回环地址，不自动下载模型。</p>
          </div>
          <button className="button" disabled={!!busy} onClick={refresh}>
            <RefreshCw size={14} />
            检测连接
          </button>
        </div>
        <div className="setting-row">
          <div>
            <b>推理检查</b>
            <p>实际发送短请求，确认当前模型能够生成回复。</p>
          </div>
          <button className="button" disabled={!!busy || !status?.ai.installed} onClick={test}>
            {busy === 'test' ? <Spinner /> : <CheckCircle2 size={14} />}运行检查
          </button>
        </div>
        {check !== null && (
          <div className={check ? 'notice success' : 'inline-error'}>
            {check ? <Check size={16} /> : <AlertCircle size={16} />}{' '}
            {check ? '真实推理检查通过' : '推理检查未通过，请查看连接或稍后重试。'}
          </div>
        )}
        <div className="setting-row">
          <div>
            <b>计算模式</b>
            <p>CPU 低干扰运行；显存充足时可自行选择 GPU。</p>
          </div>
          <select
            aria-label="计算模式"
            disabled={!!busy || !status}
            value={status?.preferences.gpu_layers ?? 0}
            onChange={(e) => update({ gpu_layers: Number(e.target.value) })}
          >
            <option value={0}>CPU · 低干扰</option>
            <option value={-1}>自动 GPU</option>
          </select>
        </div>
        <div className="setting-row">
          <div>
            <b>CPU 线程</b>
            <p>限制模型推理线程，减少后台资源占用。</p>
          </div>
          <select
            aria-label="CPU线程"
            disabled={!!busy || !status}
            value={status?.preferences.cpu_threads || 4}
            onChange={(e) => update({ cpu_threads: Number(e.target.value) })}
          >
            {[2, 4, 6, 8].map((v) => (
              <option key={v} value={v}>
                {v} 线程
              </option>
            ))}
          </select>
        </div>
        {status?.ai.connected && !status.ai.installed && (
          <div className="notice">
            <AlertCircle size={17} />
            <div>
              <b>请先安装模型</b>
              <p>
                在 Ollama 中执行 <code>ollama pull qwen3.5:9b</code>，完成后重新检测。
              </p>
            </div>
          </div>
        )}
      </section>
      <div>
        <section className="panel settings-card">
          <div className="settings-card-title">
            <div className="settings-icon">
              <Database size={22} />
            </div>
            <div>
              <h3>本地数据</h3>
              <p>任务、证据和运行记录保存在本机</p>
            </div>
          </div>
          <p className="setting-description">
            数据库备份会包含你的任务配置与结果。升级应用不会覆盖已有任务或采集数据。
          </p>
          <button
            className="button"
            disabled={!!busy}
            onClick={async () => {
              setBusy('backup');
              try {
                notify('备份已保存：' + (await exportTask('', 'sqlite')));
              } catch (e) {
                notify(errorText(e));
              } finally {
                setBusy('');
              }
            }}
          >
            {busy === 'backup' ? <Spinner /> : <Download size={15} />}备份数据库
          </button>
        </section>
        <section className="panel settings-card capability-card">
          <div className="settings-card-title">
            <div className="settings-icon">
              <ShieldCheck size={22} />
            </div>
            <div>
              <h3>采集能力</h3>
              <p>当前安装包的实际支持范围</p>
            </div>
          </div>
          {[
            ['静态 HTML / JSON / CSV / XML', '已启用'],
            ['任务队列 / 暂停与恢复', '已启用'],
            ['Excel / CSV / JSON 导出', '已启用'],
            ['全网搜索提供方', '未配置'],
            ['动态网页 / PDF / OCR', '尚未接入'],
          ].map(([name, value]) => (
            <div className="capability-row" key={name}>
              <span>{name}</span>
              <small className={value === '已启用' ? 'available' : ''}>{value}</small>
            </div>
          ))}
          <p className="small-note">
            任务会检查 robots 与公开网络地址；来源不允许访问时会明确记录失败。
          </p>
        </section>
      </div>
    </div>
  );
}
