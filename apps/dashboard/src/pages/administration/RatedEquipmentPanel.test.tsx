import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { RatedEquipmentPanel } from './RatedEquipmentPanel';
import { configDocument } from '../../test/fixtures';

describe('RatedEquipmentPanel', () => {
  it('renders pump curves and membrane models', () => {
    render(
      <RatedEquipmentPanel
        rows={configDocument.rated_equipment}
        readOnly={false}
        onChange={() => {}}
      />,
    );
    expect(screen.getByTestId('admin-panel-rated-equipment')).toBeInTheDocument();
    // Pump equipment renders a pump-curve editor.
    expect(screen.getByTestId('rated-0-pump-curve')).toBeInTheDocument();
    expect(screen.getByLabelText('rated-0-flow-1')).toHaveValue(500);
    // Membrane equipment renders a membrane-model editor.
    expect(screen.getByTestId('rated-1-membrane-model')).toBeInTheDocument();
    expect(screen.getByLabelText('rated-1-membrane-model-name')).toHaveValue('SW30HRLE-440i');
  });

  it('is read-only for non-admin roles', () => {
    render(
      <RatedEquipmentPanel rows={configDocument.rated_equipment} readOnly onChange={() => {}} />,
    );
    expect(screen.getByLabelText('rated-0-asset')).toBeDisabled();
    expect(screen.queryByTestId('admin-panel-rated-equipment-add')).not.toBeInTheDocument();
  });
});
