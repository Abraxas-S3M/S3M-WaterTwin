import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AlarmThresholdsPanel } from './AlarmThresholdsPanel';
import { configDocument } from '../../test/fixtures';

describe('AlarmThresholdsPanel', () => {
  it('renders alarm threshold rows', () => {
    render(
      <AlarmThresholdsPanel
        rows={configDocument.alarm_thresholds}
        readOnly={false}
        onChange={() => {}}
      />,
    );
    expect(screen.getByTestId('admin-panel-alarm-thresholds')).toBeInTheDocument();
    expect(screen.getByLabelText('alarm-metric-0')).toHaveValue('winding_temp_c');
    expect(screen.getByLabelText('alarm-warn-high-0')).toHaveValue(85);
    expect(screen.getByLabelText('alarm-enabled-0')).toBeChecked();
  });

  it('is read-only for non-admin roles', () => {
    render(
      <AlarmThresholdsPanel rows={configDocument.alarm_thresholds} readOnly onChange={() => {}} />,
    );
    expect(screen.getByLabelText('alarm-metric-0')).toBeDisabled();
    expect(screen.getByLabelText('alarm-enabled-0')).toBeDisabled();
    expect(screen.queryByTestId('admin-panel-alarm-thresholds-add')).not.toBeInTheDocument();
  });
});
