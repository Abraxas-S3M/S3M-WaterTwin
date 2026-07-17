import { SafetyBoundaryBanner } from './components/SafetyBoundaryBanner';
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

function Nav() {
  const page = useDashboardStore((s) => s.page);
  const navigate = useDashboardStore((s) => s.navigate);
  return (
    <nav className="app-nav" aria-label="Primary">
      <div className="brand">
        <h1>S3M-WaterTwin</h1>
        <div className="sub">Operator Console</div>
      </div>
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
      <div style={{ flex: 1 }} />
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
    default:
      return <CommandOverview />;
  }
}

export default function App() {
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
