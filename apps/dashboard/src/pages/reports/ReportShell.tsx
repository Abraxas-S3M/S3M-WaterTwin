import type { ReactNode } from 'react';

interface ReportShellProps {
  title: string;
  testId?: string;
  onClose?: () => void;
  /** Injectable print handler (defaults to window.print) for testability. */
  onPrint?: () => void;
  children: ReactNode;
}

function defaultPrint() {
  if (typeof window !== 'undefined' && typeof window.print === 'function') {
    window.print();
  }
}

/**
 * Full-screen, print-optimised container for a paginated report. The toolbar is
 * screen-only (hidden by the print stylesheet); the `.report-sheet` renders a
 * clean, high-contrast, paginated document suitable for "Print" / "Save as PDF".
 */
export function ReportShell({
  title,
  testId,
  onClose,
  onPrint = defaultPrint,
  children,
}: ReportShellProps) {
  return (
    <div className="report-view" data-testid={testId}>
      <div className="report-toolbar" role="toolbar" aria-label="Report actions">
        <div className="report-toolbar-title">{title}</div>
        <div className="report-toolbar-actions">
          <button className="btn primary" onClick={() => onPrint()} data-testid="report-print">
            Print / Save as PDF
          </button>
          {onClose ? (
            <button className="btn ghost" onClick={() => onClose()} data-testid="report-close">
              Close
            </button>
          ) : null}
        </div>
      </div>
      <div className="report-sheet">{children}</div>
    </div>
  );
}

interface ReportHeaderProps {
  title: string;
  subtitle: string;
  facilityId?: string;
  trainId?: string;
  generatedAt: Date;
  operator?: string;
}

export function ReportHeader({
  title,
  subtitle,
  facilityId,
  trainId,
  generatedAt,
  operator,
}: ReportHeaderProps) {
  return (
    <header className="report-header">
      <div>
        <h1 className="report-title">{title}</h1>
        <div className="report-subtitle">{subtitle}</div>
      </div>
      <dl className="report-meta">
        {facilityId ? (
          <div>
            <dt>Facility / Train</dt>
            <dd>
              {facilityId}
              {trainId ? ` · ${trainId}` : ''}
            </dd>
          </div>
        ) : null}
        <div>
          <dt>Generated</dt>
          <dd>{generatedAt.toLocaleString()}</dd>
        </div>
        {operator ? (
          <div>
            <dt>Prepared by</dt>
            <dd>{operator}</dd>
          </div>
        ) : null}
      </dl>
    </header>
  );
}

/**
 * Mandatory advisory footer restating the read-only control posture so a
 * printed report can never be mistaken for an authorization to act on plant
 * equipment. Mirrors the API report boundary footer.
 */
export function ReportBoundaryFooter({ note }: { note?: string }) {
  return (
    <footer className="report-boundary" data-testid="report-boundary">
      <div className="report-boundary-badge">ADVISORY · READ-ONLY · NO CONTROL WRITE</div>
      <p>
        {note ??
          'This report is advisory and preliminary. Figures are read-only model output on ' +
            'synthetic data — not measured or validated plant data — and must not be used as an ' +
            'autonomous control action. All actions require operator approval and are recorded ' +
            'for audit.'}
      </p>
    </footer>
  );
}
