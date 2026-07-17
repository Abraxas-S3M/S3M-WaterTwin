import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LabMethodsPanel } from './LabMethodsPanel';
import { configDocument } from '../../test/fixtures';

describe('LabMethodsPanel', () => {
  it('renders lab methods and compliance limits', () => {
    render(
      <LabMethodsPanel
        labMethods={configDocument.lab_methods}
        complianceLimits={configDocument.compliance_limits}
        readOnly={false}
        onLabMethodsChange={() => {}}
        onComplianceLimitsChange={() => {}}
      />,
    );
    expect(screen.getByTestId('admin-panel-lab-methods')).toBeInTheDocument();
    expect(screen.getByTestId('admin-lab-methods-table')).toBeInTheDocument();
    expect(screen.getByTestId('admin-compliance-limits-table')).toBeInTheDocument();
    expect(screen.getByLabelText('method-analyte-0')).toHaveValue('Boron');
    expect(screen.getByLabelText('limit-value-0')).toHaveValue(1);
    expect(screen.getByLabelText('limit-basis-0')).toHaveValue('WHO drinking-water guideline');
  });

  it('is read-only for non-admin roles', () => {
    render(
      <LabMethodsPanel
        labMethods={configDocument.lab_methods}
        complianceLimits={configDocument.compliance_limits}
        readOnly
        onLabMethodsChange={() => {}}
        onComplianceLimitsChange={() => {}}
      />,
    );
    expect(screen.getByLabelText('method-analyte-0')).toBeDisabled();
    expect(screen.getByLabelText('limit-value-0')).toBeDisabled();
    expect(screen.queryByTestId('admin-panel-lab-methods-add')).not.toBeInTheDocument();
    expect(screen.queryByTestId('admin-add-compliance-limit')).not.toBeInTheDocument();
  });
});
