import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { INGEST_TEMPLATES, TemplateDownloads } from './TemplateDownloads';

describe('TemplateDownloads', () => {
  it('renders a download link for each ingest template', () => {
    render(<TemplateDownloads />);
    expect(screen.getByTestId('ingest-template-downloads')).toBeInTheDocument();
    for (const template of INGEST_TEMPLATES) {
      const link = screen.getByTestId(`download-${template.id}`);
      expect(link).toHaveAttribute('href', template.href);
      expect(link).toHaveAttribute('download', template.filename);
      expect(link).toHaveTextContent(template.label);
    }
  });

  it('covers the three ingestion domains', () => {
    expect([...INGEST_TEMPLATES].map((t) => t.id).sort()).toEqual([
      'equipment',
      'lab',
      'tag_mapping',
    ]);
  });

  it('accepts an overridden template list', () => {
    render(
      <TemplateDownloads
        templates={[
          {
            id: 'equipment',
            label: 'Custom equipment',
            description: 'custom',
            filename: 'custom.csv',
            href: '/somewhere/custom.csv',
          },
        ]}
      />,
    );
    const link = screen.getByTestId('download-equipment');
    expect(link).toHaveAttribute('href', '/somewhere/custom.csv');
    expect(screen.queryByTestId('download-lab')).not.toBeInTheDocument();
  });
});
