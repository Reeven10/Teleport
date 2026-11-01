import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { Sidebar } from './components/layout/Sidebar.tsx';
import { TopBar } from './components/layout/TopBar.tsx';
import { RemoteConsentPrompt } from './components/remote/RemoteConsentPrompt.tsx';
import { DashboardPage } from './pages/DashboardPage.tsx';
import { HistoryPage } from './pages/HistoryPage.tsx';
import { MigrationPage } from './pages/MigrationPage.tsx';
import { RemotePage } from './pages/RemotePage.tsx';
import { SettingsPage } from './pages/SettingsPage.tsx';
import { WorkloadsPage } from './pages/WorkloadsPage.tsx';
import { TeleportProvider } from './store/TeleportContext.tsx';

export default function App() {
  return (
    <BrowserRouter>
      <TeleportProvider>
        <div className="flex min-h-screen bg-canvas text-ink">
          <Sidebar />
          <div className="flex min-w-0 flex-1 flex-col">
            <TopBar />
            <RemoteConsentPrompt />
            <main className="flex-1 px-6 py-8 md:px-10">
              <div className="mx-auto max-w-[1200px]">
                <Routes>
                  <Route path="/" element={<DashboardPage />} />
                  <Route path="/workloads" element={<WorkloadsPage />} />
                  <Route path="/migration" element={<MigrationPage />} />
                  <Route path="/remote" element={<RemotePage />} />
                  <Route path="/history" element={<HistoryPage />} />
                  <Route path="/settings" element={<SettingsPage />} />
                </Routes>
              </div>
            </main>
          </div>
        </div>
      </TeleportProvider>
    </BrowserRouter>
  );
}
