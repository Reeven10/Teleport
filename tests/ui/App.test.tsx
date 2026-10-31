import { render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import App from '@/App.tsx';

test('renders the title', () => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('offline'))));
  vi.stubGlobal('WebSocket', class { close() {} });
  render(<App />);
  expect(screen.getByText('Teleport')).toBeInTheDocument();
});
