import { useEffect, useState } from 'react';
import { SafetyBoundaryBanner } from './components/SafetyBoundaryBanner';
import { isAuthConfigured } from './auth/config';
import { completeLoginIfCallback } from './auth/oidc';
import { useAuth } from './auth/useAuth';
import { LoginGate } from './auth/LoginGate';
import { UserBadge } from './auth/UserBadge';
import { CommandOverview } from './pages/CommandOverview';
import { ProcessTwin } from './pages/ProcessTwin';
import { AssetTwin } from './pages/AssetTwin';
import { SimulationCenter } from './pages/SimulationCenter';
import { WaterQuality } from './pages/WaterQuality';
import { PredictiveMaintenance } from './pages/PredictiveMaintenance';
import { EnergyOptimization } from './pages/EnergyOptimization';
import { ResilienceCommand } from './pages/ResilienceCommand';
import { ExecutiveValue } from './pages/ExecutiveValue';
import { OperationsAssistant } from './pages/OperationsAssistant';
import { MultiFacilityAdmin } from './pages/MultiFacilityAdmin';
import { FacilitySwitcher } from './components/FacilitySwitcher';
import { useDashboardStore, type PageId } from './state/store';

interface NavEntry {
  id: PageId;
  label: string;
  page: number;
  disabled?: boolean;
  note?: string;
}

const NAV: NavEntry[] = [
  { id: 'command', label: 'Command Overview', page: 1 },
  { id: 'process', label: 'Process Twin', page: 2 },
  { id: 'asset', label: 'Asset Twin', page: 4 },
  { id: 'water-quality', label: 'Water Quality', page: 5 },
  { id: 'predictive-maintenance', label: 'Predictive Maintenance', page: 6 },
  { id: 'energy', label: 'Energy Optimization', page: 7 },
  { id: 'resilience', label: 'Resilience Command', page: 9 },
  { id: 'executive', label: 'Executive Value / ROI', page: 10 },
  { id: 'assistant', label: 'Operations Assistant', page: 11 },
  { id: 'simulation', label: 'Simulation Center', page: 8, note: 'Phase 8–9' },
];

// Administration section entries. Gated behind the facility-management
// capability so facility-operators never see the fleet-wide admin surface.
const ADMIN_NAV: NavEntry[] = [
  { id: 'admin-facilities', label: 'Multi-Facility', page: 12 },
];

function Nav() {
  const page = useDashboardStore((s) => s.page);
  const navigate = useDashboardStore((s) => s.navigate);
  const { capabilities } = useAuth();
  return (
    <nav className="app-nav" aria-label="Primary">
      <div className="brand">
        <h1>S3M-WaterTwin</h1>
        <div className="sub">Operator Console</div>
      </div>
      <FacilitySwitcher />
      {NAV.map((item) => (
        <button
          key={item.id}
          className={`nav-item${page === item.id ? ' active' : ''}`}
          onClick={() => navigate(item.id)}
          aria-current={page === item.id ? 'page' : undefined}
        >
          <span>{item.label}</span>
          {item.note ? <span className="phase-tag">{item.note}</span> : null}
        </button>
      ))}
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
              <span>{item.label}</span>
              {item.note ? <span className="phase-tag">{item.note}</span> : null}
            </button>
          ))}
        </div>
      ) : null}
      <div style={{ flex: 1 }} />
      <UserBadge />
      <div className="brand">
        <div className="sub">Pages 1, 2, 4 live · others in later phases</div>
      </div>
    </nav>
  );
}

function CurrentPage() {
  const page = useDashboardStore((s) => s.page);
  switch (page) {
    case 'command':
      return <CommandOverview />;
    case 'process':
      return <ProcessTwin />;
    case 'asset':
      return <AssetTwin />;
    case 'water-quality':
      return <WaterQuality />;
    case 'predictive-maintenance':
      return <PredictiveMaintenance />;
    case 'energy':
      return <EnergyOptimization />;
    case 'resilience':
      return <ResilienceCommand />;
    case 'executive':
      return <ExecutiveValue />;
    case 'assistant':
      return <OperationsAssistant />;
    case 'simulation':
      return <SimulationCenter />;
    case 'admin-facilities':
      return <MultiFacilityAdmin />;
    default:
      return <CommandOverview />;
  }
}

export default function App() {
  const { isAuthenticated } = useAuth();
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
              <div className="sub">Signing in…</div>
            </div>
          </div>
        </div>
      );
    }
    return <LoginGate />;
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
    </div>
  );
}
