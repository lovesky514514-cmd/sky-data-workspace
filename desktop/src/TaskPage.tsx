import { useState } from 'react';
import {
  Activity,
  ArrowUpRight,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Database,
  Link2,
  ListTodo,
  Plus,
  Search,
  ShieldCheck,
  Sparkles,
  X,
} from 'lucide-react';
import { Modal } from './components';
import TaskTable from './TaskTable';
import TaskLogDialog from './TaskLogDialog';
import { PAGE_SIZE, useTasks } from './useTasks';
import type { Task } from './types';

interface TaskPageProps {
  model: ReturnType<typeof useTasks>;
  ready: boolean;
  onEdit: (task: Task) => void;
  onNewTask: () => void;
  openResults: (task: Task) => void;
  onAssistant: () => void;
  notify: (message: string) => void;
}

export default function TaskPage({
  model,
  ready,
  onEdit,
  onNewTask,
  openResults,
  onAssistant,
  notify,
}: TaskPageProps) {
  const { list, busy, action, query, setPage, setSearch, setFilter } = model;
  const { page, search, filter } = query;
  const [logTask, setLogTask] = useState<Task | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Task | null>(null);
  const all = Object.values(list.counts).reduce((sum, count) => sum + count, 0);
  const running = (list.counts.running ?? 0) + (list.counts.queued ?? 0);

  return (
    <>
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-top">
            <span>全部任务</span>
            <div className="stat-icon blue">
              <ListTodo size={18} />
            </div>
          </div>
          <strong>
            {all}
            <small>个</small>
          </strong>
          <p>你的本地采集工作清单</p>
        </div>
        <div className="stat-card">
          <div className="stat-top">
            <span>正在执行</span>
            <div className="stat-icon cyan">
              <Activity size={18} />
            </div>
          </div>
          <strong>
            {running}
            <small>个</small>
          </strong>
          <p>
            <i className={running ? 'live-dot' : ''} />
            {running ? '采集引擎正在处理任务' : '当前队列空闲'}
          </p>
        </div>
        <div className="stat-card">
          <div className="stat-top">
            <span>已采集数据</span>
            <div className="stat-icon violet">
              <Database size={18} />
            </div>
          </div>
          <strong>
            {list.records.toLocaleString()}
            <small>条</small>
          </strong>
          <p>保留来源、时间与内容哈希</p>
        </div>
        <div className="stat-card">
          <div className="stat-top">
            <span>已完成任务</span>
            <div className="stat-icon green">
              <CheckCircle2 size={18} />
            </div>
          </div>
          <strong>
            {list.counts.completed || 0}
            <small>个</small>
          </strong>
          <p>可查看结果并导出文件</p>
        </div>
      </div>
      <section className="panel task-panel">
        <div className="task-toolbar">
          <div className="task-filters">
            {[
              ['', '全部任务'],
              ['running', '采集中'],
              ['queued', '排队中'],
              ['paused', '已暂停'],
              ['completed', '已完成'],
              ['failed', '失败'],
            ].map(([value, label]) => (
              <button
                key={value}
                className={filter === value ? 'active' : ''}
                onClick={() => setFilter(value)}
              >
                {label}
                {value === '' && <small>{all}</small>}
              </button>
            ))}
          </div>
          <div className="search-box">
            <Search size={15} />
            <input
              aria-label="搜索任务"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索任务名称…"
            />
            {search && (
              <button aria-label="清空搜索" onClick={() => setSearch('')}>
                <X size={13} />
              </button>
            )}
          </div>
        </div>
        {list.tasks.length ? (
          <TaskTable
            tasks={list.tasks}
            ready={ready}
            busy={busy}
            action={action}
            onEdit={onEdit}
            openResults={openResults}
            setLogTask={setLogTask}
            setDeleteTarget={setDeleteTarget}
          />
        ) : (
          <div className="empty">
            <div className="empty-illustration">
              <div className="empty-sheet">
                <div />
                <div />
                <div />
                <span>
                  <CheckCircle2 size={22} />
                </span>
              </div>
              <div className="floating-link">
                <Link2 size={18} />
              </div>
            </div>
            <h2>{search || filter ? '没有找到匹配任务' : '从第一个采集任务开始'}</h2>
            <p>
              {search || filter
                ? '调整搜索关键词或状态筛选，再试一次。'
                : '添加你信任的来源，预览字段，让数据有序进入工作空间。'}
            </p>
            {!search && !filter && (
              <button className="button primary" disabled={!ready} onClick={() => onNewTask()}>
                <Plus size={16} />
                创建采集任务
              </button>
            )}
            <div className="empty-flow">
              <span>
                <Link2 size={13} />
                添加来源
              </span>
              <ChevronRight size={12} />
              <span>
                <ListTodo size={13} />
                预览字段
              </span>
              <ChevronRight size={12} />
              <span>
                <Database size={13} />
                采集与导出
              </span>
            </div>
          </div>
        )}
        <div className="table-footer">
          <span>
            {list.total ? '共 ' + list.total + ' 个任务' : '任务与数据将自动保存在本机'}
            <i className="footer-dot" />
            数据不上传云端
          </span>
          <div className="button-row">
            <button aria-label="上一页" disabled={page === 0} onClick={() => setPage(page - 1)}>
              <ChevronLeft size={15} />
            </button>
            <span>
              {page + 1} / {Math.max(1, Math.ceil(list.total / PAGE_SIZE))}
            </span>
            <button
              aria-label="下一页"
              disabled={(page + 1) * PAGE_SIZE >= list.total}
              onClick={() => setPage(page + 1)}
            >
              <ChevronRight size={15} />
            </button>
          </div>
        </div>
      </section>
      <div className="bottom-cards">
        <button className="hint-card" onClick={() => onAssistant()}>
          <div className="hint-icon">
            <Sparkles size={20} />
          </div>
          <div>
            <b>不确定字段该怎么整理？</b>
            <p>让本地 AI 助手解释采集规则与质量检查。</p>
          </div>
          <ArrowUpRight size={18} />
        </button>
        <div className="privacy-card">
          <ShieldCheck size={18} />
          <span>原始证据保留，采集结果默认待审核。</span>
        </div>
      </div>
      {logTask && (
        <TaskLogDialog
          key={logTask.task_id}
          task={logTask}
          onClose={() => setLogTask(null)}
          notify={notify}
        />
      )}
      {deleteTarget && (
        <Modal title="删除这个任务？" onClose={() => setDeleteTarget(null)}>
          <div className="modal-body">
            <p>任务“{deleteTarget.name}”及其关联结果将被删除。导出的文件保持不变。</p>
          </div>
          <div className="modal-footer">
            <button className="button" onClick={() => setDeleteTarget(null)}>
              保留任务
            </button>
            <button
              className="button danger"
              onClick={() => {
                void action(deleteTarget, 'delete');
                setDeleteTarget(null);
              }}
            >
              确认删除
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}
