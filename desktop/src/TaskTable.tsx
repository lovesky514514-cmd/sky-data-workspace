import { Copy, Database, Link2, Pause, Pencil, Play, Square, Terminal, Trash2 } from 'lucide-react';
import { Spinner, Status } from './components';
import { date } from './format';
import type { Task, TaskAction } from './types';

interface TaskTableProps {
  tasks: Task[];
  ready: boolean;
  busy: ReadonlySet<string>;
  action: (task: Task, action: TaskAction) => Promise<void>;
  onEdit: (task: Task) => void;
  openResults: (task: Task) => void;
  setLogTask: (task: Task) => void;
  setDeleteTarget: (task: Task) => void;
}

function sourceHostname(url: string) {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

function isActive(task: Task) {
  return task.status === 'running' || task.status === 'queued';
}

function runAction(task: Task): TaskAction {
  if (isActive(task)) return 'pause';
  return task.status === 'completed' ? 'rerun' : 'resume';
}

export default function TaskTable(props: TaskTableProps) {
  const { tasks, ready, busy, action, onEdit, openResults, setLogTask, setDeleteTarget } = props;
  return (
    <div className="task-table-scroll">
      <table className="task-table">
        <thead>
          <tr>
            <th>任务名称 / 来源</th>
            <th>状态</th>
            <th>采集进度</th>
            <th>数据量</th>
            <th>最近更新</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <tr key={task.task_id}>
              <td>
                <button
                  className="task-name"
                  onClick={() => onEdit(task)}
                  disabled={isActive(task)}
                >
                  {task.name}
                  <Pencil size={12} />
                </button>
                <div className="task-source">
                  <Link2 size={12} />
                  <span title={task.urls[0]}>{sourceHostname(task.urls[0])}</span>
                  <small>{task.total > 1 ? '+ ' + (task.total - 1) + ' 个来源' : ''}</small>
                </div>
              </td>
              <td>
                <Status value={task.status} />
              </td>
              <td>
                <div className="progress-label">
                  <span>
                    {task.completed + task.failed} / {task.total}
                  </span>
                  <small>{task.progress}%</small>
                </div>
                <div className={'progress-track ' + task.status}>
                  <span style={{ width: task.progress + '%' }} />
                </div>
                {task.failed > 0 && <small className="source-fail">{task.failed} 个来源失败</small>}
              </td>
              <td>
                <b className="record-count">{task.record_count.toLocaleString()}</b>
                <small className="unit-label"> 条</small>
              </td>
              <td className="time-cell">
                {date(task.updated_at)}
                {task.next_run_at && <small>下次 {date(task.next_run_at)}</small>}
              </td>
              <td>
                <div className="row-actions">
                  <button
                    className="run-button"
                    disabled={busy.has(task.task_id) || !ready}
                    title={isActive(task) ? '暂停任务' : '开始或继续任务'}
                    onClick={() => action(task, runAction(task))}
                  >
                    {busy.has(task.task_id) ? (
                      <Spinner />
                    ) : isActive(task) ? (
                      <Pause size={13} />
                    ) : (
                      <Play size={13} />
                    )}
                    <span>
                      {isActive(task)
                        ? '暂停'
                        : task.status === 'paused'
                          ? '继续'
                          : task.status === 'completed'
                            ? '重跑'
                            : '开始'}
                    </span>
                  </button>
                  <button
                    className="icon-button"
                    title="查看结果"
                    aria-label={'查看结果 ' + task.name}
                    onClick={() => openResults(task)}
                  >
                    <Database size={15} />
                  </button>
                  <button
                    className="icon-button"
                    title="运行日志"
                    aria-label={'运行日志 ' + task.name}
                    onClick={() => setLogTask(task)}
                  >
                    <Terminal size={15} />
                  </button>
                  <button
                    className="icon-button"
                    title="复制任务"
                    aria-label={'复制任务 ' + task.name}
                    onClick={() => action(task, 'copy')}
                  >
                    <Copy size={14} />
                  </button>
                  {isActive(task) ? (
                    <button
                      className="icon-button danger-hover"
                      title="取消"
                      aria-label={'取消任务 ' + task.name}
                      onClick={() => action(task, 'cancel')}
                    >
                      <Square size={14} />
                    </button>
                  ) : (
                    <button
                      className="icon-button danger-hover"
                      title="删除"
                      aria-label={'删除任务 ' + task.name}
                      onClick={() => setDeleteTarget(task)}
                    >
                      <Trash2 size={14} />
                    </button>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
