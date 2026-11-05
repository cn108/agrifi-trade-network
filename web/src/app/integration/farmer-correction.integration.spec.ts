import { HttpErrorResponse, HttpInterceptorFn, provideHttpClient, withFetch, withInterceptors } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { environment } from '../../environments/environment';
import { HarvestBatch, MarketplaceService } from '../data/marketplace.service';
import { FarmerWorkspacePage } from '../pages/farmer-workspace.page';

// Opt-in: needs a real Django API (throwaway SQLite database) seeded by
// backend/integration/seed_correction_fixture.py and listening at environment.apiBaseUrl.
// Enable with AGRIFI_INTEGRATION=1. Without it every test here is skipped, never reported as passed.
const enabled = (globalThis as { process?: { env?: Record<string, string> } }).process?.env?.['AGRIFI_INTEGRATION'] === '1';
const PASSWORD = 'pw-test-2026-strong';

let bearer = '';
const posted: { url: string; body: Record<string, unknown> }[] = [];
const authInterceptor: HttpInterceptorFn = (request, next) => {
  if (request.method === 'POST' && request.url.endsWith('/harvest-batches/')) {
    posted.push({ url: request.url, body: request.body as Record<string, unknown> });
  }
  return next(bearer ? request.clone({ setHeaders: { Authorization: `Bearer ${bearer}` } }) : request);
};

