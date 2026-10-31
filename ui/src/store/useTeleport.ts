import { createContext, useContext } from 'react';
import type { DeviceInfo } from '@contract';
import type { MockScenario } from '../mock/mockFeeder.ts';
import type { StoreAction, TeleportState, WorkloadItem } from './types.ts';

export interface TeleportContextValue {
  state: TeleportState;
  dispatch: (action: StoreAction) => void;
  toggleTheme: () => void;
  toggleMockFeeder: (enable?: boolean) => void;
  setSimulationScenario: (scenario: MockScenario) => void;
  clearRecommendation: () => void;
  selectPeer: (peerId: string) => void;
  addPairedDevice: (device: DeviceInfo) => void;
  addWorkload: (item: WorkloadItem) => void;
}

export const TeleportContext = createContext<TeleportContextValue | null>(null);

export function useTeleport(): TeleportContextValue {
  const ctx = useContext(TeleportContext);
  if (!ctx) {
    throw new Error('useTeleport must be used within a TeleportProvider');
  }
  return ctx;
}
