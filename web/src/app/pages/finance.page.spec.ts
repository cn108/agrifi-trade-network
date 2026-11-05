import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { FinanceReport, MarketplaceService } from '../data/marketplace.service';
import { FinancePage } from './finance.page';

describe('FinancePage', () => {
  const report: FinanceReport = {
    simulated: true,
    simulation_label: 'SIMULATED — NO MONEY MOVED',
    trial_balance: {
      accounts: [],
      totals: [{ currency: 'NGN', debit_minor: 10000, credit_minor: 10000, balanced: true }],
    },
    journals: [],
    payments: [{ currency: 'NGN', status: 'simulated_succeeded', count: 2, total_minor: 25000 }],
    refunds: [],
    settlements: [],
  };

  const api = {
    payments: vi.fn(() => of([])),
    refunds: vi.fn(() => of([])),
    settlements: vi.fn(() => of([])),
    ledgerAccounts: vi.fn(() => of([])),
    journals: vi.fn(() => of([])),
    financeReport: vi.fn(() => of(report)),
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [FinancePage],
      providers: [{ provide: MarketplaceService, useValue: api }, provideRouter([])],
    });
  });

  it('shows the API-computed trial balance and record summaries', () => {
    const fixture = TestBed.createComponent(FinancePage);
    fixture.detectChanges();

    const element: HTMLElement = fixture.nativeElement;
    expect(api.financeReport).toHaveBeenCalled();
    expect(element.querySelector('[data-testid="trial-balance"]')?.textContent).toContain('Balanced');
    expect(element.querySelector('[data-testid="report-payments"]')?.textContent).toContain('2 ·');
    expect(element.textContent).toContain('SIMULATED — NO MONEY MOVED');
  });

  it('flags an out-of-balance trial balance', () => {
    api.financeReport.mockReturnValueOnce(
      of({
        ...report,
        trial_balance: {
          accounts: [],
          totals: [{ currency: 'NGN', debit_minor: 2, credit_minor: 1, balanced: false }],
        },
      }),
    );
    const fixture = TestBed.createComponent(FinancePage);
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('OUT OF BALANCE');
  });
});
