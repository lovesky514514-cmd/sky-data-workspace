import { useCallback, useEffect, useState } from 'react';
import { version as packageVersion } from '../package.json';
import { api, bootstrap } from './bridge';
import { errorText } from './format';
import type { AIStatus } from './types';

export function useRuntime(notify: (message: string) => void) {
  const [ready, setReady] = useState(false);
  const [bootError, setBootError] = useState('');
  const [version, setVersion] = useState(packageVersion);
  const [status, setStatus] = useState<AIStatus | null>(null);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const runtime = await bootstrap();
        if (!active) return;
        setReady(runtime.state === 'ready');
        setBootError(runtime.error ?? '');
        setVersion(runtime.version);
      } catch (error) {
        if (active) {
          setReady(false);
          setBootError(errorText(error));
        }
      } finally {
        if (active) timer = setTimeout(poll, 2000);
      }
    }
    void poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, []);

  const refreshStatus = useCallback(async () => {
    if (!ready) return;
    try {
      setStatus(await api<AIStatus>('/api/ai/status'));
    } catch (error) {
      notify(errorText(error));
    }
  }, [ready, notify]);

  useEffect(() => {
    if (!ready) return;
    void refreshStatus();
    const timer = setInterval(refreshStatus, 30000);
    return () => clearInterval(timer);
  }, [ready, refreshStatus]);

  return { ready, bootError, version, status, refreshStatus };
}
