import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { SafetyBoundaryBanner } from './components/SafetyBoundaryBanner';
import { ShellControls } from './components/ShellControls';
import { useDirection } from './i18n/useDirection';
import { useBranding } from './branding/useBranding';
import { isAuthConfigured } from './auth/config';
import { completeLoginIfCallback } from './auth/oidc';
import { useAuth } from './auth/useAuth';
import { LoginGate } from './auth/LoginGate';
import { UserBadge } from './auth/UserBadge';
import { CommandOverview } from './pages/CommandOverview';
import { ProcessTwin } from './pages/ProcessTwin';
import { NetworkTwin } from './pages/NetworkTwin';
import { AssetTwin } from './pages/AssetTwin';
import { SimulationCenter } from './pages/SimulationCenter';
import { WaterQuality } from './pages/WaterQuality';
import { PredictiveMaintenance } from './pages/PredictiveMaintenance';
import { MaintenanceCenter } from './pages/MaintenanceCenter';
import { EnergyOptimization } from './pages/EnergyOptimization';
import { ResilienceCommand } from './pages/ResilienceCommand';
import { ExecutiveValue } from './pages/ExecutiveValue';
import { OperationsAssistant } from './pages/OperationsAssistant';
import { Administration } from './pages/Administration';
import { ControlRoom } from './pages/ControlRoom';
import { ShiftReport } from './pages/reports/ShiftReport';
import { ExecutiveReport } from './pages/reports/ExecutiveReport';
import { Models } from './pages/Models';
import { Security } from './pages/Security';
import { MultiFacilityAdmin } from './pages/MultiFacilityAdmin';
import { FacilitySwitcher } from './components/FacilitySwitcher';
import { TrainingSimulator } from './pages/TrainingSimulator';
import { useDashboardStore, type PageId } from './state/store';

interface NavEntry {
  id: PageId;
  label?: string;
  page: number;
  disabled?: boolean;
  requiresSecurity?: boolean;
  adminOnly?: boolean;
  noteKey?: string;
}

const NAV: NavEntry[] = [
  { id: 'command', page: 1 },
  { id: 'process', page: 2 },
  { id: 'network', page: 3 },
  { id: 'asset', page: 4 },
  { id: 'water-quality', page: 5 },
  { id: 'predictive-maintenance', page: 6 },
  { id: 'maintenance-center', page: 6 },
  { id: 'energy', page: 7 },
  { id: 'resilience', page: 9 },
  { id: 'executive', page: 10 },
  { id: 'models', page: 12 },
  { id: 'assistant', page: 11 },
  { id: 'security', page: 12, requiresSecurity: true },
  { id: 'training', page: 12, noteKey: 'nav.notes.training' },
  { id: 'simulation', page: 8, noteKey: 'nav.notes.simulation' },
  { id: 'administration', page: 12 },
];

// Administration section entries. Gated behind the facility-management
// capability so facility-operators never see the fleet-wide admin surface.
const ADMIN_NAV: NavEntry[] = [{ id: 'admin-facilities', page: 12 }];
function Brand() {
  const { displayName, displaySubtitle, logoUrl } = useBranding();
  return (
    <div className="brand">
      {logoUrl ? (
        <img className="brand-logo" src={logoUrl} alt={displayName} data-testid="brand-logo" />
      ) : (
        <h1>{displayName}</h1>
      )}
      <div className="sub">{displaySubtitle}</div>
    </div>
  );
}

