import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { environment } from '../../environments/environment';
import { HarvestBatch, MarketplaceService } from '../data/marketplace.service';
import { FarmerWorkspacePage } from '../pages/farmer-workspace.page';
import contract from './harvest-correction.contract.json';

// Runs without a server: the real MarketplaceService/page emit requests that are checked against the
// contract file that the Django test (test_correction_contract.py) also enforces against the real API.
describe('harvest correction contract (Angular side)', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
  });

  it('the real service sends exactly the contract keys for a correction', () => {
    const api = TestBed.inject(MarketplaceService);
    const http = TestBed.inject(HttpTestingController);
    api
      .createHarvestBatch({
        category: 'c', quantity: '1.000', unit_code: 'kg', harvested_on: '2026-11-01',
        client_sync_id: 'k', notes: '', resubmission_of: 'o',
      })
      .subscribe();
    const request = http.expectOne(`${environment.apiBaseUrl}/harvest-batches/`);
    expect(request.request.method).toBe('POST');
    expect(Object.keys(request.request.body).sort()).toEqual([...contract.correction_request_keys].sort());
    request.flush({});
  });

  it('the real service sends exactly the contract keys when rejecting', () => {
    const api = TestBed.inject(MarketplaceService);
    const http = TestBed.inject(HttpTestingController);
    api.reviewHarvestBatch('id', 'reject', 'why').subscribe();
    const request = http.expectOne(`${environment.apiBaseUrl}/harvest-batches/id/reject/`);
    expect(Object.keys(request.request.body).sort()).toEqual([...contract.reject_request_keys].sort());
    request.flush({});
  });

  it('the page submits a correction through the real service with the contract payload', () => {
    const batch: HarvestBatch = {
      id: 'o', category: 'c', quantity: '5.000', unit_code: 'kg', harvested_on: '2026-11-01',
      client_sync_id: 'orig', notes: '', status: 'rejected', rejection_reason: 'bad',
      resubmission_of: null, correction_id: null, created_at: '2026-11-02T10:00:00Z',
    };
    const spy = vi.fn(() => of({ ...batch, id: 'n', status: 'submitted' }));
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      imports: [FarmerWorkspacePage],
      providers: [
        provideRouter([]),
        {
          provide: MarketplaceService,
          useValue: {
            categories: () => of([]), harvestBatches: () => of([batch]), listings: () => of([]),
            createHarvestBatch: spy,
          },
        },
      ],
    });
    const fixture = TestBed.createComponent(FarmerWorkspacePage);
    fixture.detectChanges();
    fixture.componentInstance.startCorrection(batch);
    fixture.componentInstance.submitBatch();
    const sent = (spy.mock.calls[0] as unknown[])[0] as Record<string, unknown>;
    expect(Object.keys(sent).sort()).toEqual([...contract.correction_request_keys].sort());
  });

  it('the HarvestBatch fields the UI reads are listed in the contract', () => {
    const source: HarvestBatch = {
      id: '', category: '', quantity: '', unit_code: '', harvested_on: '', client_sync_id: '', notes: '',
      status: 'submitted', rejection_reason: '', resubmission_of: null, correction_id: null, created_at: '',
    };
    expect(Object.keys(source).sort()).toEqual([...contract.response_keys_read_by_angular].sort());
  });
});
