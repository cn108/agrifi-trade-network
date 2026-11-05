import { CurrencyPipe, DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { forkJoin, of } from 'rxjs';
import { AuthService } from '../auth/auth.service';
import {
  Dispute,
  FinancialRecord,
  MarketplaceService,
  OrderSummary,
} from '../data/marketplace.service';

@Component({
  imports: [CurrencyPipe, DatePipe, ReactiveFormsModule, RouterLink],
  template: `
    <main class="mx-auto min-h-screen max-w-5xl px-5 py-8 lg:px-8">
      <a class="text-sm font-semibold text-emerald-800 hover:text-emerald-950" routerLink="/orders">← Order history</a>
      @if (errorMessage()) {
        <p class="mt-6 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">{{ errorMessage() }}</p>
      }
      @if (loading()) {
        <p class="mt-8 rounded-2xl bg-white p-8 text-slate-500">Loading order details…</p>
      } @else if (order(); as current) {
        <div class="mt-6 flex flex-wrap items-start justify-between gap-4">
          <div>
            <p class="text-sm font-semibold text-emerald-700">Order details</p>
            <h1 class="mt-1 text-3xl font-semibold tracking-tight text-slate-900">Order {{ current.id.slice(0, 8) }}</h1>
            <p class="mt-2 text-sm text-slate-500">Created {{ current.created_at | date: 'medium' }}</p>
          </div>
          <span class="rounded-full bg-emerald-50 px-4 py-2 text-sm font-semibold capitalize text-emerald-900">{{ current.status }}</span>
        </div>

        @if (successMessage()) {
          <p class="mt-5 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900" role="status">{{ successMessage() }}</p>
        }

        <section class="mt-7 rounded-2xl border border-slate-200 bg-white p-6">
          <h2 class="text-lg font-semibold text-slate-900">Items and server-calculated total</h2>
          <div class="mt-4 divide-y divide-slate-100">
            @for (item of current.items; track item.id) {
              <div class="flex flex-wrap items-center justify-between gap-3 py-4">
                <div>
                  <p class="font-medium text-slate-900">{{ item.listing_name }}</p>
                  <p class="mt-1 text-xs text-slate-500">{{ item.category_name }} · {{ item.quantity }} {{ item.unit_code }} · {{ item.unit_price_minor / 100 | currency: current.currency : 'symbol' : '1.2-2' }} / {{ item.unit_code }}</p>
                </div>
                <p class="font-semibold text-slate-900">{{ item.line_total_minor / 100 | currency: current.currency : 'symbol' : '1.2-2' }}</p>
              </div>
            }
          </div>
          <div class="mt-3 flex justify-between border-t border-slate-200 pt-4 text-lg font-semibold">
            <span>Order total</span>
            <span>{{ current.total_minor / 100 | currency: current.currency : 'symbol' : '1.2-2' }}</span>
          </div>
          <p class="mt-2 text-xs text-slate-500">Final prices and totals are calculated by the server, not the browser.</p>
        </section>

        <section class="mt-5 rounded-2xl border border-slate-200 bg-white p-6">
          <h2 class="text-lg font-semibold text-slate-900">Delivery information</h2>
          <p class="mt-3 whitespace-pre-line text-sm text-slate-700">{{ current.delivery_address }}</p>
          @if (current.notes) { <p class="mt-2 whitespace-pre-line text-sm text-slate-500">{{ current.notes }}</p> }
        </section>

        <section class="mt-5 rounded-2xl border border-slate-200 bg-white p-6">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 class="text-lg font-semibold text-slate-900">Allowed actions</h2>
              <p class="mt-1 text-sm text-slate-500">The API verifies ownership, role and state for every transition.</p>
            </div>
            <div class="flex flex-wrap gap-2">
              @if (canCancel(current)) {
                <button class="secondary-button" [disabled]="working()" (click)="transition(current, 'cancel')">Cancel pending order</button>
              }
              @if (isSeller(current) && current.status === 'pending') {
                <button class="action-button" [disabled]="working()" (click)="transition(current, 'confirm')">Confirm order</button>
              }
              @if (isSeller(current) && current.status === 'confirmed') {
                <button class="action-button" [disabled]="working()" (click)="transition(current, 'ship')">Mark shipped</button>
              }
              @if (isSeller(current) && current.status === 'shipped') {
                <button class="action-button" [disabled]="working()" (click)="transition(current, 'deliver')">Mark delivered</button>
              }
              @if (isBuyer(current) && current.status === 'delivered') {
                <button class="action-button" [disabled]="working()" (click)="transition(current, 'complete')">Confirm delivery</button>
              }
              @if (isBuyer(current) && current.status === 'confirmed' && !hasPayment()) {
                <button class="action-button" [disabled]="working()" (click)="recordSimulatedPayment(current)">Record simulated payment</button>
              }
            </div>
          </div>

          @if (isBuyer(current) && canDispute(current) && !dispute()) {
            <form class="mt-6 grid gap-3 border-t border-slate-100 pt-5 sm:grid-cols-[1fr_auto]" [formGroup]="disputeForm" (ngSubmit)="openDispute(current)">
              <label class="text-sm font-medium text-slate-700">
                Report an order issue
                <textarea class="form-input min-h-20" formControlName="reason" maxlength="2000" placeholder="Describe the issue"></textarea>
              </label>
              <button class="secondary-button self-end" [disabled]="working() || disputeForm.invalid">Open dispute</button>
            </form>
          }

          @if (dispute(); as caseFile) {
            <div class="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-4">
              <div class="flex flex-wrap justify-between gap-2">
                <p class="font-semibold capitalize text-amber-950">Dispute: {{ caseFile.status }}</p>
                @if (caseFile.outcome) { <span class="text-sm capitalize text-amber-900">{{ caseFile.outcome.replace('_', ' ') }}</span> }
              </div>
              <p class="mt-2 text-sm text-amber-950">{{ caseFile.reason }}</p>
              @if (caseFile.resolution_notes) { <p class="mt-2 text-sm text-amber-900">{{ caseFile.resolution_notes }}</p> }
            </div>
          }
        </section>

        <section class="mt-5 rounded-2xl border border-slate-200 bg-white p-6">
          <h2 class="text-lg font-semibold text-slate-900">Status history</h2>
          <ol class="mt-4 space-y-4">
            @for (entry of current.history; track entry.created_at + entry.to_status) {
              <li class="flex gap-3 text-sm">
                <span class="mt-1.5 size-2 shrink-0 rounded-full bg-emerald-700"></span>
                <div><p class="font-medium capitalize text-slate-800">{{ entry.to_status.replace('_', ' ') }}</p>
                  <p class="mt-1 text-xs text-slate-500">{{ entry.created_at | date: 'medium' }}{{ entry.reason ? ' · ' + entry.reason : '' }}</p>
                </div>
              </li>
            }
          </ol>
        </section>
      }
    </main>
  `,
  styles: [`
    .form-input { display: block; width: 100%; margin-top: 0.5rem; border: 1px solid #cbd5e1; border-radius: 0.75rem; background: white; padding: 0.75rem 1rem; outline: none; }
    .form-input:focus { border-color: #047857; box-shadow: 0 0 0 4px rgb(4 120 87 / 10%); }
    .action-button { border-radius: 0.75rem; background: #065f46; padding: 0.65rem 0.9rem; color: white; font-size: 0.875rem; font-weight: 600; }
    .secondary-button { border: 1px solid #cbd5e1; border-radius: 0.75rem; padding: 0.65rem 0.9rem; color: #334155; font-size: 0.875rem; font-weight: 600; }
    button:disabled { opacity: 0.55; }
  `],
})
export class OrderPage implements OnInit {
  private readonly api = inject(MarketplaceService);
  private readonly route = inject(ActivatedRoute);
  private readonly auth = inject(AuthService);
  readonly order = signal<OrderSummary | null>(null);
  readonly dispute = signal<Dispute | null>(null);
  readonly payments = signal<FinancialRecord[]>([]);
  readonly loading = signal(true);
  readonly working = signal(false);
  readonly errorMessage = signal('');
  readonly successMessage = signal('');
  readonly disputeForm = inject(FormBuilder).nonNullable.group({
    reason: ['', [Validators.required, Validators.maxLength(2000)]],
  });
  private paymentOperationId = crypto.randomUUID();

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id');
    if (!id) {
      this.errorMessage.set('Order identifier is missing.');
      this.loading.set(false);
      return;
    }
    const roles = this.auth.user()?.roles ?? [];
    const paymentRequest = roles.includes('buyer') ? this.api.payments() : of([]);
    forkJoin({
      order: this.api.order(id),
      disputes: this.api.disputes(),
      payments: paymentRequest,
    }).subscribe({
      next: ({ order, disputes, payments }) => {
        this.order.set(order);
        this.dispute.set(disputes.find((item) => item.order === order.id) ?? null);
        this.payments.set(payments.filter((payment) => payment.order === order.id));
        this.loading.set(false);
      },
      error: (error: unknown) => {
        this.errorMessage.set(
          error instanceof HttpErrorResponse && error.status === 404
            ? 'This order is not available to your account.'
            : 'Order details could not be loaded.',
        );
        this.loading.set(false);
      },
    });
  }

  isBuyer(order: OrderSummary): boolean {
    return order.buyer === this.auth.user()?.id && (this.auth.user()?.roles.includes('buyer') ?? false);
  }

  isSeller(order: OrderSummary): boolean {
    return order.seller === this.auth.user()?.id && (this.auth.user()?.roles.includes('farmer') ?? false);
  }

  canCancel(order: OrderSummary): boolean {
    return order.status === 'pending' && (this.isBuyer(order) || this.isSeller(order));
  }

  canDispute(order: OrderSummary): boolean {
    return ['confirmed', 'shipped', 'delivered', 'completed'].includes(order.status) && !this.dispute();
  }

  hasPayment(): boolean {
    return this.payments().length > 0;
  }

  transition(order: OrderSummary, action: string): void {
    if (this.working()) return;
    this.working.set(true);
    this.errorMessage.set('');
    this.successMessage.set('');
    const reason = action === 'cancel' ? 'Cancelled by participant' : '';
    this.api.transitionOrder(order.id, action, reason).subscribe({
      next: (updated) => {
        this.order.set(updated);
        this.successMessage.set(`Order ${action} action completed.`);
        this.working.set(false);
      },
      error: (error: unknown) => {
        this.errorMessage.set(
          error instanceof HttpErrorResponse && error.status === 409
            ? 'The order state or required workflow step does not allow this action.'
            : 'The API did not accept this order action.',
        );
        this.working.set(false);
      },
    });
  }

  recordSimulatedPayment(order: OrderSummary): void {
    if (this.working()) return;
    this.working.set(true);
    this.errorMessage.set('');
    this.api.createPayment(order.id, this.paymentOperationId).subscribe({
      next: (payment) => {
        this.paymentOperationId = crypto.randomUUID();
        this.payments.update((items) => [...items, payment]);
        this.successMessage.set('Simulated payment recorded. No real money moved.');
        this.working.set(false);
      },
      error: (error: unknown) => {
        this.errorMessage.set(
          error instanceof HttpErrorResponse && error.status === 409
            ? 'The order is not eligible for simulated payment in its current state.'
            : 'Payment simulation failed. Retry with the same operation key if the result is uncertain.',
        );
        this.working.set(false);
      },
    });
  }

  openDispute(order: OrderSummary): void {
    if (this.disputeForm.invalid || this.working()) {
      this.disputeForm.markAllAsTouched();
      return;
    }
    this.working.set(true);
    this.api.openDispute(order.id, this.disputeForm.controls.reason.value).subscribe({
      next: (dispute) => {
        this.dispute.set(dispute);
        this.order.update((current) => current ? { ...current, status: 'disputed' } : current);
        this.successMessage.set('Dispute submitted for operations review.');
        this.working.set(false);
      },
      error: (error: unknown) => {
        this.errorMessage.set(
          error instanceof HttpErrorResponse && error.status === 409
            ? 'The order already has an active dispute or cannot be disputed in its current state.'
            : 'Dispute could not be submitted.',
        );
        this.working.set(false);
      },
    });
  }
}
