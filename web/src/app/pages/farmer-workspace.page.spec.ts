import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
import { HarvestBatch, MarketplaceService } from '../data/marketplace.service';
import { FarmerWorkspacePage } from './farmer-workspace.page';

const base: HarvestBatch = {
  id: 'rejected-batch-id',
  category: 'category-id',
  quantity: '100.000',
  unit_code: 'kg',
  harvested_on: '2026-11-01',
  client_sync_id: 'original-key',
  notes: 'first try',
  status: 'rejected',
  rejection_reason: 'Quantity looks wrong',
  resubmission_of: null,
  correction_id: null,
  created_at: '2026-11-02T10:00:00Z',
};

describe('FarmerWorkspacePage rejected-batch correction', () => {
  let batches: HarvestBatch[];
  const api = {
    categories: vi.fn(() => of([{ id: 'category-id', name: 'Maize', is_active: true }])),
    harvestBatches: vi.fn(() => of(batches)),
    listings: vi.fn(() => of([])),
    listingStock: vi.fn(),
    createHarvestBatch: vi.fn(),
  };

  function render() {
    const fixture = TestBed.createComponent(FarmerWorkspacePage);
    fixture.detectChanges();
    return fixture;
  }

  beforeEach(() => {
    batches = [{ ...base }];
    api.harvestBatches.mockClear();
    api.createHarvestBatch.mockReset();
    TestBed.configureTestingModule({
      imports: [FarmerWorkspacePage],
      providers: [{ provide: MarketplaceService, useValue: api }, provideRouter([])],
    });
  });

  it('shows the rejection reason and offers a correction on a rejected batch', () => {
    const fixture = render();
    const element: HTMLElement = fixture.nativeElement;

    expect(element.querySelector('[data-testid="rejection-reason"]')?.textContent).toContain(
      'Quantity looks wrong',
    );
    expect(element.querySelector('[data-testid="start-correction"]')).not.toBeNull();
  });

  it('does not offer corrections for accepted, submitted or already-corrected batches', () => {
    batches = [
      { ...base, id: 'a', status: 'accepted', rejection_reason: '' },
      { ...base, id: 's', status: 'submitted', rejection_reason: '' },
      { ...base, id: 'c', correction_id: 'x' },
    ];
    const fixture = render();

    expect(fixture.nativeElement.querySelectorAll('[data-testid="start-correction"]').length).toBe(0);
    const component = fixture.componentInstance;
    component.startCorrection(batches[0]);
    component.startCorrection(batches[2]);
    expect(component.correctingBatchId()).toBe('');
  });

  it('starts a correction with prefilled fields and a NEW operation key', () => {
    const fixture = render();
    const component = fixture.componentInstance;
    const keyBefore = component.batchOperationId();

    component.startCorrection(batches[0]);
    fixture.detectChanges();

    expect(component.correctingBatchId()).toBe('rejected-batch-id');
    expect(component.batchOperationId()).not.toBe(keyBefore);
    expect(component.batchForm.getRawValue().quantity).toBe('100.000');
    expect(fixture.nativeElement.querySelector('[data-testid="correction-banner"]')).not.toBeNull();
  });

  it('submits the correction linked to the original, with a key different from the original', () => {
    api.createHarvestBatch.mockReturnValue(of({ ...base, id: 'new-id', status: 'submitted' }));
    const fixture = render();
    const component = fixture.componentInstance;
    component.startCorrection(batches[0]);
    component.batchForm.patchValue({ quantity: '10' });

    component.submitBatch();

    const payload = api.createHarvestBatch.mock.calls[0][0];
    expect(payload.resubmission_of).toBe('rejected-batch-id');
    expect(payload.quantity).toBe('10');
    expect(payload.client_sync_id).not.toBe('original-key');
    expect(component.correctingBatchId()).toBe('');
    expect(component.message()).toContain('Correction submitted');
  });

  it('reuses the same key when a failed correction is retried', () => {
    api.createHarvestBatch.mockReturnValueOnce(throwError(() => new Error('offline')));
    api.createHarvestBatch.mockReturnValueOnce(of({ ...base, id: 'new-id', status: 'submitted' }));
    const fixture = render();
    const component = fixture.componentInstance;
    component.startCorrection(batches[0]);

    component.submitBatch();
    component.submitBatch();

    const [first, second] = api.createHarvestBatch.mock.calls.map((call) => call[0]);
    expect(second.client_sync_id).toBe(first.client_sync_id);
    expect(second.resubmission_of).toBe('rejected-batch-id');
  });

  it('shows the correction and its own status independently of the original', () => {
    batches = [
      { ...base, correction_id: 'new-id' },
      {
        ...base,
        id: 'new-id',
        status: 'submitted',
        rejection_reason: '',
        resubmission_of: 'rejected-batch-id',
        correction_id: null,
        client_sync_id: 'new-key',
      },
    ];
    const fixture = render();
    const element: HTMLElement = fixture.nativeElement;

    expect(element.querySelector('[data-testid="corrected-by"]')?.textContent).toContain('submitted');
    expect(element.querySelector('[data-testid="correction-of"]')?.textContent).toContain('rejected');
    expect(element.querySelector('[data-testid="start-correction"]')).toBeNull();
  });

  it('cancelling a correction discards the link and issues a fresh key', () => {
    const fixture = render();
    const component = fixture.componentInstance;
    component.startCorrection(batches[0]);
    const correctionKey = component.batchOperationId();

    component.cancelCorrection();

    expect(component.correctingBatchId()).toBe('');
    expect(component.batchOperationId()).not.toBe(correctionKey);
  });
});
