import '@testing-library/jest-dom/vitest';

// Mock ResizeObserver for Recharts in JSDOM
class ResizeObserverMock {
  observe(target: Element) {
    // Dispatch a mock resize entry
    target.dispatchEvent(new Event('resize'));
  }
  unobserve() {}
  disconnect() {}
}

if (typeof window !== 'undefined') {
  if (!window.ResizeObserver) {
    window.ResizeObserver = ResizeObserverMock;
  }
  // Mock element dimensions in JSDOM for recharts
  window.HTMLElement.prototype.getBoundingClientRect = function () {
    return {
      width: 400,
      height: 100,
      top: 0,
      left: 0,
      bottom: 100,
      right: 400,
      x: 0,
      y: 0,
      toJSON: () => {},
    };
  };
}