function Nav() {
  const { t } = useTranslation();
  const page = useDashboardStore((s) => s.page);
  const navigate = useDashboardStore((s) => s.navigate);
  const setDisplayMode = useDashboardStore((s) => s.setDisplayMode);
  const openReport = useDashboardStore((s) => s.openReport);
  const { capabilities } = useAuth();
  const entries = NAV.filter(
    (item) =>
      (!item.requiresSecurity || capabilities.readSecurity) &&
      (!item.adminOnly || capabilities.administer),
  );
  return (
    <nav className="app-nav" aria-label={t('nav.ariaLabel')}>
      <Brand />
      <FacilitySwitcher />
      {entries.map((item) => (
        <button
          key={item.id}
          className={`nav-item${page === item.id ? ' active' : ''}`}
          onClick={() => navigate(item.id)}
          aria-current={page === item.id ? 'page' : undefined}
          data-testid={`nav-${item.id}`}
        >
          <span>{t(`nav.items.${item.id}`, { defaultValue: item.label })}</span>
          {item.noteKey ? <span className="phase-tag">{t(item.noteKey)}</span> : null}
        </button>
      ))}

      <div className="nav-group" aria-label="Display &amp; reports">
        <div className="nav-group-title">Display &amp; reports</div>
        <button
          className="nav-item"
          onClick={() => setDisplayMode('control-room')}
          data-testid="enter-control-room"
        >
          <span>Control Room display</span>
        </button>
        <button
          className="nav-item"
          onClick={() => openReport('shift')}
          data-testid="open-shift-report"
        >
          <span>Print shift report</span>
        </button>
        <button
          className="nav-item"
          onClick={() => openReport('executive')}
          data-testid="open-executive-report"
        >
          <span>Print executive report</span>
        </button>
      </div>

      {capabilities.manageFacilities ? (
        <div className="nav-section" data-testid="admin-nav-section">
          <div className="nav-section-title">Administration</div>
          {ADMIN_NAV.map((item) => (
            <button
              key={item.id}
              className={`nav-item${page === item.id ? ' active' : ''}`}
              onClick={() => navigate(item.id)}
              aria-current={page === item.id ? 'page' : undefined}
              data-testid={`nav-${item.id}`}
            >
              <span>{t(`nav.items.${item.id}`)}</span>
              {item.noteKey ? <span className="phase-tag">{t(item.noteKey)}</span> : null}
            </button>
          ))}
        </div>
      ) : null}
      <div style={{ flex: 1 }} />
      <FacilitySwitcher />
      <ShellControls />
      <UserBadge />
      <div className="brand">
        <div className="sub">{t('nav.footerNote')}</div>
      </div>
    </nav>
  );
}

function ReportOverlay() {
  const reportView = useDashboardStore((s) => s.reportView);
  if (reportView === 'shift') return <ShiftReport />;
  if (reportView === 'executive') return <ExecutiveReport />;
  return null;
}

function CurrentPage() {
  const page = useDashboardStore((s) => s.page);
  switch (page) {
    case 'command':
      return <CommandOverview />;
    case 'process':
      return <ProcessTwin />;
    case 'network':
      return <NetworkTwin />;
    case 'asset':
      return <AssetTwin />;
    case 'water-quality':
      return <WaterQuality />;
    case 'predictive-maintenance':
      return <PredictiveMaintenance />;
    case 'maintenance-center':
      return <MaintenanceCenter />;
    case 'energy':
      return <EnergyOptimization />;
    case 'resilience':
      return <ResilienceCommand />;
    case 'executive':
      return <ExecutiveValue />;
    case 'assistant':
      return <OperationsAssistant />;
    case 'models':
      return <Models />;
    case 'security':
      return <Security />;
    case 'training':
      return <TrainingSimulator />;
    case 'simulation':
      return <SimulationCenter />;
    case 'administration':
      return <Administration />;
    case 'admin-facilities':
      return <MultiFacilityAdmin />;
    default:
      return <CommandOverview />;
  }
}

export default function App() {
  const { t } = useTranslation();
  const { isAuthenticated } = useAuth();
  const displayMode = useDashboardStore((s) => s.displayMode);
  const reportView = useDashboardStore((s) => s.reportView);
  // Apply language direction (RTL for Arabic) and customer branding at the shell root.
  useDirection();
  useBranding();
  // While OIDC is configured, wait for a possible redirect-callback exchange to
  // resolve before deciding whether to show the login gate.
  const [callbackResolved, setCallbackResolved] = useState(!isAuthConfigured());

  useEffect(() => {
    if (!isAuthConfigured()) return;
    let active = true;
    void completeLoginIfCallback().finally(() => {
      if (active) setCallbackResolved(true);
    });
    return () => {
      active = false;
    };
  }, []);

  if (isAuthConfigured() && !isAuthenticated) {
    if (!callbackResolved) {
      return (
        <div className="app-shell" data-testid="auth-loading">
          <SafetyBoundaryBanner />
          <div className="login-wrap">
            <div className="login-card">
              <div className="sub">{t('common.signingIn')}</div>
            </div>
          </div>
        </div>
      );
    }
    return <LoginGate />;
  }

  // Control-room display mode: large-format wall display with minimal chrome.
  // Reports can still be opened on top of it.
  if (displayMode === 'control-room') {
    return (
      <>
        <ControlRoom />
        {reportView ? <ReportOverlay /> : null}
      </>
    );
  }

  return (
    <div className="app-shell">
      <SafetyBoundaryBanner />
      <div className="app-body">
        <Nav />
        <main className="app-main">
          <CurrentPage />
        </main>
      </div>
      {reportView ? <ReportOverlay /> : null}
    </div>
  );
}
