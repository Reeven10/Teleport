import { useState } from 'react';
import type { WorkloadManifest } from '@contract';
import { apiDetectServer, apiStartServer, type AppTemplate, type ServerDetection } from '../../api.ts';
import { FolderField } from '../ui/FolderField.tsx';
import { Icon } from '../ui/Icon.tsx';

interface ServerAppCardProps {
  app: AppTemplate;
  onStarted: (manifest: WorkloadManifest, message: string) => void;
  onError: (message: string) => void;
}

/** Pick a server project folder, see what Teleport detected (language, install, start command, port),
 *  adjust it if needed, and run it as a migratable workload. */
export function ServerAppCard({ app, onStarted, onError }: ServerAppCardProps) {
  const [path, setPath] = useState('');
  const [found, setFound] = useState<ServerDetection | null>(null);
  const [command, setCommand] = useState('');
  const [port, setPort] = useState('');
  const [detectError, setDetectError] = useState<string | null>(null);
  const [busy, setBusy] = useState<'detect' | 'start' | null>(null);

  async function detect(folder: string) {
    if (!folder.trim()) return;
    setBusy('detect');
    setDetectError(null);
    setFound(null);
    try {
      const res = await apiDetectServer(folder);
      setFound(res);
      setCommand(res.command);
      setPort(String(res.port));
    } catch (err: unknown) {
      setDetectError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function start() {
    if (!found) return;
    setBusy('start');
    try {
      const manifest = await apiStartServer(found.path, command, Number(port) || undefined);
      onStarted(
        manifest,
        `${found.name} is starting: ${found.install ? 'installing its dependencies, then ' : ''}it opens on http://localhost:${port}.`,
      );
    } catch (err: unknown) {
      onError(`Could not start the server: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div data-testid={`app-${app.id}`} className="tp-card flex flex-col p-5 sm:col-span-2">
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-line bg-raised text-muted">
          <Icon name="workloads" className="h-4 w-4" />
        </span>
        <div>
          <h2 className="text-[15px] font-medium text-ink">{app.title}</h2>
          <p className="mt-0.5 text-xs leading-relaxed text-muted">{app.description}</p>
        </div>
      </div>

      <div className="mt-4">
        <FolderField
          value={path}
          onChange={(p) => {
            setPath(p);
            setFound(null);
          }}
          onPicked={(p) => void detect(p)}
          title="Choose the server project folder"
          testId="server-project-path"
        />
      </div>

      {!found && (
        <div className="mt-3 flex items-center justify-between gap-3">
          <p className="text-xs text-faint">Node (package.json) or Python (app.py, main.py, server.py, manage.py).</p>
          <button type="button" className="tp-btn" disabled={!path.trim() || busy !== null} onClick={() => void detect(path)}>
            {busy === 'detect' ? 'Looking...' : 'Detect'}
          </button>
        </div>
      )}
      {detectError && <p className="mt-2 text-xs text-bad">{detectError}</p>}

      {found && (
        <div className="mt-4 rounded-xl border border-line bg-raised p-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="tp-chip font-mono text-ink">
              {found.kind === 'node' ? 'Node.js' : 'Python'} {found.runtime.minVersion}+
            </span>
            <span className="text-sm text-ink">{found.name}</span>
          </div>
          <dl className="mt-3 grid grid-cols-1 gap-3 text-xs sm:grid-cols-[auto_1fr]">
            <dt className="text-faint">Dependencies</dt>
            <dd className="text-ink">
              {found.dependencies.length === 0
                ? 'none'
                : `${found.dependencies.length}: ${found.dependencies.slice(0, 6).join(', ')}${found.dependencies.length > 6 ? ', ...' : ''}`}
              <span className="text-faint">
                {found.install
                  ? ` · installed with ${found.install} on whichever laptop runs it (never copied)`
                  : ''}
              </span>
            </dd>
            <dt className="self-center text-faint">Start command</dt>
            <dd>
              <input
                value={command}
                onChange={(e) => setCommand(e.target.value)}
                className="w-full rounded-lg border border-line-strong bg-surface px-2.5 py-1.5 font-mono text-xs text-ink outline-none focus:border-ink/40"
              />
            </dd>
            <dt className="self-center text-faint">Port</dt>
            <dd className="flex items-center gap-2">
              <input
                value={port}
                onChange={(e) => setPort(e.target.value.replace(/\D/g, ''))}
                className="w-24 rounded-lg border border-line-strong bg-surface px-2.5 py-1.5 font-mono text-xs text-ink outline-none focus:border-ink/40"
              />
              <span className="text-faint">opens http://localhost:{port || '...'} when ready</span>
            </dd>
          </dl>
          <div className="mt-4 flex justify-end">
            <button type="button" className="tp-btn-primary" disabled={busy !== null || !command.trim()} onClick={() => void start()}>
              {busy === 'start' ? 'Starting...' : 'Start server'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
