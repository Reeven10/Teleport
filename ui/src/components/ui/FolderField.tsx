import { useState } from 'react';
import { apiPickFolder } from '../../api.ts';
import { Icon } from './Icon.tsx';

interface FolderFieldProps {
  value: string;
  onChange: (path: string) => void;
  /** Called with the folder chosen in the system dialog (not on typing). */
  onPicked?: (path: string) => void;
  placeholder?: string;
  title?: string;
  testId?: string;
}

/** A path box with a Browse button that opens the system folder dialog on this laptop. */
export function FolderField({ value, onChange, onPicked, placeholder, title, testId }: FolderFieldProps) {
  const [picking, setPicking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function browse() {
    setPicking(true);
    setError(null);
    try {
      const path = await apiPickFolder(title);
      if (path) {
        onChange(path);
        onPicked?.(path);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'The folder dialog could not open; type the path instead.');
    } finally {
      setPicking(false);
    }
  }

  return (
    <div>
      <div className="flex gap-2">
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder ?? 'C:\\Users\\me\\projects\\demo'}
          data-testid={testId}
          className="min-w-0 flex-1 rounded-lg border border-line-strong bg-canvas px-3 py-2 font-mono text-xs text-ink outline-none placeholder:text-faint focus:border-ink/40"
        />
        <button
          type="button"
          onClick={() => void browse()}
          disabled={picking}
          data-testid={testId ? `${testId}-browse` : undefined}
          className="tp-btn shrink-0"
        >
          <Icon name="folder" className="h-3.5 w-3.5" />
          {picking ? 'Choose in the dialog...' : 'Browse'}
        </button>
      </div>
      {error && <p className="mt-1.5 text-xs text-bad">{error}</p>}
    </div>
  );
}
