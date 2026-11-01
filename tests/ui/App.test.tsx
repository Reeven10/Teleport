import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { expect, test, vi, beforeEach, afterEach } from 'vitest';
import App from '@/App.tsx';

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('agent offline'))));
  vi.stubGlobal(
    'WebSocket',
    class {
      close() {}
      send() {}
    },
  );
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

test('renders dashboard shell with title and navigation', async () => {
  render(<App />);

  // Brand
  expect(screen.getByText('Teleport')).toBeInTheDocument();

  // Navigation items
  expect(screen.getByRole('link', { name: /Dashboard/i })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: /Workloads/i })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: /Migration/i })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: /Remote/i })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: /History/i })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: /Settings/i })).toBeInTheDocument();

  // Simulated badge
  expect(screen.getByTestId('badge-simulated')).toBeInTheDocument();

  // Device cards render
  await waitFor(() => {
    expect(screen.getByTestId('device-card-device-a')).toBeInTheDocument();
    expect(screen.getByTestId('device-card-device-b')).toBeInTheDocument();
  });
});

test('navigates to Workloads page and shows workload summary', async () => {
  render(<App />);

  const workloadsNav = screen.getByRole('link', { name: /Workloads/i });
  fireEvent.click(workloadsNav);

  await waitFor(() => {
    expect(screen.getByText(/What runs here/i)).toBeInTheDocument();
    expect(screen.getByTestId('workload-card-wl-token-trainer')).toBeInTheDocument();
  });
});

test('opens and closes the Pair Device modal', async () => {
  render(<App />);

  const pairBtn = screen.getByRole('button', { name: /Pair Device/i });
  fireEvent.click(pairBtn);

  expect(screen.getByRole('heading', { name: /Pair New Device/i })).toBeInTheDocument();
  expect(screen.getByPlaceholderText(/192.168.1.102:8765/i)).toBeInTheDocument();

  const closeBtn = screen.getByRole('button', { name: /Close/i });
  fireEvent.click(closeBtn);

  await waitFor(() => {
    expect(screen.queryByRole('heading', { name: /Pair New Device/i })).not.toBeInTheDocument();
  });
});
