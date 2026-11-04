import { useState, useEffect } from 'react';
import { Database, Download, RefreshCw, ShieldCheck, X, Check, Ban, Copy } from 'lucide-react';
import { api, exportTask } from './bridge';
import { date, display, errorText } from './format';
import { Spinner } from './components';
import type { Task, RecordRow } from './types';

export default function Results({
  selected,
  onSelect,
  notify,
}: {
  selected: string;
  onSelect: (id: string) => void;
  notify: (s: string) => void;
}) {
  const [tasks, setTasks] = useState<Task[]>([]),
    [rows, setRows] = useState<RecordRow[]>([]);
  const [total, setTotal] = useState(0),
    [page, setPage] = useState(0),
    [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(''),
    [detail, setDetail] = useState<RecordRow | null>(null),
    [error, setError] = useState('');
  useEffect(() => {
    api<{ tasks: Task[] }>('/api/tasks?limit=100')
      .then((r) => {
        setTasks(r.tasks);
        if (!selected && r.tasks[0]) onSelect(r.tasks[0].task_id);
      })
      .catch((e) => setError(errorText(e)));
  }, []);
  useEffect(() => setPage(0), [selected]);
  async function load() {
    if (!selected) return;
    setBusy(true);
    setError('');
    try {
      const r = await api<{ records: RecordRow[]; total: number }>(
        '/api/tasks/' + selected + '/results?offset=' + page * 50 + '&limit=50',
      );
      setRows(r.records);
      setTotal(r.total);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    void load();
  }, [selected, page]);
  const fields = [...new Set(rows.flatMap((r) => Object.keys(r.data)))];
  async function save(format: string) {
    setExporting(format);
    try {
      notify('已保存：' + (await exportTask(selected, format)));
    } catch (e) {
      notify(errorText(e));
    } finally {
      setExporting('');
    }
  }
  async function review(status: string) {
    if (!detail) return;
    try {
      await api('/api/tasks/review', { record_id: detail.record_id, status });
      setDetail({ ...detail, review_status: status });
      await load();
    } catch (e) {
      notify(errorText(e));
    }
  }
  return (
    <>
      <div className="section-toolbar">
        <div className="select-field">
          <Database size={17} />
          <select
            aria-label="选择结果任务"
            value={selected}
            onChange={(e) => onSelect(e.target.value)}
          >
            <option value="">选择一个采集任务</option>
            {tasks.map((t) => (
              <option value={t.task_id} key={t.task_id}>
                {t.name}
              </option>
            ))}
          </select>
        </div>
        <div className="button-row">
          <button className="button" disabled={!selected || busy} onClick={load}>
            <RefreshCw size={15} />
            刷新
          </button>
          {['json', 'csv', 'xlsx'].map((f) => (
            <button
              className={'button ' + (f === 'xlsx' ? 'primary' : '')}
              key={f}
              disabled={!total || !!exporting}
              onClick={() => save(f)}
            >
              {exporting === f ? <Spinner /> : <Download size={15} />}导出{' '}
              {f === 'xlsx' ? 'Excel' : f.toUpperCase()}
            </button>
          ))}
        </div>
      </div>
      <div className="notice">
        <ShieldCheck size={19} />
        <div>
          <b>数据与证据，一起保留</b>
          <p>
            点击任意数据行查看来源、定位与内容哈希。数据默认待审核，采集成功不等于业务语义已核验。
          </p>
        </div>
      </div>
      {error && <div className="inline-error">{error}</div>}
      <section className="panel results-panel">
        <div className="panel-heading">
          <h3>
            采集结果 <span>{total.toLocaleString()} 条</span>
          </h3>
          <small>{busy ? '正在读取本地数据…' : '分页读取 · 原始值保留'}</small>
        </div>
        {rows.length ? (
          <div className="data-scroll">
            <table className="data-table result-table">
              <thead>
                <tr>
                  <th className="row-index">#</th>
                  {fields.map((f) => (
                    <th key={f}>{f}</th>
                  ))}
                  <th>审核</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr
                    key={row.record_id}
                    onClick={() => setDetail(row)}
                    tabIndex={0}
                    onKeyDown={(e) => e.key === 'Enter' && setDetail(row)}
                  >
                    <td className="row-index">{page * 50 + i + 1}</td>
                    {fields.map((f) => (
                      <td key={f} title={display(row.data[f])}>
                        {display(row.data[f])}
                      </td>
                    ))}
                    <td>
                      <span className={'review ' + row.review_status}>
                        {row.review_status === 'approved'
                          ? '已审核'
                          : row.review_status === 'rejected'
                            ? '已驳回'
                            : '待审核'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty compact">
            <div className="empty-symbol">
              <Database size={28} />
            </div>
            <h3>还没有采集结果</h3>
            <p>在任务清单中开始一个任务，完成后在这里查看原始数据。</p>
          </div>
        )}
        <div className="table-footer">
          <span>共 {total.toLocaleString()} 条 · 每页50条</span>
          <div className="button-row">
            <button disabled={!page} onClick={() => setPage(page - 1)}>
              上一页
            </button>
            <span>{page + 1}</span>
            <button disabled={(page + 1) * 50 >= total} onClick={() => setPage(page + 1)}>
              下一页
            </button>
          </div>
        </div>
      </section>
      {detail && (
        <div
          className="sheet-backdrop"
          onMouseDown={(e) => e.target === e.currentTarget && setDetail(null)}
        >
          <aside className="evidence-sheet" aria-label="证据与审核">
            <div className="sheet-heading">
              <div>
                <span className="eyebrow">SOURCE EVIDENCE</span>
                <h2>证据与审核</h2>
              </div>
              <button className="icon-button" aria-label="关闭证据" onClick={() => setDetail(null)}>
                <X size={20} />
              </button>
            </div>
            <div className="sheet-body">
              <div className="evidence-block">
                <label>来源网址</label>
                <p className="selectable">{detail.source_url}</p>
                <button
                  className="text-button"
                  onClick={() =>
                    navigator.clipboard
                      .writeText(detail.source_url)
                      .then(() => notify('来源网址已复制'))
                      .catch(() => notify('请手动选择并复制网址'))
                  }
                >
                  <Copy size={13} />
                  复制网址
                </button>
              </div>
              <div className="detail-grid">
                <div>
                  <label>采集时间</label>
                  <p>{date(detail.retrieved_at)}</p>
                </div>
                <div>
                  <label>数据定位</label>
                  <p>{detail.evidence_locator}</p>
                </div>
              </div>
              <div className="evidence-block">
                <label>内容 SHA-256</label>
                <code>{detail.content_hash}</code>
                <p className="small-note">原始内容已存入本地证据目录。</p>
              </div>
              <div className="evidence-values">
                {Object.entries(detail.data).map(([key, value]) => (
                  <div key={key}>
                    <label>{key}</label>
                    <p>{display(value)}</p>
                  </div>
                ))}
              </div>
            </div>
            <div className="sheet-footer">
              <button className="button" onClick={() => review('rejected')}>
                <Ban size={16} />
                驳回
              </button>
              <button className="button primary" onClick={() => review('approved')}>
                <Check size={16} />
                标记已审核
              </button>
            </div>
          </aside>
        </div>
      )}
    </>
  );
}
