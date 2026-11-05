import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { MarketplaceService, HarvestBatch } from '../data/marketplace.service';
import { OperationsPage } from './operations.page';

describe('OperationsPage', () => {
  const batch: HarvestBatch = {
    id: 'batch-id',
    category: 'category-id',
    quantity: '10.000',
    unit_code: 'kg',
    harvested_on: '2026-11-04',
    client_sync_id: 'sync-id',
    notes: '',
    status: 'submitted',
    rejection_reason: '',
    created_at: '2026-11-04T10:00:00Z',
  };

  const api = {
    categories: vi.fn(() => of([])),
    harvestBatches: vi.fn(() => of([batch])),
    operationsListings: vi.fn(() => of([])),
    disputes: vi.fn(() => of([])),
    reviewHarvestBatch: vi.fn(() => of(batch)),
  };

  beforeEach(() => {
    api.categories.mockClear();
    api.harvestBatches.mockClear();
    api.operationsListings.mockClear();
    api.disputes.mockClear();
    api.reviewHarvestBatch.mockClear();
    TestBed.configureTestingModule({
      imports: [OperationsPage],
      providers: [
        { provide: MarketplaceService, useValue: api },
        provideRouter([]),
      ],
    });
  });

  it('explains why a batch cannot be rejected without a reason', () => {
    const fixture = TestBed.createComponent(OperationsPage);
    fixture.detectChanges();

    fixture.componentInstance.reviewBatch(batch, 'reject', '  ');
    fixture.detectChanges();

    expect(api.reviewHarvestBatch).not.toHaveBeenCalled();
    expect(fixture.nativeElement.querySelector('[role="alert"]').textContent).toContain(
      'Enter a rejection reason',
    );
  });

  it('submits the trimmed rejection reason to the API', () => {
    const fixture = TestBed.createComponent(OperationsPage);
    fixture.detectChanges();

    fixture.componentInstance.reviewBatch(batch, 'reject', '  Damaged produce  ');

    expect(api.reviewHarvestBatch).toHaveBeenCalledWith(
      'batch-id',
      'reject',
      'Damaged produce',
    );
    expect(fixture.componentInstance.message()).toBe('Batch rejected.');
  });
});