async function login(email: string): Promise<string> {
  const response = await fetch(`${environment.apiBaseUrl}/auth/login/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password: PASSWORD }),
  });
  expect(response.status).toBe(200);
  return (await response.json()).access as string;
}

async function until(check: () => boolean, what: string): Promise<void> {
  for (let i = 0; i < 100; i++) {
    if (check()) return;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(`Timed out waiting for ${what}`);
}

async function rejection(promise: Promise<unknown>): Promise<number> {
  try {
    await promise;
  } catch (error) {
    return (error as HttpErrorResponse).status;
  }
  throw new Error('Expected the request to be rejected');
}

describe.skipIf(!enabled)('farmer correction workflow against the real Django API', () => {
  let api: MarketplaceService;
  let farmerToken = '';
  let opsToken = '';

  beforeEach(() => {
    posted.length = 0;
    TestBed.configureTestingModule({
      providers: [provideHttpClient(withFetch(), withInterceptors([authInterceptor])), provideRouter([])],
    });
    api = TestBed.inject(MarketplaceService);
  });

  it('creates a linked correction, keeps the original unchanged and rejects duplicates', async () => {
    farmerToken = await login('it-farmer@example.com');
    opsToken = await login('it-ops@example.com');
    const uid = crypto.randomUUID();

    bearer = farmerToken;
    const category = (await firstValueFrom(api.categories())).find((c) => c.name === 'IT Maize');
    expect(category).toBeDefined();
    const originalKey = crypto.randomUUID();
    const original = await firstValueFrom(
      api.createHarvestBatch({
        category: category!.id,
        quantity: '100.000',
        unit_code: 'kg',
        harvested_on: '2026-11-01',
        client_sync_id: originalKey,
        notes: `original ${uid}`,
      }),
    );
    expect(original.status).toBe('submitted');

    bearer = opsToken;
    const rejected = await firstValueFrom(api.reviewHarvestBatch(original.id, 'reject', 'Quantity looks wrong'));
    expect(rejected.status).toBe('rejected');

    // The real page, wired to the real service and API.
    bearer = farmerToken;
    posted.length = 0;
    const fixture = TestBed.createComponent(FarmerWorkspacePage);
    const element: HTMLElement = fixture.nativeElement;
    fixture.detectChanges();
    const rowFor = (id: string) => element.querySelector(`[data-batch-id="${id}"]`);
    await until(() => {
      fixture.detectChanges();
      return rowFor(original.id) !== null;
    }, 'rejected batch row');

    expect(rowFor(original.id)!.querySelector('[data-testid="rejection-reason"]')?.textContent).toContain(
      'Quantity looks wrong',
    );
    (rowFor(original.id)!.querySelector('[data-testid="start-correction"]') as HTMLButtonElement).click();
    fixture.detectChanges();
    const component = fixture.componentInstance;
    expect(component.correctingBatchId()).toBe(original.id);
    component.batchForm.patchValue({ quantity: '10.000', notes: `corrected ${uid}` });
    component.submitBatch();
    await until(() => component.message() !== '' || component.errorMessage() !== '', 'correction response');
    expect(component.errorMessage()).toBe('');
    expect(component.message()).toContain('Correction submitted');

    // Angular request payload matches the backend contract.
    expect(posted).toHaveLength(1);
    const body = posted[0].body;
    expect(Object.keys(body).sort()).toEqual(
      ['category', 'client_sync_id', 'harvested_on', 'notes', 'quantity', 'resubmission_of', 'unit_code'],
    );
    expect(body['resubmission_of']).toBe(original.id);
    expect(body['client_sync_id']).not.toBe(originalKey);

    // Server state: original untouched, correction linked.
    const batches = await firstValueFrom(api.harvestBatches());
    const find = (id: string) => batches.find((b: HarvestBatch) => b.id === id)!;
    const correction = batches.find((b) => b.resubmission_of === original.id)!;
    expect(correction).toBeDefined();
    const after = find(original.id);
    expect(after.status).toBe('rejected');
    expect(after.quantity).toBe(original.quantity);
    expect(after.notes).toBe(original.notes);
    expect(after.client_sync_id).toBe(originalKey);
    expect(after.rejection_reason).toBe('Quantity looks wrong');
    expect(after.correction_id).toBe(correction.id);
    expect(correction.status).toBe('submitted');
    expect(Number(correction.quantity)).toBe(10);
    expect(correction.client_sync_id).toBe(body['client_sync_id']);

    // UI shows the correction's own status; no further correction is offered.
    await until(() => {
      fixture.detectChanges();
      return rowFor(correction.id) !== null;
    }, 'correction row');
    expect(rowFor(original.id)!.querySelector('[data-testid="corrected-by"]')?.textContent).toContain('submitted');
    expect(rowFor(correction.id)!.querySelector('[data-testid="correction-of"]')?.textContent).toContain('rejected');
    expect(rowFor(original.id)!.querySelector('[data-testid="start-correction"]')).toBeNull();

    // Duplicate submissions: same key replays the same record; no extra rows.
    const countBefore = batches.length;
    const replay = await firstValueFrom(
      api.createHarvestBatch({
        category: category!.id,
        quantity: '10.000',
        unit_code: 'kg',
        harvested_on: String(body['harvested_on']),
        client_sync_id: String(body['client_sync_id']),
        notes: `corrected ${uid}`,
        resubmission_of: original.id,
      }),
    );
    expect(replay.id).toBe(correction.id);

    // A second correction of the same rejected batch with a new key is refused.
    const second = await rejection(
      firstValueFrom(
        api.createHarvestBatch({
          category: category!.id,
          quantity: '11.000',
          unit_code: 'kg',
          harvested_on: '2026-11-01',
          client_sync_id: crypto.randomUUID(),
          notes: 'second',
          resubmission_of: original.id,
        }),
      ),
    );
    expect([400, 409]).toContain(second);

    // Reusing the original's key for a correction conflicts.
    const reused = await rejection(
      firstValueFrom(
        api.createHarvestBatch({
          category: category!.id,
          quantity: '10.000',
          unit_code: 'kg',
          harvested_on: '2026-11-01',
          client_sync_id: originalKey,
          notes: 'reuse',
          resubmission_of: original.id,
        }),
      ),
    );
    expect(reused).toBe(409);

    expect((await firstValueFrom(api.harvestBatches())).length).toBe(countBefore);
  });
});
