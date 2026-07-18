import type { ReactElement } from 'react';

/**
 * The three templated-ingestion domains served by the `watertwin-ingest` service.
 * The download links live in the drop step of the configuration workbench: an
 * operator downloads a template, fills it in, and drops it back to produce a
 * reviewable diff. Importing is read-only decision-support — nothing is ever
 * written to OT.
 *
 * The template files themselves are generated from, and validated against, the
 * parser column contracts in `services/watertwin-ingest`, so the CSV a user
 * downloads can never drift from what the parser accepts.
 */
export interface IngestTemplate {
  /** Stable identifier matching the parser `KIND`. */
  readonly id: 'equipment' | 'tag_mapping' | 'lab';
  /** Human-readable label for the download link. */
  readonly label: string;
  /** Short description of what the template captures. */
  readonly description: string;
  /** Downloaded filename. */
  readonly filename: string;
  /** URL the template is served from (watertwin-ingest). */
  readonly href: string;
}

export const INGEST_TEMPLATES: readonly IngestTemplate[] = [
  {
    id: 'equipment',
    label: 'Equipment specifications',
    description: 'Asset nameplate & rated data (flow, head, power, speed, efficiency, NPSHr).',
    filename: 'equipment_template.csv',
    href: '/api/ingest/templates/equipment_template.csv',
  },
  {
    id: 'tag_mapping',
    label: 'OT tag mapping',
    description: 'Map OT tags to canonical assets with unit, scale, offset and deadband.',
    filename: 'tag_mapping_template.csv',
    href: '/api/ingest/templates/tag_mapping_template.csv',
  },
  {
    id: 'lab',
    label: 'Lab methods',
    description: 'Sample point, parameter, method, unit and detection/quantitation limits.',
    filename: 'lab_methods_template.csv',
    href: '/api/ingest/templates/lab_methods_template.csv',
  },
] as const;

export interface TemplateDownloadsProps {
  /** Override the template list (defaults to {@link INGEST_TEMPLATES}). */
  readonly templates?: readonly IngestTemplate[];
}

/**
 * Renders the downloadable spreadsheet-template links shown in the import drop
 * step. Each link is a real `download` anchor so the browser saves the CSV
 * directly from the ingest service.
 */
export function TemplateDownloads({
  templates = INGEST_TEMPLATES,
}: TemplateDownloadsProps): ReactElement {
  return (
    <div className="card" data-testid="ingest-template-downloads">
      <h3>Download a template</h3>
      <p className="context">
        Fill a template and drop it below to import equipment, tag mappings or lab methods. Uploads
        are parsed into a reviewable diff before anything is applied — this import path is read-only
        to OT and writes no control commands.
      </p>
      <ul className="template-list">
        {templates.map((template) => (
          <li key={template.id} data-testid={`template-${template.id}`}>
            <a
              className="btn ghost"
              href={template.href}
              download={template.filename}
              data-testid={`download-${template.id}`}
            >
              {template.label}
            </a>
            <span className="card-sub">{template.description}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
