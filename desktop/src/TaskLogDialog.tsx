import { useEffect, useState } from 'react';
import { Terminal } from 'lucide-react';
import { api } from './bridge';
import { Modal } from './components';
import { date, errorText } from './format';
import type { Task } from './types';

interface LogEntry {
  log_id: number;
  created_at: string;
  level: string;
  message: string;
}

interface TaskLogDialogProps {
  task: Task;
  onClose: () => void;
  notify: (message: string) => void;
}

export default function TaskLogDialog({ task, onClose, notify }: TaskLogDialogProps) {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const response = await api<{ logs: LogEntry[] }>(`/api/tasks/${task.task_id}/logs`);
        if (active) setLogs(response.logs);
      } catch (error) {
        if (active) notify(errorText(error));
      } finally {
        if (active) timer = setTimeout(poll, 2000);
      }
    }
    void poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [task.task_id, notify]);

  return (
    <Modal title={`${task.name} · 运行日志`} onClose={onClose} wide>
      <div className="modal-body log-list">
        {logs.length ? (
          logs.map((log) => (
            <div key={log.log_id} className={`log-line ${log.level}`}>
              <span>{date(log.created_at)}</span>
              <i />
              <p>{log.message}</p>
            </div>
          ))
        ) : (
          <div className="empty compact">
            <Terminal size={26} />
            <p>暂无运行日志</p>
          </div>
        )}
      </div>
      <div className="modal-footer">
        <span className="small-note">自动刷新 · 最近300条</span>
        <button className="button" onClick={onClose}>
          关闭
        </button>
      </div>
    </Modal>
  );
}
