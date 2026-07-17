import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ProcessStagesPanel } from './ProcessStagesPanel';
import { configDocument } from '../../test/fixtures';

describe('ProcessStagesPanel', () => {
  it('renders process stages and sampling points', () => {
    render(
      <ProcessStagesPanel
        stages={configDocument.process_stages}
        samplingPoints={configDocument.sampling_points}
        readOnly={false}
        onStagesChange={() => {}}
        onSamplingPointsChange={() => {}}
      />,
    );
    expect(screen.getByTestId('admin-panel-process-stages')).toBeInTheDocument();
    expect(screen.getByTestId('admin-process-stages-table')).toBeInTheDocument();
    expect(screen.getByTestId('admin-sampling-points-table')).toBeInTheDocument();
    expect(screen.getByLabelText('stage-id-0')).toHaveValue('intake');
    expect(screen.getByLabelText('sp-id-0')).toHaveValue('SP-01');
    expect(screen.getByLabelText('sp-type-1')).toHaveValue('lab');
  });

  it('is read-only for non-admin roles', () => {
    render(
      <ProcessStagesPanel
        stages={configDocument.process_stages}
        samplingPoints={configDocument.sampling_points}
        readOnly
        onStagesChange={() => {}}
        onSamplingPointsChange={() => {}}
      />,
    );
    expect(screen.getByLabelText('stage-id-0')).toBeDisabled();
    expect(screen.getByLabelText('sp-id-0')).toBeDisabled();
    expect(screen.queryByTestId('admin-panel-process-stages-add')).not.toBeInTheDocument();
    expect(screen.queryByTestId('admin-add-sampling-point')).not.toBeInTheDocument();
  });
});
