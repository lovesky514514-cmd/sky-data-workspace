import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './bridge';
import { errorText } from './format';
import type { Task, TaskAction, TaskList } from './types';

export const PAGE_SIZE = 12;
const emptyList: TaskList = { tasks: [], total: 0, counts: {}, records: 0 };

export function useTasks(ready: boolean, notify: (message: string) => void) {
  const [query, setQuery] = useState({ page: 0, search: '', filter: '' });
  const [list, setList] = useState(emptyList);
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  const inFlight = useRef(new Set<string>());
  const queryEpoch = useRef(0);

  const loadTasks = useCallback(async () => {
    if (!ready) return;
    const epoch = ++queryEpoch.current;
    const params = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String(query.page * PAGE_SIZE),
      q: query.search,
      status: query.filter,
    });
    try {
      const result = await api<TaskList>(`/api/tasks?${params}`);
      if (epoch !== queryEpoch.current) return;
      setList(result);
      const lastPage = Math.max(0, Math.ceil(result.total / PAGE_SIZE) - 1);
      if (query.page > lastPage) setQuery((current) => ({ ...current, page: lastPage }));
    } catch (error) {
      if (epoch === queryEpoch.current) notify(errorText(error));
    }
  }, [ready, query, notify]);

  // A mutation may finish after the filter changes. Refresh the current query.
  const latestLoad = useRef(loadTasks);
  useEffect(() => {
    latestLoad.current = loadTasks;
    if (!ready) return;
    let active = true;
    let timer = setTimeout(poll, 150);
    async function poll() {
      await loadTasks();
      if (active) timer = setTimeout(poll, 2500);
    }
    return () => {
      active = false;
      queryEpoch.current += 1;
      clearTimeout(timer);
    };
  }, [ready, loadTasks]);

  async function action(task: Task, operation: TaskAction) {
    const id = task.task_id;
    if (!ready || inFlight.current.has(id)) return;
    inFlight.current.add(id);
    setBusy(new Set(inFlight.current));
    try {
      await api('/api/tasks/action', { task_id: id, action: operation });
      await latestLoad.current();
      if (operation === 'copy') notify('任务已复制为草稿');
    } catch (error) {
      notify(errorText(error));
    } finally {
      inFlight.current.delete(id);
      setBusy(new Set(inFlight.current));
    }
  }

  return {
    list,
    busy,
    query,
    loadTasks,
    action,
    setPage: (page: number) => setQuery((current) => ({ ...current, page })),
    setSearch: (search: string) => setQuery((current) => ({ ...current, search, page: 0 })),
    setFilter: (filter: string) => setQuery((current) => ({ ...current, filter, page: 0 })),
  };
}
