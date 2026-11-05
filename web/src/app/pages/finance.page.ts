import { CurrencyPipe, DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';
import {
  FinanceReport,
  FinancialRecord,
  JournalEntry,
  LedgerAccount,
  MarketplaceService,
} from '../data/marketplace.service';

@Component({
  imports: [CurrencyPipe, DatePipe, ReactiveFormsModule, RouterLink],
  template: `
    <main class="mx-auto min-h-screen max-w-7xl px-5 py-8 lg:px-8">
      <a class="text-sm font-semibold text-emerald-800 hover:text-emerald-950" routerLink="/">← Dashboard</a>
      <div class="mt-6">
        <p class="text-sm font-semibold text-amber-800">Finance operations</p>
        <h1 class="mt-1 text-3xl font-semibold tracking-tight text-slate-900">Simulated financial records</h1>
      </div>
      <div class="mt-5 rounded-2xl border border-amber-300 bg-amber-50 p-5">
        <p class="font-bold text-amber-950">SIMULATED — NO MONEY MOVED</p>
        <p class="mt-1 text-sm leading-6 text-amber-900">
          These internal records do not charge buyers, hold funds, provide escrow, or transfer/payout
          money. Only eligible completed orders can receive a settlement record. Refund eligibility
          and caps are enforced by the API.
        </p>
      </div>
      @if (message()) {
        <p class="mt-5 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900" role="status">{{ message() }}</p>
      }
      @if (errorMessage()) {
        <p class="mt-5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">{{ errorMessage() }}</p>
      }
      @if (loading()) {
        <p class="mt-8 rounded-2xl bg-white p-8 text-slate-500">Loading finance records…</p>
      } @else {
        <section class="mt-6 grid gap-5 lg:grid-cols-2">
          <article class="rounded-2xl border border-slate-200 bg-white p-6">
            <h2 class="text-lg font-semibold text-slate-900">Record a simulated refund</h2>
            <p class="mt-1 text-sm text-slate-500">Select a payment. The API checks dispute outcome and remaining paid amount.</p>
            <form class="mt-5 space-y-4" [formGroup]="refundForm" (ngSubmit)="createRefund()">
              <label class="block text-sm font-medium text-slate-700">
                Simulated payment
                <select class="form-input" formControlName="payment">
                  <option value="">Select payment</option>
                  @for (payment of payments(); track payment.id) {
                    <option [value]="payment.id">{{ payment.id.slice(0, 8) }} · {{ payment.amount_minor / 100 | currency: payment.currency : 'symbol' : '1.2-2' }}</option>
                  }
                </select>
              </label>
              <label class="block text-sm font-medium text-slate-700">
                Amount (integer kobo)
                <input class="form-input" formControlName="amount_minor" min="1" step="1" type="number" />
              </label>
              <label class="block text-sm font-medium text-slate-700">
                Reason
                <textarea class="form-input min-h-20" formControlName="reason" maxlength="1000"></textarea>
              </label>
              <button class="action-button" [disabled]="refundForm.invalid || working()">
                {{ working() ? 'Submitting…' : 'Record simulated refund' }}
              </button>
            </form>
          </article>

          <article class="rounded-2xl border border-slate-200 bg-white p-6">
            <h2 class="text-lg font-semibold text-slate-900">Record a simulated settlement</h2>
            <p class="mt-1 text-sm text-slate-500">Choose a paid order. The API requires completion and nets prior refunds.</p>
            <form class="mt-5 space-y-4" [formGroup]="settlementForm" (ngSubmit)="createSettlement()">
              <label class="block text-sm font-medium text-slate-700">
                Order from simulated payments
                <select class="form-input" formControlName="order">
                  <option value="">Select order</option>
                  @for (payment of payments(); track payment.id) {
                    @if (payment.order) {
                      <option [value]="payment.order">Order {{ payment.order.slice(0, 8) }} · Payment {{ payment.id.slice(0, 8) }}</option>
                    }
                  }
                </select>
              </label>
              <p class="rounded-lg bg-slate-50 p-3 text-xs leading-5 text-slate-600">
                This creates an internal ledger record only. It does not pay the seller.
              </p>
              <button class="action-button" [disabled]="settlementForm.invalid || working()">
                {{ working() ? 'Submitting…' : 'Record simulated settlement' }}
              </button>
            </form>
          </article>
        </section>

        <section class="mt-6 grid gap-5 xl:grid-cols-3">
          @for (group of recordGroups(); track group.title) {
            <article class="rounded-2xl border border-slate-200 bg-white p-5">
              <h2 class="font-semibold text-slate-900">{{ group.title }}</h2>
              <div class="mt-3 divide-y divide-slate-100">
                @for (record of group.records; track record.id) {
                  <div class="py-3">
                    <p class="text-sm font-medium capitalize text-slate-800">{{ record.id.slice(0, 8) }} · {{ record.status.replace('_', ' ') }}</p>
                    <p class="mt-1 text-sm font-semibold text-slate-900">
                      {{ record.amount_minor / 100 | currency: record.currency : 'symbol' : '1.2-2' }}
                    </p>
                    <p class="mt-1 text-[0.7rem] text-amber-800">{{ record.simulation_label }}</p>
                  </div>
                }
                @if (!group.records.length) { <p class="py-3 text-sm text-slate-500">No records.</p> }
              </div>
            </article>
          }
        </section>

        <section class="mt-6 rounded-2xl border border-slate-200 bg-white p-6" aria-label="Finance report">
          <h2 class="text-lg font-semibold text-slate-900">Finance report (simulated)</h2>
          @if (report(); as r) {
            <p class="mt-1 text-sm text-slate-500">Trial balance totals and record summaries, computed by the API from the immutable journal.</p>
            <div class="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              @for (total of r.trial_balance.totals; track total.currency) {
                <div class="rounded-xl bg-slate-50 p-4" data-testid="trial-balance">
                  <p class="text-xs font-semibold uppercase text-slate-500">Trial balance {{ total.currency }}</p>
                  <p class="mt-1 text-sm">Debits {{ total.debit_minor / 100 | currency: total.currency : 'symbol' : '1.2-2' }}</p>
                  <p class="text-sm">Credits {{ total.credit_minor / 100 | currency: total.currency : 'symbol' : '1.2-2' }}</p>
                  <p class="mt-1 text-sm font-semibold" [class.text-red-700]="!total.balanced">{{ total.balanced ? 'Balanced' : 'OUT OF BALANCE' }}</p>
                </div>
              }
              @for (group of reportGroups(); track group.title) {
                <div class="rounded-xl bg-slate-50 p-4" [attr.data-testid]="'report-' + group.title.toLowerCase()">
                  <p class="text-xs font-semibold uppercase text-slate-500">{{ group.title }}</p>
                  @for (row of group.rows; track row.currency + (row.status ?? '')) {
                    <p class="mt-1 text-sm">{{ row.count }} · {{ row.total_minor / 100 | currency: row.currency : 'symbol' : '1.2-2' }}</p>
                  }
                  @if (!group.rows.length) { <p class="mt-1 text-sm text-slate-500">None.</p> }
                </div>
              }
            </div>
          } @else {
            <p class="mt-2 text-sm text-slate-500">Report unavailable.</p>
          }
        </section>

        <section class="mt-6 grid gap-5 lg:grid-cols-2">
          <article class="rounded-2xl border border-slate-200 bg-white p-6">
            <h2 class="text-lg font-semibold text-slate-900">Derived account balances</h2>
            <p class="mt-1 text-sm text-slate-500">Calculated from the posted simulated journal lines.</p>
            <div class="mt-4 divide-y divide-slate-100">
              @for (account of accounts(); track account.code) {
                <div class="flex justify-between gap-3 py-3 text-sm">
                  <span>{{ account.name }} <span class="text-xs text-slate-400">{{ account.code }}</span></span>
                  <strong>{{ account.debit_balance_minor / 100 | currency: account.currency : 'symbol' : '1.2-2' }}</strong>
                </div>
              }
            </div>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-white p-6">
            <h2 class="text-lg font-semibold text-slate-900">Posted journal entries</h2>
            <div class="mt-4 max-h-80 divide-y divide-slate-100 overflow-auto">
              @for (journal of journals(); track journal.id) {
                <div class="py-3">
                  <div class="flex justify-between gap-2">
                    <p class="font-medium text-slate-800">{{ journal.reference }}</p>
                    <p class="text-xs text-slate-500">{{ journal.posted_at | date: 'short' }}</p>
                  </div>
                  <p class="mt-1 text-xs text-slate-500">{{ journal.memo }}</p>
                  <p class="mt-1 text-sm font-semibold text-slate-700">
                    {{ journal.debit_total_minor / 100 | currency: journal.currency : 'symbol' : '1.2-2' }}
                    · {{ journal.source_type }} / {{ journal.kind }}
                  </p>
                </div>
              }
              @if (!journals().length) { <p class="py-3 text-sm text-slate-500">No journals posted.</p> }
            </div>
          </article>
        </section>
      }
    </main>
  `,
  styles: [`
    .form-input { display: block; width: 100%; margin-top: 0.5rem; border: 1px solid #cbd5e1; border-radius: 0.75rem; background: white; padding: 0.75rem 1rem; outline: none; }
    .form-input:focus { border-color: #047857; box-shadow: 0 0 0 4px rgb(4 120 87 / 10%); }
    .action-button { border-radius: 0.75rem; background: #065f46; padding: 0.7rem 1rem; color: white; font-weight: 600; }
    .action-button:disabled { opacity: 0.55; }
  `],
})
export class FinancePage implements OnInit {
  private readonly api = inject(MarketplaceService);
  readonly payments = signal<FinancialRecord[]>([]);
  readonly refunds = signal<FinancialRecord[]>([]);
  readonly settlements = signal<FinancialRecord[]>([]);
  readonly accounts = signal<LedgerAccount[]>([]);
  readonly journals = signal<JournalEntry[]>([]);
  readonly report = signal<FinanceReport | null>(null);
  readonly reportGroups = computed(() => {
    const report = this.report();
    return report
      ? [
          { title: 'Payments', rows: report.payments },
          { title: 'Refunds', rows: report.refunds },
          { title: 'Settlements', rows: report.settlements },
        ]
      : [];
  });
  readonly loading = signal(true);
  readonly working = signal(false);
  readonly message = signal('');
  readonly errorMessage = signal('');
  private refundKey = crypto.randomUUID();
  private settlementKey = crypto.randomUUID();
  readonly refundForm = inject(FormBuilder).nonNullable.group({
    payment: ['', Validators.required],
    amount_minor: [1, [Validators.required, Validators.min(1)]],
    reason: ['', [Validators.required, Validators.maxLength(1000)]],
  });
  readonly settlementForm = inject(FormBuilder).nonNullable.group({
    order: ['', Validators.required],
  });

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    forkJoin({
      payments: this.api.payments(),
      refunds: this.api.refunds(),
      settlements: this.api.settlements(),
      accounts: this.api.ledgerAccounts(),
      journals: this.api.journals(),
      report: this.api.financeReport(),
    }).subscribe({
      next: (data) => {
        this.report.set(data.report);
        this.payments.set(data.payments);
        this.refunds.set(data.refunds);
        this.settlements.set(data.settlements);
        this.accounts.set(data.accounts);
        this.journals.set(data.journals);
        this.loading.set(false);
      },
      error: (error: unknown) => {
        this.errorMessage.set(
          error instanceof HttpErrorResponse && error.status === 403
            ? 'The API denied finance operator access.'
            : 'Finance records could not be loaded.',
        );
        this.loading.set(false);
      },
    });
  }

  createRefund(): void {
    if (this.refundForm.invalid || this.working()) return;
    const data = this.refundForm.getRawValue();
    this.working.set(true);
    this.errorMessage.set('');
    this.api.createRefund(data.payment, data.amount_minor, data.reason, this.refundKey).subscribe({
      next: () => {
        this.refundKey = crypto.randomUUID();
        this.message.set('Simulated refund record created. No money moved.');
        this.refundForm.reset({ payment: '', amount_minor: 1, reason: '' });
        this.working.set(false);
        this.load();
      },
      error: (error: unknown) => this.fail(error, 'Simulated refund could not be recorded.'),
    });
  }

  createSettlement(): void {
    if (this.settlementForm.invalid || this.working()) return;
    this.working.set(true);
    this.errorMessage.set('');
    this.api.createSettlement(this.settlementForm.controls.order.value, this.settlementKey).subscribe({
      next: () => {
        this.settlementKey = crypto.randomUUID();
        this.message.set('Simulated settlement record created. No payout was made.');
        this.settlementForm.reset({ order: '' });
        this.working.set(false);
        this.load();
      },
      error: (error: unknown) => this.fail(error, 'Order is not eligible for simulated settlement.'),
    });
  }

  recordGroups(): Array<{ title: string; records: FinancialRecord[] }> {
    return [
      { title: 'Simulated payments', records: this.payments() },
      { title: 'Simulated refunds', records: this.refunds() },
      { title: 'Simulated settlements', records: this.settlements() },
    ];
  }

  private fail(error: unknown, fallback: string): void {
    this.errorMessage.set(
      error instanceof HttpErrorResponse && error.status === 409
        ? 'The operation conflicts with current eligibility or record state. The same request key is retained for safe retry.'
        : fallback,
    );
    this.working.set(false);
  }
}
