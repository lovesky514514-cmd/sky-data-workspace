import { useState, useCallback } from 'react';
import { ArrowRight, Check, Link2, ChevronLeft, Play, Search, ShieldCheck } from 'lucide-react';
import { api } from './bridge';
import { errorText, parseUrls } from './format';
import { Modal, Spinner, DataTable } from './components';
import type { Task, Preview } from './types';

export default function TaskWizard({
  task,
  onClose,
  onSaved,
}: {
  task?: Task;
  onClose: () => void;
  onSaved: (task: Task) => void;
}) {
  const [step, setStep] = useState(0),
    [name, setName] = useState(task?.name || '');
  const [urls, setUrls] = useState(task?.urls.join('\n') || ''),
    [interval, setInterval] = useState(task?.interval_seconds || 0);
  const [preview, setPreview] = useState<Preview | null>(null),
    [fields, setFields] = useState(task?.fields || []);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [approved, setApproved] = useState(false);
  const close = useCallback(() => {
    if (!busy) onClose();
  }, [busy, onClose]);
  async function sample(skip = false) {
    setError('');
    try {
      if (!name.trim()) throw new Error('请填写任务名称。');
      const values = parseUrls(urls);
      if (skip) {
        setStep(2);
        return;
      }
      setBusy(true);
      const result = await api<Preview>('/api/tasks/preview', { url: values[0] });
      setPreview(result);
      setFields(result.fields);
      setStep(1);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function save(start: boolean) {
    setError('');
    setBusy(true);
    try {
      if (start && !approved) throw new Error('请先确认采集来源。');
      const definition = {
        name: name.trim(),
        urls: parseUrls(urls),
        fields,
        interval_seconds: interval || null,
      };
      let saved = task
        ? await api<Task>('/api/tasks/update', { task_id: task.task_id, definition })
        : await api<Task>('/api/tasks', definition);
      if (start)
        saved = await api<Task>('/api/tasks/action', { task_id: saved.task_id, action: 'start' });
      onSaved(saved);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title={task ? '编辑采集任务' : '新建采集任务'} onClose={close} wide>
      <div className="wizard-steps">
        {['设置来源', '预览与字段', '确认执行'].map((label, i) => (
          <div key={label} className={i <= step ? 'active' : ''}>
            <span>{i < step ? <Check size={14} /> : i + 1}</span>
            {label}
          </div>
        ))}
      </div>
      <div className="modal-body">
        {step === 0 && (
          <div className="wizard-form">
            <label>
              任务名称{' '}
              <input
                aria-label="任务名称"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="例如：公开数据每周更新"
                maxLength={120}
              />
            </label>
            <label>
              来源网址{' '}
              <textarea
                aria-label="来源网址"
                className="url-input"
                value={urls}
                onChange={(e) => setUrls(e.target.value)}
                placeholder={'https://example.com/data\n每行一个来源，最多30个'}
              />
            </label>
            <div className="help-row">
              <Link2 size={15} />
              <span>
                支持静态 HTML、JSON、CSV 和 XML。来源先由你指定，程序不会自动扩大抓取范围。
              </span>
            </div>
            <label>
              更新频率{' '}
              <select value={interval} onChange={(e) => setInterval(Number(e.target.value))}>
                <option value={0}>仅执行一次</option>
                <option value={86400}>每天更新</option>
                <option value={604800}>每周更新</option>
              </select>
            </label>
            <div className="notice subtle">
              <Search size={17} />
              <div>
                <b>从明确的来源开始</b>
                <p>本版本尚未配置全网搜索提供方；PDF / OCR 与动态网页将在后续版本接入。</p>
              </div>
            </div>
          </div>
        )}
        {step === 1 && preview && (
          <>
            <div className="preview-heading">
              <div>
                <span className="tag">{preview.kind}</span>
                <b>{preview.title || '来源小样本'}</b>
              </div>
              <span>检测到 {preview.total_rows.toLocaleString()} 行 · 预览前5行</span>
            </div>
            <label className="field-heading">
              选择要保留的字段 <small>原始证据和来源始终保留</small>
            </label>
            <div className="field-chips">
              {preview.fields.map((f) => (
                <label key={f} className={fields.includes(f) ? 'selected' : ''}>
                  <input
                    type="checkbox"
                    checked={fields.includes(f)}
                    onChange={(e) =>
                      setFields(e.target.checked ? [...fields, f] : fields.filter((v) => v !== f))
                    }
                  />
                  {f}
                </label>
              ))}
            </div>
            <DataTable fields={fields} rows={preview.rows.map((r) => r.data)} />
            {preview.warnings.map((w) => (
              <p className="small-note" key={w}>
                {w}
              </p>
            ))}
          </>
        )}
        {step === 2 && (
          <div className="confirmation">
            <div className="confirm-icon">
              <ShieldCheck size={30} />
            </div>
            <h3>准备好开始采集了</h3>
            <p>程序按来源依次执行，保留原始内容和数据定位，结果先进入待审核状态。</p>
            <dl>
              <div>
                <dt>任务名称</dt>
                <dd>{name}</dd>
              </div>
              <div>
                <dt>来源数量</dt>
                <dd>{urls.split(/\r?\n/).filter((v) => v.trim()).length} 个</dd>
              </div>
              <div>
                <dt>采集字段</dt>
                <dd>{fields.length ? fields.length + ' 个字段' : '自动保留原始字段'}</dd>
              </div>
              <div>
                <dt>更新频率</dt>
                <dd>{interval === 0 ? '仅执行一次' : interval === 86400 ? '每天' : '每周'}</dd>
              </div>
            </dl>
            <label className="checkbox-line">
              <input
                type="checkbox"
                checked={approved}
                onChange={(e) => setApproved(e.target.checked)}
              />
              我已确认这些来源允许采集，并了解结果仍需核验。
            </label>
          </div>
        )}
        {error && (
          <div role="alert" className="inline-error">
            {error}
          </div>
        )}
      </div>
      <div className="modal-footer">
        <button
          className="button ghost"
          disabled={busy}
          onClick={() => (step ? setStep(step - 1) : close())}
        >
          {step ? (
            <>
              <ChevronLeft size={16} />
              上一步
            </>
          ) : (
            '取消'
          )}
        </button>
        <div className="button-row">
          {step === 0 && (
            <>
              <button className="button ghost" disabled={busy} onClick={() => sample(true)}>
                跳过预览
              </button>
              <button className="button primary" disabled={busy} onClick={() => sample()}>
                {busy ? <Spinner /> : <Search size={16} />}预览来源
              </button>
            </>
          )}
          {step === 1 && (
            <button className="button primary" disabled={!fields.length} onClick={() => setStep(2)}>
              确认字段
              <ArrowRight size={16} />
            </button>
          )}
          {step === 2 && (
            <>
              <button className="button" disabled={busy} onClick={() => save(false)}>
                保存草稿
              </button>
              <button
                className="button primary"
                disabled={busy || !approved}
                onClick={() => save(true)}
              >
                {busy ? <Spinner /> : <Play size={15} />}保存并开始
              </button>
            </>
          )}
        </div>
      </div>
    </Modal>
  );
}
