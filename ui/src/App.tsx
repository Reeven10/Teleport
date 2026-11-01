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
        <div className="flex min-h-screen flex-col bg-slate-100 text-slate-900 transition-colors duration-200 dark:bg-slate-950 dark:text-slate-100">
          <TopBar />
          <RemoteConsentPrompt />
          <div className="flex flex-1">
            <Sidebar />
            <main className="flex-1 overflow-y-auto p-6 md:p-8">
              <div className="mx-auto max-w-7xl">
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
