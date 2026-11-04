import {
  Database,
  ListTodo,
  Minimize2,
  Power,
  Settings,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { desktop, nativeAction } from './bridge';
import { errorText } from './format';
import type { Route } from './types';

const navigation = [
  { id: 'tasks' as Route, label: '任务清单', icon: ListTodo },
  { id: 'results' as Route, label: '采集结果', icon: Database },
  { id: 'ai' as Route, label: 'AI 助手', icon: Sparkles },
  { id: 'settings' as Route, label: '设置', icon: Settings },
];

interface SidebarProps {
  route: Route;
  setRoute: (route: Route) => void;
  all: number;
  version: string;
  notify: (message: string) => void;
}

export default function WorkspaceSidebar({ route, setRoute, all, version, notify }: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-avatar">
          <img src="/app-avatar.jpg" alt="SKY图标" />
        </div>
        <div>
          <b>
            SKY<span> Data Workspace</span>
          </b>
          <small>数据采集工作台</small>
        </div>
      </div>
      <div className="workspace-label">WORKSPACE</div>
      <nav>
        {navigation.map((n) => (
          <button
            key={n.id}
            className={route === n.id ? 'active' : ''}
            onClick={() => setRoute(n.id)}
          >
            <n.icon size={19} />
            <span>{n.label}</span>
            {n.id === 'tasks' && !!all && <small>{all}</small>}
            {n.id === 'ai' && <i className="nav-dot" />}
          </button>
        ))}
      </nav>
      <div className="sidebar-note">
        <div className="note-mark">
          <ShieldCheck size={18} />
        </div>
        <b>每一条数据，都有出处</b>
        <p>
          本地存储 · 原始证据保留
          <br />
          AI 辅助，独立核验
        </p>
        <span>
          <i />
          本地工作空间
        </span>
      </div>
      <div className="sidebar-bottom">
        {desktop && (
          <>
            <button onClick={() => nativeAction('hide_to_tray').catch((e) => notify(errorText(e)))}>
              <Minimize2 size={15} />
              收起至托盘
            </button>
            <button onClick={() => nativeAction('quit_app').catch((e) => notify(errorText(e)))}>
              <Power size={15} />
              退出程序
            </button>
          </>
        )}
        <div className="version">
          <span>SKY Data Workspace</span>
          <small>{version}</small>
        </div>
      </div>
    </aside>
  );
}
