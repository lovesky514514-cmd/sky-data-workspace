import { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, ChevronRight, Plus, X } from 'lucide-react';
import TaskWizard from './TaskWizard';
import TaskPage from './TaskPage';
import WorkspaceSidebar from './WorkspaceSidebar';
import Results from './Results';
import Assistant from './Assistant';
import SettingsView from './SettingsView';
import { useRuntime } from './useRuntime';
import { useTasks } from './useTasks';
import type { Task, Route } from './types';

const headings: Record<Route, [string, string]> = {
  tasks: ['任务清单', '把分散的来源，整理成有据可查的数据。'],
  results: ['采集结果', '原始数据、来源证据与质量审核，在同一处查看。'],
  ai: ['AI 助手', '查询本地知识，理解字段与采集规则。'],
  settings: ['设置', '管理本地模型、运行偏好和数据备份。'],
};

export default function App() {
  const [route, setRoute] = useState<Route>('tasks');
  const [wizard, setWizard] = useState<{ task?: Task } | null>(null);
  const [selected, setSelected] = useState('');
  const [toast, setToast] = useState('');
  const notify = useCallback((message: string) => setToast(message), []);
  const { ready, bootError, status, refreshStatus, version } = useRuntime(notify);
  const tasks = useTasks(ready, notify);
  const all = Object.values(tasks.list.counts).reduce((sum, count) => sum + count, 0);
  const closeWizard = useCallback(() => setWizard(null), []);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(''), 6500);
    return () => clearTimeout(timer);
  }, [toast]);

  function saved(task: Task) {
    closeWizard();
    void tasks.loadTasks();
    notify(task.status === 'queued' ? '任务已加入采集队列' : '任务已保存');
  }

  function openResults(task: Task) {
    setSelected(task.task_id);
    setRoute('results');
  }

  return (
    <div className="app-shell">
      <WorkspaceSidebar
        route={route}
        setRoute={setRoute}
        all={all}
        version={version}
        notify={notify}
      />
      <main className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            工作空间
            <ChevronRight size={12} />
            <strong>{headings[route][0]}</strong>
          </div>
          <div className="topbar-right">
            <span className={'engine-state ' + (ready ? 'connected' : '')}>
              <i />
              {ready ? '本地引擎已连接' : bootError ? '引擎启动失败' : '正在启动本地引擎'}
            </span>
            <span className="header-divider" />
            <span className="local-time">本地优先，安心采集</span>
          </div>
        </header>
        <div className="main-content">
          <div className="page-heading">
            <div>
              <span className="eyebrow">
                {route === 'tasks' ? 'YOUR DATA, ORGANIZED' : 'SKY WORKSPACE'}
              </span>
              <h1>{headings[route][0]}</h1>
              <p>{headings[route][1]}</p>
            </div>
            {route === 'tasks' && (
              <button
                className="button primary large"
                disabled={!ready}
                onClick={() => setWizard({})}
              >
                <Plus size={18} />
                新建任务
              </button>
            )}
            {route === 'ai' && (
              <span className={'model-pill ' + (status?.ai.installed ? 'installed' : '')}>
                <i />
                {status?.ai.installed ? 'Qwen3.5 · 9B' : '等待本地模型'}
                <span>LOCAL</span>
              </span>
            )}
          </div>
          {bootError && (
            <div className="inline-error">
              <b>本地运行时未就绪</b>
              <p>{bootError}</p>
              <small>请重新启动程序；详细信息见应用数据目录中的 logs/desktop-runtime.log。</small>
            </div>
          )}

          <div hidden={route !== 'tasks'}>
            <TaskPage
              model={tasks}
              ready={ready}
              onEdit={(task) => setWizard({ task })}
              onNewTask={() => setWizard({})}
              openResults={openResults}
              onAssistant={() => setRoute('ai')}
              notify={notify}
            />
          </div>
          {route === 'results' && ready && (
            <Results key="results" selected={selected} onSelect={setSelected} notify={notify} />
          )}
          <div hidden={route !== 'ai'}>
            <Assistant status={status} />
          </div>
          {route === 'settings' && (
            <SettingsView status={status} refresh={refreshStatus} notify={notify} />
          )}
        </div>
      </main>
      {wizard && <TaskWizard task={wizard.task} onClose={closeWizard} onSaved={saved} />}
      {toast && (
        <div className="toast" role="status">
          <CheckCircle2 size={17} />
          <span>{toast}</span>
          <button aria-label="关闭提示" onClick={() => setToast('')}>
            <X size={14} />
          </button>
        </div>
      )}
    </div>
  );
}
